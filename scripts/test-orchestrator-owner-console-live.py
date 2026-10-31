#!/usr/bin/env python3
"""Explicit paid owner-console smoke after the private-autonomy fixture completes.

Unarchives only this fixture's three histories, runs the shipped --resume console
(status, pause, stop), then archives them again. Never accepts a native approval
or creates another executor. Not invoked by CI. Requires the exact archive hash.
"""
import argparse,json,os,shutil,subprocess,sys,time,hashlib,zipfile
from pathlib import Path
def fixed_thread_turns(events, roles):
    """Three startup turns; later watcher wakes may target only the coordinator."""
    starts = [e['params']['threadId'] for e in events if e.get('method') == 'turn/start']
    actual = [e['params']['threadId'] for e in events if e.get('method') == 'turn/started']
    modules = [tid for tid,row in roles.items() if row['role'] == 'module']
    valid = (set(starts) == set(roles) and len(starts) == len(roles)
        and set(actual) <= set(roles) and all(actual.count(tid) == 1 for tid in modules)
        and all(actual.count(tid) >= 1 for tid in roles))
    return {'verified': valid, 'explicit_context_starts': len(starts),
        'native_turns_per_thread': {tid: actual.count(tid) for tid in roles}}


p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run',action='store_true',required=True);p.add_argument('--fixture',type=Path,required=True);p.add_argument('--archive',type=Path,required=True);p.add_argument('--sha256',dest='sha',required=True);p.add_argument('--regrade',action='store_true',help='reassess saved native evidence without a server/model call');a=p.parse_args()
r=a.fixture.resolve();data=r/'owner-data';home=data/'codex-home';auth=home/'auth.json'
if r.parent != (Path.home()/'.local/share/pepper-orchestrator/private-autonomy-trials').resolve() or not r.name.startswith('trial-'):
 raise RuntimeError('only disposable private-autonomy fixtures are supported')
if hashlib.sha256(a.archive.read_bytes()).hexdigest()!=a.sha:
 raise RuntimeError('archive hash mismatch before importing candidate code')
skill=r/'install/pepper-orchestrator'
with zipfile.ZipFile(a.archive) as z:
 roots=[n[:-len('scripts/orch.py')] for n in z.namelist() if n.endswith('/scripts/orch.py') and '/codex/' not in n]
 if len(roots)!=1:raise RuntimeError('one canonical skill required')
 for n in z.namelist():
  if n.startswith(roots[0]) and not n.endswith('/'):
   rel=Path(n[len(roots[0]):])
   if rel.is_absolute() or '..' in rel.parts or (skill/rel).read_bytes()!=z.read(n):raise RuntimeError('installed candidate mismatch')
sys.path.insert(0,str(r/'install/pepper-orchestrator/scripts'))
import codex_transport,autonomy,owner_main
owner_main.verify_archive(a.archive,a.sha,skill)
before=json.loads((data/'roles.json').read_text());assert autonomy.process_observation(before['process'])['state']=='exited'
if a.regrade:
 proof=json.loads((r/'cli-smoke.json').read_text())
 original=r/'cli-smoke-initial.json'
 if not original.exists():original.write_text(json.dumps(proof,indent=2)+'\n')
 events=[json.loads(line)['message'] for line in Path(before['event_log']).read_text().splitlines()]
 assessment=fixed_thread_turns(events,before['roles'])
 proof['checks'].pop('context_turns_only',None)
 proof['checks']['fixed_thread_startup_and_watcher_wakes']=assessment['verified']
 proof['turn_assessment']=assessment;proof['regrade_model_turns']=0
 proof['grader_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
 valid=proof.get('returncode')==0 and all(proof['checks'].values()) and not proof.get('cleanup_error')
 proof['verdict']='PASS' if valid else 'WAIT'
 if valid:proof.pop('error',None)
 (r/'cli-smoke.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2));sys.exit(0 if valid else 2)
roles=list(before['roles'].values())
if len(roles)!=3 or sorted(v['role'] for v in roles)!=['coordinator','module','module']:raise RuntimeError('expected completed three-thread fixture')
manifest={'version':1,'model':roles[0]['profile']['model'],'workspace':before['workspace'],
 'coordinator':{'cwd':next(v['worktree'] for v in roles if v['role']=='coordinator')},
 'modules':[{'module':v['module'],'wp':'WP-'+v['module'].upper()+'-01','cwd':v['worktree'],'branch_prefix':v['branch_prefix']} for v in roles if v['role']=='module']}
(r/'cli-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
proof={'archive_sha256':a.sha,'threads':list(before['roles']),'checks':{},'new_executors':0,'before_manifest':before}
def history(method,label):
 api=None
 current=json.loads((data/'roles.json').read_text())
 if autonomy.process_observation(current['process'])['state']!='exited':raise RuntimeError('old fixture owner is still live/unobservable')
 try:
  shutil.copyfile(Path.home()/'.codex/auth.json',auth);auth.chmod(0o600)
  api=codex_transport.PrivateServer(before['native'],home,data,data/(label+'-events.jsonl'),actor_roots=[v['worktree'] for v in before['roles'].values()],audit=True)
  for tid in before['roles']:api.call(method,{'threadId':tid})
  assert not any(e.get('method')=='turn/started' for e in api.events)
 finally:
  try:
   if api:api.close()
  finally:auth.unlink(missing_ok=True)
 proof['checks'][label]={'model_turns':0,'native_exited':api.proc.returncode is not None,'auth_removed':not auth.exists()}
try:
 history('thread/unarchive','cli-unarchive')
 argv=[sys.executable,'-I','-S','-B',str(r/'install/pepper-orchestrator/scripts/owner_main.py'),
  '--manifest',str(r/'cli-manifest.json'),'--directory',str(data),'--native',before['native'],
  '--archive',str(a.archive),'--sha256',a.sha,'--resume']
 preflight=subprocess.run(argv+['--preflight'],capture_output=True,text=True,timeout=30)
 proof['checks']['preflight']=preflight.returncode==0
 proof['preflight_stdout']=preflight.stdout
 if preflight.returncode:raise RuntimeError('owner console preflight failed: '+preflight.stderr)
 started=time.monotonic()
 result=subprocess.run(argv,input='status\npause\nstop\n',capture_output=True,text=True,timeout=300)
 proof.update(returncode=result.returncode,stdout=result.stdout,stderr=result.stderr,elapsed_seconds=time.monotonic()-started)
 after=json.loads((data/'roles.json').read_text())
 proof['checks']['same_threads']=set(before['roles'])==set(after['roles'])
 proof['checks']['generation_advanced']=after['generation']==before['generation']+1
 proof['checks']['native_stopped']=autonomy.process_observation(after['process'])['state']=='exited'
 proof['checks']['auth_removed']=not auth.exists()
 es=[json.loads(l)['message'] for l in Path(after['event_log']).read_text().splitlines()]
 proof['native_turns_started']=sum(e.get('method')=='turn/started' for e in es)
 proof['checks']['no_thread_start']=not any(e.get('method')=='thread/start' for e in es)
 proof['turn_assessment']=fixed_thread_turns(es,before['roles'])
 proof['checks']['fixed_thread_startup_and_watcher_wakes']=proof['turn_assessment']['verified']
 proof['checks']['no_approvals']=not any(e.get('method','').endswith('/requestApproval') for e in es)
 if result.returncode or not all(v for v in proof['checks'].values()):raise RuntimeError('CLI smoke failed')
 proof['verdict']='PASS'
except Exception as error:
 proof.update(verdict='WAIT',error=type(error).__name__+': '+str(error))
finally:
 try:history('thread/archive','cli-final-archive')
 except Exception as error:proof.update(verdict='WAIT',cleanup_error=str(error))
 auth.unlink(missing_ok=True)
 (r/'cli-smoke.json').write_text(json.dumps(proof,indent=2)+'\n')
 print(json.dumps(proof,indent=2))
sys.exit(0 if proof['verdict']=='PASS' else 2)
