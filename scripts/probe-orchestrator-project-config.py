#!/usr/bin/env python3
"""Zero-model native startup canary for module-controlled project config.

Creates only an owned project and a finite MCP protocol canary. The canary must
never start. Uses a verified archive, private STDIO and isolated local auth; never
changes global config. Explicit --run; not part of ordinary offline CI.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run',action='store_true',required=True)
    p.add_argument('--archive',type=Path,required=True);p.add_argument('--sha256',required=True)
    p.add_argument('--native',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if hashlib.sha256(a.archive.read_bytes()).hexdigest()!=a.sha256:raise RuntimeError('archive hash mismatch')
    parent=Path.home()/'.local/share/pepper-orchestrator/project-config-probes';parent.mkdir(parents=True,exist_ok=True)
    root=Path(tempfile.mkdtemp(prefix='probe-',dir=parent));skill=root/'install/pepper-orchestrator';skill.mkdir(parents=True)
    with zipfile.ZipFile(a.archive) as z:
        prefixes=[n[:-len('scripts/orch.py')] for n in z.namelist() if n.endswith('/scripts/orch.py') and '/codex/' not in n]
        if len(prefixes)!=1:raise RuntimeError('one canonical skill required')
        for name in z.namelist():
            if not name.startswith(prefixes[0]) or name.endswith('/'):continue
            rel=Path(name[len(prefixes[0]):])
            if rel.is_absolute() or '..' in rel.parts:raise RuntimeError('unsafe member')
            target=skill/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(z.read(name))
    sys.path.insert(0,str(skill/'scripts'))
    import codex_transport,owner_main
    owner_main.verify_archive(a.archive,a.sha256,skill)
    project=root/'project';project.mkdir();subprocess.run(['git','init','-q',project],check=True)
    marker=root/'MCP_MUST_NOT_START';canary=root/'owned-mcp-canary.py'
    canary.write_text('import pathlib,sys,json\npathlib.Path('+repr(str(marker))+').write_text("owned canary\\n")\n'
        'for line in sys.stdin:\n r=json.loads(line)\n if "id" not in r:continue\n'
        ' result={"protocolVersion":"2024-11-05","capabilities":{"tools":{}},"serverInfo":{"name":"owned-canary","version":"1"}} if r.get("method")=="initialize" else {"tools":[]}\n'
        ' print(json.dumps({"jsonrpc":"2.0","id":r["id"],"result":result}),flush=True)\n')
    (project/'.codex').mkdir()
    (project/'.codex/config.toml').write_text('[features]\nbrowser_use = true\n[mcp_servers.owned_canary]\ncommand = '+json.dumps(sys.executable)+'\nargs = '+json.dumps(['-I','-S','-B',str(canary)])+'\nstartup_timeout_sec = 5\n')
    home=root/'home';home.mkdir();(home/'config.toml').write_text(owner_main.CONFIG)
    auth=home/'auth.json';api=None
    result={'archive_sha256':a.sha256,'fixture':str(root),'model_turns':0,'verdict':'WAIT'}
    try:
        shutil.copyfile(Path.home()/'.codex/auth.json',auth);auth.chmod(0o600)
        api=codex_transport.PrivateServer(a.native,home,root,root/'events.jsonl',actor_roots=[project],audit=True)
        response=api.start_thread(project,'gpt-6.1-sol',[],'Zero model startup canary. No turn will start.')
        time.sleep(1)
        result['thread']=response['thread']['id'];result['profile']={k:response[k] for k in ('sandbox','approvalPolicy','approvalsReviewer','runtimeWorkspaceRoots')}
        result['config']=api.call('config/read',{'cwd':str(project),'includeLayers':True})
        result['mcp']=api.call('mcpServerStatus/list',{'threadId':response['thread']['id'],'detail':'toolsAndAuthOnly'})
        result['marker_exists']=marker.exists();result['model_turns']=sum(e.get('method')=='turn/started' for e in api.events)
        api.check_configuration(project)
        if marker.exists() or result['mcp']['data'] or result['model_turns']:raise RuntimeError('project code executed or native profile escaped')
        result['verdict']='PASS'
    except Exception as error:result['error']=type(error).__name__+': '+str(error)
    finally:
        try:
            if api:api.close();result['native_stopped']=api.proc.returncode is not None
        finally:
            auth.unlink(missing_ok=True);result['auth_removed']=not auth.exists()
        a.output.write_text(json.dumps(result,indent=2)+'\n')
        print(json.dumps({k:v for k,v in result.items() if k not in ('config','profile')},indent=2))
    return 0 if result['verdict']=='PASS' else 2


if __name__=='__main__':raise SystemExit(main())
