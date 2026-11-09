import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import vm from 'node:vm';
const html=await readFile(new URL('../index.html',import.meta.url),'utf8');
class Element{constructor(){this.children=[];this.textContent=''}append(...items){this.children.push(...items)}}
const outcomeSource=html.slice(html.indexOf('function appendRunOutcome('),html.indexOf('// The run view intentionally'));
const context={localRunMode:true,document:{createElement:()=>new Element()}};vm.runInNewContext(outcomeSource,context);
for(const [status,expected] of [['failed','任务状态：运行失败'],['degraded','任务状态：降级完成'],['succeeded',null],[undefined,null],['<script>',null]]){
 const chat=new Element();context.appendRunOutcome(chat,{run_status:status});assert.equal(chat.children[0]?.textContent||null,expected);
}
context.localRunMode=false;const remoteChat=new Element();context.appendRunOutcome(remoteChat,{run_status:'failed'});assert.equal(remoteChat.children.length,0);
assert.match(html,/item\.content\);appendRunOutcome\(chat,item\);appendRunView\(chat,item\)/);
const start=html.indexOf("$('#chatForm').addEventListener('submit'");const end=html.indexOf('\nrenderConversation();',start);
const submit=html.slice(start,end);assert.ok(start>=0&&end>start);
async function send(mode,status){
 const session={id:'s',caseId:'c',datasetSha:'v',title:'新对话',messages:[]};let handler;
 const question={value:'分析'};
 const globals={current:{id:'c',dataset_sha:'v'},activeSessionId:'s',sessionById:()=>session,
  $:selector=>selector==='#chatForm'?{addEventListener:(_,fn)=>{handler=fn}}:question,
  inFlight:new Map(),localRunMode:mode,renderConversation(){},toast(){},persistSessions(){},
  req:async()=>({answer:'回复',run_status:status})};
 vm.runInNewContext(submit,globals);await handler({preventDefault(){}});return session.messages[1];
}
assert.equal((await send(true,'failed')).run_status,'failed');
assert.equal((await send(true,'degraded')).run_status,'degraded');
assert.equal((await send(true,'succeeded')).run_status,'succeeded');
assert.equal((await send(true,'untrusted')).run_status,undefined);
assert.equal((await send(false,'failed')).run_status,undefined);
console.log('Local run outcome checks passed');
