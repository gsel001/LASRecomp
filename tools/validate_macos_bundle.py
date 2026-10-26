#!/usr/bin/env python3
"""Check a signed macOS app's declared-library imports without starting its executables.

Uses the installed Xcode dyld_info and otool; Python standard library only. Checks every
bundled executable and its linked non-system closure, including whole-library and
symbol-specific re-exports. Flat/dynamic lookup and system-cache imports are counted
separately, not claimed as validated. Libraries opened only through dlopen are outside
this static check; codesign still verifies the complete bundle.
"""
import argparse
from dataclasses import dataclass
import json
import plistlib
from pathlib import Path
import re
import struct
import subprocess
from xml.parsers.expat import ExpatError

class Invalid(RuntimeError):
    pass

def run(*args):
    try:
        return subprocess.check_output(list(map(str, args)), text=True, stderr=subprocess.PIPE, timeout=120)
    except subprocess.TimeoutExpired as exc:
        raise Invalid('Tool timed out: '+str(args[0])) from exc
    except subprocess.CalledProcessError as exc:
        raise Invalid(exc.stderr.strip() or str(exc)) from exc

def system(path):
    return path.startswith(('/usr/lib/', '/System/'))

def executable(path):
    """Recognize MH_EXECUTE, including a universal image, without running file contents."""
    with path.open('rb') as stream:
        header = stream.read(32)
        if len(header) < 16:
            return False
        magic = header[:4]
        if magic in (b'\xca\xfe\xba\xbe', b'\xca\xfe\xba\xbf'):
            wide = magic[-1] == 0xbf
            offset = struct.unpack_from('>Q' if wide else '>I', header, 16)[0]
            stream.seek(offset)
            header = stream.read(16)
            magic = header[:4]
        endian = {b'\xcf\xfa\xed\xfe': '<', b'\xfe\xed\xfa\xcf': '>',
                  b'\xce\xfa\xed\xfe': '<', b'\xfe\xed\xfa\xce': '>'}.get(magic)
        return bool(endian and len(header) >= 16 and struct.unpack_from(endian+'I', header, 12)[0] == 2)

@dataclass(frozen=True)
class Dependency:
    path: str
    weak: bool = False
    reexport: bool = False

def load_commands(text):
    dependencies, rpaths = [], []
    for block in re.split(r'(?m)^Load command \d+\n', text):
        cmd = re.search(r'(?m)^\s*cmd (LC_\S+)', block)
        if not cmd:
            continue
        cmd = cmd[1]
        if cmd in ('LC_LOAD_DYLIB', 'LC_LOAD_WEAK_DYLIB', 'LC_REEXPORT_DYLIB', 'LC_LOAD_UPWARD_DYLIB'):
            name = re.search(r'(?m)^\s*name (.+) \(offset \d+\)', block)
            if not name:
                raise Invalid('Unrecognized dylib load command')
            dependencies.append(Dependency(name[1], cmd == 'LC_LOAD_WEAK_DYLIB', cmd == 'LC_REEXPORT_DYLIB'))
        elif cmd == 'LC_RPATH':
            name = re.search(r'(?m)^\s*path (.+) \(offset \d+\)', block)
            if not name:
                raise Invalid('Unrecognized rpath command')
            rpaths.append(name[1])
    return dependencies, rpaths

def imports(text):
    result = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.endswith(':') or line.startswith(('symbol', 'offset')):
            continue
        match = re.fullmatch(r'(?:0x[0-9a-fA-F]+\s+)?(\S+)\s+(\[weak-import\]\s+)?\(from ([^)]+)\)(.*)', line)
        if not match:
            raise Invalid('Unrecognized dyld_info import: '+line)
        provider = match[3]
        if match[4].strip() not in ('', '[weak-import]'):
            raise Invalid('Unrecognized import attributes: '+line)
        weak = bool(match[2]) or match[4].strip() == '[weak-import]' or provider.endswith(', weak-import')
        provider = provider.removesuffix(', weak-import')
        result.append((match[1], provider, weak))
    return result

def exports(text):
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.endswith(':') or line.startswith(('offset', 'symbol')):
            continue
        if line.startswith('[re-export]'):
            match = re.fullmatch(r'\[re-export\]\s+(\S+)\s+\((?:(\S+) )?from ([^)]+)\)', line)
            if not match:
                raise Invalid('Unrecognized symbol re-export: '+line)
            result[match[1]] = (match[3], match[2] or match[1])
        else:
            match = re.match(r'0x[0-9a-fA-F]+\s+(?:\[[^]]+\]\s+)*(\S+)', line)
            if not match:
                raise Invalid('Unrecognized dyld_info export: '+line)
            result[match[1]] = None
    return result

def provider(dependencies, label):
    exact = [d for d in dependencies if Path(d.path).name.removesuffix('.dylib') == label]
    if not exact:
        # dyld_info can print libSDL3 for the load command libSDL3.0.dylib.
        exact = [d for d in dependencies if re.sub(r'(?:\.(?:\d+|[A-Z]))+$', '', Path(d.path).name.removesuffix('.dylib')) == label]
    if len(exact) != 1:
        raise Invalid('Cannot uniquely map declared provider '+label)
    return exact[0]

class Validator:
    def __init__(self, bundle):
        self.bundle = Path(bundle).resolve()
        self.cache = {}
        self.counts = dict(executables=0, image_architectures=0, imports_checked=0,
                           system_imports=0, dynamic_lookup_imports=0, optional_missing=0)

    def image(self, path, arch):
        key = path, arch
        if key not in self.cache:
            deps, paths = load_commands(run('otool', '-arch', arch, '-l', path))
            self.cache[key] = (deps, paths, imports(run('xcrun', 'dyld_info', '-arch', arch, '-imports', path)),
                               exports(run('xcrun', 'dyld_info', '-arch', arch, '-exports', path)))
        return self.cache[key]

    def expanded(self, value, loader, root):
        if value == '@loader_path':
            return loader.parent
        if value == '@executable_path':
            return root.parent
        if value.startswith('@loader_path/'):
            return loader.parent / value[len('@loader_path/'):]
        if value.startswith('@executable_path/'):
            return root.parent / value[len('@executable_path/'):]
        if value.startswith('/'):
            return Path(value)
        raise Invalid('Unsupported relative loader path '+value)

    def graph(self, root, arch):
        nodes = {}
        def visit(path, inherited):
            path = path.resolve()
            if path in nodes:
                return
            if not path.is_relative_to(self.bundle):
                raise Invalid('Non-system dependency escapes bundle: '+str(path))
            arches = run('lipo', '-archs', path).split()
            if arch not in arches:
                raise Invalid('Missing '+arch+' slice: '+str(path))
            deps, paths, bindings, symbols = self.image(path, arch)
            search = tuple(dict.fromkeys([self.expanded(p, path, root).resolve() for p in paths] + list(inherited)))
            children = {}
            nodes[path] = (deps, bindings, symbols, children)
            for dep in deps:
                if system(dep.path):
                    continue
                if dep.path.startswith('@rpath/'):
                    candidates = [p / dep.path[len('@rpath/'):] for p in search]
                else:
                    candidates = [self.expanded(dep.path, path, root)]
                target = next((p.resolve() for p in candidates if p.is_file()), None)
                if target is None:
                    if dep.weak:
                        children[dep] = None
                        continue
                    raise Invalid('Missing bundled dependency '+dep.path+' required by '+str(path))
                children[dep] = target
                visit(target, search)
        visit(root, ())
        return nodes

    def validate_root(self, root, arch):
        nodes = self.graph(root, arch)
        def available(path, symbol, seen=frozenset()):
            if (path, symbol) in seen:
                return False
            seen = seen | {(path, symbol)}
            deps, _, symbols, children = nodes[path]
            if symbol in symbols:
                target = symbols[symbol]
                if target is None:
                    return True
                dep = provider(deps, target[0])
                if system(dep.path):
                    raise Invalid('Cannot verify non-system symbol re-export through system cache: '+symbol)
                child = children.get(dep)
                return child is not None and available(child, target[1], seen)
            return any(children.get(d) is not None and available(children[d], symbol, seen)
                       for d in deps if d.reexport and not system(d.path))
        for path, (deps, bindings, _, children) in nodes.items():
            self.counts['image_architectures'] += 1
            for symbol, label, weak in bindings:
                if label in ('flat-namespace', 'flat namespace', 'main-executable', 'weak-defs', '<weak-def-coalesce>', '<flat-namespace>', '<main-executable>'):
                    self.counts['dynamic_lookup_imports'] += 1
                    continue
                dep = provider(deps, label)
                if system(dep.path):
                    self.counts['system_imports'] += 1
                    continue
                child = children.get(dep)
                if child is None or not available(child, symbol):
                    if weak:
                        self.counts['optional_missing'] += 1
                        continue
                    raise Invalid(f'{path.relative_to(self.bundle)} [{arch}]: {symbol} missing from declared provider {dep.path}')
                self.counts['imports_checked'] += 1

    def validate(self, signature=True):
        info = self.bundle/'Contents/Info.plist'
        if not info.is_file():
            raise Invalid('Expected an app bundle with Contents/Info.plist')
        with info.open('rb') as stream:
            name = plistlib.load(stream).get('CFBundleExecutable')
        if not isinstance(name, str) or not name or Path(name).name != name or name in ('.', '..'):
            raise Invalid('Invalid CFBundleExecutable')
        main = self.bundle/'Contents/MacOS'/name
        if not main.is_file() or not executable(main):
            raise Invalid('Missing primary Mach-O executable')
        roots = sorted(p for p in self.bundle.rglob('*') if p.is_file() and executable(p))
        if not roots:
            raise Invalid('No Mach-O executables found')
        for root in roots:
            self.counts['executables'] += 1
            for arch in run('lipo', '-archs', root).split():
                self.validate_root(root.resolve(), arch)
        if signature:
            run('codesign', '--verify', '--deep', '--strict', self.bundle)
        return self.counts

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    try:
        counts = Validator(args.bundle).validate()
    except (Invalid, OSError, ValueError, plistlib.InvalidFileException, ExpatError) as error:
        parser.exit(1, 'Bundle validation failed: '+str(error)+'\n')
    print('Bundle imports and strict/deep signature verified: '+json.dumps(counts, sort_keys=True))

if __name__ == '__main__':
    main()
