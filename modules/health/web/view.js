// ---------- Health: medicines on your own schedule and appointments you add yourself (reminders only, not medical advice) ----------
var SGD = null;
const SG_TICK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const SG_EVERY = [['day', 'Every day'], ['week', 'Every week'], ['2weeks', 'Every 2 weeks'], ['month', 'Every month']];
const SG_WD = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'];
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
// The tab shows your first name (from Settings, You), or User until you add one
CFG_READY.then(() => {
  const b = document.querySelector('.tab[data-tab="sg"]'); if (!b) return;
  const t = [...b.childNodes].find((n) => n.nodeType === 3 && n.textContent.trim());
  if (t) t.replaceWith(Object.assign(document.createElement('span'), { className: 'tab-n', textContent: (CFG.name || '').trim().split(/\s+/)[0] || 'User' }));
});
const sgDate = (d) => new Date(d + 'T12:00:00');
const sgDays = (d) => Math.round((sgDate(d) - sgDate(SGD.date || SGD.today)) / 86400000);
const sgShort = (d) => sgDate(d).toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' });
const sgWhen = (d) => { const n = sgDays(d); return n === 0 ? 'Today' : n === 1 ? 'Tomorrow' : n < 14 ? `In ${n} days` : n < 70 ? `In ${Math.round(n / 7)} weeks` : `In ${Math.round(n / 30.4)} months`; };
const sgT12 = (t) => { const [h, m] = t.split(':').map(Number); return `${h % 12 || 12}${m ? ':' + String(m).padStart(2, '0') : ''} ${h < 12 ? 'AM' : 'PM'}`; };
const sgList = (a) => a.length < 2 ? a.join('') : `${a.slice(0, -1).join(', ')} and ${a[a.length - 1]}`;
const sgNth = (n) => n + (n % 10 === 1 && n !== 11 ? 'st' : n % 10 === 2 && n !== 12 ? 'nd' : n % 10 === 3 && n !== 13 ? 'rd' : 'th');
function sgPlan(m) {  // "Every day at 8 AM and 8 PM", "Every Monday at 9 AM", ...
  const at = `at ${sgList(m.times.map(sgT12))}`;
  const s = m.every === 'day' ? `Every day ${at}` : m.every === 'week' ? `Every ${SG_WD[m.weekday]} ${at}` : m.every === '2weeks' ? `Every 2 weeks ${at}` : `Every month on the ${sgNth(m.monthday)} ${at}`;
  if (!m.next) return 'Finished';
  return s + (m.stop_after ? `, ${m.stop_after} ${m.every === 'day' ? 'days' : 'doses'}` : '');
}
function renderSG() {
  const D = SGD, today = D.log[D.today] || {}, doses = D.doses;
  const done = doses.filter((x) => today[x.key]).length;
  const tg = (x) => x.remind && D.telegram ? '<em class="sg-pill">Telegram</em>' : '';
  const todayHTML = `<div class="label">Today<span class="la">${doses.length ? `<span class="lr" id="sg-mcount">${done} of ${doses.length}</span>` : ''}<button class="sg-add" data-sgnew="med">+ Add</button></span></div>
    <div class="card sg-list">${doses.map((x) => `<button class="sg-row${today[x.key] ? ' taken' : ''}" data-sgtick="${esc(x.key)}" aria-pressed="${!!today[x.key]}">
      <span class="sg-time">${sgT12(x.time)}</span><span class="t"><b>${esc(x.name)}${tg(x)}</b><small>${esc(x.dose || (x.of ? `Dose ${x.n} of ${x.of}` : SG_EVERY.find((e) => e[0] === x.every)[1]))}</small></span>
      <span class="sg-tick${today[x.key] ? ' on' : ''}">${SG_TICK}</span></button>`).join('')
      || `<div class="empty">${D.meds.length ? 'Nothing due today.' : 'No medicines yet. Tap <b>+ Add</b> to add your first.'}</div>`}</div>`;
  const soon = [...D.meds.filter((m) => m.every !== 'day' && m.next && m.next > D.today && sgDays(m.next) <= 60).map((m) => ({ d: m.next, html:
      `<button class="sg-row" data-sgedit="${esc(m.id)}"><span class="t"><b>${esc(m.name)}</b><small>${SG_EVERY.find((e) => e[0] === m.every)[1]}, next ${sgShort(m.next)}, ${sgT12(m.times[0])}</small></span><span class="r"><small>${sgWhen(m.next)}</small></span></button>` })),
    ...D.health.map((h) => ({ d: h.due, html: `<button class="sg-row" data-sgappt="${esc(h.id)}"><span class="t"><b>${esc(h.name)}</b><small>${esc(h.why ? `Appointment, ${h.why}` : 'Appointment')}</small></span>
      <span class="r"><b>${sgShort(h.due)}</b><small class="${sgDays(h.due) <= 14 ? 'soon' : ''}">${sgWhen(h.due)}</small></span></button>` }))].sort((a, b) => a.d < b.d ? -1 : 1);
  const soonHTML = `<div class="label">Coming up<button class="sg-add" data-sgnew="appt">+ Appointment</button></div>
    <div class="card sg-list">${soon.map((x) => x.html).join('') || '<div class="empty">Nothing in the next two months.</div>'}</div>`;
  const listHTML = D.meds.length ? `<div class="label">Your medicines</div><div class="card sg-list">${D.meds.map((m) => `<button class="sg-row" data-sgedit="${esc(m.id)}">
      <span class="t"><b>${esc(m.name)}</b><small>${esc(sgPlan(m))}</small></span><span class="chev">${CHEV}</span></button>`).join('')}</div>` : '';
  const note = '<p class="hint">A tick-list to help you remember. It is not medical advice. Always follow your doctor’s instructions.</p>';
  $('#sg-body').innerHTML = todayHTML + soonHTML + listHTML + note + '<div id="sg-ai"></div>';
  renderAI();
}

// ---------- The sheet: add or change a medicine or an appointment ----------
const SGF = { kind: 'med', m: null };
function sgSheet() {
  let w = $('#sgs'); if (w) return w;
  document.body.insertAdjacentHTML('beforeend', `<div class="sheet-wrap" id="sgs" hidden><div class="sheet-bg" data-sgclose></div>
    <div class="sheet" role="dialog" aria-modal="true" aria-labelledby="sgs-t"><div class="grab"></div>
    <div class="sheet-head"><button class="done" data-sgclose>Cancel</button><h2 id="sgs-t"></h2><div class="head-acts"></div></div>
    <div class="sheet-body sg-f" id="sgs-b"></div></div></div>`);
  w = $('#sgs');
  if (typeof sheetDrag === 'function') sheetDrag(w, sgClose);
  w.addEventListener('click', sgSheetClick);
  w.addEventListener('input', () => SGF.kind === 'med' && sgHint());
  return w;
}
function sgClose() { const w = $('#sgs'); if (w) w.hidden = true; }
function sgOpenMed(m) {
  const t = SGD.today;
  SGF.kind = 'med';
  const fresh = { name: '', dose: '', every: 'day', times: ['08:00'], weekday: (sgDate(t).getDay() + 6) % 7, monthday: Math.min(sgDate(t).getDate(), 28), start: t, remind: SGD.telegram };
  SGF.m = { ...fresh, ...(m ? JSON.parse(JSON.stringify(m)) : {}) };  // a daily one switched to weekly starts on today's weekday
  SGF.stop = !!SGF.m.stop_after;
  sgSheet().hidden = false; $('#sgs-t').textContent = m ? 'Change medicine' : 'Add a medicine';
  sgDrawMed();
}
function sgRead() {  // what is in the form now, kept in SGF.m so switching "How often" does not lose anything
  const f = $('#sgs-b'), m = SGF.m, v = (s) => f.querySelector(s)?.value;
  m.name = v('#sgf-name') ?? m.name; m.dose = v('#sgf-dose') ?? m.dose;
  const ts = [...f.querySelectorAll('.sgf-time')].map((i) => i.value).filter(Boolean); if (ts.length) m.times = ts;
  if (v('#sgf-start')) m.start = v('#sgf-start');
  if (v('#sgf-mday')) m.monthday = +v('#sgf-mday');
  if (v('#sgf-stop')) m.stop_after = +v('#sgf-stop');
  return m;
}
function sgDrawMed() {
  const m = SGF.m, chip = (on, attr, label) => `<button type="button" class="sg-chip${on ? ' on' : ''}" ${attr}>${label}</button>`;
  const time = (t, i) => `<span class="sg-tin"><input class="sgf-time" type="time" value="${esc(t)}" aria-label="Time ${i + 1}">${m.every === 'day' && m.times.length > 1 ? `<button type="button" data-sgrmt="${i}" aria-label="Remove this time">✕</button>` : ''}</span>`;
  const times = m.every === 'day' ? m.times : m.times.slice(0, 1);
  const when = m.every === 'week' ? `<label>On</label><div class="sg-days">${SG_WD.map((d, i) => chip(m.weekday === i, `data-sgwd="${i}" aria-label="${d}"`, d[0])).join('')}</div>`
    : m.every === '2weeks' ? `<label for="sgf-start">First one</label><input id="sgf-start" type="date" value="${esc(m.start)}">`
    : m.every === 'month' ? `<label for="sgf-mday">On day</label><select id="sgf-mday">${[...Array(28)].map((_, i) => `<option value="${i + 1}"${m.monthday === i + 1 ? ' selected' : ''}>${sgNth(i + 1)}</option>`).join('')}</select>` : '';
  const remind = SGD.telegram
    ? `<div class="sg-swrow"><span><b>Remind me on Telegram</b><small>At each time, with Done, 5 min and 15 min</small></span>${swHTML(m.remind, 'sg-remind', 'Remind me on Telegram')}</div>`
    : `<p class="hint">Want a reminder at each time? Connect Telegram in Settings, then turn it on here.</p>`;
  $('#sgs-b').innerHTML = `<label for="sgf-name">Name</label><input id="sgf-name" value="${esc(m.name)}" maxlength="60" placeholder="Vitamin D" autocomplete="off">
    <label for="sgf-dose">How much (optional)</label><input id="sgf-dose" value="${esc(m.dose || '')}" maxlength="60" placeholder="1 tablet" autocomplete="off">
    <label>How often</label><div class="sg-chips">${SG_EVERY.map(([k, l]) => chip(m.every === k, `data-sgev="${k}"`, l)).join('')}</div>
    ${when}<label>At</label><div class="sg-times">${times.map(time).join('')}${m.every === 'day' && m.times.length < 6 ? '<button type="button" class="sg-chip ghost" data-sgaddt>+ Add a time</button>' : ''}</div>
    <p class="hint" id="sgf-hint"></p>
    <label>Stop after (optional)</label><div class="sg-chips">${chip(!SGF.stop, 'data-sgstop="0"', 'Keep going')}${chip(SGF.stop, 'data-sgstop="1"', 'Stop after')}</div>
    ${SGF.stop ? `<div class="sg-stop"><input id="sgf-stop" type="number" inputmode="numeric" min="1" max="999" value="${m.stop_after || 6}" aria-label="How many"><span>${m.every === 'day' ? 'days' : 'doses'}</span></div>` : ''}
    ${remind}<div class="err-t" id="sgf-err"></div><button class="sg-go" data-sgsave>Save</button>${m.id ? '<button class="sg-del" data-sgdel>Delete medicine</button>' : ''}`;
  sgHint();
}
function sgHint() {  // the next few dates, so the schedule can be checked at a glance
  const m = sgRead(), h = $('#sgf-hint'); if (!h) return;
  if (m.every !== '2weeks' || !m.start) { h.textContent = ''; h.hidden = true; return; }
  const d = sgDate(m.start), next = [1, 2, 3].map((i) => { const x = new Date(d); x.setDate(x.getDate() + 14 * i); return x.toLocaleDateString(undefined, { day: 'numeric', month: 'short' }); });
  h.hidden = false; h.textContent = `Then every 2 weeks: ${next.join(', ')}.`;
}
function sgOpenAppt(h) {
  SGF.kind = 'appt'; SGF.m = h ? { ...h } : { name: '', due: '', why: '' };
  sgSheet().hidden = false; $('#sgs-t').textContent = h ? 'Change appointment' : 'Add an appointment';
  $('#sgs-b').innerHTML = `<label for="sgf-name">Name</label><input id="sgf-name" value="${esc(SGF.m.name)}" maxlength="60" placeholder="Dentist check-up" autocomplete="off">
    <label for="sgf-due">Date</label><input id="sgf-due" type="date" value="${esc(SGF.m.due)}">
    <label for="sgf-why">Note (optional)</label><input id="sgf-why" value="${esc(SGF.m.why || '')}" maxlength="80" placeholder="6-month check" autocomplete="off">
    <div class="err-t" id="sgf-err"></div><button class="sg-go" data-sgsave>Save</button>${h ? '<button class="sg-del" data-sgdel>Delete appointment</button>' : ''}`;
}
async function sgSheetClick(e) {
  const t = e.target.closest('button, .sheet-bg'); if (!t) return;
  if (t.matches('[data-sgclose]')) return sgClose();
  if (SGF.kind === 'med' && !t.matches('[data-sgsave], [data-sgdel]')) {
    const m = sgRead();
    if (t.dataset.sgev) { m.every = t.dataset.sgev; if (m.every !== 'day') m.times = m.times.slice(0, 1); }
    else if (t.dataset.sgwd) m.weekday = +t.dataset.sgwd;
    else if ('sgaddt' in t.dataset) m.times.push(m.times.length ? sgT24(+m.times[m.times.length - 1].slice(0, 2) + 12) : '08:00');
    else if (t.dataset.sgrmt) m.times.splice(+t.dataset.sgrmt, 1);
    else if (t.dataset.sgstop) SGF.stop = t.dataset.sgstop === '1';
    else if (t.dataset.sw === 'sg-remind') { m.remind = !m.remind; t.setAttribute('aria-checked', m.remind); return; }
    else return;
    return sgDrawMed();
  }
  if (t.matches('[data-sgdel]')) {
    const med = SGF.kind === 'med';
    if (!await confirmSheet({ title: med ? 'Delete this medicine?' : 'Delete this appointment?', text: SGF.m.name, ok: 'Delete', danger: true })) return;
    return sgSend(med ? '/sg/med/delete' : '/sg/appt/delete', { id: SGF.m.id });
  }
  if (SGF.kind === 'med') {
    const m = sgRead(), body = { ...m, stop_after: SGF.stop ? m.stop_after : null, remind: SGD.telegram && m.remind };
    if (!body.name.trim()) return sgErr('Give it a name.');
    return sgSend('/sg/med', body);
  }
  const f = $('#sgs-b');
  return sgSend('/sg/appt', { id: SGF.m.id, name: f.querySelector('#sgf-name').value, due: f.querySelector('#sgf-due').value, why: f.querySelector('#sgf-why').value });
}
const sgT24 = (h) => `${String(h % 24).padStart(2, '0')}:00`;
const sgErr = (msg) => { const x = $('#sgf-err'); if (x) x.textContent = msg; };
async function sgSend(path, body) {
  const b = $('#sgs-b [data-sgsave]'); if (b) b.disabled = true;
  try { SGD = await sgFetch(path, body); sgClose(); renderSG(); }
  catch (err) { sgErr(err.msg || 'That did not save. Try again.'); if (b) b.disabled = false; }
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
  const n = e.target.closest('[data-sgnew]'); if (n) return n.dataset.sgnew === 'appt' ? sgOpenAppt() : sgOpenMed();
  const ed = e.target.closest('[data-sgedit]'); if (ed) return sgOpenMed(SGD.meds.find((m) => m.id === ed.dataset.sgedit));
  const ap = e.target.closest('[data-sgappt]'); if (ap) return sgOpenAppt(SGD.health.find((h) => h.id === ap.dataset.sgappt));
  const t = e.target.closest('[data-sgtick]'); if (!t) return;
  const id = t.dataset.sgtick, day = (SGD.log[SGD.today] ||= {}), on = !day[id];
  if (on) day[id] = true; else delete day[id];
  t.classList.toggle('taken', on); t.setAttribute('aria-pressed', on); t.querySelector('.sg-tick').classList.toggle('on', on);  // in place: nothing moves
  const c = $('#sg-mcount'); if (c) c.textContent = `${SGD.doses.filter((x) => day[x.key]).length} of ${SGD.doses.length}`;
  try { SGD = await sgFetch('/sg/tick', { date: SGD.today, id, done: on }); } catch { loadSG(); }
});
