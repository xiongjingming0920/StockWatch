import assert from 'node:assert/strict';
process.env.STOCKWATCH_SITE_TOKEN='test-access-code-is-not-a-secret-123456';
delete process.env.STOCKWATCH_LLM_API_KEY;
delete process.env.NETLIFY;
const {default:handler}=await import('./functions/api.mjs');
async function call(path, body, token='test-access-code-is-not-a-secret-123456'){
 const req=new Request('https://example.test/api/v1'+path,{method:body===undefined?'GET':'POST',headers:{'Content-Type':'application/json','X-Stockwatch-Token':token},body:body===undefined?undefined:JSON.stringify(body)});
 const resp=await handler(req);return {status:resp.status,value:await resp.json()};
}
assert.equal((await call('/health')).value.site_token_required,true);
assert.equal((await call('/dataset',undefined,'wrong')).status,401);
process.env.STOCKWATCH_SITE_TOKEN='short';
assert.equal((await call('/dataset',undefined,'short')).status,503);
process.env.STOCKWATCH_SITE_TOKEN='test-access-code-is-not-a-secret-123456';
let dataset=await call('/dataset');assert.equal(dataset.value.row_count,19400);
let b=await call('/batches',{as_of_date:'2024-07-01',k:5,method:'rule'});assert.equal(b.status,200);
let items=await call('/batches/'+b.value.batch_id+'/cases');assert.equal(items.value.items.length,5);
let id=items.value.items[0].id;
let detail=await call('/cases/'+id);assert.equal(detail.value.history.length,7);assert.ok(detail.value.history.every(r=>r.dt<='2024-07-01'));
let msg=await call('/cases/'+id+'/messages',{message:'最近7天缺货几天？'});assert.equal(msg.status,200);assert.ok(msg.value.answer.includes('缺货记录'));
let sales=await call('/cases/'+id+'/messages',{message:'这个商品的销量是多少？'});assert.ok(sales.value.answer.includes('不支持销量'));
let save=await call('/cases/'+id+'/reviews',{action:'REVIEWED'});assert.equal(save.value.status,'REVIEWED');assert.equal((await call('/cases/'+id)).value.case.status,'REVIEWED');
let ev=await call('/batches/'+b.value.batch_id+'/evaluation');assert.equal(ev.value.known_label_count,200);
assert.equal((await call('/batches',{as_of_date:'2024-05-10',k:5,method:'model'})).status,422);
assert.equal((await call('/batches',{as_of_date:'2024-07-01',k:5,method:'model'})).status,200);
// Mock only the model endpoint: tests exercise the real data and tool executor.
process.env.STOCKWATCH_LLM_API_KEY='test-only-fake';
const realFetch=globalThis.fetch; let seen=[], n=0;
globalThis.fetch=async (url,opts)=>{const payload=JSON.parse(opts.body);seen.push(payload);n++;if(n===1)return Response.json({choices:[{message:{role:'assistant',content:null,tool_calls:[{id:'call-1',type:'function',function:{name:'get_stockout_history',arguments:JSON.stringify({days:7})}}]}}]});return Response.json({choices:[{message:{role:'assistant',content:'根据历史记录，已查到缺货日期。'}}]})};
let chat=await call('/cases/'+id+'/messages',{message:'最近呢？',history:[{role:'user',content:'查缺货'},{role:'assistant',content:'你要查几天？'}]});
assert.equal(chat.status,200);assert.equal(chat.value.mode,'DeepSeek 对话 + 受控工具');assert.equal(chat.value.tool_calls[0].operator,'get_stockout_history');assert.ok(chat.value.evidence.get_stockout_history.records.every(r=>r.dt<='2024-07-01'));assert.ok(seen[0].messages.some(x=>x.content==='查缺货'));assert.equal(n,2);
assert.equal((await call('/cases/'+id+'/messages',{message:'测试',history:[{role:'system',content:'bad'}]})).status,422);
n=0;globalThis.fetch=async()=>{n++;return Response.json({choices:[{message:{role:'assistant',tool_calls:[{id:'x',type:'function',function:{name:'get_stockout_history',arguments:'{"days":91}'}}]}}]})};
chat=await call('/cases/'+id+'/messages',{message:'最近7天缺货？'});assert.equal(chat.value.mode,'确定性回退');assert.equal(n,1);
globalThis.fetch=realFetch;delete process.env.STOCKWATCH_LLM_API_KEY;
console.log('Netlify adapter local checks passed');
