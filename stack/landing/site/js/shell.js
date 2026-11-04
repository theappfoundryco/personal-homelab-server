const T12 = { hour: 'numeric', minute: '2-digit', hour12: true };  // 9:31 PM everywhere

const $ = (s) => document.querySelector(s);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
// Your settings from config.yaml (name, timezone, home city, world clocks), served by the assistant. Defaults keep the page working without it.
const CFG = { name: '', timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, home_city: '', clocks: [], features: {}, support: {} };
const CFG_READY = fetch('/api/bot/config', { cache: 'no-store' }).then((r) => r.json()).then((c) => Object.assign(CFG, c)).catch(() => {}).finally(() => { const b = document.getElementById('jther-open'); if (b) b.style.display = CFG.features.therapy_recap ? '' : 'none'; });
const getJSON = async (u, o) => { const r = await fetch(u, { cache: 'no-store', ...o }); if (!r.ok) throw new Error(r.status); return r.json(); };
const post = (u, body) => getJSON(u, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Refresh buttons: spin for a beat first so the tap clearly registered, then refresh, and stop on a full turn.
async function spinning(btn, fn) {
  if (btn.classList.contains('spin')) return;
  btn.classList.add('spin'); btn.setAttribute('aria-busy', 'true');
  await sleep(1000);
  try { await fn(); } finally {
    const svg = btn.querySelector('svg'); let done = false;
    const stop = () => { if (!done) { done = true; btn.classList.remove('spin'); btn.removeAttribute('aria-busy'); } };
    svg.addEventListener('animationiteration', stop, { once: true }); setTimeout(stop, 850);
  }
}

// Messages: work in progress ("stay") shows under its button; everything else pops up in a floating pill and fades,
// so nothing on the page moves when a message comes and goes.
function flash(el, text, { bad = false, stay = false, ms } = {}) {
  clearTimeout(el._t); clearTimeout(el._t2);
  if (text && !stay) { el.className = 'toast'; el.textContent = ''; return snack(text, { bad, ms }); }
  el.className = 'toast' + (bad ? ' bad' : ''); el.textContent = text;
}
function snack(text, { bad = false, ms } = {}) {
  const el = $('#snack'); clearTimeout(el._t);
  el.textContent = text; el.classList.toggle('bad', bad); el.classList.add('on');
  el._t = setTimeout(() => el.classList.remove('on'), ms || (bad ? 5000 : 2600));
}
// confirmSheet({ title, text, ok, danger }) -> true when confirmed
function confirmSheet({ title, text = '', ok = 'OK', no = 'Cancel', danger = false }) {
  const box = $('#cfm'), btn = box.querySelector('[data-cfm-ok]');
  box.querySelector('.cfm-no').textContent = no;
  $('#cfm-t').textContent = title; $('#cfm-x').textContent = text;
  btn.textContent = ok; btn.classList.toggle('danger', danger);
  box.hidden = false; btn.focus({ preventScroll: true });
  return new Promise((done) => {
    const end = (v) => { box.hidden = true; box.onclick = null; document.removeEventListener('keydown', key, true); done(v); };
    const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); end(false); } };
    document.addEventListener('keydown', key, true);
    box.onclick = (e) => { if (e.target.closest('[data-cfm-ok]')) end(true); else if (e.target.closest('[data-cfm-no]')) end(false); };
  });
}
const HOST = location.hostname;
const appURL = (port, path = '') => `http://${HOST}:${port}${path}`;
const STANDALONE = navigator.standalone === true || matchMedia('(display-mode: standalone)').matches;
const IOS = /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
let X = {};  // from the assistant: location, agenda, reminders, FX

// ---------- Links never open a pop-up browser inside the app ----------
// Apps open in the viewer below; other websites (news stories) open in Safari itself.
function openOutside(url) {
  if (STANDALONE && IOS) {
    location.href = 'x-safari-' + url;  // iOS 17+: hand the link to Safari
    setTimeout(() => { if (!document.hidden) window.open(url, '_blank', 'noopener'); }, 900);
  } else window.open(url, '_blank', 'noopener');
}
document.addEventListener('click', (e) => {
  const a = e.target.closest('a[href]');
  if (!a || a.target === '_self') return;
  const u = new URL(a.href, location.href);
  if (u.origin === location.origin) return;
  e.preventDefault(); openOutside(u.href);
});

// ---------- Theme ----------
const SUN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>';
const MOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z"/></svg>';
const isDark = () => document.documentElement.dataset.theme === 'dark';
const paintTheme = () => { $('#theme').innerHTML = isDark() ? SUN : MOON; };
$('#theme').onclick = () => {
  const t = isDark() ? 'light' : 'dark', root = document.documentElement;
  const flip = () => { root.dataset.theme = t; paintTheme(); };
  // a soft crossfade of the whole screen; older browsers ease each colour over instead
  if (document.startViewTransition && !matchMedia('(prefers-reduced-motion: reduce)').matches) document.startViewTransition(flip);
  else { root.classList.add('theming'); flip(); clearTimeout(paintTheme.t); paintTheme.t = setTimeout(() => root.classList.remove('theming'), 500); }
  document.querySelector('meta[name="theme-color"]').content = t === 'dark' ? '#0f0e0d' : '#f4f3f0';
  try { localStorage.setItem('theme-pick', t); } catch (e) {}
  paintTheme();
};
paintTheme();

// ---------- Tabs (all in this page: nothing navigates away) ----------
const loaded = {};
// Back to the top, and stay there: iOS shifts the page while the keyboard is up and slides it back late,
// so drop focus first and pin the top again once the keyboard has gone.
function toTop() {
  const a = document.activeElement; if (a && a !== document.body && a.blur) a.blur();
  const pin = () => window.scrollTo(0, 0);
  pin(); requestAnimationFrame(pin); setTimeout(pin, 120); setTimeout(pin, 400);
  window.visualViewport?.addEventListener('resize', pin, { once: true });
}
function showTab(name) {
  document.querySelectorAll('.view').forEach((v) => { v.hidden = v.id !== 'v-' + name; });
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('on', t.dataset.tab === name));
  toTop();
  if (name === 'journal' && typeof loadJournal === 'function') loadJournal();
  if (name === 'server' && typeof loadServer === 'function') loadServer();
  if (name === 'sg' && typeof loadSG === 'function') loadSG();
  if (name === 'gym' && typeof loadGym === 'function') { renderGymHome.done = false; loadGym(); }
  if (!rebooting) flash($('#act-msg'), '');
  try { sessionStorage.setItem('tab', name); } catch (e) {}
}
document.addEventListener('click', (e) => { const t = e.target.closest('[data-tab]'); if (t) showTab(t.dataset.tab); });
