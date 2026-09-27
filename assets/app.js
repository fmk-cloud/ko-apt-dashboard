'use strict';

const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];
const DATA_URL = './data/site-data.json';

let DATA = { meta: {}, complexes: [] };
let shownRows = [];
let currentArea = 59;
let currentPop = null;
let selectedRegions = new Set();

const state = {
  fromMonth: '2025-09',
  toMonth: null,
  hhMin: '300', hhMax: 'max',
  farMin: '100', farMax: 'max',
  yearMin: 'min', yearMax: 'max',
};

const seoulRows = [
  [['강남구','tier1'],['서초구','tier1'],['용산구','tier2'],['송파구','tier2']],
  [['성동구','tier3'],['마포구','tier4'],['광진구','tier4']],
  [['동작구','tier5'],['양천구','tier5'],['강동구','tier5'],['영등포구','tier6'],['중구','tier6']],
  [['종로구','tier7'],['서대문구','tier7'],['동대문구','tier7'],['성북구','tier8'],['강서구','tier8'],['관악구','tier8']],
  [['구로구','tier9'],['노원구','tier9'],['은평구','tier9'],['중랑구','tier9'],['강북구','tier9'],['금천구','tier9'],['도봉구','tier9']]
];
const gyeonggiRows = [
  [['과천시','tier2'],['분당시','tier4']],
  [['광명시','tier7'],['하남시','tier6'],['평촌동','tier8'],['수지구','tier7'],['광교','tier7']],
  [['동탄시','tier8'],['성남시','tier6'],['수정구','tier6'],['중원동','tier8'],['삼송동','tier8'],['지축','tier8']],
  [['일산시','tier9'],['의왕시','tier8'],['구리시','tier8']]
];
const labelMap = {'분당시':'분당구'};

const OPTIONS = {
  householdMin:[['min','이하'],['200','200'],['300','300'],['500','500'],['1000','1000'],['2000','2000']],
  householdMax:[['200','200'],['300','300'],['500','500'],['1000','1000'],['2000','2000'],['max','이상']],
  farMin:[['min','이하'],['100','100'],['200','200'],['300','300'],['400','400'],['500','500'],['600','600'],['700','700'],['800','800'],['900','900']],
  farMax:[['200','200'],['300','300'],['400','400'],['500','500'],['600','600'],['700','700'],['800','800'],['900','900'],['max','이상']],
  yearMin:[['min','이하'],['1980','1980'],['1990','1990'],['2000','2000'],['2005','2005'],['2010','2010'],['2015','2015'],['2020','2020'],['2025','2025']],
  yearMax:[['1980','1980'],['1990','1990'],['2000','2000'],['2005','2005'],['2010','2010'],['2015','2015'],['2020','2020'],['2025','2025'],['max','이상']],
};

const GRADE_TEXT = `1급지: 강남, 서초
2급지: 용산, 송파 (여의도, 성수·서울숲) / 경기: 과천
3급지: 성동 / 경기: 판교
4급지: 마포, 광진 (목동, 흑석) / 경기: 분당
5급지: 동작, 양천, 강동 (당산, 약수·신당)
6급지: 영등포, 중구 (마곡, 북아현, 청량리) / 경기: 하남, 성남 수정구 핵심지·위례, 철산
7급지: 종로, 서대문, 동대문 (수색, 신도림, 중계, 길음) / 경기: 광명, 수지, 광교, 동탄역 생활권, 평촌 핵심지
8급지: 성북, 강서, 관악, 구로, 노원 / 경기: 평촌, 동탄2, 의왕, 구리, 성남 중원구, 삼송·지축, 킨텍스 생활권
9급지: 은평, 중랑, 강북, 금천, 도봉 / 경기: 일산`;

function esc(s){return String(s ?? '').replace(/[&<>"']/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#039;'}[m]));}
function dateObj(s){ return new Date(`${s}T12:00:00+09:00`); }
function monthDiff(a,b){ return (a.getFullYear()-b.getFullYear())*12+(a.getMonth()-b.getMonth()); }
function num(v){ if(v==='min') return -Infinity; if(v==='max') return Infinity; return Number(v); }
function fmtMonth(v){ return String(v || '').replace('-','.'); }
function parseYear(s){ const m=String(s||'').match(/(19|20)\d{2}/); return m ? Number(m[0]) : null; }
function inRange(v,minv,maxv){ return v != null && Number.isFinite(Number(v)) && Number(v)>=num(minv) && Number(v)<=num(maxv); }
function money(v){
  if(v==null || !Number.isFinite(v)) return '—';
  const e=v/10000;
  const s=Number.isInteger(e)?e.toFixed(0):e.toFixed(2).replace(/0+$/,'').replace(/\.$/,'');
  return `${s}억`;
}
function signedMoney(v){ return `${v>=0?'+':''}${money(v)}`; }
function signedPct(v){ return `${v>=0?'+':''}${v.toFixed(1)}%`; }
function dataRegion(label){ return labelMap[label] || label; }

function buildRegionRows(hostId, rows){
  const host=document.getElementById(hostId); host.innerHTML='';
  const loaded=new Set(DATA.meta.loaded_regions || []);
  rows.forEach(row=>{
    const rowEl=document.createElement('div'); rowEl.className='regionRow';
    row.forEach(([label,tier])=>{
      const b=document.createElement('button');
      b.className=`regionBtn ${tier}`; b.textContent=label; b.dataset.region=dataRegion(label);
      if(selectedRegions.has(b.dataset.region)) b.classList.add('active');
      if(!loaded.has(b.dataset.region)) b.classList.add('noData');
      b.title=loaded.has(b.dataset.region)?`${label} 데이터 수록`:`${label} 데이터는 아직 수록되지 않음`;
      b.onclick=()=>{
        const r=b.dataset.region;
        if(selectedRegions.has(r)) selectedRegions.delete(r); else selectedRegions.add(r);
        b.classList.toggle('active'); render();
      };
      rowEl.appendChild(b);
    });
    host.appendChild(rowEl);
  });
}

function monthsBetween(minMonth,maxMonth){
  if(!minMonth || !maxMonth) return [];
  const [sy,sm]=minMonth.split('-').map(Number), [ey,em]=maxMonth.split('-').map(Number);
  const arr=[]; let d=new Date(sy,sm-1,1,12), end=new Date(ey,em-1,1,12);
  while(d<=end){ const v=`${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}`; arr.push([v,fmtMonth(v)]); d=new Date(d.getFullYear(),d.getMonth()+1,1,12); }
  return arr;
}
function fillSelect(el,opts,val){ el.innerHTML=''; opts.forEach(([v,l])=>el.insertAdjacentHTML('beforeend',`<option value="${esc(v)}">${esc(l)}</option>`)); el.value=val; }
function updateSummaries(){
  $('#periodSummary').textContent=`${fmtMonth(state.fromMonth)} ~ ${fmtMonth(state.toMonth)}`;
  $('#hhSummary').textContent=`${state.hhMin==='min'?'이하':state.hhMin+'세대'} ~ ${state.hhMax==='max'?'이상':state.hhMax+'세대'}`;
  $('#farSummary').textContent=`${state.farMin==='min'?'이하':state.farMin+'%'} ~ ${state.farMax==='max'?'이상':state.farMax+'%'}`;
  $('#yearSummary').textContent=state.yearMin==='min'&&state.yearMax==='max'?'전체':`${state.yearMin==='min'?'이하':state.yearMin} ~ ${state.yearMax==='max'?'이상':state.yearMax}`;
}
function openPopover(type,anchor){
  currentPop=type; const pop=$('#filterPopover'), min=$('#popMin'), max=$('#popMax');
  let title,optsMin,optsMax,vMin,vMax;
  if(type==='period'){ title='데이터 기간'; const opts=monthsBetween(DATA.meta.min_month || '2022-09', DATA.meta.current_month); optsMin=opts;optsMax=opts;vMin=state.fromMonth;vMax=state.toMonth; }
  if(type==='hh'){ title='세대수';optsMin=OPTIONS.householdMin;optsMax=OPTIONS.householdMax;vMin=state.hhMin;vMax=state.hhMax; }
  if(type==='far'){ title='용적률';optsMin=OPTIONS.farMin;optsMax=OPTIONS.farMax;vMin=state.farMin;vMax=state.farMax; }
  if(type==='year'){ title='준공일자';optsMin=OPTIONS.yearMin;optsMax=OPTIONS.yearMax;vMin=state.yearMin;vMax=state.yearMax; }
  $('#popTitle').textContent=title; fillSelect(min,optsMin,vMin); fillSelect(max,optsMax,vMax);
  const r=anchor.getBoundingClientRect(), w=290; let left=Math.min(r.left,window.innerWidth-w-12), top=r.bottom+7;
  if(top+165>window.innerHeight) top=Math.max(12,r.top-165);
  pop.style.left=`${Math.max(12,left)}px`;pop.style.top=`${top}px`;pop.classList.add('show');
}
function closePopover(){ $('#filterPopover').classList.remove('show');currentPop=null; }
function applyPopover(){
  const a=$('#popMin').value,b=$('#popMax').value;
  if(currentPop==='period'){ state.fromMonth=a;state.toMonth=b;if(state.fromMonth>state.toMonth)state.toMonth=state.fromMonth; }
  if(currentPop==='hh'){ state.hhMin=a;state.hhMax=b;if(num(a)>num(b))state.hhMax='max'; }
  if(currentPop==='far'){ state.farMin=a;state.farMax=b;if(num(a)>num(b))state.farMax='max'; }
  if(currentPop==='year'){ state.yearMin=a;state.yearMax=b;if(num(a)>num(b))state.yearMax='max'; }
  closePopover();updateSummaries();render();
}

function txRows(c,group){
  const raw=(c.tx || []).map(x=>({date:x[0],area:Number(x[1]),floor:Number(x[2]),price:Number(x[3])}));
  const band=group===59 ? raw.filter(t=>t.area>=57&&t.area<=61.5) : raw.filter(t=>t.area>=82&&t.area<=86.5);
  const mid=band.filter(t=>t.floor>=10);
  if(!mid.length) return [];
  // Prefer the most frequently traded near-identical exclusive-area cluster to avoid mixing distinct 59/84 types.
  const counts=new Map();
  mid.forEach(t=>{ const k=(Math.round(t.area*10)/10).toFixed(1); counts.set(k,(counts.get(k)||0)+1); });
  const [modeKey,modeCount]=[...counts.entries()].sort((a,b)=>b[1]-a[1] || Math.abs(Number(a[0])-group)-Math.abs(Number(b[0])-group))[0];
  const mode=Number(modeKey);
  const clustered=mid.filter(t=>Math.abs(t.area-mode)<=0.26);
  return (modeCount>=2 && clustered.length>=2) ? clustered : mid;
}
function weightFor(dist){ return dist===0?1:dist===1?.8:dist===2?.65:dist===3?.5:dist<=6?.3:.15; }
function weightedMedian(arr){
  const a=[...arr].sort((x,y)=>x.price-y.price), total=a.reduce((s,x)=>s+x.weight,0); let acc=0;
  for(const x of a){acc+=x.weight;if(acc>=total/2)return x.price;} return a.at(-1)?.price ?? null;
}
function pctile(vals,p){
  const a=[...vals].sort((x,y)=>x-y); if(!a.length)return null;if(a.length===1)return a[0];
  const i=(a.length-1)*p,l=Math.floor(i),h=Math.ceil(i);return l===h?a[l]:a[l]+(a[h]-a[l])*(i-l);
}
function estimate(c,group,target,isEnd){
  const base=txRows(c,group);if(!base.length)return null;const windows=[0,1,2,3,6,12];
  for(const win of windows){
    const cand=base.filter(t=>{const d=monthDiff(dateObj(t.date),target);if(isEnd&&d>0)return false;return Math.abs(d)<=win;});
    if(!cand.length)continue;const monthSet=new Set(cand.map(t=>t.date.slice(0,7)));
    if(win===0&&cand.length<2)continue;
    if(win>0&&cand.length<2&&monthSet.size<2&&win<12)continue;
    const weighted=cand.map(t=>{const dist=Math.abs(monthDiff(dateObj(t.date),target));return {...t,dist,weight:weightFor(dist)};});
    const prices=cand.map(x=>x.price);return {value:weightedMedian(weighted),low:pctile(prices,.25),high:pctile(prices,.75),samples:weighted,window:win};
  }
  return null;
}
function confidence(oldE,newE){
  if(!oldE||!newE)return{s:1,reasons:['10층 이상 실거래 표본이 부족해 정상 중층 매수가를 계산하지 못함']};
  let s=5,reasons=[];
  for(const [label,e] of [['과거',oldE],['현재',newE]]){
    if(e.window===0) reasons.push(`${label}: 목표월 10층 이상 거래 사용`);
    else if(e.window<=1){s-=1;reasons.push(`${label}: ±1개월까지 확대`);}
    else if(e.window<=3){s-=2;reasons.push(`${label}: ±${e.window}개월까지 확대`);}
    else{s-=3;reasons.push(`${label}: ±${e.window}개월까지 확대`);}
    if(e.samples.length<=2){s-=1;reasons.push(`${label}: 표본 ${e.samples.length}건`);}
  }
  return{s:Math.max(1,s),reasons};
}
function displayName(c){
  const station=(c.station_display || c.station || '').replace(/역$/,'');
  return station ? `${c.name}(${station}역)` : c.name;
}
function filterComplex(c){
  if(!selectedRegions.has(c.region)) return false;
  if(!inRange(c.households,state.hhMin,state.hhMax)) return false;
  const farDefault=state.farMin==='100'&&state.farMax==='max';
  if(c.far==null || !Number.isFinite(Number(c.far))){ if(!farDefault)return false; } else if(!inRange(c.far,state.farMin,state.farMax)) return false;
  const y=parseYear(c.completed); const yearDefault=state.yearMin==='min'&&state.yearMax==='max';
  if(y==null){if(!yearDefault)return false;} else if(!inRange(y,state.yearMin,state.yearMax))return false;
  return true;
}
function render(){
  updateSummaries();
  const oldTarget=new Date(`${state.fromMonth}-01T12:00:00+09:00`),newTarget=new Date(`${state.toMonth}-01T12:00:00+09:00`);
  $('#oldHead').textContent=`${fmtMonth(state.fromMonth)} 정상 중층 매수가`;$('#newHead').textContent=`${fmtMonth(state.toMonth)} 정상 중층 매수가`;
  const valid=[],missing=[];
  DATA.complexes.filter(filterComplex).forEach(c=>{
    const hasArea=txRows(c,currentArea).length>0;
    const oldE=estimate(c,currentArea,oldTarget,false),newE=estimate(c,currentArea,newTarget,true),cf=confidence(oldE,newE);
    if(oldE&&newE){const change=newE.value-oldE.value,rate=change/oldE.value*100;valid.push({c,oldE,newE,cf,change,rate,ok:true});}
    else missing.push({c,oldE,newE,cf,ok:false,areaMissing:!hasArea});
  });
  valid.sort((a,b)=>b.change-a.change || b.rate-a.rate || a.c.name.localeCompare(b.c.name,'ko'));
  valid.forEach((x,i)=>x.rank=i+1);missing.sort((a,b)=>a.c.name.localeCompare(b.c.name,'ko'));shownRows=[...valid,...missing];
  $('#rowCount').textContent=`${shownRows.length}개 단지 · 가격산정 ${valid.length}개`;
  const tb=$('#tbody');
  if(!shownRows.length){tb.innerHTML='<tr class="emptyRow"><td colspan="10">선택한 지역/조건에 맞는 단지가 없습니다.</td></tr>';return;}
  tb.innerHTML=shownRows.map((r,idx)=>{
    const c=r.c, name=esc(displayName(c)), naver=esc(c.naver || `https://new.land.naver.com/search?sk=${encodeURIComponent(c.name)}`), far=c.far==null?'—':`${Number(c.far).toFixed(Number(c.far)%1?1:0)}%`, completed=esc(c.completed || '—');
    if(!r.ok){const reason=r.areaMissing?`${currentArea}㎡ 중층 데이터 부족`:'비교기간 중층 데이터 부족';return `<tr class="emptyRow"><td class="rank">—</td><td><a class="name" target="_blank" rel="noopener" href="${naver}">${name}</a><div class="subline">${reason}</div></td><td>${c.households??'—'}</td><td>${far}</td><td>${completed}</td><td class="na">중층 데이터 부족</td><td class="na">중층 데이터 부족</td><td>—</td><td>—</td><td><span class="conf" onclick="openDetail(${idx})">*1</span></td></tr>`;}
    const cls=r.change>=0?'up':'down';return `<tr><td class="rank">${r.rank}</td><td><a class="name" target="_blank" rel="noopener" href="${naver}">${name}</a><div class="subline">10층 이상 · 대표면적 자동매칭</div></td><td>${c.households??'—'}</td><td>${far}</td><td>${completed}</td><td><div class="priceMain"><span class="est">(추정)</span>${money(r.oldE.value)}</div><div class="rangeLine">${money(r.oldE.low)}~${money(r.oldE.high)} · ${r.oldE.samples.length}건</div></td><td><div class="priceMain"><span class="est">(추정)</span>${money(r.newE.value)}</div><div class="rangeLine">${money(r.newE.low)}~${money(r.newE.high)} · ${r.newE.samples.length}건</div></td><td class="${cls}">${signedMoney(r.change)}</td><td class="${cls}">${signedPct(r.rate)}</td><td><span class="conf" onclick="openDetail(${idx})">*${r.cf.s}</span></td></tr>`;
  }).join('');
}
function sampleHtml(e,target){
  if(!e)return'<tr><td colspan="5" class="na">표본 없음</td></tr>';
  return e.samples.slice().sort((a,b)=>dateObj(b.date)-dateObj(a.date)).map(x=>`<tr><td>${esc(x.date)}</td><td>${x.floor}층</td><td>${x.area.toFixed(2)}㎡</td><td>${money(x.price)}</td><td>${Math.abs(monthDiff(dateObj(x.date),target))}개월</td></tr>`).join('');
}
window.openDetail=function(index){
  const r=shownRows[index],oldTarget=new Date(`${state.fromMonth}-01T12:00:00+09:00`),newTarget=new Date(`${state.toMonth}-01T12:00:00+09:00`),c=r.c;
  $('#dTitle').textContent=displayName(c);$('#dSub').textContent=`${c.region} · ${c.households??'—'}세대 · 용적률 ${c.far==null?'—':c.far+'%'} · 준공 ${c.completed||'—'}`;
  $('#oldP').textContent=r.oldE?`(추정)${money(r.oldE.value)}`:'계산 불가';$('#newP').textContent=r.newE?`(추정)${money(r.newE.value)}`:'계산 불가';
  $('#oldT').textContent=r.oldE?`표본 ${r.oldE.samples.length}건 · 관찰구간 ${money(r.oldE.low)}~${money(r.oldE.high)}`:'10층 이상 표본 없음';
  $('#newT').textContent=r.newE?`표본 ${r.newE.samples.length}건 · 관찰구간 ${money(r.newE.low)}~${money(r.newE.high)}`:'10층 이상 표본 없음';
  $('#confT').textContent=`*${r.cf.s} 산정 근거`;$('#reasons').innerHTML=r.cf.reasons.map(x=>`<li>${esc(x)}</li>`).join('');
  $('#oldSamples').innerHTML=sampleHtml(r.oldE,oldTarget);$('#newSamples').innerHTML=sampleHtml(r.newE,newTarget);$('#detailWrap').classList.add('show');
};

async function init(){
  try{
    const res=await fetch(`${DATA_URL}?v=${Date.now()}`,{cache:'no-store'});if(!res.ok)throw new Error(`HTTP ${res.status}`);DATA=await res.json();
  }catch(err){
    console.error(err);$('#tbody').innerHTML='<tr class="emptyRow"><td colspan="10">데이터 파일을 불러오지 못했습니다. 로컬 파일로 직접 열지 말고 정적 웹서버/Vercel에서 실행하세요.</td></tr>';return;
  }
  state.toMonth=DATA.meta.current_month || '2026-09';
  const earliest=DATA.meta.min_month || '2022-09'; if(state.fromMonth<earliest)state.fromMonth=earliest;if(state.fromMonth>state.toMonth)state.fromMonth=state.toMonth;
  const loaded=DATA.meta.loaded_regions || ['영등포구','성동구','마포구'];selectedRegions=new Set(loaded);
  $('#updatedAt').textContent=DATA.meta.updated_at?`데이터 ${DATA.meta.updated_at}`:'';
  if(DATA.meta.status && DATA.meta.status!=='full'){const n=$('#dataNotice');n.hidden=false;n.textContent=DATA.meta.note || '현재는 구축 단계 데이터입니다. GitHub Actions 최초 수집이 완료되면 전체 데이터로 교체됩니다.';}
  $('#gradeText').textContent=GRADE_TEXT;buildRegionRows('seoulRegionRows',seoulRows);buildRegionRows('gyeonggiRegionRows',gyeonggiRows);updateSummaries();render();
}

$('#periodSummary').onclick=e=>openPopover('period',e.currentTarget);$('#hhSummary').onclick=e=>openPopover('hh',e.currentTarget);$('#farSummary').onclick=e=>openPopover('far',e.currentTarget);$('#yearSummary').onclick=e=>openPopover('year',e.currentTarget);
$('#popCancel').onclick=closePopover;$('#popApply').onclick=applyPopover;
document.addEventListener('mousedown',e=>{const p=$('#filterPopover');if(p.classList.contains('show')&&!p.contains(e.target)&&!e.target.classList.contains('summaryBtn'))closePopover();});
document.addEventListener('keydown',e=>{if(e.key==='Escape'){closePopover();$$('.modalWrap.show').forEach(x=>x.classList.remove('show'));}});
$$('[data-close]').forEach(b=>b.onclick=()=>document.getElementById(b.dataset.close).classList.remove('show'));
$('#openGradeHelp').onclick=()=>$('#gradeHelpWrap').classList.add('show');
$('#selectLoadedRegions').onclick=()=>{const loaded=new Set(DATA.meta.loaded_regions||[]);selectedRegions=new Set(loaded);$$('.regionBtn').forEach(b=>b.classList.toggle('active',loaded.has(b.dataset.region)));render();};
$('#selectAllRegions').onclick=()=>{$$('.regionBtn').forEach(b=>{selectedRegions.add(b.dataset.region);b.classList.add('active');});render();};
$('#clearRegions').onclick=()=>{selectedRegions.clear();$$('.regionBtn').forEach(b=>b.classList.remove('active'));render();};
$('#areaToggle').querySelectorAll('button').forEach(btn=>btn.onclick=()=>{currentArea=Number(btn.dataset.area);$('#areaToggle').querySelectorAll('button').forEach(x=>x.classList.toggle('active',x===btn));render();});

init();
