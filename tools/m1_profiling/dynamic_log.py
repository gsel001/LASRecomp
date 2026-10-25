"""Manual Dynamic observation: numeric-only events, explicit phases, honest proxy metrics."""
import hashlib,json,math,re,statistics
from pathlib import Path
import profile as core

SCENARIOS={
 'key-cavern':{'id':'DA','legacy':'A','scene':'KeyCavern','resolution':'dynamic'},
 'goponga':{'id':'DB','legacy':'C','scene':None,'resolution':'dynamic'},
 'fixed-1x':{'id':'DC','legacy':'B','scene':'KeyCavern','resolution':'1'},
 'kanalet':{'id':'DK','legacy':'C','scene':'KanaletCastle','resolution':'dynamic'},
}
PHASES=('stationary','movement','recovery')
ERRORS={'invalid_event','collector_overflow','collector_backlog','incomplete_log_line','missing_log','invalid_boundaries',
 'missing_runtime_samples','nonmonotonic_runtime','missing_periods','scene_mismatch','scene_changed','compilation',
 'large_present_gap','drawable_mismatch','window_changed','scale_missing','dynamic_missing','metalfx_failed','settings_changed',
 'user_contamination','visual_issue_reported','visual_unverified','graphics_mismatch','coverage_insufficient','baseline_unverified','invalid_phase_timing','normal_exit_unverified'}

def stats(values):
 if not values:return {'samples':0,'status':'unavailable'}
 a=sorted(values)
 def q(p):
  pos=(len(a)-1)*p;i=int(pos);return a[i]+(a[min(i+1,len(a)-1)]-a[i])*(pos-i)
 return {'samples':len(a),'minimum':a[0],'median':q(.5),'p95':q(.95),'p99':q(.99),'maximum':a[-1]}

def parse_line(line,observed_s,scenario):
 if not math.isfinite(observed_s) or observed_s<0:raise ValueError('Invalid observer clock')
 e={'observed_s':observed_s}
 if line.startswith('[metal] t='):
  rows,bad=core.runtime_rows(line)
  if bad or not rows:return dict(e,type='invalid',code='invalid_event')
  r=rows[0];scene=SCENARIOS[scenario]['scene'];pace=re.search(r'\bpace (30|60)\b',line)
  return dict(e,type='fps',source_t=r['t'],frame=r['frame'],fps=r['fps'],max_gap_ms=r['max_present_gap_ms'],
   compile=r['compile_count'],game_gpu_interval_ms=r['gpu_counter_ms'],pace=int(pace[1]) if pace else None,
   scene_match=(scene.lower() in r['level'].lower()) if scene else r['level']!='-',level_id=hashlib.sha256(r['level'].encode()).hexdigest())
 if line.startswith('[scale] frame '):
  m=re.fullmatch(r'\[scale\] frame (\d+) drawable (\d+)x(\d+) -> render scale ([\d.]+)x([\d.]+) \(reshape (\d+)\)',line)
  if not m:return dict(e,type='invalid',code='invalid_event')
  w,h=int(m[2]),int(m[3]);sx,sy=float(m[4]),float(m[5])
  if min(w,h,sx,sy)<=0 or not all(math.isfinite(x) for x in [sx,sy]):return dict(e,type='invalid',code='invalid_event')
  return dict(e,type='scale',frame=int(m[1]),width=w,height=h,sx=sx,sy=sy,reshape=int(m[6]))
 if line.startswith('[dynres] ') and re.match(r'\[dynres\] [\d.]+ ->',line):
  m=re.fullmatch(r'\[dynres\] ([\d.]+) -> ([\d.]+) \(frame ([\d.]+) ms, median ([\d.]+), (\d+) spikes? left out, gpu (-?[\d.]+) ms = game (-?[\d.]+) \+ window (-?[\d.]+), budget ([\d.]+)(?:, holding (\d+) fps)?, next raise in ([\d.]+) s(?:; spans summed ([\d.]+) ms)?\)',line)
  if not m:return dict(e,type='invalid',code='invalid_event')
  fields={'old':float(m[1]),'factor':float(m[2]),'period_mean_ms':float(m[3]),'period_median_ms':float(m[4]),'spikes':int(m[5]),
   'gpu_total_ms':float(m[6]),'gpu_game_ms':float(m[7]),'gpu_window_ms':float(m[8]),'budget_ms':float(m[9]),'hold_fps':int(m[10] or 0),'raise_wait_s':float(m[11]),'spans_sum_ms':float(m[12]) if m[12] else None}
  if not all(math.isfinite(x) for x in fields.values() if x is not None) or not 0<fields['factor']<=1 or not 0<fields['old']<=1 or fields['period_mean_ms']<=0 or fields['period_median_ms']<=0 or fields['budget_ms']<=0 or fields['hold_fps'] not in [0,20,30]:return dict(e,type='invalid',code='invalid_event')
  for key in ['gpu_total_ms','gpu_game_ms','gpu_window_ms']:
   if fields[key]<0:fields[key]=None
  if fields['gpu_total_ms'] is None:fields['gpu_game_ms']=fields['gpu_window_ms']=None
  return dict(e,type='decision',**fields)
 if line.startswith('[hitch] '):
  m=re.fullmatch(r'\[hitch\] t=([\d.]+) frame (\d+) gap ([\d.]+) ms',line)
  return dict(e,type='hitch',source_t=float(m[1]),frame=int(m[2]),gap_ms=float(m[3])) if m else dict(e,type='invalid',code='invalid_event')
 if line.startswith('[metalfx] '):
  if line=='[metalfx] spatial scaler available':return dict(e,type='metalfx',available=True)
  if 'not supported on this GPU' in line:return dict(e,type='metalfx',available=False)
  m=re.fullmatch(r'\[metalfx\] (\d+)x(\d+) -> (\d+)x(\d+) \((ok|FAILED)\)',line)
  if m:return dict(e,type='metalfx',created=m[5]=='ok',input_allocation=[int(m[1]),int(m[2])],output_allocation=[int(m[3]),int(m[4])])
 if line.startswith('[pace] '):
  if 'holding the game\'s 30 fps mode' in line:return dict(e,type='pace',hold=30)
  if 'back to the game\'s own choice' in line or 'back-off cleared, trying 60' in line:return dict(e,type='pace',hold=0)
  if 'staying at 30' in line:return dict(e,type='pace',hold=30)
 if line.startswith('[dynres] window ') and 'lines:' in line:return dict(e,type='invalid',code='window_changed')
 return None

class Collector:
 def __init__(self,path,scenario,start,parser=None):self.parser=parser or parse_line;self.path=Path(path);self.scenario=scenario;self.start=start;self.offset=0;self.pending=b'';self.events=[];self.errors=[]
 def poll(self,now):
  if not self.path.is_file():return
  with self.path.open('rb') as f:
   f.seek(self.offset);chunk=f.read(1024*1024);self.offset=f.tell()
   if f.read(1):self.errors.append('collector_backlog')
  data=self.pending+chunk;parts=data.split(b'\n');self.pending=parts.pop()
  if len(self.pending)>65536:self.pending=b'';self.errors.append('incomplete_log_line')
  for part in parts:
   try:event=self.parser(part.decode(errors='replace').rstrip('\r'),max(0,now-self.start),self.scenario)
   except (ValueError,TypeError,OverflowError):event={'type':'invalid','observed_s':max(0,now-self.start),'code':'invalid_event'}
   if event:
    if len(self.events)>=100000:self.errors.append('collector_overflow');break
    self.events.append(event)
 def finish(self):
  if self.pending:self.errors.append('incomplete_log_line')

def dwell(events,begin,end,key,kind,convert=lambda e:e.get('factor')):
 points=[e for e in events if e['type']==kind and e['observed_s']<=end]
 previous=[e for e in points if e['observed_s']<=begin];value=convert(previous[-1]) if previous else None;cursor=begin;out={};unknown=0
 for e in [e for e in points if begin<e['observed_s']<end]+[{'observed_s':end}]:
  duration=e['observed_s']-cursor
  if value is None:unknown+=duration
  else:out[value]=out.get(value,0)+duration
  cursor=e['observed_s']
  if 'type' in e:value=convert(e)
 return out,unknown

def weighted_median(d):
 if not d:return None
 half=sum(d.values())/2;acc=0
 for key,value in sorted(d.items()):
  acc+=value
  if acc>=half:return key

def analyze(events,phases,scenario,excluded=(),collector_errors=()):
 errors=list(collector_errors);results=[];level_sets=[];config=SCENARIOS[scenario];dynamic=config['resolution']=='dynamic'
 if len(phases)!=3 or [x.get('name') for x in phases]!=list(PHASES):errors.append('invalid_boundaries')
 if phases and any(e.get('type')=='invalid' and e.get('code')=='window_changed' and phases[0].get('begin_s',0)<=e.get('observed_s',-1)<=phases[-1].get('end_s',0) for e in events):errors.append('window_changed')
 if any(b.get('observed_s',-1)<a.get('observed_s',0) for a,b in zip(events,events[1:])):errors.append('nonmonotonic_runtime')
 if any(e['type']=='metalfx' and (e.get('available') is False or e.get('created') is False) for e in events):errors.append('metalfx_failed')
 last_end=-1
 for phase in phases:
  name=phase.get('name');begin=phase.get('begin_s',-1);end=phase.get('end_s',-1)
  if name not in PHASES or not all(type(v) in (int,float) and math.isfinite(v) for v in [begin,end]) or begin<last_end or end-begin<30:
   errors.append('invalid_boundaries');continue
  last_end=end;lo,hi=begin+2,end-2;flags=[]
  if name in excluded:flags.append('user_contamination')
  fps=[e for e in events if e['type']=='fps' and lo<=e['observed_s']<=hi];valid=[];duration=0;near60=0;interval_gpu=[]
  levels={e['level_id'] for e in fps};level_sets.append(levels)
  if len(levels)>1:flags.append('scene_changed')
  if any(not e['scene_match'] for e in fps):flags.append('scene_mismatch')
  if any(e['compile'] is None or e['compile']>0 for e in fps):flags.append('compilation')
  for a,b in zip(fps,fps[1:]):
   dt=b['source_t']-a['source_t'];host=b['observed_s']-a['observed_s'];frames=b['frame']-a['frame']
   if dt<=0 or frames<=0 or host<0 or b['fps']<=0 or not math.isfinite(b['fps']):flags.append('nonmonotonic_runtime');continue
   if dt>2.5 or host>2.5:flags.append('missing_periods');continue
   if b['max_gap_ms']>=100:flags.append('large_present_gap');continue
   if b['compile']!=0 or not b['scene_match'] or a['level_id']!=b['level_id']:continue
   valid.append(b);duration+=dt
   if 58<=b['fps']<=62:near60+=dt
   if b['game_gpu_interval_ms'] is not None:interval_gpu.append(b['game_gpu_interval_ms']/frames)
  if len(valid)<20:flags.append('missing_runtime_samples')
  if duration<.8*(hi-lo):flags.append('coverage_insufficient')
  anchors=[e for e in events if e['type']=='scale' and e['observed_s']<=lo]
  scales=anchors[-1:]+[e for e in events if e['type']=='scale' and lo<e['observed_s']<=hi]
  if not scales:flags.append('scale_missing')
  if any((e['width'],e['height'])!=(2880,1800) for e in scales):flags.append('drawable_mismatch')
  if any(e['reshape']!=0 or abs(e['sx']-e['sy'])>.002 for e in scales):flags.append('graphics_mismatch')
  phase_events=[e for e in events if lo<=e['observed_s']<=hi]
  if any(e['type']=='invalid' for e in phase_events):flags.append('invalid_event')
  decisions=[e for e in phase_events if e['type']=='decision']
  if dynamic and (len(decisions)<3 or decisions[0]['observed_s']-lo>5 or hi-decisions[-1]['observed_s']>5 or any(b['observed_s']-a['observed_s']>5 for a,b in zip(decisions,decisions[1:]))):flags.append('dynamic_missing')
  source='decision' if dynamic else 'scale'
  factors,unknown=dwell(events,lo,hi,'factor',source,lambda e:e['factor'] if dynamic else e['sy']/min(e['width']/1920,e['height']/1080))
  floor=1/3 # Retina Match 1620 lines: max(1/3, 540/1620)
  changes=[e for e in decisions if abs(e['factor']-e['old'])>.005]
  all_changes=[e for e in events if e['type']=='decision' and begin<=e['observed_s']<end and abs(e['factor']-e['old'])>.005]
  oscillations=sum((a['factor']-a['old'])*(b['factor']-b['old'])<0 and b['observed_s']-a['observed_s']<=30 for a,b in zip(changes,changes[1:]))
  dynholds,hold_unknown=dwell(events,lo,hi,'hold_fps','decision',lambda e:e['hold_fps']) if dynamic else ({},hi-lo)
  pace_events=[]
  for e in events:
   pace_events.append(e)
   if e['type']=='fps' and e.get('pace') in [30,60]:pace_events.append({'type':'pace','observed_s':e['observed_s'],'hold':30 if e['pace']==30 else 0})
  pace,pace_unknown=dwell(pace_events,lo,hi,'hold','pace',lambda e:e['hold'])
  hitches=[e['gap_ms'] for e in phase_events if e['type']=='hitch']
  if unknown>2:flags.append('scale_missing')
  results.append({'phase':name,'requested_seconds':end-begin,'core_begin_s':lo,'core_end_s':hi,'quality_flags':sorted(set(flags)),
   'fps_one_second_blocks':stats([e['fps'] for e in valid]),'period_reciprocal_ms_proxy':stats([1000/e['fps'] for e in valid]),
   'measured_runtime_seconds':duration,'near_60_percent_of_measured':100*near60/duration if duration else None,
   'per_frame_time_ms':{'status':'unavailable; no full per-frame series'},
   'hitches_over_40ms':{'count':len(hitches),'gap_sum_ms':sum(hitches),'maximum_ms':max(hitches,default=None)},
   'factor':{'minimum':min(factors,default=None),'median_time_weighted':weighted_median(factors),'maximum':max(factors,default=None),'seconds_by_factor':[{'factor':k,'seconds':v} for k,v in sorted(factors.items())],'unknown_seconds':unknown,'below_fixed_1x_seconds':sum(v for k,v in factors.items() if k<2/3-.005)},
   'adjustments':len(changes),'all_phase_adjustments':len(all_changes),'maximum_factor_adjustment':max((abs(e['factor']-e['old']) for e in all_changes),default=0),'at_floor_seconds':sum(v for k,v in factors.items() if k<=floor+.005),'reversals_within_30s':oscillations,'dynamic_hold_30_seconds':dynholds.get(30,0),'dynamic_hold_20_seconds':dynholds.get(20,0),'dynamic_hold_unknown_seconds':hold_unknown,
   'pace_hold_30_seconds':pace.get(30,0),'pace_hold_unknown_seconds':pace_unknown,
   'at_floor_decisions':sum(e['factor']<=floor+.005 for e in decisions),'over_budget_at_floor_decisions':sum(e['factor']<=floor+.005 and e['gpu_total_ms'] is not None and e['gpu_total_ms']>e['budget_ms'] for e in decisions),
   'controller_gpu_game_ms':stats([e['gpu_game_ms'] for e in decisions if e['gpu_game_ms'] is not None]),'controller_gpu_window_ms':stats([e['gpu_window_ms'] for e in decisions if e['gpu_window_ms'] is not None]),
   'game_gpu_interval_per_present_proxy_ms':stats(interval_gpu)})
 if len(results)==3 and level_sets[0] and level_sets[2] and level_sets[0]!=level_sets[2]:results[2]['quality_flags']=sorted(set(results[2]['quality_flags']+['scene_mismatch']))
 errors+=sorted({x for phase in results for x in phase['quality_flags']})
 recovery={'status':'unavailable'}
 if len(results)==3 and not results[0]['quality_flags'] and not results[2]['quality_flags']:
  target=results[0]['factor']['median_time_weighted'];start=phases[2]['begin_s'];end=phases[2]['end_s'];since=None;found=None
  prior=[e for e in events if e['type']=='decision' and e['observed_s']<start]
  points=([dict(prior[-1],observed_s=start)] if prior else [])+[e for e in events if e['type']=='decision' and start<=e['observed_s']<=end]
  for e in points:
   if target is not None and e['factor']>=target-.025:
    since=e['observed_s'] if since is None else since
    if e['observed_s']-since>=5:found=since-start;break
   else:since=None
  recovery={'target_initial_stationary_factor':target,'seconds_to_sustain_target_for_5s':found,'observation_seconds':end-start,'status':'reached_initial_quality' if found is not None else 'not_reached_within_window; censored, not a defect'} if dynamic else {'status':'not applicable; fixed resolution'}
 return {'schema':1,'scenario':config['id'],'observation_method':'passive read-time stamps, 0.1s poll; two-second phase guards; no exact event/trace alignment',
  'phases':results,'recovery':recovery,'errors':sorted(set(errors)),
  'dimensions':{'drawable_expected':[2880,1800],'game_viewport_derived':[2880,1620],'internal_content_size':'derived from logged scale, not an observed texture readback','retina_dynamic_floor_factor':1/3,'retina_floor_derived':[960,540]},
  'conclusion':'Unmodified baseline only. Do not infer a controller defect or GPU bottleneck from these proxies.'}

# Only intentional numeric/fixed-label data can be shared; no raw text/paths/level names.
import privacy
N=privacy.number;I=privacy.integer;B=privacy.boolean
S={k:N for k in ['minimum','median','p95','p99','maximum']};S.update(samples=I,status=privacy.enum('unavailable','unavailable; no full per-frame series'))
EVENT_SCHEMA={'type':privacy.enum('fps','scale','decision','pace','hitch','metalfx','invalid'),'observed_s':N,'source_t':N,'frame':I,
 'fps':N,'max_gap_ms':N,'compile':I,'game_gpu_interval_ms':N,'pace':I,'scene_match':B,'level_id':privacy.digest,
 'width':I,'height':I,'sx':N,'sy':N,'reshape':I,'old':N,'factor':N,'period_mean_ms':N,'period_median_ms':N,'spikes':I,
 'gpu_total_ms':N,'gpu_game_ms':N,'gpu_window_ms':N,'budget_ms':N,'hold_fps':I,'raise_wait_s':N,'spans_sum_ms':N,'gap_ms':N,
 'available':B,'created':B,'input_allocation':[I],'output_allocation':[I],'hold':I,'code':privacy.enum(*ERRORS)}
PHASE_SCHEMA={'phase':privacy.enum(*PHASES),'requested_seconds':N,'core_begin_s':N,'core_end_s':N,'quality_flags':[privacy.enum(*ERRORS)],
 'fps_one_second_blocks':S,'period_reciprocal_ms_proxy':S,'measured_runtime_seconds':N,'near_60_percent_of_measured':N,'per_frame_time_ms':S,
 'hitches_over_40ms':{'count':I,'gap_sum_ms':N,'maximum_ms':N},
 'factor':{'minimum':N,'median_time_weighted':N,'maximum':N,'seconds_by_factor':[{'factor':N,'seconds':N}],'unknown_seconds':N,'below_fixed_1x_seconds':N},
 'adjustments':I,'all_phase_adjustments':I,'maximum_factor_adjustment':N,'at_floor_seconds':N,'reversals_within_30s':I,'dynamic_hold_30_seconds':N,'dynamic_hold_20_seconds':N,'dynamic_hold_unknown_seconds':N,'pace_hold_30_seconds':N,'pace_hold_unknown_seconds':N,
 'at_floor_decisions':I,'over_budget_at_floor_decisions':I,'controller_gpu_game_ms':S,'controller_gpu_window_ms':S,'game_gpu_interval_per_present_proxy_ms':S}
REPORT_SCHEMA={'schema':I,'scenario':privacy.enum('DA','DB','DC','DK'),'phases':[PHASE_SCHEMA],'errors':[privacy.enum(*ERRORS)],
 'recovery':{'target_initial_stationary_factor':N,'seconds_to_sustain_target_for_5s':N,'observation_seconds':N,'status':privacy.enum('unavailable','reached_initial_quality','not_reached_within_window; censored, not a defect','not applicable; fixed resolution')},
 'dimensions':{'drawable_expected':[I],'game_viewport_derived':[I],'retina_dynamic_floor_factor':N,'retina_floor_derived':[I]}}

def sanitize_report(report):return privacy.clean(report,REPORT_SCHEMA)
def sanitize_events(events):return [privacy.clean(e,EVENT_SCHEMA) for e in events[:100000]]
def report_markdown(report):
 lines=['# Dynamic observation — unmodified baseline','',f"Scenario: {report['scenario']}. Quality flags: {', '.join(report['errors']) or 'none detected; manual review still required'}.",'',
  '| Phase | FPS median / lowest block | Time near 60 | Factor min / weighted median / max | Adjustments / reversals |', '|---|---|---|---|---|']
 for row in report['phases']:
  f=row['fps_one_second_blocks'];q=row['factor']
  lines.append(f"| {row['phase']} | {f.get('median','unavailable')} / {f.get('minimum','unavailable')} | {row['near_60_percent_of_measured']}% | {q['minimum']} / {q['median_time_weighted']} / {q['maximum']} | {row['adjustments']} / {row['reversals_within_30s']} |")
 lines+=['','Recovery: '+report['recovery'].get('status','unavailable')+'.','',
  'FPS is a reported ~one-second block average; reciprocal and max-gap values are present-cadence proxies. No per-frame p95/p99 series is available. Controller G/W values are asynchronous estimates; sums of command-buffer spans are not GPU utilization.',
  'Factor dwell times use passive log-read timestamps (0.1 s polling), not exact GPU/frame event times. Two seconds at phase edges are excluded. Missing data are not filled. Internal content dimensions are derived from scale, not observed texture dimensions. MetalFX allocation sizes do not reveal active content size.',
  'Flags, loading/compilation and user contamination require interval review. A gap is not proof of a visual defect. Compare the three phases separately; no automatic controller optimization is justified by a first run.']
 return '\n'.join(lines)+'\n'

def main():
 import argparse,sys
 parser=argparse.ArgumentParser(description='Reanalyze a manual Dynamic session; no gameplay or profiling is started.')
 parser.add_argument('session',type=Path);args=parser.parse_args();session=args.session.resolve()
 try:
  meta=json.loads((session/'manifest-local.json').read_text());events=json.loads((session/'events-local.json').read_text());phases=json.loads((session/'phases-local.json').read_text())
  if any(x.get('session_id')!=meta['session_id'] or x.get('scenario')!=meta['scenario'] for x in [events,phases]):raise ValueError('Session identity mismatch')
  key=next(k for k,v in SCENARIOS.items() if v['id']==meta['scenario'])
  report=analyze(events['events'],phases['phases'],key,meta.get('excluded_phases',[]))
  import dynamic_observe
  failed=bool(report['errors'])
  core.dump(session/'dynamic-analysis-status.json',{'status':'analysis_failed' if failed else 'analysis_complete','errors':report['errors']})
  print(dynamic_observe.save_bundle(session,meta,events['events'],phases['phases'],report,archive_name='dynamic-analysis-error.zip' if failed else 'safe-summary.zip',write_sidecars=False));return 1 if failed else 0
 except (Exception,KeyboardInterrupt):
  print('Dynamic analysis failed; no replacement result claimed. Prior archive/private evidence retained.',file=sys.stderr);return 1
if __name__=='__main__':raise SystemExit(main())
