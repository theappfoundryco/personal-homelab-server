// ---------- Health: medicines, courses and appointments you add yourself (reminders only, not medical advice) ----------
var SGD = null;
const SG_TICK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
async function sgFetch(u, body) {
  const r = await fetch('/api/bot' + u, { method: body ? 'POST' : 'GET', cache: 'no-store', body: body ? JSON.stringify(body) : undefined,
    headers: body ? { 'Content-Type': 'application/json' } : {} });
  const j = await r.json(); if (!r.ok) throw Object.assign(new Error('failed'), { msg: j.msg });
  return j;
}
async function loadSG() {
  if (!SGD) $('#sg-body').innerHTML = '<div class="skel"></div><div class="skel"></div>';
  try { [SGD, AID] = await Promise.all([sgFetch('/sg'), sgFetch('/sg/ai').catch(() => null)]); renderSG(); }
  catch { $('#sg-body').innerHTML = '<div class="err">Couldn’t load this right now. Try again in a minute.</div>'; }
}
const sgDate = (d) => new Date(d + 'T12:00:00');
const sgDays = (d) => Math.round((sgDate(d) - sgDate(SGD.date || SGD.today)) / 86400000);
const sgShort = (d) => sgDate(d).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const sgWhen = (d) => { const n = sgDays(d); return n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n < 14 ? `In ${n} days` : n < 70 ? `In ${Math.round(n / 7)} weeks` : `In ${Math.round(n / 30.4)} months`; };
function sgMeds() {
  const D = SGD;
  const dose = (c) => c.doses.indexOf(D.today) + 1;  // by the meds day (turns over at 4 AM), not the calendar date
  return [...D.courses.filter(dose).map((c) => ({ id: c.id, label: c.name, sub: `Weekly • dose ${dose(c)} of ${c.weeks}` })),
    ...D.slots.map((x) => ({ id: x.id, label: x.label, sub: x.items.join(', ') }))];
}
function renderSG() {
  const D = SGD, today = D.log[D.today] || {}, meds = sgMeds();
  const medsHTML = `<div class="label">Today’s meds<span class="lr" id="sg-mcount">${meds.filter((m) => today[m.id]).length} of ${meds.length}</span></div>
    <div class="card sg-list">${meds.map((m) => `<button class="sg-row${today[m.id] ? ' taken' : ''}" data-sgtick="${m.id}" aria-pressed="${!!today[m.id]}">
      <span class="sg-tick${today[m.id] ? ' on' : ''}">${SG_TICK}</span><span class="t"><b>${esc(m.label)}</b><small>${esc(m.sub)}</small></span></button>`).join('')
      || '<div class="empty">No medicines added yet.</div>'}</div>`;
  const healthHTML = `<div class="label">Health</div><div class="card sg-list">${D.courses.map((c) => {
      const sub = !c.next ? 'Course finished' : (c.next === D.today ? 'Due today' : `Next ${sgShort(c.next)}`) + ` • ends ${sgShort(c.ends)}`;
      return `<div class="sg-row"><span class="t"><b>${esc(c.name)}</b><small>${c.taken} of ${c.weeks} doses • ${sub}</small>
        <span class="sg-dots" aria-hidden="true">${c.doses.map((d) => `<i class="${D.log[d]?.[c.id] ? 'on' : ''}${d === D.today ? ' now' : ''}"></i>`).join('')}</span></span></div>`; }).join('')}
    ${D.health.map((h) => `<div class="sg-row"><span class="t"><b>${esc(h.name)}</b><small>${esc(h.why || '')}</small></span>
      <span class="r"><b>${sgShort(h.due)}</b><small>${sgWhen(h.due)}</small></span></div>`).join('')
      || (D.courses.length ? '' : '<div class="empty">No appointments or courses yet.</div>')}</div>`;
  const note = '<p class="hint">A tick-list to help you remember. It is not medical advice. Always follow your doctor’s instructions.</p>';
  $('#sg-body').innerHTML = medsHTML + healthHTML + note + '<div id="sg-ai"></div>';
  renderAI();
}

// ---------- SG: AI usage (tokens in and out of the local model, Monday to Sunday, days split at midnight, server time) ----------
var AID = null;
const aiAdd = (d, n) => { const x = sgDate(d); x.setDate(x.getDate() + n); return isoDay(x); };
const tk = (n) => n >= 1e6 ? +(n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : n >= 1e3 ? +(n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + 'k' : String(Math.round(n));
const aiSum = (ds, kind) => ds.reduce((a, d) => { for (const [k, v] of Object.entries(AID.days[d] || {})) if (!kind || k === kind) { a.in += v.in; a.out += v.out; a.calls += v.calls; } return a; }, { in: 0, out: 0, calls: 0 });
function renderAI() {
  if (!AID) { $('#sg-ai').innerHTML = '<div class="err">Couldn’t load AI usage right now. Try again in a minute.</div>'; return; }
  const t = AID.today, mon = aiAdd(t, -((sgDate(t).getDay() + 6) % 7)), week = [...Array(7)].map((_, i) => aiAdd(mon, i)).filter((d) => d <= t);
  const col = (a, n) => `<span><small>${a}</small><b class="num">${tk(n)}</b><small>${n.toLocaleString('en-IN')}</small></span>`;
  const row = (a, x) => `<div><p>${a}</p>${col('In', x.in)}${col('Out', x.out)}</div>`;
  $('#sg-ai').innerHTML = `<div class="label">AI usage<span class="lr">All models</span></div>
    <div class="card ai-c3">${row(`So far, since ${sgShort(AID.first)}`, AID.total || aiSum(week))}</div>
    <p class="hint ai-note">Tokens in and out. Days run midnight to midnight (server time). Open WebUI and n8n aren’t counted.</p>`;
}
$('#sg-body').addEventListener('click', async (e) => {
  const t = e.target.closest('[data-sgtick]'); if (!t) return;
  const id = t.dataset.sgtick, day = (SGD.log[SGD.today] ||= {}), on = !day[id];
  if (on) day[id] = true; else delete day[id];
  t.classList.toggle('taken', on); t.setAttribute('aria-pressed', on); t.querySelector('.sg-tick').classList.toggle('on', on);  // in place: nothing moves
  const meds = sgMeds(); $('#sg-mcount').textContent = `${meds.filter((m) => day[m.id]).length} of ${meds.length}`;
  try { SGD = await sgFetch('/sg/tick', { date: SGD.today, id, done: on }); } catch { loadSG(); }
});
