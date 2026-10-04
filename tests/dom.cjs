// npm install --no-save jsdom@26.1.0; node tests/dom.cjs
const {JSDOM} = require('jsdom');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const root=path.resolve(__dirname,'..'), html=fs.readFileSync(path.join(root,'index.html'),'utf8'), ui=fs.readFileSync(path.join(root,'news-ui.js'),'utf8');
const fixture=JSON.parse(fs.readFileSync(path.join(root,'news.json'),'utf8'));
const tick=()=>new Promise(r=>setTimeout(r,0));
function setup(withoutInitialFlags=false){
 const dom=new JSDOM(html,{url:'https://example.test/',runScripts:'outside-only'}),w=dom.window;
 if(withoutInitialFlags)w.document.querySelectorAll('.rflag').forEach(n=>n.remove());
 const requests=[];w.fetch=(url,options)=>new Promise((resolve,reject)=>requests.push({resolve,reject,options}));
 for(const script of w.document.querySelectorAll('script:not([src])'))w.eval(script.textContent);
 w.eval(ui);return {dom,w,d:w.document,requests};
}
function choose(x,key){const b=x.d.querySelector(`[onclick="rankTab(this,'${key}')"]`);x.w.rankTab(b,key);}
async function fulfill(x,data=fixture){x.requests.shift().resolve({ok:true,json:async()=>data});await tick();}
(async()=>{
 let x=setup(),fallback=x.d.querySelector('#rankGrid').textContent;
 choose(x,'coding');assert.equal(x.d.querySelector('#rankGrid').textContent,fallback);assert.match(x.d.querySelector('#newsStatus').textContent,/通常用途の保存/);
 x.w.filt(x.d.querySelectorAll('.fb')[1],'model');
 await fulfill(x);assert.match(x.d.querySelector('.rtab.ac').textContent,/コーディング/);assert.ok(x.d.querySelector('#rankGrid').textContent.includes(fixture.ranking_coding[0].name));
 let dates=Array.from(x.d.querySelectorAll('#ng .ndate'),n=>n.textContent);assert.deepEqual(dates,[...dates].sort().reverse());assert.equal(dates.length,fixture.articles.length);
 for(const c of x.d.querySelectorAll('#ng .nc'))assert.equal(c.style.display,c.dataset.t==='model'?'':'none');
 for(const key of ['general','japanese','coding','edge','general'])choose(x,key);
 assert.ok(x.d.querySelector('#rankGrid').textContent.includes(fixture.ranking_general[0].name));
 // A failed refresh preserves already-loaded data and selected category.
 const before=x.d.querySelector('#rankGrid').textContent;x.d.querySelector('#newsStatus + button').click();x.requests.shift().reject(new Error('offline'));await tick();assert.equal(x.d.querySelector('#rankGrid').textContent,before);assert.match(x.d.querySelector('#newsStatus').textContent,/失敗/);
 x.d.querySelector('#newsStatus + button').click();x.d.querySelector('#newsStatus + button').click();assert.equal(x.requests.length,1);choose(x,'edge');await fulfill(x);assert.match(x.d.querySelector('.rtab.ac').textContent,/エッジ/);
 const years=Array.from(x.d.querySelectorAll('.ayb'),n=>n.textContent);assert.deepEqual(years,['2026','2025','2024']);assert.equal(x.w.AD.length,16);
 x.d.querySelectorAll('.ayb')[2].click();assert.equal(x.d.querySelectorAll('#ag .acard').length,2);assert.equal(x.d.querySelectorAll('#ag a').length,2);
 x.dom.window.close();
 const hostile='<img src=x onerror="window.pwned=1"> & " </script><script>window.pwned=1</script>';
 let data=structuredClone(fixture);data.ticker=[hostile];Object.assign(data.featured,{title:hostile,summary:hostile});Object.assign(data.articles[0],{title:hostile,summary:hostile});
 for(const key of ['general','coding','japanese','edge'])Object.assign(data['ranking_'+key][0],{name:hostile,size:hostile,country:hostile,org:hostile,reason:hostile,badges:[hostile],score:0});
 x=setup();await fulfill(x,data);assert.equal(x.w.pwned,undefined);assert.equal(x.d.querySelectorAll('#tickerTrack img,#rankGrid img,#ng img,#heroBox script').length,0);assert.ok(x.d.querySelector('#rankGrid').textContent.includes(hostile));assert.equal(x.d.querySelector('#rankGrid .rbar').style.width,'0%');x.dom.window.close();
 const invalid=[...['javascript:alert(1)','data:text/html,hi','httpsx://example.com','//example.com','https://user:pass@example.com','https://example.com/\nonclick=x','https://'].map(url=>d=>{d.featured.url=url;}),d=>{d.articles[0].date='2026.02.30';},d=>{d.ranking_edge[0].badges={};},d=>{d.ranking_general[0].score='90';},d=>{d.ticker=[{}];},d=>{delete d.ranking_japanese;},d=>{d.updated='2999.01.01';},d=>{d.articles[0].tag='__proto__';},d=>{d.ranking_edge[0].released='2026.13';}];
 for(const change of invalid){data=structuredClone(fixture);change(data);x=setup();await fulfill(x,data);assert.match(x.d.querySelector('#newsStatus').textContent,/失敗/);assert.equal(x.d.querySelector('#rankGrid').textContent,fallback);x.dom.window.close();}
 x=setup();choose(x,'japanese');x.requests.shift().reject(new Error('network'));await tick();assert.equal(x.d.querySelector('#rankGrid').textContent,fallback);assert.match(x.d.querySelector('.rtab.ac').textContent,/日本語/);assert.match(x.d.querySelector('#newsStatus').textContent,/失敗/);x.d.querySelector('#newsStatus + button').click();await fulfill(x);assert.ok(x.d.querySelector('#rankGrid').textContent.includes(fixture.ranking_japanese[0].name));x.dom.window.close();
 // All supported flags must render in every category without any initial SVGs.
 const codes=['cn','us','fr','jp'];
 const flagData=structuredClone(fixture);
 for(const key of ['general','coding','japanese','edge']){
  const template=flagData['ranking_'+key][0];
  flagData['ranking_'+key]=codes.map((flag,i)=>({...structuredClone(template),flag,name:'Flag '+flag,country:['中国','米国','仏国','日本'][i]}));
 }
 x=setup(true);assert.equal(x.d.querySelectorAll('#rankGrid .rflag').length,0);await fulfill(x,flagData);
 for(const key of ['general','coding','japanese','edge','general']){
  choose(x,key);const svgs=Array.from(x.d.querySelectorAll('#rankGrid .rflag svg'));
  assert.equal(svgs.length,4);
  assert.ok(svgs.every(n=>n.namespaceURI==='http://www.w3.org/2000/svg' && n.getAttribute('viewBox')==='0 0 30 20'));
  assert.equal(svgs[0].querySelector('polygon').getAttribute('fill'),'#FFDE00');
  assert.equal(svgs[1].querySelectorAll('rect').length,9);
  assert.equal(svgs[2].querySelectorAll('rect').length,3);
  assert.equal(svgs[3].querySelector('circle').getAttribute('fill'),'#BC002D');
 }
 x.dom.window.close();
 // Current data flags render independently too; no country SVG is borrowed from fallback.
 x=setup(true);await fulfill(x);
 for(const key of ['general','coding','japanese','edge']){
  choose(x,key);assert.equal(x.d.querySelectorAll('#rankGrid .rflag svg').length,fixture['ranking_'+key].filter(m=>codes.includes(m.flag)).length);
 }
 x.dom.window.close();
 // Empty code is the supported no-flag fallback; unknown/hostile codes reject safely.
 data=structuredClone(fixture);data.ranking_general[0].flag='';x=setup(true);await fulfill(x,data);assert.equal(x.d.querySelector('#rankGrid .rc').querySelector('.rflag'),null);x.dom.window.close();
 for(const flag of ['zz','__proto__','<svg onload="window.pwned=1">']){
  data=structuredClone(fixture);data.ranking_general[0].flag=flag;x=setup(true);await fulfill(x,data);
  assert.match(x.d.querySelector('#newsStatus').textContent,/失敗/);assert.equal(x.d.querySelectorAll('#rankGrid .rflag').length,0);assert.equal(x.w.pwned,undefined);x.dom.window.close();
 }
 console.log('PASS DOM: independent cn/us/fr/jp SVGs in all categories and safe unknown-code fallback; safe text, 15 invalid payloads/URLs, stable sorting/all articles, category before load, initial/refresh failure, fallback/retry, duplicate clicks, filter retention, repeated tabs and all 16 archive records/unique years.');
})().catch(e=>{console.error(e);process.exitCode=1;});
