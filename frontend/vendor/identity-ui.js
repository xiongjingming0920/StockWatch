import {login, signup, logout as identityLogout, getUser, handleAuthCallback, acceptInvite, requestPasswordRecovery, updateUser} from './identity-client.js';
const $=s=>document.querySelector(s);
let registrationOpen=false;
function panel(message=''){ $('#authPanel').hidden=false; $('#authMessage').textContent=message; }
function reload(){window.location.reload()}
function showLogin(){
  $('#authTitle').textContent='登录 StockWatch';$('#authIntro').textContent='请使用邮箱和密码登录。';
  $('#authRegister').hidden=true;$('#authSetPassword').hidden=true;$('#authLogin').hidden=false;$('#authMessage').textContent='';
  $('#authShowLogin').setAttribute('aria-pressed','true');$('#authShowRegister').setAttribute('aria-pressed','false');
}
function showRegister(){
  $('#authTitle').textContent='注册 StockWatch';$('#authIntro').textContent=registrationOpen?'使用邮箱注册，验证邮箱后再登录。':'目前为超级管理员测试阶段，暂不开放用户注册。';
  $('#authLogin').hidden=true;$('#authSetPassword').hidden=true;$('#authRegister').hidden=false;$('#authMessage').textContent='';
  $('#authSignup').hidden=!registrationOpen;$('#authRegisterClosed').hidden=registrationOpen;
  $('#authShowLogin').setAttribute('aria-pressed','false');$('#authShowRegister').setAttribute('aria-pressed','true');
}
function wireTabs(){
  $('#authShowLogin').addEventListener('click',showLogin);
  $('#authShowRegister').addEventListener('click',showRegister);
}
function wireLogin(){
  $('#authLogin').addEventListener('submit',async e=>{e.preventDefault();const email=$('#authEmail').value.trim(),field=$('#authPassword'),password=field.value;field.value='';try{await login(email,password);reload()}catch{$('#authMessage').textContent='登录失败，请检查邮箱、密码和邀请状态。'}});
  $('#authForgot').addEventListener('click',async()=>{const email=$('#authEmail').value.trim();if(!email){$('#authMessage').textContent='请先填写邮箱，再点击忘记密码。';return}try{await requestPasswordRecovery(email)}catch{}$('#authMessage').textContent='如果该邮箱属于已开通账号，系统将发送重置链接。请检查邮箱。'});
}
function wireSignup(){
  $('#authSignup').addEventListener('submit',async e=>{e.preventDefault();if(!registrationOpen)return;
    const email=$('#authSignupEmail').value.trim(),password=$('#authSignupPassword').value,confirm=$('#authSignupConfirm').value;
    $('#authSignupPassword').value='';$('#authSignupConfirm').value='';
    if(password!==confirm){$('#authMessage').textContent='两次输入的密码不一致，请重新输入。';return}
    try{await signup(email,password);$('#authMessage').textContent='注册请求已提交。如邮箱可用，请查收验证邮件，完成验证后登录。'}
    catch{$('#authMessage').textContent='暂时无法完成注册，请检查邮箱、密码或稍后重试。'}
  });
}
export async function requireLogin(options={}){
  registrationOpen=options.registration_open===true;
  wireTabs();
  wireSignup();
  let callback;
  try { callback=await handleAuthCallback(); } catch { panel('邀请链接或重置链接无效或已过期，请联系管理员重新发送。'); return null; }
  if(callback?.type==='invite'||callback?.type==='recovery'){
    panel(); $('#authTabs').hidden=true;$('#authRegister').hidden=true;$('#authLogin').hidden=true;$('#authSetPassword').hidden=false;
    $('#authTitle').textContent=callback.type==='invite'?'完成受邀注册':'重置登录密码';
    $('#authIntro').textContent=callback.type==='invite'?'受邀用户请设置密码以创建账号。':'请设置新的登录密码。';
    $('#authSetPassword').addEventListener('submit',async e=>{e.preventDefault();const field=$('#authNewPassword'),value=field.value;field.value='';try{
      if(callback.type==='invite'){
        const user=await acceptInvite(callback.token,value);callback=null;
        $('#authTabs').hidden=false;showLogin();
        $('#authIntro').textContent='账户已激活，请使用受邀邮箱和刚设置的密码登录。';
        if(typeof user?.email==='string')$('#authEmail').value=user.email;
        $('#authMessage').textContent='密码已设置，请登录。';wireLogin();
      }else{await updateUser({password:value});reload()}
    }catch{$('#authMessage').textContent='设置密码失败，请检查链接是否有效或稍后重试。'}});
    return null;
  }
  try { await getUser(); } catch {} // Restore SDK refresh scheduling; server remains authoritative.
  let r; try {r=await fetch('/api/v1/session',{cache:'no-store',credentials:'same-origin'})} catch{panel('无法连接登录服务，请稍后重试。');return null}
  if(r.ok){const data=await r.json(),user=data.user;if(!user||typeof user.id!=='string'||!user.id)throw Error('invalid session');return user}
  if(r.status===403){panel('当前为超级管理员测试阶段，此账号暂不能使用。');$('#authLogin').hidden=true;$('#authTabs').hidden=true;$('#authSwitchAccount').hidden=false;$('#authSwitchAccount').addEventListener('click',async()=>{try{await identityLogout()}finally{reload()}});return null}
  if(r.status!==401){panel('登录服务暂不可用，请稍后刷新重试。');$('#authLogin').hidden=true;return null}
  panel();
  $('#authTabs').hidden=false;showLogin();
  wireLogin();
  return null;
}
export async function logout(){try{await identityLogout()}finally{reload()}}
