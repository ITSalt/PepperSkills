"""Export authority/provenance events, omitting reasoning, account and usage data."""
import argparse,hashlib,json,re
from pathlib import Path


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
 p=argparse.ArgumentParser();p.add_argument('--result',type=Path,required=True);p.add_argument('--data',type=Path,required=True)
 p.add_argument('--project-result',type=Path,required=True);p.add_argument('--project-events',type=Path,required=True)
 p.add_argument('--output',type=Path,required=True);p.add_argument('--label',required=True);a=p.parse_args()
 result=json.loads(a.result.read_text());project=json.loads(a.project_result.read_text());a.output.mkdir(parents=True,exist_ok=True)
 aliases=[(result['fixture'],'/FIXTURE'),(project['fixture'],'/PROJECT_CONFIG_FIXTURE'),(result['native'],'/NATIVE/codex')]
 repository=result.get('github_repository')
 if repository:aliases.append((repository,'example/fixture-'+a.label))
 hosts=set()
 def find_hosts(value):
  if isinstance(value,dict):
   for k,v in value.items():
    if k=='host' and isinstance(v,str):hosts.add(v)
    find_hosts(v)
  elif isinstance(value,list):
   for v in value:find_hosts(v)
 cli=a.data/'cli-smoke.json'
 if not cli.exists():cli=a.data.parent/'cli-smoke.json'
 for file in [a.result,a.data/'roles.json',cli]:
  if file.exists():find_hosts(json.loads(file.read_text()))
 def clean(v):
  if isinstance(v,dict):
   if v.get('type') in ('reasoning','reasoningSummary'):return None
   return {clean(k):clean(x) for k,x in v.items() if k not in ('encrypted_content','encryptedContent','tokenUsage','totalTokenUsage','accountId','account_id','userId','user_id')}
  if isinstance(v,list):return [clean(x) for x in v if not isinstance(x,dict) or x.get('type') not in ('reasoning','reasoningSummary')]
  if isinstance(v,str):
   for old,new in sorted(aliases,key=lambda x:-len(x[0])):v=v.replace(old,new)
   for host in hosts:v=v.replace(host,'fixture-host-'+a.label)
   v=v.replace('/PROJECT_CONFIG_FIXTURE/home/','/PROJECT_CONFIG_FIXTURE/owner-home/')
   v=re.sub(r'/(?:Users|home)/[^/\s"\\]+','/HOST_HOME',v)
   v=re.sub(r'[0-9a-f]{8}-[0-9a-f-]{27}:(\d+)',r'FIXTURE_BOOT:\1',v)
   return v
  return v
 def write(name,value):
  (a.output/name).write_text(json.dumps(clean(value),indent=2,ensure_ascii=False)+'\n')
 methods={'initialize','remoteControl/disable','remoteControl/status/read','mcpServerStatus/list','config/read',
  'thread/start','thread/resume','thread/queue/add','thread/compact/start','thread/archive','thread/unarchive','turn/start',
  'turn/started','turn/completed','item/started','item/completed','item/tool/call','item/permissions/requestApproval','item/fileChange/requestApproval'}
 provenance=[]
 def export_log(file,out):
  records=[json.loads(line) for line in file.read_text().splitlines()]
  inventory=set()
  for e in records:
   item=e.get('message',{}).get('params',{}).get('item',{})
   if item.get('type')=='custom_tool_call' and 'ALL_TOOLS' in item.get('input','') and 'Object.getOwnPropertyNames(globalThis)' in item.get('input',''):inventory.add(item['call_id'])
  selected=[];requests={}
  for ordinal,e in enumerate(records):
   m=e['message'];method=m.get('method');params=m.get('params') or {};item=params.get('item') or {}
   if e['direction']=='owner_to_native' and method and 'id' in m:requests[m['id']]=method
   keep=method in methods or method=='rawResponseItem/completed' and item.get('call_id') in inventory
   if method in ('item/started','item/completed') and item.get('type')=='reasoning':keep=False
   if method is None and 'id' in m:
    keep=(e['direction']=='owner_to_native' or requests.get(m['id']) in methods)
   if not keep:continue
   # Config contains only the isolated fixture's profile and project canary.
   selected.append({'ordinal':ordinal,**e})
  write(out,selected)
  provenance.append({'source':file.name,'raw_sha256':sha(file),'records_original':len(records),'records_exported':len(selected),
   'export':out,'export_sha256':sha(a.output/out)})
 write('result.json',result)
 for name,file in (('roles.json',a.data/'roles.json'),('cli-smoke.json',cli)):
  if file.exists():write(name,json.loads(file.read_text()))
 write('project-config.json',project)
 for file in sorted(a.data.glob('*.jsonl')):
  if 'events' in file.name and file.name!='project-config-events.jsonl':export_log(file,file.stem+'.json')
 export_log(a.project_events,'project-config-events.json')
 write('export-provenance.json',{'label':a.label,'exporter_sha256':sha(Path(__file__)),
  'sources':provenance,'redactions':'Fixture, home, native, repository, host and boot identifiers aliased; reasoning, account and usage telemetry omitted. Event ordinals, native envelopes, commands, results and errno retained.'})
 print(a.label,len(provenance),'logs exported')


if __name__=='__main__':main()
