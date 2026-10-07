/* k.apt cloud workspace v1. Stable keys across UI versions; official Supabase SDK. */
(() => {
 'use strict';
 const $=s=>document.querySelector(s), clone=v=>structuredClone(v), json=v=>JSON.stringify(v), OWNER='kAptCloudOwnerV1',CONFIG='kAptSupabaseConfigV1';
 const local=window.KaptLocal, BUCKET='kapt-private-images',TABLE='kapt_workspaces';
 let db,client,config,user=null,owner='guest',base=null,revision=0,ready=false,suppress=false,dirty=false,bootstrapped=false,importOnEmpty=false,switching=false,syncPromise=null,changeTimer,pollTimer,epoch=0,recovery=false;
 const digests=new WeakMap();
 const message=(text,badge)=>{$('#cloudMessage').textContent=text;if(badge)$('#cloudBadge').textContent=badge;};
 function controls(){const logged=!!user;$('#cloudSignedIn').hidden=!logged;$('#cloudSignedOut').hidden=logged;$('#cloudAccountBtn').textContent=logged?'계정':'로그인';$('#cloudEmailLabel').textContent=user?.email||'';$('#cloudRecovery').hidden=!recovery;}
 function errorText(e){const t=e?.message||String(e);if(/invalid login|credentials/i.test(t))return '이메일 또는 비밀번호를 확인해 주세요.';if(/email.*confirm/i.test(t))return '이메일 인증을 완료한 뒤 로그인해 주세요.';if(/fetch|network|timeout|abort/i.test(t))return '연결하지 못했습니다. 이 기기에 보관한 변경은 연결 후 다시 동기화합니다.';if(/42P01|PGRST202|does not exist|schema cache/i.test(t))return '프로젝트에서 supabase/setup.sql을 실행한 뒤 다시 동기화해 주세요.';return t.slice(0,260);}
 function getConfig(){let v=window.KAPT_SUPABASE_CONFIG||{};if(!v.url||!v.publishableKey)try{v=JSON.parse(localStorage.getItem(CONFIG)||'{}')}catch{}return v;}
 function validateConfig(v){const u=new URL(v.url);if(u.protocol!=='https:'||u.username||u.password||u.search||u.hash)throw Error('Project URL은 https://로 시작하는 프로젝트 주소를 입력해 주세요.');const key=v.publishableKey.trim();if(key.startsWith('sb_secret_'))throw Error('Secret key는 사용할 수 없습니다. 공개 Publishable key를 입력해 주세요.');if(!key.startsWith('sb_publishable_')){let payload;try{payload=JSON.parse(atob(key.split('.')[1].replace(/-/g,'+').replace(/_/g,'/')))}catch{}if(payload?.role!=='anon')throw Error('Publishable key 또는 anon key를 입력해 주세요. service_role 키는 사용할 수 없습니다.');}return {url:u.origin,publishableKey:key};}
 async function openDb(){db=await new Promise((resolve,reject)=>{const r=indexedDB.open('kAptCloudLocalV1',1);r.onupgradeneeded=()=>r.result.createObjectStore('workspaces',{keyPath:'id'});r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
 function cached(id){return new Promise((resolve,reject)=>{const tx=db.transaction('workspaces','readonly'),r=tx.objectStore('workspaces').get(id);r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});}
 function cache(id,snapshot,b=base,r=revision,pending=dirty){return new Promise((resolve,reject)=>{const tx=db.transaction('workspaces','readwrite');tx.objectStore('workspaces').put({id,snapshot:clone(snapshot),base:clone(b),revision:r,pending,updatedAt:Date.now()});tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});}
 async function remember(){await cache(owner,local.capture());}
 function strip(snapshot){return {...snapshot,maps:snapshot.maps.map(({blob,...m})=>m)};}
 function merge(baseValue,localValue,remoteValue){
  if(json(baseValue)===json(localValue))return clone(remoteValue);
  if(json(baseValue)===json(remoteValue))return clone(localValue);
  if(Array.isArray(localValue)&&Array.isArray(remoteValue)&&[...localValue,...remoteValue].every(x=>x&&typeof x==='object'&&x.id)){
   const b=new Map((baseValue||[]).map(x=>[x.id,x])),l=new Map(localValue.map(x=>[x.id,x])),r=new Map(remoteValue.map(x=>[x.id,x]));
   const out=[];for(const id of new Set([...r.keys(),...l.keys(),...b.keys()])){const v=merge(b.get(id),l.get(id),r.get(id));if(v!==undefined)out.push(v);}return out.sort((a,b)=>(a.savedAt||a.createdAt||0)-(b.savedAt||b.createdAt||0)).slice(localValue.some(x=>x.preset)?-10:0);
  }
  if(localValue&&remoteValue&&typeof localValue==='object'&&typeof remoteValue==='object'&&!Array.isArray(localValue)&&!Array.isArray(remoteValue)){
   const out={};for(const k of new Set([...Object.keys(baseValue||{}),...Object.keys(remoteValue),...Object.keys(localValue)])){const v=merge(baseValue?.[k],localValue[k],remoteValue[k]);if(v!==undefined)out[k]=v;}return out;
  }
  return clone(localValue); // A simultaneous edit to the same item keeps this device's explicit edit.
 }
 function checkPayload(p){if(!p||p.schema!==1||typeof p.storage!=='object'||!Array.isArray(p.maps))throw Error('계정 자료 형식을 확인하지 못했습니다. 기존 자료는 덮어쓰지 않았습니다.');return p;}
 async function sha(blob){if(!digests.has(blob))digests.set(blob,crypto.subtle.digest('SHA-256',await blob.arrayBuffer()).then(a=>[...new Uint8Array(a)].map(b=>b.toString(16).padStart(2,'0')).join('')));return digests.get(blob);}
 function guard(ticket){if(ticket!==epoch||!user)throw Error('계정이 변경되어 이전 작업을 중단했습니다.');}
 async function upload(snapshot,ticket){const result=strip(snapshot);for(let i=0;i<snapshot.maps.length;i++){const row=snapshot.maps[i],out=result.maps[i];if(row.deleted){delete out.cloudPath;continue;}if(row.blob){const hash=await sha(row.blob),path=user.id+'/'+encodeURIComponent(row.id)+'/'+hash;guard(ticket);if(row.cloudPath!==path){const {error}=await client.storage.from(BUCKET).upload(path,row.blob,{contentType:row.blob.type,upsert:true});if(error)throw error;}guard(ticket);out.cloudPath=path;out.mime=row.blob.type;out.bytes=row.blob.size;}else if(out.cloudPath&&!out.cloudPath.startsWith(user.id+'/'))throw Error('다른 계정의 이미지는 가져올 수 없습니다.');}return result;}
 async function hydrate(payload,snapshot,ticket){checkPayload(payload);const maps=[];for(const row of payload.maps){guard(ticket);const found=snapshot?.maps?.find(x=>x.id===row.id&&x.cloudPath===row.cloudPath&&x.blob);if(row.cloudPath&&!row.deleted){if(!row.cloudPath.startsWith(user.id+'/'))throw Error('이미지 계정 경로가 일치하지 않습니다.');let blob=found?.blob;if(!blob){const {data,error}=await client.storage.from(BUCKET).download(row.cloudPath);if(error)throw error;blob=data;}maps.push({...row,blob});}else maps.push({...row});}return {...clone(payload),maps};}
 async function pull(ticket){guard(ticket);const {data,error}=await client.from(TABLE).select('revision,payload').eq('user_id',user.id).maybeSingle();if(error)throw error;guard(ticket);if(data)checkPayload(data.payload);return data;}
 async function apply(snapshot){suppress=true;try{await local.apply(snapshot)}finally{suppress=false;}}
 async function sync(){if(!user||switching||!ready)return;if(syncPromise)return syncPromise;syncPromise=syncWork().finally(()=>{syncPromise=null});return syncPromise;}
 async function syncWork(){const ticket=epoch,uid=user.id;try{
  // Take a new local snapshot, even when an offline edit was made just before closing.
  const start=local.capture();await cache(owner,start);let row=await pull(ticket);guard(ticket);
  if(!bootstrapped){
   if(row){base=base||clone(row.payload);revision=row.revision;}
   else if(importOnEmpty){const guest=await cached('guest');if(guest?.snapshot){const imported=clone(guest.snapshot);await apply(imported);dirty=true;message('기존 브라우저 자료를 계정에 가져오는 중입니다.','동기화 중');}}
   bootstrapped=true;
  }
  const current=local.capture();let payload=await upload(current,ticket);guard(ticket);
  const localBase=base||{schema:1,storage:{},filter:null,maps:[]};let merged=row?merge(localBase,payload,row.payload):payload;
  let serverRevision=row?.revision||0;
  if(!row||json(merged)!==json(row.payload)){
   for(let attempt=0;attempt<4;attempt++){
    guard(ticket);const {data,error}=await client.rpc('kapt_write_workspace',{p_expected_revision:serverRevision,p_payload:merged});if(error)throw error;guard(ticket);
    if(data?.conflict){checkPayload(data.payload);merged=merge(row?.payload||localBase,merged,data.payload);row={payload:data.payload,revision:data.revision};serverRevision=data.revision;continue;}
    if(!data||!data.payload||!Number.isInteger(data.revision))throw Error('동기화 응답을 확인하지 못했습니다.');row=data;serverRevision=data.revision;break;
   }
   if(!row||json(row.payload)!==json(merged))throw Error('다른 기기에서도 수정 중입니다. 잠시 후 다시 동기화합니다.');
  }
  guard(ticket);
  const finalPayload=row.payload;
  const hydrated=await hydrate(finalPayload,current,ticket);guard(ticket);
  // Apply only if the user has not made a newer edit while requests were in flight.
  const now=local.capture();const unchanged=json(strip(now))===json(strip(current))&&now.maps.every((m,i)=>m.blob===current.maps[i]?.blob);
  base=clone(finalPayload);revision=serverRevision;
  if(unchanged&&!local.editing()){await apply(hydrated);dirty=false;}
  else{
   // Keep changes made during the upload, and rebase them onto the committed payload.
   const patched=merge(payload,strip(now),finalPayload);const withBlobs=patched.maps.map(m=>({...m,blob:now.maps.find(x=>x.id===m.id&&(!m.cloudPath||x.cloudPath===m.cloudPath))?.blob||hydrated.maps.find(x=>x.id===m.id)?.blob}));
   if(!local.editing()){await apply({...patched,maps:withBlobs});dirty=json(patched)!==json(finalPayload);}else{base=clone(localBase);dirty=true;}
  }
  await cache(uid,local.capture(),base,revision,dirty);message(dirty?'최신 변경을 이어서 동기화합니다.':'동기화 완료 · '+new Date().toLocaleTimeString('ko-KR'),dirty?'저장 중':'동기화 완료');if(dirty&&!local.editing())schedule(1200);
 }catch(e){if(ticket!==epoch)return;dirty=true;try{await remember()}catch{}message(errorText(e),'동기화 대기');} }
 function schedule(delay=900){clearTimeout(changeTimer);changeTimer=setTimeout(async()=>{if(!ready||suppress)return;dirty=!!user;try{await remember();if(user)await sync();}catch(e){message(errorText(e),'저장 실패');}},delay);}
 function changed(){if(!ready||suppress||switching)return;if(user){dirty=true;$('#cloudBadge').textContent='저장 중';}schedule();}
 async function handleSession(session){
  const next=session?.user||null;if((next?.id||'guest')===owner&&ready){user=next;controls();return;}
  if(switching){setTimeout(()=>handleSession(session),100);return;}
  switching=true;local.lock(true);clearTimeout(changeTimer);const ticket=++epoch;
  try{
   await local.ready();if(ready)await remember();user=next;owner=next?.id||'guest';base=null;revision=0;dirty=false;bootstrapped=false;
   const saved=await cached(owner);importOnEmpty=!saved;if(saved){base=saved.base;revision=saved.revision||0;dirty=!!saved.pending;await apply(saved.snapshot);}else await apply({schema:1,storage:{},filter:null,maps:[]});
   base=base||strip(local.capture());
   localStorage.setItem(OWNER,owner);ready=true;controls();message(user?'계정 자료를 확인하는 중입니다.':'로그아웃했습니다. 기존 브라우저 자료는 이 기기에 남아 있습니다.',user?'동기화 중':'이 기기에 저장');
  }catch(e){ready=false;message('계정 전환을 완료하지 못했습니다. '+errorText(e),'확인 필요');}
  finally{switching=false;}
  try{if(ticket===epoch&&user&&ready)await sync();}finally{local.lock(false);}
 }
 async function connect(){if(!config?.url||!config?.publishableKey){$('#cloudSetup').open=true;message('Supabase 연결 설정을 먼저 입력해 주세요.','이 기기에 저장');return;}
  if(!window.supabase?.createClient){message('로그인 모듈을 읽지 못했습니다. assets/vendor 폴더가 함께 있는지 확인해 주세요.');return;}
  client=window.supabase.createClient(config.url,config.publishableKey,{auth:{storageKey:'kAptSupabaseAuthV1-'+new URL(config.url).host,persistSession:true,autoRefreshToken:true,detectSessionInUrl:true},global:{fetch:(url,options)=>fetch(url,{...options,signal:options?.signal||AbortSignal.timeout(25000)})}});
  client.auth.onAuthStateChange((event,session)=>{if(event==='PASSWORD_RECOVERY'){recovery=true;$('#cloudAccountWrap').classList.add('show');}if(event==='SIGNED_OUT')recovery=false;setTimeout(()=>handleSession(session),0);});
  const {data,error}=await client.auth.getSession();if(error)throw error;await handleSession(data.session);clearInterval(pollTimer);pollTimer=setInterval(()=>{if(!document.hidden&&navigator.onLine)sync()},30000);
 }
 async function authAction(action){if(!client){message('Supabase 연결 설정을 먼저 입력해 주세요.');return;}const email=$('#cloudEmail').value.trim(),password=$('#cloudPassword').value;try{
  if(!email)throw Error('이메일을 입력해 주세요.');message('요청 중입니다.');let result;
  const redirect=location.protocol==='https:'||location.protocol==='http:'?location.origin+location.pathname:undefined;
  if(action==='login')result=await client.auth.signInWithPassword({email,password});
  else if(action==='signup'){if(password.length<6)throw Error('비밀번호는 6자 이상 입력해 주세요.');result=await client.auth.signUp({email,password,options:{emailRedirectTo:redirect}});}
  else result=await client.auth.resetPasswordForEmail(email,{redirectTo:redirect});
  if(result.error)throw result.error;$('#cloudPassword').value='';if(action==='signup'&&!result.data.session)message('가입 확인 메일을 보냈습니다. 메일에서 인증한 뒤 로그인해 주세요.');else if(action==='reset')message('등록된 이메일이라면 비밀번호 재설정 메일이 발송됩니다.');
 }catch(e){message(errorText(e));}}
 async function importGuest(){if(!user)return;try{await sync();const guest=await cached('guest');if(!guest?.snapshot){message('가져올 브라우저 자료가 없습니다.');return;}if(!bootstrapped)throw Error('계정 자료를 먼저 확인한 후 가져올 수 있습니다.');const current=local.capture(),incoming=guest.snapshot;
  const storage={...current.storage,...incoming.storage};storage.kAptComplexMemosV1={...(current.storage.kAptComplexMemosV1||{}),...(incoming.storage.kAptComplexMemosV1||{})};const existing=current.storage.koAptDashboardFilterSavesV21||[],added=incoming.storage.koAptDashboardFilterSavesV21||[];storage.koAptDashboardFilterSavesV21=[...new Map([...existing,...added].map(x=>[x.id,x])).values()].sort((a,b)=>a.savedAt-b.savedAt).slice(-10);
  const maps=[...new Map([...current.maps,...incoming.maps].map(m=>[m.id,m])).values()];await apply({...current,storage,maps});dirty=true;await remember();await sync();
 }catch(e){message(errorText(e));}}
 async function init(){
  $('#cloudAccountBtn').onclick=()=>{$('#cloudAccountWrap').classList.add('show');};$('#cloudLoginForm').onsubmit=e=>{e.preventDefault();authAction('login')};$('#cloudSignup').onclick=()=>authAction('signup');$('#cloudReset').onclick=()=>authAction('reset');$('#cloudSyncNow').onclick=()=>sync();$('#cloudImport').onclick=importGuest;
  $('#cloudLogout').onclick=async()=>{if(!client)return;try{await remember();const {error}=await client.auth.signOut({scope:'local'});if(error)throw error;await handleSession(null);}catch(e){message(errorText(e));}};
  $('#cloudUpdatePassword').onclick=async()=>{try{const password=$('#cloudNewPassword').value;if(password.length<6)throw Error('비밀번호는 6자 이상 입력해 주세요.');const {error}=await client.auth.updateUser({password});if(error)throw error;recovery=false;$('#cloudNewPassword').value='';controls();message('비밀번호를 변경했습니다.');}catch(e){message(errorText(e));}};
  $('#cloudConfigForm').onsubmit=async e=>{e.preventDefault();try{const next=validateConfig({url:$('#cloudProjectUrl').value.trim(),publishableKey:$('#cloudPublicKey').value.trim()});if(user)throw Error('프로젝트를 바꾸려면 먼저 로그아웃해 주세요.');localStorage.setItem(CONFIG,json(next));message('연결 설정을 저장했습니다. 다시 여는 중입니다.');location.reload();}catch(e){message(errorText(e));}};
  try{await local.ready();await openDb();const oldOwner=localStorage.getItem(OWNER)||'guest';const original=local.capture(),prior=await cached(oldOwner);await cache(oldOwner,original,prior?.base||null,prior?.revision||0,prior?.pending||false);owner=oldOwner;
   // Keep queued account metadata across reload; the active legacy workspace has newest offline edits.
   ready=true;config=getConfig();if(config.url&&config.publishableKey)config=validateConfig(config);$('#cloudProjectUrl').value=config.url||'';$('#cloudPublicKey').value=config.publishableKey||'';
   if(oldOwner!=='guest'){const guest=await cached('guest');await apply(guest?.snapshot||{schema:1,storage:{},filter:null,maps:[]});owner='guest';localStorage.setItem(OWNER,'guest');}
   await connect();
  }catch(e){message('연결 준비를 완료하지 못했습니다. '+errorText(e),'이 기기에 저장');}
  window.addEventListener('storage',e=>{if(e.key===OWNER&&e.newValue&&e.newValue!==owner){ready=false;++epoch;location.reload();}});
  window.addEventListener('online',()=>sync());window.addEventListener('focus',()=>sync());window.addEventListener('pagehide',()=>{if(ready&&!suppress)remember().catch(()=>{})});
 }
 window.KaptCloud={changed,sync,merge,validateConfig,get user(){return user},get owner(){return owner},get ready(){return ready},get client(){return client}};
 init();
})();
