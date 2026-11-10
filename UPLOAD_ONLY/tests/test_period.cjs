const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),path=require('node:path');
const html=fs.readFileSync(path.join(__dirname,'../index.html'),'utf8');
function extract(start,end){const a=html.indexOf(start),b=html.indexOf(end,a);assert(a>=0&&b>a);return html.slice(a,b);}
const elements={};const context=vm.createContext({Intl,Date,console,
 DATA:{meta:{min_month:'2024-01',current_month:'2026-09'},complexes:[]},
 state:{fromMonth:'2025-09',toMonth:'2026-10'},
 fmtMonth:x=>x,esc:x=>x,trackFilterChange:()=>{},updateSummaries:()=>{},
 $:key=>elements[key]??=( {} ),shownRows:[{old:'stale'}]});
vm.runInContext(extract('function monthsBetween(', 'function fillSelect(')+extract('function latestClosedMonthKST(', 'function pendingMonth('),context);
assert.equal(vm.runInContext("latestClosedMonthKST(new Date('2026-10-31T14:59:59Z'))",context),'2026-09');
assert.equal(vm.runInContext("latestClosedMonthKST(new Date('2026-10-31T15:00:00Z'))",context),'2026-10');
assert.equal(vm.runInContext("latestClosedMonthKST(new Date('2026-12-31T15:00:00Z'))",context),'2026-12');
vm.runInContext("latestClosedMonthKST=()=> '2026-10'",context);
let options=vm.runInContext('periodOptions()',context);
assert.equal(options[0][0],'2026-10');assert.match(options[0][1],/수집 대기/);
assert(!options.some(x=>x[0]==='2026-11'));
assert(vm.runInContext('selectedPeriodPending()',context));
// Exercise the actual rendering early exit: an old price cannot masquerade as October.
vm.runInContext(extract('function render(){','  const valid=[],missing=[];')+'}',context);
vm.runInContext('render()',context);
assert.equal(context.shownRows.length,0);assert.match(elements['#tbody'].innerHTML,/2026-10/);assert.match(elements['#tbody'].innerHTML,/2026-09/);
vm.runInContext("DATA.meta.current_month='2026-10'",context);
assert.equal(vm.runInContext('selectedPeriodPending()',context),false);
assert.equal(vm.runInContext('periodOptions()[0][1]',context),'2026-10');
vm.runInContext("DATA.meta.current_month='2026-09';state.toMonth='2026-09'",context);
assert.equal(vm.runInContext('selectedPeriodPending()',context),false);
// Every inline script is valid JavaScript, including embedded data and app code.
for(const match of html.matchAll(/<script\b([^>]*)>([\s\S]*?)<\/script>/g)){
 if(!/\bsrc=/.test(match[1])&&match[2].trim())new vm.Script(match[2]);
}
console.log('PASS: KST rollover, October options, pending-data guard, collected-month transition, inline JS syntax');
