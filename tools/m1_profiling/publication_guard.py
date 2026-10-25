"""Pure destination checks for the explicitly authorized, non-force fork publication."""
import re

def destination(login,remote,branch,existing_sha=None):
 if login!='gsel001':raise ValueError('authenticated account is not fork owner')
 if remote not in ['https://github.com/gsel001/LASRecomp.git','https://github.com/gsel001/LASRecomp']:raise ValueError('not the authorized fork remote')
 if not re.fullmatch(r'codex/[a-z][a-z0-9-]{2,90}',branch) or '..' in branch:raise ValueError('not a new task branch')
 if existing_sha is not None:raise ValueError('destination branch already exists; no rewrite permitted')
 return ['git','push','myfork','HEAD:refs/heads/'+branch]
