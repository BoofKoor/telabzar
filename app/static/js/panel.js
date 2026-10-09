/* Telabzar admin panel — progressive enhancement over server-rendered pages.
   Every page works without this file (forms post, links navigate); this adds charts,
   menus, dialogs, sheets, live save bars, the button editor and the sign-in code boxes.
   No inline handlers anywhere: everything is bound here by delegation, so the CSP can
   stay `script-src 'self'`. Numbers inside the page arrive pre-formatted from Python
   (app/panel_fmt.py); only chart axis ticks are formatted here, with Intl. */
(function () {
  'use strict';
  const doc = document, root = doc.documentElement;
  root.classList.add('js');
  const LANG = root.lang === 'en' ? 'en' : 'fa';
  const RTL = root.dir === 'rtl';
  const $ = (s, r) => (r || doc).querySelector(s);
  const $$ = (s, r) => Array.from((r || doc).querySelectorAll(s));
  const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const debounce = (fn, ms) => { let h; return (...a) => { clearTimeout(h); h = setTimeout(() => fn(...a), ms); }; };
  const clamp = (x, a, b) => Math.max(a, Math.min(b, x));
  const NF = new Intl.NumberFormat(LANG === 'fa' ? 'fa-IR' : 'en-US', { maximumFractionDigits: 0 });
  const num = (x) => NF.format(x);
  const toLatin = (s) => String(s).replace(/[۰-۹]/g, (c) => '۰۱۲۳۴۵۶۷۸۹'.indexOf(c)).replace(/[٠-٩]/g, (c) => '٠١٢٣٤٥٦٧٨٩'.indexOf(c));
  // This file runs in <head> (so `html.js` is set before the first paint), which is before
  // <body> exists: the sprite URL and the string table are read lazily, on first use.
  let spriteUrl = '', strings = null;
  const SPRITE = () => spriteUrl || (spriteUrl = (doc.body && doc.body.dataset.sprite) || '/static/icons.svg');
  const T = () => strings || (strings = (() => { try { return JSON.parse(($('#panel-i18n') || {}).textContent || '{}'); } catch (e) { return {}; } })());
  const t = (k, vars) => { let s = T()[k] || k; if (vars) s = s.replace(/\{(\w+)\}/g, (m, n) => (vars[n] != null ? vars[n] : m)); return s; };
  const ic = (name, cls) => `<svg class="ic${cls ? ' ' + cls : ''}" aria-hidden="true"><use href="${SPRITE()}#i-${name}"></use></svg>`;

  /* ── toast ── */
  function toast(text, icon) {
    let w = $('.toast-wrap');
    if (!w) { w = doc.createElement('div'); w.className = 'toast-wrap'; w.setAttribute('aria-live', 'polite'); doc.body.appendChild(w); }
    const el = doc.createElement('div'); el.className = 'toast'; el.innerHTML = ic(icon || 'circle-check') + esc(text);
    w.appendChild(el);
    setTimeout(() => el.remove(), 2800);
  }

  /* ── theme: cookie + data-theme, no reload; charts read CSS variables so they repaint by themselves ── */
  function isDark() { const th = root.dataset.theme; return th ? th === 'dark' : matchMedia('(prefers-color-scheme: dark)').matches; }
  function setTheme(th) {
    root.dataset.theme = th;
    doc.cookie = `tab_theme=${th}; max-age=${365 * 86400}; path=/; samesite=lax`;
    $$('[data-theme-icon]').forEach((u) => u.setAttribute('href', `${SPRITE()}#i-${th === 'dark' ? 'sun' : 'moon'}`));
    $$('input[data-theme-switch]').forEach((i) => { i.checked = th === 'dark'; });
  }

  /* ── dropdowns (<details class="dd">) ── */
  function closeDropdowns(except) {
    $$('details.dd[open]').forEach((d) => { if (d !== except && !d.contains(except)) d.removeAttribute('open'); });
  }
  doc.addEventListener('toggle', (e) => {
    const d = e.target;
    if (!(d instanceof HTMLDetailsElement) || !d.classList.contains('dd') || !d.open) return;
    closeDropdowns(d);
    const menu = d.querySelector(':scope > .menu');
    if (!menu) return;
    d.classList.remove('start', 'up');
    const r = menu.getBoundingClientRect();
    if (r.left < 8 || r.right > innerWidth - 8) d.classList.add('start');
    if (r.bottom > innerHeight - 8 && d.getBoundingClientRect().top > r.height + 16) d.classList.add('up');
  }, true);

  /* ── dialogs (<dialog class="dialog">) and the shared confirm ── */
  function openDialog(id, from) {
    const d = doc.getElementById(id);
    if (!d || typeof d.showModal !== 'function') return false;
    closeDropdowns();
    d._back = from || doc.activeElement;
    if (from) {   // a row menu may pass values into the dialog's fields
      for (const [k, v] of Object.entries(from.dataset)) {
        if (!k.startsWith('fill')) continue;
        const name = k.slice(4).replace(/^./, (c) => c.toLowerCase());
        $$(`[data-fill="${name}"]`, d).forEach((el) => { if ('value' in el && el.tagName !== 'BUTTON') el.value = v; else el.textContent = v; });
      }
    }
    d.showModal();
    focusIn(d);
    return true;
  }
  // with a keyboard, start on the first field; on a touch screen focus the dialog itself,
  // so the keyboard does not pop up over it and the close button does not wear a focus ring
  function focusIn(d) {
    const f = matchMedia('(hover: hover)').matches && ($('[autofocus]', d) || $('input:not([type=hidden]),select,textarea', d));
    if (f) { f.focus(); return; }
    d.tabIndex = -1;
    d.focus({ preventScroll: true });
  }
  doc.addEventListener('click', (e) => {
    const d = e.target;
    if (d instanceof HTMLDialogElement && d.open) {   // a click on the backdrop lands on the dialog itself
      const r = d.getBoundingClientRect();
      if (e.clientX < r.left || e.clientX > r.right || e.clientY < r.top || e.clientY > r.bottom) d.close();
    }
  });
  doc.addEventListener('close', (e) => {
    const d = e.target;
    if (d instanceof HTMLDialogElement && d._back && d._back.focus) d._back.focus({ preventScroll: true });
  }, true);
  function confirmThen(opts, go) {
    const d = $('#confirm-dlg');
    if (!d) { if (window.confirm(opts.text || opts.title)) go(); return; }
    $('[data-c-title]', d).textContent = opts.title || '';
    $('[data-c-text]', d).textContent = opts.text || '';
    const ok = $('[data-c-ok]', d);
    ok.textContent = opts.ok || t('c.confirm');
    ok.className = 'btn ' + (opts.danger ? 'btn-danger-solid' : 'btn-primary');
    ok.onclick = () => { d.close(); go(); };
    d.showModal();
    ok.focus();
  }
  doc.addEventListener('submit', (e) => {
    const f = e.target;
    if (f.dataset.confirm != null && !f._confirmed) {
      e.preventDefault();
      confirmThen({ title: f.dataset.confirm, text: f.dataset.confirmText, ok: f.dataset.confirmOk, danger: f.dataset.danger != null },
        () => { f._confirmed = true; if (f.requestSubmit) f.requestSubmit(e.submitter || undefined); else f.submit(); });
      return;
    }
    if (f.dataset.onlyChanged != null) {        // texts: post only the fields that changed
      $$('textarea[data-tx]', f).forEach((el) => { if (el.value === el.defaultValue) el.disabled = true; });
    }
    const b = e.submitter;
    if (b && b.dataset.skip) {                    // e.g. «download the file» must not send a pasted pack in the URL
      const off = $$(b.dataset.skip.split(',').map((n) => `[name="${n.trim()}"]`).join(','), f).filter((x) => !x.disabled);
      off.forEach((x) => { x.disabled = true; });
      setTimeout(() => off.forEach((x) => { x.disabled = false; }), 500);
    }
    if (b && b.dataset.busy) { b._html = b.innerHTML; b.disabled = true; b.innerHTML = `<span class="spinner"></span>${esc(b.dataset.busy)}`; }
  });
  // Back/forward cache restores the page as it was at the moment of submitting: give the
  // busy buttons and the fields we disabled for that one submission back to the user.
  addEventListener('pageshow', (e) => {
    if (!e.persisted) return;
    $$('button[data-busy]').forEach((b) => { if (b._html != null) { b.innerHTML = b._html; b.disabled = false; b._html = null; } });
    $$('textarea[data-tx][disabled]').forEach((el) => { el.disabled = false; });
  });

  /* ── sheets: a row or link fetches an HTML fragment and slides it in ── */
  async function openSheet(href) {
    let host = $('#sheet-host');
    if (!host) { host = doc.createElement('div'); host.id = 'sheet-host'; doc.body.appendChild(host); }
    const url = new URL(href, location.href);
    url.searchParams.set('frag', '1');
    let html;
    try {
      const r = await fetch(url, { credentials: 'same-origin', headers: { 'X-Requested-With': 'fetch' } });
      if (r.redirected && new URL(r.url).pathname === '/login') { location.href = '/login'; return; }
      if (!r.ok) throw new Error(r.status);
      html = await r.text();
    } catch (err) { location.href = href; return; }
    host.innerHTML = `<div class="backdrop" data-sheet-close></div>${html}`;
    host._back = doc.activeElement;
    const sh = $('.sheet', host);
    if (sh) { sh.setAttribute('tabindex', '-1'); sh.focus({ preventScroll: true }); }
    mount(host);
  }
  function closeSheet() {
    const host = $('#sheet-host');
    if (!host || !host.innerHTML) return false;
    if (host.dataset.static != null) {           // server-rendered (?open=…): drop the parameter
      const u = new URL(location.href); u.searchParams.delete('open'); u.searchParams.delete('job'); u.searchParams.delete('dl');
      history.replaceState(null, '', u);
      delete host.dataset.static;
    }
    host.innerHTML = '';
    if (host._back && host._back.focus) host._back.focus({ preventScroll: true });
    return true;
  }

  /* ── copy ── */
  function copy(text, from) {
    const manual = () => {
      const scope = (from && from.closest('.sheet, .dialog, .card')) || doc.body;
      const box = $$('.codebox, .mono, bdi', scope).find((x) => x.textContent.trim() === String(text).trim());
      if (box) { const rg = doc.createRange(); rg.selectNodeContents(box); const s = getSelection(); s.removeAllRanges(); s.addRange(rg); }
      toast(t('c.copy_manual'), 'copy');
    };
    try { navigator.clipboard.writeText(String(text)).then(() => toast(t('c.copied'), 'copy'), manual); } catch (e) { manual(); }
  }

  /* ── charts: plain SVG sized to the container, redrawn on resize ──
     thin columns (<=24px) with a 4px rounded data-end, square at the baseline; 2px surface
     gap between stacked segments; recessive grid; hatched fill for the partial bucket;
     per-column tooltip + keyboard; every chart has a table view beside it. */
  const NS = 'http://www.w3.org/2000/svg';
  function niceScale(v) {
    v = Math.max(1, v);
    const e = Math.pow(10, Math.floor(Math.log10(v)));
    let best = null;
    for (const k of [e / 100, e / 10, e, e * 10]) for (const m of [1, 2, 2.5, 5]) {
      const step = m * k;
      if (step < 1 || !Number.isInteger(step)) continue;
      const n = Math.ceil(v / step);
      if (n < 2 || n > 5) continue;
      if (!best || step * n < best.max || (step * n === best.max && Math.abs(n - 4) < Math.abs(best.n - 4))) best = { max: step * n, n, step };
    }
    if (!best) best = { max: v <= 1 ? 1 : 2, n: v <= 1 ? 1 : 2, step: 1 };
    return { max: best.max, ticks: Array.from({ length: best.n + 1 }, (_, i) => i * best.step) };
  }
  function colTop(x, y, w, h, r) {
    r = Math.min(r, w / 2, h);
    if (h <= 0) return '';
    return `M${x},${y + h}V${y + r}Q${x},${y} ${x + r},${y}H${x + w - r}Q${x + w},${y} ${x + w},${y + r}V${y + h}Z`;
  }
  function rect(x, y, w, h) { return h <= 0 ? '' : `M${x},${y}h${w}v${h}h${-w}Z`; }
  let tipEl;
  function tip(html, x, y) {
    if (!tipEl) { tipEl = doc.createElement('div'); tipEl.className = 'tip pop'; tipEl.setAttribute('role', 'status'); doc.body.appendChild(tipEl); }
    if (html == null) { tipEl.style.display = 'none'; return; }
    tipEl.innerHTML = html; tipEl.style.display = 'block';
    const r = tipEl.getBoundingClientRect();
    let left = x + 14, top = y - r.height - 12;
    if (left + r.width > innerWidth - 8) left = x - r.width - 14;
    if (left < 8) left = 8;
    if (top < 8) top = y + 16;
    tipEl.style.left = left + 'px'; tipEl.style.top = top + 'px';
  }
  let uid = 0;
  function columns(el, spec) {
    const W = Math.max(240, el.clientWidth);
    const mini = !!spec.mini;
    const H = spec.height || (mini ? 40 : W < 520 ? 200 : (spec.tall && innerWidth >= 1280 ? 296 : 240));
    const padT = mini ? 2 : 10, padB = mini ? 0 : 26;
    const n = spec.labels.length;
    if (!n) { el.innerHTML = ''; return; }
    const totals = spec.labels.map((_, i) => spec.series.reduce((a, s) => a + (s.values[i] || 0), 0));
    const scale = niceScale(Math.max(1, ...totals)), max = scale.max;
    const ticks = mini ? [] : scale.ticks;
    const yLab = ticks.map((v) => num(v));
    const labW = mini ? 0 : Math.max(...yLab.map((s) => s.length)) * 7 + 10;
    const padS = mini ? 0 : labW, padE = mini ? 0 : 4;
    const plotW = W - padS - padE, plotH = H - padT - padB;
    const slot = plotW / n;
    const bw = clamp(slot * (mini ? 0.7 : 0.62), mini ? 2 : 3, 24);
    const rad = bw >= 8 ? 4 : bw >= 4 ? 2 : 1;
    const X = (i) => { const x = padS + i * slot + (slot - bw) / 2; return RTL ? W - x - bw : x; };
    const Y = (v) => padT + plotH - (v / max) * plotH;
    const id = el.id || (el.id = 'ch' + ++uid);
    let g = '';
    ticks.forEach((v, k) => {
      const y = Math.round(Y(v)) + 0.5;
      g += `<line class="${k === 0 ? 'base' : 'gl'}" x1="${RTL ? 0 : padS}" x2="${RTL ? W - padS : W}" y1="${y}" y2="${y}"/>`;
      g += `<text x="${RTL ? W - 2 : 0}" y="${y + 4}" text-anchor="${RTL ? 'end' : 'start'}" style="direction:ltr" class="num">${esc(yLab[k])}</text>`;
    });
    g += `<rect class="hl" x="0" y="${padT}" width="${Math.max(bw + 8, slot * 0.86)}" height="${plotH}" rx="6"/>`;
    let defs = '';
    spec.series.forEach((s, k) => {
      defs += `<pattern id="${id}-p${k}" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" style="fill:${s.color}" opacity=".32"/><rect width="3" height="6" style="fill:${s.color}"/></pattern>`;
    });
    for (let i = 0; i < n; i++) {
      let acc = 0;
      const partial = spec.partial && spec.partial[i];
      const segs = spec.series.map((s, k) => ({ k, v: s.values[i] || 0, c: s.color })).filter((x) => x.v > 0);
      segs.forEach((sg, j) => {
        const y0 = Y(acc), y1 = Y(acc + sg.v);
        acc += sg.v;
        const top = j === segs.length - 1;
        let h = y0 - y1;
        if (!top && h > 3) h -= 2;
        const fill = partial ? `url(#${id}-p${sg.k})` : sg.c;
        const d = top ? colTop(X(i), y1, bw, h, rad) : rect(X(i), y1, bw, h);
        if (d) g += `<path d="${d}" style="fill:${fill}"/>`;
      });
    }
    if (!mini) {
      const every = n <= 8 ? 1 : Math.ceil(n / (W < 520 ? 4 : 7));
      for (let i = n - 1; i >= 0; i -= every) g += `<text x="${X(i) + bw / 2}" y="${H - 6}" text-anchor="middle">${esc(spec.labels[i])}</text>`;
    }
    for (let i = 0; i < n; i++) {
      const x = RTL ? W - (padS + (i + 1) * slot) : padS + i * slot;
      g += `<rect data-i="${i}" x="${x}" y="0" width="${slot}" height="${H}" fill="transparent"/>`;
    }
    el.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="${esc(spec.aria || '')}"><defs>${defs}</defs>${g}</svg>`;
    const svg = el.firstChild, hl = svg.querySelector('.hl');
    const show = (i, cx, cy) => {
      if (i == null) { hl.classList.remove('on'); tip(null); el._active = null; return; }
      el._active = i;
      hl.setAttribute('x', X(i) + bw / 2 - +hl.getAttribute('width') / 2);
      hl.classList.add('on');
      const rows = spec.series.map((s) => `<div class="tr"><span><i class="swatch" style="background:${s.color}"></i>${esc(s.label)}</span><b class="num">${esc(s.fmt[i])}</b></div>`).join('');
      const tot = spec.series.length > 1 && spec.totals ? `<div class="tr" style="margin-top:4px"><span>${esc(t('c.total'))}</span><b class="num">${esc(spec.totals[i])}</b></div>` : '';
      const foot = spec.notes && spec.notes[i] ? `<div class="tf">${esc(spec.notes[i])}</div>` : '';
      const r = el.getBoundingClientRect();
      const px = cx != null ? cx : r.left + (X(i) + bw / 2) * (r.width / W);
      const py = cy != null ? cy : r.top + Y(totals[i]) * (r.height / H);
      tip(`<div class="tt">${esc((spec.tips || spec.labels)[i])}</div>${rows}${tot}${foot}`, px, py);
    };
    svg.addEventListener('pointermove', (e) => { const hit = e.target.closest && e.target.closest('rect[data-i]'); if (hit) show(+hit.dataset.i, e.clientX, e.clientY); });
    svg.addEventListener('pointerleave', () => show(null));
    if (!mini) {
      el.setAttribute('tabindex', '0');
      el.onkeydown = (e) => {
        const fwd = RTL ? 'ArrowLeft' : 'ArrowRight', back = RTL ? 'ArrowRight' : 'ArrowLeft';
        if (![fwd, back, 'Home', 'End'].includes(e.key)) return;
        e.preventDefault();
        let i = el._active == null ? n - 1 : el._active;
        if (e.key === fwd) i = Math.min(n - 1, i + 1);
        if (e.key === back) i = Math.max(0, i - 1);
        if (e.key === 'Home') i = 0;
        if (e.key === 'End') i = n - 1;
        show(i);
      };
      el.onblur = () => show(null);
    }
  }
  function donut(el, spec) {
    const S = 184, R = 82, TH = 20, C = S / 2;
    const items = spec.items.filter((x) => x.value > 0);
    const total = items.reduce((a, x) => a + x.value, 0);
    const circ = 2 * Math.PI * (R - TH / 2);
    const gap = items.length > 1 ? 2 : 0;
    let off = 0, g = '';
    spec.items.forEach((it, i) => {
      if (!it.value || !total) return;
      const len = (it.value / total) * circ;
      const dash = Math.max(0.5, len - gap);
      g += `<circle data-i="${i}" cx="${C}" cy="${C}" r="${R - TH / 2}" fill="none" style="stroke:${it.color}" stroke-width="${TH}" stroke-dasharray="${dash} ${circ - dash}" stroke-dashoffset="${-off}" transform="rotate(-90 ${C} ${C})"/>`;
      off += len;
    });
    el.innerHTML = `<svg viewBox="0 0 ${S} ${S}" width="${S}" height="${S}" role="img" aria-label="${esc(spec.aria || '')}">
      <circle cx="${C}" cy="${C}" r="${R - TH / 2}" fill="none" style="stroke:var(--track)" stroke-width="${TH}"/>${g}
      <text x="${C}" y="${C - 2}" text-anchor="middle" style="font-size:24px;font-weight:700;fill:var(--ink)" class="num">${esc(spec.center)}</text>
      <text x="${C}" y="${C + 20}" text-anchor="middle" style="font-size:12.5px">${esc(spec.center_label)}</text></svg>`;
    const svg = el.firstChild;
    svg.addEventListener('pointermove', (e) => {
      const c = e.target.closest && e.target.closest('circle[data-i]');
      if (!c) { tip(null); return; }
      const it = spec.items[+c.dataset.i];
      tip(`<div class="tt">${esc(it.label)}</div>` + (it.rows || []).map(([k, v]) => `<div class="tr"><span>${esc(k)}</span><b class="num">${esc(v)}</b></div>`).join(''), e.clientX, e.clientY);
    });
    svg.addEventListener('pointerleave', () => tip(null));
  }
  const charts = new Map();
  function drawChart(el) {
    const spec = charts.get(el);
    if (!spec || !el.isConnected || el.offsetParent === null) return;
    (spec.type === 'donut' ? donut : columns)(el, spec);
  }
  function mountCharts(r) {
    $$('[data-spec]', r).forEach((el) => {
      try { charts.set(el, JSON.parse(el.dataset.spec)); } catch (e) { return; }
      drawChart(el);
    });
  }
  addEventListener('resize', debounce(() => { for (const el of charts.keys()) drawChart(el); }, 120));

  /* ── forms with a save bar: count changed fields, show the bar, cancel = reset ── */
  function fieldValue(el) { return el.type === 'checkbox' || el.type === 'radio' ? el.checked : el.value; }
  function trackDirty(form) {
    const fields = $$('input:not([type=hidden]):not([data-ignore]),select:not([data-ignore]),textarea:not([data-ignore])', form);
    fields.forEach((el) => { el._init = fieldValue(el); });
    const bar = $('[data-savebar]', form);
    const update = () => {
      let n = 0, bad = 0;
      fields.forEach((el) => {
        const dirty = fieldValue(el) !== el._init;
        const host = el.closest('[data-f]');
        if (host) host.classList.toggle('dirty', dirty || $$('input,select,textarea', host).some((x) => fieldValue(x) !== x._init));
        if (dirty) n++;
        if (el.classList.contains('err')) bad++;
      });
      if (form.dataset.extraDirty) n += +form.dataset.extraDirty;
      if (!bar) return;
      bar.hidden = n === 0;
      const msg = $('[data-savebar-msg]', bar);
      if (msg) msg.textContent = bad ? t('st.fix', { n: num(bad) }) : t('c.unsaved', { n: num(n) });
      const sv = $('[data-savebar-save]', bar);
      if (sv) sv.disabled = bad > 0;
    };
    form._update = update;
    form.addEventListener('input', update);
    form.addEventListener('change', update);
    form.addEventListener('reset', () => setTimeout(() => {
      $$('[data-int]', form).forEach(validateInt);
      if (form._afterReset) form._afterReset();
      update();
    }, 0));
    update();
  }
  function validateInt(el) {
    const host = el.closest('.ctl') || el.parentElement;
    const v = toLatin(el.value).replace(/[٬,\s]/g, '');
    let err = '';
    if (!/^-?\d+$/.test(v)) err = t('st.err.num');
    else if (+v < 0) err = t('st.err.neg');
    else if (el.dataset.max && +v > +el.dataset.max) err = t('st.err.max', { n: num(+el.dataset.max) });
    el.classList.toggle('err', !!err);
    const box = el.closest('.fld, .cap-cell');
    if (!box) return;
    const old = $('.field-err.js-err', box); if (old) old.remove();
    if (err) (el.closest('.ctl') || el.closest('.cap-cell')).insertAdjacentHTML('beforeend', `<div class="field-err js-err">${ic('circle-alert', 'ic-14')}${esc(err)}</div>`);
  }

  /* ── settings page ── */
  function mountSettings(r) {
    const form = $('#set-form', r);
    if (!form) return;
    $$('[data-int]', form).forEach((el) => el.addEventListener('input', () => { validateInt(el); }));
    const q = $('[data-set-q]', r);
    if (q) {
      const items = $$('.fld, .cap-cell', form);
      const run = () => {
        const ql = q.value.trim().toLowerCase();
        items.forEach((it) => { it.hidden = !!ql && !(it.dataset.search || '').toLowerCase().includes(ql); });
        $$('.set-sub', form).forEach((h) => {
          let el = h.nextElementSibling, any = false;
          while (el && !el.classList.contains('set-sub')) { if (el.matches('.fld, .cap-grid') && (el.matches('.cap-grid') ? $$('.cap-cell', el).some((c) => !c.hidden) : !el.hidden)) any = true; el = el.nextElementSibling; }
          h.hidden = !any;
        });
        $$('.cap-grid', form).forEach((gr) => { gr.hidden = !$$('.cap-cell', gr).some((c) => !c.hidden); });
        let anySec = false;
        $$('.set-sec', form).forEach((s) => { const vis = $$('.fld, .cap-cell', s).some((x) => !x.hidden); s.hidden = !vis; anySec = anySec || vis; });
        const none = $('[data-set-none]', r); if (none) none.hidden = anySec;
      };
      q.addEventListener('input', debounce(run, 120));
      if (q.value) run();
    }
    const links = $$('.set-nav a', r);
    if (links.length && 'IntersectionObserver' in window) {
      const io = new IntersectionObserver((ents) => {
        for (const en of ents) if (en.isIntersecting) { const id = en.target.id; links.forEach((a) => a.classList.toggle('on', a.getAttribute('href') === '#' + id)); }
      }, { rootMargin: '-80px 0px -65% 0px' });
      $$('.set-sec', r).forEach((s) => io.observe(s));
    }
    const focus = new URLSearchParams(location.search).get('focus');
    if (focus) {
      const el = doc.getElementById('f-' + focus);
      if (el) setTimeout(() => { el.scrollIntoView({ block: 'center' }); el.classList.add('hit'); const i = $('input,select,textarea', el); if (i) i.focus({ preventScroll: true }); }, 30);
    }
  }

  /* ── texts page: autosize, live placeholder checks, post only what changed ── */
  function autosize(ta) { ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 2 + 'px'; }
  function phCheck(ta) {
    const row = ta.closest('.txt-row');
    if (!row) return;
    const want = new Set((row.dataset.ph || '').split(' ').filter(Boolean));
    const have = new Set(ta.value.match(/\{\w+\}/g) || []);
    const missing = [...want].filter((x) => !have.has(x)), unknown = [...have].filter((x) => !want.has(x));
    $$('.js-ph', row).forEach((x) => x.remove());
    const box = ta.parentElement;
    missing.forEach((v) => box.insertAdjacentHTML('beforeend', `<div class="field-err js-ph" style="color:var(--warn-ink)">${ic('triangle-alert', 'ic-14')}${esc(t('tx.missing', { v }))}</div>`));
    unknown.forEach((v) => box.insertAdjacentHTML('beforeend', `<div class="field-err js-ph">${ic('circle-alert', 'ic-14')}${esc(t('tx.unknown', { v }))}</div>`));
    ta.classList.toggle('err', unknown.length > 0);
  }
  function mountTexts(r) {
    const tas = $$('textarea[data-tx]', r);
    // read every height first, then write: one layout pass instead of one per row
    tas.forEach((ta) => { ta.style.height = 'auto'; });
    const hs = tas.map((ta) => ta.scrollHeight + 2);
    tas.forEach((ta, i) => { ta.style.height = hs[i] + 'px'; ta.addEventListener('input', () => { autosize(ta); phCheck(ta); }); });
  }

  /* ── button editor: drag or Alt+arrow to reorder, live Telegram preview ── */
  function mountButtons(r) {
    const list = $('#be-list', r), prev = $('#tg-kb', r), form = $('#bt-form', r);
    if (!list || !form) return;
    const caps = JSON.parse(form.dataset.widthCap || '{"full":1,"half":2,"third":3}');
    const closeLabel = form.dataset.closeLabel || '';
    const orderIn = $('input[name=order]', form);
    const initOrder = orderIn.value;
    const rows = () => $$('.be-row', list);
    const sync = () => {
      orderIn.value = rows().map((x) => x.dataset.op).join(',');
      form.dataset.extraDirty = orderIn.value !== initOrder ? '1' : '';
      // preview: visible buttons packed into rows by width, «close» on its own last row
      // an empty box saves as «use the default», which is the input's placeholder
      const label = (x) => { const b = $('[data-bt-label]', x); return b.value.trim() || b.placeholder; };
      const vis = rows().filter((x) => $('input[type=checkbox]', x).checked).map((x) => ({
        label: label(x), style: $('select', x).value,
        width: ($('input[data-width]:checked', x) || {}).value || 'third' }));
      let html = '', i = 0;
      while (i < vis.length) {
        const w = vis[i].width, cap = caps[w] || 3;
        let j = i;
        while (j < vis.length && j - i < cap && vis[j].width === w) j++;
        html += `<div class="r">${vis.slice(i, j).map((b) => `<span class="b ${esc(b.style)}">${esc(b.label)}</span>`).join('')}</div>`;
        i = j;
      }
      html += `<div class="r"><span class="b">${esc(closeLabel)}</span></div>`;
      if (prev) prev.innerHTML = html;
      rows().forEach((x) => x.classList.toggle('off', !$('input[type=checkbox]', x).checked));
      if (form._update) form._update();
    };
    form._afterReset = () => {
      // reset restores fields but not the DOM order: rebuild from the initial order
      const want = initOrder.split(',');
      want.forEach((op) => { const x = $(`.be-row[data-op="${op}"]`, list); if (x) list.appendChild(x); });
      sync();
    };
    list.addEventListener('input', sync);
    list.addEventListener('change', sync);
    list.addEventListener('pointerdown', (e) => {
      const g = e.target.closest('[data-grip]');
      if (!g) return;
      e.preventDefault();
      const row = g.closest('.be-row');
      row.classList.add('dragging');
      g.setPointerCapture(e.pointerId);
      const move = (ev) => {
        for (const other of rows()) {
          if (other === row) continue;
          const rc = other.getBoundingClientRect();
          if (ev.clientY > rc.top && ev.clientY < rc.bottom) {
            const after = ev.clientY > rc.top + rc.height / 2;
            list.insertBefore(row, after ? other.nextSibling : other);
            sync();
            break;
          }
        }
      };
      const up = () => { g.removeEventListener('pointermove', move); row.classList.remove('dragging'); };
      g.addEventListener('pointermove', move);
      g.addEventListener('pointerup', up, { once: true });
      g.addEventListener('pointercancel', up, { once: true });
    });
    list.addEventListener('keydown', (e) => {
      const g = e.target.closest('[data-grip]');
      if (!g || !e.altKey || (e.key !== 'ArrowUp' && e.key !== 'ArrowDown')) return;
      e.preventDefault();
      const row = g.closest('.be-row');
      if (e.key === 'ArrowUp' && row.previousElementSibling) list.insertBefore(row, row.previousElementSibling);
      if (e.key === 'ArrowDown' && row.nextElementSibling) list.insertBefore(row.nextElementSibling, row);
      g.focus();
      sync();
    });
    sync();
  }

  /* ── sign-in code: six boxes write into the real `code` field ── */
  function mountLogin(r) {
    const form = $('#lg-code', r);
    if (form) {
      const real = $('input[name=code]', form), boxes = $$('.otp input', form), go = $('[type=submit]:not([form])', form);
      if (boxes.length === 6 && real) {
        $('.otp', form).hidden = false;
        const code = () => boxes.map((b) => b.value).join('');
        const sync = () => { real.value = code(); if (go) go.disabled = real.value.length !== 6; };
        const submit = () => { if (real.value.length === 6) { if (form.requestSubmit) form.requestSubmit(go); else form.submit(); } };
        const fill = (digits, from) => {
          for (let i = 0; i < digits.length && from + i < 6; i++) boxes[from + i].value = digits[i];
          (boxes.find((b) => !b.value) || boxes[5]).focus();
          sync(); submit();
        };
        boxes.forEach((b, i) => {
          b.addEventListener('input', () => {
            const v = toLatin(b.value).replace(/\D/g, '');
            if (v.length > 1) { b.value = ''; fill(v, i); return; }
            b.value = v;
            $$('.js-clear-err', form).forEach((x) => x.remove());
            $('.otp', form).classList.remove('err');
            if (v && i < 5) boxes[i + 1].focus();
            sync(); submit();
          });
          b.addEventListener('keydown', (e) => {
            if (e.key === 'Backspace' && !b.value && i > 0) { e.preventDefault(); boxes[i - 1].value = ''; boxes[i - 1].focus(); sync(); }
            else if (e.key === 'ArrowLeft' && i > 0) { e.preventDefault(); boxes[i - 1].focus(); }
            else if (e.key === 'ArrowRight' && i < 5) { e.preventDefault(); boxes[i + 1].focus(); }
          });
          b.addEventListener('focus', () => b.select());
          b.addEventListener('paste', (e) => { e.preventDefault(); fill(toLatin(e.clipboardData.getData('text')).replace(/\D/g, '').slice(0, 6), 0); });
        });
        sync();
        if (!boxes[0].disabled) setTimeout(() => boxes[0].focus(), 0);
      }
    }
    $$('[data-countdown]', r).forEach((el) => {
      let left = +el.dataset.countdown;
      const label = el.dataset.label || '{t}';
      const clock = (s) => { const m = Math.floor(s / 60), x = s % 60; const out = `${m}:${String(x).padStart(2, '0')}`; return LANG === 'fa' ? out.replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[d]) : out; };
      const target = el.dataset.enables ? doc.getElementById(el.dataset.enables) : null;
      const tick = () => {
        if (left <= 0) {
          if (target) { target.disabled = false; }
          if (el.dataset.done) el.textContent = el.dataset.done; else if (el.dataset.expire != null) location.href = el.dataset.expire || location.href;
          clearInterval(h); return;
        }
        el.textContent = label.replace('{t}', clock(left));
        left--;
      };
      const h = setInterval(tick, 1000);
      tick();
    });
    const idIn = $('input[name=admin_id]', r);
    if (idIn) idIn.addEventListener('input', () => { const v = toLatin(idIn.value); if (v !== idIn.value) idIn.value = v; });
  }

  /* ── global search ── */
  let sIdx = -1, sTimer;
  async function searchFetch(q) {
    const r = await fetch('/api/search?q=' + encodeURIComponent(q), { credentials: 'same-origin' });
    if (!r.ok) return null;
    return r.json();
  }
  function searchHTML(res) {
    let html = '';
    for (const grp of (res && res.groups) || []) {
      if (!grp.items.length) continue;
      html += `<div class="grp">${esc(grp.label)}</div>` + grp.items.map((x) =>
        `<a class="menu-item" href="${esc(x.href)}"><span class="tint-ic ${esc(x.tint || 't0')}">${ic(x.icon)}</span><span class="trunc">${esc(x.t)}</span>${x.sub ? `<span class="sub trunc ${x.mono ? 'mono' : ''}" ${x.mono ? 'dir="ltr"' : ''}>${esc(x.sub)}</span>` : ''}</a>`).join('');
    }
    return html || `<div class="empty" style="padding:22px">${esc(t('c.no_results'))}</div>`;
  }
  function mountSearch() {
    const input = $('#q');
    if (!input) return;
    const pop = $('#search-pop');
    const run = debounce(async () => {
      const q = input.value.trim();
      if (q.length < 2) { pop.hidden = true; return; }
      const res = await searchFetch(q);
      if (input.value.trim() !== q) return;
      pop.innerHTML = searchHTML(res);
      pop.hidden = false;
      sIdx = -1;
    }, 160);
    input.addEventListener('input', run);
    input.addEventListener('focus', () => { if (input.value.trim().length >= 2) run(); });
    input.addEventListener('keydown', (e) => {
      const items = $$('.menu-item', pop);
      if (e.key === 'Escape') { pop.hidden = true; input.blur(); return; }
      if (!items.length || pop.hidden) return;
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault();
        sIdx = (sIdx + (e.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
        items.forEach((x, i) => x.classList.toggle('active', i === sIdx));
        items[sIdx].scrollIntoView({ block: 'nearest' });
      } else if (e.key === 'Enter' && sIdx >= 0) {
        e.preventDefault();
        items[sIdx].click();
      }
    });
    doc.addEventListener('pointerdown', (e) => { if (!pop.hidden && !pop.contains(e.target) && e.target !== input) pop.hidden = true; });
    const dlgIn = $('#q2'), box = $('#q2res');
    if (dlgIn && box) {
      dlgIn.addEventListener('input', debounce(async () => {
        const q = dlgIn.value.trim();
        if (q.length < 2) { box.innerHTML = `<div class="muted fs-12">${esc(t('srch.hint'))}</div>`; return; }
        box.innerHTML = searchHTML(await searchFetch(q));
      }, 160));
    }
  }

  /* ── delegated clicks ── */
  doc.addEventListener('click', (e) => {
    const el = e.target.closest('[data-act],[data-dialog],[data-copy],[data-view],[data-sheet-close],[data-close],a[data-sheet],tr[data-href],[data-default],[data-reveal]');
    if (!el) {
      if (!e.target.closest('details.dd')) closeDropdowns();
      const app = $('#app');
      if (app && app.classList.contains('drawer') && e.target === app) app.classList.remove('drawer');
      return;
    }
    if (el.matches('[data-dialog]')) { if (openDialog(el.dataset.dialog, el)) e.preventDefault(); return; }
    if (el.matches('[data-close]')) { const d = el.closest('dialog'); if (d) { e.preventDefault(); d.close(); } return; }
    if (el.matches('[data-sheet-close]')) { e.preventDefault(); closeSheet(); return; }
    if (el.matches('a[data-sheet]')) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button === 1) return;
      e.preventDefault(); closeDropdowns(); openSheet(el.href); return;
    }
    if (el.matches('tr[data-href]')) {
      if (e.target.closest('a,button,input,select,textarea,summary,details')) return;
      const a = $('a[data-sheet], a.rowlink', el);
      if (a && a.dataset.sheet != null) openSheet(a.href); else location.href = el.dataset.href;
      return;
    }
    if (el.matches('[data-copy]')) { e.preventDefault(); copy(el.dataset.copy, el); return; }
    if (el.matches('[data-view]')) {
      const card = el.closest('.card'), table = el.dataset.view === 'table';
      card.classList.toggle('show-table', table);
      $$('[data-view]', card).forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.view === el.dataset.view)));
      if (!table) $$('[data-spec]', card).forEach(drawChart);
      return;
    }
    if (el.matches('[data-default]')) {         // settings: reset one field to its default
      e.preventDefault();
      const f = doc.getElementById(el.dataset.default);
      if (!f) return;
      if (f.type === 'checkbox') f.checked = el.dataset.v === '1'; else f.value = el.dataset.v;
      f.dispatchEvent(new Event('input', { bubbles: true })); f.dispatchEvent(new Event('change', { bubbles: true }));
      return;
    }
    if (el.matches('[data-reveal]')) {
      e.preventDefault();
      const i = el.parentElement.querySelector('input');
      i.type = i.type === 'password' ? 'text' : 'password';
      $('use', el).setAttribute('href', `${SPRITE()}#i-${i.type === 'password' ? 'eye' : 'eye-off'}`);
      return;
    }
    const act = el.dataset.act;
    if (act === 'drawer') { $('#app').classList.add('drawer'); }
    else if (act === 'drawer-close') { $('#app').classList.remove('drawer'); }
    else if (act === 'theme') { e.preventDefault(); setTheme(isDark() ? 'light' : 'dark'); }
    else if (act === 'search-open') { e.preventDefault(); openDialog('search-dlg', el); }
    else if (act === 'reset-form') { e.preventDefault(); const f = el.closest('form'); if (f) f.reset(); }
  });
  doc.addEventListener('change', (e) => {
    const el = e.target;
    if (el.matches('input[data-theme-switch]')) setTheme(el.checked ? 'dark' : 'light');
    if (el.matches('select[data-autosubmit]') && el.form) el.form.submit();
    if (el.matches('input[type=checkbox][data-autosubmit]') && el.form) el.form.submit();
    if (el.matches('.file-pick input[type=file]')) {
      const n = $('[data-file-name]', el.closest('.file-pick'));
      const f = el.files && el.files[0];
      if (n) { n.textContent = f ? f.name : n.dataset.fileName; n.classList.toggle('has', !!f); }
    }
  });
  doc.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if ($$('details.dd[open]').length) { closeDropdowns(); return; }
      if (closeSheet()) return;
      const app = $('#app'); if (app) app.classList.remove('drawer');
    }
    if (e.key === '/' && !/INPUT|TEXTAREA|SELECT/.test((doc.activeElement || {}).tagName || '')) {
      const i = $('#q'); if (i && i.offsetParent) { e.preventDefault(); i.focus(); }
    }
    if (e.key === 'Enter' && e.target.matches && e.target.matches('tr[data-href]')) e.target.click();
  });
  addEventListener('scroll', () => { const tb = $('#topbar'); if (tb) tb.classList.toggle('scrolled', scrollY > 4); }, { passive: true });

  function mount(r) {
    mountCharts(r);
    $$('form[data-savebar-form]', r).forEach(trackDirty);
    mountSettings(r);
    mountTexts(r);
    mountButtons(r);
    mountLogin(r);
  }
  function boot() {
    // «auto» theme follows the OS, which the server cannot see: fix the toggle's icon and state here
    const dark = isDark();
    $$('[data-theme-icon]').forEach((u) => u.setAttribute('href', `${SPRITE()}#i-${dark ? 'sun' : 'moon'}`));
    $$('input[data-theme-switch]').forEach((i) => { i.checked = dark; });
    mount(doc);
    mountSearch();
    $$('dialog.dialog[open]').forEach((d) => { d.close(); if (typeof d.showModal === 'function') { d.showModal(); focusIn(d); } else d.setAttribute('open', ''); });
    const host = $('#sheet-host');
    if (host && host.innerHTML.trim()) host.dataset.static = '';
    const fl = $('[data-toast]');
    if (fl) { toast(fl.dataset.toast, fl.dataset.icon); }
    // a flash message is consumed once: drop ok=/err= from the URL so a reload does not repeat it
    const u = new URL(location.href);
    if (['ok', 'err', 'sent'].some((k) => u.searchParams.has(k))) { ['ok', 'err', 'sent'].forEach((k) => u.searchParams.delete(k)); history.replaceState(null, '', u); }
  }
  if (doc.readyState === 'loading') doc.addEventListener('DOMContentLoaded', boot); else boot();
})();
