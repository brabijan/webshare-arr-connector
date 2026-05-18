/* Sdílené vykreslování výsledků skenu Webshare (sezóna / celý seriál).
 * Streamuje průběh přes Server-Sent Events: progress bar + epizody se
 * plní průběžně, jak jsou hotové. Pod každou epizodou je víc funkčních
 * souborů; stahuje se přes /api/confirm.
 */
(function () {
  if (window.WebshareScan) return;

  const CSS = `
  .scan-bar{display:flex;gap:10px;align-items:center;margin:8px 0 24px;flex-wrap:wrap}
  .scan-btn{padding:10px 18px;background:#4CAF50;color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:14px}
  .scan-btn:hover{background:#45a049}
  .scan-btn:disabled{background:#666;cursor:not-allowed}
  .scan-progress{color:#999;font-size:13px}
  .scan-pwrap{margin:6px 0 22px}
  .scan-pbar{height:14px;background:#2a2a2a;border-radius:7px;overflow:hidden;border:1px solid #333}
  .scan-pbar-fill{height:100%;width:0;background:#4CAF50;transition:width .25s ease}
  .scan-pstat{margin-top:6px;color:#bbb;font-size:13px}
  .scan-pstat.done{color:#4CAF50}.scan-pstat.err{color:#f44336}
  .scan-season-h{margin:26px 0 12px;color:#fff;font-size:1.25em;border-bottom:1px solid #333;padding-bottom:6px}
  .scan-ep{background:#1a1a1a;border:1px solid #2c2c2c;border-radius:8px;padding:16px;margin-bottom:12px}
  .scan-ep.none{opacity:.65}
  .scan-ep-head{font-weight:bold;color:#fff;margin-bottom:4px}
  .scan-ep-num{color:#4CAF50}
  .scan-ep-empty{color:#888;font-size:13px;margin-top:6px}
  .scan-ep-wait{color:#999;font-size:13px;margin-top:6px}
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

  function epKey(season, epnum) { return `scan-ep-${season}-${epnum}`; }

  function headHtml(season, epnum, title) {
    return `<div class="scan-ep-head"><span class="scan-ep-num">S${pad(season)}E${pad(epnum)}</span> — ${esc(title || 'Bez názvu')}</div>`;
  }

  function fileRow(result, index) {
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
        <button class="scan-dl" data-idx="${index}">Stáhnout</button>
      </div>`;
  }

  function episodeInner(season, ep) {
    const head = headHtml(season, ep.episode_number, ep.title);
    if (!ep.results || ep.results.length === 0) {
      return head + `<div class="scan-ep-empty">Nic dostupného nenalezeno</div>`;
    }
    return head + ep.results.map((r, i) => fileRow(r, i)).join('');
  }

  function placeholderInner(season, epnum, title) {
    return headHtml(season, epnum, title) + `<div class="scan-ep-wait">⏳ skenuji…</div>`;
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
        const head = epEl.querySelector('.scan-ep-head').outerHTML;
        epEl.classList.add('done');
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

  function bindDownloads(root) {
    root.querySelectorAll('.scan-dl').forEach(btn => {
      if (btn._bound) return;
      btn._bound = true;
      btn.addEventListener('click', () => doDownload(btn));
    });
  }

  /* Streamovaný sken s progress barem.
   * url: /api/scan-season-stream?... nebo /api/scan-series-stream?...
   * onEnd: volitelný callback po dokončení/chybě (pro re-enable tlačítka)
   */
  function stream(url, container, onEnd) {
    injectCss();
    container.innerHTML = '';

    const wrap = document.createElement('div');
    wrap.className = 'scan-pwrap';
    wrap.innerHTML =
      `<div class="scan-pbar"><div class="scan-pbar-fill"></div></div>` +
      `<div class="scan-pstat">Připravuji…</div>`;
    container.appendChild(wrap);
    const body = document.createElement('div');
    container.appendChild(body);

    const fill = wrap.querySelector('.scan-pbar-fill');
    const stat = wrap.querySelector('.scan-pstat');

    let total = 0, done = 0, withRes = 0, finished = false;
    const es = new EventSource(url);

    const finish = (cls, msg) => {
      finished = true;
      try { es.close(); } catch (_) {}
      stat.textContent = msg;
      if (cls) stat.classList.add(cls);
      if (typeof onEnd === 'function') onEnd();
    };

    es.onmessage = (e) => {
      let m;
      try { m = JSON.parse(e.data); } catch (_) { return; }

      if (m.type === 'start') {
        total = m.total || 0;
        const multi = (m.seasons || []).length > 1;
        (m.seasons || []).forEach(s => {
          if (multi) {
            const h = document.createElement('h3');
            h.className = 'scan-season-h';
            h.textContent = `Sezóna ${s.season}`;
            body.appendChild(h);
          }
          (s.episodes || []).forEach(ep => {
            const d = document.createElement('div');
            d.className = 'scan-ep';
            d.id = epKey(s.season, ep.episode_number);
            d.innerHTML = placeholderInner(s.season, ep.episode_number, ep.title);
            body.appendChild(d);
          });
        });
        fill.style.width = total ? '0%' : '100%';
        stat.textContent = total ? `0 / ${total} epizod` : 'Žádné chybějící epizody ke stažení';
        if (total === 0) finish('done', 'Žádné chybějící epizody ke stažení');

      } else if (m.type === 'episode') {
        const ep = m.episode;
        done = m.done || (done + 1);
        const el = document.getElementById(epKey(m.season, ep.episode_number));
        const hasRes = ep.results && ep.results.length > 0;
        if (hasRes) withRes++;
        if (el) {
          el.setAttribute('data-pid', ep.pending_id || '');
          el.innerHTML = episodeInner(m.season, ep);
          el.classList.add(hasRes ? 'has' : 'none');
          bindDownloads(el);
        }
        fill.style.width = (total ? Math.round(done / total * 100) : 100) + '%';
        stat.textContent = `${done} / ${total} epizod  •  ${withRes} s dostupnými soubory`;

      } else if (m.type === 'done') {
        fill.style.width = '100%';
        finish('done', `Hotovo: ${withRes} z ${total} epizod má dostupné soubory`);

      } else if (m.type === 'error') {
        finish('err', 'Chyba: ' + (m.error || 'sken selhal'));
      }
    };

    es.onerror = () => {
      if (finished) return;
      finish('err', 'Spojení přerušeno (sken mohl proběhnout jen částečně).');
    };

    return es;
  }

  window.WebshareScan = { stream };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', injectCss);
  } else {
    injectCss();
  }
})();
