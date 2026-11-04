// ---------- Ask anything (streams from the local AI) ----------
function openAsk() { $('#askp').hidden = false; document.body.style.overflow = 'hidden'; $('#ask').focus({ preventScroll: true }); }  // focus inside the tap so iOS opens the keyboard
function closeAsk() { $('#ask').blur(); $('#askp').hidden = true; document.body.style.overflow = ''; }

document.querySelector('[data-close-ask]').onclick = closeAsk;
const askBox = $('#ask');
askBox.oninput = () => { askBox.style.height = 'auto'; askBox.style.height = askBox.scrollHeight + 'px'; };
askBox.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#ask-form').requestSubmit(); } };
$('#ask-form').onsubmit = async (e) => {
  e.preventDefault();
  const q = $('#ask').value.trim(); if (!q) return;
  const box = $('#answer'); box.hidden = false;
  box.innerHTML = `<div class="q">${esc(q)}</div><span class="a">Thinking…</span>`;
  $('#ask').value = ''; $('#ask').style.height = 'auto'; $('#ask').blur();
  const a = box.querySelector('.a');
  try {
    const r = await fetch('/api/bot/ask', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ q }) });
    const reader = r.body.getReader(), dec = new TextDecoder(); let text = '';
    for (;;) { const { done, value } = await reader.read(); if (done) break; text += dec.decode(value, { stream: true }); a.textContent = text.replace(/\*\*/g, ''); }
    if (!text.trim()) a.textContent = 'Sorry, no answer came back. Try again?';
  } catch { a.textContent = "Sorry, the AI isn't available right now."; }
};

// ---------- Apps (open inside this page) ----------
const ICON = (n) => `https://cdn.jsdelivr.net/gh/homarr-labs/dashboard-icons/png/${n}.png`;
const APPS = [
  { name: 'AI chat', sub: 'Talk to your AI', port: 8081, icon: 'open-webui', c: 'open-webui', app: 'open-webui' },
  { name: 'Charts', sub: 'Server history', port: 3000, path: '/d/homelab-command?kiosk', icon: 'grafana', c: 'grafana', app: 'monitoring' },
  { name: 'Uptime', sub: 'Your websites', port: 3001, icon: 'uptime-kuma', c: 'uptime-kuma', app: 'uptime-kuma' },
  { name: 'Search', sub: 'Private search', port: 8889, icon: 'searxng', c: 'searxng', app: 'searxng' },
  { name: 'Automations', sub: 'Opens in Safari', port: 5678, icon: 'n8n', c: 'n8n', app: 'n8n', outside: true },  // n8n refuses to be shown inside other pages
];
const TOOLS = [
  { name: 'Ad blocker', sub: 'AdGuard', port: 3002, icon: 'adguard-home', c: 'adguard', app: 'adguard' },
  { name: 'Logs', sub: 'App activity', port: 8888, icon: 'dozzle', c: 'dozzle', app: 'dozzle' },
  { name: 'Metrics', sub: 'Prometheus', port: 9090, icon: 'prometheus', c: 'prometheus', app: 'monitoring' },
  { name: 'Dashboard', sub: 'Everything', port: 3080, icon: 'homarr', c: 'homepage', app: 'homepage' },
];
const appHTML = (a, i) => `<button class="card app" data-app="${i}">
  <span class="ic">${a.icon ? `<img src="${ICON(a.icon)}" alt="" loading="lazy" onerror="this.style.visibility='hidden'">` : `<b>${esc(a.name.trim().charAt(0).toUpperCase())}</b>`}${a.c ? `<i data-c="${a.c}"></i>` : ''}</span>
  <span><b>${esc(a.name)}</b><small>${esc(a.sub)}</small></span></button>`;
let ALL = [...APPS, ...TOOLS];
// The tiles: built-in ones only for apps you installed (minus any you hid in Settings), then your own, in Everyday apps and Tools.
// The list ends with Add apps, which opens Settings, Apps. If the app list can't be read, every built-in tile shows, as before.
let tilesInstalled = null, tilesLayout = {}, tilesCustom = [];  // tilesCustom: the apps you added yourself (Settings, Apps, Add your own)
const ADD_TILE = { name: 'Add apps', sub: 'Choose what to install', add: true };
const addHTML = () => `<button class="card app app-add" data-app-more><span class="ic"><b>+</b></span><span><b>${ADD_TILE.name}</b><small>${ADD_TILE.sub}</small></span></button>`;
function renderTiles(layout = tilesLayout) {
  tilesLayout = layout || {};
  const hide = new Set(tilesLayout.tiles_hidden || []), own = (g) => (tilesLayout.tiles || []).filter((t) => (t.group || 'apps') === g && /^https?:\/\//i.test(t.url || ''));
  const have = (a) => !hide.has(a.name) && (!a.app || !tilesInstalled || tilesInstalled.has(a.app));
  const mine = (g) => tilesCustom.filter((a) => a.tile === g && !hide.has(a.name));
  const apps = [...APPS.filter(have), ...mine('apps'), ...own('apps')], tools = [...TOOLS.filter(have), ...mine('tools'), ...own('tools')];
  ALL = [...apps, ...tools];
  $('#apps').innerHTML = apps.map((a, i) => appHTML(a, i)).join('') + addHTML();
  $('#tools').innerHTML = tools.map((a, i) => appHTML(a, i + apps.length)).join('');
  $('#tools').hidden = $('#tools').previousElementSibling.hidden = !tools.length;
  paintApps();
}
async function loadInstalled() {
  try {
    const r = await (await fetch('/api/bot/server/catalog', { cache: 'no-store' })).json();
    if (Array.isArray(r.apps)) {
      tilesInstalled = new Set(r.apps.filter((a) => !a.custom && (a.chosen || a.state === 'running' || a.state === 'stopped')).map((a) => a.id));
      tilesCustom = r.apps.filter((a) => a.custom).map((a) => ({ name: a.title, sub: 'Your app', port: a.port, c: a.id, tile: a.tile }));
    }
  } catch (e) { tilesInstalled = null; }
  renderTiles();
}
renderTiles();
loadInstalled();
function paintApps() { document.querySelectorAll('.app i[data-c]').forEach((i) => { i.className = typeof running === 'undefined' || running == null ? '' : running.includes(i.dataset.c) ? 'up' : 'down'; }); }

let current = null;
function openApp(a) {
  const url = a.url || appURL(a.port, a.path);
  if (a.outside) return openOutside(url);
  current = url;
  $('#viewer-title').textContent = a.name;
  $('.viewer-load').hidden = false;
  $('#viewer-frame').src = url;
  $('#viewer').hidden = false; document.body.style.overflow = 'hidden';
}
$('#viewer-frame').onload = () => { $('.viewer-load').hidden = true; };
$('#viewer-done').onclick = () => { $('#viewer').hidden = true; $('#viewer-frame').src = 'about:blank'; document.body.style.overflow = ''; current = null; };
$('#viewer-reload').onclick = () => { if (current) spinning($('#viewer-reload'), () => new Promise((ok) => {
  const f = $('#viewer-frame'); f.addEventListener('load', ok, { once: true }); setTimeout(ok, 15000); f.src = current; })); };
$('#viewer-out').onclick = () => { if (current) openOutside(current); };
document.addEventListener('click', (e) => {
  if (e.target.closest('[data-app-more]')) { openSettings(); SET.page = 'apps'; setRender(); return; }
  const b = e.target.closest('[data-app]'); if (b) openApp(ALL[+b.dataset.app]);
});
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') { if (!$('#jms').hidden) jmsClose(); else if (!$('#sheet').hidden) closeSheet(); else if (!$('#wtp').hidden) closeWt(); else if (!$('#statp').hidden) closeStat(); else if (!$('#viewer').hidden) $('#viewer-done').click(); else if (!$('#jent').hidden) closeEntry(); else if (!$('#jdsub').hidden) closeJdSub(); else if (!$('#jdeep').hidden) closeDeep(); else if (!$('#jlet').hidden) closeLetters(); else if (!$('#jfind').hidden) closeFind(); else if (!$('#jq').hidden) closeQueue(); else if (!$('#jwks').hidden) closeWeeks(); else if (!$('#jther').hidden) closeTher(); else if (!$('#askp').hidden) closeAsk(); else if (!$('#newsp').hidden) closeNews(); else if (!$('#pastp').hidden) closePast(); else if (!$('#notesp').hidden) closeNotes(); else if (!$('#hwp').hidden) closeHw(); else if (!$('#nlp').hidden) closeNl(); else if (!$('#brief').hidden) closeBrief(); else if (!$('#wxp').hidden) closeWx(); else if (!$('#gymp').hidden || !$('#gymh').hidden) {
  const top = [...document.querySelectorAll('#gymp:not([hidden]), #gymh:not([hidden])')].sort((a, b) => (+b.style.zIndex || 50) - (+a.style.zIndex || 50))[0];
  top.id === 'gymh' ? $('#gymh [data-hback]').click() : closeGym(); } } });
