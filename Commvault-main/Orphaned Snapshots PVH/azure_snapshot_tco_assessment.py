#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,json,logging,re,sys
from dataclasses import asdict,dataclass
from datetime import datetime,timezone
from decimal import Decimal,InvalidOperation
from pathlib import Path
from typing import Iterable
from azure.core.exceptions import HttpResponseError, ResourceNotFoundError
from azure.identity import DefaultAzureCredential
from azure.mgmt.compute import ComputeManagementClient
try:
    from azure.mgmt.subscription import SubscriptionClient
except ImportError:
    SubscriptionClient=None
LOG=logging.getLogger("azure-snapshot-tco")
DISK_ID=re.compile(r"^/subscriptions/([^/]+)/resourceGroups/([^/]+)/providers/Microsoft\.Compute/disks/([^/]+)$",re.I)
@dataclass
class Finding:
    subscription_id:str; resource_group:str; snapshot_name:str; snapshot_id:str; location:str
    source_resource_id:str; source_disk_exists:str; created_time_utc:str; age_days:int
    incremental:bool; sku_name:str; logical_size_gib:int; estimated_billable_gib:str
    price_per_gib_month:str; estimated_storage_exposure_monthly:str
    estimated_storage_exposure_annual:str; currency:str; classification:str
    rationale:str; tags_json:str; estimate_basis:str

def parser():
 p=argparse.ArgumentParser()
 p.add_argument('--subscription',action='append');p.add_argument('--tenant-id')
 p.add_argument('--min-age-days',type=int,default=90);p.add_argument('--high-confidence-age-days',type=int,default=180)
 p.add_argument('--include-tag',action='append',default=[]);p.add_argument('--protect-tag',action='append',default=[])
 p.add_argument('--include-no-source',action='store_true');p.add_argument('--rates-json');p.add_argument('--default-rate',type=Decimal)
 p.add_argument('--currency',default='USD');p.add_argument('--utilization-percent',type=Decimal,default=Decimal('100'))
 p.add_argument('--output',default='azure_snapshot_tco.csv');p.add_argument('--summary-output',default='azure_snapshot_tco_summary.json')
 p.add_argument('--log-level',default='INFO');return p

def parse_rules(values):
 r=[]
 for i in values:
  k,s,v=i.partition('=');r.append((k.lower(),v if s else None))
 return r

def matches(tags,rules):
 n={k.lower():str(v) for k,v in tags.items()}
 return any(k in n and (v is None or n[k]==v) for k,v in rules)

def load_rates(path,default):
 rates={}
 if path:
  raw=json.loads(Path(path).read_text())
  for k,v in raw.items(): rates[str(k).lower()]=Decimal(str(v))
 if default is not None: rates.setdefault('default',default)
 return rates

def resource_group(rid):
 parts=rid.strip('/').split('/')
 for i,p in enumerate(parts):
  if p.lower()=='resourcegroups': return parts[i+1]
 raise ValueError(rid)

def enabled_subscriptions(credential):
 if SubscriptionClient is None:
  raise RuntimeError('No subscription specified and SubscriptionClient is not available. Use --subscription.')
 client=SubscriptionClient(credential)
 return [s.subscription_id for s in client.subscriptions.list() if str(s.state).lower().endswith('enabled')]

def source_status(source_id,credential,clients):
 m=DISK_ID.match(source_id or '')
 if not m: return None,'source_is_absent_or_not_a_managed_disk_id'
 subscription,rg,disk_name=m.groups();client=clients.setdefault(subscription.lower(),ComputeManagementClient(credential,subscription))
 try:
  client.disks.get(rg,disk_name);return True,'source_disk_exists'
 except ResourceNotFoundError:
  return False,'source_disk_missing'
 except HttpResponseError as exc:
  return None,f'source_validation_failed:{getattr(exc,"status_code","unknown")}'

def classify(exists,has_source,age,tags,args,include,protect):
 if exists is True: return 'Active','source_disk_exists'
 if protect and matches(tags,protect): return 'Recovery Candidate','source_missing_or_unknown_but_protection_tag_matches'
 if include and not matches(tags,include): return 'Recovery Candidate','required_candidate_tag_missing'
 if exists is None and not (args.include_no_source and not has_source): return 'Review Required','source_absent_unparseable_or_validation_failed'
 if age < args.min_age_days: return 'Recovery Candidate','source_missing_but_snapshot_is_younger_than_threshold'
 if age >= args.high_confidence_age_days and not tags: return 'High TCO Opportunity','source_missing_no_tags_and_high_age_threshold_met'
 return 'TCO Opportunity','source_missing_and_minimum_age_met'

def main():
 args=parser().parse_args();logging.basicConfig(level=getattr(logging,args.log_level))
 include,protect=parse_rules(args.include_tag),parse_rules(args.protect_tag)
 rates=load_rates(args.rates_json,args.default_rate)
 credential=DefaultAzureCredential(tenant_id=args.tenant_id) if args.tenant_id else DefaultAzureCredential()
 subs=args.subscription or enabled_subscriptions(credential)
 clients={};findings=[];errors=[];now=datetime.now(timezone.utc);util=args.utilization_percent/Decimal('100')
 for sub in subs:
  compute=clients.setdefault(sub.lower(),ComputeManagementClient(credential,sub))
  try:
   for snap in compute.snapshots.list():
    created=(snap.time_created or now);created=created if created.tzinfo else created.replace(tzinfo=timezone.utc)
    created=created.astimezone(timezone.utc);age=max(0,(now-created).days);tags=snap.tags or {}
    src=getattr(snap.creation_data,'source_resource_id',None) or ''
    exists,reason=source_status(src,credential,clients)
    classification,rationale=classify(exists,bool(src),age,tags,args,include,protect)
    logical=int(snap.disk_size_gb or 0);bill=Decimal(logical)*util
    rate=rates.get((snap.location or '').lower(),rates.get('default'));monthly=bill*rate if rate is not None else None
    findings.append(Finding(sub,resource_group(snap.id),snap.name,snap.id,snap.location or '',src,'true' if exists is True else 'false' if exists is False else 'unknown',created.isoformat(),age,bool(getattr(snap,'incremental',False)),getattr(getattr(snap,'sku',None),'name','') or '',logical,f'{bill:.2f}','' if rate is None else f'{rate:.8f}','' if monthly is None else f'{monthly:.2f}','' if monthly is None else f'{monthly*12:.2f}',args.currency,classification,f'{rationale}; {reason}',json.dumps(tags,sort_keys=True),f'directional storage exposure estimate'))
  except Exception as exc: errors.append(str(exc))
 rows=[asdict(x) for x in findings]
 with Path(args.output).open('w',newline='',encoding='utf-8') as fh:
  w=csv.DictWriter(fh,fieldnames=list(Finding.__dataclass_fields__));w.writeheader();w.writerows(rows)
 cand={'TCO Opportunity','High TCO Opportunity'};c=[r for r in rows if r['classification'] in cand]
 def total(f):
  return f"{sum(Decimal(r[f]) for r in c if r[f] != ''):.2f}"
 summary={'generated_utc':datetime.now(timezone.utc).isoformat(),'currency':args.currency,'estimate_disclaimer':'Directional storage exposure estimate based on logical snapshot size and customer-selected utilization assumptions. Azure incremental snapshots are billed based on used storage, therefore actual Azure charges may be higher or lower.','inventory_count':len(rows),'candidate_count':len(c),'candidate_logical_size_gib':sum(r['logical_size_gib'] for r in c),'candidate_estimated_billable_gib':total('estimated_billable_gib'),'candidate_estimated_storage_exposure_monthly':total('estimated_storage_exposure_monthly'),'candidate_estimated_storage_exposure_annual':total('estimated_storage_exposure_annual'),'classification_counts':{n:sum(r['classification']==n for r in rows) for n in sorted({r['classification'] for r in rows})},'scan_errors':errors}
 Path(args.summary_output).write_text(json.dumps(summary,indent=2))
 return 0
if __name__=='__main__': sys.exit(main())
