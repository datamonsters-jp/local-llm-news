/* Treat all generated content as text. No generated value is parsed as HTML. */
(function () {
  'use strict';
  const keys = ['general', 'coding', 'japanese', 'edge'];
  const tags = {model:'tmodel', tool:'ttool', hw:'thw', research:'tresearch', trend:'ttrend'};
  const colors = ['cyan','purple','green','yellow','orange','pink'];
  const grid = document.getElementById('rankGrid');
  const fallback = Array.from(grid.children, n => n.cloneNode(true));
  const tabs = Array.from(document.querySelectorAll('.rtab'));
  const state = {selected:'general', data:null, pending:false, failed:false};
  const status = document.createElement('p');
  status.id = 'newsStatus'; status.className = 'rank-legend'; status.setAttribute('role', 'status');
  const retry = document.createElement('button');
  retry.type = 'button'; retry.className = 'fb'; retry.textContent = '再読み込み';
  grid.before(status, retry);
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
  function rankCard(m, i) {
    const card = node('div','rc '+(i<3?'r'+(i+1):'ro'));
    const head = node('div','rh'), names = node('div','rnw'), name = node('div','rname');
    name.append(link(m.url,'',m.name)); names.append(name);
    const org = node('div','rorg');
    // Clone only trusted inline SVG flags from the original static cards.
    if (flags[m.flag]) { const flag = node('div','rflag'); flag.append(flags[m.flag].cloneNode(true)); org.append(flag); }
    org.append(node('span','rcountry',m.country+' · '+m.org)); names.append(org);
    const released = node('div','rdate','📅 '); released.append(node('b','',m.released+' リリース')); names.append(released);
    head.append(node('div','rnum',['🥇','🥈','🥉'][i] || '#'+(i+1)),names,node('div','rsize',m.size));
    const bg = node('div','rbar-bg'), bar = node('div','rbar'); bar.style.width = m.score+'%'; bg.append(bar);
    const meta = node('div','rmeta'); meta.append(node('span','rscore','SCORE '+m.score),node('span','rreason',m.reason));
    const badges = node('div','rbadges'); m.badges.forEach(b=>badges.append(node('span','rbadge',b)));
    card.append(head,bg,meta,badges); return card;
  }
  const flags = {};
  fallback.forEach(card => {
    const country = card.querySelector('.rcountry'), svg = card.querySelector('.rflag svg');
    if (country && svg) { const key = {'中国':'cn','米国':'us','仏国':'fr','日本':'jp'}[country.textContent.split(' · ')[0]]; if (key) flags[key] = svg; }
  });
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
  retry.addEventListener('click',load);
  load();
})();
