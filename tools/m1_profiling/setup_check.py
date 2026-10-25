#!/usr/bin/env python3
"""Verify the packaged dependency manifest; optionally exercise fixture-only preflight."""
import argparse,hashlib,json,subprocess,sys
from pathlib import Path

def verify(root):
 root=Path(root);manifest=json.loads((root/'DEPENDENCIES.json').read_text())
 if manifest.get('schema')!=1 or not isinstance(manifest.get('files'),dict):raise ValueError('Invalid dependency manifest.')
 for name,expected in manifest['files'].items():
  if Path(name).name!=name:raise ValueError('Invalid dependency name.')
  p=root/name
  if not p.is_file() or p.is_symlink() or hashlib.sha256(p.read_bytes()).hexdigest()!=expected:
   raise ValueError('Packaged dependency missing or changed: '+name)
 return manifest

def main():
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--fixture-dry-run',action='store_true');args=parser.parse_args()
 root=Path(__file__).resolve().parent;verify(root)
 if args.fixture_dry_run:
  subprocess.run([sys.executable,'-B',str(root/'test_profiling.py'),'Tests.test_preflight_fixture_success','Tests.test_dry_run_never_launches','Tests.test_private_isolation_all_scenarios'],check=True,timeout=30)
  print('FIXTURE DRY-RUN PASSED; no real checkout, tools, game or saves used.')
 else:print('Packaged dependencies verified; no game launched.')
if __name__=='__main__':
 try:main()
 except (OSError,ValueError,subprocess.SubprocessError) as error:sys.exit(f'Setup verification failed: {error}')
