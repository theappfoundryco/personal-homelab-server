// ---------- Notes ----------
// Planner: one box for notes, reminders and goals. While he speaks, the server's quick rules label it at once.
// On Add the row waits in that section (pulsing dot) while the AI (loaded on demand, freed after 5 idle minutes) gives the verdict;
// a tap on another type first skips the AI and teaches it.
const KINDS = { note: 'Note', reminder: 'Reminder', goal: 'Goal' };
let forced = null, remWhen = null, peek = { kind: 'note' }, peekT = 0, peekN = 0, pending = [];
const grow = () => { const ta = $('#add-text'); ta.style.height = 'auto'; ta.style.height = ta.scrollHeight + 'px'; ta.style.overflowY = ta.scrollHeight > innerHeight * 0.4 ? 'auto' : 'hidden'; };
const capKind = () => forced || (remWhen ? 'reminder' : peek.kind);
async function capPeek(t) {
  const n = ++peekN;
  let p; try { p = t ? await post('/api/bot/capture/peek', { text: t }) : { kind: 'note' }; } catch { p = null; }
  if (n !== peekN) return;  // he kept talking: a newer check is on its way
  if (p) peek = p;
  capHint();
}
function capHint() {
  const c = $('#composer'), h = $('#cap-hint'); if (!c || !h) return;
  const k = capKind(), t = $('#add-text').value.trim();
  c.querySelector('.chips').hidden = k !== 'reminder';
  if (!t && !forced && !remWhen) { h.innerHTML = '<span>Start with “goal”, or say a time.</span>'; return; }
  const when = k !== 'reminder' || remWhen ? '' : peek.need || (!peek.when && peek.sure !== false) ? 'add a time below' : peek.sure !== false ? esc(peek.when) : 'I’ll work out the times';
  h.innerHTML = `<button type="button" class="cap-kind" data-kind-pick aria-label="Saving as ${KINDS[k]}. Change it">${KINDS[k]}${PEN}</button>${when ? `<span>${when}</span>` : ''}`;
}
function pickKind() {  // "Save as": one tap sets it and closes
  const box = $('#kindp'), cur = capKind(), ic = { note: PIC.note, reminder: PIC.bell, goal: PIC.peak };
  $('#kind-opts').innerHTML = Object.entries(KINDS).map(([k, l]) => `<button data-k="${k}" class="${k === cur ? 'on' : ''}">${ic[k]}${l}</button>`).join('');
  box.hidden = false;
  const end = () => { box.hidden = true; box.onclick = null; document.removeEventListener('keydown', key, true); };
  const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); end(); } };
  document.addEventListener('keydown', key, true);
  box.onclick = (e) => {
    const b = e.target.closest('[data-k]');
    if (b) { forced = b.dataset.k === peek.kind ? null : b.dataset.k; if (b.dataset.k !== 'reminder') $('#composer [data-clear-pick]')?.click(); capHint(); end(); }
    else if (e.target.closest('[data-kind-no]')) end();
  };
}
function buildComposer() {
  const keep = $('#add-text')?.value || '';
  if (!$('#composer')) {
    $('#notes-body').innerHTML = `<div class="card composer" id="composer"></div><div id="notes-lists"><div class="skel"></div></div>
      <p class="hint">Just say it: the AI on your server decides if it’s a note, a reminder or a goal, and learns when you change it. Tap the circle when a note is done and the target when a goal is achieved. Reminders reach you on Telegram and as a phone alert.</p>`;
    $('#notes-lists').onclick = listTap;
  }
  const c = $('#composer');
  c.innerHTML = `
      <form class="add" id="add-form" autocomplete="off"><textarea id="add-text" rows="1" placeholder="Note, reminder or goal" enterkeyhint="done" aria-label="New note, reminder or goal"></textarea><button class="pill">Add</button></form>
      <div class="cap-hint" id="cap-hint" aria-live="polite"></div>
      <div class="cap-busy" id="cap-busy" hidden></div>
      <div class="chips" hidden>
        <button type="button" class="chip" data-in="60">In 1 hour</button>
        <button type="button" class="chip" data-at="21:00">Tonight 9 PM</button>
        <button type="button" class="chip" data-at="+09:00">Tomorrow 9 AM</button>
        <label class="chip" id="pick-chip">Pick a time<input type="datetime-local" id="pick"></label>
      </div>
      <div class="toast" id="toast"></div>`;
  const local = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
  const pickChip = (el, when) => { c.querySelectorAll('.chip').forEach((x) => x.classList.toggle('on', x === el && remWhen !== when ? true : false));
    remWhen = el.classList.contains('on') ? when : null; if (remWhen) forced = null; capHint(); $('#add-text').focus(); };
  c.querySelectorAll('.chip[data-in]').forEach((x) => x.onclick = () => pickChip(x, local(new Date(Date.now() + x.dataset.in * 60000))));
  c.querySelectorAll('.chip[data-at]').forEach((x) => x.onclick = () => {
    const d = new Date(), tom = x.dataset.at.startsWith('+'), [h, m] = x.dataset.at.replace('+', '').split(':').map(Number);
    d.setHours(h, m, 0, 0); if (tom || d < new Date()) d.setDate(d.getDate() + 1); pickChip(x, local(d)); });
  const clearPick = () => { remWhen = null; c.querySelectorAll('.chip').forEach((x) => x.classList.remove('on')); $('#pick-chip').firstChild.textContent = 'Pick a time'; $('#pick').value = ''; };
  $('#pick').onchange = () => { const v = $('#pick').value; c.querySelectorAll('.chip').forEach((x) => x.classList.remove('on'));
    if (v) { $('#pick-chip').classList.add('on'); $('#pick-chip').firstChild.textContent = new Date(v).toLocaleString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', hour12: true }).replace(/\b(am|pm)\b/g, (x) => x.toUpperCase()); remWhen = v; forced = null; } else remWhen = null;
    capHint(); };
  $('#cap-hint').onclick = (e) => { if (e.target.closest('[data-kind-pick]')) pickKind(); };
  c.insertAdjacentHTML('beforeend', '<button type="button" data-clear-pick hidden></button>');  // lets the sheet clear a picked time
  c.querySelector('[data-clear-pick]').onclick = clearPick;
  const ta = $('#add-text');
  ta.value = keep; grow();
  ta.oninput = () => {
    grow(); clearTimeout(peekT);
    const t = ta.value.trim();
    if (!t) forced = null;  // a cleared box starts fresh
    peekT = setTimeout(() => { peekT = 0; capPeek(t); }, 250);
    capHint();
  };
  ta.onkeydown = (e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); $('#add-form').requestSubmit(); } };  // Enter adds, Shift+Enter is a new line
  capPeek(keep.trim());
  capBusy();  // the composer is rebuilt on every load, so the hint is checked each time
  $('#add-form').onsubmit = async (e) => {
    e.preventDefault();
    const toast = $('#toast'), t = ta.value.trim();
    if (!t || pending.some((p) => p.text === t)) return;  // no double adds from a double tap
    clearTimeout(peekT); peekN++;
    const kind = forced || (remWhen ? 'reminder' : ''), p = { text: t, kind: kind || peek.kind, timed: !!remWhen };  // empty kind: the server asks the AI
    const body = { text: t, kind, guess: forced ? peek.kind : '', when: remWhen || '' };
    ta.value = ''; grow(); forced = null; peek = { kind: 'note' }; clearPick(); capHint();
    pending.push(p); drawLists();  // the row waits in its section while the AI decides; he can keep adding
    let r; try { r = await post('/api/bot/capture/save', body); }
    catch { r = { ok: false, error: 'The assistant isn’t reachable right now.' }; }
    pending = pending.filter((x) => x !== p);
    if (!r.ok) {  // give the words back so nothing is lost
      if (!ta.value.trim()) { ta.value = t; grow(); if (r.kind === 'reminder') forced = 'reminder'; capPeek(t); }
      drawLists(); return flash(toast, r.error, { bad: true });
    }
    await loadNotes();
  };
}
// While a big job has the AI's memory, an Add is a few seconds slower: say so, so it doesn't look stuck
async function capBusy() {
  const a = await getJSON('/api/bot/server/ai').catch(() => null), el = $('#cap-busy'); if (!el) return;
  el.hidden = !a?.busy;
  if (a?.busy) el.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg><span>The AI is ${esc(a.busy.toLowerCase())}. Adding takes a few seconds longer until it’s done.</span>`;
}
function openNotes() { $('#notesp').hidden = false; document.body.style.overflow = 'hidden'; $('#notesp .panel-body').scrollTop = 0; loadNotes(); }
function closeNotes() { const a = document.activeElement; if (a?.blur) a.blur(); $('#notesp').hidden = true; document.body.style.overflow = ''; }
$('#notes-open').onclick = openNotes;
document.querySelector('[data-close-notes]').onclick = closeNotes;
function notesSub(n) {  // Home tile: no counts, only a dot when a reminder is due today
  const today = new Date().toDateString(), due = n.reminders.filter((r) => new Date(r.due * 1000).toDateString() === today).length;
  $('#plan-dot').hidden = !due;
  $('#notes-open').setAttribute('aria-label', due ? `Planner, ${plural(due, 'reminder')} due today` : 'Planner');
}
getJSON('/api/bot/notes').then(notesSub).catch(() => {});
const PIC = {  // section icons: never the same as the marks on the rows below them
  bell: '<svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M6 16.5V11a6 6 0 0 1 12 0v5.5l1.5 2h-15z"/><path d="M10 21a2.2 2.2 0 0 0 4 0"/></svg>',
  note: '<svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14 3.5H7a2.5 2.5 0 0 0-2.5 2.5v12A2.5 2.5 0 0 0 7 20.5h10a2.5 2.5 0 0 0 2.5-2.5V9z"/><path d="M14 3.5V9h5.5M8.5 13h7M8.5 16.5h4.5"/></svg>',
  peak: '<svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2.5 20l7-11.5 4 6.5 2.5-3.5 5.5 8.5z"/><path d="M9.5 8.5V3.5l4 1.6-4 1.6"/></svg>',
  target: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"><circle cx="12" cy="12" r="8.5"/><circle cx="12" cy="12" r="4.5"/><circle cx="12" cy="12" r="1" fill="currentColor"/></svg>',
  tick: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>',
};
const pDate = (t) => new Date(t * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
let lastNotes = null;
async function loadNotes() {
  if (!$('#composer')) buildComposer();
  let n;
  try { n = await getJSON('/api/bot/notes'); } catch { if (!lastNotes) $('#notes-lists').innerHTML = '<div class="err">Your planner is unavailable right now.</div>'; return; }
  notesSub(n); lastNotes = n; drawLists();
}
const pendRows = (k) => pending.filter((p) => p.kind === k).map((p) => {
  const dot = '<i class="chk" aria-hidden="true"><i></i></i>', txt = `<span>${esc(p.text)}<br><small>${k === 'reminder' && !p.timed ? 'setting time' : 'saving'}</small></span>`;
  return `<div class="note pend" aria-label="Saving">${k === 'reminder' ? txt + dot : dot + txt}</div>`; }).join('');
function drawLists() {
  const lists = $('#notes-lists'), n = lastNotes; if (!lists) return;
  if (!n) { if (pending.length) lists.innerHTML = ['reminder', 'note', 'goal'].map((k) => pendRows(k) && `<div class="card sec">${pendRows(k)}</div>`).join(''); return; }
  const goals = n.goals || [], done = n.achieved || [], pr = pendRows('reminder'), pn = pendRows('note'), pg = pendRows('goal');
  lists.innerHTML = `
    <div class="card sec"><h3>${PIC.bell}Reminders<small>${n.reminders.length || ''}</small></h3>${pr}${n.reminders.length || pr ? n.reminders.map((r) => `<div class="note"><span>${esc(r.text)}<br><small>${esc(r.when)}${r.repeat ? ' • repeats ' + esc(r.repeat) : ''}</small></span><button class="chk" aria-label="Cancel reminder" data-cancel="${esc(r.id)}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg></button></div>`).join('') : '<div class="empty">No reminders.</div>'}${pastRow('reminders', n.past?.reminders, 'See done')}</div>
    <div class="card sec"><h3>${PIC.note}Notes<small>${n.notes.length || ''}</small></h3>${pn}${n.notes.length || pn ? n.notes.map((x) => `<div class="note"><button class="chk" aria-label="Mark done" data-done="${esc(x.id)}"></button><span>${esc(x.text)}</span></div>`).join('') : '<div class="empty">No notes yet.</div>'}${pastRow('notes', n.past?.notes, 'See done')}</div>
    <div class="card sec goals"><h3>${PIC.peak}Goals of life<small>${goals.length || ''}</small></h3>${pg}${goals.length || pg ? goals.map((g) => `<div class="note"><button class="chk tgt" aria-label="Mark achieved" data-achieve="${esc(g.id)}">${PIC.target}</button><span class="gtxt" data-goal="${esc(g.id)}" role="button" tabindex="0">${esc(g.text)}<br><small>Added ${pDate(g.added)}</small></span></div>`).join('') : '<div class="empty">Your life goals live here. Start with “Goal: …”.</div>'}
      ${pastRow('goals', done.length, 'See reached')}</div>`;
}
function goalSheet(id, text) {  // edit, achieve or delete; delete asks again
  const box = $('#goalp'), opts = $('#goal-opts');
  $('#goalp-t').textContent = 'Your goal'; $('#goalp-x').textContent = text;
  opts.innerHTML = `<button data-g="edit">${PEN}Edit text</button><button data-g="ach">${PIC.target}Mark achieved</button><button data-g="del" class="danger">${TRASH}Delete goal</button>`;
  box.hidden = false;
  const end = () => { box.hidden = true; box.onclick = null; document.removeEventListener('keydown', key, true); };
  const key = (e) => { if (e.key === 'Escape') { e.stopPropagation(); end(); } };
  document.addEventListener('keydown', key, true);
  box.onclick = async (e) => {
    if (e.target.closest('[data-goal-no]')) return end();
    const g = e.target.closest('[data-g]')?.dataset.g;
    if (g === 'edit') {
      $('#goalp-t').textContent = 'Edit goal'; $('#goalp-x').textContent = '';
      opts.innerHTML = `<textarea id="goal-ed" maxlength="300" aria-label="Goal"></textarea><button class="cfm-ok" data-g="save">Save</button>`;
      const ta = $('#goal-ed'); ta.value = text; ta.focus(); ta.setSelectionRange(text.length, text.length);
      return;
    }
    if (g === 'save') {
      const v = $('#goal-ed').value.trim(); if (!v) return;
      end(); await post('/api/bot/goals/edit', { id, text: v }).catch(() => {}); snack('Goal updated'); return loadNotes();
    }
    if (g === 'ach') { end(); await post('/api/bot/goals/achieve', { id }).catch(() => {}); snack('Goal achieved. Well done.'); return loadNotes(); }
    if (g === 'del') {
      end();
      if (!await confirmSheet({ title: 'Delete this goal?', text, ok: 'Delete goal', danger: true })) return;
      await post('/api/bot/goals/delete', { id }).catch(() => {}); snack('Goal deleted'); return loadNotes();
    }
  };
}
// ----- Past: every reminder that went off, note ticked off and goal reached, under plain time headings.
// It opens on the tab he came from; notes can be brought back, goals undone.
let pastData = null, pastTab = 'reminders';
const pastRow = (k, n, l) => `<button class="past-row" data-past="${k}">${l}<small>${n || ''}</small>${CHEV}</button>`;  // always there, so the way in never hides
const PAST_EMPTY = { reminders: 'Reminders show here after they go off.', notes: 'Notes you tick off show here.', goals: 'Goals you reach show here.' };
const PAST_Q = { reminders: 'Search past reminders', notes: 'Search past notes', goals: 'Search reached goals' };
function pastGroup(t) {
  const d = new Date(t * 1000), now = new Date(), day = new Date(d.getFullYear(), d.getMonth(), d.getDate()), today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const n = Math.round((today - day) / 864e5), wk = (today.getDay() + 6) % 7;  // days since Monday
  if (n <= 0) return 'Today';
  if (n === 1) return 'Yesterday';
  if (n <= wk) return 'Earlier this week';
  if (n <= wk + 7) return 'Last week';
  return d.toLocaleDateString('en-GB', { month: 'long', ...(d.getFullYear() !== now.getFullYear() && { year: 'numeric' }) });
}
const pDay = (t) => new Date(t * 1000).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const pTook = (a, b) => { const d = Math.max(1, Math.round((b - a) / 86400));  // seconds
  return d < 14 ? plural(d, 'day') : d < 60 ? plural(Math.round(d / 7), 'week') : d < 730 ? plural(Math.round(d / 30.4), 'month') : plural(Math.round(d / 365), 'year'); };
function pastRowHTML(x) {
  const t = pastTab === 'goals' ? x.achieved : x.at, near = ['Today', 'Yesterday'].includes(pastGroup(t)), when = near ? hhmm(t) : `${pDay(t)}, ${hhmm(t)}`;
  if (pastTab === 'reminders') return `<div class="note past"><i class="chk">${PIC.tick}</i><span>${esc(x.text)}<br><small>Went off ${when}</small></span></div>`;
  if (pastTab === 'notes') return `<div class="note past"><i class="chk">${PIC.tick}</i><span>${esc(x.text)}<br><small>Ticked off ${near ? when : pDay(t)}</small></span><button class="undo" data-pback="${esc(x.id)}">Bring back</button></div>`;
  return `<div class="note past"><i class="chk tgt">${PIC.peak}</i><span>${esc(x.text)}<br><small>Reached ${pDay(t)}${x.added ? ` • took ${pTook(x.added, t)}` : ''}</small></span><button class="undo" data-unach="${esc(x.id)}">Undo</button></div>`;
}
function renderPast() {
  document.querySelectorAll('[data-pt]').forEach((b) => b.classList.toggle('on', b.dataset.pt === pastTab));
  const box = $('#past-list'), raw = $('#past-q').value.trim(), q = raw.toLowerCase();
  $('#past-q').placeholder = PAST_Q[pastTab];
  if (!pastData) { box.innerHTML = '<div class="card" style="margin-top:20px"><div class="skel"></div></div>'; return; }
  const all = pastData[pastTab] || [], xs = q ? all.filter((x) => x.text.toLowerCase().includes(q)) : all;
  if (!xs.length) { box.innerHTML = `<div class="empty">${q ? `Nothing matches “${esc(raw)}”.` : PAST_EMPTY[pastTab]}</div>`; return; }
  const groups = [];
  for (const x of xs) { const g = pastGroup(pastTab === 'goals' ? x.achieved : x.at); if (groups.at(-1)?.[0] !== g) groups.push([g, []]); groups.at(-1)[1].push(x); }
  box.innerHTML = (pastTab === 'goals' && !q ? `<div class="card pgoal"><b class="num">${all.length}</b><small>${all.length === 1 ? 'goal' : 'goals'} reached</small></div>` : '')
    + groups.map(([g, ys]) => `<div class="label">${g}</div><div class="card pgrp">${ys.map(pastRowHTML).join('')}</div>`).join('');
}
async function openPast(tab) {
  pastTab = tab; $('#past-q').value = ''; $('#pastp').hidden = false; renderPast();
  try { pastData = await getJSON('/api/bot/past'); } catch { if (!pastData) { $('#past-list').innerHTML = '<div class="err" style="margin-top:20px">Your past items are unavailable right now.</div>'; return; } }
  renderPast();
}
function closePast() { $('#pastp').hidden = true; }
document.querySelector('[data-close-past]').onclick = closePast;
$('#pastp .ptabs').onclick = (e) => { const b = e.target.closest('[data-pt]'); if (b) { pastTab = b.dataset.pt; renderPast(); } };
$('#past-q').oninput = renderPast;
$('#past-list').onclick = async (e) => {
  const back = e.target.closest('[data-pback]'), un = e.target.closest('[data-unach]');
  if (!back && !un) return;
  const row = (back || un).closest('.note'); row.classList.add('gone');
  const r = await (back ? post('/api/bot/past/restore', { id: back.dataset.pback }) : post('/api/bot/goals/achieve', { id: un.dataset.unach, undo: true })).catch(() => null);
  if (!r?.ok) { row.classList.remove('gone'); return snack('Couldn’t bring it back. Try again.'); }
  snack(back ? 'Back in your notes' : 'Back in your goals');
  pastData = await getJSON('/api/bot/past').catch(() => pastData); renderPast(); loadNotes();
};
async function listTap(e) {
  const pr = e.target.closest('[data-past]');
  if (pr) return openPast(pr.dataset.past);
  const done = e.target.closest('[data-done]'), cancel = e.target.closest('[data-cancel]'), ach = e.target.closest('[data-achieve]'), un = e.target.closest('[data-unach]');
  if (ach) {  // a goal is never deleted: it moves to Achieved with the date
    if (!await confirmSheet({ title: 'Goal achieved?', text: ach.closest('.note').querySelector('span').firstChild.textContent, ok: 'Mark achieved' })) return;
    ach.innerHTML = PIC.tick; ach.closest('.note').classList.add('gone');
    await Promise.all([post('/api/bot/goals/achieve', { id: ach.dataset.achieve }).catch(() => {}), sleep(350)]);
    return loadNotes();
  }
  if (un) { await post('/api/bot/goals/achieve', { id: un.dataset.unach, undo: true }).catch(() => {}); return loadNotes(); }
  const gt = e.target.closest('[data-goal]');
  if (gt) return goalSheet(gt.dataset.goal, gt.firstChild.textContent);
  if (done) {  // ticks, fades out, then the list reloads
    done.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>'; done.closest('.note').classList.add('gone');
    await Promise.all([post('/api/bot/notes/done', { id: done.dataset.done }).catch(() => {}), sleep(350)]);
    return loadNotes();
  }
  if (!cancel) return;
  const what = cancel.closest('.note').querySelector('span').firstChild.textContent;
  if (!await confirmSheet({ title: 'Cancel this reminder?', text: what, ok: 'Cancel reminder', danger: true })) return;
  cancel.closest('.note').classList.add('gone');
  await Promise.all([post('/api/bot/reminders/delete', { id: cancel.dataset.cancel }).catch(() => {}), sleep(300)]);
  loadNotes();
}
