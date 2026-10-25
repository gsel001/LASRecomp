#!/usr/bin/env python3
"""Non-gameplay tests. All saves/settings are synthetic temporary fixtures."""
import argparse
import copy
import io
import json
import os
from pathlib import Path
import pty
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch,Mock
import zipfile
import profile as p
import analyze as a

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(prefix='las-profile-tests-');self.root=Path(self.tmp.name)
  self.repo=self.root/'repo';(self.repo/'build').mkdir(parents=True);(self.repo/'.git').mkdir()
  self.data=self.root/'source';(self.data/'extracted/exefs').mkdir(parents=True);(self.data/'extracted/romfs').mkdir()
  self.settings=self.data/'larecomp.ini';self.settings.write_text('rando_seed =\nfullscreen = 0\nresolution = dynamic\naspect = unlocked\nantialias = smaa\nupscaler = metalfx\n')
  self.save=self.data/'save';self.save.mkdir();(self.save/'slot').write_bytes(b'synthetic save')
  main=bytearray(0x60);main[:4]=b'NSO0';main[0x40:0x48]=b'12345678';(self.data/'extracted/exefs/main').write_bytes(main)
  self.exe=self.repo/'build/lasrecomp';self.exe.write_bytes(b'fixture-generator\0[depth-no-fs] experimental= [scale] frame ');self.exe.chmod(0o700)
  self.lib=self.data/'extracted/lasgame.dylib';self.lib.write_bytes(b'not loaded synthetic library');Path(str(self.lib)+'.id').write_text('fixture-generator-'+bytes(main[0x40:0x48]).hex().upper())
  self.helper=p.helper_module()
  self.args=argparse.Namespace(scenario='A',method='overview',motion='stationary',seconds=25,warmup=30)
  self.meta={'helper_sha256':p.sha(Path(self.helper.__file__)),'scenario':'A','method':'overview','status':'preflight_passed_not_launched','git_head':'a'*40,'git_branch':'fixture','git_status':' M fixture','executable_sha256':p.sha(self.exe),'library_sha256':p.sha(self.lib),'expected_drawable':[2880,1800],'environment':{},'warnings':[]}
 def tearDown(self):self.tmp.cleanup()
 def log(self,scene='KeyCavern',compile=0):
  return '\n'.join(f'[metal] t={t} frame {t*30} 30.0 fps max 34ms level {scene} (gpu 600ms, compile {compile}/0)' for t in [10,12,14])
 def test_valid_paths_and_library(self):self.assertEqual(p.validate_inputs(self.repo,self.data,self.settings,self.save),(self.exe,self.lib))
 def test_missing_executable(self):
  self.exe.unlink()
  with self.assertRaises(p.Invalid):p.validate_inputs(self.repo,self.data,self.settings,self.save)
 def test_wrong_installed_executable_symlink(self):
  self.exe.unlink();self.exe.symlink_to('/bin/true')
  with self.assertRaises(p.Invalid):p.validate_inputs(self.repo,self.data,self.settings,self.save)
 def test_missing_library(self):
  self.lib.unlink()
  with self.assertRaises(p.Invalid):p.validate_inputs(self.repo,self.data,self.settings,self.save)
 def test_incompatible_library_id(self):
  Path(str(self.lib)+'.id').write_text('wrong-123')
  with self.assertRaises(p.Invalid):p.validate_inputs(self.repo,self.data,self.settings,self.save)
 def test_invalid_main(self):
  (self.data/'extracted/exefs/main').write_bytes(b'bad')
  with self.assertRaises(p.Invalid):p.validate_inputs(self.repo,self.data,self.settings,self.save)
 def test_save_symlink_rejected(self):
  (self.save/'link').symlink_to(self.settings)
  with self.assertRaises(p.Invalid):p.validate_inputs(self.repo,self.data,self.settings,self.save)
 def test_private_isolation_all_scenarios(self):
  before=self.settings.read_bytes();saved=(self.save/'slot').read_bytes()
  for scenario in ['A','B','C']:
   dest=self.root/scenario;env=p.prepare(dest,self.helper,self.settings,self.save,self.data,self.lib,scenario,{},False)
   self.assertEqual(self.helper.ini_values(dest/'larecomp.ini')['resolution'],'1' if scenario=='B' else 'match')
   (dest/'save/slot').write_bytes(b'private changed');self.assertEqual(Path(env['LARECOMP_DATA_ROOT']).resolve(),(dest/'data').resolve())
   self.assertTrue((dest/'data/extracted').is_symlink());self.assertEqual(self.settings.read_bytes(),before);self.assertEqual((self.save/'slot').read_bytes(),saved)
 def test_environment_cleans_presence_flags(self):
  parent={'HOME':'/synthetic','LARECOMP_DEPTH_NO_FS_DIAG':'0','LARECOMP_LOG_PACE':'0','MTL_HUD_ENABLED':'1','DYLD_INSERT_LIBRARIES':'bad','NO_RAW':'1','LASRECOMP_LOG_APPEND':'1','LARECOMP_SKIP_FSHASH':'123','RANDOM_EXPERIMENT':'1'}
  env=p.clean_environment(parent,self.root,self.data,self.lib)
  self.assertEqual(env['LARECOMP_DEPTH_NO_FS'],'0');self.assertEqual(env['LARECOMP_NO_LAUNCHER'],'1')
  self.assertTrue(all(k not in env for k in parent if k!='HOME'))
  self.assertNotIn('MTL_CAPTURE_ENABLED',env)
 def test_frame_layer_separate(self):self.assertEqual(p.clean_environment({},self.root,self.data,self.lib,True)['MTL_CAPTURE_ENABLED'],'1')
 def test_pid_identity_correct(self):self.assertTrue(p.verify_pid(123,self.exe,lambda _:self.exe.resolve()))
 def test_pid_identity_wrong(self):
  with self.assertRaises(p.Invalid):p.verify_pid(123,self.exe,lambda _:Path('/Applications/LAS Recomp.app/Contents/MacOS/lasrecomp'))
 def test_pid_identity_missing(self):
  with self.assertRaises(p.Invalid):p.verify_pid(123,self.exe,lambda _:None)
 def test_graphics_correct(self):
  d=p.graphics('[scale] frame 1 drawable 2880x1800 -> render scale 1.500x1.500 (reshape 0)','A');self.assertEqual(d['render_area_derived_not_observed'],[2880,1620])
 def test_resolution_control(self):self.assertEqual(p.graphics('[scale] frame 1 drawable 2880x1800 -> render scale 1.000x1.000 (reshape 0)','B')['render_scale_observed'],[1,1])
 def test_wrong_drawable(self):
  with self.assertRaises(p.Invalid):p.graphics('[scale] frame 1 drawable 2048x1280 -> render scale 1.000x1.000 (reshape 0)','A')
 def test_wrong_scale(self):
  with self.assertRaises(p.Invalid):p.graphics('[scale] frame 1 drawable 2880x1800 -> render scale 1.000x1.000 (reshape 0)','A')
 def test_missing_graphics(self):
  with self.assertRaises(p.Invalid):p.graphics('','A')
 def test_baseline_banner(self):p.validate_baseline('[depth-no-fs] experimental=0')
 def test_experimental_rejected(self):
  with self.assertRaises(p.Invalid):p.validate_baseline('[depth-no-fs] experimental=1')
 def test_diagnostics_rejected(self):
  with self.assertRaises(p.Invalid):p.validate_baseline('[depth-no-fs] experimental=0\n[depth-no-fs-diag] enabled=1')
 def test_missing_baseline_log(self):
  with self.assertRaises(p.Invalid):p.validate_baseline('')
 def test_numeric_proxy_not_gpu_frame(self):
  d=p.measurements(self.log(),'A');self.assertFalse(d['errors']);self.assertEqual(d['asynchronous_gpu_ms_per_present_proxy']['median'],10);self.assertEqual(d['runtime_fps_periodic']['samples'],2);self.assertIn('status',d['gpu_execution_ms'])
 def test_invalid_log(self):self.assertIn('missing_or_insufficient_runtime_samples',p.measurements('garbage','A')['errors'])
 def test_loading_scene_change(self):self.assertIn('scene_changed_or_unconfirmed',p.measurements(self.log(scene='Menu'),'A')['errors'])
 def test_compile_invalid(self):self.assertIn('shader_compilation_not_settled_or_unobservable',p.measurements(self.log(compile=3),'A')['errors'])
 def test_scale_change_invalid(self):self.assertIn('render_scale_changed_in_recording_window',p.measurements(self.log()+'\n[scale] frame 9','A')['errors'])
 def test_trace_fresh_exact_session(self):
  trace=self.root/'recording.trace';trace.mkdir();(trace/'data').write_text('synthetic');self.assertTrue(p.trace_matches(trace,self.root,time.time()-1))
 def test_trace_stale_rejected(self):
  trace=self.root/'recording.trace';trace.mkdir();(trace/'data').touch();os.utime(trace,(1,1));self.assertFalse(p.trace_matches(trace,self.root,time.time()))
 def test_trace_wrong_session_rejected(self):
  trace=self.root/'recording.trace';trace.mkdir();(trace/'data').touch();self.assertFalse(p.trace_matches(trace,self.repo,time.time()))
 def test_empty_trace_rejected(self):
  trace=self.root/'recording.trace';trace.mkdir();self.assertFalse(p.trace_matches(trace,self.root,time.time()))
 def test_safe_zip_allowlist(self):
  local=dict(self.meta,session_id='fixture',launch_environment={'SECRET':'must not share'},executable='/private/secret',pid=45)
  (self.root/'runtime-local.log').write_text('/private/secret proprietary shader');(self.root/'frame.gputrace').write_text('proprietary')
  archive=p.write_safe(self.root,local,{'errors':[]})
  with zipfile.ZipFile(archive) as z:
   self.assertEqual(set(z.namelist()),p.SAFE_NAMES);self.assertNotIn(b'private/secret',b''.join(z.read(n) for n in z.namelist()))
 def test_session_identity_unique(self):
  # Two cancelled mock launches must produce separate sessions and never claim capture.
  with patch.object(p,'HERE',self.root),patch.object(sys.stdin,'isatty',return_value=True),patch('builtins.input',return_value='CANCEL'),patch.object(p,'environment_metadata',return_value={}):
   for _ in range(2):self.assertEqual(p.session_run(self.args,self.meta,(self.helper,self.data,self.settings,self.save,self.exe,self.lib)),1)
  sessions=list((self.root/'sessions').iterdir());self.assertEqual(len(sessions),2)
  for s in sessions:self.assertFalse(json.loads((s/'safe/summary.json').read_text())['capture_validated']);self.assertTrue((s/'private/save/slot').exists())
 def test_launch_failure_no_false_capture(self):
  with patch.object(p,'HERE',self.root),patch.object(sys.stdin,'isatty',return_value=True),patch('builtins.input',return_value='LAUNCH'),patch.object(p,'conflicts',return_value=[]),patch.object(p.subprocess,'Popen',side_effect=OSError('synthetic launch failure')),patch.object(p,'environment_metadata',return_value={}):
   self.assertEqual(p.session_run(self.args,self.meta,(self.helper,self.data,self.settings,self.save,self.exe,self.lib)),1)
  s=next((self.root/'sessions').iterdir());self.assertEqual(json.loads((s/'safe/summary.json').read_text())['status'],'failed_or_interrupted');self.assertTrue((s/'private/save/slot').exists())
 def simulate_session(self,exit_code=0,clean=True,toc_mode='valid',sample_mode='valid',recorder_error=None,settings_change=False):
  game=Mock(pid=123);game.poll.return_value=None;game.wait.return_value=exit_code
  def fake_launch(*args,**kwargs):
   self.runtime=Path(kwargs['stdout'].name)
   kwargs['stdout'].write((f'[gamelib] {self.lib} (123 + 456 functions)\n[depth-no-fs] experimental=0\n[scale] frame 1 drawable 2880x1800 -> render scale 1.500x1.500 (reshape 0)\n'+self.log()+'\n').encode());return game
  def fake_record(process,exe,session,method,seconds):
   (session/'recording.trace').mkdir();(session/'recording.trace/data').write_text('synthetic trace')
   times=list(range(46,72,2))
   if sample_mode=='short':times=[46,48]
   if sample_mode=='backward':times.reverse()
   lines=[f'[metal] t={t} frame {1380 if sample_mode=="duplicate" else t*30} 30.0 fps max 34ms level KeyCavern (gpu 600ms, compile 0/0)' for t in times]
   with (session/'runtime-local.log').open('ab') as f:f.write(('\n'.join(lines)+'\n').encode())
   if settings_change:(session/'private/larecomp.ini').write_text('resolution = 1\n')
   if recorder_error:raise p.RecorderError(recorder_error,{'confirmed':False,'stage':'unconfirmed','escalated':True,'interrupts':0})
   return 0
  def warm_sleep(seconds):
   if seconds==30 and sample_mode!='stale':
    with self.runtime.open('ab') as f:f.write(('\n'.join(f'[metal] t={t} frame {t*30} 30.0 fps max 34ms level KeyCavern (gpu 600ms, compile 0/0)' for t in range(16,46,2))+'\n').encode())
  def fake_command(args,*unused,**kwargs):
   if '--toc' in args:
    path=Path(args[args.index('--output')+1])
    texts={'valid':'<trace-toc><run><info><target><process pid="123"/></target></info><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>','malformed':'<trace-toc><run>','incomplete':'<trace-toc><run><info/></run></trace-toc>','unexpected':'<other/>','wrong-pid':'<trace-toc><run><info><target><process pid="124"/></target></info><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>'}
    if toc_mode in texts:path.write_text(texts[toc_mode])
   return 0,''
  with patch.object(p,'HERE',self.root),patch.object(sys.stdin,'isatty',return_value=True),patch('builtins.input',side_effect=['LAUNCH','READY','CLEAN' if clean else 'uncertain']),patch.object(p,'conflicts',return_value=[]),patch.object(p.subprocess,'Popen',side_effect=fake_launch),patch.object(p,'environment_metadata',return_value={}),patch.object(p,'verify_pid'),patch.object(p.time,'sleep',side_effect=warm_sleep),patch.object(p,'record',side_effect=fake_record),patch.object(p,'command',side_effect=fake_command):
   code=p.session_run(self.args,self.meta,(self.helper,self.data,self.settings,self.save,self.exe,self.lib))
  session=next((self.root/'sessions').iterdir());self.session=session;summary=json.loads((session/'safe/summary.json').read_text())
  self.assertTrue((session/'private/save/slot').exists());return code,summary
 def test_full_mock_session_success(self):
  code,summary=self.simulate_session();self.assertEqual(code,0);self.assertTrue(summary['trace_pid_verified']);self.assertTrue(summary['pid_executable_verified'])
 def test_full_mock_session_abnormal_exit(self):
  code,summary=self.simulate_session(exit_code=7);self.assertEqual(code,1);self.assertIn('nonzero_game_exit',summary['error_codes'])
 def test_full_mock_session_focus_contamination(self):
  code,summary=self.simulate_session(clean=False);self.assertEqual(code,1);self.assertEqual(summary['status'],'capture_requires_interval_review')
 def test_mock_exit_lifecycle(self):
  proc=Mock();proc.wait.side_effect=[KeyboardInterrupt,0];self.assertEqual(p.wait_for_exit(proc),0)
 def test_mock_abnormal_exit(self):
  proc=Mock();proc.wait.return_value=7;self.assertEqual(p.wait_for_exit(proc),7)
 def test_mock_real_process_launch_exit(self):
  proc=subprocess.Popen(['/usr/bin/true'],start_new_session=True);self.assertEqual(p.wait_for_exit(proc),0)
 def test_recorder_attaches_pid_not_name(self):
  cmd=p.recorder(123,self.root,'metal',8);self.assertEqual(cmd[cmd.index('--attach')+1],'123');self.assertNotIn('--launch',cmd)
 def test_recorder_interruption(self):
  game=Mock(pid=123);game.poll.return_value=None;rec=Mock();rec.poll.return_value=None;rec.wait.side_effect=[KeyboardInterrupt,0]
  with patch.object(p,'verify_pid'),patch.object(p.subprocess,'Popen',return_value=rec):
   with self.assertRaises(p.Invalid):p.record(game,self.exe,self.root,'metal',8)
  rec.send_signal.assert_called_once();game.terminate.assert_not_called()
 def test_terminal_input_via_pty(self):
  master,slave=pty.openpty()
  try:
   child=subprocess.Popen([sys.executable,'-c','import time; x=input("READY? "); print("accepted:"+x,flush=True); time.sleep(.3)'],stdin=slave,stdout=slave,stderr=slave);os.close(slave);slave=None
   ready,_,_=select.select([master],[],[],3);self.assertTrue(ready);prompt=os.read(master,1024);self.assertIn(b'READY?',prompt);os.write(master,b'READY\n')
   chunks=[]
   while select.select([master],[],[],.1)[0]:
    try:
     block=os.read(master,1024)
     if not block:break
     chunks.append(block)
    except OSError:break
   child.wait(timeout=3)
   self.assertIn(b'accepted:READY',b''.join(chunks))
  finally:
   os.close(master)
   if slave is not None:os.close(slave)
 def test_noninteractive_launch_rejected(self):
  with patch.object(sys.stdin,'isatty',return_value=False):
   with self.assertRaises(p.Invalid):p.session_run(self.args,self.meta,())
 def test_trace_inventory_redaction(self):
  toc=self.root/'toc.xml';toc.write_text('<trace-toc><run><info><target><process pid="123"/></target><environment><item key="secret" value="do not share"/></environment></info><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>')
  self.assertNotIn('secret',json.dumps(a.inventory(toc,123)))
  with self.assertRaises(p.Invalid):a.inventory(toc,124)
 def csv(self,extra=''):
  path=self.root/'samples.csv'
  header='session_id,pid,metric,value,unit,start_s,end_s,source,sample_id,time_s,frame_id\n'
  rows=''.join(f'fixture,123,gpu_execution_ms,{10 if i%2==0 else 20},ms,2,23,instruments_selection,{i},{2+i*.5},{i}\n' for i in range(42))
  if extra:rows+='fixture,123,gpu_execution_ms,nan,ms,2,23,instruments_selection,extra,22.9,42\n'
  path.write_text(header+rows);return path
 def test_selected_metrics(self):self.assertEqual(a.read_samples(self.csv(),'fixture',123,'overview')['metrics']['gpu_execution_ms']['median'],15)
 def test_mixed_session_rejected(self):
  with self.assertRaises(p.Invalid):a.read_samples(self.csv(),'different',123,'overview')
 def test_nonfinite_samples_rejected(self):
  with self.assertRaises(p.Invalid):a.read_samples(self.csv('fixture,123,gpu_execution_ms,nan,ms,2,8,instruments_selection\n'),'fixture',123,'overview')
 def test_comparison_mismatched_resolution(self):
  x=dict(self.meta,session_id='1',status='capture_ready_for_manual_trace_review');y=dict(x,session_id='2',expected_drawable=[2048,1280])
  with self.assertRaises(p.Invalid):a.compare(x,y)
 def test_no_capture_comparison_rejected(self):
  with self.assertRaises(p.Invalid):a.compare(dict(self.meta,session_id='1'),dict(self.meta,session_id='2'))
 def test_dry_run_never_launches(self):
  with patch.object(p,'HERE',self.root),patch.object(sys,'argv',['profile.py','--dry-run']),patch.object(p,'preflight',return_value=(self.meta,())),patch.object(p,'session_run',side_effect=AssertionError('must not launch')):
   self.assertEqual(p.main(),0)
 def mock_preflight(self,free=12*1024**3,tools=True,template_code=0):
  helper=Mock();helper.data_paths.return_value=(self.data,self.settings,self.save);helper.ini_values=self.helper.ini_values
  with patch.object(p,'check_xcode_installation',return_value=True),patch.object(p,'helper_module',return_value=helper),patch.object(p,'command',return_value=(template_code,'Game Performance Overview Metal System Trace')),patch.object(p,'conflicts',return_value=[]),patch.object(p.shutil,'which',return_value='/usr/bin/tool' if tools else None),patch.object(p.shutil,'disk_usage',return_value=Mock(free=free)),patch.object(p,'environment_metadata',return_value={}),patch.object(p.subprocess,'check_output',return_value='fixture'):
   return p.preflight(self.args,self.repo)
 def test_preflight_fixture_success(self):self.assertEqual(self.mock_preflight()[0]['executable_sha256'],p.sha(self.exe))
 def test_preflight_missing_tools(self):
  with self.assertRaises(p.Invalid):self.mock_preflight(tools=False)
 def test_preflight_low_storage(self):
  with self.assertRaises(p.Invalid):self.mock_preflight(free=1024)
 def test_preflight_permission_failure(self):
  with self.assertRaises(p.Invalid):self.mock_preflight(template_code=127)
 def test_conflicting_process_detection(self):
  with patch.object(p,'command',return_value=(0,' 123 /Applications/LAS Recomp.app/Contents/MacOS/lasrecomp\n 456 /bin/sleep')):self.assertEqual(p.conflicts(),[123])
 def test_process_list_permission_not_silent(self):
  with patch.object(p,'command',return_value=(1,'')):
   with self.assertRaises(p.Invalid):p.conflicts()
 def test_discovery_ignores_inherited_private_paths(self):
  helper=Mock()
  def discover(args):
   self.assertNotIn('LARECOMP_DATA_ROOT',os.environ);self.assertNotIn('LARECOMP_SETTINGS',os.environ);return 'root','settings','save'
  helper.data_paths.side_effect=discover
  with patch.dict(os.environ,{'LARECOMP_DATA_ROOT':'stale-private','LARECOMP_SETTINGS':'stale.ini'}):
   self.assertEqual(p.discover_inputs(helper,self.args),('root','settings','save'));self.assertEqual(os.environ['LARECOMP_DATA_ROOT'],'stale-private')
 def test_cli_help(self):
  for name in ['profile.py','analyze.py','validate_tools.py']:
   result=subprocess.run([sys.executable,str(p.HERE/name),'--help'],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
