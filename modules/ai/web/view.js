// ---------- Server and Apps: AI usage (tokens in and out of the local model since the first day counted; days split at midnight, server time) ----------
var AID = null;
const aiDay = (d) => new Date(d + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
const tk = (n) => n >= 1e6 ? +(n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : n >= 1e3 ? +(n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + 'k' : String(Math.round(n));
const aiSum = (ds) => ds.reduce((a, d) => { for (const v of Object.values(AID.days[d] || {})) { a.in += v.in; a.out += v.out; a.calls += v.calls; } return a; }, { in: 0, out: 0, calls: 0 });
function renderAI() {
  const box = $('#ai-use'); if (!box) return;
  if (!AID) { box.innerHTML = ''; return; }  // the AI module is off or not answering: nothing to show
  const col = (a, n) => `<span><small>${a}</small><b class="num">${tk(n)}</b><small>${n.toLocaleString()}</small></span>`;
  const total = AID.total || aiSum(Object.keys(AID.days || {}));
  box.innerHTML = `<div class="label">AI usage<span class="lr">All models</span></div>
    <div class="card ai-c3"><div><p>So far, since ${aiDay(AID.first)}</p>${col('In', total.in)}${col('Out', total.out)}</div></div>
    <p class="hint ai-note">Tokens in and out. Days run midnight to midnight (server time). Open WebUI and n8n aren’t counted.</p>`;
}
async function loadAI() {
  try { const r = await fetch('/api/bot/sg/ai', { cache: 'no-store' }); AID = r.ok ? await r.json() : null; } catch { AID = null; }
  renderAI();
}
(() => {  // a box at the end of Server and Apps, filled each time that page opens
  const v = $('#v-server'); if (!v || $('#ai-use')) return;
  v.insertAdjacentHTML('beforeend', '<div id="ai-use"></div>');
  new MutationObserver(() => { if (!v.hidden) loadAI(); }).observe(v, { attributes: true, attributeFilter: ['hidden'] });
  if (!v.hidden) loadAI();
})();
