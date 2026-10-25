"""Thin manual Dynamic workflow using the existing audited launch/isolation primitives."""
import copy,json,os,sys,time,traceback,uuid
from pathlib import Path
from datetime import datetime,timezone
import profile as core
import dynamic_log as log
import privacy

SAFE_FILES={'summary.json','dynamic-report.json','dynamic-events.jsonl','phases.json','REPORT.md','errors.json'}

def configure(private,inputs,key,parent):
 helper,root,settings,save,exe,library=inputs;cfg=log.SCENARIOS[key]
 env=core.prepare(private,helper,settings,save,root,library,cfg['legacy'],parent)
 ini=Path(env['LARECOMP_SETTINGS']);overrides={'resolution':cfg['resolution'],'upscaler':'metalfx','antialias':'off','aspect':'original','fullscreen':'1'}
 lines=[s for s in ini.read_text().splitlines() if s.split('=',1)[0].strip() not in overrides]
 ini.write_text('\n'.join(lines)+'\n'+''.join(f'{k} = {v}\n' for k,v in overrides.items()))
 core.require(all(helper.ini_values(ini).get(k)==v for k,v in overrides.items()),'Private Dynamic settings mismatch.')
 env.update(LARECOMP_DEPTH_NO_FS='0',LARECOMP_LOG_DYNRES='1',LARECOMP_FPS_INTERVAL='1',LARECOMP_LOG_HITCH_MS='40')
 return env

def preflight(args):
 legacy=copy.copy(args);legacy.scenario=log.SCENARIOS[args.dynamic]['legacy'];legacy.method=args.dynamic_trace or 'overview'
 if getattr(args,'prearm',False):legacy.method='time'
 meta,inputs=core.preflight(legacy)
 binary=inputs[-2].read_bytes()
 core.require(all(token in binary for token in [b'LARECOMP_LOG_DYNRES',b'LARECOMP_FPS_INTERVAL',b'LARECOMP_LOG_HITCH_MS',b'[dynres]']),'Development build lacks required Dynamic/FPS/hitch log support; no game started.')
 if args.dynamic=='kanalet':meta['workload']={'scene':'KanaletCastle','position':'upper-right-entrance','confirmation':False}
 cfg=log.SCENARIOS[args.dynamic];meta.update(scenario=cfg['id'],method='dynamic-'+(args.dynamic_trace or 'log'),motion='phased' if not args.dynamic_trace else 'stationary')
 meta['requested_graphics'].update(resolution=cfg['resolution'],dynamic=cfg['resolution']=='dynamic',upscaler='metalfx')
 meta['dynamic_protocol']={'phase_seconds':args.phase_seconds,'warmup_seconds':args.warmup,'guard_seconds':2,'log_poll_seconds':.1,'log_dynres':True,'fps_interval_seconds':1,'hitch_threshold_ms':40}
 if getattr(args,'recovery',None):
  import recovery
  core.require(not args.repeat_crossing or args.recovery=='screen-transition','Repeat crossing requires screen-transition.')
  core.require(5<=args.recovery_trace_seconds<=180,'Recovery trace duration must be 5..180 seconds.')
  core.require(b'LARECOMP_LOG_INDOOR' in binary,'Development build lacks camera-zone diagnostics.')
  if args.recovery_pace_details:core.require(b'LARECOMP_LOG_PACE' in binary,'Development build lacks pacing diagnostics.')
  meta.update(scenario=recovery.IDS[args.recovery],motion='phased')
  meta['dynamic_protocol'].update(phase_seconds=0,guard_seconds=0)
  if args.recovery=='intensive':core.require(300<=args.intensive_seconds<=600,'Intensive duration must be 300..600 seconds.')
  meta['recovery_protocol']={'test':args.recovery,'repeat_crossing':args.repeat_crossing,'recovery_seconds':120,'pace_details':args.recovery_pace_details,'trace_seconds':args.recovery_trace_seconds if args.dynamic_trace else 0,'source_sha256':core.sha(core.HERE/'recovery.py')}
  if args.recovery=='intensive':meta['recovery_protocol'].update(intensive_seconds=args.intensive_seconds,trace_request_offset_seconds=args.intensive_trace_at)
 meta['dynamic_sources_sha256']={name:core.sha(core.HERE/name) for name in ['dynamic_observe.py','dynamic_log.py']}
 return meta,inputs

def validate_start(text,events,key,inputs):
 core.validate_baseline(text);core.validate_loaded_library(text,inputs[-1])
 scales=[e for e in events if e['type']=='scale'];core.require(scales,'No actual drawable/scale log; cannot verify output.')
 core.require(scales[-1]['reshape']==0 and abs(scales[-1]['sx']-scales[-1]['sy'])<.002,'Observed reshape/scale does not match Original 16:9.')
 core.require((scales[-1]['width'],scales[-1]['height'])==(2880,1800),'Drawable differs from 2880×1800; correct display/fullscreen and retry.')
 core.require(not any(e['type']=='metalfx' and (e.get('available') is False or e.get('created') is False) for e in events),'MetalFX reports unsupported/failed; this is not the requested scenario.')
 if log.SCENARIOS[key]['resolution']=='1':core.require(abs(scales[-1]['sx']-1)<.002 and abs(scales[-1]['sy']-1)<.002,'Fixed 1x scale not observed.')
 else:core.require(any(e['type']=='decision' for e in events),'No Dynamic decision log. Confirm Dynamic and wait for loading to finish.')
 return {'drawable_observed':[2880,1800],'render_scale_observed':[scales[-1]['sx'],scales[-1]['sy']],
  'source_texture_dimensions':'unverified without frame capture','fullscreen_aspect_aa':'private requested settings and user confirmation; runtime state unverified',
  'dynamic_resolution':'selected privately and decision logs observed' if log.SCENARIOS[key]['resolution']=='dynamic' else 'not requested; disabled in private settings; runtime enum unverified'}

def observe_span(process,collector,seconds,clock=time.monotonic,sleep=time.sleep):
 start=clock();end=start+seconds
 while True:
  now=clock();collector.poll(now)
  core.require(process.poll() is None,'Game exited before the observation phase completed.')
  if now>=end:return start-collector.start,now-collector.start
  sleep(min(.1,end-now))

def save_bundle(session,meta,events,phases,report,archive_name='safe-summary.zip',write_sidecars=True):
 # Separate protocol/files; never overwrite legacy captures or analysis sidecars.
 module=log
 if report.get('kind')=='recovery':
  import recovery
  module=recovery
 report=module.sanitize_report(report);events=module.sanitize_events(events)
 safe_phases=privacy.clean(phases,[{'name':privacy.enum(*module.PHASES),'begin_s':privacy.number,'end_s':privacy.number,'requested_seconds':privacy.integer}])
 summary=core.safe_summary(meta,{})
 payload={'summary.json':(json.dumps(summary,indent=2)+'\n').encode(),('recovery-report.json' if module is not log else 'dynamic-report.json'):(json.dumps(report,indent=2,allow_nan=False)+'\n').encode(),
  ('recovery-events.jsonl' if module is not log else 'dynamic-events.jsonl'):''.join(json.dumps(e,allow_nan=False)+'\n' for e in events).encode(),'phases.json':(json.dumps(safe_phases,indent=2)+'\n').encode(),
  'REPORT.md':module.report_markdown(report).encode(),'errors.json':(json.dumps({'observation_codes':report['errors'],'workflow_codes':summary.get('error_codes',[])},indent=2)+'\n').encode()}
 if (session/'active-local.json').exists():
  import hang_watch
  payload['diagnostics.json']=(json.dumps(hang_watch.safe_outcomes(session),indent=2)+'\n').encode()
 core.require(set(payload)-{'diagnostics.json'}==(module.SAFE_FILES if module is not log else SAFE_FILES),'Unsafe Dynamic archive member.')
 archive=core.atomic_zip(session/archive_name,payload)
 if write_sidecars:
  safe=session/'safe';safe.mkdir(exist_ok=True)
  for name,data in payload.items():core.dump(safe/name,json.loads(data)) if name.endswith('.json') else (safe/name).write_bytes(data)
 return archive

def run(args):
 core.require(30<=args.warmup<=300,'Warm-up must be 30..300 seconds.')
 core.require(args.method=='overview','Use --dynamic-trace for a separately labeled heavy trace, or omit --method.')
 core.require(60<=args.phase_seconds<=600,'Phase duration must be 60..600 seconds.')
 recovery_mode=getattr(args,'recovery',None)
 protocol=log
 if recovery_mode:
  import recovery
  protocol=recovery
 meta,inputs=preflight(args)
 if args.dry_run:
  folder=core.HERE/'preflight';folder.mkdir(exist_ok=True)
  core.dump(folder/f"{meta['scenario']}-dynamic-safe.json",core.safe_summary(meta,{}))
  print('DYNAMIC PREFLIGHT PASSED — NO GAME LAUNCHED\n'+str(folder/f"{meta['scenario']}-dynamic-safe.json"));return 0
 core.require(sys.stdin.isatty(),'Use macOS Terminal for interactive launch; --dry-run never starts gameplay.')
 cfg=dict(log.SCENARIOS[args.dynamic])
 if recovery_mode:cfg['id']=meta['scenario']
 identifier=f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{cfg['id']}-baseline-2880x1800-{meta['method']}-{meta['motion']}-{uuid.uuid4().hex[:8]}"
 session=core.HERE/'sessions'/identifier;session.mkdir(parents=True,mode=0o700)
 meta.update(session_id=identifier,status='preparing',error_codes=[],capture_validated=False)
 collector=log.Collector(session/'runtime-local.log',args.dynamic,time.monotonic(),parser=protocol.parse_line);phases=[];process=None;archive=None;excluded=[];report=None
 try:
  env=configure(session/'private',inputs,args.dynamic,os.environ)
  if recovery_mode:
   env['LARECOMP_LOG_INDOOR']='1'
   if args.recovery_pace_details:env['LARECOMP_LOG_PACE']='1'
  meta['launch_environment']=env;core.dump(session/'manifest-local.json',meta)
  print(f"Scenario {cfg['id']}: {args.dynamic}; {cfg['resolution']} + MetalFX; original renderer.\nSession: {session}\nUse the same room/position; scene selection is manual.")
  if recovery_mode:protocol.confirm_launch()
  else:core.require(input('Type LAUNCH to start the protected development game: ').strip()=='LAUNCH','Launch cancelled.')
  core.require(not core.conflicts(),'Another LAS Recomp instance appeared.');core.check_helper(meta['helper_sha256'])
  exe,library=inputs[-2:];core.require(core.sha(exe)==meta['executable_sha256'] and core.sha(library)==meta['library_sha256'],'Executable/library changed after preflight.')
  with collector.path.open('wb',buffering=0) as stream:
   process=core.subprocess.Popen([str(exe)],cwd=env['LARECOMP_DATA_ROOT'],env=env,stdin=core.subprocess.DEVNULL,stdout=stream,stderr=core.subprocess.STDOUT,start_new_session=True)
   time.sleep(1);core.require(process.poll() is None,'Development game failed to start.');core.verify_pid(process.pid,exe)
   meta.update(pid=process.pid,pid_verified=True,status='launched_not_captured');core.dump(session/'manifest-local.json',meta)
   if hasattr(args,'no_watchdog'):
    import hang_watch
    hang_watch.register(session,meta,exe,not args.no_watchdog);args.watchdog_session=session
    meta['watchdog']={'enabled':not args.no_watchdog,'simulation_progress_available':False,'poll_seconds':2,'sample_seconds':10,'trace_seconds':20,'cooldown_seconds':300,'max_captures':2,'prearmed':getattr(args,'prearm',False)}
    core.dump(session/'manifest-local.json',meta)
   print('Confirm Fullscreen, Original 16:9, '+('Dynamic' if cfg['resolution']=='dynamic' else '1x')+', MetalFX, AA Off. Enter the requested room and chosen view.\nREADY starts 10 seconds to refocus, then warm-up and automatic phases; no further Terminal input while playing.')
   if recovery_mode:print(protocol.instructions(args),flush=True)
   core.require(input('Type READY when the scene/settings are confirmed: ').strip()=='READY','Scene not confirmed.')
   meta['user_confirmed_graphics_and_scene']=True;meta.setdefault('workload',{})['confirmation']=True
   if recovery_mode:protocol.announce('Get ready. Return to the game in fullscreen. Recording begins shortly.')
   observe_span(process,collector,10);warm_begin=collector.events[-1]['observed_s'] if collector.events else 0
   if recovery_mode:protocol.announce(f'Warm-up starting. Allow {args.warmup} seconds for the game to settle. A separate stationary baseline follows.')
   observe_span(process,collector,args.warmup)
   values=inputs[0].ini_values(Path(env['LARECOMP_SETTINGS']))
   core.require(values.get('resolution') in ({'dynamic'} if cfg['resolution']=='dynamic' else {'1','1x'}) and all(values.get(k)==v for k,v in {'upscaler':'metalfx','antialias':'off','aspect':'original','fullscreen':'1'}.items()),'Current private settings do not match the requested Dynamic/control scenario.')
   text=collector.path.read_text(errors='replace');meta['observed']=validate_start(text,collector.events,args.dynamic,inputs);meta['loaded_library_verified']=True
   recent=[e for e in collector.events if e['type']=='fps' and e['observed_s']>warm_begin]
   core.require(len(recent)>=3 and all(e['scene_match'] and e['compile']==0 for e in recent[-3:]) and recent[-1]['source_t']>recent[-3]['source_t'] and time.monotonic()-collector.start-recent[-1]['observed_s']<3 and all(b['frame']>a['frame'] and b['source_t']>a['source_t'] for a,b in zip(recent[-3:],recent[-2:])),'Warm-up is stale, loading, compiling or wrong scene; quit normally and retry longer.')
   settings_before=core.sha(Path(env['LARECOMP_SETTINGS']))
   if recovery_mode:
    protocol.observe(args,process,collector,session,meta,exe,phases,observe_span)
   elif args.dynamic_trace:
    print('\aFocused Instruments trace starting; remain still until completion.',flush=True)
    method=args.dynamic_trace;seconds=8 if method=='metal' else 25;began=time.time();trace_start=time.monotonic()
    meta['recording']={'begin_utc':core.utc(),'requested_seconds':seconds,'alignment':'recorder lifetime brackets; trim attach/start/stop margins in Instruments'}
    code=core.record(process,exe,session,method,seconds)
    meta['recording'].update(end_utc=core.utc(),monotonic_seconds=time.monotonic()-trace_start,recorder_exit=code)
    core.require(code==0 and core.trace_matches(session/'recording.trace',session,began),'Focused Dynamic trace failed.','recorder_failed')
    code,out=core.command(['xcrun','xctrace','export','--input',session/'recording.trace','--toc','--output',session/'toc-local.xml'],120)
    (session/'trace-export-local.log').write_text(out);core.require(code==0,'Trace metadata export failed.','trace_export_failed')
    import analyze;analyze.inventory(session/'toc-local.xml',process.pid);meta['trace_pid_verified']=True;meta['capture_created']=True
    report={'schema':1,'scenario':cfg['id'],'phases':[],'errors':[],'recovery':{'status':'unavailable'}}
   else:
    for index,name in enumerate(log.PHASES,1):
     if getattr(args,'watchdog_session',None):hang_watch.phase(session,name)
     print('\a'*index+f'Phase {index}/3: {name}, {args.phase_seconds} seconds.',flush=True)
     begin,end=observe_span(process,collector,args.phase_seconds);phases.append({'name':name,'begin_s':begin,'end_s':end});core.dump(session/'phases-local.json',{'session_id':identifier,'scenario':cfg['id'],'phases':phases})
   if core.sha(Path(env['LARECOMP_SETTINGS']))!=settings_before:collector.errors.append('settings_changed')
   core.verify_pid(process.pid,exe)
   if getattr(args,'watchdog_session',None):
    complete=hang_watch.finish_pending(session);args.watchdog_finish_checked=True
    if not complete:print('Diagnostic wait reached 240 seconds; another recording may still be active. Partial evidence retained.')
   if recovery_mode:protocol.announce('Recording complete. You may quit the game normally.' if not getattr(args,'watchdog_session',None) or complete else 'Gameplay measurement complete. Diagnostic time limit reached. Partial evidence is saved; a recorder may still be active.')
   print('\a'*(5 if recovery_mode else 4)+'Observation complete. Quit LAS Recomp normally.',flush=True)
 except (Exception,KeyboardInterrupt) as error:
  meta['status']='failed_or_interrupted';meta['error_codes'].append(getattr(error,'code',type(error).__name__))
  if isinstance(error,core.RecorderError):meta.setdefault('recording',{})['shutdown']=error.cleanup
  if recovery_mode:protocol.announce('Test interrupted. Close the game normally.')
  (session/'error-local.txt').write_text(traceback.format_exc());print(f'\aSession incomplete: {error}\nQuit normally; all private files are retained.',flush=True)
 finally:
  try:
   if process is not None:
    meta['game_exit_code']=core.wait_for_exit(process)
    if meta['game_exit_code']!=0:collector.errors.append('normal_exit_unverified')
   if getattr(args,'watchdog_session',None) and not getattr(args,'watchdog_finish_checked',False):hang_watch.finish_pending(session)
   collector.poll(time.monotonic());collector.finish()
   if (recovery_mode and phases) or len(phases)==3 or meta.get('capture_created'):
    try:
     answer=input(protocol.clean_prompt(args) if recovery_mode else 'Type CLEAN only if you followed cues, returned to the same position and had no loads/menus/focus/settings changes; otherwise list affected phases (stationary,movement,recovery): ').strip().lower()
     excluded=[] if answer=='clean' else [n for n in protocol.PHASES if n in answer]
     if answer!='clean' and not excluded:excluded=list(protocol.PHASES)
     visual=input('Checked blur/pumping/shimmer/flicker/dark rectangles/textures/lighting/ghosting/clipping? Type NONE if checked and no defect; ISSUE if observed; SKIP if unchecked: ').strip().upper()
     meta['visual_review_result']='none_reported' if visual=='NONE' else 'issue_reported' if visual=='ISSUE' else 'not_checked'
     meta['visual_check_complete']=visual in ['NONE','ISSUE']
    except (EOFError,KeyboardInterrupt):excluded=list(protocol.PHASES);meta['visual_check_complete']=False;meta['visual_review_result']='not_checked'
   if report is None:report=protocol.analyze(collector.events,phases,args.recovery if recovery_mode else args.dynamic,excluded,collector.errors)
   else:report['errors']=sorted(set(report['errors']+collector.errors+(['user_contamination'] if excluded else [])))
   if meta.get('visual_review_result') in ['issue_reported','not_checked']:report['errors']=sorted(set(report['errors']+['visual_issue_reported' if meta['visual_review_result']=='issue_reported' else 'visual_unverified']))
   if meta['status']!='failed_or_interrupted':
    ready=not report['errors'] and meta.get('visual_review_result')=='none_reported' and meta.get('game_exit_code')==0
    meta.update(status='dynamic_observation_ready_for_review' if ready else 'dynamic_observation_requires_review',observation_validated=ready,capture_validated=ready if args.dynamic_trace else False)
   meta['excluded_phases']=excluded
   meta['environment_end']=core.environment_metadata();core.dump(session/'manifest-local.json',meta)
   core.dump(session/'events-local.json',{'session_id':identifier,'scenario':cfg['id'],'events':collector.events})
   archive=save_bundle(session,meta,collector.events,phases,report)
   if recovery_mode:
    try:
     if core.subprocess.run(['/usr/bin/open','-R',str(archive)],check=False).returncode:print('Safe ZIP created; Finder reveal failed.')
    except OSError:print('Safe ZIP created; Finder reveal unavailable.')
   print(f"Status: {meta['status']}\nShare only: {archive}\nRaw logs/private data/traces remain local: {session}")
  except (Exception,KeyboardInterrupt):
   meta.update(status='finalization_failed',capture_validated=False,observation_validated=False)
   meta['error_codes'].append('session_failed')
   try:
    (session/'finalization-error-local.txt').write_text(traceback.format_exc());core.dump(session/'manifest-local.json',meta)
    fallback={'schema':1,'scenario':cfg['id'],'phases':[],'errors':['invalid_event'],'recovery':{'status':'unavailable'}}
    if recovery_mode:fallback=protocol.analyze([],[],args.recovery,collector_errors=['invalid_event'])
    archive=save_bundle(session,meta,[],[],fallback);print(f'Finalization failed; error summary: {archive}. Private files retained.')
   except (Exception,KeyboardInterrupt):print('Finalization failed; no safe archive available. Private files retained; no successful result claimed.')
 return 0 if meta['status']=='dynamic_observation_ready_for_review' else 1
