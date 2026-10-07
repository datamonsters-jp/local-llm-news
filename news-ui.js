/* Treat all generated content as text. No generated value is parsed as HTML. */
(function () {
  'use strict';
  const keys = ['general', 'coding', 'japanese', 'edge'];
  const tags = {model:'tmodel', tool:'ttool', hw:'thw', research:'tresearch', trend:'ttrend'};
  const colors = ['cyan','purple','green','yellow','orange','pink'];
  const grid = document.getElementById('rankGrid');
  const fallback = Array.from(grid.children, n => n.cloneNode(true));
  const tabs = Array.from(document.querySelectorAll('.rtab'));
  const state = {selected:'general', data:null, pending:false, failed:false, hardware:null};
  const status = document.createElement('p');
  status.id = 'newsStatus'; status.className = 'rank-legend'; status.setAttribute('role', 'status');
  const retry = document.createElement('button');
  retry.type = 'button'; retry.className = 'fb'; retry.textContent = '再読み込み';
  grid.before(status, retry);
  const hardwareStatus = document.createElement('p');
  hardwareStatus.className = 'hw-catalog-status'; hardwareStatus.setAttribute('role','status');
  const hardwareRetry = document.createElement('button');
  hardwareRetry.type='button'; hardwareRetry.className='hw-retry'; hardwareRetry.textContent='目安を再読み込み'; hardwareRetry.hidden=true;
  grid.before(hardwareStatus, hardwareRetry);
  function node(tag, cls, value) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (value !== undefined) e.textContent = value;
    return e;
  }
  function safeURL(value) {
    if (typeof value !== 'string' || value !== value.trim() || /[\s\u0000-\u0020\u007f\\]/.test(value)) return null;
    try {
      const u = new URL(value);
      return ['http:', 'https:'].includes(u.protocol) && u.hostname && !u.username && !u.password ? u.href : null;
    } catch (_) { return null; }
  }
  function link(value, cls, label) {
    const href = safeURL(value);
    if (!href) return node('span', cls, label);
    const a = node('a', cls, label); a.href = href; a.target = '_blank'; a.rel = 'noopener noreferrer'; return a;
  }
  function date(value, month) {
    if (typeof value !== 'string' || !(month ? /^\d{4}\.\d{2}$/ : /^\d{4}\.\d{2}\.\d{2}$/).test(value)) return false;
    const [y,m,d=1] = value.split('.').map(Number);
    const dt = new Date(Date.UTC(y,m-1,d));
    return y >= 1000 && dt.getUTCFullYear() === y && dt.getUTCMonth() === m-1 && dt.getUTCDate() === d;
  }
  function text(v, empty=false) { return typeof v === 'string' && (empty || v.trim().length > 0); }
  function article(a, updated) {
    return a && typeof a === 'object' && !Array.isArray(a) && Object.hasOwn(tags,a.tag) && date(a.date) && a.date <= updated && text(a.title) && text(a.summary) && safeURL(a.url);
  }
  function model(m, updated) {
    return m && typeof m === 'object' && !Array.isArray(m) && ['name','size','country','org','reason'].every(k => text(m[k])) &&
      typeof m.score === 'number' && Number.isFinite(m.score) && m.score >= 0 && m.score <= 100 &&
      // Preserve legacy year-only release precision; the updater requires YYYY.MM.
      (date(m.released,true) || (typeof m.released === 'string' && /^[1-9]\d{3}$/.test(m.released))) && m.released <= updated.slice(0,7) && ['', 'cn','us','fr','jp'].includes(m.flag) &&
      Array.isArray(m.badges) && m.badges.every(b => text(b)) && (m.url === '' || safeURL(m.url));
  }
  function validate(d) {
    const today = new Intl.DateTimeFormat('en-CA', {timeZone:'Asia/Tokyo',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date()).replaceAll('-','.');
    if (!d || Array.isArray(d) || !date(d.updated) || d.updated > today || !Array.isArray(d.ticker) || !d.ticker.length || !d.ticker.every(x => text(x)) ||
      !keys.every(k => Array.isArray(d['ranking_'+k]) && d['ranking_'+k].every(m => model(m,d.updated))) ||
      !article(d.featured,d.updated) || !Array.isArray(d.articles) || !d.articles.length || !d.articles.every(a => article(a,d.updated))) throw new Error('Invalid news schema');
    return d;
  }
  // Generated prose is not a source of hardware guidance. Hide the whole
  // hardware-related reason/badge; never guess a replacement specification.
  // This display policy does not reject an otherwise valid daily update.
  const generatedHardwareClaim = /(?:[0-9０-９]+(?:[.,][0-9０-９]+)?\s*(?:[KMGT]i?B|ＧＢ|ギガバイト|t\s*\/\s*s\b))|(?:RAM|VRAM|GPU|CPU|NPU|Mac|DGX|RTX|PC|メモリ|高速|快適|サクサク|スマホ|ラズパイ|ノートパソコン|毎秒|tokens?\s*(?:\/|per)\s*s|トークン\s*\/\s*秒)/i;
  const safeReason = value => generatedHardwareClaim.test(value) ? 'ローカル実行の条件は、下のPC・メモリの目安をご確認ください。' : value;
  function rankCard(m, i) {
    const card = node('div','rc '+(i<3?'r'+(i+1):'ro'));
    const head = node('div','rh'), names = node('div','rnw'), name = node('div','rname');
    name.append(link(m.url,'',m.name)); names.append(name);
    const org = node('div','rorg');
    // Flags are built only from fixed local SVG data, never generated markup.
    if (flags[m.flag]) { const flag = node('div','rflag'); flag.append(flags[m.flag].cloneNode(true)); org.append(flag); }
    org.append(node('span','rcountry',m.country+' · '+m.org)); names.append(org);
    const released = node('div','rdate','📅 '); released.append(node('b','',m.released+' リリース')); names.append(released);
    head.append(node('div','rnum',['🥇','🥈','🥉'][i] || '#'+(i+1)),names,node('div','rsize',m.size));
    const bg = node('div','rbar-bg'), bar = node('div','rbar'); bar.style.width = m.score+'%'; bg.append(bar);
    const meta = node('div','rmeta'); meta.append(node('span','rscore','SCORE '+m.score),node('span','rreason',safeReason(m.reason)));
    const badges = node('div','rbadges'); m.badges.filter(b=>!generatedHardwareClaim.test(b)).forEach(b=>badges.append(node('span','rbadge',b)));
    card.append(head,bg,meta,badges);
    if(window.HardwareGuidance) card.append(window.HardwareGuidance.createBlock(document,m.name,state.hardware));
    else card.append(node('p','hardware-guide','PC・メモリの目安: 確認中（動作条件は未確認です）'));
    return card;
  }
  function flagSVG(shapes) {
    const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 30 20');
    svg.setAttribute('aria-hidden', 'true');
    shapes.forEach(([tag, attributes]) => {
      const shape = document.createElementNS('http://www.w3.org/2000/svg', tag);
      Object.entries(attributes).forEach(([name, value]) => shape.setAttribute(name, value));
      svg.append(shape);
    });
    return svg;
  }
  // Independent of which countries happen to appear in the saved ranking.
  const flags = {
    cn: flagSVG([
      ['rect', {width:30, height:20, fill:'#DE2910'}],
      ['polygon', {points:'5,2 6.18,5.09 9.51,5.09 6.84,7.05 7.82,10.18 5,8.5 2.18,10.18 3.16,7.05 0.49,5.09 3.82,5.09', fill:'#FFDE00'}]
    ]),
    us: flagSVG([
      ['rect', {width:30, height:20, fill:'#fff'}],
      ...[0,3.08,6.15,9.23,12.31,15.38,18.46].map(y => ['rect', {width:30, height:1.54, y, fill:'#B22234'}]),
      ['rect', {width:12, height:10.77, fill:'#3C3B6E'}]
    ]),
    fr: flagSVG([
      ['rect', {width:30, height:20, fill:'#ED2939'}],
      ['rect', {width:20, height:20, fill:'#fff'}],
      ['rect', {width:10, height:20, fill:'#002395'}]
    ]),
    jp: flagSVG([
      ['rect', {width:30, height:20, fill:'#fff'}],
      ['circle', {cx:15, cy:10, r:6, fill:'#BC002D'}]
    ])
  };
  function notice() {
    let message = state.pending ? '最新データを読み込み中。現在の保存データを表示しています。' :
      state.failed ? '最新データの取得に失敗しました。現在の保存データを表示しています。' : 'データ更新日: '+state.data.updated+'（現在の情報と異なる場合があります）';
    if (!state.data && state.selected !== 'general') message += ' 選択した用途の保存データがないため、通常用途の保存データを表示しています。';
    status.textContent = message;
    retry.disabled = state.pending; retry.hidden = !state.failed;
  }
  function renderRanking() {
    tabs.forEach((b,i)=>{b.classList.toggle('ac',keys[i]===state.selected);b.setAttribute('aria-pressed',String(keys[i]===state.selected));});
    if (!state.data) grid.replaceChildren(...fallback.map(n=>n.cloneNode(true)));
    else {
      const list = state.data['ranking_'+state.selected];
      grid.replaceChildren(...(list.length ? list.map(rankCard) : [node('div','empty','// この用途のデータはありません //')]));
    }
    notice();
  }
  window.rankTab = function (_,key) { if (keys.includes(key)) { state.selected=key; renderRanking(); } };
  function newsCard(a,i,featured=false) {
    const card = node('div',featured?'':'nc '+colors[i%colors.length]); card.dataset.t = a.tag;
    const meta = node('div',featured?'hmeta':'cmeta'); meta.append(node('span','tag '+tags[a.tag],a.tag.toUpperCase()),node('span','ndate',a.date));
    card.append(meta,node('h3','',a.title),node('p','',a.summary),link(a.url,featured?'rdmore':'clink','READ MORE →')); return card;
  }
  function apply(d) {
    document.getElementById('hdrDate').textContent = '// '+d.updated+' UPDATE //';
    document.getElementById('ftxt').textContent = '© 2026 — 最終更新: '+d.updated+' // ローカルLLMの最前線をお届け';
    const ticker = document.getElementById('tickerTrack'); ticker.replaceChildren();
    [...d.ticker,...d.ticker].forEach(t => ticker.append(node('span','ti',t),node('span','ts',' ★ ')));
    document.getElementById('heroBox').replaceChildren(...newsCard(d.featured,0,true).childNodes);
    const cards = d.articles.slice().sort((a,b)=>b.date.localeCompare(a.date)).map((a,i)=>newsCard(a,i));
    cards.forEach(c => { c.style.display = window.selectedNewsTag === 'all' || c.dataset.t === window.selectedNewsTag ? '' : 'none'; });
    document.getElementById('ng').replaceChildren(...cards);
  }
  async function load() {
    if (state.pending) return;
    state.pending=true; state.failed=false; renderRanking();
    const controller = new AbortController(), timer = setTimeout(()=>controller.abort(),15000);
    try {
      const response = await fetch('news.json?v='+Date.now(),{signal:controller.signal});
      if (!response.ok) throw new Error('News request failed');
      const data = validate(await response.json());
      apply(data); state.data=data;
    } catch (_) { state.failed=true; }
    finally { clearTimeout(timer);state.pending=false;renderRanking(); }
  }
  let hardwarePending=false;
  async function loadHardware() {
    if(hardwarePending || !window.HardwareGuidance)return;
    hardwarePending=true;hardwareRetry.disabled=true;hardwareRetry.hidden=true;
    hardwareStatus.textContent='PC・メモリの資料を読み込み中…';
    const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),10000);
    try {
      const response=await fetch('hardware-guidance.json',{signal:controller.signal});
      if(!response.ok)throw new Error('Hardware request failed');
      state.hardware=window.HardwareGuidance.validateCatalog(await response.json());
      hardwareStatus.textContent='PCの目安は確認済みの資料から別途管理しています。未登録モデルは「確認中」と表示します。';
    } catch(_) {
      hardwareStatus.textContent='PCの目安を取得できませんでした。ニュースは引き続き表示できます。';hardwareRetry.hidden=false;
    } finally {clearTimeout(timer);hardwarePending=false;hardwareRetry.disabled=false;renderRanking();}
  }
  hardwareRetry.addEventListener('click',loadHardware);
  if(window.HardwareGuidance)loadHardware();
  else hardwareStatus.textContent='PCの目安は現在利用できません。ニュースは引き続き表示できます。';
  retry.addEventListener('click',load);
  load();
})();

