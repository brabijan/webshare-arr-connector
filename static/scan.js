/* Sdílené vykreslování výsledků skenu Webshare (sezóna / celý seriál).
 * Pod každou epizodou ukáže více funkčních souborů; uživatel klikne ten,
 * který chce. Stahuje přes /api/confirm (pending confirmation z backendu).
 */
(function () {
  if (window.WebshareScan) return;

  const CSS = `
  .scan-bar{display:flex;gap:10px;align-items:center;margin:8px 0 24px;flex-wrap:wrap}
  .scan-btn{padding:10px 18px;background:#4CAF50;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:14px}
  .scan-btn:hover{background:#45a049}
  .scan-btn:disabled{background:#666;cursor:not-allowed}
  .scan-progress{color:#999;font-size:13px}
  .scan-season-h{margin:26px 0 12px;color:#fff;font-size:1.25em;border-bottom:1px solid #333;padding-bottom:6px}
  .scan-ep{background:#1a1a1a;border:1px solid #2c2c2c;border-radius:8px;padding:16px;margin-bottom:12px}
  .scan-ep-head{font-weight:bold;color:#fff;margin-bottom:4px}
  .scan-ep-num{color:#4CAF50}
  .scan-ep-empty{color:#888;font-size:13px;margin-top:6px}
  .scan-file{display:flex;justify-content:space-between;align-items:center;gap:12px;background:#242424;border-radius:6px;padding:10px 12px;margin-top:8px}
  .scan-file-info{flex:1;min-width:0}
  .scan-file-name{color:#fff;font-size:13px;word-break:break-word;margin-bottom:6px}
  .scan-meta{display:flex;flex-wrap:wrap;gap:6px}
  .scan-badge{padding:3px 7px;border-radius:4px;font-size:11px;font-weight:bold;color:#fff}
  .scan-badge.q{background:#2196F3}.scan-badge.cz{background:#FF5722}
  .scan-badge.l{background:#9C27B0}.scan-badge.s{background:#607D8B}
  .scan-badge.sc{background:#4CAF50}
  .scan-dl{padding:8px 14px;background:#4CAF50;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:13px;white-space:nowrap}
  .scan-dl:hover{background:#45a049}
  .scan-dl:disabled{background:#666;cursor:not-allowed}
  .scan-ep.done{border-color:#4CAF50;border-left:4px solid #4CAF50}
  .scan-done-msg{color:#4CAF50;font-size:13px;margin-top:8px}
  .scan-err{color:#f44336;font-size:13px;margin-top:8px}
  `;

  function injectCss() {
    if (document.getElementById('scan-css')) return;
    const s = document.createElement('style');
    s.id = 'scan-css';
    s.textContent = CSS;
    document.head.appendChild(s);
  }

  function esc(t) {
    const d = document.createElement('div');
    d.textContent = t == null ? '' : String(t);
    return d.innerHTML;
  }

  function pad(n) { return String(n).padStart(2, '0'); }

  function fileRow(season, ep, result, index) {
    const p = result.parsed || {};
    const sc = result.score || {};
    const meta = [];
    if (p.quality) meta.push(`<span class="scan-badge q">${esc(p.quality)}</span>`);
    if (p.has_czech) meta.push(`<span class="scan-badge cz">CZ</span>`);
    if (p.language) meta.push(`<span class="scan-badge l">${esc(p.language)}</span>`);
    if (result.file_size_gb) meta.push(`<span class="scan-badge s">${result.file_size_gb.toFixed(2)} GB</span>`);
    if (sc.total !== undefined) meta.push(`<span class="scan-badge sc">Score ${sc.total}</span>`);
    return `
      <div class="scan-file">
        <div class="scan-file-info">
          <div class="scan-file-name">${esc(result.name)}</div>
          <div class="scan-meta">${meta.join('')}</div>
        </div>
        <button class="scan-dl" data-pid="" data-idx="${index}">Stáhnout</button>
      </div>`;
  }

  function episodeBlock(season, ep) {
    const num = `S${pad(season)}E${pad(ep.episode_number)}`;
    const head = `<div class="scan-ep-head"><span class="scan-ep-num">${num}</span> — ${esc(ep.title || 'Bez názvu')}</div>`;
    if (!ep.results || ep.results.length === 0) {
      return `<div class="scan-ep"><div>${head}</div><div class="scan-ep-empty">Nic dostupného nenalezeno</div></div>`;
    }
    const rows = ep.results.map((r, i) => fileRow(season, ep, r, i)).join('');
    return `<div class="scan-ep" data-pid="${ep.pending_id || ''}">${head}${rows}</div>`;
  }

  async function doDownload(btn) {
    const epEl = btn.closest('.scan-ep');
    const pendingId = epEl && epEl.getAttribute('data-pid');
    const idx = parseInt(btn.getAttribute('data-idx'), 10);
    if (!pendingId) {
      btn.insertAdjacentHTML('afterend', '<div class="scan-err">Chybí pending_id</div>');
      return;
    }
    epEl.querySelectorAll('.scan-dl').forEach(b => { b.disabled = true; });
    btn.textContent = 'Odesílám…';
    try {
      const resp = await fetch('/api/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pending_id: parseInt(pendingId, 10), result_index: idx })
      });
      const data = await resp.json();
      if (data.success) {
        epEl.classList.add('done');
        const head = epEl.querySelector('.scan-ep-head').outerHTML;
        epEl.innerHTML = head +
          `<div class="scan-done-msg">✓ Odesláno do pyLoad (Package ID: ${esc(data.package_id)}) — ${esc(data.filename || '')}</div>`;
      } else {
        epEl.querySelectorAll('.scan-dl').forEach(b => { b.disabled = false; b.textContent = 'Stáhnout'; });
        btn.insertAdjacentHTML('afterend', `<div class="scan-err">Chyba: ${esc(data.error || 'nepodařilo se odeslat')}</div>`);
      }
    } catch (e) {
      epEl.querySelectorAll('.scan-dl').forEach(b => { b.disabled = false; b.textContent = 'Stáhnout'; });
      btn.insertAdjacentHTML('afterend', `<div class="scan-err">Chyba: ${esc(e.message)}</div>`);
    }
  }

  function bindDownloads(container) {
    container.querySelectorAll('.scan-dl').forEach(btn => {
      btn.addEventListener('click', () => doDownload(btn));
    });
  }

  /* payload: sezóna {season, episodes:[...]}  nebo  seriál {seasons:[{season,episodes}]} */
  function render(container, payload) {
    injectCss();
    let html = '';
    let total = 0, withResults = 0;

    const seasons = payload.seasons
      ? payload.seasons
      : [{ season: payload.season, episodes: payload.episodes || [] }];

    seasons.forEach(s => {
      if (payload.seasons) {
        html += `<h3 class="scan-season-h">Sezóna ${s.season}</h3>`;
      }
      (s.episodes || []).forEach(ep => {
        total++;
        if (ep.results && ep.results.length) withResults++;
        html += episodeBlock(s.season, ep);
      });
      if (!s.episodes || s.episodes.length === 0) {
        html += `<div class="scan-ep-empty">Žádné chybějící epizody</div>`;
      }
    });

    container.innerHTML =
      `<div class="scan-progress">Hotovo: ${withResults}/${total} epizod má dostupné soubory</div>` + html;
    bindDownloads(container);
  }

  window.WebshareScan = { render };

  // Nastyluj tlačítka hned (CSS je potřeba i před spuštěním skenu)
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectCss);
  } else {
    injectCss();
  }
})();
