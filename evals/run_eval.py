"""Offline gold evaluation against the actual FastAPI and service implementations."""
from __future__ import annotations
import csv, hashlib, json, os, sys, tempfile
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'backend'))
for key in ('STOCKWATCH_LLM_API_KEY', 'STOCKWATCH_LLM_BASE_URL', 'STOCKWATCH_LLM_MODEL'):
    os.environ[key] = ''  # force offline; never transmit data or print configuration
from fastapi.testclient import TestClient
from app.main import app
from app import services, data_contract

def main():
    spec=json.loads((ROOT/'evals/cases.json').read_text(encoding='utf8'))
    data=ROOT/'backend/data/freshretail_sample.csv'
    digest=hashlib.sha256(data.read_bytes()).hexdigest()
    if digest != spec['dataset_sha256']:
        print(json.dumps({'status':'blocked','reason':'dataset_sha256_mismatch','expected':spec['dataset_sha256'],'observed':digest},ensure_ascii=False,indent=2))
        return 2
    contract = data_contract.validate(data, require_reference=True)
    contract_summary = {'contract_id': contract['contract_id'], 'version': contract['contract_version'],
                        'status': contract['status'], 'errors': contract['errors'], 'warnings': contract['warnings']}
    if contract['status'] == 'fail':
        print(json.dumps({'status':'blocked','reason':'data_contract_failed','contract':contract_summary},ensure_ascii=False,indent=2))
        return 2
    results=[]
    with tempfile.TemporaryDirectory(prefix='stockwatch-eval-') as tmp:
        os.environ['FRESHRETAIL_PATH']=str(data)
        os.environ['STOCKWATCH_DB']=str(Path(tmp)/'eval.sqlite3')
        os.environ['STOCKWATCH_AUTH_DB']=str(Path(tmp)/'auth.sqlite3')
        os.environ['STOCKWATCH_RUN_DB']=str(Path(tmp)/'runs.sqlite3')
        client=TestClient(app, base_url='http://127.0.0.1:8765', client=('127.0.0.1', 50000), headers={'origin':'http://127.0.0.1:8765'})
        credentials={'email':'eval@example.test','password':'temporary-eval-password'}
        client.post('/api/v1/auth/register', json=credentials).raise_for_status()
        client.post('/api/v1/auth/login', json=credentials).raise_for_status()
        for case in spec['cases']:
            observed=None; status='fail'; reason=None
            try:
                kind=case['kind']; expected=case['expected']
                if kind=='llm_followup':
                    results.append({'case_id':case['id'],'status':'unassessed','expected':expected,'observed':None}); continue
                batch=services.build_batch(case['as_of'],30,'rule')
                items=services.get_cases(batch['batch_id'])['items']
                item=next(x for x in items if x['store_id']==case['store'] and x['product_id']==case['product'])
                if kind=='history':
                    response=client.post('/api/v1/cases/'+item['id']+'/messages',json={'message':case['question'],'history':[]})
                    response.raise_for_status(); evidence=response.json()['evidence']
                    observed={k:evidence[k] for k in ('start_date','end_date','observed_days','stockout_days')}
                    observed.update(missing_count=len(evidence['missing_dates']),unknown_count=len(evidence['unknown_dates']))
                    status='pass' if observed==expected else 'fail'
                elif kind=='ranking':
                    observed={k:item[k] for k in expected}; status='pass' if observed==expected else 'fail'
                elif kind=='limits':
                    response=client.post('/api/v1/cases/'+item['id']+'/messages',json={'message':case['question'],'history':[]})
                    response.raise_for_status(); observed={'answer':response.json()['answer']}
                    status='pass' if all(x in observed['answer'] for x in expected['must_include']) else 'fail'
                elif kind=='future_mutation':
                    before=services.get_history(item['id'],14)
                    mutated=Path(tmp)/'future.csv'
                    with data.open(encoding='utf8',newline='') as source,mutated.open('w',encoding='utf8',newline='') as dest:
                        reader=csv.DictReader(source); writer=csv.DictWriter(dest,fieldnames=reader.fieldnames);writer.writeheader()
                        for row in reader:
                            if row['store_id']==case['store'] and row['product_id']==case['product'] and row['dt']>'2024-07-01': row['stock_hour6_22_cnt']='16'
                            writer.writerow(row)
                    os.environ['FRESHRETAIL_PATH']=str(mutated)
                    try:
                        other=services.build_batch(case['as_of'],30,'rule'); other_items=services.get_cases(other['batch_id'])['items']
                        other_item=next(x for x in other_items if x['store_id']==case['store'] and x['product_id']==case['product'])
                        after=services.get_history(other_item['id'],14)
                        fields=('rank','score','stockout_days_7d','stockout_hours_7d')
                        observed={'results_unchanged':before==after and all(item[k]==other_item[k] for k in fields)}
                        status='pass' if observed==expected else 'fail'
                    finally: os.environ['FRESHRETAIL_PATH']=str(data)
                elif kind in ('synthetic_missing_history','synthetic_unknown_label'):
                    mutated=Path(tmp)/(kind+'.csv')
                    with data.open(encoding='utf8',newline='') as source,mutated.open('w',encoding='utf8',newline='') as dest:
                        reader=csv.DictReader(source);writer=csv.DictWriter(dest,fieldnames=reader.fieldnames);writer.writeheader()
                        for row in reader:
                            target_date='2024-06-30' if kind=='synthetic_missing_history' else '2024-07-02'
                            if row['store_id']==case['store'] and row['product_id']==case['product'] and row['dt']==target_date: row['stock_hour6_22_cnt']=''
                            writer.writerow(row)
                    os.environ['FRESHRETAIL_PATH']=str(mutated)
                    try:
                        other=services.build_batch(case['as_of'],1000 if kind=='synthetic_missing_history' else 30,'rule')
                        if kind=='synthetic_missing_history':
                            candidates=services.get_cases(other['batch_id'])['items']
                            observed={'candidate_present':any(x['store_id']==case['store'] and x['product_id']==case['product'] for x in candidates)}
                        else:
                            evaluation=services.evaluate_batch(other['batch_id']);observed={k:evaluation[k] for k in expected}
                        status='pass' if observed==expected else 'fail'
                    finally: os.environ['FRESHRETAIL_PATH']=str(data)
                else: raise ValueError('unknown case kind')
            except Exception as exc:
                reason=type(exc).__name__+': '+str(exc)
            results.append({'case_id':case['id'],'status':status,'expected':case['expected'],'observed':observed,**({'error':reason} if reason else {})})
    counts={s:sum(x['status']==s for x in results) for s in ('pass','fail','unassessed')}
    print(json.dumps({'suite':spec['version'],'dataset_sha256':digest,'contract':contract_summary,'mode':'offline_deterministic_only','counts':counts,'cases':results},ensure_ascii=False,indent=2))
    return 1 if counts['fail'] else 0

if __name__=='__main__': raise SystemExit(main())
