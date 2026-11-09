import {timingSafeEqual, createHash} from 'node:crypto';
import {getUser, verifyRequestOrigin} from '@netlify/identity';

// Identity must be explicitly enabled; default retains the existing site-token gate.
export function authMode(env=process.env){return env.STOCKWATCH_AUTH_MODE || 'site_token'}
// Closed beta is the safe default until an explicit, separately configured launch.
export function accessMode(env=process.env){return env.STOCKWATCH_ACCESS_MODE || 'admin_only'}
export async function authorize(request, {env=process.env, identityUser=getUser, originCheck=verifyRequestOrigin}={}){
 const mode=authMode(env);
 if(mode==='site_token'){
  const expected=env.STOCKWATCH_SITE_TOKEN, actual=request.headers.get('x-stockwatch-token')||'';
  if(!expected||expected.trim().length<32)return {status:503,detail:'线上访问口令尚未配置或长度不足，API 暂不可用。'};
  const a=Buffer.from(expected),b=Buffer.from(actual);
  if(!actual||a.length!==b.length||!timingSafeEqual(a,b))return {status:401,detail:'请先输入访问口令。'};
  return {status:200,mode,scope:null,user:null};
 }
 if(mode!=='identity')return {status:503,detail:'身份认证配置无效。'};
 // Cookie-authenticated state-changing requests require same-origin protection.
 if(!['GET','HEAD','OPTIONS'].includes(request.method)){
  try{originCheck(request)}catch{return {status:403,detail:'请求来源不受信任。'}}
 }
 let user;
 try{user=await identityUser()}catch{return {status:503,detail:'身份服务暂不可用。'}}
 if(!user||typeof user.id!=='string'||!user.id)return {status:401,detail:'请先登录账号。'};
 const access=accessMode(env);
 if(!['admin_only','registered'].includes(access))return {status:503,detail:'账号访问策略配置无效。'};
 if(access==='admin_only'&&(!Array.isArray(user.roles)||!user.roles.includes('super_admin')))return {status:403,detail:'当前为内部测试，仅超级管理员可使用。'};
 const scope=createHash('sha256').update(user.id).digest('hex');
 return {status:200,mode,scope,user:{id:user.id,email:typeof user.email==='string'?user.email:'',roles:Array.isArray(user.roles)?user.roles:[]}};
}
