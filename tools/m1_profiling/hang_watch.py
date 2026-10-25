"""Conservative external diagnostics. Never launches, kills or restarts the game."""
import argparse,ctypes,fcntl,json,os,re,shutil,subprocess,sys,time,uuid,xml.etree.ElementTree as ET
from pathlib import Path
from datetime import datetime,timezone
import profile as core

TEMPLATES={'time':'Time Profiler','overview':'Game Performance Overview','metal':'Metal System Trace'}
COOLDOWN=300;MAX_CAPTURES=2;POLL=2;SAMPLE_SECONDS=10;TRACE_SECONDS=20
class IdentityError(RuntimeError):pass
class BSDInfo(ctypes.Structure):
 _fields_=[(n,ctypes.c_uint32) for n in ['flags','status','xstatus','pid','ppid','uid','gid','ruid','rgid','svuid','svgid','reserved']]+[('comm',ctypes.c_char*16),('name',ctypes.c_char*32)]+[(n,ctypes.c_uint32) for n in ['nfiles','pgid','jobc','tdev','tpgid']]+[('nice',ctypes.c_int32),('start_sec',ctypes.c_uint64),('start_usec',ctypes.c_uint64)]
def identity(pid):
 if type(pid) is not int or pid<=1:raise IdentityError('invalid_pid')
 lib=ctypes.CDLL('/usr/lib/libproc.dylib');buf=ctypes.create_string_buffer(4096);info=BSDInfo()
 if lib.proc_pidpath(pid,buf,len(buf))<=0 or lib.proc_pidinfo(pid,3,0,ctypes.byref(info),ctypes.sizeof(info))!=ctypes.sizeof(info) or info.pid!=pid:raise IdentityError('process_unavailable')
 return {'pid':pid,'executable':str(Path(os.fsdecode(buf.value)).resolve()),'start_sec':info.start_sec,'start_usec':info.start_usec}
def verify(record,hash_binary=False):
 expected=record['identity'];actual=identity(expected['pid'])
 if actual!=expected:raise IdentityError('pid_reused_or_identity_changed')
 if Path(actual['executable']).name!='lasrecomp':raise IdentityError('not_development_game')
 if hash_binary and core.sha(Path(actual['executable']))!=record['binary_sha256']:raise IdentityError('binary_changed')
 return actual

def speech(message):
 import recovery
 recovery.announce(message,wait_for_turn=True)
def read(path,default=None):
 try:return json.loads(Path(path).read_text())
 except (OSError,ValueError):return default

def register(session,meta,exe,start_monitor=True):
 record={'schema':1,'session_id':meta['session_id'],'identity':identity(meta['pid']),'binary_sha256':meta['executable_sha256'],'upstream_commit':meta.get('beta6_upstream_commit'),'development_commit':meta['git_head'],'registered_utc':core.utc(),'auto_enabled':start_monitor}
 if record['identity']['executable']!=str(exe.resolve()):raise IdentityError('launch_path_mismatch')
 core.dump(session/'active-local.json',record);core.dump(session/'watch-phase-local.json',{'phase':'navigation','confirmed':False})
 if start_monitor:
  with (session/'watchdog-local.log').open('ab',buffering=0) as stream:
   subprocess.Popen([sys.executable,'-B',str(Path(__file__).resolve()),'monitor','--session',str(session)],stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
 return record

def phase(session,name):core.dump(session/'watch-phase-local.json',{'phase':name,'confirmed':True,'utc':core.utc()})
def owned_session(session):
 session=Path(session).resolve();base=(core.HERE/'sessions').resolve()
 if session.parent!=base or session.is_symlink():raise IdentityError('not_profiling_session')
 record=read(session/'active-local.json')
 if not record or record.get('session_id')!=session.name:raise IdentityError('missing_session_identity')
 meta=read(session/'manifest-local.json',{})
 if meta.get('pid')!=record['identity']['pid'] or meta.get('executable_sha256')!=record['binary_sha256'] or meta.get('executable')!=record['identity']['executable']:raise IdentityError('session_manifest_mismatch')
 verify(record,True);return record

def active_session():
 matches=[]
 for p in (core.HERE/'sessions').glob('*/active-local.json'):
  try:owned_session(p.parent);matches.append(p.parent)
  except (IdentityError,OSError,KeyError,TypeError):pass
 if len(matches)!=1:raise IdentityError('no_active_session' if not matches else 'ambiguous_active_sessions')
 return matches[0]

class Lock:
 def __init__(self,path):self.path=path;self.file=None
 def acquire(self):
  self.path.parent.mkdir(parents=True,exist_ok=True);self.file=self.path.open('a+')
  try:fcntl.flock(self.file,fcntl.LOCK_EX|fcntl.LOCK_NB);return True
  except BlockingIOError:self.file.close();self.file=None;return False
 def close(self):
  if self.file:self.file.close();self.file=None

class Detector:
 """Explicit runtime reports only. Silence/static images/low FPS are not proof of a gameplay hang."""
 def __init__(self):self.last_fps=None;self.last_decision=None;self.last_marker=None;self.observation={};self.frame=None;self.changed=time.monotonic();self.recent=[]
 def feed(self,text,confirmed):
  found=False
  for line in text.splitlines():
   if line.startswith('[metal] t='):
    rows,bad=core.runtime_rows(line)
    if rows and not bad:
     self.last_fps=rows[-1];self.last_fps['observed_utc']=core.utc();pace=re.search(r'\bpace (30|60)\b',line);self.last_fps['pace']=int(pace[1]) if pace else None
     if self.frame!=rows[-1]['frame']:self.frame=rows[-1]['frame'];self.changed=time.monotonic()
   if line.startswith('[dynres] '):
    import dynamic_log
    try:
     e=dynamic_log.parse_line(line,0,'goponga')
     if e and e['type']=='decision':self.last_decision=e
    except (ValueError,TypeError):pass
   if re.fullmatch(r'\[hang\] ===== .+ =====',line):found=True;self.last_marker=core.utc()
   for prefix,code in [('[warp]','transition_report'),('[widescreen]','scene_or_framing_report'),('[slow]','slow_or_loading_report')]:
    if line.startswith(prefix):self.recent=(self.recent+[{'utc':core.utc(),'type':code}])[-20:]
  self.observation={'process_liveness':'verified_separately','macos_responsiveness':'unavailable','simulation_progress':'unavailable','input_acceptance':'unavailable','last_fps':self.last_fps,'last_dynamic_decision':self.last_decision,'last_runtime_hang_report_utc':self.last_marker,'recent_transition_reports':self.recent,'loading_state':'not_continuously_observable','disk_activity':'unavailable','render_log_progress_stale_seconds':time.monotonic()-self.changed}
  # Menus/loading/non-gameplay never auto-trigger from a silent counter or unchanged scene.
  return bool(found and confirmed and self.last_fps and self.last_fps.get('level')!='-' and time.monotonic()-self.changed>=30)

def sample_command(pid,path):return ['/usr/bin/sample',str(pid),str(SAMPLE_SECONDS),'1','-mayDie','-file',str(path)]
def valid_sample(path,pid):
 if not path.is_file():return False
 text=path.read_text(errors='replace')
 return bool(re.search(r'(?:Process:\s*lasrecomp\s*\['+str(pid)+r'\]|Pid:\s*'+str(pid)+r'\b)',text) and 'Call graph:' in text and ('Binary Images:' in text or 'Total number in stack' in text))

def run_sample(record,folder,outcome):
 verify(record,True);path=folder/'sample-local.txt';start=time.monotonic();outcome['sample_begin_utc']=core.utc();child=None
 try:
  with (folder/'sample-tool-local.log').open('w') as stream:child=subprocess.Popen(sample_command(record['identity']['pid'],path),stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
  # An owned pre-armed recorder should save partial evidence rather than compete with sampling.
  (folder.parent/'pause-recorder-request').write_text(core.utc())
  code=child.wait(timeout=25);outcome['sample_exit']=code
  outcome['sample_status']='complete' if code==0 and valid_sample(path,record['identity']['pid']) else 'partial_or_denied'
 except subprocess.TimeoutExpired:
  outcome['sample_status']='timeout'
 except OSError:outcome['sample_status']='tool_unavailable_or_denied'
 finally:
  if child is not None and child.poll() is None:core.stop_recorder(child)
  outcome.update(sample_end_utc=core.utc(),sample_wall_seconds=time.monotonic()-start)
 speech('Thread sampling complete.' if outcome['sample_status']=='complete' else 'Thread sampling ended. Some evidence may be incomplete.')


def external_recording_active(session):
 record=read(session/'external-recorder-local.json',{})
 if not record.get('active'):return False
 try:return identity(record['identity']['pid'])==record['identity']
 except (IdentityError,KeyError):return False

def finish_pending(session,seconds=240):
 """Wait only after measurement spans, never shift their boundaries."""
 base=session/'diagnostics'
 if not base.exists():return True
 deadline=time.monotonic()+seconds;said=False
 while True:
  busy=external_recording_active(session)
  for name in ['capture.lock','prearm.lock','instruments.lock']:
   lock=Lock(base/name)
   if lock.acquire():lock.close()
   else:busy=True
  if not busy:return True
  if not said:speech('Diagnostic collection is still running. Keep the game open until capture completes.');said=True
  if time.monotonic()>=deadline:return False
  time.sleep(.5)

def run_trace(record,folder,outcome,template='time',seconds=TRACE_SECONDS,prearmed=False):
 lock=Lock(folder.parent/'instruments.lock');deadline=time.monotonic()+35
 while external_recording_active(folder.parent.parent):
  if time.monotonic()>=deadline:outcome['trace_status']='existing_recording_active';return
  time.sleep(.5)
 while not lock.acquire():
  if time.monotonic()>=deadline:outcome['trace_status']='existing_recording_active';return
  time.sleep(.5)
 child=None;start=time.monotonic();trace=folder/'recording.trace';pause=folder.parent/'pause-recorder-request'
 try:
  if pause.exists():pause.unlink() # ephemeral coordination only, never captured evidence
  verify(record,True);outcome.update(trace_begin_utc=core.utc(),trace_template=template,trace_requested_seconds=seconds)
  if shutil.disk_usage(folder).free<2*1024**3:outcome['trace_status']='disk_space_low';return
  with (folder/'recorder-local.log').open('w') as stream:
   cmd=['xcrun','xctrace','record','--template',TEMPLATES[template],'--attach',str(record['identity']['pid']),'--time-limit',f'{seconds}s','--output',str(trace)]
   child=subprocess.Popen(cmd,env=core.XENV,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)
   speech('Pre-armed Time Profiler capture requested. Wait for the spoken crossing cue.' if prearmed else 'Instruments attachment requested. Diagnostics are still running.')
   interrupted=False
   while child.poll() is None:
    if time.monotonic()-start>seconds+60 or (prearmed and pause.exists()):
     core.stop_recorder(child);interrupted=True;break
    try:verify(record)
    except IdentityError:
     core.stop_recorder(child);interrupted=True;break
    time.sleep(.5)
  outcome['recorder_exit']=child.poll();outcome['trace_interrupted']=interrupted
  if not trace.is_dir() or not any(trace.rglob('*')):outcome['trace_status']='missing_or_failed';return
  code,text=core.command(['xcrun','xctrace','export','--input',trace,'--toc','--output',folder/'toc-local.xml'],30)
  (folder/'export-local.log').write_text(text)
  if code:outcome['trace_status']='export_failed';return
  import analyze
  analyze.inventory(folder/'toc-local.xml',record['identity']['pid'])
  toc=ET.parse(folder/'toc-local.xml').getroot();summary=toc.find('./run/info/summary')
  if summary is None or summary.findtext('template-name')!=TEMPLATES[template] or float(summary.findtext('duration','0'))<=0:raise ValueError('trace metadata incomplete')
  outcome.update(trace_actual_start_utc=summary.findtext('start-date'),trace_actual_end_utc=summary.findtext('end-date'),trace_actual_duration_s=float(summary.findtext('duration')))
  outcome['trace_status']='partial_identity_verified' if interrupted else 'identity_verified' if child.poll()==0 else 'partial_identity_verified'
 except (OSError,ValueError,core.Invalid,subprocess.SubprocessError,IdentityError,ET.ParseError):outcome['trace_status']='failed_or_process_exited'
 finally:
  if child is not None and child.poll() is None:core.stop_recorder(child)
  outcome.update(trace_end_utc=core.utc(),trace_wall_seconds=time.monotonic()-start);lock.close()

SAFE_KEYS={'schema','trigger','confidence','started_utc','finished_utc','sample_status','sample_begin_utc','sample_end_utc','sample_wall_seconds','trace_status','trace_template','trace_requested_seconds','trace_begin_utc','trace_end_utc','trace_wall_seconds','trace_interrupted','trace_actual_start_utc','trace_actual_end_utc','trace_actual_duration_s','target_exit_observed','simulation_progress','input_acceptance','macos_responsiveness','last_fps','last_gpu_ms','dynamic_factor','pace_fps','development_commit','upstream_commit','binary_sha256'}
def sanitize(outcome):
 import privacy
 schema={k:privacy.number for k in ['sample_wall_seconds','trace_requested_seconds','trace_wall_seconds','last_fps','last_gpu_ms','dynamic_factor','pace_fps','trace_actual_duration_s']}
 schema.update({k:privacy.stamp for k in ['started_utc','finished_utc','sample_begin_utc','sample_end_utc','trace_begin_utc','trace_end_utc','trace_actual_start_utc','trace_actual_end_utc']})
 schema.update(schema=privacy.integer,trigger=privacy.enum('runtime_hang_report','manual','prearmed'),confidence=privacy.enum('suspected_runtime','user_reported','not_a_detection'),sample_status=privacy.enum('complete','partial_or_denied','timeout','tool_unavailable_or_denied','not_requested'),trace_status=privacy.enum('identity_verified','partial_identity_verified','missing_or_failed','export_failed','failed_or_process_exited','existing_recording_active','disk_space_low','not_started'),trace_template=privacy.enum(*TEMPLATES),trace_interrupted=privacy.boolean,target_exit_observed=privacy.boolean,simulation_progress=privacy.enum('unavailable'),input_acceptance=privacy.enum('unavailable'),macos_responsiveness=privacy.enum('unavailable'),development_commit=privacy.revision,upstream_commit=privacy.revision,binary_sha256=privacy.digest)
 return privacy.clean(outcome,schema)
def safe_outcomes(session):
 return [sanitize(read(p,{})) for p in sorted((session/'diagnostics').glob('*/outcome-local.json'))][-16:]
def publish(folder,outcome):
 core.dump(folder/'outcome-local.json',outcome);safe=sanitize(outcome);core.dump(folder/'diagnostics-safe.json',safe)
 core.atomic_zip(folder/'safe-summary.zip',{'diagnostics.json':(json.dumps(safe,indent=2)+'\n').encode(),'README.md':b'# Suspected hang diagnostics\nRaw sample and trace stay local. A suspected trigger is not proof of a freeze; simulation/input progress is unavailable.\n'})

def capture(session,trigger='manual',prearmed=False,seconds=120):
 record=owned_session(session);base=session/'diagnostics';base.mkdir(mode=0o700,exist_ok=True)
 coordination=Lock(base/('prearm.lock' if prearmed else 'capture.lock'))
 if not coordination.acquire():return 2
 folder=None
 try:
  state=read(base/'rate-local.json',{'attempts':0,'last_epoch':0})
  if not prearmed and (state['attempts']>=MAX_CAPTURES or time.time()-state['last_epoch']<COOLDOWN):return 2
  if not prearmed:core.dump(base/'rate-local.json',{'attempts':state['attempts']+1,'last_epoch':time.time()})
  folder=base/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+trigger+'-'+uuid.uuid4().hex[:8]);folder.mkdir(mode=0o700)
  context=read(session/'watch-context-local.json',{});fps=context.get('last_fps') or {};decision=context.get('last_dynamic_decision') or {}
  outcome={'schema':1,'trigger':trigger,'confidence':'not_a_detection' if prearmed else 'user_reported' if trigger=='manual' else 'suspected_runtime','started_utc':core.utc(),'sample_status':'not_requested','trace_status':'not_started','simulation_progress':'unavailable','input_acceptance':'unavailable','macos_responsiveness':'unavailable','development_commit':record['development_commit'],'upstream_commit':record.get('upstream_commit'),'binary_sha256':record['binary_sha256'],'last_fps':fps.get('fps'),'last_gpu_ms':decision.get('gpu_total_ms'),'dynamic_factor':decision.get('factor'),'pace_fps':fps.get('pace')}
  core.dump(folder/'context-local.json',{'session':record,'latest_observations':context,'manifest':read(session/'manifest-local.json',{})});publish(folder,outcome)
  if not prearmed:
   speech('Possible game freeze. Diagnostic collection is starting.')
   try:run_sample(record,folder,outcome)
   except (IdentityError,OSError):outcome['sample_status']='partial_or_denied'
   publish(folder,outcome) # successful thread evidence survives all subsequent failures
  run_trace(record,folder,outcome,seconds=seconds if prearmed else TRACE_SECONDS,prearmed=prearmed)
  try:verify(record);outcome['target_exit_observed']=False
  except IdentityError:outcome['target_exit_observed']=True
  outcome['finished_utc']=core.utc();publish(folder,outcome)
  if not prearmed:
   if outcome['trace_status']=='existing_recording_active':speech('Diagnostic time limit reached. Another Instruments recording may still be active. Thread evidence has been saved.')
   elif outcome['sample_status']=='complete' or outcome['trace_status'] in ['identity_verified','partial_identity_verified']:speech('Diagnostic capture complete. If the game is still frozen, you may now quit.')
   else:speech('Diagnostic attempt finished. Collection failed. You may quit the game normally.')
  if not prearmed:subprocess.run(['/usr/bin/open','-R',str(folder/'safe-summary.zip')],check=False)
  return 0 if outcome['sample_status']=='complete' or outcome['trace_status'] in ['identity_verified','partial_identity_verified'] else 1
 finally:coordination.close()

def spawn(session,mode='capture',seconds=120):
 folder=session/'diagnostics';folder.mkdir(mode=0o700,exist_ok=True)
 cmd=[sys.executable,'-B',str(Path(__file__).resolve()),mode,'--session',str(session)]
 if mode=='capture':cmd+=['--trigger','runtime_hang_report']
 if mode=='prearm':cmd+=['--seconds',str(seconds)]
 with (folder/'launcher-local.log').open('ab',buffering=0) as stream:return subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT,stdin=subprocess.DEVNULL,start_new_session=True)

def monitor(session):
 record=owned_session(session);detector=Detector();offset=0;pending=b''
 while True:
  try:verify(record)
  except IdentityError:break
  try:
   with (session/'runtime-local.log').open('rb') as f:f.seek(offset);chunk=f.read(1024*1024);offset=f.tell()
  except OSError:chunk=b''
  parts=(pending+chunk).split(b'\n');pending=parts.pop()[-65536:];phase_data=read(session/'watch-phase-local.json',{})
  confirmed=phase_data.get('confirmed') and phase_data.get('phase') in ['baseline','stationary','intensive','movement','event_1','event_2','recovery','recovery_1','recovery_2']
  trigger=detector.feed(b'\n'.join(parts).decode(errors='replace'),confirmed);core.dump(session/'watch-context-local.json',detector.observation)
  if trigger:spawn(session)
  time.sleep(POLL)
 core.dump(session/'watchdog-exit-local.json',{'utc':core.utc(),'reason':'target_exited_or_identity_changed'})

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('mode',choices=['monitor','capture','emergency','prearm','identity-self-test']);p.add_argument('--trigger',choices=['runtime_hang_report','manual'],default='manual');p.add_argument('--session',type=Path);p.add_argument('--seconds',type=int,default=120);a=p.parse_args()
 try:
  import setup_check
  setup_check.verify(core.HERE)
  if a.mode=='identity-self-test':
   info=identity(os.getpid());assert info['pid']==os.getpid() and info['start_sec']>0;print('libproc PID/start-time/path identity self-test passed; no game used.');return 0
  if not 20<=a.seconds<=180:raise ValueError('Trace duration must be 20..180 seconds.')
  session=active_session() if a.mode=='emergency' else a.session
  if session is None:raise IdentityError('session_required')
  if a.mode=='monitor':monitor(session);return 0
  return capture(session,'prearmed' if a.mode=='prearm' else a.trigger,a.mode=='prearm',a.seconds)
 except (IdentityError,OSError,ValueError,KeyError,KeyboardInterrupt) as e:
  print('Diagnostics not completed:',type(e).__name__,str(e));return 1
if __name__=='__main__':raise SystemExit(main())
