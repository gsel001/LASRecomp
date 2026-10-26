#!/usr/bin/env python3
"""Packaging regression: synthetic C libraries only, no game files or game execution."""
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import validate_macos_bundle as v

class ParsingTests(unittest.TestCase):
    def test_import_formats(self):
        self.assertEqual(v.imports('x [arm64]:\n -imports:\n 0x001 _foo (from libA)\n _bar [weak-import] (from libB)\n'), [('_foo','libA',False),('_bar','libB',True)])
    def test_unrecognized_import_fails_closed(self):
        with self.assertRaises(v.Invalid):v.imports('changed tool output')
    def test_direct_and_specific_reexports(self):
        self.assertEqual(v.exports('x [arm64]:\n -exports:\n offset symbol\n 0x1234 _foo\n [re-export] _bar (from libA)\n [re-export] _alias (_original from libA)\n'), {'_foo':None,'_bar':('libA','_bar'),'_alias':('libA','_original')})
    def test_bad_reexport_fails_closed(self):
        with self.assertRaises(v.Invalid):v.exports('[re-export] unknown syntax')
    def test_declared_provider_not_global_pool(self):
        ds=[v.Dependency('@rpath/libavcodec.63.dylib'),v.Dependency('@rpath/libavutil.61.dylib')]
        self.assertEqual(v.provider(ds,'libavcodec.63'),ds[0])
    def test_short_provider_aliases(self):
        self.assertEqual(v.provider([v.Dependency('/usr/lib/libSystem.B.dylib')],'libSystem').path,'/usr/lib/libSystem.B.dylib')
    def test_ambiguous_short_alias_rejected(self):
        with self.assertRaises(v.Invalid):v.provider([v.Dependency('@rpath/libA.1.dylib'),v.Dependency('@rpath/libA.2.dylib')],'libA')
    def test_unknown_provider_rejected(self):
        with self.assertRaises(v.Invalid):v.provider([],'libA')
    def test_load_command_types(self):
        text='Load command 0\n cmd LC_REEXPORT_DYLIB\n name @rpath/libA.dylib (offset 24)\nLoad command 1\n cmd LC_LOAD_WEAK_DYLIB\n name @rpath/libB.dylib (offset 24)\nLoad command 2\n cmd LC_RPATH\n path @loader_path (offset 12)\n'
        ds,rs=v.load_commands(text);self.assertTrue(ds[0].reexport);self.assertTrue(ds[1].weak);self.assertEqual(rs,['@loader_path'])
    def test_malformed_load_command_rejected(self):
        with self.assertRaises(v.Invalid):v.load_commands('Load command 0\n cmd LC_LOAD_DYLIB\n')
    def test_loader_and_executable_paths(self):
        x=v.Validator('/tmp/Fixture.app');self.assertEqual(x.expanded('@loader_path',Path('/a/lib'),Path('/b/exe')),Path('/a'));self.assertEqual(x.expanded('@executable_path/../Frameworks',Path('/a/lib'),Path('/b/MacOS/exe')),Path('/b/MacOS/../Frameworks'))
    def test_relative_loader_path_rejected(self):
        with self.assertRaises(v.Invalid):v.Validator('/tmp/Fixture.app').expanded('libA.dylib',Path('/a/lib'),Path('/a/exe'))
    def test_executable_magic_and_fat(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'binary';thin=struct.pack('<IIII',0xfeedfacf,0,0,2);p.write_bytes(thin);self.assertTrue(v.executable(p));p.write_bytes(struct.pack('>IIIIII',0xcafebabe,1,0,0,32,16)+b'\0'*8+thin);self.assertTrue(v.executable(p));p.write_bytes(b'not a MachO image');self.assertFalse(v.executable(p))
    def test_reexport_cycle_is_bounded(self):
        a,b=Path('/fixture/a'),Path('/fixture/b');da=v.Dependency('@rpath/b.dylib',reexport=True);db=v.Dependency('@rpath/a.dylib',reexport=True)
        nodes={a:([da],[('_missing','b',False)],{},{da:b}),b:([db],[],{},{db:a})};x=v.Validator('/fixture')
        with patch.object(x,'graph',return_value=nodes),self.assertRaises(v.Invalid):x.validate_root(a,'arm64')
    def test_symbol_specific_reexport_alias(self):
        a,b,c=map(Path,['/fixture/a','/fixture/b','/fixture/c']);db=v.Dependency('@rpath/b.dylib');dc=v.Dependency('@rpath/c.dylib');nodes={a:([db],[('_alias','b',False)],{},{db:b}),b:([dc],[],{'_alias':('c','_real')},{dc:c}),c:([],[],{'_real':None},{})};x=v.Validator('/fixture')
        with patch.object(x,'graph',return_value=nodes):x.validate_root(a,'arm64')
        self.assertEqual(x.counts['imports_checked'],1)
    def test_weak_and_dynamic_lookup_not_claimed_as_resolved(self):
        a,b=Path('/fixture/a'),Path('/fixture/b');db=v.Dependency('@rpath/b.dylib');nodes={a:([db],[('_optional','b',True),('_python','flat-namespace',False)],{},{db:b}),b:([],[],{},{})};x=v.Validator('/fixture')
        with patch.object(x,'graph',return_value=nodes):x.validate_root(a,'arm64')
        self.assertEqual(x.counts['optional_missing'],1);self.assertEqual(x.counts['dynamic_lookup_imports'],1);self.assertEqual(x.counts['imports_checked'],0)

@unittest.skipUnless(sys.platform=='darwin','requires installed Apple linker/dyld_info')
class NativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory(prefix='macos-bundle-test-');cls.base=Path(cls.temp.name);cls.host=v.run('uname','-m').strip();cls.lib=cls.base/'reference';cls.lib.mkdir()
        def build(name,source,extra=()):
            p=cls.base/(name+'.c');p.write_text(source);out=cls.lib/name
            v.run('xcrun','clang','-dynamiclib',p,'-Wl,-install_name,@rpath/'+name,*extra,'-o',out)
            return out
        util=build('libavutil.61.dylib','int av_frame_clone(void){return 7;}')
        cls.oldcodec=build('old-codec.dylib','int codec_marker(void){return 1;}')
        v.run('install_name_tool','-id','@rpath/libavcodec.63.dylib',cls.oldcodec)
        exports=cls.base/'reexports.txt';exports.write_text('_av_frame_clone\n')
        cls.codec=build('libavcodec.63.dylib','int codec_marker(void){return 1;}',(str(util),'-Wl,-reexported_symbols_list,'+str(exports)))
        cls.whole=build('whole-codec.dylib','int codec_marker(void){return 1;}',('-Wl,-reexport_library,'+str(util),));v.run('install_name_tool','-id','@rpath/libavcodec.63.dylib',cls.whole)
        sdl=build('libSDL3.0.dylib','int SDL_PackagingProbe(void){return 2;}')
        source=cls.base/'main.c';source.write_text('extern int av_frame_clone(void),codec_marker(void),SDL_PackagingProbe(void);int main(void){return av_frame_clone()+codec_marker()+SDL_PackagingProbe()!=10;}')
        cls.bad=cls.base/'bad';cls.good=cls.base/'good'
        for exe,codec in [(cls.bad,cls.codec),(cls.good,cls.oldcodec)]:v.run('xcrun','clang',source,codec,util,sdl,'-Wl,-rpath,@executable_path/../Frameworks','-Wl,-headerpad_max_install_names','-o',exe)
    @classmethod
    def tearDownClass(cls):cls.temp.cleanup()
    def setUp(self):
        self.case=tempfile.TemporaryDirectory(dir=self.base);self.addCleanup(self.case.cleanup);self.app=Path(self.case.name)/'Fixture.app';self.c=self.app/'Contents';(self.c/'MacOS').mkdir(parents=True);(self.c/'Frameworks').mkdir();self.exe=self.c/'MacOS/probe';shutil.copy2(self.bad,self.exe)
        for n in ['libavutil.61.dylib','libSDL3.0.dylib']:shutil.copy2(self.lib/n,self.c/'Frameworks'/n)
        shutil.copy2(self.oldcodec,self.c/'Frameworks/libavcodec.63.dylib');(self.c/'Info.plist').write_bytes(plistlib.dumps({'CFBundleIdentifier':'org.example.bundle-test','CFBundleExecutable':'probe','CFBundlePackageType':'APPL'}))
    def validate(self):return v.Validator(self.app).validate(signature=False)
    def package(self):
        project=Path(self.case.name)/'project';(project/'tools').mkdir(parents=True)
        for name in ['bundle_macos.sh','validate_macos_bundle.py']:shutil.copy2(Path(v.__file__).parent/name,project/'tools'/name)
        files={'runtime/paths.h':'#define RT_BUNDLE_ID "org.example.bundle-test"\n',
               'runtime/ui/launcher.mm':'#define LARECOMP_VERSION "test-packaging"\n'}
        for name in ['runtime/cpu.h','runtime/simd.h','runtime/simd_fp.h','runtime/gamelib.h','tools/gamelib_entry.c','runtime/hle/hle_symbols.txt','docs/icon/icon.icns','docs/icon/icon_1024.png','third_party/fonts/Baloo2/Baloo2-SemiBold.ttf','third_party/fonts/Baloo2/OFL.txt','third_party/fonts/DejaVu/DejaVuSans.ttf','third_party/fonts/DejaVu/DejaVuSans-Bold.ttf','third_party/fonts/DejaVu/LICENSE']:files[name]='synthetic packaging fixture\n'
        for name,content in files.items():
            path=project/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(content)
        source=project/'helper.c';source.write_text('int main(void){return 0;}')
        for name in ['build/helper/lasgen/lasgen','build/zig/zig']:
            path=project/name;path.parent.mkdir(parents=True,exist_ok=True);v.run('xcrun','clang',source,'-o',path)
        output=Path(self.case.name)/'Disposable package.app'
        result=subprocess.run(['bash',str(project/'tools/bundle_macos.sh'),str(self.exe),str(output)],cwd=project,text=True,capture_output=True)
        return result,output
    def test_fresh_packaging_corrected_provider_and_source_rpaths(self):
        shutil.copy2(self.good,self.exe);result,output=self.package();self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertEqual(v.Validator(output).validate()['imports_checked'],3)
    def test_fresh_packaging_honors_source_loader_rpath(self):
        shutil.copy2(self.good,self.exe);v.run('install_name_tool','-rpath','@executable_path/../Frameworks','@loader_path/../Frameworks',self.exe)
        result,output=self.package();self.assertEqual(result.returncode,0,result.stdout+result.stderr)
    def test_fresh_packaging_rejects_original_mismatch(self):
        result,output=self.package();self.assertNotEqual(result.returncode,0);self.assertIn('_av_frame_clone missing from declared provider',result.stderr)
    def test_packaging_rejects_conflicting_library_basename(self):
        shutil.copy2(self.good,self.exe);other=Path(self.case.name)/'other/libavutil.61.dylib';other.parent.mkdir();source=Path(self.case.name)/'other.c';source.write_text('int av_frame_clone(void){return 9;}');v.run('xcrun','clang','-dynamiclib',source,'-Wl,-install_name,'+str(other),'-o',other)
        source.write_text('extern int av_frame_clone(void);int codec_marker(void){return av_frame_clone();}');v.run('xcrun','clang','-dynamiclib',source,other,'-Wl,-install_name,@rpath/libavcodec.63.dylib','-o',self.c/'Frameworks/libavcodec.63.dylib')
        result,output=self.package();self.assertNotEqual(result.returncode,0);self.assertIn('conflicting source libraries named libavutil.61.dylib',result.stderr)
    def test_original_av_frame_clone_mismatch(self):
        # The symbol is in avutil, but the executable declares avcodec. Global pooling is insufficient.
        self.assertIn('_av_frame_clone',v.exports(v.run('xcrun','dyld_info','-exports',self.c/'Frameworks/libavutil.61.dylib')))
        with self.assertRaisesRegex(v.Invalid,'_av_frame_clone missing from declared provider @rpath/libavcodec.63.dylib'):self.validate()
    def test_relinked_configuration_checks_all_imports(self):
        shutil.copy2(self.good,self.exe);self.assertEqual(self.validate()['imports_checked'],3)
    def test_legitimate_symbol_reexport(self):
        shutil.copy2(self.codec,self.c/'Frameworks/libavcodec.63.dylib');self.assertGreaterEqual(self.validate()['imports_checked'],3)
    def test_legitimate_whole_library_reexport(self):
        shutil.copy2(self.whole,self.c/'Frameworks/libavcodec.63.dylib');self.assertGreaterEqual(self.validate()['imports_checked'],3)
    def test_required_transitive_library_missing(self):
        shutil.copy2(self.codec,self.c/'Frameworks/libavcodec.63.dylib');(self.c/'Frameworks/libavutil.61.dylib').unlink()
        with self.assertRaisesRegex(v.Invalid,'Missing bundled dependency'):self.validate()
    def test_external_non_system_dependency_rejected(self):
        shutil.copy2(self.good,self.exe);v.run('install_name_tool','-change','@rpath/libavutil.61.dylib',self.lib/'libavutil.61.dylib',self.exe)
        with self.assertRaisesRegex(v.Invalid,'escapes bundle'):self.validate()
    def test_wrong_architecture_dependency_rejected(self):
        shutil.copy2(self.good,self.exe);target=self.c/'Frameworks/libavutil.61.dylib';source=self.base/'other.c';source.write_text('int av_frame_clone(void){return 7;}');other='x86_64' if self.host=='arm64' else 'arm64';v.run('xcrun','clang','-arch',other,'-dynamiclib',source,'-Wl,-install_name,@rpath/libavutil.61.dylib','-o',target)
        with self.assertRaisesRegex(v.Invalid,'Missing '+self.host+' slice'):self.validate()
    def test_all_bundled_executables_are_checked(self):
        shutil.copy2(self.good,self.exe);shutil.copy2(self.bad,self.c/'MacOS/second')
        with self.assertRaisesRegex(v.Invalid,'_av_frame_clone missing'):self.validate()
    def test_native_corrected_dependency_binding(self):
        shutil.copy2(self.good,self.exe);self.validate();self.assertEqual(subprocess.run([str(self.exe)],capture_output=True).returncode,0)
    def test_missing_primary_executable_rejected_even_with_helper(self):
        self.exe.unlink();shutil.copy2(self.good,self.c/'MacOS/other')
        with self.assertRaisesRegex(v.Invalid,'Missing primary'):self.validate()
    def test_primary_executable_escape_rejected(self):
        (self.c/'Info.plist').write_bytes(plistlib.dumps({'CFBundleExecutable':'../outside'}))
        with self.assertRaisesRegex(v.Invalid,'Invalid CFBundleExecutable'):self.validate()
    def test_signature_failure_rejected(self):
        shutil.copy2(self.good,self.exe)
        with self.assertRaises(v.Invalid):v.Validator(self.app).validate()
    def test_signed_final_bundle_and_cli(self):
        shutil.copy2(self.good,self.exe)
        for f in (self.c/'Frameworks').glob('*.dylib'):v.run('codesign','-f','-s','-',f)
        v.run('codesign','-f','-s','-',self.app);self.assertEqual(v.Validator(self.app).validate()['imports_checked'],3)
        result=subprocess.run([sys.executable,str(Path(v.__file__)),str(self.app)],text=True,capture_output=True);self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main()
