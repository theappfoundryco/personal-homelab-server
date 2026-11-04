// ---------- Sheets: drag down by the handle or header to close ----------
function sheetDrag(wrap, close) {
  const sh = wrap.querySelector('.sheet'); let y0 = null, dy = 0;
  const start = (e) => { if (e.target.closest('button, input, textarea, select')) return; y0 = e.clientY; dy = 0; sh.style.transition = 'none'; e.currentTarget.setPointerCapture(e.pointerId); };
  const move = (e) => { if (y0 === null) return; dy = Math.max(0, e.clientY - y0); sh.style.transform = `translateY(${dy}px)`; };
  const end = (e) => {
    if (y0 === null) return; if (e.type === 'pointerup') dy = Math.max(0, e.clientY - y0); y0 = null;  // a quick flick may send no moves sh.style.transition = 'transform .2s cubic-bezier(.2,.8,.2,1)';
    if (dy > 90) { sh.style.transform = 'translateY(100%)'; setTimeout(() => { close(); sh.style.transform = sh.style.transition = ''; }, 200); }
    else sh.style.transform = '';
  };
  wrap.querySelectorAll('.grab, .sheet-head').forEach((el) => { el.onpointerdown = start; el.onpointermove = move; el.onpointerup = end; el.onpointercancel = end; });
}
sheetDrag($('#sheet'), closeSheet); if (typeof jmsClose === 'function') sheetDrag($('#jms'), jmsClose);

// ---------- Start ----------
CFG_READY.then(() => { tick(); weather(); loadExtras(); if (typeof status === 'function') status(); });
setInterval(tick, 10000);
setInterval(() => { if (!document.hidden && typeof status === 'function') status(); }, 30000);
setInterval(() => { if (!document.hidden) loadExtras(); }, 5 * 60000);
document.addEventListener('visibilitychange', () => { if (!document.hidden) { tick(); if (typeof status === 'function') status(); if (Date.now() - (loadExtras.at || 0) > 60000) loadExtras(); pageFresh(); } });
const pageTag = () => fetch('/', { method: 'HEAD', cache: 'no-store' }).then((r) => r.headers.get('etag')).catch(() => null);
const PAGE_TAG = pageTag();
async function pageFresh() {  // never on the journal, while you're typing or with unsaved journal words: it tries again next time you come back
  if (!$('#v-journal').hidden) return;
  const [a, b] = await Promise.all([PAGE_TAG, pageTag()]);
  const typing = document.activeElement?.matches?.('input, textarea, [contenteditable]') || [...document.querySelectorAll('.jw')].some((w) => w._dirty);
  if (a && b && a !== b && !typing) location.reload();
}
try { const t = sessionStorage.getItem('tab'); if (t && t !== 'home' && $('#v-' + t)) showTab(t); } catch (e) {}
// the Telegram reminder's "Start now" opens /#journal
function fromHash() { if (location.hash === '#journal' && typeof jFocus !== 'undefined') { jFocus = true; showTab('journal'); history.replaceState(null, '', location.pathname + location.search); } }
fromHash(); window.addEventListener('hashchange', fromHash);
