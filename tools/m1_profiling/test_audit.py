#!/usr/bin/env python3
"""Focused independent-audit regressions. Fixtures only; no game/tools/captures launched."""
import copy,csv,hashlib,io,json,os,shutil,subprocess,sys,tempfile,time,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
import profile as p
import analyze as a
import privacy,isolation,setup_check
import test_profiling as base_tests

class AuditTests(unittest.TestCase):
 setUp=base_tests.Tests.setUp
 tearDown=base_tests.Tests.tearDown
 log=base_tests.Tests.log
 simulate_session=base_tests.Tests.simulate_session
 def test_malformed_toc_finalizes_failure(self):
  code,d=self.simulate_session(toc_mode='malformed');self.assertEqual(code,1);self.assertFalse(d['capture_validated']);self.assertFalse(d['trace_pid_verified']);self.assertIn('trace_toc_malformed',d['error_codes'])
  self.assertTrue((self.session/'safe-summary.zip').is_file());self.assertIn('ParseError',(self.session/'trace-error-local.txt').read_text());self.assertEqual((self.session/'toc-local.xml').read_text(),'<trace-toc><run>')
 def test_empty_table_metadata_rejected(self):
  path=self.root/'empty.xml';path.write_text('<trace-toc><run><info><target><process pid="123"/></target></info><data/></run></trace-toc>')
  with self.assertRaises(a.TraceError) as c:a.inventory(path,123)
  self.assertEqual(c.exception.code,'trace_toc_incomplete')
 def test_missing_toc_finalizes_failure(self):
  code,d=self.simulate_session(toc_mode='missing');self.assertEqual(code,1);self.assertIn('trace_toc_missing',d['error_codes'])
 def test_incomplete_toc_finalizes_failure(self):
  code,d=self.simulate_session(toc_mode='incomplete');self.assertEqual(code,1);self.assertIn('trace_toc_incomplete',d['error_codes'])
 def test_unexpected_toc_finalizes_failure(self):
  code,d=self.simulate_session(toc_mode='unexpected');self.assertEqual(code,1);self.assertIn('trace_toc_unexpected',d['error_codes'])
 def test_wrong_toc_pid_finalizes_failure(self):
  code,d=self.simulate_session(toc_mode='wrong-pid');self.assertEqual(code,1);self.assertIn('trace_toc_pid_mismatch',d['error_codes'])
 def test_analysis_malformed_preserves_previous_zip(self):
  self.simulate_session();archive=self.session/'safe-summary.zip';before=archive.read_bytes()
  def export(args,*unused,**kwargs):Path(args[args.index('--output')+1]).write_text('<broken>');return 0,''
  with patch.object(sys,'argv',['analyze.py',str(self.session)]),patch.object(p,'command',side_effect=export):self.assertEqual(a.main(),1)
  self.assertEqual(archive.read_bytes(),before);self.assertTrue((self.session/'analysis-error.zip').is_file());self.assertIn('ParseError',(self.session/'analysis-error-local.txt').read_text())
 def test_atomic_zip_preserves_good_archive_on_write_failure(self):
  dest=self.root/'a.zip';p.atomic_zip(dest,{'old':b'old'});before=dest.read_bytes()
  with patch.object(p.zipfile.ZipFile,'writestr',side_effect=OSError('synthetic disk full')):
   with self.assertRaises(OSError):p.atomic_zip(dest,{'new':b'new'})
  self.assertEqual(dest.read_bytes(),before);self.assertFalse(list(self.root.glob('*.tmp')))
 def test_atomic_zip_preserves_good_archive_on_replace_failure(self):
  dest=self.root/'a.zip';p.atomic_zip(dest,{'old':b'old'});before=dest.read_bytes()
  with patch.object(p.os,'replace',side_effect=OSError('synthetic permission')):
   with self.assertRaises(OSError):p.atomic_zip(dest,{'new':b'new'})
  self.assertEqual(dest.read_bytes(),before)
 def test_early_recorder_failure_no_capture(self):
  game=Mock(pid=123);game.poll.return_value=None;rec=Mock();rec.wait.return_value=8
  with patch.object(p,'verify_pid'),patch.object(p.subprocess,'Popen',return_value=rec):self.assertEqual(p.record(game,self.exe,self.root,'metal',8),8)
  game.terminate.assert_not_called();rec.kill.assert_not_called()
 def test_all_shutdown_timeouts_report_unconfirmed(self):
  child=Mock();child.poll.return_value=None;child.wait.side_effect=subprocess.TimeoutExpired('synthetic',.01)
  result=p.stop_recorder(child,(.01,.01,.01));self.assertFalse(result['confirmed']);child.send_signal.assert_called_once();child.terminate.assert_called_once();child.kill.assert_called_once()
 def test_recorder_exit_signal_race(self):
  child=Mock();child.poll.return_value=None;child.send_signal.side_effect=ProcessLookupError;child.wait.return_value=0
  result=p.stop_recorder(child);self.assertTrue(result['confirmed']);child.kill.assert_not_called()
 def test_ctrl_c_during_shutdown_bounded(self):
  child=Mock();child.poll.return_value=None;child.wait.side_effect=KeyboardInterrupt
  result=p.stop_recorder(child,(.01,.01,.01));self.assertFalse(result['confirmed']);self.assertEqual(result['interrupts'],9);child.kill.assert_called_once()
 def test_sigint_shutdown_reaps(self):
  child=Mock();child.poll.return_value=None;child.wait.return_value=-2
  result=p.stop_recorder(child);self.assertTrue(result['confirmed']);child.terminate.assert_not_called()
 def test_cleanup_failure_has_error_zip(self):
  code,d=self.simulate_session(recorder_error='recorder_shutdown_unconfirmed');self.assertEqual(code,1);self.assertIn('recorder_shutdown_unconfirmed',d['error_codes']);self.assertTrue((self.session/'safe-summary.zip').exists());self.assertTrue((self.session/'recording.trace').exists())
 def test_real_stubborn_recorder_is_killed_reaped_only(self):
  child=subprocess.Popen([sys.executable,str(p.HERE/'mock_recorder.py'),'--ignore-signals'],stdout=subprocess.PIPE,text=True,start_new_session=True)
  unrelated=subprocess.Popen(['/bin/sleep','30'],start_new_session=True)
  try:
   self.assertEqual(child.stdout.readline().strip(),'ready');start=time.monotonic()
   result=p.stop_recorder(child,(.05,.05,.5));self.assertTrue(result['confirmed']);self.assertEqual(result['stage'],'kill');self.assertLess(time.monotonic()-start,2);self.assertIsNotNone(child.poll());self.assertIsNone(unrelated.poll())
  finally:
   if child.poll() is None:child.kill();child.wait()
   child.stdout.close();unrelated.terminate();unrelated.wait()
 def test_real_record_timeout_reports_cleanup(self):
  child=subprocess.Popen([sys.executable,str(p.HERE/'mock_recorder.py'),'--ignore-signals'],stdout=subprocess.PIPE,text=True,start_new_session=True)
  game=Mock(pid=123);game.poll.return_value=None
  try:
   self.assertEqual(child.stdout.readline().strip(),'ready')
   with patch.object(p,'verify_pid'),patch.object(p.subprocess,'Popen',return_value=child):
    with self.assertRaises(p.RecorderError) as c:p.record(game,self.exe,self.root,'metal',8,completion_timeout=.05,shutdown_timeouts=(.05,.05,.5))
   self.assertTrue(c.exception.cleanup['confirmed']);self.assertEqual(c.exception.code,'recorder_timeout');game.terminate.assert_not_called();self.assertTrue((self.root/'recorder-shutdown-local.json').exists())
  finally:
   if child.poll() is None:child.kill();child.wait()
   child.stdout.close()
 def test_duplicate_runtime_frame_rejected(self):
  text=self.log().replace('frame 360','frame 300');self.assertIn('nonmonotonic_frames',p.measurements(text,'A')['errors'])
 def test_backward_timestamp_rejected(self):
  text='\n'.join(reversed(self.log().splitlines()));self.assertIn('nonmonotonic_timestamps',p.measurements(text,'A')['errors'])
 def test_short_long_window_rejected(self):self.assertIn('insufficient_time_coverage',p.measurements(self.log(),'A',25)['errors'])
 def test_missing_runtime_period_rejected(self):self.assertIn('missing_runtime_periods',p.measurements(self.log().replace('t=14','t=20'),'A')['errors'])
 def test_nan_runtime_rejected(self):self.assertIn('invalid_runtime_row',p.measurements(self.log().replace('30.0 fps','nan fps'),'A')['errors'])
 def test_zero_runtime_timing_rejected(self):self.assertIn('nonpositive_timing',p.measurements(self.log().replace('30.0 fps','0 fps'),'A')['errors'])
 def test_missing_gpu_timing_explicitly_unavailable(self):
  d=p.measurements(self.log().replace('gpu 600ms, ',''),'A');self.assertFalse(d['errors']);self.assertEqual(d['asynchronous_gpu_ms_per_present_proxy']['samples'],0);self.assertEqual(d['asynchronous_gpu_ms_per_present_proxy']['status'],'unavailable')
 def test_missing_partial_gpu_intervals_rejected(self):
  text=self.log().replace('t=12 frame 360 30.0 fps max 34ms level KeyCavern (gpu 600ms,','t=12 frame 360 30.0 fps max 34ms level KeyCavern (')
  self.assertIn('missing_proxy_intervals',p.measurements(text,'A')['errors'])
 def test_stale_warmup_rejected(self):
  with self.assertRaises(p.Invalid):p.validate_warmup('', 'A',30,self.log())
 def test_old_replayed_warmup_rejected(self):
  with self.assertRaises(p.Invalid):p.validate_warmup(self.log(),'A',4,self.log())
 def test_full_session_duplicate_not_ready(self):
  code,d=self.simulate_session(sample_mode='duplicate');self.assertEqual(code,1);self.assertFalse(d['capture_validated']);self.assertIn('nonmonotonic_frames',d['metrics']['errors']);self.assertEqual(d['metrics']['runtime_fps_periodic']['samples'],0)
 def test_full_session_short_not_ready(self):
  code,d=self.simulate_session(sample_mode='short');self.assertEqual(code,1);self.assertIn('insufficient_time_coverage',d['metrics']['errors'])
 def test_full_session_backward_not_ready(self):
  code,d=self.simulate_session(sample_mode='backward');self.assertEqual(code,1);self.assertIn('nonmonotonic_timestamps',d['metrics']['errors'])
 def test_full_session_stale_warmup_not_ready(self):
  code,d=self.simulate_session(sample_mode='stale');self.assertEqual(code,1);self.assertIn('runtime_log_stale',d['error_codes'])
 def test_graphics_change_not_ready(self):
  code,d=self.simulate_session(settings_change=True);self.assertEqual(code,1);self.assertIn('graphics_settings_changed',d['metrics']['errors'])
 def valid_comparison(self):
  def make(id):
   return {'session_id':f'20261025T035000Z-A-baseline-2880x1800-overview-stationary-{id:08x}','scenario':'A','method':'overview','motion':'stationary','status':'capture_ready_for_manual_trace_review',
    'workload':{'scene':'KeyCavern','position':'historical-key-cavern-position','confirmation':True},'executable_sha256':'a'*64,'library_sha256':'b'*64,'expected_drawable':[2880,1800],
    'requested_graphics':{'fullscreen':True,'aspect':'original','antialias':'off','dynamic':False,'resolution':'match','upscaler':'metalfx'},
    'observed':{'drawable_observed':[2880,1800],'render_scale_observed':[1.5,1.5],'render_area_derived_not_observed':[2880,1620]},
    'renderer':'baseline','renderer_optimization':{'name':'LARECOMP_DEPTH_NO_FS','value':0},'pid_executable_verified':True,'loaded_library_verified':True,'trace_pid_verified':True,'user_confirmed_graphics_and_scene':True,
    'recording':{'requested_seconds':25},'environment':{'power_source':'battery','low_power_mode_by_source':{'Battery Power':0,'AC Power':0},'gpu_display_thermal':{'thermal_state':0}}}
  return make(1),make(2)
 def test_resolution_comparison_accepts_A_B(self):
  x,y=self.valid_comparison();y['scenario']='B';y['session_id']=y['session_id'].replace('-A-','-B-');y['requested_graphics']['resolution']='1';y['observed']['render_scale_observed']=[1.,1.];y['observed']['render_area_derived_not_observed']=[1920,1080]
  self.assertTrue(a.compare(x,y,'resolution')['compatible_metadata'])
 def test_renderer_AB_accepts_only_flag_change(self):
  x,y=self.valid_comparison();y['renderer']='experimental';y['session_id']=y['session_id'].replace('-baseline-','-experimental-');y['renderer_optimization']['value']=1;self.assertTrue(a.compare(x,y,'renderer')['compatible_metadata'])
 def test_repeatability_accepts_same_settings(self):x,y=self.valid_comparison();self.assertTrue(a.compare(x,y)['compatible_metadata'])
 def test_library_hash_mismatch_rejected(self):
  x,y=self.valid_comparison();y['library_sha256']='c'*64
  for purpose in ['renderer','resolution','repeatability']:
   with self.subTest(purpose=purpose),self.assertRaises(p.Invalid):a.compare(x,y,purpose)
 def test_comparison_required_identities_not_absent(self):
  x,y=self.valid_comparison();del x['library_sha256'];del y['library_sha256']
  with self.assertRaises(p.Invalid):a.compare(x,y)
 def test_comparison_mismatch_matrix(self):
  changes=[('executable_sha256','c'*64),('method','metal'),('motion','movement'),('expected_drawable',[2048,1280]),('workload.scene','Goponga'),('requested_graphics.upscaler','bilinear'),('requested_graphics.antialias','smaa'),('requested_graphics.aspect','unlocked')]
  for path,value in changes:
   x,y=self.valid_comparison();target=y;keys=path.split('.')
   for k in keys[:-1]:target=target[k]
   target[keys[-1]]=value
   with self.subTest(path=path),self.assertRaises(p.Invalid):a.compare(x,y)
 def test_environment_difference_reported(self):
  x,y=self.valid_comparison();y['environment']['power_source']='AC';self.assertIn('environment.power_source',a.compare(x,y)['environment_differences'])
 def test_resolution_not_allowed_for_renderer(self):
  x,y=self.valid_comparison();y['requested_graphics']['resolution']='1'
  with self.assertRaises(p.Invalid):a.compare(x,y,'renderer')
 def test_selected_duplicate_frame_rejected(self):
  path=base_tests.Tests.csv(self);s=path.read_text().replace(',2.5,1\n',',2.5,0\n');path.write_text(s)
  with self.assertRaises(p.Invalid):a.read_samples(path,'fixture',123,'overview')
 def test_selected_backward_time_rejected(self):
  path=base_tests.Tests.csv(self);path.write_text(path.read_text().replace(',2.5,1\n',',1.5,1\n'))
  with self.assertRaises(p.Invalid):a.read_samples(path,'fixture',123,'overview')
 def test_selected_short_coverage_rejected(self):
  path=base_tests.Tests.csv(self);path.write_text('\n'.join(path.read_text().splitlines()[:4])+'\n')
  with self.assertRaises(p.Invalid):a.read_samples(path,'fixture',123,'overview')
 def test_command_buffers_same_frame_are_allowed(self):
  path=base_tests.Tests.csv(self);lines=path.read_text().replace('gpu_execution_ms','command_buffer_gpu_ms').splitlines();items=list(csv.DictReader(lines))
  for r in items:r['frame_id']='0'
  with path.open('w',newline='') as f:w=csv.DictWriter(f,fieldnames=items[0]);w.writeheader();w.writerows(items)
  self.assertIn('command_buffer_gpu_ms',a.read_samples(path,'fixture',123,'overview')['metrics'])
 def test_copy_failure_preserves_synthetic_source(self):
  before=(self.save/'slot').read_bytes();dest=self.root/'private';dest.mkdir()
  with patch.object(isolation.shutil,'copytree',side_effect=OSError('synthetic copy failure')):
   with self.assertRaises(OSError):isolation.prepare_private_run(dest,self.settings,self.save,self.data,{})
  self.assertEqual((self.save/'slot').read_bytes(),before)
 def test_helper_drift_rejected(self):
  with self.assertRaises(p.Invalid) as c:p.check_helper('0'*64)
  self.assertEqual(c.exception.code,'helper_drift')
 def test_discovery_save_root_symlink_rejected(self):
  link=self.data/'save-link';link.symlink_to(self.save,target_is_directory=True)
  args=Mock(data_root=str(self.data),settings=str(self.settings),save_dir=str(link))
  with self.assertRaises(ValueError):isolation.data_paths(args,repo=self.repo)
 def test_nested_privacy_sentinels_are_removed(self):
  marker='/Users/private/SECRET-SENTINEL.shader'
  x,y=self.valid_comparison();x['requested_graphics']['upscaler']=marker;x['observed']['source_texture_dimensions']=marker
  x['environment']={'model':marker,'power_source':marker,'gpu_display_thermal':{'gpu':marker,'thermal_state':marker,'display_points':[{'filename':marker}]}}
  x['recording']={'begin_utc':marker,'motion':marker,'shutdown':{'stage':marker,'extra':{'path':marker}}};x['workload']['position']=marker;x['warnings']=[marker];x['error_codes']=[marker];x['profiling_sources_sha256']={'isolation.py':marker};x['git_branch']=marker;x['session_id']=marker
  archive=p.write_safe(self.root,x,{'runtime_fps_periodic':{'median':marker,'p95':float('nan'),'extra':{'id':marker}},'errors':[marker]})
  with zipfile.ZipFile(archive) as z:
   data=b''.join(z.read(n) for n in z.namelist());self.assertNotIn(marker.encode(),data);self.assertNotIn(b'NaN',data);self.assertEqual(set(z.namelist()),p.SAFE_NAMES)
 def test_analysis_nested_sentinel_removed(self):
  value=a.sanitize_analysis({'session_id':'/private/secret','selected_metrics':{'metrics':{'gpu_execution_ms':{'median':{'path':'/private/secret'}}}},'trace_inventory':{'schemas':['/private/secret']}})
  self.assertNotIn('/private/secret',json.dumps(value))
 def test_huge_numeric_metadata_is_bounded(self):
  self.assertIsNone(privacy.number(10**10000))
 def test_review_metadata_sentinels_removed(self):
  for kind in privacy.REVIEW_SCHEMAS:
   self.assertNotIn('/private/SENTINEL',json.dumps(privacy.review_record(kind,{'nested':{'path':'/private/SENTINEL'},'head':'/private/SENTINEL'})))
 def analysis_failure_retry(self,kind):
  good,_=self.valid_comparison()
  for key in ['workload','requested_graphics','renderer','renderer_optimization']:self.meta[key]=copy.deepcopy(good[key])
  code,_=self.simulate_session();self.assertEqual(code,0)
  manifest=self.session/'manifest-local.json';original_manifest=manifest.read_bytes()
  capture=json.loads(original_manifest);safe=self.session/'safe'
  original_sidecars={f.name:f.read_bytes() for f in safe.iterdir() if f.is_file()}
  archive=self.session/'safe-summary.zip';original_zip=archive.read_bytes()
  other=json.loads((safe/'summary.json').read_text());other['session_id']=other['session_id'][:-8]+('00000000' if other['session_id'].endswith('ffffffff') else 'ffffffff')
  other_path=self.root/'comparison.json';other_path.write_text(json.dumps(other))
  csv_path=base_tests.Tests.csv(self);valid_csv=csv_path.read_text().replace('fixture,',capture['session_id']+',');csv_path.write_text(valid_csv)
  options=[]
  if kind=='missing':options=['--samples',str(self.root/'mistyped.csv')]
  if kind=='invalid':csv_path.write_text('invalid CSV');options=['--samples',str(csv_path)]
  if kind=='comparison':
   mismatch=copy.deepcopy(other);mismatch['library_sha256']='c'*64;other_path.write_text(json.dumps(mismatch));options=['--compare',str(other_path)]
  def export(args,*unused,**kwargs):
   Path(args[args.index('--output')+1]).write_text('<broken>' if self.bad_toc else '<trace-toc><run><info><target><process pid="123"/></target></info><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>');return 0,''
  self.bad_toc=kind=='toc'
  with patch.object(sys,'argv',['analyze.py',str(self.session),*options]),patch.object(p,'command',side_effect=export):self.assertEqual(a.main(),1)
  self.assertEqual(manifest.read_bytes(),original_manifest);self.assertEqual(archive.read_bytes(),original_zip)
  self.assertEqual({f.name:f.read_bytes() for f in safe.iterdir() if f.is_file()},original_sidecars)
  failure=json.loads((self.session/'analysis-status.json').read_text());self.assertEqual(failure['status'],'analysis_failed');self.assertEqual(failure['trace_review_required'],kind=='toc')
  with zipfile.ZipFile(self.session/'analysis-error.zip') as z:
   self.assertEqual(json.loads(z.read('analysis.json'))['status'],'analysis_failed');self.assertEqual(json.loads(z.read('summary.json'))['status'],capture['status']);self.assertEqual(json.loads(z.read('measurements.json')),json.loads(original_sidecars['measurements.json']))
  self.bad_toc=False;csv_path.write_text(valid_csv);other_path.write_text(json.dumps(other))
  with patch.object(sys,'argv',['analyze.py',str(self.session),'--samples',str(csv_path),'--compare',str(other_path)]),patch.object(p,'command',side_effect=export):self.assertEqual(a.main(),0)
  self.assertEqual(manifest.read_bytes(),original_manifest);self.assertEqual({f.name:f.read_bytes() for f in safe.iterdir() if f.is_file()},original_sidecars)
  result=json.loads((self.session/'analysis-status.json').read_text());self.assertEqual(result['status'],'analysis_complete');self.assertFalse(result['trace_review_required']);self.assertNotIn('error_codes',result)
  with zipfile.ZipFile(archive) as z:
   summary=json.loads(z.read('summary.json'));self.assertEqual(summary,json.loads(original_sidecars['summary.json']));self.assertTrue(summary['capture_validated']);self.assertEqual(json.loads(z.read('measurements.json')),json.loads(original_sidecars['measurements.json']));self.assertEqual(json.loads(z.read('analysis.json'))['status'],'analysis_complete')
  self.assertTrue(a.compare(summary,other)['compatible_metadata'])
 def test_analysis_missing_samples_corrected_retry(self):self.analysis_failure_retry('missing')
 def test_analysis_invalid_samples_corrected_retry(self):self.analysis_failure_retry('invalid')
 def test_analysis_comparison_corrected_retry(self):self.analysis_failure_retry('comparison')
 def test_analysis_malformed_trace_corrected_retry(self):self.analysis_failure_retry('toc')
 def test_clean_packaged_installation(self):
  source=Path(p.__file__).resolve().parent;dest=self.root/'clean';dest.mkdir()
  for name in setup_check.verify(source)['files']:shutil.copyfile(source/name,dest/name)
  shutil.copyfile(source/'DEPENDENCIES.json',dest/'DEPENDENCIES.json')
  for args in [[str(dest/'profile.py'),'--self-check'],[str(dest/'setup_check.py'),'--fixture-dry-run']]:
   result=subprocess.run([sys.executable,'-B',*args],cwd=dest,capture_output=True,text=True,timeout=30);self.assertEqual(result.returncode,0,result.stdout+result.stderr)
  bootstrap='import profile,runpy; from pathlib import Path; profile.REPO=Path("/nonexistent-checkout-audit-fixture"); runpy.run_path("test_profiling.py",run_name="__main__")'
  result=subprocess.run([sys.executable,'-B','-c',bootstrap],cwd=dest,capture_output=True,text=True,timeout=30)
  self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('Ran 59 tests',result.stderr)

if __name__=='__main__':unittest.main(verbosity=2)
