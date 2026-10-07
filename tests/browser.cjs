// Offline browser regression suite: node tests/browser.cjs (Playwright required).
const {chromium} = require('playwright');
const fs = require('node:fs'), path = require('node:path'), assert = require('node:assert/strict');
const root = path.resolve(__dirname,'..'), fixture = JSON.parse(fs.readFileSync(path.join(root,'news.json'),'utf8'));
(async()=>{
 const browser = await chromium.launch({headless:true,...(process.env.CHROMIUM_PATH ? {executablePath:process.env.CHROMIUM_PATH} : {})});
 try {
 const page = await browser.newPage();
 let payload = structuredClone(fixture), fail=false, release, requests=0;
 await page.route('**/*',async route=>{
  const url = new URL(route.request().url());
  if(url.pathname.endsWith('news.json')) {requests++;if(release)await new Promise(r=>release=r);if(fail)return route.fulfill({status:503,body:'unavailable'});return route.fulfill({json:payload});}
  const file = path.join(root,url.pathname==='/'?'index.html':url.pathname.slice(1));
  if(file.startsWith(root) && fs.existsSync(file))return route.fulfill({path:file});
  return route.abort();
 });
 release=true; await page.goto('https://test.local/');
 const fallback = await page.locator('#rankGrid').innerText();
 await page.getByRole('button',{name:'コーディング用途'}).click();
 assert.equal(await page.locator('#rankGrid').innerText(),fallback);
 assert.match(await page.locator('#newsStatus').innerText(),/通常用途の保存/);
 const unblock=release; release=null;unblock();
 await page.waitForFunction(()=>document.querySelector('#newsStatus').textContent.startsWith('データ更新日'));
 assert.match(await page.locator('.rtab.ac').innerText(),/コーディング/);
 assert.match(await page.locator('#rankGrid').innerText(),new RegExp(fixture.ranking_coding[0].name.replace(/[.*+?^${}()|[\]\\]/g,'\\$&')));
 const dates = await page.locator('#ng .ndate').allTextContents();assert.deepEqual(dates,[...dates].sort().reverse());assert.equal(dates.length,fixture.articles.length);
 // Hostile generated text remains literal in every sink.
 const hostile='<img src=x onerror="window.pwned=1"> & " </script><script>window.pwned=1</script>';
 payload=structuredClone(fixture);payload.ticker=[hostile];payload.featured.title=hostile;payload.featured.summary=hostile;
 payload.articles[0].title=hostile;payload.articles[0].summary=hostile;
 for(const key of ['general','coding','japanese','edge'])Object.assign(payload['ranking_'+key][0],{name:hostile,size:hostile,country:hostile,org:hostile,reason:hostile,badges:[hostile],score:0});
 await page.reload();await page.waitForFunction(()=>document.querySelector('#newsStatus').textContent.startsWith('データ更新日'));
 assert.equal(await page.evaluate(()=>window.pwned),undefined);assert.equal(await page.locator('#tickerTrack img, #rankGrid img, #ng img, #heroBox script').count(),0);
 assert.ok((await page.locator('#rankGrid').innerText()).includes(hostile));assert.equal(await page.locator('#rankGrid .rbar').first().evaluate(n=>n.style.width),'0%');
 // Invalid URLs and malformed nested schema reject the entire response; fallback remains.
 for(const url of ['javascript:alert(1)','data:text/html,hi','httpsx://example.com','//example.com','https://user:pass@example.com','https://example.com/\nonclick=x']){
  payload=structuredClone(fixture);payload.featured.url=url;await page.reload();await page.waitForFunction(()=>document.querySelector('#newsStatus').textContent.includes('失敗'));
  assert.equal(await page.locator('#rankGrid').innerText(),fallback);
 }
 for(const mutate of [d=>d.articles[0].date='2026.02.30',d=>d.ranking_edge[0].badges={},d=>d.ranking_general[0].score='90',d=>d.ticker=[{}],d=>delete d.ranking_japanese,d=>d.updated='2999.01.01']){
  payload=structuredClone(fixture);mutate(payload);await page.reload();await page.waitForFunction(()=>document.querySelector('#newsStatus').textContent.includes('失敗'));
  assert.equal(await page.locator('#rankGrid').innerText(),fallback);
 }
 // Initial fetch failure keeps fallback under pre-load selection; retry preserves selected tab.
 payload=structuredClone(fixture);fail=true;release=true;await page.reload();await page.getByRole('button',{name:'エッジAI用途'}).click();const go=release;release=null;go();
 await page.waitForFunction(()=>document.querySelector('#newsStatus').textContent.includes('失敗'));
 assert.equal(await page.locator('#rankGrid').innerText(),fallback);assert.match(await page.locator('.rtab.ac').innerText(),/エッジ/);
 fail=false;await page.getByRole('button',{name:'再読み込み'}).click();await page.waitForFunction(()=>document.querySelector('#newsStatus').textContent.startsWith('データ更新日'));
 assert.match(await page.locator('.rtab.ac').innerText(),/エッジ/);
 assert.ok((await page.locator('#rankGrid').innerText()).includes(fixture.ranking_edge[0].name));
 for(const name of ['通常用途','日本語用途','コーディング用途','エッジAI用途','通常用途'])await page.getByRole('button',{name,exact:false}).click();
 assert.ok((await page.locator('#rankGrid').innerText()).includes(fixture.ranking_general[0].name));
 await page.getByRole('button',{name:'2024',exact:true}).click();assert.equal(await page.locator('#ag .acard').count(),2);assert.equal(await page.locator('#ag a').count(),2);
 await page.waitForFunction(()=>document.querySelector('.hw-catalog-status').textContent.includes('確認済み'));
 await page.getByRole('button',{name:'通常用途',exact:false}).click();
 assert.equal(await page.locator('#rankGrid .hardware-guide').count(),8);
 assert.match(await page.locator('#rankGrid').innerText(),/DGX Spark/);
 assert.match(await page.locator('#rankGrid').innerText(),/重み公開待ち/);
 for(const width of [1280,390,320]) {
   await page.setViewportSize({width,height:900});
   for(const key of ['日本語用途','エッジAI用途','通常用途']) {
     await page.getByRole('button',{name:key,exact:false}).click();
     const summary=page.locator('#rankGrid .hw-details summary').first();
     await summary.click();assert.equal(await summary.evaluate(e=>e.parentElement.open),true);
     assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth), 'horizontal overflow at '+width);
     await summary.click();assert.equal(await summary.evaluate(e=>e.parentElement.open),false);
   }
 }
 console.log('PASS: safe text/URLs, complete schema, sorting, pre-load tab/failure/fallback/retry, repeated transitions, corrected archive years, hardware details and 320/390/1280px overflow ('+requests+' requests)');
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});

