// Offline parity check: compares independent implementations, no network/API key.
import assert from 'node:assert/strict';
import {spawnSync} from 'node:child_process';
import {mkdtempSync,unlinkSync,rmdirSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
process.env.STOCKWATCH_SITE_TOKEN='test-access-code-is-not-a-secret-123456';
delete process.env.STOCKWATCH_LLM_API_KEY;
delete process.env.NETLIFY;
delete process.env.SITE_ID;
const {default: handler}=await import('./functions/api.mjs');
async function call(path,body){let r=await handler(new Request('https://local.test/api/v1'+path,{method:body?'POST':'GET',headers:{'content-type':'application/json','x-stockwatch-token':process.env.STOCKWATCH_SITE_TOKEN},body:body?JSON.stringify(body):undefined}));if(!r.ok)throw Error(`Node ${path} ${r.status}`);return r.json()}
const dir=mkdtempSync(join(tmpdir(),'stockwatch-parity-'));
const py=`import json,os,sys\nos.environ['STOCKWATCH_DB']=sys.argv[1]\nfrom app import services\nout={}\nfor m in ['rule','model']:\n b=services.build_batch('2024-07-01',30,m)\n out[m]={'cases':services.get_cases(b['batch_id'])['items'],'eval':services.evaluate_batch(b['batch_id']),'dataset':services.dataset_info()}\nprint(json.dumps(out))`;
try{
 const result=spawnSync('py',['-3.13','-c',py,join(dir,'state.sqlite')],{cwd:join(process.cwd(),'backend'),encoding:'utf8'});
 if(result.status!==0)throw Error('Python parity process failed: '+result.stderr);
 const expected=JSON.parse(result.stdout), dataset=await call('/dataset');assert.equal(dataset.dataset_sha,expected.rule.dataset.dataset_sha);
 const model=await call('/model');assert.equal(model.dataset_sha,dataset.dataset_sha);
 for(const method of ['rule','model']){
  let batch=await call('/batches',{as_of_date:'2024-07-01',k:30,method});let cases=(await call('/batches/'+batch.batch_id+'/cases')).items;
  let evals=await call('/batches/'+batch.batch_id+'/evaluation'), ref=expected[method];
  assert.equal(cases.length,ref.cases.length);
  for(let i=0;i<cases.length;i++){
   assert.equal(cases[i].store_id,ref.cases[i].store_id,`${method} rank ${i+1} store`);
   assert.equal(cases[i].product_id,ref.cases[i].product_id,`${method} rank ${i+1} product`);
   assert.ok(Math.abs(cases[i].score-ref.cases[i].score)<1e-12,`${method} rank ${i+1} score`);
  }
  for(const field of ['hits','positive_count','selected_count','known_label_count','precision_at_k_known','recall_at_k_known']) assert.equal(evals[field],ref.eval[field],`${method} ${field}`);
 }
 console.log('Node/Python parity verified for rule and model; hashes agree');
}finally{try{unlinkSync(join(dir,'state.sqlite'))}catch{}rmdirSync(dir)}
