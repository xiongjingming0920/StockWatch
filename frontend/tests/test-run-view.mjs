import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
const source=html.slice(html.indexOf('function validRunId('),html.indexOf('function renderConversation()'));
assert.ok(source.includes('addEventListener'));
class Element {
 constructor(tag){this.tag=tag;this.children=[];this.textContent='';this.handlers={};this.open=false}
 append(...nodes){this.children.push(...nodes)}
 insertBefore(node,ref){this.children.splice(this.children.indexOf(ref),0,node)}
 replaceChildren(){this.children=[];this.textContent=''}
 setAttribute(){}
 addEventListener(event,handler){this.handlers[event]=handler}
}
const calls=[];let response={events:[]},fail=false;
const ctx={document:{createElement:tag=>new Element(tag)},localRunMode:true,API:'/api/v1',fetch:async(url,options)=>{calls.push({url,options});if(fail)throw Error('sensitive');return {ok:true,json:async()=>response}}};
vm.runInNewContext(source,ctx);
const id='1aa8c949-532d-4e25-8222-241f20b89e12';
let chat=new Element('chat');ctx.localRunMode=false;ctx.appendRunView(chat,{run_id:'id'});assert.equal(chat.children.length,0);
ctx.localRunMode=true;ctx.appendRunView(chat,{});assert.match(chat.children[0].children[1].textContent,/没有可查看/);assert.equal(calls.length,0);
chat=new Element('chat');ctx.appendRunView(chat,{run_id:'invalid<script>'});assert.match(chat.children[0].children[1].textContent,/无效/);assert.equal(calls.length,0);
chat=new Element('chat');ctx.appendRunView(chat,{run_id:id});let details=chat.children[0];assert.equal(details.children[0].textContent,'查看运行过程');
response={run:{id,status:'succeeded'},events:[{event_type:'model_call',status:'success',duration_ms:34},{event_type:'tool_call',status:'error',tool_name:'get_stockout_history',duration_ms:4},{event_type:'<script>evil</script>',status:'<b>evil</b>',tool_name:'x',duration_ms:-1}]};
details.open=true;await details.handlers.toggle();
assert.equal(calls[0].url,'/api/v1/runs/'+id);assert.equal(details.children[1].textContent,'任务编号：'+id);
let lines=details.children[2].children.map(x=>x.textContent);
assert.deepEqual(lines,['任务状态：成功','调用模型 · 成功 · 34 毫秒','调用工具 · 查询缺货历史 · 失败 · 4 毫秒','处理步骤']);
await details.handlers.toggle();assert.equal(calls.length,1,'successful result is cached');
chat=new Element('chat');ctx.appendRunView(chat,{run_id:id});details=chat.children[0];details.open=true;fail=true;await details.handlers.toggle();
assert.match(details.children[2].textContent,/无法获取/);fail=false;response={run:{id,status:'<script>hidden</script>'},events:[]};await details.handlers.toggle();assert.equal(details.children[2].children[0].textContent,'任务状态：未知');assert.match(details.children[2].children[1].textContent,/暂无/);
assert.match(html,/run_id:localRunMode&&typeof d\.run_id==='string'\?d\.run_id:undefined/);
assert.match(html,/localRunMode=data\.auth_mode==='local'/);
const reqSource=html.slice(html.indexOf('async function req('),html.indexOf('function statusText('));
const requestContext={API:'/api/v1',localRunMode:true,identityMode:false,tokenRequired:false,fetch:async()=>({ok:false,status:500,json:async()=>({detail:'任务失败',run_id:id})}),validRunId:ctx.validRunId};
vm.runInNewContext(reqSource,requestContext);
await assert.rejects(requestContext.req('/cases/a/messages'),error=>error.run_id===id&&error.message==='任务失败');
requestContext.localRunMode=false;
await assert.rejects(requestContext.req('/cases/a/messages'),error=>!Object.hasOwn(error,'run_id'));
requestContext.localRunMode=true;requestContext.fetch=async()=>({ok:false,status:500,json:async()=>({detail:'错误',run_id:'<script>'})});
await assert.rejects(requestContext.req('/cases/a/messages'),error=>!Object.hasOwn(error,'run_id'));
assert.match(html,/if\(item\.run_id\)appendRunView\(chat,item\)/);
assert.match(html,/localRunMode&&validRunId\(err\.run_id\)\?\{run_id:err\.run_id\}/);

const submitStart=html.indexOf("$('#chatForm').addEventListener('submit'");
const submitEnd=html.indexOf('\nrenderConversation();',submitStart);
const submitSource=html.slice(submitStart,submitEnd);assert.ok(submitStart>=0&&submitEnd>submitStart);
async function failedSubmit(local){
 const session={id:'s',caseId:'c',datasetSha:'v',title:'新对话',messages:[]};let handler,writes=0;
 const question={value:'为什么缺货？'};
 const submitContext={current:{id:'c',dataset_sha:'v'},activeSessionId:'s',sessionById:()=>session,
  $:selector=>selector==='#chatForm'?{addEventListener:(_,fn)=>{handler=fn}}:question,
  inFlight:new Map(),localRunMode:local,validRunId:ctx.validRunId,renderConversation(){},toast(){},persistSessions(){writes++},
  req:async()=>{const error=Error('任务失败');error.run_id=id;throw error}};
 vm.runInNewContext(submitSource,submitContext);await handler({preventDefault(){}});
 assert.equal(writes,1);return session.messages[0];
}
assert.equal((await failedSubmit(true)).run_id,id);
assert.equal(Object.hasOwn(await failedSubmit(false),'run_id'),false);
console.log('Local run view checks passed');
