#!/usr/bin/env python3
"""Strict trace identity, selected numeric evidence, and explicit comparison purposes."""
import argparse,csv,json,math,re,sys,traceback
from pathlib import Path
import xml.etree.ElementTree as ET
import profile as launch
import privacy
METRICS={'cpu_frame_ms','gpu_execution_ms','present_interval_ms','command_buffer_gpu_ms','render_pass_gpu_ms'}
FRAME_METRICS={'cpu_frame_ms','gpu_execution_ms','present_interval_ms'}
KNOWN_SCHEMAS={'metal-gpu-intervals','metal-application-command-buffer-submissions','metal-command-buffer-frame-assignment','metal-perf-overview-layer-per-frame-metric','metal-perf-overview-layer-per-frame-interval-metric'}
class TraceError(launch.Invalid):pass

def inventory(toc,pid):
 try:root=ET.parse(toc).getroot()
 except FileNotFoundError as e:raise TraceError('Trace metadata is missing.','trace_toc_missing') from e
 except ET.ParseError as e:raise TraceError('Trace metadata is malformed.','trace_toc_malformed') from e
 if root.tag!='trace-toc':raise TraceError('Unexpected trace metadata root.','trace_toc_unexpected')
 runs=root.findall('./run')
 if len(runs)!=1:raise TraceError('Exactly one trace run is required.','trace_toc_incomplete')
 targets=runs[0].findall('./info/target/process')
 if len(targets)!=1 or not targets[0].get('pid','').isdigit() or runs[0].find('data') is None:
  raise TraceError('Trace target/data metadata incomplete.','trace_toc_incomplete')
 if targets[0].get('pid')!=str(pid):raise TraceError('Trace PID mismatch.','trace_toc_pid_mismatch')
 schemas={t.get('schema') for t in root.findall('./run/data/table') if t.get('schema')}
 if not schemas:raise TraceError('Trace table metadata is empty.','trace_toc_incomplete')
 return {'target_pid_matches':True,'schema_count':len(schemas),'schemas':sorted(schemas&KNOWN_SCHEMAS),
         'timing_status':'table presence does not prove rows, units, per-frame semantics or useful game metrics'}

def read_samples(path,session_id,pid,method):
 required={'session_id','pid','metric','value','unit','start_s','end_s','source','sample_id','time_s','frame_id'}
 series={};bounds=set();sources=set()
 with path.open(newline='') as f:
  rows=csv.DictReader(f)
  launch.require(set(rows.fieldnames or [])==required,'CSV columns must match the version-2 selected-sample contract.')
  for row in rows:
   launch.require(None not in row and all(v is not None for v in row.values()),'Incomplete CSV interval.')
   launch.require(row['session_id']==session_id and row['pid']==str(pid),'Mixed session or PID.')
   metric=row['metric'];launch.require(metric in METRICS and row['unit']=='ms','Unknown metric/units.')
   launch.require(row['source'] in ['instruments_selection','metal_counter_replay'],'Unknown source.')
   launch.require(not(method=='frame' and metric in FRAME_METRICS),'Partial capture cannot provide frame series.')
   value,start,end,t=[float(row[k]) for k in ['value','start_s','end_s','time_s']]
   launch.require(all(math.isfinite(v) for v in [value,start,end,t]) and value>0 and 0<=start<=t<end,'Invalid timing/selection.')
   launch.require(bool(row['sample_id']) and len(row['sample_id'])<=128,'Missing sample identity.')
   frame=int(row['frame_id']) if row['frame_id'] else None
   launch.require(frame is None or frame>=0,'Invalid frame ID.')
   if metric in FRAME_METRICS:launch.require(frame is not None,'Frame series needs actual frame identities.')
   series.setdefault(metric,[]).append((row['sample_id'],t,frame,value));bounds.add((start,end));sources.add(row['source'])
 launch.require(len(bounds)==1 and bool(series),'Exactly one selected interval required.')
 start,end=next(iter(bounds));minimum=5 if method=='metal' else 20
 # Partial pass/CB captures have no whole-timeline coverage promise; require distinct samples only.
 if method!='frame':launch.require(end-start>=minimum,'Selected interval is too short.')
 for metric,items in series.items():
  launch.require(len(items)>=3 and len({r[0] for r in items})==len(items),'Insufficient or duplicated sample identities.')
  deltas=[b[1]-a[1] for a,b in zip(items,items[1:])]
  launch.require(all(d>=0 for d in deltas),'Backward selected timestamps.')
  if metric in FRAME_METRICS:
   launch.require(all(d>0 for d in deltas),'Duplicate frame timestamps.')
   launch.require(all(b[2]==a[2]+1 for a,b in zip(items,items[1:])),'Missing/duplicated/backward frame observations.')
  # CB/pass identifiers can be opaque and several can share a frame or timestamp.
  if method!='frame':
   launch.require(items[0][1]-start<=1 and end-items[-1][1]<=1 and max(deltas,default=0)<=1,'Insufficient selected-interval coverage.')
 return {'selection_seconds':[start,end],'sources':sorted(sources),'metrics':{k:launch.distribution([i[3] for i in v],method='linear quantile; explicitly selected samples') for k,v in series.items()},
         'status':'user-supplied selected-interval samples; extraction semantics require independent review'}

def required(data,path):
 value=data
 for key in path.split('.'):
  launch.require(isinstance(value,dict) and key in value,f'Missing comparison metadata: {path}')
  value=value[key]
 launch.require(value is not None and value!='unverified',f'Unverified comparison metadata: {path}')
 return value

def compare(a,b,purpose='repeatability'):
 launch.require(purpose in ['repeatability','renderer','resolution'],'Explicit known comparison purpose required.')
 fields=['session_id','scenario','status','workload.scene','workload.position','workload.confirmation','method','motion','expected_drawable',
         'executable_sha256','library_sha256','requested_graphics.fullscreen','requested_graphics.aspect','requested_graphics.antialias',
         'requested_graphics.dynamic','requested_graphics.upscaler','requested_graphics.resolution','observed.drawable_observed','observed.render_scale_observed',
         'observed.render_area_derived_not_observed','renderer_optimization.name','renderer_optimization.value','renderer','pid_executable_verified','loaded_library_verified','trace_pid_verified',
         'user_confirmed_graphics_and_scene','recording.requested_seconds']
 for data in [a,b]:
  for f in fields:
   required(data,f)
   launch.require(required(privacy.summary(data),f)==required(data,f),'Invalid typed comparison metadata: '+f)
  launch.require(f"-{data['scenario']}-{data['renderer']}-" in data['session_id'],'Session filename/metadata identity mismatch.')
  launch.require(data['status']=='capture_ready_for_manual_trace_review','Capture quality checks not complete.')
  for flag in ['pid_executable_verified','loaded_library_verified','trace_pid_verified','user_confirmed_graphics_and_scene']:
   launch.require(data[flag] is True,'Comparison identity/confirmation missing.')
  launch.require(required(data,'workload.confirmation') is True,'Scene/position confirmation missing.')
  for h in ['executable_sha256','library_sha256']:launch.require(privacy.digest(data[h])==data[h],'Malformed identity hash.')
  launch.require(data['expected_drawable']==required(data,'observed.drawable_observed') and len(data['expected_drawable'])==2 and all(type(v) is int and v>0 for v in data['expected_drawable']),'Drawable identity invalid.')
  launch.require(required(data,'renderer_optimization.name')=='LARECOMP_DEPTH_NO_FS' and required(data,'renderer_optimization.value') in [0,1],'Unknown optimization.')
  launch.require((data['renderer']=='experimental')==(required(data,'renderer_optimization.value')==1),'Renderer flag/label mismatch.')
  launch.require(not required(data,'requested_graphics.dynamic'),'Dynamic resolution is not comparable here.')
 launch.require(a['session_id']!=b['session_id'],'Cannot compare a session to itself.')
 allowed={'session_id','status','pid_executable_verified','loaded_library_verified','trace_pid_verified','user_confirmed_graphics_and_scene'}
 if purpose=='resolution':allowed|={'scenario','requested_graphics.resolution','observed.render_scale_observed','observed.render_area_derived_not_observed'}
 if purpose=='renderer':allowed|={'renderer','renderer_optimization.value'}
 for f in fields:
  if f not in allowed:launch.require(required(a,f)==required(b,f),f'Comparison mismatch: {f}')
 if purpose=='resolution':
  launch.require({required(a,'requested_graphics.resolution'),required(b,'requested_graphics.resolution')}=={'match','1'},'Resolution comparison requires Match versus 1x.')
  for d in [a,b]:
   scale=1.5 if required(d,'requested_graphics.resolution')=='match' else 1.
   launch.require(required(d,'observed.render_area_derived_not_observed')==([2880,1620] if scale==1.5 else [1920,1080]),'Derived resolution mismatch.')
   launch.require(required(d,'observed.render_scale_observed')==[scale,scale],'Observed resolution/scale mismatch.')
   launch.require(d['expected_drawable']==[2880,1800] and required(d,'observed.drawable_observed')==[2880,1800],'Resolution control needs the same Retina drawable.')
 elif purpose=='renderer':
  launch.require(required(a,'renderer_optimization.name')=='LARECOMP_DEPTH_NO_FS' and {required(a,'renderer_optimization.value'),required(b,'renderer_optimization.value')}=={0,1},'Only specified renderer flag may change.')
  launch.require({a['renderer'],b['renderer']}=={'baseline','experimental'},'Renderer mode labels must differ correctly.')
  for d in [a,b]:launch.require((d['renderer']=='experimental')==(required(d,'renderer_optimization.value')==1),'Renderer label/flag mismatch.')
 # Cross-scenario resolution A/B is allowed, but physical workload identity must agree above.
 if purpose!='resolution':launch.require(a.get('scenario')==b.get('scenario'),'Scenario mismatch.')
 else:launch.require({a.get('scenario'),b.get('scenario')}=={'A','B'},'Resolution comparison requires scenarios A and B.')
 differences=[]
 for field in ['environment.power_source','environment.low_power_mode_by_source','environment.gpu_display_thermal.thermal_state']:
  try:
   if required(a,field)!=required(b,field):differences.append(field)
  except launch.Invalid:differences.append(field+'.unverified')
 return {'compatible_metadata':True,'purpose':purpose,'environment_differences':differences,
         'interpretation':'Metadata compatibility only. Exact room/camera and selected metric meaning still require human review.'}

ANALYSIS_SCHEMA={'failure_stage':privacy.enum('capture_read','trace_inventory','sample_input','comparison','report'),'trace_review_required':privacy.boolean,'session_id':privacy.session,'status':privacy.enum('analysis_failed','analysis_complete'),
 'trace_inventory':{'target_pid_matches':privacy.boolean,'schema_count':privacy.integer,'schemas':[privacy.enum(*KNOWN_SCHEMAS)]},
 'selected_metrics':{'selection_seconds':[privacy.number],'sources':[privacy.enum('instruments_selection','metal_counter_replay')],'metrics':{m:privacy.STAT for m in METRICS}},
 'comparison':{'compatible_metadata':privacy.boolean,'purpose':privacy.enum('renderer','resolution','repeatability'),
 'environment_differences':[privacy.enum('environment.power_source','environment.low_power_mode_by_source','environment.gpu_display_thermal.thermal_state','environment.power_source.unverified','environment.low_power_mode_by_source.unverified','environment.gpu_display_thermal.thermal_state.unverified')]},'error_codes':[privacy.code]}
def sanitize_analysis(data):return privacy.clean(data,ANALYSIS_SCHEMA)

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('session',type=Path);p.add_argument('--samples',type=Path);p.add_argument('--compare',type=Path)
 p.add_argument('--comparison-type',choices=['repeatability','renderer','resolution'],default='repeatability')
 args=p.parse_args();s=args.session.resolve();local={};metrics={};phase='capture_read';out={'status':'analysis_failed'}
 try:
  local=json.loads((s/'manifest-local.json').read_text());out['session_id']=local['session_id']
  metrics=json.loads((s/'safe/measurements.json').read_text())
  if (s/'recording.trace').is_dir():
   phase='trace_inventory'
   toc=s/'toc-local.xml';code,text=launch.command(['xcrun','xctrace','export','--input',s/'recording.trace','--toc','--output',toc],120)
   (s/'analysis-export-local.log').write_text(text);launch.require(code==0,'TOC export failed.','trace_export_failed')
   out['trace_inventory']=inventory(toc,local['pid'])
  if args.samples:
   phase='sample_input';out['selected_metrics']=read_samples(args.samples,local['session_id'],local['pid'],local['method'])
  if args.compare:
   phase='comparison';out['comparison']=compare(json.loads((s/'safe/summary.json').read_text()),json.loads(args.compare.read_text()),args.comparison_type)
  phase='report';out.update(status='analysis_complete',trace_review_required=False)
  launch.dump(s/'analysis-status.json',sanitize_analysis(out))
  archive=launch.write_safe(s,local,metrics,extra=out,write_sidecars=False);print(archive);return 0
 except (Exception,KeyboardInterrupt) as error:
  code=getattr(error,'code','analysis_failed')
  out.update(status='analysis_failed',error_codes=[code],failure_stage=phase,trace_review_required=phase=='trace_inventory')
  try:
   (s/'analysis-error-local.txt').write_text(traceback.format_exc())
   launch.dump(s/'analysis-status.json',sanitize_analysis(out))
   # Keep a prior good safe-summary.zip byte-for-byte intact; write a separate failure report.
   failure=launch.write_safe(s,dict(local),metrics,extra=out,archive_name='analysis-error.zip',write_sidecars=False)
   print(f'Analysis failed ({code}); error report: {failure}',file=sys.stderr)
  except (Exception,KeyboardInterrupt):print('Analysis failed; error ZIP unavailable. Original archive/trace retained.',file=sys.stderr)
  return 1
if __name__=='__main__':sys.exit(main())
