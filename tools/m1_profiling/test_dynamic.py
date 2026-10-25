#!/usr/bin/env python3
"""Synthetic manual-session fixtures only. Never loads game code or accesses real saves."""
import argparse,copy,json,math,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
import profile as p
import dynamic_log as log
import dynamic_observe as run
import test_profiling as base

class DynamicTests(unittest.TestCase):
 setUp=base.Tests.setUp
 tearDown=base.Tests.tearDown
 def make_args(self,**overrides):
  data=dict(dynamic='key-cavern',dynamic_trace=None,phase_seconds=60,warmup=30,dry_run=False,method='overview',scenario='A',motion='stationary',seconds=None,data_root=None,settings=None,save_dir=None)
  data.update(overrides);return argparse.Namespace(**data)
 def phases(self):return [{'name':n,'begin_s':40+i*60,'end_s':100+i*60} for i,n in enumerate(log.PHASES)]
 def events(self,key='key-cavern',gpu=True):
  values=[];previous=.8
  values.append(log.parse_line('[scale] frame 1 drawable 2880x1800 -> render scale '+('1.000x1.000' if key=='fixed-1x' else '1.200x1.200')+' (reshape 0)',0,key))
  for i in range(221):
   factor=.5 if 100<i<=160 else .8
   line=f'[metal] t={100+i} frame {6000+i*60} 60.0 fps max 17ms level '+('Field_01' if key=='goponga' else 'KeyCavern')+' ('+('gpu 660ms, ' if gpu else '')+'compile 0/0, pace 60)'
   values.append(log.parse_line(line,float(i),key))
   if key!='fixed-1x':
    values.append(log.parse_line(f'[dynres] {previous:.2f} -> {factor:.2f} (frame 16.7 ms, median 16.7, 0 spikes left out, gpu 12.0 ms = game 11.0 + window 1.0, budget 14.5, next raise in 5 s; spans summed 14.0 ms)',i+.01,key));previous=factor
  return sorted(values,key=lambda e:e['observed_s'])
 def report(self,events=None,key='key-cavern',phases=None):return log.analyze(self.events(key) if events is None else events,self.phases() if phases is None else phases,key)
 def test_dynamic_private_settings_exact(self):
  before=self.settings.read_bytes();original=(self.save/'slot').read_bytes()
  for i,key in enumerate(log.SCENARIOS):
   env=run.configure(self.root/f'private{i}',(self.helper,self.data,self.settings,self.save,self.exe,self.lib),key,{'LARECOMP_DYN_TEST':'.1','LARECOMP_LOG_PACE':'1','LARECOMP_DEPTH_NO_FS':'1','MTL_HUD_ENABLED':'1'})
   values=self.helper.ini_values(Path(env['LARECOMP_SETTINGS']));self.assertEqual(values['resolution'],'1' if key=='fixed-1x' else 'dynamic');self.assertEqual(values['upscaler'],'metalfx');self.assertEqual(values['antialias'],'off');self.assertEqual(values['aspect'],'original');self.assertEqual(values['fullscreen'],'1')
   self.assertEqual(env['LARECOMP_DEPTH_NO_FS'],'0');self.assertEqual(env['LARECOMP_LOG_DYNRES'],'1');self.assertEqual(env['LARECOMP_FPS_INTERVAL'],'1');self.assertEqual(env['LARECOMP_LOG_HITCH_MS'],'40')
   for flag in ['LARECOMP_DYN_TEST','LARECOMP_LOG_PACE','LARECOMP_DEPTH_PROBE','MTL_HUD_ENABLED']:self.assertNotIn(flag,env)
   Path(env['LARECOMP_SAVE_DIR'],'slot').write_bytes(b'private test')
  self.assertEqual(self.settings.read_bytes(),before);self.assertEqual((self.save/'slot').read_bytes(),original)
 def test_actual_decision_format(self):
  e=self.events()[2];decisions=[e for e in self.events() if e['type']=='decision'];self.assertEqual(decisions[0]['factor'],.8);self.assertEqual(decisions[0]['gpu_window_ms'],1);self.assertEqual(decisions[0]['spans_sum_ms'],14)
 def test_normal_manual_three_phases(self):
  r=self.report();self.assertEqual(r['errors'],[]);self.assertEqual([x['phase'] for x in r['phases']],list(log.PHASES));self.assertEqual(r['phases'][0]['fps_one_second_blocks']['median'],60);self.assertEqual(r['phases'][1]['factor']['median_time_weighted'],.5);self.assertEqual(r['phases'][0]['factor']['median_time_weighted'],.8)
 def test_time_weighted_occupancy(self):
  r=self.report();phase=r['phases'][1];self.assertAlmostEqual(sum(x['seconds'] for x in phase['factor']['seconds_by_factor'])+phase['factor']['unknown_seconds'],56);self.assertEqual(phase['factor']['below_fixed_1x_seconds'],56)
 def test_recovery_after_movement(self):
  r=self.report()['recovery'];self.assertEqual(r['status'],'reached_initial_quality');self.assertAlmostEqual(r['seconds_to_sustain_target_for_5s'],1.01,places=2)
 def test_recovery_censored_not_defect(self):
  events=self.events()
  for e in events:
   if e['type']=='decision' and e['observed_s']>160:e['factor']=.5
  r=self.report(events)['recovery'];self.assertIsNone(r['seconds_to_sustain_target_for_5s']);self.assertIn('censored',r['status'])
 def test_goponga_manual_location(self):self.assertFalse(self.report(key='goponga')['errors'])
 def test_fixed_control_no_dynamic_required(self):self.assertFalse(self.report(key='fixed-1x')['errors']);self.assertIn('not applicable',self.report(key='fixed-1x')['recovery']['status'])
 def test_startup_window_transition_excluded(self):
  events=self.events();events[0]['width']=1280;events.append(log.parse_line('[scale] frame 2 drawable 2880x1800 -> render scale 1.200x1.200 (reshape 0)',5,'key-cavern'));self.assertFalse(self.report(sorted(events,key=lambda e:e['observed_s']))['errors'])
 def test_recovery_in_different_room_not_comparable(self):
  events=self.events()
  for e in events:
   if e['type']=='fps' and e['observed_s']>=160:e['level_id']='f'*64
  r=self.report(events);self.assertIn('scene_mismatch',r['phases'][2]['quality_flags']);self.assertEqual(r['recovery']['status'],'unavailable')
 def write_analysis_inputs(self,events=None):
  meta=dict(self.meta,session_id='20261025T010000Z-DA-baseline-2880x1800-dynamic-log-phased-12345678',scenario='DA',method='dynamic-log',status='dynamic_observation_ready_for_review')
  p.dump(self.root/'manifest-local.json',meta);p.dump(self.root/'events-local.json',{'session_id':meta['session_id'],'scenario':'DA','events':self.events() if events is None else events});p.dump(self.root/'phases-local.json',{'session_id':meta['session_id'],'scenario':'DA','phases':self.phases()});run.save_bundle(self.root,meta,self.events(),self.phases(),self.report())
 def test_reanalysis_wrong_session_keeps_original_zip(self):
  self.write_analysis_inputs();archive=self.root/'safe-summary.zip';before=archive.read_bytes();d=json.loads((self.root/'events-local.json').read_text());d['session_id']='wrong';p.dump(self.root/'events-local.json',d)
  with patch.object(sys,'argv',['dynamic_log.py',str(self.root)]):self.assertEqual(log.main(),1)
  self.assertEqual(archive.read_bytes(),before)
 def test_reanalysis_insufficient_keeps_original_retry_works(self):
  self.write_analysis_inputs([]);archive=self.root/'safe-summary.zip';before=archive.read_bytes();manifest=(self.root/'manifest-local.json').read_bytes();sidecars={x.name:x.read_bytes() for x in (self.root/'safe').iterdir()}
  with patch.object(sys,'argv',['dynamic_log.py',str(self.root)]):self.assertEqual(log.main(),1)
  self.assertEqual(archive.read_bytes(),before);self.assertEqual((self.root/'manifest-local.json').read_bytes(),manifest);self.assertTrue((self.root/'dynamic-analysis-error.zip').exists())
  meta=json.loads(manifest);p.dump(self.root/'events-local.json',{'session_id':meta['session_id'],'scenario':'DA','events':self.events()})
  with patch.object(sys,'argv',['dynamic_log.py',str(self.root)]):self.assertEqual(log.main(),0)
  self.assertEqual((self.root/'manifest-local.json').read_bytes(),manifest);self.assertEqual({x.name:x.read_bytes() for x in (self.root/'safe').iterdir()},sidecars)
 def test_missing_dynamic_metrics_invalid(self):self.assertIn('dynamic_missing',self.report([e for e in self.events() if e['type']!='decision'])['errors'])
 def test_missing_scale_no_assumed_resolution(self):self.assertIn('scale_missing',self.report([e for e in self.events() if e['type']!='scale'])['errors'])
 def test_missing_gpu_explicit_unavailable(self):
  self.assertEqual(self.report(self.events(gpu=False))['phases'][0]['game_gpu_interval_per_present_proxy_ms']['samples'],0)
  event=log.parse_line('[dynres] 0.80 -> 0.80 (frame 16.7 ms, median 16.7, 0 spikes left out, gpu -1.0 ms = game -1.0 + window 0.0, budget 14.5, next raise in 5 s)',1,'key-cavern');self.assertIsNone(event['gpu_window_ms'])
 def test_wrong_drawable_invalid(self):
  events=self.events();events[0]['width']=2048;self.assertIn('drawable_mismatch',self.report(events)['errors'])
 def test_compilation_retained_excluded(self):
  events=self.events();next(e for e in events if e['type']=='fps' and e['observed_s']==50)['compile']=1;self.assertIn('compilation',self.report(events)['phases'][0]['quality_flags'])
 def test_source_duplicate_backward_rejected(self):
  events=self.events();fps=[e for e in events if e['type']=='fps'];fps[51]['frame']=fps[50]['frame'];fps[51]['source_t']=fps[50]['source_t'];self.assertIn('nonmonotonic_runtime',self.report(events)['errors'])
 def test_missing_periods_not_padded(self):
  events=[e for e in self.events() if not(e['type']=='fps' and 50<e['observed_s']<65)];r=self.report(events);self.assertIn('missing_periods',r['errors']);self.assertLess(r['phases'][0]['measured_runtime_seconds'],56)
 def test_phase_boundaries_missing_or_reordered(self):
  self.assertIn('invalid_boundaries',self.report(phases=self.phases()[:2])['errors']);self.assertIn('invalid_boundaries',self.report(phases=list(reversed(self.phases())))['errors'])
 def test_phase_edge_loading_not_steady(self):
  events=self.events();next(e for e in events if e['type']=='fps' and e['observed_s']==100)['compile']=3;r=self.report(events);self.assertEqual(r['errors'],[])
 def test_explicit_phase_contamination(self):self.assertIn('user_contamination',log.analyze(self.events(),self.phases(),'key-cavern',['movement'])['phases'][1]['quality_flags'])
 def test_hold_metrics_separate(self):
  events=self.events();events.append({'type':'pace','observed_s':101,'hold':30})
  for e in events:
   if e['type']=='decision' and 100<e['observed_s']<160:e['hold_fps']=30
   if e['type']=='fps' and 100<e['observed_s']<160:e['pace']=30
  r=self.report(sorted(events,key=lambda e:e['observed_s']));self.assertEqual(r['phases'][1]['dynamic_hold_30_seconds'],56);self.assertEqual(r['phases'][1]['pace_hold_30_seconds'],56)
 def test_hitches_preserved_as_present_gaps(self):
  events=self.events()+[log.parse_line('[hitch] t=151.00 frame 9060 gap 120 ms',51,'key-cavern')];r=self.report(sorted(events,key=lambda e:e['observed_s']));self.assertEqual(r['phases'][0]['hitches_over_40ms']['count'],1);self.assertEqual(r['phases'][0]['hitches_over_40ms']['gap_sum_ms'],120)
 def test_metalfx_failure_not_assumed_working(self):
  events=self.events()+[log.parse_line('[metalfx] spatial scaler not supported on this GPU',3,'key-cavern')];self.assertIn('metalfx_failed',self.report(sorted(events,key=lambda e:e['observed_s']))['errors'])
 def test_actual_metalfx_allocation_not_content(self):
  e=log.parse_line('[metalfx] 2880x1620 -> 2880x1620 (ok)',1,'key-cavern');self.assertEqual(e['input_allocation'],[2880,1620]);self.assertNotIn('internal_content',e)
 def test_collector_partial_and_unsafe_lines(self):
  path=self.root/'log';path.write_text('secret shader /private/DO-NOT-SHARE\n[scale] frame 1 drawable 2880x1800 -> render scale 1.000')
  c=log.Collector(path,'key-cavern',10);c.poll(11);self.assertFalse(c.events)
  with path.open('a') as f:f.write('x1.000 (reshape 0)\n')
  c.poll(12);self.assertEqual(c.events[0]['type'],'scale');self.assertNotIn('DO-NOT-SHARE',json.dumps(c.events))
 def test_observer_clock_backward_invalid(self):
  events=self.events();events[10]['observed_s']=-1;self.assertIn('nonmonotonic_runtime',self.report(events)['errors'])
 def test_safe_dynamic_zip_allowlist(self):
  report=self.report();meta=dict(self.meta,session_id='20261025T010000Z-DA-baseline-2880x1800-dynamic-log-phased-12345678',scenario='DA',method='dynamic-log',status='dynamic_observation_ready_for_review')
  meta['requested_graphics']={'upscaler':'/private/secret'};(self.root/'runtime-local.log').write_text('secret raw asset')
  archive=run.save_bundle(self.root,meta,self.events(),self.phases(),report)
  with zipfile.ZipFile(archive) as z:self.assertEqual(set(z.namelist()),run.SAFE_FILES);self.assertNotIn(b'/private/secret',b''.join(z.read(n) for n in z.namelist()));self.assertNotIn(b'secret raw asset',b''.join(z.read(n) for n in z.namelist()))
 def test_preflight_missing_log_support(self):
  with patch.object(p,'preflight',return_value=(copy.deepcopy(self.meta),(self.helper,self.data,self.settings,self.save,self.exe,self.lib))):
   with self.assertRaises(p.Invalid):run.preflight(self.make_args())
 def test_preflight_propagates_missing_exe_or_dependency(self):
  with patch.object(p,'preflight',side_effect=p.Invalid('missing dependency')):
   with self.assertRaises(p.Invalid):run.preflight(self.make_args())
 def test_cli_dispatch_dry_run_no_game(self):
  with patch.object(sys,'argv',['profile.py','--dynamic','key-cavern','--dry-run']),patch.object(run,'run',return_value=0) as runner:
   self.assertEqual(p.main(),0);self.assertEqual(runner.call_args[0][0].dynamic,'key-cavern');self.assertTrue(runner.call_args[0][0].dry_run)
 def test_scenario_identity_mapping(self):self.assertEqual([x['id'] for x in log.SCENARIOS.values()],['DA','DB','DC','DK']);self.assertEqual(p.SCENARIOS['B']['resolution'],'1')
 def mock_session(self,interrupt=False,early_exit=False,trace=False,visual='NONE',finalization_error=False):
  original=(self.save/'slot').read_bytes();proc=Mock(pid=123);proc.poll.return_value=2 if early_exit else None;proc.wait.return_value=2 if early_exit else 0
  cfg=log.SCENARIOS['key-cavern'];meta=copy.deepcopy(self.meta);meta.update(scenario='DA',method='dynamic-metal' if trace else 'dynamic-log',motion='stationary' if trace else 'phased',requested_graphics={'resolution':'dynamic','dynamic':True,'upscaler':'metalfx','fullscreen':True,'aspect':'original','antialias':'off'})
  state={'now':1000.};events=self.events()
  def launch(*args,**kwargs):kwargs['stdout'].write((f'[gamelib] {self.lib} (1 + 1 functions)\n[depth-no-fs] experimental=0\n').encode());return proc
  def span(process,c,seconds,*unused,**kwargs):
   if interrupt and seconds==60:raise KeyboardInterrupt()
   begin=state['now']-c.start;state['now']+=seconds;end=state['now']-c.start;c.events=copy.deepcopy([e for e in events if e['observed_s']<=end]);c.offset=c.path.stat().st_size;return begin,end
  def record(game,exe,session,method,seconds):
   self.assertEqual(method,'metal');self.assertEqual(seconds,8);(session/'recording.trace').mkdir();(session/'recording.trace/data').write_text('fixture');return 0
  def command(args,*unused,**kwargs):Path(args[args.index('--output')+1]).write_text('<trace-toc><run><info><target><process pid="123"/></target></info><data><table schema="metal-gpu-intervals"/></data></run></trace-toc>');return 0,''
  with patch.object(log.Collector,'finish',side_effect=OSError('synthetic finalization failure') if finalization_error else None),patch.object(p,'command',side_effect=command),patch.object(p,'HERE',self.root),patch.object(run,'preflight',return_value=(meta,(self.helper,self.data,self.settings,self.save,self.exe,self.lib))),patch.object(sys.stdin,'isatty',return_value=True),patch('builtins.input',side_effect=['LAUNCH','READY','CLEAN',visual]),patch.object(p,'conflicts',return_value=[]),patch.object(p,'verify_pid'),patch.object(p,'record',side_effect=record if trace else AssertionError('ordinary Dynamic must not invoke Instruments')),patch.object(p,'environment_metadata',return_value={}),patch.object(p.subprocess,'Popen',side_effect=launch),patch.object(run,'observe_span',side_effect=span),patch.object(run.time,'monotonic',side_effect=lambda:state['now']),patch.object(run.time,'sleep'):
   # Start validation needs only the actual loaded-library/banner plus known scale/decision observations.
   code=run.run(self.make_args(dynamic_trace='metal' if trace else None))
  session=next((self.root/'sessions').iterdir());summary=json.loads((session/'safe/summary.json').read_text());self.assertTrue((session/'private/save/slot').exists());self.assertEqual((self.save/'slot').read_bytes(),original);proc.terminate.assert_not_called();return code,session,summary
 def test_full_mock_dynamic_no_instruments(self):
  code,session,summary=self.mock_session();self.assertEqual(code,0);self.assertTrue(summary['observation_validated']);self.assertFalse(summary['capture_validated']);self.assertEqual(summary['capture_scope'],'lightweight runtime log observation');self.assertFalse((session/'recording.trace').exists())
 def test_interruption_keeps_private_saves(self):
  code,session,summary=self.mock_session(interrupt=True);self.assertEqual(code,1);self.assertFalse(summary['capture_validated']);self.assertTrue((session/'safe-summary.zip').exists())
 def test_optional_focused_trace_separate(self):
  code,session,summary=self.mock_session(trace=True);self.assertEqual(code,0);self.assertEqual(summary['method'],'dynamic-metal');self.assertTrue(summary['trace_pid_verified']);self.assertTrue((session/'recording.trace').exists());self.assertFalse(json.loads((session/'safe/dynamic-report.json').read_text())['phases'])
 def test_visual_issue_is_reported_not_inferred(self):
  code,session,summary=self.mock_session(visual='ISSUE');self.assertEqual(code,1);self.assertEqual(summary['visual_review_result'],'issue_reported');self.assertTrue(summary['visual_check_complete']);self.assertIn('visual_issue_reported',json.loads((session/'safe/dynamic-report.json').read_text())['errors'])
 def test_finalization_error_keeps_failure_summary(self):
  code,session,summary=self.mock_session(finalization_error=True);self.assertEqual(code,1);self.assertEqual(summary['status'],'finalization_failed');self.assertTrue((session/'safe-summary.zip').exists());self.assertTrue((session/'private/save').exists())
 def test_observe_span_monotonic_boundaries(self):
  process=Mock();process.poll.return_value=None;collector=Mock(start=5);clock=iter([10,10,10.5,11]);begin,end=run.observe_span(process,collector,1,clock=lambda:next(clock),sleep=Mock());self.assertEqual((begin,end),(5,6));self.assertEqual(collector.poll.call_count,3)
 def test_launch_failure_not_success(self):
  code,session,summary=self.mock_session(early_exit=True);self.assertEqual(code,1);self.assertEqual(summary['status'],'failed_or_interrupted')

if __name__=='__main__':unittest.main(verbosity=2)
