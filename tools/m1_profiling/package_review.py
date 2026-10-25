#!/usr/bin/env python3
"""Create an atomic, reproducible allowlisted preparation ZIP. Never package raw captures."""
from datetime import datetime,timezone
import hashlib,json,subprocess
from pathlib import Path
import profile as launch
import setup_check
import privacy
ROOT=Path(__file__).resolve().parent
ALLOW=['preflight/RI-dynamic-safe.json','recovery.py','test_recovery.py','RECOVERY_GUIDE.md','preflight/RT-dynamic-safe.json','preflight/RC-dynamic-safe.json','profile.py','analyze.py','isolation.py','privacy.py','setup_check.py','DEPENDENCIES.json','mock_recorder.py',
 'dynamic_observe.py','dynamic_log.py','test_dynamic.py','DYNAMIC_GUIDE.md','DYNAMIC_REVIEW.md','preflight/DA-dynamic-safe.json',
 'validate_tools.py','tool_probe.m','test_profiling.py','test_audit.py','package_review.py','README.md','CAPTURE_GUIDE.md',
 'ANALYSIS_PLAN.md','VALIDATION.md','AUDIT_FIXES.md','preflight/latest-safe.json','validation/capabilities-safe.json',
 'validation/tests-safe.json','validation/preservation-safe.json']
def main():
 setup_check.verify(ROOT)
 stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');archive=Path.home()/'Desktop'/f'LASRecomp-Recovery-Preparation-{stamp}.zip'
 payload={};manifest={'created_utc':stamp,'purpose':'targeted transition/combat recovery preparation; no gameplay captured by preparation','files':{}}
 for name in ALLOW:
  path=ROOT/name
  if not path.is_file() or path.is_symlink():raise ValueError('Missing/unsafe package file: '+name)
  data=path.read_bytes()
  if name.startswith('preflight/'):data=(json.dumps(privacy.summary(json.loads(data)),indent=2)+'\n').encode()
  if name.startswith('validation/'):
   kind=Path(name).name.split('-safe')[0];data=(json.dumps(privacy.review_record(kind,json.loads(data)),indent=2)+'\n').encode()
  payload[name]=data
 progress=Path.home()/'Desktop/LASRecomp-RESEARCH-PROGRESS.md'
 if not progress.is_file() or progress.is_symlink():raise ValueError('Missing/unsafe progress report.')
 payload['LASRecomp-RESEARCH-PROGRESS.md']=progress.read_bytes()
 for name,data in payload.items():manifest['files'][name]=hashlib.sha256(data).hexdigest()
 payload['PACKAGE-MANIFEST.json']=(json.dumps(manifest,indent=2)+'\n').encode()
 launch.atomic_zip(archive,payload);print(archive)
 if subprocess.run(['/usr/bin/open','-R',str(archive)],check=False).returncode:print('ZIP verified; Finder reveal failed.')
if __name__=='__main__':main()
