#!/usr/bin/env python3
"""Non-gameplay capability check: compile tiny synthetic clear helper and attach tools."""
import argparse,json,os,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
ENV=dict(os.environ,DEVELOPER_DIR='/Applications/Xcode.app/Contents/Developer',MTL_CAPTURE_ENABLED='1')
def run(cmd,timeout=60):
 try:
  p=subprocess.run(cmd,env=ENV,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,timeout=timeout)
  return {'exit_code':p.returncode,'output':p.stdout[-16000:]}
 except subprocess.TimeoutExpired:return {'exit_code':None,'output':'Timed out; not validated'}
def main():
 a=argparse.ArgumentParser(description=__doc__);a.add_argument('--output',type=Path,required=True);args=a.parse_args();args.output.mkdir(parents=True,exist_ok=False)
 exe=args.output/'tool-probe'
 report={'synthetic_only':True,'no_game_launched':True}
 report['compile']=run(['xcrun','clang','-O2','-Wall','-Wextra','-Werror','-fobjc-arc','-framework','Foundation','-framework','Metal','-framework','CoreGraphics',str(ROOT/'tool_probe.m'),'-o',str(exe)])
 if report['compile']['exit_code']:raise SystemExit('Probe compile failed')
 report['templates']=run(['xcrun','xctrace','list','templates'])
 report['metadata']=run([str(exe)])
 for template in ['Game Performance Overview','Game Performance','Metal System Trace']:
  name=template.lower().replace(' ','-');trace=args.output/(name+'.trace')
  with (args.output/(name+'-helper.log')).open('w') as f:
   helper=subprocess.Popen([str(exe),'40'],env=ENV,stdout=f,stderr=f,start_new_session=True)
   try:
    time.sleep(1)
    report[name]=run(['xcrun','xctrace','record','--template',template,'--attach',str(helper.pid),'--time-limit','2s','--output',str(trace)],55)
    report[name]['trace_exists']=trace.is_dir()
    if trace.is_dir():report[name]['export']=run(['xcrun','xctrace','export','--input',str(trace),'--toc','--output',str(args.output/(name+'-toc.xml'))])
   finally:helper.terminate();helper.wait(timeout=10)
  (args.output/'capabilities-local.json').write_text(json.dumps(report,indent=2))
 with (args.output/'gpu-helper.log').open('w') as f:
  helper=subprocess.Popen([str(exe),'25'],env=ENV,stdout=f,stderr=f,start_new_session=True)
  try:
   time.sleep(1);report['gpucapture-list']=run(['/usr/bin/gpucapture','list'])
   report['gpucapture-boundaries']=run(['/usr/bin/gpucapture','boundaries','--pid',str(helper.pid)])
   capture=args.output/'synthetic.gputrace'
   report['gpucapture-start']=run(['/usr/bin/gpucapture','start','--pid',str(helper.pid),'--count','1','--output',str(capture)],20)
   report['gpucapture-start']['capture_exists']=capture.exists()
  finally:helper.terminate();helper.wait(timeout=10)
 (args.output/'capabilities-local.json').write_text(json.dumps(report,indent=2))
 print(args.output/'capabilities-local.json')
if __name__=='__main__':main()
