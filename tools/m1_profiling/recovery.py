"""Targeted manual event/recovery protocol; reuses the audited Dynamic launcher."""
import copy,json,math,re,time,subprocess,threading,os,fcntl,tempfile
from pathlib import Path
import profile as core
import dynamic_log as log
import privacy

IDS={'screen-transition':'RT','combat':'RC','intensive':'RI'}
PHASES=('baseline','event_1','recovery_1','return_to_start','settle','event_2','recovery_2','intensive')
SAFE_FILES={'summary.json','recovery-report.json','recovery-events.jsonl','phases.json','REPORT.md','errors.json'}
ERRORS=log.ERRORS|{'unexpected_scene_change','pace_details_missing','trace_failed','event_timing_unconfirmed'}


VOICE_TEST='Voice check. Recovery phase announcements will sound like this. Adjust your volume before launching.'

def _speak(message,issued,wait_for_turn=False):
 # Only this worker waits for audio; measurement code never waits or joins it.
 child=None;voice_lock=None
 try:
  if not wait_for_turn and time.monotonic()-issued>1:
   print('Voice cue missed its deadline; use the stopwatch schedule.',flush=True);return
  fd=os.open(str(Path(tempfile.gettempdir())/f'lasrecomp-speech-{os.getuid()}.lock'),os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600);voice_lock=os.fdopen(fd,'r+')
  deadline=time.monotonic()+(15 if wait_for_turn else 0)
  while True:
   try:fcntl.flock(voice_lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
   except BlockingIOError:
    if time.monotonic()>=deadline:return
    time.sleep(.05)
  child=subprocess.Popen(['/usr/bin/say','-r','190',message],stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
  if child.wait(timeout=15)!=0:print('Speech unavailable; use the stopwatch schedule.',flush=True)
 except (OSError,subprocess.TimeoutExpired):
  print('Speech unavailable; use the stopwatch schedule.',flush=True)
 finally:
  if child is not None and child.poll() is None:
   try:
    child.kill();child.wait(timeout=1)
   except (OSError,subprocess.TimeoutExpired):pass
  if voice_lock:voice_lock.close()

def announce(message,wait_for_turn=False):
 """Dispatch audio off the timing thread. Never wait for /usr/bin/say."""
 try:
  threading.Thread(target=_speak,args=(message,time.monotonic(),wait_for_turn),daemon=not wait_for_turn).start()
 except RuntimeError:print('Speech unavailable; use the stopwatch schedule.',flush=True)

def confirm_launch():
 announce(VOICE_TEST)
 print('VOICE CHECK: hear the spoken sentence before LAUNCH. Adjust Mac volume/output if needed. Type VOICE to repeat; no game starts until LAUNCH. If speech is unavailable, use the documented stopwatch schedule.',flush=True)
 while True:
  answer=input('Type VOICE to repeat the volume test, or LAUNCH to start the protected development game: ').strip()
  if answer=='VOICE':announce(VOICE_TEST);continue
  core.require(answer=='LAUNCH','Launch cancelled.');return

def phase_announcement(args,name):
 if name=='intensive':return f'Intensive gameplay begins now. Fight enemies, move between rooms, and explore demanding areas for {args.intensive_seconds//60} minutes'+(f' and {args.intensive_seconds%60} seconds.' if args.intensive_seconds%60 else '.')
 if name.startswith('event'):
  if args.recovery=='combat':return 'Begin combat now. Fight for up to thirty seconds.'
  return 'Cross the screen boundary now.' if name=='event_1' else 'Repeat the same forward screen crossing now.'
 return {'baseline':'Baseline measurement starting. Stand still for thirty seconds. Intensive gameplay will begin afterward.' if args.recovery=='intensive' else 'Baseline measurement starting. Stand still for thirty seconds. The transition or combat test will begin afterward.',
  'recovery_1':'Intensive gameplay complete. Find a safe position and stand still. We are measuring performance recovery for two minutes.' if args.recovery=='intensive' else 'Test event complete. Stop when safe and stand still. We are measuring performance recovery for two minutes.',
  'recovery_2':'Stop. Begin two minutes of stationary recovery.',
  'return_to_start':'Return across the boundary to your original starting position now.',
  'settle':'Stop at the original position. Remain still for thirty seconds.'}[name]

def plan(args):
 if args.recovery=='intensive':return [('baseline',30),('intensive',args.intensive_seconds),('recovery_1',120)]
 phases=[('baseline',30),('event_1',10 if args.recovery=='screen-transition' else 30),('recovery_1',120)]
 if args.repeat_crossing:phases += [('return_to_start',10),('settle',30),('event_2',10),('recovery_2',120)]
 return phases

def instructions(args):
 if args.recovery=='intensive':return (f'INTENSIVE TEST: after refocus and warm-up, remain stationary for a 30-second baseline. At the intensive cue play normally and continuously for {args.intensive_seconds} seconds: combat, effects, screens and room changes are intended events. At the recovery cue stop when safe and remain stationary for 120 seconds. No Terminal interaction during play; use the stopwatch guide if voice is unavailable. Mark late stopping or unexpected interruptions after normal quit.')
 event='cross the chosen A-to-B boundary once within 10 seconds, then stop at the chosen destination' if args.recovery=='screen-transition' else 'fight the small group for up to 30 seconds; stop only when safe'
 return ('RECOVERY TEST: first remain still for 30 seconds; at the event cue '+event+'. At the recovery cue remain still for 120 seconds. '+
  ('Then return B-to-A within 10 seconds, wait 30 seconds, and repeat the SAME A-to-B crossing on the next cue. ' if args.repeat_crossing else '')+
  'Cues follow 10 seconds to refocus and 30 seconds warm-up. Spoken announcements run asynchronously. Use the documented stopwatch schedule if speech is unavailable. '
  'If combat/transition is unfinished at the recovery cue, finish safely and mark that recovery phase affected after quitting. '
  'Exact action times are manual; recovery timing is relative to the cue. No Terminal input is needed during play.')

def clean_prompt(args):
 return ('Type CLEAN if events matched the cues and each recovery began stationary/safe, with no unexpected menu/focus/settings changes or further transitions during recovery. '
  'Planned combat/crossings/loading are intended events. Otherwise list affected phases ('+','.join(n for n,_ in plan(args))+'); ALL if uncertain: ')

def parse_line(line,observed_s,scenario):
 event=log.parse_line(line,observed_s,scenario)
 if event and event['type']=='fps':
  m=re.search(r'\bcompile \d+/([\d.]+)ms',line)
  event['compile_ms']=float(m[1]) if m else None
  if event['compile_ms'] is not None and not math.isfinite(event['compile_ms']):return {'type':'invalid','observed_s':observed_s,'code':'invalid_event'}
 if line.startswith('[widescreen] zone '):
  m=re.fullmatch(r'\[widescreen\] zone (\d+) x [-\d.]+\.\.[-\d.]+ z [-\d.]+\.\.[-\d.]+(?: \(side view\))?, camera x [-\d.]+: (crop|box|full \(stale zone\)) at frame (\d+)',line)
  return {'type':'zone','observed_s':observed_s,'zone_id':int(m[1]),'frame':int(m[3])} if m else {'type':'invalid','observed_s':observed_s,'code':'invalid_event'}
 if line.startswith('[pace] '):
  detail=re.fullmatch(r'\[pace\] period ([\d.]+) blocked ([\d.]+) busy ([\d.]+) cost ([\d.]+) ms \(queue wait ([\d.]+), cpu ([\d.]+), render cpu ([\d.]+), gpu (-?[\d.]+), gpu wait ([\d.]+), submit ([\d.]+), present ([\d.]+), hooks ([\d.]+), lock ([\d.]+)\)( \(no gameplay\))?',line)
  if detail:
   fields=dict(zip(['period_ms','blocked_ms','busy_ms','cost_ms','queue_wait_ms','cpu_ms','render_cpu_ms','gpu_ms','gpu_wait_ms','submit_ms','present_ms','hooks_ms','lock_ms'],map(float,detail.groups()[:13])))
   if not all(math.isfinite(v) for v in fields.values()):return {'type':'invalid','observed_s':observed_s,'code':'invalid_event'}
   if fields['gpu_ms']<0:fields['gpu_ms']=None
   return dict(type='pace_sample',observed_s=observed_s,gameplay=detail[14] is None,**fields)
  if event:
   event['reason']='hold_entry' if 'holding the game' in line else 'gpu_prevents_release' if 'staying at 30' in line else 'settings_reset' if 'back-off cleared' in line else 'headroom_release'
   event['backing_off']='(backing off)' in line
   m=re.search(r'clear CPU headroom \(([\d.]+) ms.*GPU takes ([\d.]+) ms',line)
   if m:event.update(cpu_cost_avg_ms=float(m[1]),gpu_avg_ms=float(m[2]))
   m=re.search(r'(\d+) frames with (?:clear|enough) headroom.*\(([\d.]+) ms.*median ([\d.]+), at most ([\d.]+)(?:, gpu ([\d.]+) ms|, gpu not timed)\)',line)
   if m:event.update(headroom_frames=int(m[1]),cpu_cost_avg_ms=float(m[2]),cost_median_ms=float(m[3]),cost_peak_ms=float(m[4]),gpu_avg_ms=float(m[5]) if m[5] else None)
  elif 'left out ' in line:
   m=re.fullmatch(r'\[pace\] left out (\d+) of (\d+) frames after .+: (\d+) late, (\d+) busy',line)
   if m:event={'type':'pace_note','observed_s':observed_s,'reason':'hitch_grace','ignored_frames':int(m[1]),'total_frames':int(m[2]),'late_frames':int(m[3]),'busy_frames':int(m[4])}
  elif 'a minute at 60:' in line:event={'type':'pace_note','observed_s':observed_s,'reason':'backoff_reset'}
 return event

def observe(args,process,collector,session,meta,exe,phases,span):
 recorder=None;stream=None;began=None;trace_start=None
 def start_trace(phase,offset):
  nonlocal recorder,stream,began,trace_start
  core.verify_pid(process.pid,exe);began=time.time();trace_start=time.monotonic()
  meta['recording']={'trigger_phase':phase,'requested_offset_seconds':offset,'begin_utc':core.utc(),'requested_seconds':args.recovery_trace_seconds,'alignment':'trace request time; actual recording bounds require Instruments'}
  stream=(session/'recorder-local.log').open('w')
  recorder=core.subprocess.Popen(core.recorder(process.pid,session,args.dynamic_trace,args.recovery_trace_seconds),env=core.XENV,stdout=stream,stderr=core.subprocess.STDOUT,start_new_session=True)
  if getattr(args,'watchdog_session',None):
   import hang_watch
   core.dump(session/'external-recorder-local.json',{'active':True,'identity':hang_watch.identity(recorder.pid)})
 try:
  for name,seconds in plan(args):
   if getattr(args,'watchdog_session',None):
    import hang_watch
    hang_watch.phase(session,name)
    if name=='baseline' and getattr(args,'prearm',False):hang_watch.spawn(session,'prearm',120)
   announce(phase_announcement(args,name))
   print('\a'*(2 if name.startswith('event') else 3 if name.startswith('recovery') else 4 if name=='return_to_start' else 1)+f'{name}: {seconds} seconds. '+{'intensive':'PLAY INTENSIVELY NOW: combat, effects and repeated transitions are intended events.','baseline':'Remain still.','event_1':'PERFORM THE PLANNED EVENT NOW.','event_2':'Repeat the same A-to-B crossing NOW.','recovery_1':'STOP when safe; remain still and observe recovery.','recovery_2':'Remain still and observe recovery.','return_to_start':'Return B-to-A now.','settle':'Wait at the original starting position.'}[name],flush=True)
   if name=='baseline' and args.dynamic_trace and args.recovery!='intensive':
    begin,_=span(process,collector,seconds-10)
    start_trace('baseline',20)
    _,end=span(process,collector,10)
   elif name=='intensive' and args.dynamic_trace:
    begin=time.monotonic()-collector.start
    if args.intensive_trace_at:begin,_=span(process,collector,args.intensive_trace_at)
    start_trace('intensive',args.intensive_trace_at)
    _,end=span(process,collector,seconds-args.intensive_trace_at)
   else:begin,end=span(process,collector,seconds)
   phases.append(dict(name=name,begin_s=begin,end_s=end,**({'requested_seconds':seconds} if name=='intensive' else {})))
   core.dump(session/'phases-local.json',{'session_id':meta['session_id'],'scenario':meta['scenario'],'phases':phases})
  if recorder:
   # Long traces may still be running. Keep polling logs without extending the marked recovery window.
   deadline=trace_start+args.recovery_trace_seconds+30
   while recorder.poll() is None and time.monotonic()<deadline:span(process,collector,1)
   core.require(recorder.poll()==0 and core.trace_matches(session/'recording.trace',session,began),'Recovery trace failed.','recorder_failed')
   code,out=core.command(['xcrun','xctrace','export','--input',session/'recording.trace','--toc','--output',session/'toc-local.xml'],120)
   (session/'trace-export-local.log').write_text(out);core.require(code==0,'Recovery trace export failed.','trace_export_failed')
   import analyze
   analyze.inventory(session/'toc-local.xml',process.pid)
   meta.update(trace_pid_verified=True,capture_created=True)
   meta['recording'].update(validation_utc=core.utc(),request_to_validation_seconds=time.monotonic()-trace_start,recorder_exit=0)
 finally:
  if recorder and recorder.poll() is None:
   cleanup=core.stop_recorder(recorder);meta.setdefault('recording',{})['shutdown']=cleanup
  if stream:stream.close()
  if getattr(args,'watchdog_session',None) and recorder:core.dump(session/'external-recorder-local.json',{'active':False})


def window(events,begin,end):return [e for e in events if begin<=e.get('observed_s',-1)<end]
def latest(events,kind,t,max_age=None):
 values=[e for e in events if e['type']==kind and e['observed_s']<=t]
 return values[-1] if values and (max_age is None or t-values[-1]['observed_s']<=max_age) else None

def recovery_time(rows,start):
 since=None;previous=None;found=None
 for e in rows:
  good=(58<=e['fps']<=62 and e.get('pace')==60 and e.get('compile')==0 and e['max_gap_ms']<100)
  if previous:
   dt=e['source_t']-previous['source_t'];host=e['observed_s']-previous['observed_s']
   if not (0<dt<=2.5 and 0<=host<=2.5 and e['frame']>previous['frame']):good=False
  else:good=False # Do not count the partly pre-cue first block as sustained recovery.
  if good:
   since=e['observed_s'] if since is None else since
   if e['observed_s']-since>=5:found=since-start;break
  else:since=None
  previous=e
 return found


def slowdown_intervals(rows,begin,end):
 """Classify complete periodic FPS blocks; never bridge missing/counter-reset periods."""
 summaries=[]
 for threshold in (55,45,35):
  episodes=[];active=None;known=0;unknown_left=True
  def finish(censored):
   nonlocal active
   if active is not None:
    active['right_censored']=censored;episodes.append(active);active=None
  for a,b in zip(rows,rows[1:]):
   dt=b['source_t']-a['source_t'];host=b['observed_s']-a['observed_s']
   valid=0<dt<=2.5 and 0<=host<=2.5 and b['frame']>a['frame'] and math.isfinite(b['fps']) and b['fps']>=0
   if not valid:finish(True);unknown_left=True;continue
   known+=dt
   if b['fps']<threshold:
    if active is None:
     active={'begin_phase_s':max(0,a['observed_s']-begin),'begin_observed_s':a['observed_s'],'begin_runtime_s':a['source_t'],'duration_seconds':0,'minimum_block_fps':b['fps'],'pace_30_observed':False,'left_censored':unknown_left}
    active.update(end_phase_s=max(0,b['observed_s']-begin),end_observed_s=b['observed_s'],end_runtime_s=b['source_t'],duration_seconds=active['duration_seconds']+dt,
     minimum_block_fps=min(active['minimum_block_fps'],b['fps']),pace_30_observed=active['pace_30_observed'] or b.get('pace')==30)
   else:finish(False)
   unknown_left=False
  finish(True)
  summaries.append({'threshold_fps':threshold,'observed_slow_seconds':sum(e['duration_seconds'] for e in episodes),
   'classified_seconds':known,'unclassified_phase_seconds':max(0,end-begin-known),'episode_count':len(episodes),
   'episodes_truncated':len(episodes)>1000,'episodes':episodes[:1000]})
 return summaries

def phase_report(events,phase,excluded):
 name=phase['name'];begin=phase['begin_s'];end=phase['end_s'];part=window(events,begin,end);rows=[e for e in part if e['type']=='fps'];flags=[]
 if name in excluded:flags.append('user_contamination')
 if any(e['type']=='invalid' for e in part):flags.append('invalid_event')
 if not rows:flags.append('missing_runtime_samples')
 if any(e.get('compile') is None for e in rows):flags.append('missing_runtime_samples')
 intervals=[];near=0;seconds=0
 for a,b in zip(rows,rows[1:]):
  dt=b['source_t']-a['source_t'];host=b['observed_s']-a['observed_s']
  if dt<=0 or host<0 or b['frame']<=a['frame']:flags.append('nonmonotonic_runtime');continue
  if dt>2.5 or host>2.5:flags.append('missing_periods');continue
  seconds+=dt
  if 58<=b['fps']<=62:near+=dt
  # All intentional hitches/compilation and scene events stay in statistics.
  if b.get('game_gpu_interval_ms') is not None:intervals.append(b['game_gpu_interval_ms']/(b['frame']-a['frame']))
 if rows and (rows[0]['observed_s']-begin>2.5 or end-rows[-1]['observed_s']>2.5):flags.append('missing_periods')
 if seconds<.75*(end-begin) or seconds>1.25*(end-begin):flags.append('coverage_insufficient')
 decisions=[e for e in part if e['type']=='decision']
 if not decisions:flags.append('dynamic_missing')
 elif decisions[0]['observed_s']-begin>5 or end-decisions[-1]['observed_s']>5 or any(b['observed_s']-a['observed_s']>5 for a,b in zip(decisions,decisions[1:])):flags.append('dynamic_missing')
 scales=[e for e in part if e['type']=='scale'];anchor=latest(events,'scale',begin)
 if anchor:scales.insert(0,anchor)
 if not scales:flags.append('scale_missing')
 if any((e['width'],e['height'])!=(2880,1800) for e in scales):flags.append('drawable_mismatch')
 if any(e['reshape'] or abs(e['sx']-e['sy'])>.002 for e in scales):flags.append('graphics_mismatch')
 state=[]
 for e in events:
  if e['type']=='pace':state.append(e)
  if e['type']=='fps' and e.get('pace') in (30,60):state.append({'type':'pace','observed_s':e['observed_s'],'hold':30 if e['pace']==30 else 0})
 # Durations count observed intervals only, not unbounded forward fills across loading or missing logs.
 held=unknown=0
 for a,b in zip(rows,rows[1:]):
  dt=b['source_t']-a['source_t'];host=b['observed_s']-a['observed_s']
  if 0<dt<=2.5 and 0<=host<=2.5:
   if b.get('pace')==30:held+=dt
   elif b.get('pace')!=60:unknown+=dt
  else:unknown+=max(0,host)
 factors,fu=log.dwell(events,begin,end,'factor','decision')
 low_budget_held=over=over60=0;candidate_seconds=0
 for index,a in enumerate(decisions):
  dt=(decisions[index+1]['observed_s'] if index+1<len(decisions) else end)-a['observed_s'];pace=latest(state,'pace',a['observed_s'],2.5)
  if a.get('gpu_total_ms') is not None:
   over+=a['gpu_total_ms']>a['budget_ms'];over60+=a['gpu_total_ms']>1000/60
   if a['gpu_total_ms']<a['budget_ms'] and pace and pace['hold']==30:
    low_budget_held+=1
    if 0<=dt<=2.5:candidate_seconds+=dt
 hitches=[e['gap_ms'] for e in part if e['type']=='hitch'];levels=[e['level_id'] for e in rows]
 level_changes=sum(a!=b for a,b in zip(levels,levels[1:]));zones=[e['zone_id'] for e in part if e['type']=='zone']
 zone_anchor=latest(events,'zone',begin)
 if zone_anchor:zones.insert(0,zone_anchor['zone_id'])
 if name not in ('event_1','event_2','return_to_start','intensive') and (level_changes or len(set(zones))>1):flags.append('unexpected_scene_change')
 pace_samples=[e for e in part if e['type']=='pace_sample' and e['gameplay']]
 recovery_rows=rows
 fps_recovery=recovery_time(recovery_rows,begin) if name.startswith('recovery') and not flags else None
 return {'slowdowns':slowdown_intervals(rows,begin,end),'pacer_hold_observed':any(e.get('pace')==30 for e in rows) or any(e['type']=='pace' and e.get('reason')=='hold_entry' for e in part),
  'pacer_hold_entry_events':sum(e['type']=='pace' and e.get('reason')=='hold_entry' for e in part),'pacer_hold_release_events':sum(e['type']=='pace' and e.get('reason') in ('headroom_release','settings_reset') for e in part),
  'phase':name,'begin_s':begin,'end_s':end,'quality_flags':sorted(set(flags)),
  'fps_one_second_blocks':log.stats([e['fps'] for e in rows if e['fps']>0]),
  'period_reciprocal_ms_proxy':log.stats([1000/e['fps'] for e in rows if e['fps']>0]),
  'near_60_percent_measured':100*near/seconds if seconds else None,'measured_seconds':seconds,
  'hitch_count':len(hitches),'hitch_gap_sum_ms':sum(hitches),'hitch_gap_max_ms':max(hitches,default=None),
  'compile_count':sum(e['compile'] or 0 for e in rows),'compile_ms_sum':sum(e.get('compile_ms') or 0 for e in rows),'compile_time_available':bool(rows) and all(e.get('compile_ms') is not None for e in rows),
  'runtime_level_changes':level_changes,'zone_log_records':len(zones),'pacer_hold_30_observed_seconds':held,'pacer_hold_unknown_seconds':unknown,
  'factor_minimum':min(factors,default=None),'factor_median_time_weighted':log.weighted_median(factors),'factor_maximum':max(factors,default=None),'factor_unknown_seconds':fu,
  'factor_dwell':[{'factor':k,'seconds':v} for k,v in sorted(factors.items())],
  'factor_adjustments':sum(abs(e['factor']-e['old'])>.005 for e in decisions),
  'at_floor_decisions':sum(e['factor']<=1/3+.005 for e in decisions),'over_60hz_budget_at_floor_decisions':sum(e['factor']<=1/3+.005 and e['gpu_total_ms'] is not None and e['gpu_total_ms']>1000/60 for e in decisions),
  'dynamic_hold_30_decisions':sum(e['hold_fps']==30 for e in decisions),
  'controller_gpu_total_ms':log.stats([e['gpu_total_ms'] for e in decisions if e['gpu_total_ms'] is not None]),
  'controller_gpu_game_ms':log.stats([e['gpu_game_ms'] for e in decisions if e['gpu_game_ms'] is not None]),
  'controller_gpu_window_ms':log.stats([e['gpu_window_ms'] for e in decisions if e['gpu_window_ms'] is not None]),
  'game_gpu_interval_per_present_proxy_ms':log.stats(intervals),
  'over_dynamic_budget_decisions':over,'above_60hz_budget_decisions':over60,'below_dynamic_budget_while_pacer_held_decisions':low_budget_held,'below_dynamic_budget_while_held_observed_seconds':candidate_seconds,
  'pace_cpu_cost_ms':log.stats([e['cost_ms'] for e in pace_samples]),'pace_render_cpu_ms':log.stats([e['render_cpu_ms'] for e in pace_samples]),
  'pace_gpu_delta_ms':log.stats([e['gpu_ms'] for e in pace_samples if e['gpu_ms'] is not None]),
  'seconds_from_recovery_cue_to_sustained_60':fps_recovery,
  'recovery_status':'not_applicable' if not name.startswith('recovery') else 'invalid_or_incomplete' if flags else 'sustained_60_observed' if fps_recovery is not None else 'not_observed_within_window_censored'}

def analyze(events,phases,scenario,excluded=(),collector_errors=()):
 errors=list(collector_errors);names=[p.get('name') for p in phases];expected=['baseline','intensive','recovery_1'] if scenario=='intensive' else list(PHASES[:3]) if len(phases)==3 else list(PHASES[:7])
 valid=names==expected;previous=-1
 for p in phases:
  b,e=p.get('begin_s'),p.get('end_s')
  if not all(type(v) in (int,float) and math.isfinite(v) for v in [b,e]) or b<previous or e<=b:valid=False;break
  previous=e
  if p['name']=='intensive':
   duration=p.get('requested_seconds',300)
   if type(duration) is not int or not 300<=duration<=600:valid=False;break
  else:duration=30 if p['name'] in ('baseline','settle') or (p['name']=='event_1' and scenario=='combat') else 120 if p['name'].startswith('recovery') else 10
  if abs(e-b-duration)>2:valid=False
 if not valid:errors.append('invalid_boundaries')
 if any(b.get('observed_s',-1)<a.get('observed_s',0) for a,b in zip(events,events[1:])):errors.append('nonmonotonic_runtime')
 if any(e['type']=='metalfx' and (e.get('available') is False or e.get('created') is False) for e in events):errors.append('metalfx_failed')
 results=[phase_report(events,p,excluded) for p in phases] if valid else []
 errors+=list({f for p in results for f in p['quality_flags']})
 return {'schema':1,'kind':'recovery','scenario':IDS[scenario],'test':scenario,'phases':results,'errors':sorted(set(errors)),
  'recovery':{'status':'event_cue_reference_only'},'timing_method':'passive_log_read_time',
  'comparison':{'same_direction_repeat_prepared':len(phases)==7,'first_use_causation_proven':False}}

N=privacy.number;I=privacy.integer;B=privacy.boolean
EVENT_SCHEMA=copy.deepcopy(log.EVENT_SCHEMA)
EVENT_SCHEMA.update(type=privacy.enum('fps','scale','decision','pace','hitch','metalfx','invalid','zone','pace_sample','pace_note'),compile_ms=N,zone_id=I,
 reason=privacy.enum('hold_entry','gpu_prevents_release','settings_reset','headroom_release','hitch_grace','backoff_reset'),backing_off=B,gameplay=B)
for key in ['cpu_cost_avg_ms','gpu_avg_ms','cost_median_ms','cost_peak_ms','period_ms','blocked_ms','busy_ms','cost_ms','queue_wait_ms','cpu_ms','render_cpu_ms','gpu_ms','gpu_wait_ms','submit_ms','present_ms','hooks_ms','lock_ms']:EVENT_SCHEMA[key]=N
for key in ['headroom_frames','ignored_frames','total_frames','late_frames','busy_frames']:EVENT_SCHEMA[key]=I
EPISODE_SCHEMA={k:N for k in ['begin_phase_s','end_phase_s','begin_observed_s','end_observed_s','begin_runtime_s','end_runtime_s','duration_seconds','minimum_block_fps']}
EPISODE_SCHEMA.update(pace_30_observed=B,left_censored=B,right_censored=B)
SLOWDOWN_SCHEMA={'threshold_fps':I,'observed_slow_seconds':N,'classified_seconds':N,'unclassified_phase_seconds':N,'episode_count':I,'episodes_truncated':B,'episodes':[EPISODE_SCHEMA]}
PHASE_SCHEMA={'slowdowns':[SLOWDOWN_SCHEMA],'pacer_hold_observed':B,'pacer_hold_entry_events':I,'pacer_hold_release_events':I,'phase':privacy.enum(*PHASES),'quality_flags':[privacy.enum(*ERRORS)],'recovery_status':privacy.enum('not_applicable','invalid_or_incomplete','sustained_60_observed','not_observed_within_window_censored'),'compile_time_available':B,'factor_dwell':[{'factor':N,'seconds':N}]}
for key in ['begin_s','end_s','near_60_percent_measured','measured_seconds','hitch_gap_sum_ms','hitch_gap_max_ms','compile_ms_sum','pacer_hold_30_observed_seconds','pacer_hold_unknown_seconds','factor_minimum','factor_median_time_weighted','factor_maximum','factor_unknown_seconds','below_dynamic_budget_while_held_observed_seconds','seconds_from_recovery_cue_to_sustained_60']:PHASE_SCHEMA[key]=N
for key in ['hitch_count','compile_count','runtime_level_changes','zone_log_records','factor_adjustments','dynamic_hold_30_decisions','at_floor_decisions','over_60hz_budget_at_floor_decisions','over_dynamic_budget_decisions','above_60hz_budget_decisions','below_dynamic_budget_while_pacer_held_decisions']:PHASE_SCHEMA[key]=I
for key in ['fps_one_second_blocks','period_reciprocal_ms_proxy','controller_gpu_total_ms','controller_gpu_game_ms','controller_gpu_window_ms','game_gpu_interval_per_present_proxy_ms','pace_cpu_cost_ms','pace_render_cpu_ms','pace_gpu_delta_ms']:PHASE_SCHEMA[key]=log.S
REPORT_SCHEMA={'schema':I,'kind':privacy.enum('recovery'),'scenario':privacy.enum('RT','RC','RI'),'test':privacy.enum(*IDS),'phases':[PHASE_SCHEMA],'errors':[privacy.enum(*ERRORS)],'recovery':{'status':privacy.enum('event_cue_reference_only')},'timing_method':privacy.enum('passive_log_read_time'),'comparison':{'same_direction_repeat_prepared':B,'first_use_causation_proven':B}}
def sanitize_report(report):
 safe=privacy.clean(report,REPORT_SCHEMA)
 # A ten-minute alternating fixture can contain >256 episodes. Preserve up to the explicit 1000-event limit.
 for raw,row in zip(report.get('phases',[])[:256],safe.get('phases',[])):
  for original,cleaned in zip(raw.get('slowdowns',[])[:3],row.get('slowdowns',[])):
   cleaned['episodes']=[privacy.clean(e,EPISODE_SCHEMA) for e in original.get('episodes',[])[:1000]]
 return safe
def sanitize_events(events):return [privacy.clean(e,EVENT_SCHEMA) for e in events[:100000]]
def report_markdown(report):
 lines=['# Targeted FPS recovery observation','',f"Test: {report['test']} ({report['scenario']}); flags: {', '.join(report['errors']) or 'none detected; manual review required'}.",'',
 '| Phase | FPS median / blocks | Hitches >40ms | Compiles | Pacer held seconds | Recovery seconds from cue |','|---|---|---|---|---|---|']
 for row in report['phases']:
  f=row['fps_one_second_blocks'];lines.append(f"| {row['phase']} | {f.get('median','unavailable')} / {f['samples']} | {row['hitch_count']} | {row['compile_count']} | {row['pacer_hold_30_observed_seconds']:.1f} | {row['seconds_from_recovery_cue_to_sustained_60']} ({row['recovery_status']}) |")
 lines+=['','Slowdown intervals (strictly below each threshold; thresholds overlap and must not be added):','', '| Phase | Below FPS | Observed seconds | Episodes | Unclassified seconds |', '|---|---|---|---|---|']
 for row in report['phases']:
  for slow in row.get('slowdowns',[]):lines.append(f"| {row['phase']} | {slow['threshold_fps']} | {slow['observed_slow_seconds']:.1f} | {slow['episode_count']} | {slow['unclassified_phase_seconds']:.1f} |")
 lines+=['','Longest below-55 episodes (up to five per phase; seconds relative to phase cue):','', '| Phase | Start | End | Observed duration | Pacer 30 observed |', '|---|---|---|---|---|']
 for row in report['phases']:
  slow=next((s for s in row.get('slowdowns',[]) if s['threshold_fps']==55),None)
  for e in sorted(slow['episodes'] if slow else [],key=lambda e:e['duration_seconds'],reverse=True)[:5]:lines.append(f"| {row['phase']} | {e['begin_phase_s']:.1f} | {e['end_phase_s']:.1f} | {e['duration_seconds']:.1f} | {e['pace_30_observed']} |")
 lines+=['','See timestamped episodes in recovery-report.json: observer and runtime clocks are separate; durations classify periodic blocks, not exact individual frames. Phase-edge or missing-data endpoints are censored. Logged gaps are retained as events but do not imply a known FPS during missing periods. Intensive combat/effects/room/screen changes are intended workload; unexpected interruptions still need user review.', '', 'Planned combat, crossings, compilation and hitch gaps are retained. Unexpected interruptions must be marked after normal quit. Recovery is the first >=5-second observed run of 58..62 FPS blocks, pacer released, no compilation or >=100ms maximum gap; relative to the manual STOP cue, not exact action completion. It is not proof that 60 FPS persists for the rest of the window. Missing coverage never counts as recovered.',
 'Inspect recovery-report.json for scale dwell, GPU distributions, gaps and headroom candidates. Inspect timestamped recovery-events.jsonl for hold entry/release/backoff, compile interval totals, level identity hashes, zone logs and GPU decisions. Below the Dynamic budget while held is only a candidate: the pacer has different GPU/CPU conditions and its own history. Never label it a defect automatically.',
 'FPS and reciprocal p95/p99 are periodic-block cadence proxies, not frame-time percentiles. GPU counters and controller G/W are asynchronous estimates, not a synchronized full-frame trace. Compile duration is summed work, not wall stall; no compilation does not exclude resource preparation. Zone logs cover supported indoor camera paths only; manual cues cover other transitions. Log read stamps have 0.1s polling plus buffering uncertainty. Unknown CPU or exact pacer headroom requires optional detailed diagnostics or Instruments.',
 'Optional traces are separately instrumented runs; a 25-second trace cannot cover a 300/600-second intensive phase or the 120-second recovery. Check actual trace tracks, timestamps, PID and complete-frame coverage locally. No raw trace or proprietary resources are shared. Compare repeat crossings only after confirming identical route/direction/destination and workload; a difference suggests first-use effects but cannot prove them.']
 return '\n'.join(lines)+'\n'
