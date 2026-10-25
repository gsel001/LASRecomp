"""Fixture-only targeted recovery tests. No game, real saves or GPU work."""
import copy,json,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import Mock,patch
import profile as core
import dynamic_log as log
import dynamic_observe as launch
import recovery as rec
import test_profiling as base
import test_dynamic as dynamic

class RecoveryTests(unittest.TestCase):
 def setUp(self):
  base.Tests.setUp(self)
  voice=patch.object(rec,'announce');self.voice=voice.start();self.addCleanup(voice.stop)
 tearDown=base.Tests.tearDown
 def make_args(self,**kw):
  opts=dict(recovery='screen-transition',repeat_crossing=False,recovery_pace_details=False,recovery_trace_seconds=25);opts.update(kw)
  return dynamic.DynamicTests.make_args(self,**opts)
 def phases(self,**kw):
  t=40;out=[]
  for n,seconds in rec.plan(self.make_args(**kw)):out.append({'name':n,'begin_s':t,'end_s':t+seconds});t+=seconds
  return out
 def events(self,slow_until=100,gpu=8,compile_event=2):
  out=[rec.parse_line('[scale] frame 1 drawable 2880x1800 -> render scale 1.200x1.200 (reshape 0)',0,'key-cavern')];previous=.8;frame=0
  for i in range(801):
   held=70<=i<slow_until;fps=30 if held else 60;frame+=fps;factor=.5 if 70<=i<130 else .8
   level='KeyCavern' if i<75 else 'KeyCavernNewRoom'
   out.append(rec.parse_line(f'[metal] t={100+i} frame {frame} {fps}.0 fps max {180 if i==75 else 17}ms level {level} (gpu 480ms, compile {compile_event if i==75 else 0}/4ms, pace {30 if held else 60})',float(i),'key-cavern'))
   out.append(rec.parse_line(f'[dynres] {previous:.2f} -> {factor:.2f} (frame 16.7 ms, median 16.7, 0 spikes left out, gpu {gpu}.0 ms = game {gpu-1}.0 + window 1.0, budget 14.5, next raise in 5 s)',i+.01,'key-cavern'));previous=factor
  out += [rec.parse_line("[pace] frames don't fit 60 fps (12 of the last 60 over 16.2 ms busy or shown late, 0 by busy time, median 16.7): holding the game's 30 fps mode (backing off)",70.05,'key-cavern'),rec.parse_line('[hitch] t=175.00 frame 4500 gap 180 ms',75.05,'key-cavern')]
  return sorted(out,key=lambda e:e['observed_s'])
 def report(self,events=None,**kw):return rec.analyze(self.events() if events is None else events,self.phases(**kw),kw.get('recovery','screen-transition'))
 def test_screen_timing(self):self.assertEqual(rec.plan(self.make_args()),[('baseline',30),('event_1',10),('recovery_1',120)])
 def test_combat_separate_timing(self):self.assertEqual(rec.plan(self.make_args(recovery='combat')),[('baseline',30),('event_1',30),('recovery_1',120)]);self.assertEqual(self.report(recovery='combat')['scenario'],'RC')
 def test_repeat_same_direction_not_return_as_second(self):self.assertEqual([n for n,s in rec.plan(self.make_args(repeat_crossing=True))],list(rec.PHASES[:7]));self.assertTrue(self.report(repeat_crossing=True)['comparison']['same_direction_repeat_prepared'])
 def test_cli_simple_command(self):
  with patch.object(sys,'argv',['profile.py','--recovery','screen-transition','--dry-run']),patch.object(launch,'run',return_value=0) as run:
   self.assertEqual(core.main(),0);self.assertEqual(run.call_args.args[0].dynamic,'key-cavern')
 def test_cli_rejects_repeat_without_recovery(self):
  with patch.object(sys,'argv',['profile.py','--repeat-crossing']),self.assertRaises(SystemExit):core.main()
 def test_cli_rejects_fixed_control_recovery(self):
  with patch.object(sys,'argv',['profile.py','--recovery','combat','--dynamic','fixed-1x']),self.assertRaises(SystemExit):core.main()
 def test_intended_events_retained(self):
  r=self.report();self.assertFalse(r['errors']);event=r['phases'][1];self.assertEqual(event['compile_count'],2);self.assertEqual(event['hitch_count'],1);self.assertEqual(event['runtime_level_changes'],1);self.assertEqual(event['fps_one_second_blocks']['samples'],10)
 def test_fps_gaps_not_discarded(self):self.assertEqual(self.report()['phases'][1]['hitch_gap_max_ms'],180)
 def test_recovery_duration_and_censoring(self):
  r=self.report()['phases'][2];self.assertEqual(r['seconds_from_recovery_cue_to_sustained_60'],20);self.assertEqual(r['recovery_status'],'sustained_60_observed')
  r=self.report(self.events(slow_until=360))['phases'][2];self.assertIsNone(r['seconds_from_recovery_cue_to_sustained_60']);self.assertIn('censored',r['recovery_status'])
 def test_already_60_still_requires_observed_five_seconds(self):self.assertEqual(self.report(self.events(slow_until=70))['phases'][2]['seconds_from_recovery_cue_to_sustained_60'],1)
 def test_headroom_candidate_not_defect(self):
  r=self.report()['phases'][2];self.assertGreater(r['below_dynamic_budget_while_pacer_held_decisions'],10);self.assertEqual(r['over_dynamic_budget_decisions'],0);self.assertNotIn('defect',json.dumps(r))
 def test_continued_gpu_load(self):
  r=self.report(self.events(gpu=20))['phases'][2];self.assertGreater(r['over_dynamic_budget_decisions'],100);self.assertEqual(r['below_dynamic_budget_while_pacer_held_decisions'],0)
 def test_missing_gpu_no_invented_headroom(self):
  events=self.events()
  for e in events:
   if e['type']=='decision':e['gpu_total_ms']=e['gpu_game_ms']=e['gpu_window_ms']=None
  r=self.report(events)['phases'][2];self.assertEqual(r['controller_gpu_total_ms']['samples'],0);self.assertEqual(r['below_dynamic_budget_while_pacer_held_decisions'],0)
 def test_unknown_cpu_not_assumed_clear(self):self.assertEqual(self.report()['phases'][2]['pace_cpu_cost_ms'],{'samples':0,'status':'unavailable'})
 def test_gaps_do_not_count_recovered(self):
  events=[e for e in self.events() if not (e['type']=='fps' and 85<=e['observed_s']<115)]
  r=self.report(events)['phases'][2];self.assertIn('missing_periods',r['quality_flags']);self.assertIsNone(r['seconds_from_recovery_cue_to_sustained_60'])
 def test_hold_prevents_recovery_despite_60_fps(self):
  events=self.events()
  for e in events:
   if e['type']=='fps':e['pace']=30
  self.assertIn('censored',self.report(events)['phases'][2]['recovery_status'])
 def test_unexpected_interruption_separate(self):
  r=rec.analyze(self.events(),self.phases(),'screen-transition',['recovery_1']);self.assertIn('user_contamination',r['errors']);self.assertEqual(r['phases'][2]['recovery_status'],'invalid_or_incomplete')
 def test_scene_change_during_recovery_flagged(self):
  events=self.events()
  for e in events:
   if e['type']=='fps' and e['observed_s']>150:e['level_id']='a'*64
  self.assertIn('unexpected_scene_change',self.report(events)['errors'])
 def test_zone_format_numeric_only(self):
  e=rec.parse_line('[widescreen] zone 12 x -12.0..12.0 z -7.0..7.0, camera x 1.2: box at frame 100',1,'key-cavern');self.assertEqual(e,{'type':'zone','observed_s':1,'zone_id':12,'frame':100})
 def test_compile_time(self):self.assertEqual(self.report()['phases'][1]['compile_ms_sum'],40)
 def test_pacer_hold_backoff(self):
  e=next(e for e in self.events() if e['type']=='pace');self.assertEqual(e['reason'],'hold_entry');self.assertTrue(e['backing_off'])
 def test_pacer_cpu_clear_gpu_reject(self):
  e=rec.parse_line('[pace] 60 gameplay frames with clear CPU headroom (8.2 ms a frame at 60 on average), but the GPU takes 13.5 ms a frame: staying at 30',2,'key-cavern');self.assertEqual(e['reason'],'gpu_prevents_release');self.assertEqual(e['gpu_avg_ms'],13.5);self.assertEqual(e['cpu_cost_avg_ms'],8.2)
 def test_pacer_release_exact_numeric_evidence(self):
  e=rec.parse_line("[pace] 60 frames with clear headroom on gameplay frames (8.1 ms a frame at 60 on average, median 9.1, at most 12.1, gpu 9.5 ms): back to the game's own choice",3,'key-cavern');self.assertEqual(e['hold'],0);self.assertEqual(e['headroom_frames'],60);self.assertEqual(e['gpu_avg_ms'],9.5)
 def test_grace_reason_privacy(self):
  e=rec.parse_line('[pace] left out 2 of 60 frames after secret /private/asset: 1 late, 1 busy',2,'key-cavern');self.assertEqual(e['reason'],'hitch_grace');self.assertNotIn('secret',json.dumps(e))
 def test_optional_cpu_details(self):
  e=rec.parse_line('[pace] period 33.33 blocked 22.00 busy 11.33 cost 9.00 ms (queue wait 1.00, cpu 4.00, render cpu 9.00, gpu 8.00, gpu wait 0.00, submit 1.00, present 0.00, hooks 0.00, lock 0.00)',2,'key-cavern');self.assertEqual(e['type'],'pace_sample');self.assertEqual(e['cost_ms'],9);self.assertTrue(e['gameplay'])
 def test_invalid_and_incomplete_boundaries(self):
  self.assertIn('invalid_boundaries',rec.analyze(self.events(),self.phases()[:2],'screen-transition')['errors'])
  phases=self.phases();phases[2]['end_s']=float('nan');self.assertEqual(rec.analyze(self.events(),phases,'screen-transition')['phases'],[])
 def test_nonmonotonic_counters(self):
  events=self.events();rows=[e for e in events if e['type']=='fps'];rows[120]['frame']=rows[119]['frame'];self.assertIn('nonmonotonic_runtime',self.report(events)['errors'])
 def test_collector_uses_recovery_parser(self):
  path=self.root/'runtime';path.write_text('[widescreen] zone 12 x -12.0..12.0 z -7.0..7.0, camera x 1.2: box at frame 100\n');c=log.Collector(path,'key-cavern',10,parser=rec.parse_line);c.poll(11);self.assertEqual(c.events[0]['type'],'zone')
 def test_safe_report_and_archive(self):
  r=self.report();r['secret']='/private/game';events=self.events()+[dict(type='fps',observed_s=400,secret='asset')]
  meta=dict(self.meta,session_id='20261025T010000Z-RT-baseline-2880x1800-dynamic-log-phased-12345678',scenario='RT',method='dynamic-log',status='dynamic_observation_requires_review')
  archive=launch.save_bundle(self.root,meta,events,self.phases(),r)
  with zipfile.ZipFile(archive) as z:
   self.assertEqual(set(z.namelist()),rec.SAFE_FILES);allbytes=b''.join(z.read(n) for n in z.namelist());self.assertNotIn(b'/private/game',allbytes);self.assertNotIn(b'asset',z.read('recovery-events.jsonl'));self.assertEqual(json.loads(z.read('summary.json'))['scenario'],'RT');self.assertEqual(json.loads(z.read('phases.json'))[0]['name'],'baseline')
 def mock_session(self,interrupt=False,early_exit=False,trace=False,repeat=False,details=False,unclean=False,trace_failed=False,intensive=False,intensive_seconds=300,trace_at=0):
  proc=Mock(pid=123);proc.poll.return_value=2 if early_exit else None;proc.wait.return_value=2 if early_exit else 0
  recorder=Mock();recorder.poll.return_value=1 if trace_failed else 0;state={'now':1000.};events=self.events();meta=copy.deepcopy(self.meta);meta.update(scenario='RT',method='dynamic-overview' if trace else 'dynamic-log',motion='phased',requested_graphics={'resolution':'dynamic','dynamic':True,'upscaler':'metalfx'})
  original=(self.save/'slot').read_bytes();original_settings=self.settings.read_bytes();args=self.make_args(dynamic_trace='overview' if trace else None,repeat_crossing=repeat,recovery_pace_details=details)
  if intensive:
   args.recovery='intensive';args.intensive_seconds=intensive_seconds;args.intensive_trace_at=trace_at;meta['scenario']='RI'
  def popen(command,**kwargs):
   if command[0]=='xcrun':
    folder=Path(command[command.index('--output')+1]);folder.mkdir();(folder/'data').write_text('synthetic');return recorder
   self.assertEqual(kwargs['env']['LARECOMP_LOG_INDOOR'],'1');self.assertEqual(kwargs['env']['LARECOMP_DEPTH_NO_FS'],'0');self.assertEqual('LARECOMP_LOG_PACE' in kwargs['env'],details)
   kwargs['stdout'].write((f'[gamelib] {self.lib} (1 + 1 functions)\n[depth-no-fs] experimental=0\n').encode());return proc
  def span(process,c,seconds,*unused,**kwargs):
   if interrupt and seconds in (120,300,600):raise KeyboardInterrupt()
   begin=state['now']-c.start;state['now']+=seconds;end=state['now']-c.start;c.events=copy.deepcopy([e for e in events if e['observed_s']<=end]);c.offset=c.path.stat().st_size;return begin,end
  def command(argv,*unused,**kwargs):
   Path(argv[argv.index('--output')+1]).write_text('<trace-toc><run><info><target><process pid="123"/></target></info><data><table schema="metal-perf-overview-layer-per-frame-metric"/></data></run></trace-toc>');return 0,''
  with patch.object(core,'HERE',self.root),patch.object(launch,'preflight',return_value=(meta,(self.helper,self.data,self.settings,self.save,self.exe,self.lib))),patch.object(sys.stdin,'isatty',return_value=True),patch('builtins.input',side_effect=['LAUNCH','READY','recovery_1' if unclean else 'CLEAN','NONE']),patch.object(core,'conflicts',return_value=[]),patch.object(core,'verify_pid'),patch.object(core,'environment_metadata',return_value={}),patch.object(core.subprocess,'Popen',side_effect=popen),patch.object(core.subprocess,'run',return_value=Mock(returncode=0)) as reveal,patch.object(core,'command',side_effect=command),patch.object(launch,'observe_span',side_effect=span),patch.object(launch.time,'monotonic',side_effect=lambda:state['now']),patch.object(launch.time,'sleep'):
   code=launch.run(args)
  session=next((self.root/'sessions').iterdir());self.assertTrue((session/'private/save/slot').exists());self.assertEqual((self.save/'slot').read_bytes(),original);self.assertEqual(self.settings.read_bytes(),original_settings);proc.terminate.assert_not_called();proc.kill.assert_not_called();reveal.assert_called_once();return code,session,json.loads((session/'safe/recovery-report.json').read_text())
 def test_full_mock_and_finder_reveal(self):
  code,s,r=self.mock_session();self.assertEqual(code,0);self.assertFalse((s/'recording.trace').exists());self.assertEqual(r['scenario'],'RT')
 def test_mock_spoken_cues_cover_session(self):
  self.mock_session();messages=[c.args[0] for c in self.voice.call_args_list]
  self.assertIn(rec.VOICE_TEST,messages);self.assertIn('Get ready. Return to the game in fullscreen. Recording begins shortly.',messages);self.assertIn('Recording complete. You may quit the game normally.',messages)
  self.assertIn(rec.phase_announcement(self.make_args(),'baseline'),messages)
  self.assertIn(rec.phase_announcement(self.make_args(),'event_1'),messages)
  self.assertIn(rec.phase_announcement(self.make_args(),'recovery_1'),messages)
 def test_mock_repeat_complete(self):
  code,s,r=self.mock_session(repeat=True);self.assertEqual(code,0);self.assertEqual(len(r['phases']),7)
 def test_mock_details_opt_in_only(self):self.assertEqual(self.mock_session(details=True)[0],0)
 def test_mock_optional_overview_keeps_full_recovery(self):
  code,s,r=self.mock_session(trace=True);self.assertEqual(code,0);self.assertTrue((s/'recording.trace').exists());self.assertEqual(r['phases'][2]['end_s']-r['phases'][2]['begin_s'],120)
 def test_mock_interrupt_retains_private_evidence(self):self.assertEqual(self.mock_session(interrupt=True)[0],1)
 def test_mock_early_exit_not_success(self):self.assertEqual(self.mock_session(early_exit=True)[0],1)
 def test_mock_unexpected_interruption_flagged(self):self.assertEqual(self.mock_session(unclean=True)[0],1)

 def test_preflight_identity_and_protocol(self):
  self.exe.write_bytes(b'LARECOMP_LOG_DYNRES LARECOMP_FPS_INTERVAL LARECOMP_LOG_HITCH_MS [dynres] LARECOMP_LOG_INDOOR LARECOMP_LOG_PACE')
  with patch.object(core,'preflight',return_value=(dict(copy.deepcopy(self.meta),requested_graphics={}),(self.helper,self.data,self.settings,self.save,self.exe,self.lib))):
   meta,_=launch.preflight(self.make_args());self.assertEqual(meta['scenario'],'RT');self.assertEqual(meta['recovery_protocol']['recovery_seconds'],120);self.assertFalse(meta['recovery_protocol']['pace_details'])
 def test_preflight_rejects_repeat_combat(self):
  self.exe.write_bytes(b'LARECOMP_LOG_DYNRES LARECOMP_FPS_INTERVAL LARECOMP_LOG_HITCH_MS [dynres] LARECOMP_LOG_INDOOR')
  with patch.object(core,'preflight',return_value=(dict(copy.deepcopy(self.meta),requested_graphics={}),(self.helper,self.data,self.settings,self.save,self.exe,self.lib))),self.assertRaises(core.Invalid):launch.preflight(self.make_args(recovery='combat',repeat_crossing=True))
 def test_missing_zone_log_support_prevents_launch(self):
  self.exe.write_bytes(b'LARECOMP_LOG_DYNRES LARECOMP_FPS_INTERVAL LARECOMP_LOG_HITCH_MS [dynres]')
  with patch.object(core,'preflight',return_value=(dict(copy.deepcopy(self.meta),requested_graphics={}),(self.helper,self.data,self.settings,self.save,self.exe,self.lib))),self.assertRaises(core.Invalid):launch.preflight(self.make_args())
 def test_recovery_dry_run_never_launches(self):
  meta=copy.deepcopy(self.meta);meta.update(scenario='RC')
  with patch.object(core,'HERE',self.root),patch.object(launch,'preflight',return_value=(meta,())),patch.object(core.subprocess,'Popen') as spawn:
   self.assertEqual(launch.run(self.make_args(recovery='combat',dry_run=True)),0);spawn.assert_not_called();self.assertTrue((self.root/'preflight/RC-dynamic-safe.json').exists())
 def test_mock_failed_trace_never_claims_success(self):
  code,s,r=self.mock_session(trace=True,trace_failed=True);self.assertEqual(code,1);meta=json.loads((s/'safe/summary.json').read_text());self.assertEqual(meta['status'],'failed_or_interrupted');self.assertFalse(meta['capture_validated'])
 def test_large_gap_does_not_imply_cpu_stall(self):
  text=rec.report_markdown(rec.sanitize_report(self.report()));self.assertIn('cadence proxies',text);self.assertIn('not wall stall',text)
 def test_exact_60_budget_count(self):
  self.assertGreater(self.report(self.events(gpu=20))['phases'][2]['above_60hz_budget_decisions'],100)
 def test_unknown_safe_fields_removed(self):
  event=rec.sanitize_events([{'type':'pace_sample','observed_s':1,'secret':'/private/resource','cpu_ms':8}])[0];self.assertNotIn('secret',event);self.assertEqual(event['cpu_ms'],8)


class VoiceTests(unittest.TestCase):
 def args(self,kind='screen-transition'):return type('Args',(),{'recovery':kind})()
 def test_dispatch_is_daemon_and_never_joins(self):
  with patch.object(rec.threading,'Thread') as thread:
   rec.announce('Cross now.');self.assertTrue(thread.call_args.kwargs['daemon']);thread.return_value.start.assert_called_once();thread.return_value.join.assert_not_called()
 def test_worker_uses_builtin_say_without_shell(self):
  child=Mock();child.wait.return_value=0;child.poll.return_value=0
  with patch.object(rec.subprocess,'Popen',return_value=child) as spawn:rec._speak('Cross now.',rec.time.monotonic())
  self.assertEqual(spawn.call_args.args[0],['/usr/bin/say','-r','190','Cross now.']);self.assertNotIn('shell',spawn.call_args.kwargs)
 def test_missing_say_is_nonfatal(self):
  with patch.object(rec.subprocess,'Popen',side_effect=FileNotFoundError()),patch('builtins.print') as output:rec._speak('Cross now.',rec.time.monotonic())
  self.assertIn('stopwatch',output.call_args.args[0])
 def test_nonzero_speech_exit_is_nonfatal(self):
  child=Mock();child.wait.return_value=1;child.poll.return_value=1
  with patch.object(rec.subprocess,'Popen',return_value=child),patch('builtins.print') as output:rec._speak('Cross now.',rec.time.monotonic())
  self.assertIn('stopwatch',output.call_args.args[0])
 def test_hung_speech_cleanup_does_not_target_game(self):
  child=Mock();child.wait.side_effect=[rec.subprocess.TimeoutExpired('say',15),0];child.poll.return_value=None
  with patch.object(rec.subprocess,'Popen',return_value=child):rec._speak('Cross now.',rec.time.monotonic())
  child.kill.assert_called_once()
 def test_stale_speech_not_played_in_next_phase(self):
  with patch.object(rec.subprocess,'Popen') as spawn:rec._speak('Cross now.',rec.time.monotonic()-2)
  spawn.assert_not_called()
 def test_voice_repeat_before_launch(self):
  with patch.object(rec,'announce') as voice,patch('builtins.input',side_effect=['VOICE','LAUNCH']):rec.confirm_launch()
  self.assertEqual(voice.call_count,2);self.assertEqual(voice.call_args.args[0],rec.VOICE_TEST)
 def test_voice_cancel_does_not_launch(self):
  with patch.object(rec,'announce'),patch('builtins.input',return_value='CANCEL'),self.assertRaises(core.Invalid):rec.confirm_launch()
 def test_combat_announcement_differs_from_crossing(self):
  self.assertIn('combat',rec.phase_announcement(self.args('combat'),'event_1'));self.assertIn('Cross',rec.phase_announcement(self.args(),'event_1'))
 def test_repeat_cues_cover_return_settle_event_and_recovery(self):
  messages=[rec.phase_announcement(self.args(),n) for n in ['return_to_start','settle','event_2','recovery_2']]
  self.assertIn('Return',messages[0]);self.assertIn('thirty',messages[1]);self.assertIn('Repeat',messages[2]);self.assertIn('two minutes',messages[3])
 def test_speech_failure_start_is_nonfatal(self):
  with patch.object(rec.threading,'Thread',side_effect=RuntimeError()),patch('builtins.print') as output:rec.announce('Cross now.')
  self.assertIn('stopwatch',output.call_args.args[0])


class IntensiveTests(unittest.TestCase):
 setUp=RecoveryTests.setUp
 tearDown=base.Tests.tearDown
 make_args=RecoveryTests.make_args
 events=RecoveryTests.events
 mock_session=RecoveryTests.mock_session
 def intensive_args(self,**kw):return self.make_args(recovery='intensive',intensive_seconds=300,intensive_trace_at=0,**kw)
 def phases(self,seconds=300):return [{'name':'baseline','begin_s':40,'end_s':70},{'name':'intensive','begin_s':70,'end_s':70+seconds,'requested_seconds':seconds},{'name':'recovery_1','begin_s':70+seconds,'end_s':190+seconds}]
 def test_default_plan(self):self.assertEqual(rec.plan(self.intensive_args()),[('baseline',30),('intensive',300),('recovery_1',120)])
 def test_600_plan(self):
  args=self.intensive_args();args.intensive_seconds=600;self.assertEqual(rec.plan(args)[1],('intensive',600))
 def test_cli_simple_intensive(self):
  with patch.object(sys,'argv',['profile.py','--intensive','--dry-run']),patch.object(launch,'run',return_value=0) as run:
   self.assertEqual(core.main(),0);a=run.call_args.args[0];self.assertEqual(a.recovery,'intensive');self.assertEqual(a.intensive_seconds,300);self.assertIsNone(a.dynamic_trace)
 def test_cli_extended_and_optional_trace(self):
  with patch.object(sys,'argv',['profile.py','--intensive','--intensive-seconds','600','--dynamic-trace','overview','--intensive-trace-at','240','--dry-run']),patch.object(launch,'run',return_value=0) as run:
   self.assertEqual(core.main(),0);a=run.call_args.args[0];self.assertEqual(a.intensive_seconds,600);self.assertEqual(a.intensive_trace_at,240);self.assertEqual(a.dynamic_trace,'overview')
 def test_cli_rejects_invalid_combinations_and_duration(self):
  for extra in [['--intensive-seconds','299'],['--intensive-seconds','601'],['--repeat-crossing'],['--recovery','combat'],['--intensive-trace-at','300'],['--intensive-trace-at','20'],['--dynamic','fixed-1x']]:
   with self.subTest(extra=extra),patch.object(sys,'argv',['profile.py','--intensive',*extra]),self.assertRaises(SystemExit):core.main()
 def test_cli_rejects_intensive_options_alone(self):
  with patch.object(sys,'argv',['profile.py','--intensive-seconds','600']),self.assertRaises(SystemExit):core.main()
 def test_intended_scenes_compilation_hitches_retained(self):
  r=rec.analyze(self.events(),self.phases(),'intensive');self.assertEqual(r['scenario'],'RI');self.assertFalse(r['errors']);row=r['phases'][1];self.assertEqual(row['runtime_level_changes'],1);self.assertEqual(row['compile_count'],2);self.assertEqual(row['hitch_count'],1)
 def test_recovery_scene_change_still_unexpected(self):
  events=self.events()
  for e in events:
   if e['type']=='fps' and e['observed_s']>=420:e['level_id']='f'*64
  self.assertIn('unexpected_scene_change',rec.analyze(events,self.phases(),'intensive')['errors'])
 def test_spoken_intensive_and_stop_cues(self):
  self.assertIn('Intensive gameplay begins',rec.phase_announcement(self.intensive_args(),'intensive'));self.assertIn('5 minutes',rec.phase_announcement(self.intensive_args(),'intensive'));self.assertIn('Intensive gameplay complete',rec.phase_announcement(self.intensive_args(),'recovery_1'))
 def rows(self):return [dict(type='fps',observed_s=float(i),source_t=100.+i,frame=60*i,fps=f,pace=30 if f==30 else 60) for i,f in enumerate([60,50,40,30,60,40,60])]
 def test_thresholds_duration_and_overlap(self):
  r=rec.slowdown_intervals(self.rows(),0,7);self.assertEqual([x['observed_slow_seconds'] for x in r],[4,3,1]);self.assertEqual([x['episode_count'] for x in r],[2,2,1]);self.assertEqual(r[0]['episodes'][0]['begin_runtime_s'],100);self.assertEqual(r[0]['episodes'][0]['end_runtime_s'],103);self.assertTrue(r[0]['episodes'][0]['pace_30_observed'])
 def test_thresholds_strictly_below(self):
  rows=self.rows()
  for e in rows:e['fps']=55
  self.assertEqual(rec.slowdown_intervals(rows,0,7)[0]['observed_slow_seconds'],0)
 def test_gaps_split_and_censor_not_padded(self):
  rows=self.rows()
  for e in rows:e['fps']=30
  rows[3]['source_t']+=10
  slow=rec.slowdown_intervals(rows,0,7)[2];self.assertEqual(slow['observed_slow_seconds'],4);self.assertEqual(slow['episode_count'],2);self.assertTrue(all(e['right_censored'] for e in slow['episodes']))
 def test_nonmonotonic_frames_unknown(self):
  rows=self.rows();rows[2]['frame']=rows[1]['frame'];self.assertEqual(rec.slowdown_intervals(rows,0,7)[0]['classified_seconds'],5)
 def test_game_chosen_30_is_not_pacer_hold(self):
  rows=self.rows()
  for e in rows:e['pace']=60
  self.assertFalse(any(e['pace_30_observed'] for e in rec.slowdown_intervals(rows,0,7)[0]['episodes']))
 def test_missing_fps_no_recovery_or_invented_slowdown(self):
  events=[e for e in self.events() if e['type']!='fps'];r=rec.analyze(events,self.phases(),'intensive');self.assertIn('missing_runtime_samples',r['errors']);self.assertEqual(r['phases'][1]['slowdowns'][0]['observed_slow_seconds'],0);self.assertIsNone(r['phases'][2]['seconds_from_recovery_cue_to_sustained_60'])
 def test_episode_privacy_and_more_than_256_retained(self):
  rows=[dict(type='fps',observed_s=float(i),source_t=100.+i,frame=60*i,fps=30 if i%2 else 60,pace=30) for i in range(601)]
  r=rec.analyze(self.events(),self.phases(),'intensive');r['phases'][1]['slowdowns']=rec.slowdown_intervals(rows,0,601);r['phases'][1]['slowdowns'][0]['episodes'][0]['secret']='/private/asset'
  safe=rec.sanitize_report(r);self.assertEqual(len(safe['phases'][1]['slowdowns'][0]['episodes']),300);self.assertNotIn('secret',json.dumps(safe));self.assertEqual(safe['scenario'],'RI')
 def test_safe_session_identity_intensive(self):
  import privacy
  sid='20261025T010000Z-RI-baseline-2880x1800-dynamic-log-phased-12345678';self.assertEqual(privacy.session(sid),sid)
 def test_boundary_requires_requested_duration(self):
  phases=self.phases(600);phases[1]['requested_seconds']=300;self.assertIn('invalid_boundaries',rec.analyze(self.events(),phases,'intensive')['errors'])
 def test_mock_default_lightweight_exact_timing(self):
  code,s,r=self.mock_session(intensive=True);self.assertEqual(code,0);self.assertEqual([p['phase'] for p in r['phases']],['baseline','intensive','recovery_1']);self.assertEqual([p['end_s']-p['begin_s'] for p in r['phases']],[30,300,120]);self.assertFalse((s/'recording.trace').exists())
 def test_mock_600_and_voice(self):
  code,s,r=self.mock_session(intensive=True,intensive_seconds=600);self.assertEqual(code,0);self.assertEqual(r['phases'][1]['end_s']-r['phases'][1]['begin_s'],600);self.assertIn('10 minutes',str(self.voice.call_args_list));self.assertIn('Recording complete',str(self.voice.call_args_list))
 def test_mock_overview_later_trigger_does_not_shorten_phases(self):
  code,s,r=self.mock_session(intensive=True,trace=True,trace_at=200);self.assertEqual(code,0);self.assertTrue((s/'recording.trace').exists());m=json.loads((s/'safe/summary.json').read_text());self.assertEqual(m['recording']['requested_offset_seconds'],200);self.assertEqual(m['recording']['trigger_phase'],'intensive');self.assertNotIn('monotonic_seconds',m['recording']);self.assertIn('request_to_validation_seconds',m['recording']);self.assertEqual(r['phases'][1]['end_s']-r['phases'][1]['begin_s'],300)
 def test_mock_failed_intensive_trace(self):self.assertEqual(self.mock_session(intensive=True,trace=True,trace_failed=True)[0],1)
 def test_mock_interrupt_intensive_retains_evidence(self):self.assertEqual(self.mock_session(intensive=True,interrupt=True)[0],1)
 def test_mock_unexpected_interruption(self):self.assertEqual(self.mock_session(intensive=True,unclean=True)[0],1)

 def test_preflight_intensive_records_duration_and_trigger(self):
  self.exe.write_bytes(b'LARECOMP_LOG_DYNRES LARECOMP_FPS_INTERVAL LARECOMP_LOG_HITCH_MS [dynres] LARECOMP_LOG_INDOOR')
  args=self.intensive_args();args.intensive_seconds=600;args.intensive_trace_at=200;args.dynamic_trace='overview'
  with patch.object(core,'preflight',return_value=(dict(copy.deepcopy(self.meta),requested_graphics={}),(self.helper,self.data,self.settings,self.save,self.exe,self.lib))):
   m,_=launch.preflight(args);self.assertEqual(m['scenario'],'RI');self.assertEqual(m['recovery_protocol']['intensive_seconds'],600);self.assertEqual(m['recovery_protocol']['trace_request_offset_seconds'],200);self.assertEqual(m['requested_graphics']['resolution'],'dynamic')
 def test_gpu_high_and_held_headroom_remain_distinct(self):
  events=self.events();r=rec.analyze(events,self.phases(),'intensive')['phases'][1];self.assertTrue(r['pacer_hold_observed']);self.assertEqual(r['pacer_hold_entry_events'],1);self.assertGreater(r['below_dynamic_budget_while_pacer_held_decisions'],10)
  for e in events:
   if e['type']=='decision':e['gpu_total_ms']=20
  r=rec.analyze(events,self.phases(),'intensive')['phases'][1];self.assertGreater(r['above_60hz_budget_decisions'],100);self.assertEqual(r['below_dynamic_budget_while_pacer_held_decisions'],0)
 def test_timestamps_relative_to_phase(self):
  rows=self.rows()
  for e in rows:e['observed_s']+=70
  e=rec.slowdown_intervals(rows,70,77)[0]['episodes'][0];self.assertEqual(e['begin_phase_s'],0);self.assertEqual(e['end_phase_s'],3)
 def test_requested_600_duration_preserved_in_safe_phases(self):
  code,s,r=self.mock_session(intensive=True,intensive_seconds=600);phases=json.loads((s/'safe/phases.json').read_text());self.assertEqual(phases[1]['name'],'intensive');self.assertEqual(phases[1]['requested_seconds'],600)

if __name__=='__main__':unittest.main(verbosity=2)
