const $=s=>document.querySelector(s);
function panel(message=''){ $('#authPanel').hidden=false;$('#authMessage').textContent=message; }
function reload(){window.location.reload()}
async function request(path,body){
  const response=await fetch('/api/v1/auth/'+path,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  let data={};try{data=await response.json()}catch{}
  if(!response.ok)throw Error(typeof data.detail==='string'?data.detail:'请求失败，请稍后重试。');
  return data;
}
function showLogin(){
  $('#authTitle').textContent='登录 StockWatch';$('#authIntro').textContent='本机账号无需邮箱验证。测试期间仅超级管理员可以使用 Agent。';
  $('#authRegister').hidden=true;$('#authSetPassword').hidden=true;$('#authLogin').hidden=false;$('#authMessage').textContent='';
  $('#authShowLogin').setAttribute('aria-pressed','true');$('#authShowRegister').setAttribute('aria-pressed','false');
}
function showRegister(open){
  $('#authTitle').textContent='注册 StockWatch';$('#authIntro').textContent=open?'创建本机账号，无需邮箱验证。第一个注册的账号将成为本机超级管理员。':'本机注册暂未开放。';
  $('#authLogin').hidden=true;$('#authSetPassword').hidden=true;$('#authRegister').hidden=false;$('#authMessage').textContent='';
  $('#authSignup').hidden=!open;$('#authRegisterClosed').hidden=open;
  $('#authShowLogin').setAttribute('aria-pressed','false');$('#authShowRegister').setAttribute('aria-pressed','true');
}
export async function requireLogin(options={}){
  const open=options.registration_open===true;
  $('#authForgot').hidden=true;
  $('#authSignupNote').textContent='账号只保存在本机，无需验证邮箱。测试期间只有超级管理员可以使用 Agent。';
  $('#authShowLogin').addEventListener('click',showLogin);
  $('#authShowRegister').addEventListener('click',()=>showRegister(open));
  $('#authLogin').addEventListener('submit',async e=>{
    e.preventDefault();const email=$('#authEmail').value.trim(),field=$('#authPassword'),password=field.value;field.value='';
    try{await request('login',{email,password});reload()}catch(err){$('#authMessage').textContent=err.message||'无法连接登录服务，请稍后重试。'}
  });
  $('#authSignup').addEventListener('submit',async e=>{
    e.preventDefault();if(!open)return;
    const email=$('#authSignupEmail').value.trim(),password=$('#authSignupPassword').value,confirm=$('#authSignupConfirm').value;
    $('#authSignupPassword').value='';$('#authSignupConfirm').value='';
    if(password!==confirm){$('#authMessage').textContent='两次输入的密码不一致，请重新输入。';return}
    try{const result=await request('register',{email,password});showLogin();$('#authEmail').value=email;
      $('#authMessage').textContent=result.user?.roles?.includes('super_admin')?'注册成功，此账号是本机超级管理员，请登录。':'注册成功，请登录。测试期间普通账号暂不能使用 Agent。';
    }catch(err){$('#authMessage').textContent=err.message||'无法连接注册服务，请稍后重试。'}
  });
  let response;try{response=await fetch('/api/v1/session',{cache:'no-store',credentials:'same-origin'})}catch{panel('无法连接本机登录服务，请确认服务已启动后刷新。');$('#authLogin').hidden=true;return null}
  if(response.ok){
    const data=await response.json(),user=data.user;
    if(!user||typeof user.id!=='string'||!user.id)throw Error('invalid session');
    if(!Array.isArray(user.roles)||!user.roles.includes('super_admin')){
      panel('当前为超级管理员测试阶段，此账号暂不能使用 Agent。');$('#authIntro').textContent='请切换到本机超级管理员账号。';$('#authLogin').hidden=true;$('#authTabs').hidden=true;$('#authSwitchAccount').hidden=false;
      $('#authSwitchAccount').addEventListener('click',logout);return null;
    }
    return user;
  }
  if(response.status!==401){panel('登录服务暂不可用，请稍后刷新重试。');$('#authLogin').hidden=true;return null}
  panel();$('#authTabs').hidden=false;showLogin();return null;
}
export async function logout(){try{await request('logout',{})}finally{reload()}}
