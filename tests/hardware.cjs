const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),{JSDOM}=require('jsdom');
const root=path.resolve(__dirname,'..'),api=require('../hardware-guidance.js');
const catalog=JSON.parse(fs.readFileSync(path.join(root,'hardware-guidance.json'),'utf8'));
const news=JSON.parse(fs.readFileSync(path.join(root,'news.json'),'utf8'));
const html=fs.readFileSync(path.join(root,'index.html'),'utf8'),script=fs.readFileSync(path.join(root,'hardware-guidance.js'),'utf8'),ui=fs.readFileSync(path.join(root,'news-ui.js'),'utf8');
const tick=()=>new Promise(r=>setTimeout(r,0));
api.validateCatalog(catalog);assert.equal(catalog.models.length,24);
assert.equal(catalog.models.filter(e=>e.status!=='identity_unverified').length,21);
assert.equal(catalog.models.filter(e=>!['identity_unverified','unreleased'].includes(e.status)).length,20);
const currentNames=[...new Set(['general','coding','japanese','edge'].flatMap(k=>news['ranking_'+k].map(m=>m.name)))];
assert.equal(currentNames.length,24);assert.ok(currentNames.every(name=>api.lookup(catalog,name)));
assert.equal(api.lookup(catalog,'Qwen3.8-Flash-Next').total_parameters_b,180);
assert.match(api.lookup(catalog,'Qwen3.8-Flash-Next').conditions.join(' '),/51B/);
for(const name of ['Code Llama 4 70B','Code Llama 4 34B','Qwen3-72B']) {
 const e=api.lookup(catalog,name);assert.equal(e.status,'identity_unverified');assert.equal(e.total_parameters_b,null);assert.equal(e.examples.length,0);assert.equal(e.weight_gb,null);
}
for(const e of catalog.models.filter(e=>e.status==='estimated'))assert.match(e.memory,/^推定：/);

assert.equal(api.lookup(catalog,'  GEMMA 3 4B  ').weight_gb,2.6);
assert.equal(api.lookup(catalog,'Llama 4 Scout').total_parameters_b,109);
assert.equal(api.lookup(catalog,'Llama 4 Scout').active_parameters_b,17);
assert.equal(api.lookup(catalog,'Made up 4B'),null);
const invalid=[d=>d.version=2,d=>d.models[0].status='__proto__',d=>d.models[0].weight_gb=-1,d=>d.models[0].weight_gb='16',d=>d.models[0].active_parameters_b=999,d=>d.models[0].checked_at='2026-02-30',d=>d.models[0].checked_at='2999-01-01',d=>d.models[0].sources[0].url='javascript:alert(1)',d=>d.models[0].sources[0].url='https://user:pass@example.com',d=>d.models[0].sources=[],d=>d.models[0].conditions=[],d=>d.models[0].aliases.push(d.models[1].aliases[0])];
invalid.forEach(change=>{let d=structuredClone(catalog);change(d);assert.throws(()=>api.validateCatalog(d));});
function setup(){const dom=new JSDOM(html,{url:'https://test.local',runScripts:'outside-only'}),w=dom.window,requests=[];w.fetch=(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}));for(const s of w.document.querySelectorAll('script:not([src])'))w.eval(s.textContent);w.eval(script);w.eval(ui);return {dom,w,d:w.document,requests};}
async function resolve(x,name,data){const i=x.requests.findIndex(r=>r.url.startsWith(name));assert.ok(i>=0);x.requests.splice(i,1)[0].resolve({ok:true,json:async()=>data});await tick();}
(async()=>{
 let x=setup();await resolve(x,'news.json',news);assert.equal(x.d.querySelectorAll('.hw-status').length,8);assert.ok([...x.d.querySelectorAll('.hw-status')].every(e=>e.textContent==='確認中'));
 await resolve(x,'hardware-guidance.json',catalog);assert.match(x.d.querySelector('#rankGrid').textContent,/DGX Spark/);assert.match(x.d.querySelector('#rankGrid').textContent,/重み公開待ち/);
 for(const key of ['coding','japanese','edge','general']){x.w.rankTab(null,key);assert.equal(x.d.querySelectorAll('#rankGrid .hardware-guide').length,8);}
 x.w.rankTab(null,'edge');assert.match(x.d.querySelector('#rankGrid').textContent,/Mac mini/);
 const details=x.d.querySelector('.hw-details');details.open=true;assert.ok(details.open);details.open=false;assert.ok(!details.open);
 assert.ok([...x.d.querySelectorAll('.hw-sources a')].every(a=>a.rel==='noopener noreferrer'&&a.target==='_blank'));
 // Generated unknown fields cannot modify the reviewed catalog or produce markup.
 const hostile=structuredClone(news);hostile.ranking_general[0].name='<img src=x onerror="window.pwned=1">';hostile.ranking_general[0].hardware={memory:'1GB',examples:['FAKE PC']};
 x.d.querySelector('#newsStatus + button').click();await resolve(x,'news.json',hostile);assert.equal(x.w.pwned,undefined);assert.equal(x.d.querySelectorAll('#rankGrid img').length,0);assert.doesNotMatch(x.d.querySelector('#rankGrid').textContent,/FAKE PC/);x.dom.window.close();
 // Ambiguous model identities never borrow another model's specs/benchmark claims.
 x=setup();const ambiguous=structuredClone(news);ambiguous.ranking_general[0]={...ambiguous.ranking_general[0],name:'Code Llama 4 70B',size:'70B',reason:'UNVERIFIED BENCHMARK',badges:['UNVERIFIED BADGE']};
 await resolve(x,'hardware-guidance.json',catalog);await resolve(x,'news.json',ambiguous);
 assert.equal(x.d.querySelector('#rankGrid .rsize').textContent,'名称確認中');
 assert.doesNotMatch(x.d.querySelector('#rankGrid .rc').textContent,/UNVERIFIED/);
 assert.match(x.d.querySelector('#rankGrid .hardware-guide').textContent,/公式のCode Llama/);x.dom.window.close();
 // Known unresolved names fail closed before/without the optional catalog.
 for(const entry of catalog.models.filter(e=>e.status==='identity_unverified')) {
   x=setup();const d=structuredClone(news);d.ranking_general[0]={...d.ranking_general[0],name:entry.aliases[0],size:'70B',reason:'UNVERIFIED BENCHMARK',badges:['UNVERIFIED BADGE'],score:95,released:'2026.07'};
   await resolve(x,'news.json',d);
   let card=x.d.querySelector('#rankGrid .rc');assert.doesNotMatch(card.textContent,/UNVERIFIED|SCORE 95|2026.07/);assert.equal(card.querySelectorAll('.rbar-bg').length,0);
   x.requests.find(r=>r.url==='hardware-guidance.json').reject(new Error('offline'));await tick();
   card=x.d.querySelector('#rankGrid .rc');assert.doesNotMatch(card.textContent,/UNVERIFIED|SCORE 95|2026.07/);assert.equal(card.querySelector('.rsize').textContent,'名称確認中');x.dom.window.close();
 }
 // Hardware prose must be suppressed, without rejecting valid daily news.
 for(const claim of ['VRAM24GBで動作','メモリ１６ＧＢで動く','30 tokens/s','30 t/s','毎秒30トークン','Mac miniで動作','DGX Spark対応','単一GPUで動作可能','GPU1枚で動作','CPUだけで動作可能','高速動作','快適に利用']) {
   x=setup();const d=structuredClone(news);d.ranking_general[0].reason=claim;d.ranking_general[0].badges=[claim,'MoE'];
   await resolve(x,'news.json',d);await resolve(x,'hardware-guidance.json',catalog);
   assert.match(x.d.querySelector('#newsStatus').textContent,/データ更新日/);
   assert.equal(x.d.querySelector('#rankGrid .rreason').textContent,'ローカル実行の条件は、下のPC・メモリの目安をご確認ください。');
   assert.equal(x.d.querySelector('#rankGrid .rbadges').textContent,'MoE');x.dom.window.close();
 }
 // Broken optional guidance never discards valid news. Retry preserves selected tab.
 x=setup();await resolve(x,'hardware-guidance.json',{version:2,models:[]});await resolve(x,'news.json',news);assert.match(x.d.querySelector('#newsStatus').textContent,/データ更新日/);assert.equal(x.d.querySelector('.hw-retry').hidden,false);x.w.rankTab(null,'japanese');x.d.querySelector('.hw-retry').click();x.d.querySelector('.hw-retry').click();assert.equal(x.requests.length,1);await resolve(x,'hardware-guidance.json',catalog);assert.match(x.d.querySelector('.rtab.ac').textContent,/日本語/);assert.match(x.d.querySelector('#rankGrid').textContent,/Mac Studio/);x.dom.window.close();
 // Catalog-first and failed-news ordering preserve the saved unknown fallback.
 x=setup();await resolve(x,'hardware-guidance.json',catalog);x.requests[0].reject(new Error('offline'));await tick();assert.equal(x.d.querySelectorAll('#rankGrid .hardware-guide').length,1);assert.match(x.d.querySelector('#newsStatus').textContent,/失敗/);assert.doesNotMatch(x.d.querySelector('#rankGrid').textContent,/VRAM24GB動作|RTX 5090 1枚/);x.dom.window.close();
 console.log('PASS hardware: 21 source-backed identities +3 explicit name warnings, unknown/generated-field isolation, 12 invalid catalogs, source safety, independent fetch/failure/retry, both fetch orders, tabs and details.');
})();
