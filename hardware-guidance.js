/* Reviewed hardware facts only. Generated news never supplies this catalog. */
(function (root) {
  'use strict';
  const labels = {estimated:'容量からの目安',vendor_documented:'メーカー対応情報',unreleased:'重み公開待ち',server_class:'サーバー級',platform_warning:'対応状況に注意'};
  const normalize = value => value.trim().toLowerCase().replace(/\s+/g,' ');
  const text = value => typeof value === 'string' && value.trim().length > 0;
  const list = (value, nonempty=true) => Array.isArray(value) && (!nonempty || value.length > 0) && value.every(text);
  function safeURL(value) {
    if (!text(value) || value !== value.trim() || /[\s\u0000-\u0020\u007f\\]/.test(value)) return null;
    try { const url = new URL(value); return ['http:','https:'].includes(url.protocol) && url.hostname && !url.username && !url.password ? url.href : null; }
    catch (_) { return null; }
  }
  function validateCatalog(data) {
    if (!data || Array.isArray(data) || data.version !== 1 || !Array.isArray(data.models)) throw new Error('Invalid hardware catalog');
    const aliases = new Set(), ids = new Set();
    for (const entry of data.models) {
      if (!entry || Array.isArray(entry) || !['id','quantization','memory','runtime','checked_at'].every(k=>text(entry[k])) ||
          !Object.hasOwn(labels,entry.status) || !list(entry.aliases) || !list(entry.examples,false) || !list(entry.conditions) ||
          !/^\d{4}-\d{2}-\d{2}$/.test(entry.checked_at) || !Number.isFinite(Date.parse(entry.checked_at)) ||
          new Date(entry.checked_at).toISOString().slice(0,10) !== entry.checked_at ||
          entry.checked_at > new Date().toISOString().slice(0,10) || !Array.isArray(entry.sources) || !entry.sources.length ||
          !entry.sources.every(s=>s && text(s.label) && safeURL(s.url))) throw new Error('Invalid hardware entry');
      for (const key of ['weight_gb','total_parameters_b','active_parameters_b']) {
        const value = entry[key];
        if (value !== null && (typeof value !== 'number' || !Number.isFinite(value) || value <= 0 || value > 1000000)) throw new Error('Invalid hardware number');
      }
      if (entry.active_parameters_b !== null && (entry.total_parameters_b === null || entry.active_parameters_b > entry.total_parameters_b)) throw new Error('Invalid active parameter count');
      if (ids.has(entry.id)) throw new Error('Duplicate hardware ID'); ids.add(entry.id);
      for (const alias of entry.aliases) {
        const key = normalize(alias); if (aliases.has(key)) throw new Error('Duplicate hardware alias'); aliases.add(key);
      }
    }
    return data;
  }
  function lookup(catalog,name) {
    if (!catalog || !text(name)) return null;
    const key = normalize(name);
    return catalog.models.find(entry=>entry.aliases.some(alias=>normalize(alias)===key)) || null;
  }
  function createBlock(doc,name,catalog) {
    const node = (tag,cls,value) => { const element=doc.createElement(tag); element.className=cls; if(value!==undefined)element.textContent=value; return element; };
    const entry=lookup(catalog,name), block=node('section','hardware-guide');
    block.setAttribute('aria-label','ローカル実行の目安');
    const header=node('div','hw-heading'); header.append(node('span','hw-title','PC・メモリの目安'),node('span','hw-status',entry?labels[entry.status]:'確認中')); block.append(header);
    if (!entry) {
      block.append(node('p','hw-memory','このモデルの動作条件は未確認です。'),node('p','hw-note','パラメータ数だけで必要メモリや速度は判断できません。')); return block;
    }
    block.dataset.status=entry.status;
    block.append(node('p','hw-memory',entry.memory));
    for (const example of entry.examples) block.append(node('p','hw-example',example));
    const details=node('details','hw-details'); details.append(node('summary','','量子化・条件・出典'));
    details.append(node('p','','量子化: '+entry.quantization));
    if (entry.weight_gb !== null) details.append(node('p','','モデル重みのみ: 約'+entry.weight_gb+'GB（実行時の総メモリではありません）'));
    if (entry.total_parameters_b !== null) details.append(node('p','','総パラメータ: '+entry.total_parameters_b+'B'+(entry.active_parameters_b!==null?' ／ アクティブ: '+entry.active_parameters_b+'B':'')));
    details.append(node('p','','ランタイム: '+entry.runtime));
    const conditions=node('ul','hw-conditions'); entry.conditions.forEach(value=>conditions.append(node('li','',value))); details.append(conditions);
    details.append(node('p','hw-date','資料確認日: '+entry.checked_at+' ／ 当サイトによる速度の実測なし'));
    const sources=node('ul','hw-sources'); entry.sources.forEach(source=>{ const item=node('li',''),a=node('a','',source.label); a.href=safeURL(source.url);a.target='_blank';a.rel='noopener noreferrer';item.append(a);sources.append(item); }); details.append(sources);block.append(details);return block;
  }
  const api={validateCatalog,lookup,createBlock};
  if(typeof module!=='undefined' && module.exports)module.exports=api;
  else root.HardwareGuidance=api;
})(typeof window!=='undefined'?window:globalThis);
