"""Mock-only hang collection. Never samples a game or attaches a recorder."""
import argparse,copy,json,os,subprocess,sys,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
import hang_watch as h
import profile as p
import recovery as r
import dynamic_observe as observe

class WatchTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name).resolve();self.session=self.root/'sessions'/'fixture';self.session.mkdir(parents=True);self.folder=self.session/'diagnostics'/'capture';self.folder.mkdir(parents=True);self.exe=self.root/'lasrecomp';self.exe.write_bytes(b'fixture');self.record={'session_id':'fixture','identity':{'pid':123,'executable':str(self.exe),'start_sec':1,'start_usec':2},'binary_sha256':p.sha(self.exe),'development_commit':'a'*40,'upstream_commit':'b'*40};self.speech=patch.object(h,'speech').start();self.addCleanup(patch.stopall)
 def fps(self,frame=60,level='KanaletCastle'):return f'[metal] t=1.0 frame {frame} 60.0 fps max 17ms level {level} (gpu 600ms, compile 0/0ms, pace 60)'
 def test_identity_reuse_rejected(self):
  actual=dict(self.record['identity'],start_usec=3)
  with patch.object(h,'identity',return_value=actual),self.assertRaises(h.IdentityError):h.verify(self.record)
 def test_identity_path_rejected(self):
  with patch.object(h,'identity',return_value=dict(self.record['identity'],executable='/unrelated/lasrecomp')),self.assertRaises(h.IdentityError):h.verify(self.record)
 def test_binary_hash_drift_rejected(self):
  self.exe.write_bytes(b'changed')
  with patch.object(h,'identity',return_value=self.record['identity']),self.assertRaises(h.IdentityError):h.verify(self.record,True)
 def test_healthy_stationary_never_triggers(self):
  d=h.Detector()
  with patch.object(h.time,'monotonic',return_value=100):
   for f in [60,120,180]:self.assertFalse(d.feed(self.fps(f),True))
  self.assertEqual(d.observation['simulation_progress'],'unavailable')
 def test_last_fps_context_includes_compilation_pace_and_timestamp(self):
  d=h.Detector();d.feed(self.fps(),True);self.assertEqual(d.last_fps['pace'],60);self.assertEqual(d.last_fps['compile_count'],0);self.assertIn('observed_utc',d.last_fps)
 def test_silence_alone_not_freeze(self):
  d=h.Detector();d.feed(self.fps(),True)
  with patch.object(h.time,'monotonic',return_value=d.changed+120):self.assertFalse(d.feed('',True))
 def test_static_fps_counter_not_simulation_heartbeat(self):
  d=h.Detector();d.feed(self.fps(),True)
  with patch.object(h.time,'monotonic',return_value=d.changed+120):self.assertFalse(d.feed(self.fps()+'\n[hang] ===== main thread waiting =====',False))
 def test_corroborated_runtime_report_triggers(self):
  d=h.Detector();d.feed(self.fps(),True)
  with patch.object(h.time,'monotonic',return_value=d.changed+31):self.assertTrue(d.feed('[hang] ===== presenting stopped =====',True))
 def test_continuing_render_can_miss_gameplay_freeze(self):
  d=h.Detector();d.feed(self.fps(),True)
  self.assertFalse(d.feed(self.fps(120)+'\n[hang] ===== main thread wait =====',True));self.assertEqual(d.observation['input_acceptance'],'unavailable')
 def test_menu_cutscene_loading_no_unsupported_alarm(self):
  for level,confirmed in [('-',True),('KanaletCastle',False)]:
   d=h.Detector();d.feed(self.fps(level=level),confirmed)
   with patch.object(h.time,'monotonic',return_value=d.changed+60):self.assertFalse(d.feed('[hang] ===== presenting stopped =====',confirmed))
 def test_valid_sample_requires_pid_and_callgraph(self):
  path=self.root/'sample';path.write_text('Process: lasrecomp [123]\nCall graph:\nBinary Images:');self.assertTrue(h.valid_sample(path,123));self.assertFalse(h.valid_sample(path,124));path.write_text('permission denied');self.assertFalse(h.valid_sample(path,123))
 def test_sample_command_exact_pid_no_shell(self):self.assertEqual(h.sample_command(123,self.root/'sample')[:4],['/usr/bin/sample','123','10','1'])
 def test_sample_complete(self):
  child=Mock();child.wait.return_value=0;child.poll.return_value=0
  def spawn(*a,**k):(self.folder/'sample-local.txt').write_text('Process: lasrecomp [123]\nCall graph:\nBinary Images:');return child
  outcome={}
  with patch.object(h,'verify'),patch.object(h.subprocess,'Popen',side_effect=spawn):h.run_sample(self.record,self.folder,outcome)
  self.assertEqual(outcome['sample_status'],'complete');child.kill.assert_not_called()
 def test_sample_denied_preserved_as_failure(self):
  child=Mock();child.wait.return_value=1;child.poll.return_value=1;outcome={}
  with patch.object(h,'verify'),patch.object(h.subprocess,'Popen',return_value=child):h.run_sample(self.record,self.folder,outcome)
  self.assertEqual(outcome['sample_status'],'partial_or_denied')
 def test_sample_missing_tool_nonfatal(self):
  o={}
  with patch.object(h,'verify'),patch.object(h.subprocess,'Popen',side_effect=PermissionError()):h.run_sample(self.record,self.folder,o)
  self.assertEqual(o['sample_status'],'tool_unavailable_or_denied')
 def test_sample_timeout_only_owned_child_cleanup(self):
  child=Mock();child.wait.side_effect=subprocess.TimeoutExpired('sample',25);child.poll.return_value=None;o={}
  with patch.object(h,'verify'),patch.object(h.subprocess,'Popen',return_value=child),patch.object(p,'stop_recorder') as stop:h.run_sample(self.record,self.folder,o)
  stop.assert_called_once_with(child);self.assertEqual(o['sample_status'],'timeout')
 def trace(self,failed=False,exit_game=False):
  child=Mock();child.poll.return_value=1 if failed else 0
  def spawn(cmd,**kwargs):
   self.assertIn('--attach',cmd);self.assertNotIn('--launch',cmd);self.assertIn('Time Profiler',cmd)
   trace=Path(cmd[cmd.index('--output')+1]);trace.mkdir();(trace/'data').write_text('fixture');return child
  def command(cmd,*a):
   Path(cmd[cmd.index('--output')+1]).write_text('<trace-toc><run><info><target><process pid="123"/></target><summary><template-name>Time Profiler</template-name><start-date>2026-10-25T00:00:00Z</start-date><end-date>2026-10-25T00:00:20Z</end-date><duration>20</duration></summary></info><data><table schema="time-profile"/></data></run></trace-toc>');return (1 if failed else 0),''
  o={}
  with patch.object(h,'verify',side_effect=h.IdentityError('exited') if exit_game else None),patch.object(h.subprocess,'Popen',side_effect=spawn),patch.object(p,'command',side_effect=command):h.run_trace(self.record,self.folder,o)
  return o
 def test_trace_attach_and_pid_validation(self):
  o=self.trace();self.assertEqual(o['trace_status'],'identity_verified');self.assertEqual(o['trace_actual_duration_s'],20)
 def test_trace_export_failure(self):self.assertEqual(self.trace(failed=True)['trace_status'],'export_failed')
 def test_exit_before_trace_no_attach(self):self.assertEqual(self.trace(exit_game=True)['trace_status'],'failed_or_process_exited')
 def test_missing_trace_not_success(self):
  child=Mock();child.poll.return_value=0;o={}
  with patch.object(h,'verify'),patch.object(h.subprocess,'Popen',return_value=child):h.run_trace(self.record,self.folder,o)
  self.assertEqual(o['trace_status'],'missing_or_failed')
 def test_disk_limit_skips_trace_preserves_sample(self):
  o={'sample_status':'complete'}
  with patch.object(h,'verify'),patch.object(h.shutil,'disk_usage',return_value=Mock(free=1)),patch.object(h.subprocess,'Popen') as spawn:h.run_trace(self.record,self.folder,o)
  spawn.assert_not_called();self.assertEqual(o['sample_status'],'complete');self.assertEqual(o['trace_status'],'disk_space_low')
 def test_locks_are_nonblocking_and_release(self):
  a=h.Lock(self.root/'lock');b=h.Lock(self.root/'lock');self.assertTrue(a.acquire());self.assertFalse(b.acquire());a.close();self.assertTrue(b.acquire());b.close()
 def test_active_registry_identity(self):
  p.dump(self.session/'active-local.json',self.record);p.dump(self.session/'manifest-local.json',{'pid':123,'executable':str(self.exe),'executable_sha256':p.sha(self.exe)})
  with patch.object(p,'HERE',self.root),patch.object(h,'verify'):self.assertEqual(h.active_session(),self.session)
 def test_ambiguous_registry_rejected(self):
  for n in ['a','b']:(self.root/'sessions'/n).mkdir();p.dump(self.root/'sessions'/n/'active-local.json',{})
  with patch.object(p,'HERE',self.root),patch.object(h,'owned_session'),self.assertRaises(h.IdentityError):h.active_session()
 def test_no_active_registry_rejected(self):
  with patch.object(p,'HERE',self.root),self.assertRaises(h.IdentityError):h.active_session()
 def capture(self,prearmed=False,fail_trace=False):
  events=[]
  def sample(record,folder,o):events.append('sample');(folder/'sample-local.txt').write_text('private stacks');o['sample_status']='complete'
  def trace(record,folder,o,**kwargs):events.append('trace');self.assertTrue((folder/'outcome-local.json').exists());o['trace_status']='failed_or_process_exited' if fail_trace else 'identity_verified'
  with patch.object(h,'owned_session',return_value=self.record),patch.object(h,'verify'),patch.object(h,'run_sample',side_effect=sample),patch.object(h,'run_trace',side_effect=trace),patch.object(h.subprocess,'run',return_value=Mock(returncode=0)) as reveal:
   code=h.capture(self.session,'prearmed' if prearmed else 'manual',prearmed)
  return code,events,reveal
 def test_manual_capture_samples_before_trace(self):
  code,events,reveal=self.capture();self.assertEqual(code,0);self.assertEqual(events,['sample','trace']);reveal.assert_called_once()
 def test_sample_survives_failed_instruments(self):
  code,events,_=self.capture(fail_trace=True);self.assertEqual(code,0);self.assertTrue(list((self.session/'diagnostics').glob('*/sample-local.txt')))
 def test_prearm_does_not_sample_healthy_game(self):self.assertEqual(self.capture(prearmed=True)[1],['trace'])
 def test_capture_cooldown(self):
  self.capture()
  with patch.object(h,'owned_session',return_value=self.record),patch.object(h,'run_sample') as sample:self.assertEqual(h.capture(self.session),2);sample.assert_not_called()
 def test_safe_zip_excludes_raw_stacks_and_paths(self):
  self.capture();zpath=next((self.session/'diagnostics').glob('*/safe-summary.zip'))
  with zipfile.ZipFile(zpath) as z:self.assertEqual(set(z.namelist()),{'diagnostics.json','README.md'});self.assertNotIn(b'private stacks',b''.join(z.read(n) for n in z.namelist()))
 def test_sanitizer_drops_addresses_paths_raw_errors(self):
  safe=h.sanitize({'trigger':'manual','sample_status':'complete','raw':'secret','sample_path':'/Users/private','last_fps':60});self.assertNotIn('raw',safe);self.assertNotIn('sample_path',safe);self.assertEqual(safe['last_fps'],60)
 def test_context_marks_missing_simulation(self):
  d=h.Detector();d.feed(self.fps(),True);self.assertEqual(d.observation['macos_responsiveness'],'unavailable');self.assertEqual(d.observation['input_acceptance'],'unavailable')
 def test_prearm_cli_routes_without_launch(self):
  with patch.object(sys,'argv',['profile.py','--prearm','--build','beta6','--dry-run']),patch.object(observe,'run',return_value=0) as run:
   self.assertEqual(p.main(),0);a=run.call_args.args[0];self.assertTrue(a.prearm);self.assertEqual(a.dynamic,'kanalet');self.assertEqual(a.build,'beta6')
 def test_intensive_build_default_preserved(self):
  with patch.object(sys,'argv',['profile.py','--intensive','--dry-run']),patch.object(observe,'run',return_value=0) as run:self.assertEqual(p.main(),0);self.assertEqual(run.call_args.args[0].build,'baseline')
 def test_no_watchdog_cli(self):
  with patch.object(sys,'argv',['profile.py','--intensive','--no-watchdog','--dry-run']),patch.object(observe,'run',return_value=0) as run:self.assertEqual(p.main(),0);self.assertTrue(run.call_args.args[0].no_watchdog)
 def test_accurate_separate_baseline_recovery_wording(self):
  a=argparse.Namespace(recovery='intensive',intensive_seconds=420)
  self.assertIn('Baseline measurement',r.phase_announcement(a,'baseline'));self.assertIn('7 minutes',r.phase_announcement(a,'intensive'));self.assertIn('performance recovery',r.phase_announcement(a,'recovery_1'))
 def test_prearm_trace_hooks_at_baseline_with_unchanged_windows(self):
  a=argparse.Namespace(recovery='screen-transition',repeat_crossing=False,prearm=True,watchdog_session=self.session,dynamic_trace=None);phases=[];state={'now':40}
  def span(proc,c,seconds):begin=state['now'];state['now']+=seconds;return begin,state['now']
  with patch.object(r,'announce'),patch.object(h,'phase') as phase,patch.object(h,'spawn') as spawn:r.observe(a,Mock(),Mock(),self.session,{'session_id':'fixture','scenario':'RT'},self.exe,phases,span)
  spawn.assert_called_once_with(self.session,'prearm',120);self.assertEqual([x['end_s']-x['begin_s'] for x in phases],[30,10,120]);self.assertEqual(phase.call_count,3)
 def test_register_without_auto_monitor_is_still_emergency_capable(self):
  meta={'session_id':'fixture','pid':123,'executable_sha256':p.sha(self.exe),'git_head':'a'*40}
  with patch.object(h,'identity',return_value=self.record['identity']),patch.object(h.subprocess,'Popen') as spawn:h.register(self.session,meta,self.exe,False)
  spawn.assert_not_called();self.assertTrue((self.session/'active-local.json').exists())
 def test_register_starts_python_monitor_not_game(self):
  meta={'session_id':'fixture','pid':123,'executable_sha256':p.sha(self.exe),'git_head':'a'*40}
  with patch.object(h,'identity',return_value=self.record['identity']),patch.object(h.subprocess,'Popen') as spawn:h.register(self.session,meta,self.exe,True)
  self.assertIn('monitor',spawn.call_args.args[0]);self.assertNotEqual(spawn.call_args.args[0][0],str(self.exe))
 def test_stale_active_pid_not_emergency_target(self):
  p.dump(self.session/'active-local.json',self.record)
  with patch.object(p,'HERE',self.root),patch.object(h,'owned_session',side_effect=h.IdentityError('dead')),self.assertRaises(h.IdentityError):h.active_session()
 def test_overlapping_capture_rejected(self):
  lock=h.Lock(self.session/'diagnostics/capture.lock');self.assertTrue(lock.acquire())
  try:
   with patch.object(h,'owned_session',return_value=self.record),patch.object(h,'run_sample') as sample:self.assertEqual(h.capture(self.session),2);sample.assert_not_called()
  finally:lock.close()
 def test_maximum_capture_count(self):
  p.dump(self.session/'diagnostics/rate-local.json',{'attempts':2,'last_epoch':0})
  with patch.object(h,'owned_session',return_value=self.record),patch.object(h,'run_sample') as sample:self.assertEqual(h.capture(self.session),2);sample.assert_not_called()
 def test_beta6_catalog_rejects_binary_drift(self):
  p.dump(self.root/'BETA6_BUILD_LOCAL.json',{'repository':str(self.root),'binary_sha256':'0'*64,'development_commit':'a'*40})
  (self.root/'build').mkdir();(self.root/'build/lasrecomp').write_bytes(b'different')
  with patch.object(p,'HERE',self.root),self.assertRaises(p.Invalid):p.preflight(argparse.Namespace(build='beta6'))
 def test_beta6_catalog_rejects_source_revision_drift(self):
  (self.root/'build').mkdir();exe=self.root/'build/lasrecomp';exe.write_bytes(b'fixture');p.dump(self.root/'BETA6_BUILD_LOCAL.json',{'repository':str(self.root),'binary_sha256':p.sha(exe),'development_commit':'a'*40})
  with patch.object(p,'HERE',self.root),patch.object(p.subprocess,'check_output',return_value='b'*40),self.assertRaises(p.Invalid):p.preflight(argparse.Namespace(build='beta6'))
 def test_fork_publication_guard(self):
  import publication_guard as g
  command=g.destination('gsel001','https://github.com/gsel001/LASRecomp.git','codex/m1-beta6-freeze-diagnostics-v1');self.assertNotIn('--force',command);self.assertEqual(command[2],'myfork')
 def test_publication_refuses_upstream_wrong_account_or_existing_branch(self):
  import publication_guard as g
  for login,url,branch,existing in [('other','https://github.com/gsel001/LASRecomp.git','codex/task',None),('gsel001','https://github.com/peiikai/LASRecomp.git','codex/task',None),('gsel001','https://github.com/gsel001/LASRecomp.git','main',None),('gsel001','https://github.com/gsel001/LASRecomp.git','codex/task','abc')]:
   with self.subTest(login=login,url=url,branch=branch),self.assertRaises(ValueError):g.destination(login,url,branch,existing)
if __name__=='__main__':unittest.main()
