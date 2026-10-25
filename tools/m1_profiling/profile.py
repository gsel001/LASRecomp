#!/usr/bin/env python3
"""Protected development-only manual gameplay profiler. Default: Scenario A, baseline."""
import argparse
import ctypes
import hashlib
import math
import traceback
import tempfile
import isolation
import privacy
import json
import os
import plistlib
from pathlib import Path
import re
import shutil
import signal
import statistics
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = Path.home()/'Developer/LASRecomp'
DEV = '/Applications/Xcode.app/Contents/Developer'
XENV = {k:os.environ[k] for k in ['HOME','USER','LOGNAME','PATH','LANG','LC_ALL','LC_CTYPE','TMPDIR'] if k in os.environ}
XENV['DEVELOPER_DIR']=DEV
SCENARIOS = {
 'A': {'scene':'KeyCavern','resolution':'match','scale':1.5,'render_estimate':[2880,1620]},
 'B': {'scene':'KeyCavern','resolution':'1','scale':1.0,'render_estimate':[1920,1080]},
 'C': {'scene':None,'resolution':'match','scale':1.5,'render_estimate':[2880,1620]},
}
TEMPLATES={'time':'Time Profiler','overview':'Game Performance Overview','metal':'Metal System Trace'}
SAFE_NAMES={'summary.json','SUMMARY.md','measurements.json','errors.json'}
class Invalid(RuntimeError):
 def __init__(self,message,code='Invalid'):
  super().__init__(message);self.code=code

class RecorderError(Invalid):
 def __init__(self,code,cleanup):
  super().__init__('Recorder failed; see local shutdown/error records.',code);self.cleanup=cleanup


def utc():return datetime.now(timezone.utc).isoformat()
def dump(path, data):
 tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(data,indent=2)+'\n');tmp.replace(path)
def sha(path):
 h=hashlib.sha256()
 with path.open('rb') as f:
  for block in iter(lambda:f.read(1024*1024),b''):h.update(block)
 return h.hexdigest()
def command(args,timeout=30,env=None):
 try:
  p=subprocess.run(list(map(str,args)),env=env or XENV,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=timeout)
  return p.returncode,p.stdout
 except (OSError,subprocess.TimeoutExpired) as e:return 127,str(type(e).__name__)
def require(ok,message,code='Invalid'):
 if not ok:raise Invalid(message,code)
def helper_module(repo=None):
 # Compatibility API for existing callers; repo is intentionally not used for isolation code.
 return isolation

def check_helper(expected):
 require(sha(Path(isolation.__file__))==expected,'Packaged isolation dependency changed after preflight.','helper_drift')


def process_path(pid):
 """Darwin proc_pidpath returns kernel executable identity, not argv or a process name."""
 lib=ctypes.CDLL('/usr/lib/libproc.dylib');buf=ctypes.create_string_buffer(4096)
 n=lib.proc_pidpath(int(pid),buf,len(buf))
 return Path(os.fsdecode(buf.value)).resolve() if n>0 else None

def verify_pid(pid,exe,reader=process_path):
 actual=reader(pid);require(actual==exe.resolve(),'PID executable differs from the development executable (or identity is inaccessible).');return True

def conflicts():
 code,text=command(['/bin/ps','-axo','pid=,comm='])
 require(code==0,'Cannot inspect existing processes; close other LAS Recomp instances and retry.')
 return [int(line.strip().split(None,1)[0]) for line in text.splitlines()
         if len(line.strip().split(None,1))==2 and Path(line.strip().split(None,1)[1]).name.lower()=='lasrecomp']

def validate_inputs(repo,root,settings,save):
 exe=repo/'build/lasrecomp'
 require(exe.is_file() and not exe.is_symlink() and os.access(exe,os.X_OK),'Missing executable development build/lasrecomp; no installed-app fallback.')
 require((repo/'.git').exists(),'Expected source checkout Git metadata is missing.')
 require(root.is_dir() and settings.is_file(),'Data root or source settings are missing.')
 require(save.is_dir() and not save.is_symlink(),'Save directory must exist and cannot be a symbolic link.')
 require(not any(p.is_symlink() for p in save.rglob('*')),'Save tree contains a symbolic link; refusing unsafe copy.')
 extracted=root/'extracted';require((extracted/'romfs').is_dir(),'Existing extracted/romfs is required; never import/extract here.')
 main=extracted/'exefs/main';require(main.is_file(),'Existing extracted/exefs/main is missing.')
 with main.open('rb') as f:hdr=f.read(0x60)
 require(len(hdr)==0x60 and hdr[:4]==b'NSO0','Extracted main is not a recognized NSO; no import is attempted.')
 suffix=hdr[0x40:0x48].hex().upper();binary=exe.read_bytes()
 library=None
 for p in [exe.parent/'lasgame.dylib',extracted/'lasgame.dylib']:
  side=Path(str(p)+'.id')
  if p.is_file() and side.is_file():
   ident=side.read_text().strip()
   # Runtime builds its expected id from the embedded generator prefix + NSO build id.
   if ident.endswith('-'+suffix) and ident[:-(len(suffix)+1)].encode()+b'\0' in binary:
    library=p;break
 require(library is not None,'Existing compiled game library/ID does not match executable generator ID and extracted build. No build/import will run.')
 require(b'[depth-no-fs] experimental=' in binary and b'[scale] frame ' in binary,'Build lacks required baseline/scale log anchors.')
 return exe,library

def clean_environment(parent,private,root,library,frame=False):
 # A small allowlist removes inherited LARECOMP/LASRECOMP/MTL/DYLD/NO_RAW/trace/debug overrides.
 env={k:parent[k] for k in ['HOME','USER','LOGNAME','LANG','LC_ALL','LC_CTYPE','__CF_USER_TEXT_ENCODING'] if k in parent}
 env.update(PATH='/usr/bin:/bin:/usr/sbin:/sbin',TMPDIR=str(private/'tmp'),XDG_CACHE_HOME=str(private/'cache'),
            LARECOMP_DATA_ROOT=str(root),LARECOMP_DATA_HOME=str(private/'app-home'),
            LARECOMP_SETTINGS=str(private/'larecomp.ini'),LARECOMP_SAVE_DIR=str(private/'save'),
            LARECOMP_GAME_LIB=str(library),LARECOMP_NO_LAUNCHER='1',LARECOMP_DEPTH_NO_FS='0')
 if frame:env['MTL_CAPTURE_ENABLED']='1'
 return env

def prepare(private,helper,settings,save,source,library,scenario,parent,frame=False):
 private.mkdir(mode=0o700)
 # Reuse only the copy/isolation primitive; discard ALL diagnostic launch flags it returns.
 _,ini=helper.prepare_private_run(private,settings,save,source,parent)
 values=helper.ini_values(ini);require(not values.get('rando_seed',''),'This prepared workflow requires vanilla settings. Select vanilla in a future normal session first; no original settings changed.')
 overrides={'fullscreen':'1','aspect':'original','resolution':SCENARIOS[scenario]['resolution'],'antialias':'off'}
 lines=[line for line in ini.read_text().splitlines() if line.split('=',1)[0].strip() not in overrides]
 ini.write_text('\n'.join(lines)+'\n'+''.join(f'{k} = {v}\n' for k,v in overrides.items()))
 root=private/'data';root.mkdir()
 # Original content is referenced read-only by the existing runtime. Extraction/setup paths disabled.
 (root/'extracted').symlink_to(source/'extracted',target_is_directory=True)
 for name in ['fonts','gamecontrollerdb.txt']:
  if (source/name).exists():(root/name).symlink_to(source/name,target_is_directory=(source/name).is_dir())
 for p in [private/'tmp',private/'app-home',private/'cache',root/'cache',root/'build'] :p.mkdir()
 return clean_environment(parent,private,root,library,frame)

def graphics(text,scenario):
 matches=list(re.finditer(r'\[scale\] frame (\d+) drawable (\d+)x(\d+) -> render scale ([\d.]+)x([\d.]+) \(reshape (\d+)\)',text))
 require(matches,'Actual drawable/render scale not observed. Confirm fullscreen and wait for gameplay; no diagnostic instrumentation is enabled.')
 m=matches[-1];s=SCENARIOS[scenario]
 require((int(m[2]),int(m[3]))==(2880,1800),'Actual drawable is not 2880×1800. Manually select macOS 1440×900 scaled and fullscreen; retry a new session.')
 require(abs(float(m[4])-s['scale'])<.002 and abs(float(m[5])-s['scale'])<.002,'Actual render scale differs from scenario. Select Match (A/C) or 1x (B), Original 16:9, AA Off; retry.')
 return {'drawable_observed':[int(m[2]),int(m[3])],'render_scale_observed':[float(m[4]),float(m[5])],
         'render_area_derived_not_observed':s['render_estimate'], 'source_texture_dimensions':'unverified without frame capture',
         'fullscreen_aspect_aa':'private requested settings and user confirmation; runtime state unverified',
         'dynamic_resolution':'not requested; disabled in private settings; runtime enum unverified'}

def validate_baseline(text):
 vals=re.findall(r'\[depth-no-fs\] experimental=(\d+)',text)
 require(vals and set(vals)=={'0'},'Baseline renderer banner missing or experimental renderer detected.')
 require('[depth-no-fs-diag] enabled=1' not in text and '[depth-probe]' not in text,'Unexpected diagnostic instrumentation in log.')

def runtime_rows(text):
 rows=[];malformed=False
 pattern=r'\[metal\] t=([^ ]+) frame ([^ ]+) ([^ ]+) fps max ([^ ]+)ms level (.*?) \((.*?)\)'
 for line in text.splitlines():
  if not line.startswith('[metal] t='):continue
  m=re.fullmatch(pattern,line)
  try:
   require(m is not None,'Invalid periodic row.')
   gpu=re.search(r'\bgpu ([^ ,]+)ms,',m[6]);comp=re.search(r'\bcompile (\d+)/',m[6])
   r={'t':float(m[1]),'frame':int(m[2]),'fps':float(m[3]),'max_present_gap_ms':float(m[4]),'level':m[5],
      'gpu_counter_ms':float(gpu[1]) if gpu else None,'compile_count':int(comp[1]) if comp else None}
   require(r['frame']>=0 and all(math.isfinite(r[k]) for k in ['t','fps','max_present_gap_ms']),'Invalid periodic number.')
   if r['gpu_counter_ms'] is not None:require(math.isfinite(r['gpu_counter_ms']) and r['gpu_counter_ms']>0,'Invalid GPU proxy counter.')
   rows.append(r)
  except (Invalid,ValueError,OverflowError):malformed=True
 return rows,malformed

def measurements(text,scenario,required_seconds=None):
 rows,malformed=runtime_rows(text);errors=[]
 if malformed:errors.append('invalid_runtime_row')
 if len(rows)<3:errors.append('missing_or_insufficient_runtime_samples')
 if any(r['fps']<=0 or r['max_present_gap_ms']<=0 or r['t']<0 for r in rows):errors.append('nonpositive_timing')
 gaps=[b['t']-a['t'] for a,b in zip(rows,rows[1:])]
 if any(g<=0 for g in gaps):errors.append('nonmonotonic_timestamps')
 if any(b['frame']<=a['frame'] for a,b in zip(rows,rows[1:])):errors.append('nonmonotonic_frames')
 if any(g>4.1 for g in gaps):errors.append('missing_runtime_periods')
 if len({r['level'] for r in rows})>1:errors.append('level_changed_inside_window')
 scene=SCENARIOS[scenario]['scene']
 if any((scene and scene.lower() not in r['level'].lower()) or r['level']=='-' for r in rows):errors.append('scene_changed_or_unconfirmed')
 if any(r['max_present_gap_ms']>=100 for r in rows):errors.append('loading_or_focus_sized_gap')
 if any(r['compile_count'] is None or r['compile_count']>0 for r in rows):errors.append('shader_compilation_not_settled_or_unobservable')
 if '[scale] frame ' in text:errors.append('render_scale_changed_in_recording_window')
 span=rows[-1]['t']-rows[0]['t'] if len(rows)>1 else 0
 if required_seconds is not None:
  # Default log cadence is 2 seconds. At most one boundary period at each end is absent.
  need=max(4.,required_seconds-4.)
  if span<need or len(rows)<max(3,math.ceil(need/2.)+1):errors.append('insufficient_time_coverage')
 proxy=[]
 if not errors:
  proxy=[r['gpu_counter_ms']/(r['frame']-prev['frame']) for prev,r in zip(rows,rows[1:]) if r['gpu_counter_ms'] is not None]
  if proxy and len(proxy)!=len(rows)-1:errors.append('missing_proxy_intervals')
 invalid={'samples':0,'status':'invalid evidence; distributions withheld'}
 return {'runtime_fps_periodic':invalid if errors else distribution([r['fps'] for r in rows[1:]]),
         'asynchronous_gpu_ms_per_present_proxy':invalid if errors else distribution(proxy),
         'cpu_frame_ms':{'status':'unavailable; inspect Instruments'},'gpu_execution_ms':{'status':'unavailable; inspect Instruments'},
         'present_interval_ms':{'status':'unavailable as a per-frame series'},'individual_render_pass_ms':{'status':'unavailable; frame capture/counters required'},
         'coverage':{'rows':len(rows),'span_seconds':max(0,span),'required_seconds':required_seconds,'max_gap_seconds':max(gaps,default=0),'boundary_excluded':1},
         'location_validation':'KeyCavern token matched when samples valid' if scenario in ['A','B'] else 'Goponga requires user confirmation; only stable non-menu runtime level checked',
         'errors':sorted(set(errors))}

def validate_warmup(text,scenario,elapsed,previous_text=''):
 result=measurements(text,scenario,elapsed)
 before,_=runtime_rows(previous_text);after,_=runtime_rows(text)
 if before and after:
  require(after[0]['t']>before[-1]['t'] and after[0]['frame']>before[-1]['frame'],'Stale warm-up log progress.','runtime_log_stale')
 require(not result['errors'],'Warm-up samples are stale, incomplete, loading or compiling.','runtime_log_stale')
 return result

def validate_loaded_library(text,library):
 # Runtime can try fallbacks after explicit-library failure. Confirm the actual successful path.
 paths=re.findall(r'^\[gamelib\] (.*?) \(.*?\)$',text,re.M)
 require(paths and all(Path(p).resolve()==library.resolve() for p in paths),'Loaded game library path missing or differs from hashed library.')
 return True


def distribution(values,method='linear quantile; periodic blocks, not frames'):
 if not values:return {'samples':0,'status':'unavailable'}
 require(all(type(v) in (float,int) and math.isfinite(v) and v>0 for v in values),'Distribution requires positive finite values.')
 a=sorted(values);pos=(len(a)-1)*.95;i=int(pos)
 return {'samples':len(a),'median':statistics.median(a),'p95':a[i]+(a[min(i+1,len(a)-1)]-a[i])*(pos-i),'method':method}

def trace_matches(path,session,began):
 return (path.parent.resolve()==session.resolve() and path.name=='recording.trace' and not path.is_symlink()
         and path.is_dir() and path.stat().st_mtime>=began-2 and any(path.iterdir()))

def environment_metadata():
 commands={'model':['/usr/sbin/sysctl','-n','hw.model'],'macos':['/usr/bin/sw_vers','-productVersion'],
           'power':['/usr/bin/pmset','-g','batt'],'low_power':['/usr/bin/pmset','-g','custom'],'xcode':['xcodebuild','-version']}
 out={}
 for key,args in commands.items():
  code,text=command(args)
  if key=='power':
   out['power_source']='AC' if "'AC Power'" in text else 'battery' if "'Battery Power'" in text else 'unavailable'
   percent=re.search(r'(\d+)%;',text);out['battery_percent']=int(percent[1]) if percent else None
  elif key=='low_power':
   source=None;states={}
   for line in text.splitlines():
    if line.strip() in ['Battery Power:','AC Power:']:source=line.strip()[:-1]
    match=re.search(r'lowpowermode\s+(\d+)',line)
    if match and source:states[source]=int(match[1])
   out['low_power_mode_by_source']=states or {'status':'unavailable'}
  else:out[key]=text.strip() if code==0 else 'unavailable'
 try:
  with Path('/Applications/Xcode.app/Contents/Applications/Instruments.app/Contents/Info.plist').open('rb') as f:
   info=plistlib.load(f);out['instruments_version']=info.get('CFBundleShortVersionString','unavailable')
 except (OSError,ValueError):out['instruments_version']='unavailable'
 probe=HERE/'tool-probe'
 if probe.is_file():
  code,text=command([probe])
  try:out['gpu_display_thermal']=json.loads(text) if code==0 else {'status':'unavailable'}
  except ValueError:out['gpu_display_thermal']={'status':'unavailable'}
 return out

def discover_inputs(helper,args):
 # Use only explicit CLI overrides, never an inherited disposable test data-root/settings/save path.
 keys=['LARECOMP_DATA_ROOT','LARECOMP_DATA_HOME','LARECOMP_SETTINGS','LARECOMP_SAVE_DIR']
 saved={k:os.environ[k] for k in keys if k in os.environ}
 try:
  for k in keys:os.environ.pop(k,None)
  return helper.data_paths(args)
 finally:os.environ.update(saved)

def check_xcode_installation():
 return Path(DEV).is_dir() and Path('/Applications/Xcode.app/Contents/Applications/Instruments.app').is_dir()

def preflight(args,repo=REPO):
 if getattr(args,'build','baseline')=='beta6':
  catalog=json.loads((HERE/'BETA6_BUILD_LOCAL.json').read_text());repo=Path(catalog['repository'])
  require(sha(repo/'build/lasrecomp')==catalog['binary_sha256'],'Selected Beta 6 executable changed since build validation.')
  require(subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()==catalog['development_commit'],'Selected Beta 6 source revision changed since validation.')
 import setup_check
 setup_check.verify(Path(__file__).resolve().parent)
 helper=helper_module(repo)
 root,settings,save=discover_inputs(helper,args)
 require(not helper.ini_values(settings).get('rando_seed',''),'Vanilla source settings required; no original setting will be edited.')
 exe,library=validate_inputs(repo,root,settings,save)
 require(check_xcode_installation(),'Installed Xcode/Instruments missing.')
 for name in ['xcrun','gpucapture','gpudebug','metalperftrace']:require(shutil.which(name),f'Required installed tool missing: {name}')
 code,templates=command(['xcrun','xctrace','list','templates'],45)
 require(code==0,'Instruments template discovery failed. Run from Terminal outside restricted execution; see preflight limitations.')
 require(TEMPLATES[args.method] in templates,'Requested Instruments template not available.')
 require(not conflicts(),'Another LAS Recomp process exists. Quit all LAS Recomp copies normally, then retry.')
 require(shutil.disk_usage(HERE).free>=10*1024**3,'At least 10 GiB free storage required for local traces.')
 git=lambda *a:subprocess.check_output(['git',*a],cwd=repo,text=True).strip()
 result={'schema':1,'checked_utc':utc(),'status':'preflight_passed_not_launched','scenario':args.scenario,
         'method':args.method,'renderer':'baseline','expected_drawable':[2880,1800],
         'executable':str(exe.resolve()),'executable_sha256':sha(exe),'library':str(library.resolve()),'library_sha256':sha(library),
         'git_head':git('rev-parse','HEAD'),'git_branch':git('branch','--show-current'),'git_status':git('status','--porcelain=v1'),
         'profiling_sources_sha256':{name:sha(HERE/name) for name in ['profile.py','analyze.py','isolation.py','privacy.py','tool_probe.m']},
         'dependencies_manifest_sha256':sha(Path(__file__).with_name('DEPENDENCIES.json')),
         'helper_sha256':sha(HERE/'isolation.py'), 'free_gib':round(shutil.disk_usage(HERE).free/1024**3,1),
         'workload':{'scene':'Goponga' if args.scenario=='C' else 'KeyCavern','position':'user-confirmed-goponga-position' if args.scenario=='C' else 'historical-key-cavern-position','confirmation':False},
         'renderer_optimization':{'name':'LARECOMP_DEPTH_NO_FS','value':0},
         'requested_graphics':{'fullscreen':True,'aspect':'original','resolution':SCENARIOS[args.scenario]['resolution'],'antialias':'off','dynamic':False,'upscaler':privacy.GRAPHICS['upscaler'](helper.ini_values(settings).get('upscaler','unverified'))},
         'source_settings_sha256':sha(settings),'source_upscaler':helper.ini_values(settings).get('upscaler','unverified'),
         'environment':environment_metadata(),'warnings':['Gameplay attachment permission and actual metrics require the first real session.',
          'Detailed runtime settings/source dimensions are not logged with eligibility diagnostics disabled; mark unverified.',
          'Default periodic FPS/renderer stats and occasional texture-allocation logs remain; overhead is unquantified.',
          'Private empty shader cache may require additional warm-up; do not record active shader compilation.']}
 if getattr(args,'build','baseline')=='beta6':result.update(build_selection='beta6',beta6_upstream_commit=catalog['upstream_commit'])
 else:result['build_selection']='baseline'
 return result,(helper,root,settings,save,exe,library)

def safe_summary(local,metrics):
 data=dict(local,capture_created=local.get('capture_created',False),capture_validated=local.get('capture_validated',False),trace_pid_verified=local.get('trace_pid_verified',False),loaded_library_verified=local.get('loaded_library_verified',False),git_dirty=bool(local.get('git_status')),metrics=metrics,
           pid_executable_verified=local.get('pid_verified',False),
           capture_scope='lightweight runtime log observation' if local.get('method')=='dynamic-log' else 'one command buffer; complete frame unverified' if local.get('method')=='frame' else 'Instruments timeline')
 return privacy.summary(data)

def atomic_zip(archive,payload):
 archive=Path(archive);temporary=archive.with_name(archive.name+'.'+uuid.uuid4().hex+'.tmp')
 try:
  with zipfile.ZipFile(temporary,'x',zipfile.ZIP_DEFLATED) as z:
   for name,data in payload.items():z.writestr(name,data)
  with zipfile.ZipFile(temporary) as z:
   require(set(z.namelist())==set(payload) and z.testzip() is None,'ZIP validation failed.')
   require(all(z.read(name)==data for name,data in payload.items()),'ZIP payload differs.')
  os.replace(temporary,archive)
 finally:
  if temporary.exists():temporary.unlink()
 return archive

def write_safe(session,local,metrics,extra=None,archive_name='safe-summary.zip',write_sidecars=True):
 folder=session/'safe'
 if write_sidecars:folder.mkdir(exist_ok=True)
 safe=safe_summary(local,metrics);clean_metrics=privacy.metrics(metrics)
 errors={'codes':privacy.clean(local.get('error_codes',[]),[privacy.code]),'measurement_errors':clean_metrics.get('errors',[])}
 payload={'summary.json':(json.dumps(safe,indent=2,allow_nan=False)+'\n').encode(),
          'measurements.json':(json.dumps(clean_metrics,indent=2,allow_nan=False)+'\n').encode(),
          'errors.json':(json.dumps(errors,indent=2)+'\n').encode(),
          'SUMMARY.md':('# Profiling summary\n\nStatus: '+safe.get('status','unverified')+'\n\n'
           'Raw traces, XML and error details stay local. Runtime values are recorder-lifetime proxies; '
           'inspect selected trace intervals before interpreting performance.\n').encode()}
 if extra is not None:
  import analyze
  payload['analysis.json']=(json.dumps(analyze.sanitize_analysis(extra),indent=2)+'\n').encode()
  if isinstance(extra,dict) and extra.get('status')=='analysis_failed':
   payload['SUMMARY.md']=b'# Analysis failed\n\nThe capture record is unchanged. See analysis.json for the current analysis error; this archive does not certify current trace validity.\n\n'+payload['SUMMARY.md']
 # Build replacement completely before replacing a prior valid archive; local text files are secondary.
 archive=atomic_zip(session/archive_name,payload)
 if write_sidecars:
  for name,data in payload.items():
   temporary=folder/(name+'.tmp');temporary.write_bytes(data);os.replace(temporary,folder/name)
 return archive


def wait_for_exit(process):
 while True:
  try:return process.wait()
  except KeyboardInterrupt:print('\nQuit LAS Recomp normally. Private files are retained; the launcher is still waiting.',flush=True)

def recorder(pid,session,method,seconds):
 return ['xcrun','xctrace','record','--template',TEMPLATES[method],'--attach',str(pid),'--time-limit',f'{seconds}s','--output',str(session/'recording.trace')]

def stop_recorder(child,timeouts=(2.,2.,2.)):
 result={'confirmed':False,'escalated':False,'stage':'unconfirmed','interrupts':0}
 def reap(timeout):
  for attempt in range(3):
   try:
    result_code=child.wait(timeout=timeout);return type(result_code) is int
   except KeyboardInterrupt:result['interrupts']+=1;timeout=0
   except (subprocess.TimeoutExpired,OSError):return False
  return False
 if type(child.poll()) is int:
  result.update(confirmed=reap(0),stage='already_exited');return result
 for stage,timeout in zip(['sigint','terminate','kill'],timeouts):
  try:
   if type(child.poll()) is not int:
    if stage=='sigint':child.send_signal(signal.SIGINT)
    elif stage=='terminate':child.terminate()
    else:child.kill()
  except ProcessLookupError:pass
  except KeyboardInterrupt:result['interrupts']+=1
  except OSError:pass
  result['escalated']=stage!='sigint';result['stage']=stage
  if reap(timeout):result['confirmed']=True;return result
 result['stage']='unconfirmed'
 return result

def record(process,exe,session,method,seconds,completion_timeout=None,shutdown_timeouts=(2.,2.,2.)):
 verify_pid(process.pid,exe);require(process.poll() is None,'Game exited before recording.')
 with (session/'recorder-local.log').open('w') as log:
  child=subprocess.Popen(recorder(process.pid,session,method,seconds),env=XENV,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
  try:return child.wait(timeout=completion_timeout if completion_timeout is not None else seconds+120)
  except (KeyboardInterrupt,subprocess.TimeoutExpired) as error:
   cleanup=stop_recorder(child,shutdown_timeouts);dump(session/'recorder-shutdown-local.json',cleanup)
   code='recorder_interrupted' if isinstance(error,KeyboardInterrupt) else 'recorder_timeout'
   if not cleanup['confirmed']:code='recorder_shutdown_unconfirmed'
   raise RecorderError(code,cleanup) from error


def session_run(args,meta,inputs):
 require(sys.stdin.isatty(),'Interactive launch requires macOS Terminal input. Use --dry-run for noninteractive checks.')
 helper,source,settings,save,exe,library=inputs
 session=HERE/'sessions'/f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{args.scenario}-baseline-2880x1800-{args.method}-{args.motion}-{uuid.uuid4().hex[:8]}"
 session.mkdir(parents=True,mode=0o700);os.chmod(session,0o700)
 meta=dict(meta,session_id=session.name,status='preparing',error_codes=[],motion=args.motion)
 private=session/'private' # persistent: never auto-deleted, even on process crash or terminal loss.
 process=None;metrics={'errors':['capture_not_started']}
 try:
  env=prepare(private,helper,settings,save,source,library,args.scenario,os.environ,args.method=='frame')
  meta['launch_environment']=env;meta['private_settings_sha256']=sha(Path(env['LARECOMP_SETTINGS']))
  dump(session/'manifest-local.json',meta)
  print(f'Private session: {session}\nExecutable: {exe}\nBaseline renderer; protected save copy. No extraction or import.\n')
  require(input('Type LAUNCH to start the development game: ').strip()=='LAUNCH','Launch cancelled.')
  # Recheck identities/conflicts immediately before launch, after user interaction.
  require(not conflicts(),'Conflicting LAS Recomp instance appeared.')
  check_helper(meta['helper_sha256'])
  require(sha(exe)==meta['executable_sha256'] and sha(library)==meta['library_sha256'],'Executable/library changed after preflight.')
  with (session/'runtime-local.log').open('wb',buffering=0) as log:
   process=subprocess.Popen([str(exe)],cwd=env['LARECOMP_DATA_ROOT'],env=env,stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
   meta.update(status='launched_not_captured',pid=process.pid)
   time.sleep(1);require(process.poll() is None,'Game exited during launch. See local log; no capture succeeded.')
   verify_pid(process.pid,exe);meta['pid_verified']=True;dump(session/'manifest-local.json',meta)
   print(f'Verified development process PID {process.pid}.\nEnter the scenario room; confirm Fullscreen, Original 16:9, '+('1x' if args.scenario=='B' else 'Match display')+', AA Off. Stay in the chosen position. Return here once ready.')
   require(input('Type READY once the scene and settings are confirmed: ').strip()=='READY','Scene readiness was not confirmed.')
   meta['user_confirmed_graphics_and_scene']=True
   meta.setdefault('workload',{})['confirmation']=True
   print('Return to the game within 10 seconds. Then remain there: '+str(args.warmup)+'-second warm-up, followed by recording.',flush=True)
   time.sleep(10)
   warm_before=(session/'runtime-local.log').read_text(errors='replace');warm_offset=(session/'runtime-local.log').stat().st_size;warm_start=time.monotonic()
   time.sleep(args.warmup)
   require(process.poll() is None,'Game exited during warm-up.')
   text=(session/'runtime-local.log').read_text(errors='replace');validate_baseline(text);meta['observed']=graphics(text,args.scenario)
   meta['loaded_library_verified']=validate_loaded_library(text,library)
   warm_elapsed=max(args.warmup,time.monotonic()-warm_start)
   with (session/'runtime-local.log').open('rb') as f:f.seek(warm_offset);warm_text=f.read().decode(errors='replace')
   validate_warmup(warm_text,args.scenario,warm_elapsed,warm_before)
   offset=(session/'runtime-local.log').stat().st_size;began=time.time();began_mono=time.monotonic()
   settings_before=sha(Path(env['LARECOMP_SETTINGS']))
   meta['recording']={'begin_utc':utc(),'requested_seconds':None if args.method=='frame' else args.seconds,'requested_command_buffers':1 if args.method=='frame' else None,'motion':args.motion,'alignment':'recorder lifetime brackets; trim attach/start/stop margins in Instruments'}
   if args.method=='frame':
    # Capture layer is enabled only for this separately named session, never the first baseline timeline.
    verify_pid(process.pid,exe);code,boundaries=command(['/usr/bin/gpucapture','boundaries','--pid',str(process.pid)])
    (session/'boundaries-local.txt').write_text(boundaries)
    require(code==0,'No capturable boundary available; see local boundary output and guide.')
    code,out=command(['/usr/bin/gpucapture','start','--pid',str(process.pid),'--count','1','--output',str(session/'partial-command-buffer.gputrace')],45)
    (session/'recorder-local.log').write_text(out)
    capture_ok=code==0 and (session/'partial-command-buffer.gputrace').is_dir() and any((session/'partial-command-buffer.gputrace').iterdir())
   else:
    code=record(process,exe,session,args.method,args.seconds);capture_ok=code==0 and trace_matches(session/'recording.trace',session,began)
   meta['recording'].update(end_utc=utc(),wall_seconds=max(0,time.monotonic()-began_mono),monotonic_seconds=max(0,time.monotonic()-began_mono),recorder_exit=code)
   require(process.poll() is None,'Game exited during recording; capture requires manual inspection.')
   verify_pid(process.pid,exe)
   with (session/'runtime-local.log').open('rb') as f:f.seek(offset);window=f.read().decode(errors='replace')
   metrics=measurements(window,args.scenario,max(args.seconds,time.monotonic()-began_mono))
   if sha(Path(env['LARECOMP_SETTINGS']))!=settings_before:
    metrics['errors'].append('graphics_settings_changed')
    for key in ['runtime_fps_periodic','asynchronous_gpu_ms_per_present_proxy']:metrics[key]={'samples':0,'status':'invalid evidence; distributions withheld'}
   # Frame capture is intrusive and one frame is too short for runtime interval distributions.
   if args.method=='frame':metrics={'errors':[],'status':'partial command-buffer capture only; complete frame coverage/replay/counters unverified'}
   require(capture_ok,'Recorder failed or no fresh matching capture was produced. Inspect local recorder log.','recorder_failed')
   meta['capture_created']=True;meta['capture_validated']=False
   meta['status']='captured_quality_pending' if not metrics['errors'] else 'captured_invalid_runtime_window'
   print('\aRecording finished. Quit LAS Recomp normally. Raw capture remains local.',flush=True)
 except (Invalid,OSError,ValueError,KeyboardInterrupt,EOFError) as e:
  meta['status']='failed_or_interrupted';meta['error_codes'].append(getattr(e,'code',type(e).__name__))
  (session/'error-local.txt').write_text(traceback.format_exc())
  if isinstance(e,RecorderError):meta.setdefault('recording',{})['shutdown']=e.cleanup
  print(f'\a\nSession incomplete: {e}\nPrivate data remains at {private}',flush=True)
 finally:
  archive=None
  try:
   if process is not None:
    if process.poll() is None:print('Waiting for normal game exit; private saves are retained.',flush=True)
    meta['game_exit_code']=wait_for_exit(process)
    if meta['game_exit_code']!=0:meta['status']='abnormal_game_exit';meta['error_codes'].append('nonzero_game_exit')
   if meta.get('capture_created'):
    try:answer=input('Type CLEAN only if no loads, menus, focus/settings changes or unexpected movement occurred: ').strip()
    except (EOFError,KeyboardInterrupt):answer='unverified'
    meta['stationary_window_user_check']=answer=='CLEAN'
    # Remain pending until all metadata validation finishes.
    meta['status']='captured_quality_pending'
   meta['environment_end']=environment_metadata()
   if meta.get('capture_created') and args.method!='frame':
    # Persist a pending state even if export/parser fails, never a ready state first.
    dump(session/'manifest-local.json',meta)
    code,out=command(['xcrun','xctrace','export','--input',session/'recording.trace','--toc','--output',session/'toc-local.xml'],120)
    (session/'trace-export-local.log').write_text(out)
    try:
     require(code==0,'Trace TOC export failed.','trace_export_failed')
     import analyze
     analyze.inventory(session/'toc-local.xml',meta['pid']);meta['trace_pid_verified']=True
    except (OSError,ValueError,RuntimeError) as e:
     meta['trace_pid_verified']=False;meta['capture_validated']=False
     meta['status']='capture_requires_trace_identity_review';meta['error_codes'].append(getattr(e,'code','trace_pid_unverified'))
     (session/'trace-error-local.txt').write_text(traceback.format_exc())
   if meta.get('capture_created') and (args.method=='frame' or meta.get('trace_pid_verified')):
    good=(not metrics.get('errors') and meta.get('game_exit_code')==0 and meta.get('stationary_window_user_check'))
    meta['capture_validated']=bool(good)
    meta['status']='capture_ready_for_manual_trace_review' if good else 'capture_requires_interval_review'
   dump(session/'manifest-local.json',meta)
   archive=write_safe(session,meta,metrics)
  except (Exception,KeyboardInterrupt) as error:
   # Best effort, bounded finalization: preserve original stack locally, provide a fixed failure package.
   meta.update(status='finalization_failed',capture_validated=False,trace_pid_verified=False)
   meta['error_codes'].append(getattr(error,'code','session_failed'))
   try:(session/'finalization-error-local.txt').write_text(traceback.format_exc());dump(session/'manifest-local.json',meta)
   except OSError:pass
   try:archive=write_safe(session,meta,{'errors':meta['error_codes']})
   except (Exception,KeyboardInterrupt):print('Failure summary could not be written. Local session and private files remain.',flush=True)
  print(f"Status: {meta['status']}\nShare only: {archive if archive else 'no archive available'}\nLocal/private data: {session}")
 return 0 if meta['status']=='capture_ready_for_manual_trace_review' else 1


def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--self-check',action='store_true',help='Packaged dependency verification only; no game, saves or system tools')
 parser.add_argument('--dry-run',action='store_true',help='Preflight only; never launches the game or copies saves')
 parser.add_argument('--dynamic',choices=['key-cavern','goponga','fixed-1x','kanalet'],help='Unmodified Dynamic investigation; default 3×60-second passive observation')
 parser.add_argument('--build',choices=['baseline','beta6'],default='baseline',help='Explicit validated development build selection; baseline default preserved')
 parser.add_argument('--no-watchdog',action='store_true',help='Disable automatic watcher; emergency capture remains available')
 parser.add_argument('--prearm',action='store_true',help='Time Profiler around Kanalet Castle upper-right entrance; timed 30-second lead-in')
 parser.add_argument('--intensive',action='store_true',help='300-second realistic stress phase plus stationary recovery; no Instruments by default')
 parser.add_argument('--intensive-seconds',type=int,default=300,help='Intensive gameplay duration, 300..600 seconds')
 parser.add_argument('--intensive-trace-at',type=int,default=0,help='Optional trace request offset into intensive gameplay, in seconds')
 parser.add_argument('--recovery',choices=['screen-transition','combat'],help='Targeted event plus 120-second recovery; default location Key Cavern')
 parser.add_argument('--repeat-crossing',action='store_true',help='Return and repeat the same A-to-B crossing; screen-transition only')
 parser.add_argument('--recovery-pace-details',action='store_true',help='Optional per-frame CPU/pacing diagnostics; adds logging overhead')
 parser.add_argument('--recovery-trace-seconds',type=int,default=25,help='Optional recovery trace duration, 5..180 seconds; log observation continues independently')
 parser.add_argument('--phase-seconds',type=int,default=60,help='Each Dynamic observation phase, 60..600 seconds')
 parser.add_argument('--dynamic-trace',choices=['overview','metal'],help='Optional focused Dynamic trace instead of the normal three phases')
 parser.add_argument('--scenario',choices=SCENARIOS,default='A')
 parser.add_argument('--method',choices=['overview','metal','frame'],default='overview')
 parser.add_argument('--motion',choices=['stationary','movement'],default='stationary')
 parser.add_argument('--seconds',type=int,default=None)
 parser.add_argument('--warmup',type=int,default=30,help='Stationary warm-up after refocus (30..300 seconds)')
 for name in ['data-root','settings','save-dir']:parser.add_argument('--'+name)
 args=parser.parse_args()
 if args.self_check:
  import setup_check
  setup_check.verify(HERE);print('PACKAGED DEPENDENCIES VERIFIED — NO GAME LAUNCHED');return 0
 if args.prearm:
  if args.intensive or args.recovery or args.dynamic_trace:parser.error('--prearm selects its own Kanalet transition and Time Profiler recording.')
  args.recovery='screen-transition';args.dynamic='kanalet'
 if args.intensive:
  if args.recovery or args.repeat_crossing:parser.error('--intensive cannot combine with --recovery or --repeat-crossing.')
  if not 300<=args.intensive_seconds<=600:parser.error('--intensive-seconds must be 300..600.')
  if not 0<=args.intensive_trace_at<args.intensive_seconds:parser.error('--intensive-trace-at must fall within intensive gameplay.')
  if args.intensive_trace_at and not args.dynamic_trace:parser.error('--intensive-trace-at requires --dynamic-trace.')
  args.recovery='intensive'
 elif args.intensive_seconds!=300 or args.intensive_trace_at:
  parser.error('Intensive options require --intensive.')
 if args.recovery:
  if args.dynamic=='fixed-1x':parser.error('Recovery tests require Dynamic.')
  args.dynamic=args.dynamic or 'key-cavern'
 elif args.repeat_crossing or args.recovery_pace_details or args.recovery_trace_seconds!=25:
  parser.error('Recovery options require --recovery.')
 if args.dynamic:
  try:
   import dynamic_observe
   return dynamic_observe.run(args)
  except (Invalid,OSError,ValueError,subprocess.SubprocessError) as error:parser.exit(1,f'Dynamic workflow incomplete: {error}\nNo successful observation is claimed.\n')
 if args.dynamic_trace:parser.error('--dynamic-trace requires --dynamic.')
 args.seconds=args.seconds or (8 if args.method=='metal' else 25)
 if not 30<=args.warmup<=300:parser.error('Warm-up must be 30..300 seconds.')
 if not 5<=args.seconds<=30:parser.error('Duration must be 5..30 seconds.')
 # Frame preflight uses Overview template as availability prerequisite, not a claim of frame-capture support.
 original=args.method
 if original=='frame':args.method='overview'
 try:meta,inputs=preflight(args)
 except (Invalid,OSError,ValueError,subprocess.SubprocessError) as e:parser.exit(1,f'Preflight failed: {e}\nNo game launched.\n')
 args.method=original;meta['method']=original
 if args.dry_run:
  folder=HERE/'preflight';folder.mkdir(exist_ok=True)
  dump(folder/'latest-local.json',meta)
  safe=safe_summary(meta,{'status':'not recorded; dry-run only'})
  dump(folder/'latest-safe.json',safe)
  print('PREFLIGHT PASSED — NO GAME LAUNCHED\n'+str(folder/'latest-safe.json'))
  return 0
 try:return session_run(args,meta,inputs)
 except (Invalid,OSError) as e:parser.exit(1,f'Session did not complete: {e}\nAny private data/logs are retained; no successful capture is claimed.\n')
if __name__=='__main__':
 sys.modules['profile']=sys.modules[__name__]
 sys.exit(main())
