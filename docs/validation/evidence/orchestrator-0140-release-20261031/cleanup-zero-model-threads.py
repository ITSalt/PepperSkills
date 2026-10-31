import hashlib,json,os,shutil,sys,uuid
from pathlib import Path
rpath=Path(sys.argv[1]);result=json.loads(rpath.read_text());root=Path(result['fixture']);home=root/'home';auth=home/'auth.json'
sys.path.insert(0,str(root/'install/pepper-orchestrator/scripts'))
import codex_transport
native=Path(sys.argv[2]);api=None
try:
 shutil.copyfile(Path.home()/'.codex/auth.json',auth);auth.chmod(0o600)
 api=codex_transport.PrivateServer(native,home,root,root/('archive-events-'+uuid.uuid4().hex+'.jsonl'),actor_roots=[root/'project'],audit=True)
 result['history_cleanup']=[]
 for key in ['thread','redirected_thread']:
  try:
   api.call('thread/archive',{'threadId':result[key]})
   result['history_cleanup'].append('archived')
  except codex_transport.TransportError as e:
   if 'no rollout found for thread id '+result[key] not in str(e):raise
   result['history_cleanup'].append('no_rollout_zero_model_thread')
 assert not any(e.get('method')=='turn/started' for e in api.events)
 result['history_cleanup_complete']=True
finally:
 try:
  if api:api.close();result['cleanup_native_stopped']=api.proc.returncode is not None
 finally:
  auth.unlink(missing_ok=True);result['cleanup_auth_removed']=not auth.exists()
rpath.write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({k:result[k] for k in ['verdict','history_cleanup','history_cleanup_complete','cleanup_native_stopped','cleanup_auth_removed']}))
