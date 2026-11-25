const test = require('node:test');
const assert = require('node:assert/strict');
const vm = require('node:vm');
const fs = require('node:fs');
const generator = fs.readFileSync('gen_briefing.py','utf8');
const start = generator.indexOf('async function copySection(key, btn)');
const source = generator.slice(start, generator.indexOf('function refreshDataCardExpiry()',start)).replaceAll('{{','{').replaceAll('}}','}');
const text = '오늘의 뉴스\nhttps://v.daum.net/v/20261125142405459\n코스피 : 4,683.72pt';
function setup(writeText, {fallback=true, timeout=false, disabled=false}={}) {
  const state = {copied:0,alerts:0,legacy:0,written:null,expiry:0};
  const ta = {value:'visible preview',style:{cssText:'original'},focus(){},select(){},setSelectionRange(){}};
  const context = vm.createContext({
    navigator:writeText === null ? {} : {clipboard:{writeText: value=>{state.written=value;return writeText(value);}}},
    window:{__content_shortnews:text},
    document:{getElementById:()=>ta,execCommand:()=>{state.legacy++;return fallback;}},
    refreshDataCardExpiry:()=>state.expiry++, markCopied:()=>state.copied++, alert:()=>state.alerts++,
    setTimeout:timeout ? callback=>{queueMicrotask(callback);return 1;} : setTimeout,
    clearTimeout:timeout ? ()=>{} : clearTimeout,
  });
  vm.runInContext(source,context);
  return {state,ta,copy:()=>context.copySection('shortnews',{disabled})};
}
test('successful clipboard write includes URLs and KOSPI without trusting execCommand',async()=>{
  const t=setup(()=>Promise.resolve()); await t.copy();
  assert.equal(t.state.written,text); assert.equal(t.state.copied,1); assert.equal(t.state.legacy,0);
});
test('rejected clipboard permission uses fallback and restores preview',async()=>{
  const t=setup(()=>Promise.reject(new Error('denied'))); await t.copy();
  assert.equal(t.state.legacy,1);assert.equal(t.state.copied,1);assert.equal(t.ta.value,'visible preview');assert.equal(t.ta.style.cssText,'original');
});
test('older browsers keep synchronous clipboard fallback',async()=>{
  const t=setup(null);await t.copy();assert.equal(t.state.legacy,1);assert.equal(t.state.copied,1);
});
test('an unresolved clipboard request cannot stall the button',async()=>{
  const t=setup(()=>new Promise(()=>{}),{timeout:true});await t.copy();
  assert.equal(t.state.legacy,1);assert.equal(t.state.copied,1);
});
test('failure of both clipboard paths does not report copied',async()=>{
  const t=setup(()=>Promise.reject(new Error('denied')),{fallback:false});await t.copy();
  assert.equal(t.state.copied,0);assert.equal(t.state.alerts,1);
});
test('disabled expired cards do not copy',async()=>{
  const t=setup(()=>Promise.resolve(),{disabled:true});await t.copy();
  assert.equal(t.state.expiry,1);assert.equal(t.state.written,null);assert.equal(t.state.legacy,0);assert.equal(t.state.copied,0);
});
