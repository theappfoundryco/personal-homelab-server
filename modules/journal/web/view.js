// ---------- Journal ----------
// One entry a day, talked in with Wispr Flow. It saves as you go; Done saves it; at 4:30 AM Gemma, on the server, adds a mood, tags and a summary.
const J_PROMPTS = ['What actually happened today?', 'What went well, or what are you proud of?', 'What drained you or got under your skin?',
  'How are your body and head, from 1 to 10?', 'What’s the one thing that matters tomorrow?'];
const J_SUNDAY = 'And the week as a whole: how was it?';
let J = null, jMonth = null, jOpen = null, jRange = 7, jFocus = false;
const jEdit = new Set();
const jWords = (t) => (String(t).match(/\S+/g) || []).length;
const jEntry = (d) => J && J.entries.find((e) => e.date === d);
// The words live in month files on the server: J.texts holds the months loaded so far, J.years the years whose index is here.
function jApply(r) {  // a fresh /journal answer: its years replace ours, older years and loaded words stay
  const keep = J ? J.entries.filter((e) => !r.years.includes(e.date.slice(0, 4))) : [];
  const texts = { ...(J?.texts || {}), ...r.texts }, years = new Set([...(J?.years || []), ...r.years]);
  J = { ...r, entries: [...keep, ...r.entries].sort((a, b) => (a.date < b.date ? -1 : 1)), texts, years };
  jAttach();
}
function jAttach() { J.entries.forEach((e) => { const t = J.texts[e.date.slice(0, 7)]; if (t && e.date in t) e.text = t[e.date]; }); }
async function jNeed(days) {  // load the words of these days' months, and their years' index, if not here yet
  const ys = [...new Set(days.map((d) => d.slice(0, 4)))].filter((y) => !J.years.has(y));
  const ms = [...new Set(days.map((d) => d.slice(0, 7)))].filter((m) => !J.texts[m]);
  await Promise.all([...ys.map(async (y) => { const r = await getJSON('/api/bot/journal/year?y=' + y);
      J.entries = [...J.entries.filter((e) => !e.date.startsWith(y)), ...r.entries].sort((a, b) => (a.date < b.date ? -1 : 1)); J.years.add(y); }),
    ...ms.map(async (m) => { const r = await getJSON('/api/bot/journal/month?m=' + m); J.texts[m] = r.texts; })].map((p) => p.catch(() => {})));
  jAttach();
}
const jMoodCls = (m) => (m >= 7 ? 'good' : m >= 4 ? 'warn' : 'bad');
const jClock = (s) => `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
const jShort = (d) => dParse(d).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
const jBusy = (box) => { const w = box.querySelector('.jw'); return w && (w.contains(document.activeElement) || w._dirty); };

async function loadJournal() {
  try { await Promise.all([getJSON('/api/bot/journal').then(jApply), jAi === null ? jAiCheck() : null]); }
  catch (e) { if (!J) { $('#j-today').innerHTML = '<div class="err">Your journal isn’t reachable right now. Try again in a minute.</div>'; return; } }
  jMonth = jMonth || J.today.slice(0, 7);
  // Up past midnight, tonight's entry is still the day that's ending (until 4 AM); say so instead of looking a day behind
  $('#j-sub').textContent = longDate(J.today) + (J.date && J.date > J.today ? ' • counts as tonight until 4 AM' : '');
  if (jFocus) jWrite = true;  // came here to write: open the writer straight away
  renderJToday(); renderCal(); jWeekLoad().then(renderJWeek); renderJDeep(); jdLoad().then(() => { renderJDeep(); renderJLetter(); });
  if (jOpen) renderEntry();
  if (jFocus) { jFocus = false; const ta = $('#j-today [data-jt]'); if (ta) { ta.focus({ preventScroll: true }); ta.setSelectionRange(ta.value.length, ta.value.length); } }
}

function writerHTML(d) {
  if (jEntry(d) && jEntry(d).text === undefined) return '<div class="card"><div class="skel"></div></div>';
  const e = jEntry(d), qs = [...J_PROMPTS, ...(dParse(d).getDay() === 0 ? [J_SUNDAY] : [])];
  return `<div class="card jw" data-jw="${d}">
    ${e?.text?.trim() ? `<details class="jqd"><summary>${CHEV}Prompts</summary><ol class="jq">${qs.map((q) => `<li>${esc(q)}</li>`).join('')}</ol></details>`
      : `<ol class="jq">${qs.map((q) => `<li>${esc(q)}</li>`).join('')}</ol>`}
    <textarea data-jt placeholder="Start writing, or dictate with your keyboard's microphone." aria-label="Journal entry for ${esc(longDate(d))}">${esc(e?.text || '')}</textarea>
    <div class="jfoot"><span class="jtm" data-jtm title="Time spent writing"></span><span class="jwc" data-jwc></span><span class="jst" data-jst>${e ? 'Saved' : ''}</span>
      <button class="jclose" data-jclose aria-label="Close the writer" title="Close (what you wrote is kept)">${XMARK}</button><button class="jsave" data-jdone>Done</button></div></div>`;
}
// a finished entry the night run hasn't read yet: no mood or summary to show
const jThinking = (e) => !!e && !!e.sum_due && !e.ai_at;
// from 7 AM until tonight's entry is done, today's slot waits for its summary (purple line, purple bar)
const jAwait = (d) => !!J && d === J.today && !jEntry(d)?.done && (new Date().getHours() >= 7 || J.date !== J.today);
function jViewHTML(e, inTab) {
  const thinking = jThinking(e);
  return `<div class="card jdn" ${inTab ? `data-jread="${e.date}" role="button" tabindex="0"` : ''}>
    <div class="jdn-h">${e.mood && !thinking ? `<button class="jmood ${jMoodCls(e.mood)}" data-jmood="${e.date}" aria-label="Mood ${e.mood} out of 10${e.mood_set ? ', your score' : ''}. Change it"><b class="num">${e.mood}</b><small>/10</small></button>` : '<span class="jmood"><b>–</b></span>'}
      <div><b>${inTab ? 'Tonight’s entry' : esc(longDate(e.date))}</b><small>${e.words} ${e.words === 1 ? 'word' : 'words'}${e.secs >= 60 ? ` • ${Math.round(e.secs / 60)} min` : ''}${e.mood_set && !thinking ? ' • <span class="jmine">your score</span>' : ''}</small></div>
      <button class="icon-btn" data-jedit="${e.date}" aria-label="Edit this entry">${PEN}</button></div>
    ${thinking ? jWait('<b>Summary pending.</b> Your mood and summary arrive by morning.') : e.summary ? `<p class="jsum">${esc(e.summary)}</p>` : ''}${!thinking && e.sum_due ? jWait(e.summary ? '<b>Summary pending.</b> A fresh one arrives by morning.' : '<b>Summary pending.</b> Your mood and summary arrive by morning.') : ''}
    ${e.tags?.length ? `<div class="jtags">${e.tags.map((t) => `<span>${esc(t)}</span>`).join('')}</div>` : ''}
    <div class="jtext">${e.text === undefined ? '<div class="skel"></div>' : esc(e.text)}</div></div>`;
}
function jWire(box) {
  box.querySelectorAll('.jw').forEach((w) => {
    const d = w.dataset.jw, ta = w.querySelector('[data-jt]');
    w._secs = jEntry(d)?.secs || 0; w._ver = 0;
    let draft = null; try { draft = localStorage.getItem('jdraft:' + d); } catch (e) {}
    if (draft && draft.trim() && draft !== ta.value) { ta.value = draft; w._dirty = true; w._ver = 1; jQueue(w); }  // never sent: send it now
    jCount(w);
  });
}
function jCount(w) {
  const n = jWords(w.querySelector('[data-jt]').value), wc = w.querySelector('[data-jwc]'), tm = w.querySelector('[data-jtm]');
  wc.textContent = n < 150 ? `${n} of 150 words` : `${n} words`;
  wc.classList.toggle('ok', n >= 150);
  tm.textContent = jClock(w._secs); tm.classList.toggle('ok', w._secs >= 600);
}
function jQueue(w) { clearTimeout(w._deb); w._deb = setTimeout(() => jSave(w), 1500); w.querySelector('[data-jst]').textContent = ''; }

let jWrite = false;  // tonight's writer is open (it opens when you tap Start or Continue)
function jStartHTML(d) {
  const e = jEntry(d); let draft = ''; try { draft = localStorage.getItem('jdraft:' + d) || ''; } catch (x) {}
  const n = jWords(draft.trim() ? draft : e?.text || '');
  const sub = n ? `${plural(n, 'word')}${e?.updated ? ` • saved ${hhmm(e.updated)}` : ''}` : 'About ten minutes. Talk it through with Wispr Flow.';
  return `<div class="card jstart"><div class="jstart-h"><span class="jic">${PEN}</span><div><b>${n ? 'Continue tonight’s entry' : 'Tonight’s entry'}</b><small>${sub}</small></div></div>
    ${jAwait(d) ? jWait('<b>Summary pending.</b> Write tonight and your mood and summary arrive by morning.') : ''}
    <button class="jgo" data-jwrite>${n ? 'Continue writing' : 'Start writing'}${ARROW}</button></div>`;
}
function renderJToday() {
  const box = $('#j-today'), d = J.today, e = jEntry(d);
  if (jBusy(box) && box.querySelector('.jw').dataset.jw === d) return;  // don't touch it while you're talking
  box.innerHTML = e?.done && !jEdit.has(d) ? jViewHTML(e, true) : jWrite || jEdit.has(d) ? writerHTML(d) : jStartHTML(d);
  jWire(box);
}
// the last few nights at a glance: mood and the first lines of the summary
function renderJRecent() {
  const es = J.entries.filter((e) => e.date < J.today && (e.words || e.text?.trim())).slice(-5).reverse();
  $('#j-recent').innerHTML = es.length ? `<div class="label">Recent</div><div class="card jrec">${es.map((e) => { const th = jThinking(e), m = e.mood && !th;
    return `<button class="jr" data-jday="${e.date}"><span class="jr-m ${m ? jMoodCls(e.mood) : ''}">${m ? e.mood : '–'}</span>
      <span class="jr-t"><b>${esc(jShort(e.date))}</b><small>${th || !e.summary ? (th ? (jAi === false ? 'No summary (no AI engine)' : 'Mood and summary arrive by morning') : plural(e.words || 0, 'word')) : esc(e.summary)}</small></span><span class="chev">${CHEV}</span></button>`; }).join('')}</div>` : '';
}
function renderCal() {
  const [yy, mm] = jMonth.split('-').map(Number), first = new Date(yy, mm - 1, 1), n = new Date(yy, mm, 0).getDate();
  const es = J.entries.filter((e) => e.date.startsWith(jMonth)), moods = es.filter((e) => e.mood && !jThinking(e)).map((e) => e.mood);
  const minMonth = isoDay(new Date(dParse(J.today).getFullYear() - 2, dParse(J.today).getMonth() + 1, 1)).slice(0, 7);
  const cells = [...Array((first.getDay() + 6) % 7)].map(() => '<i></i>').join('') + [...Array(n)].map((_, k) => {
    const iso = `${jMonth}-${String(k + 1).padStart(2, '0')}`, e = jEntry(iso);
    return `<button class="hc jc${e ? ' on' : ''}${e?.mood ? ' m-' + jMoodCls(e.mood) : ''}${iso === J.today ? ' now' : ''}" data-jday="${iso}" ${iso > (J.date || J.today) ? 'disabled' : ''}
      aria-label="${esc(longDate(iso) + (e ? (e.mood ? `: mood ${e.mood} out of 10` : ': written') : ''))}"><b class="num">${k + 1}</b><small></small></button>`;
  }).join('');
  const sub = es.length ? `${es.length} ${es.length === 1 ? 'entry' : 'entries'}${moods.length ? ` • average mood ${(moods.reduce((a, b) => a + b, 0) / moods.length).toFixed(1)}` : ''}` : 'No entries yet';
  $('#j-cal').innerHTML = `<div class="card hcal"><div class="hmh">
      <button class="icon-btn" data-jm="-1" aria-label="Previous month" ${jMonth <= minMonth ? 'disabled' : ''}>${BACK}</button>
      <div><b>${first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' })}</b><small>${sub}</small></div>
      <button class="icon-btn" data-jm="1" aria-label="Next month" ${jMonth >= (J.date || J.today).slice(0, 7) ? 'disabled' : ''}>${CHEV}</button></div>
    <div class="hgrid">${WD.map((x) => `<span>${x}</span>`).join('')}${cells}</div>
    <div class="jlegend"><span><i class="good"></i>Mood 7 to 10</span><span><i class="warn"></i>4 to 6</span><span><i class="bad"></i>1 to 3</span></div></div>`;
  renderJRecent(); renderJQueue();
}

// one day in its own panel: read it, or write a day you missed
async function jOpenEntry(d) {
  jOpen = d; $('#jent').hidden = false; document.body.style.overflow = 'hidden'; $('#jent-body').innerHTML = '<div class="card"><div class="skel"></div></div>';
  await jNeed([d]); if (jOpen === d) renderEntry();
}
function renderEntry() {
  const d = jOpen, e = jEntry(d), box = $('#jent-body');
  $('#jent-title').textContent = d === J.today ? 'Tonight' : jShort(d);
  $('#jent [data-jstep="-1"]').disabled = !J.entries.length || d <= J.entries[0].date;
  $('#jent [data-jstep="1"]').disabled = d >= (J.date || J.today);
  $('#jent-del').hidden = !e;
  if (jBusy(box)) return;
  box.innerHTML = e && (e.done || d !== J.today) && !jEdit.has(d) ? jViewHTML(e, false)
    : (e ? '' : `<div class="gpast">${CAL}<div><b>Writing for ${esc(longDate(d))}</b><small>It goes into that day in your journal.</small></div></div>`) + writerHTML(d);
  jWire(box);
}
// Your own score for a day: the night run never overwrites it, and "Use AI's score" goes back.
// A why is optional; the last few go into the AI's prompt so it learns how you rate a day.
const J_FEEL = ['sad', 'lonely', 'anxious', 'hopeful', 'calm', 'happy', 'grateful', 'guilty', 'proud', 'heartbroken', 'relieved'];
const jMoodWord = (m) => (m <= 2 ? 'Awful' : m <= 4 ? 'Bad' : m === 5 ? 'Mixed' : m === 6 ? 'Okay' : m === 7 ? 'Good' : 'Great');
let jmsDay = null, jmsBody = '';
function jMoodSheet(d) {
  const e = jEntry(d); if (!e?.mood) return;
  jmsDay = d; const feel = new Set(e.feelings || []);
  $('#jms-title').textContent = `How did ${jShort(d)} feel?`;
  $('#jms-body').innerHTML = `<div class="jms-n"><b class="num" data-jms-num></b><small>/10</small><span data-jms-word></span></div>
    <input type="range" class="jms-r" min="1" max="10" step="1" value="${e.mood}" aria-label="Mood out of 10" data-jms-r>
    <div class="jms-ends"><span>Awful</span><span>Great</span></div>
    <div class="jms-l">Feelings <small>up to 3</small></div>
    <div class="jms-fs">${J_FEEL.map((f) => `<button type="button" class="jms-f${feel.has(f) ? ' on' : ''}" data-jms-f="${f}" aria-pressed="${feel.has(f)}">${f}</button>`).join('')}</div>
    <div class="jms-l">Why <small>optional</small></div>
    <input class="jms-why" data-jms-why maxlength="300" autocomplete="off" placeholder="Good lunch and F1, the Hinge thing sat over it" value="${esc(e.mood_why || '')}">
    <p class="jms-note">Your score stays when the summary is redone. Your reasons teach the AI how you rate a day.</p>
    <div class="jms-acts">${e.mood_set ? `<button class="jms-reset" data-jms-reset>Use AI’s score${e.mood_ai ? ` (${e.mood_ai})` : ''}</button>` : ''}<button class="jms-save" data-jms-save>Save</button></div>`;
  const r = $('#jms-body [data-jms-r]'), n = $('#jms-body .jms-n');
  const paint = () => {
    const m = +r.value, c = jMoodCls(m);
    n.className = 'jms-n ' + c; r.className = 'jms-r ' + c; r.style.setProperty('--p', `${(m - 1) / 9 * 100}%`);
    n.querySelector('[data-jms-num]').textContent = m; n.querySelector('[data-jms-word]').textContent = jMoodWord(m);
  };
  r.oninput = paint; paint();
  $('#jms-body').querySelectorAll('[data-jms-f]').forEach((b) => b.onclick = () => {
    const on = !b.classList.contains('on');
    if (on && $('#jms-body').querySelectorAll('.jms-f.on').length >= 3) return snack('Up to 3 feelings. Tap one to drop it first.');
    b.classList.toggle('on', on); b.setAttribute('aria-pressed', on);
  });
  $('#jms-body [data-jms-save]').onclick = () => jmsSave({ mood: +r.value, feelings: [...$('#jms-body').querySelectorAll('.jms-f.on')].map((b) => b.dataset.jmsF), why: $('#jms-body [data-jms-why]').value });
  const rs = $('#jms-body [data-jms-reset]'); if (rs) rs.onclick = () => jmsSave({ reset: true });
  jmsBody = document.body.style.overflow; document.body.style.overflow = 'hidden'; $('#jms').hidden = false;
}
function jmsClose() { $('#jms').hidden = true; document.body.style.overflow = jmsBody; jmsDay = null; }
document.querySelectorAll('[data-jms-no]').forEach((b) => b.onclick = jmsClose);
async function jmsSave(body) {
  const d = jmsDay, btns = $('#jms-body').querySelectorAll('.jms-acts button');
  btns.forEach((b) => b.disabled = true);
  let r; try { r = await post('/api/bot/journal/mood', { date: d, ...body }); } catch (x) { r = null; }
  if (!r?.ok) { btns.forEach((b) => b.disabled = false); return snack(r?.msg || 'Couldn’t save your score. Try again.', { bad: true }); }
  const e = jEntry(d);
  if (e) for (const k of ['mood', 'feelings', 'mood_set', 'mood_why', 'mood_ai', 'feelings_ai']) { if (r.entry[k] == null) delete e[k]; else e[k] = r.entry[k]; }
  jmsClose();
  if (jOpen === d) renderEntry();
  renderJToday(); renderCal();
  if (!$('#jther').hidden) renderTher();
  snack(body.reset ? 'Back to the AI’s score' : 'Score saved');
}
async function closeEntry() {
  const w = $('#jent .jw'); if (w?._dirty) await jSave(w);
  $('#jent').hidden = true; if ($('#jther').hidden && $('#jfind').hidden) document.body.style.overflow = '';
  jEdit.delete(jOpen); jOpen = null; renderJToday(); renderCal();
  if (!$('#jther').hidden) renderTher();
  if (!$('#jfind').hidden) jfRun();  // came from find and replace: its results reflect any edit
}
document.querySelector('[data-close-jent]').onclick = closeEntry;
// < and >: the day before or after, saving anything half-written first
const jAddDay = (d, n) => { const x = dParse(d); x.setDate(x.getDate() + n); return x.toLocaleDateString('en-CA'); };
async function jStep(n) {
  const b = $(`#jent [data-jstep="${n}"]`); if (!jOpen || b.disabled) return;
  const w = $('#jent .jw'); if (w?._dirty) await jSave(w);
  jEdit.delete(jOpen); jOpenEntry(jAddDay(jOpen, n));
}
$('#jent').querySelectorAll('[data-jstep]').forEach((b) => { b.onclick = () => jStep(+b.dataset.jstep); });
document.addEventListener('keydown', (e) => {
  if ($('#jent').hidden || e.target.closest('input, textarea, [contenteditable]')) return;
  if (e.key === 'ArrowLeft') jStep(-1); else if (e.key === 'ArrowRight') jStep(1);
});
$('#jent-del').onclick = async () => {
  const d = jOpen;
  if (!await confirmSheet({ title: 'Delete this entry?', text: `${longDate(d)}. This can’t be undone.`, ok: 'Delete entry', danger: true })) return;
  try { await post('/api/bot/journal/delete', { date: d }); } catch (e) { return snack('Couldn’t delete it. Try again.', { bad: true }); }
  J.entries = J.entries.filter((x) => x.date !== d); if (J.texts[d.slice(0, 7)]) delete J.texts[d.slice(0, 7)][d];
  try { localStorage.removeItem('jdraft:' + d); } catch (e) {}
  const w = $('#jent .jw'); if (w) w._dirty = false;
  await closeEntry(); snack('Entry deleted');
};

async function jSave(w, done = false) {
  clearTimeout(w._deb);
  const d = w.dataset.jw, text = w.querySelector('[data-jt]').value, ver = w._ver, st = w.querySelector('[data-jst]');
  try { localStorage.setItem('jdraft:' + d, text); } catch (e) {}
  try {
    const r = await post('/api/bot/journal/save', { date: d, text, secs: w._secs, done });
    J.entries = J.entries.filter((x) => x.date !== d).concat(r.entry ? [r.entry] : []).sort((a, b) => (a.date < b.date ? -1 : 1));
    const mt = (J.texts[d.slice(0, 7)] ||= {}); if (r.entry) mt[d] = r.entry.text; else delete mt[d];
    if (w._ver === ver) { w._dirty = false; try { localStorage.removeItem('jdraft:' + d); } catch (e) {} }
    st.textContent = text.trim() ? 'Saved' : '';
    renderCal();
    return r.entry;
  } catch (e) { st.textContent = 'Not saved'; return undefined; }
}
// Close: back to how it was before Start writing. What you typed is kept (saved as you type) and the button then says Continue writing.
async function jClose(w) {
  const d = w.dataset.jw;
  if (w._dirty) await jSave(w);
  w._dirty = false; document.activeElement?.blur?.();
  jEdit.delete(d); if (d === J.today) jWrite = false;
  if ($('#jent-body').contains(w)) { if (jEntry(d)) renderEntry(); else closeEntry(); } else renderJToday();
}
async function jDone(w) {
  const had = !!jEntry(w.dataset.jw)?.summary, d = w.dataset.jw, ta = w.querySelector('[data-jt]'), n = jWords(ta.value);
  if (!n) return jClose(w);  // nothing written, nothing to lose: back to how it was
  if (n < 150 && !await confirmSheet({ title: `${n} ${n === 1 ? 'word' : 'words'} so far`, text: 'A few more lines make it more useful when you look back. Aim for about 150.', ok: 'Save anyway', no: 'Keep going' })) { ta.focus(); return; }
  const btn = w.querySelector('[data-jdone]'); btn.disabled = true;
  const e = await jSave(w, true);
  btn.disabled = false;
  if (e === undefined) return snack('Couldn’t save. Check your connection and try again.', { bad: true });
  jEdit.delete(d); w._dirty = false; ta.blur(); if (d === J.today) jWrite = false;
  snack('Saved to your journal');
  if (jOpen === d) renderEntry(); else renderJToday();
  renderCal();
  // it already has a summary: a fresh one replaces it, so ask
  if (had && await confirmSheet({ title: 'Write a fresh summary?', text: 'This entry already has one. Gemma can write a new one tonight that includes your changes.', ok: 'Yes, tonight', no: 'Keep the old one' })) {
    try { const r = await post('/api/bot/journal/resum', { date: d }); if (r?.entry) Object.assign(jEntry(d), r.entry); } catch {}
    if (jOpen === d) renderEntry(); else renderJToday();
  }
}

// typing, the timer (counts while the box is in use) and saving as you go
document.addEventListener('input', (ev) => {
  if (!ev.target.matches?.('[data-jt]')) return;
  const w = ev.target.closest('.jw'); w._dirty = true; w._ver++; jCount(w); jQueue(w);
});
document.addEventListener('focusin', (ev) => { if (ev.target.matches?.('[data-jt]')) ev.target.closest('.jw')._on = true; });
document.addEventListener('focusout', (ev) => { if (!ev.target.matches?.('[data-jt]')) return; const w = ev.target.closest('.jw'); w._on = false; if (w._dirty) jSave(w); });
document.addEventListener('visibilitychange', () => { if (document.hidden) document.querySelectorAll('.jw').forEach((w) => { if (w._dirty) jSave(w); }); });
let jAwaitWas = null;
setInterval(() => { if (!J || document.hidden || jAwait(J.today) === jAwaitWas) return;
  jAwaitWas = jAwait(J.today); renderJToday(); if (!$('#jther').hidden) renderTher(); }, 30000);
setInterval(() => { if (J && !document.hidden) { renderJWeek(); renderJLetter(); } }, 30000);  // the weekly card leaves at 6 PM, the letter's at midnight
setInterval(() => { if (!document.hidden) document.querySelectorAll('.jw').forEach((w) => { if (w._on) { w._secs++; jCount(w); } }); }, 1000);

// for your therapist: a stretch of days, moods and the key moments, ready to share
// therapy is Wednesday at 3 PM, before that night's entry: every stretch runs Wednesday to the Tuesday before the next session (today, if it's Wednesday)
const jSession = () => { const x = dParse(J.today); x.setDate(x.getDate() + (10 - x.getDay()) % 7); return x; };
const jStretchDays = () => [...Array(jRange)].map((_, i) => { const x = jSession(); x.setDate(x.getDate() - (jRange - i)); return isoDay(x); });
async function openTher() {
  $('#jther').hidden = false; document.body.style.overflow = 'hidden'; $('#jther-body').innerHTML = '<div class="card"><div class="skel"></div></div>';
  $('#jther .panel-body').scrollTop = 0;
  await Promise.all([jNeed(jStretchDays()), jWeekLoad(), JD ? null : jdLoad()]); renderTher();
}
function closeTher() { $('#jwks').hidden = true; $('#jther').hidden = true; document.body.style.overflow = ''; }
// ----- weekly summary card (Wed to Tue only): written Wednesday at 8 AM from the full entries, shown from 12 noon until midnight
let jWeek = null, jWeekT = 0;
const jWkOpen = new Set();  // weekly summaries opened to all their moments
const JSPARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M11 3.5l1.6 4.4a3 3 0 0 0 1.8 1.8l4.4 1.6-4.4 1.6a3 3 0 0 0-1.8 1.8L11 19.1l-1.6-4.4a3 3 0 0 0-1.8-1.8L3.2 11.3l4.4-1.6a3 3 0 0 0 1.8-1.8z"/><path d="M18.5 3v3.5M16.75 4.75h3.5"/></svg>';
async function jWeekLoad() {
  try { jWeek = await getJSON('/api/bot/journal/weekly'); } catch { jWeek = null; }
  clearTimeout(jWeekT);
  const at = jWeek?.until ? jWeek.until * 1000 - Date.now() + 5000 : 0;  // it changes at 8 AM, noon and midnight on Wednesday
  if (at > 0 && at < 16 * 3600e3) jWeekT = setTimeout(() => jWeekLoad().then(() => { renderJWeek(); if (!$('#jther').hidden) renderTher(); if (!$('#jwks').hidden) renderWeeks(); }), at);
}
const jWeekRng = (w) => { const a = dParse(w.from), b = dParse(w.to);
  return a.getMonth() === b.getMonth() ? `${a.getDate()} to ${shortDate(w.to)}` : `${shortDate(w.from)} to ${shortDate(w.to)}`; };
function jRecapHTML(w) {  // one weekly summary in full: this week's, or any week before it
  const hp = w.happened || [], open = jWkOpen.has(w.from), li = (b, i) => `<li${i >= 5 ? ' class="more"' : ''}>${esc(b)}</li>`, made = new Date(w.made * 1000);
  return `<div class="card jwk ready${open ? ' open' : ''}"><h4><span>${JSPARK}Your week</span><small>${jWeekRng(w)}</small></h4><p class="jwk-line">${esc(w.line)}</p>
    ${hp.length ? `<h5>What happened</h5><ul>${hp.map(li).join('')}</ul>${hp.length > 5 ? `<button class="jwk-all" data-jwk-all="${w.from}">${open ? 'Show less' : `Show all ${hp.length}`}</button>` : ''}` : ''}
    ${w.bring_up?.length ? `<h5>Worth bringing up</h5><ul>${w.bring_up.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>` : ''}
    ${w.tags?.length ? `<div class="jtags">${w.tags.map((t) => `<span>${esc(t)}</span>`).join('')}</div>` : ''}
    <div class="jwk-f"><span>From ${w.nights}${w.full ? ' full' : ''} ${w.nights === 1 ? 'entry' : 'entries'}${w.made ? ` • made ${shortDate(isoDay(made))}, ${made.toLocaleTimeString('en-US', T12)}` : ''}</span>
    <button data-jwk-share="${w.from}" aria-label="Copy your week" title="Copy">${COPY_ICONS}</button></div></div>`;
}
function jWeekHTML() {  // this week's card while it isn't ready yet (pending, being written, too thin or missed)
  const w = jWeek; if (!w?.status || w.status === 'ready') return '';
  const head = `<h4><span>${JSPARK}Your week</span><small>${jWeekRng(w)}</small></h4>`;
  const [b, t] = { pending: ['Weekly summary pending.', 'It arrives Wednesday by 12 noon.'], writing: [`Reading your ${w.nights} nights.`, 'Your weekly summary arrives by 12 noon.'],
    thin: ['Not enough to sum up.', `${plural(w.nights, 'night')} this week.`], missed: ['No summary this week.', 'It couldn’t be written.'] }[w.status] || [];
  if (!b) return '';
  return `<div class="card jwk ${w.status}">${head}${jWait(`<b>${b}</b> ${t}`)}${w.status === 'pending' ? `<div class="jwk-dots">${w.written.map((x) => `<i${x ? ' class="on"' : ''}></i>`).join('')}</div>
    <p class="jwk-n">${w.nights} of 7 nights written</p>` : ''}</div>`;
}
function jWeeksHTML() {  // every weekly summary, newest first, with this week's on top until it's written
  if (!JD) return jWeekHTML() + '<div class="err">Your weekly summaries aren’t reachable right now. Try again in a minute.</div>';
  const rc = JD.recaps || [];
  if (jWeek?.status === 'ready' && !rc.some((w) => w.from === jWeek.from)) rc.unshift(jWeek);
  return jWeekHTML() + (rc.length ? rc.map(jRecapHTML).join('') : '<div class="empty">Your weekly summaries gather here. A new one comes every Wednesday by 12 noon.</div>');
}
const jWkAll = () => [...(jWeek?.status === 'ready' ? [jWeek] : []), ...(JD?.recaps || [])];
function jWkClick(e) {  // Show all and Share on a weekly summary, wherever it shows
  const all = e.target.closest('[data-jwk-all]'), sh = e.target.closest('[data-jwk-share]');
  if (all) { const f = all.dataset.jwkAll, w = jWkAll().find((x) => x.from === f), c = all.closest('.jwk'), open = c.classList.toggle('open');
    open ? jWkOpen.add(f) : jWkOpen.delete(f); all.textContent = open ? 'Show less' : `Show all ${w?.happened?.length || ''}`; return true; }
  if (sh) { const w = jWkAll().find((x) => x.from === sh.dataset.jwkShare); if (w) jSend(jWeekText(w), sh); return true; }
  return false;
}
// the journal page shows it from 12 noon to 6 PM on the Wednesday; tapping opens it in For your therapist
const JSPROUT = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M2 9a10 10 0 1 0 20 0"/><path d="M12 19a10 10 0 0 1 10-10"/><path d="M2 9a10 10 0 0 1 10 10"/><path d="M12 4a9.7 9.7 0 0 1 3 7.5"/><path d="M9 11.5A9.7 9.7 0 0 1 12 4"/></svg>';
function renderJWeek() {
  const w = jWeek, t = new Date(), on = w?.status === 'ready' && isoDay(t) === w.week && t.getHours() >= 12 && t.getHours() < 18;
  const h = on ? `<button class="card row-btn jwk-pop" data-jweek><span class="jic">${JSPROUT}</span><span><b>Your weekly summary</b>
    <small>${jWeekRng(w)}, ${w.nights === 7 ? 'all 7 nights' : plural(w.nights, 'night')}. Take a breath, it’s ready.${w.session && CFG.support?.therapist ? ` A little something for your chat with ${esc(CFG.support.therapist)}.` : ''}</small></span><span class="chev">${CHEV}</span></button>` : '';
  const box = $('#j-week'); if (box.innerHTML !== h) box.innerHTML = h;
}
$('#j-week').onclick = async (e) => { if (!e.target.closest('[data-jweek]') || !J) return;
  await openTher(); openWeeks(); };
const jWeekText = (w) => [`Weekly summary, ${jWeekRng(w)}`, w.line, '', 'What happened', ...w.happened.map((b) => `• ${b}`),
  ...(w.bring_up?.length ? ['', 'Worth bringing up', ...w.bring_up.map((b) => `• ${b}`)] : [])].join('\n');
$('#jther-body').addEventListener('click', (e) => { if (e.target.closest('[data-jwks]')) openWeeks(); });
$('#jther-open').onclick = () => { if (J) openTher(); };
function openWeeks() { $('#jwks').hidden = false; $('#jwks .panel-body').scrollTop = 0; renderWeeks(); }
function renderWeeks() { $('#jwks-body').innerHTML = jWeeksHTML(); }
function closeWeeks() { $('#jwks').hidden = true; }
document.querySelector('[data-close-jwks]').onclick = closeWeeks;
$('#jwks-body').addEventListener('click', jWkClick);

// ----- Deep insights (2026-10-28): what the journal knows about him. The numbers come from the index the page already has
// (moods by topic, weekday, people, feelings); the written parts come from Gemma each morning (/journal/deep).
// Letters are never read by any AI. Around a date that matters, it goes quieter: just the moon and a soft card, insights on a tap.
const JMOON = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 3.5a5.5 5.5 0 1 0 5 8 4.5 4.5 0 0 1-5-8z"/><path class="jmw" d="M3 19c1.5 0 1.5-1 3-1s1.5 1 3 1 1.5-1 3-1 1.5 1 3 1 1.5-1 3-1 1.5 1 3 1"/></svg>';
const jdI = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const JD_IC = {
  sun: jdI('<circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/>'),
  cloud: jdI('<path d="M7 18h10a4 4 0 0 0 .5-7.97A6 6 0 0 0 6 11a3.5 3.5 0 0 0 1 7z"/>'),
  week: jdI('<path d="M4 20V10M9.3 20V6M14.6 20v-8M20 20V4"/>'),
  wave: jdI('<path d="M3 15c2.5 0 2.5-6 5-6s2.5 6 5 6 2.5-6 5-6 2.5 3 3 3"/>'),
  loop: jdI('<path d="M17 3l3 3-3 3"/><path d="M4 11V9a3 3 0 0 1 3-3h13"/><path d="M7 21l-3-3 3-3"/><path d="M20 13v2a3 3 0 0 1-3 3H4"/>'),
  before: jdI('<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>'),
  star: jdI('<path d="M12 4l2.4 4.9 5.4.8-3.9 3.8.9 5.4L12 16.4l-4.8 2.5.9-5.4-3.9-3.8 5.4-.8z"/>'),
  up: jdI('<path d="M4 16l5-5 4 4 7-7"/><path d="M15 8h5v5"/>'),
  calm: jdI('<path d="M3 12h4l2-3 3 6 2-3h7"/>'),
  heart: jdI('<path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/>'),
  back: jdI('<path d="M4 12a8 8 0 1 0 2.3-5.7"/><path d="M4 4v4.5h4.5"/><path d="M12 8v4l2.5 1.5"/>'),
  talk: jdI('<path d="M4 5h11a1.5 1.5 0 0 1 1.5 1.5v6A1.5 1.5 0 0 1 15 14H9l-4 3.5V14H4a1.5 1.5 0 0 1-1.5-1.5v-6A1.5 1.5 0 0 1 4 5z"/><path d="M16.5 9H20a1.5 1.5 0 0 1 1.5 1.5v6A1.5 1.5 0 0 1 20 18h-1v3l-3.5-3H11a1.5 1.5 0 0 1-1.5-1.5V16"/>'),
  letter: jdI('<rect x="3.5" y="5.5" width="17" height="13" rx="2"/><path d="M4 7l8 6 8-6"/>'),
  date: jdI('<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M9 3v4M15 3v4"/><path d="M12 17.6s-3-1.8-3-3.6a1.5 1.5 0 0 1 3-.7 1.5 1.5 0 0 1 3 .7c0 1.8-3 3.6-3 3.6z"/>'),
};
// the hero: a night sky, a crescent moon and its light on the water
const JD_WAVE = (y, o) => `<path d="M-40 ${y}${Array.from({ length: 22 }, () => 'c5 0 5-2.4 10-2.4s5 2.4 10 2.4').join('')}" stroke="rgba(238,243,248,${o})"/>`;
const JD_SCENE = `<svg viewBox="0 0 340 132" aria-hidden="true"><g fill="#eef3f8">${[[34, 26, 1.2, 0], [70, 52, 0.9, -1.4], [104, 18, 1.4, -2.6], [150, 40, 1, -0.8], [188, 14, 1.1, -3.1],
  [214, 62, 0.8, -1.9], [300, 22, 1.2, -2.2], [318, 64, 0.9, -0.4], [128, 70, 0.8, -3.4], [20, 70, 1, -2.9], [276, 80, 0.7, -1.1]].map(([x, y, r, d]) =>
  `<circle class="jd-star" cx="${x}" cy="${y}" r="${r}" style="animation-delay:${d}s"/>`).join('')}</g>
  <circle class="jd-glow" cx="252" cy="46" r="34" fill="#f4ecd2" opacity=".08"/>
  <mask id="jd-cres"><rect width="340" height="132" fill="#fff"/><circle cx="261" cy="39" r="16" fill="#000"/></mask>
  <circle cx="252" cy="46" r="18" fill="#f4ecd2" mask="url(#jd-cres)"/>
  <rect y="94" width="340" height="38" fill="#182b3c"/><path d="M0 94h340" stroke="rgba(238,243,248,.2)"/>
  <g class="jd-wv" fill="none" stroke-width="1.1">${JD_WAVE(106, '.13')}${JD_WAVE(118, '.09')}</g>
  <g class="jd-glint" stroke="#f4ecd2" stroke-width="1.6" stroke-linecap="round"><path d="M241 100h20" opacity=".7"/><path d="M236 107h12M253 107h9" opacity=".55"/><path d="M244 114h15" opacity=".45"/><path d="M248 121h7" opacity=".3"/></g></svg>`;

let JD = null, jdTab = 'patterns', jdAll = false, jdSubV = null, jdL = null, jdEdit = null, jdGym = new Set();
async function jdLoad() { try { JD = await getJSON('/api/bot/journal/deep'); } catch {} }
let jdRange = 14, jdReadT = 0;  // 14 or 30 days
// mood over time: 2W or 1M, the nights in that window stretched edge to edge, a leader and day number on
// each night (where they fit), the month written under the first night of each month with a faint line where months meet,
// dotted across 3+ missed nights. No average line.
function jdMoodCard(rows) {
  const rng = jdRange === 30 ? 30 : 14, from = isoDay(new Date(dParse(J.today) - (rng - 1) * 864e5)), inR = rows.filter((e) => e.date >= from);
  const seg = `<div class="seg jd-rng">${[[14, '2W'], [30, '1M']].map(([k, n]) => `<button data-jdr="${k}" class="${rng === k ? 'on' : ''}">${n}</button>`).join('')}</div>`;
  const span = rng === 14 ? 'Past 14 days' : 'Past month';
  const cap = inR.length ? `${span}, ${plural(inR.length, 'night')} written, average ${jd1(jdAvg(inR.map((e) => e.mood)))}.` : `${span}: no nights written.`;
  return jdCard(JD_IC.wave, 'Your mood over time', seg + (inR.length ? jdChart(inR) : '') + `<p>${cap}</p>`);
}
function jdChart(rows) {
  const W = 320, H = 186, L = 14, R = 14, T = 24, B = 40, base = H - B, f = (v) => v.toFixed(1);
  const t0 = dParse(rows[0].date), span = dParse(rows.at(-1).date) - t0;
  const X = (d) => (span ? L + ((dParse(d) - t0) / span) * (W - L - R) : W / 2), Y = (m) => T + (1 - (m - 1) / 9) * (base - T - 6);
  const pts = rows.map((e) => ({ e, x: X(e.date), y: Y(e.mood) }));
  let solid = '', dotted = '';
  pts.forEach((p, i) => { if (!i) return; const q = pts[i - 1], seg = `M${f(q.x)} ${f(q.y)}L${f(p.x)} ${f(p.y)}`;
    if (jdDays(q.e.date, p.e.date) >= 4) dotted += seg; else solid += seg; });
  // the first night of each month always gets its date and month; the rest where there's room
  const first = pts.map((p, i) => !i || p.e.date.slice(0, 7) !== pts[i - 1].e.date.slice(0, 7));
  const lab = pts.map(() => false); let lastX = -99;
  pts.forEach((p, i) => { if (first[i]) { lab[i] = true; lastX = p.x; } });
  lastX = -99;
  pts.forEach((p, i) => { const next = pts.findIndex((q, j) => j > i && first[j]);
    if (lab[i] || (p.x - lastX >= 17 && (next < 0 || pts[next].x - p.x >= 17))) { lab[i] = true; lastX = p.x; } });
  const mon = (d) => dParse(d).toLocaleDateString('en-GB', { month: 'short' });
  const seams = pts.filter((p, i) => i && first[i]).map((p) => { const q = pts[pts.indexOf(p) - 1]; return (q.x + p.x) / 2; });
  return `<svg class="jd-ch" viewBox="0 0 ${W} ${H}" role="img" aria-label="Mood by night">${[4, 7].map((m) => `<path d="M0 ${f(Y(m))}H${W}" class="g"/>`).join('')}
    ${seams.map((x) => `<path d="M${f(x)} ${T - 8}V${H - 4}" class="sm"/>`).join('')}<path d="M0 ${base}H${W}" class="bl"/>
    ${pts.map((p, i) => `<path d="M${f(p.x)} ${f(p.y + 5)}V${base}" class="ld${lab[i] ? '' : ' x'}"/>`).join('')}
    <path d="${solid}" class="l"/><path d="${dotted}" class="l dt"/>
    ${pts.map((p, i) => `<g data-jday="${p.e.date}"><circle cx="${f(p.x)}" cy="${f(p.y)}" r="11" class="hit"/><circle cx="${f(p.x)}" cy="${f(p.y)}" r="3.4" class="${jMoodCls(p.e.mood)}"/>
      ${lab[i] || rows.length <= 16 ? `<text x="${f(p.x)}" y="${f(p.y - 9)}" class="v">${p.e.mood}</text>` : ''}${lab[i] ? `<text x="${f(p.x)}" y="${base + 15}" class="dl">${dParse(p.e.date).getDate()}</text>` : ''}
      ${first[i] ? `<text x="${f(p.x)}" y="${base + 30}" class="mo">${mon(p.e.date)}</text>` : ''}</g>`).join('')}</svg>`;
}

// ----- the nightly deep read: morning note, shifts, and the cards built from each night's signals
const JD_SIG = () => JD?.signals || {};
function jdNoteHTML() {  // about last night, with the few nights before it as background
  const n = JD?.note; if (!n?.text) return '';
  return jdCard(JD_IC.sun, `Your morning note<small>${n.date === isoDay(new Date()) ? 'This morning' : shortDate(n.date)}</small>`,
    `<p class="jd-lead">${esc(n.text)}</p>${jdDayBtns([n.night])}`, 'jd-morning');
}
function jdTop() {  // Sundays bring the week in patterns (the month's letter has its own place since 2026-11-01)
  const t = isoDay(new Date()), w = JD?.week;
  let h = jdNoteHTML();
  if (w && jdDays(w.week, t) <= 1) h += jdWeekCard(w);
  return h;
}
function jdSignalsPatterns(rows) {
  const S = JD_SIG(), ds = rows.filter((e) => S[e.date]);
  if (ds.length < 3) return '';
  let h = '';
  const cop = ds.flatMap((e) => (S[e.date].coping || []).filter((c) => c.helped === true).map((c) => ({ ...c, date: e.date }))).reverse();
  if (cop.length) h += jdCard(JD_IC.calm, 'What helped you through', `<div class="jd-fs">${cop.slice(0, 6).map((c) =>
    `<div class="jd-f"><span><b>${esc(jdCap(c.what))}</b><small>${shortDate(c.date)}</small></span><em class="up">Helped</em></div>`).join('')}</div>`);
  const vs = (pick, label) => { const a = ds.filter((e) => pick(S[e.date])), b = ds.filter((e) => !pick(S[e.date]));
    if (a.length < 2 || b.length < 2) return null; const w = jdAvg(a.map((e) => e.mood)), o = jdAvg(b.map((e) => e.mood)); return { label, n: a.length, w, o, d: w - o }; };
  const se = [vs((s) => s.sleep?.quality === 'good', 'After good sleep'), vs((s) => s.energy === 'high', 'High energy nights')].filter((x) => x && x.d >= 0.3);
  if (se.length) h += jdCard(JD_IC.wave, 'Sleep and energy', `<div class="jd-fs">${se.map(jdFRow).join('')}</div><p>From what you wrote about your sleep and energy.</p>`);
  return h;
}
const jdWeekCard = (w) => jdCard(JD_IC.week, `Your week in patterns<small>${shortDate(w.from)} to ${shortDate(w.to)}</small>`, `${w.line ? `<p class="jd-lead">${esc(w.line)}</p>` : ''}
  ${w.patterns?.map((x) => `<div class="jd-th"><p>${esc(x.text)}</p>${x.dates?.length ? jdDayBtns(x.dates) : ''}</div>`).join('') || ''}
  ${w.helped?.length ? `<p class="jd-k">What helped</p>${jdChips(w.helped)}` : ''}${w.hard?.length ? `<p class="jd-k">What was hard</p>${jdChips(w.hard)}` : ''}${w.keep ? `<p class="jd-k">Worth keeping close</p><p class="jd-t">${esc(w.keep)}</p>` : ''}`);
function jdLonger() {
  let h = '';
  const ch = JD?.chapters || [];
  if (ch.length) h += jdCard(JD_IC.star, 'The chapters so far', `<div class="jd-chs">${ch.map((c, i) => `<div class="jd-chp${i === ch.length - 1 ? ' now' : ''}"><i></i><div><b>${esc(c.title)}</b><small>${shortDate(c.from)} to ${i === ch.length - 1 ? 'now' : shortDate(c.to)}</small><p>${esc(c.line)}</p></div></div>`).join('')}</div>`);
  if (JD?.week) h += jdWeekCard(JD.week);
  return h;
}
function jdReadPoll() {  // while the first read runs, check back every 2 minutes while Deep insights is open
  clearTimeout(jdReadT);
  if (JD?.reading) jdReadT = setTimeout(async () => { if ($('#jdeep').hidden) return; await jdLoad(); renderDeep(); jdReadPoll(); }, 120000);
}
const jdRows = () => (J?.entries || []).filter((e) => e.mood && e.words);  // written nights with a mood, oldest first
const jdAvg = (xs) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0);
const jd1 = (v) => (Math.round(v * 10) / 10).toFixed(1);
const jdDays = (a, b = J.today) => Math.round((dParse(b) - dParse(a)) / 864e5);
const jdAgo = (d) => { const n = jdDays(d); return n <= 0 ? 'today' : n === 1 ? 'yesterday' : n < 14 ? `${n} days ago` : n < 60 ? `${Math.round(n / 7)} weeks ago` : shortDate(d); };
const jdUl = (xs) => `<ul class="jd-list">${xs.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`;
const jdChips = (xs) => `<div class="jd-chips">${xs.map((x) => `<span>${esc(x)}</span>`).join('')}</div>`;
const jdCard = (ic, title, inner, cls = '') => `<div class="card jd-card${cls ? ' ' + cls : ''}"><h3>${ic}<span>${title}</span></h3>${inner}</div>`;
const jdDayBtns = (ds) => `<div class="jd-ds">${ds.map((d) => `<button class="jd-d" data-jday="${d}">${shortDate(d)}</button>`).join('')}</div>`;
const jdMon = (k) => dParse(k + '-15').toLocaleDateString('en-GB', { month: 'short' });
// the written parts aren't there yet: being read now, or they come with the morning run
const jdAiWait = () => jWait(JD?.busy || JD?.reading ? 'Gemma is reading your nights right now. This part fills in within the hour.' : 'This part is written each morning at 5 AM, once there are 5 nights to read.');

function jdNear() {  // a date that matters, from 3 days before it to the day after
  const t = dParse(J.today);
  for (const x of JD?.dates || []) for (const y of [t.getFullYear() - 1, t.getFullYear(), t.getFullYear() + 1]) {
    const n = Math.round((dParse(`${y}-${x.md}`) - t) / 864e5);
    if (n >= -1 && n <= 3) return { ...x, n };
  }
  return null;
}
const jdNearTxt = (x) => x.n === 0 ? `Today is ${x.label}.` : x.n === 1 ? `${x.label} is tomorrow.` : x.n === -1 ? `Yesterday was ${x.label}.` : `${x.label} is in ${x.n} days.`;
function jdHeavy(rows) {  // the last three nights written were all heavy, and the latest is recent
  const l = rows.slice(-3);
  return l.length === 3 && l.every((e) => e.mood <= 4) && jdDays(l[2].date) <= 3 && jdDays(l[0].date, l[2].date) <= 6;
}
function jdBack() {  // the furthest back "on this day" that has an entry (a month or more: last week is on the calendar)
  const t = dParse(J.today);
  for (const [m, label] of [[12, 'A year ago today'], [6, 'Six months ago today'], [3, 'Three months ago today'], [1, 'A month ago today']]) {
    const d = new Date(t); d.setMonth(d.getMonth() - m);
    const e = d.getDate() === t.getDate() && jEntry(isoDay(d));
    if (e && e.words) return { e, label };
  }
  return null;
}
function jdFactors(rows) {  // mood on nights with a topic (gym days from the gym log too) against every other night
  const f = {};
  rows.forEach((e) => {
    const ks = new Set(e.tags || []); if (jdGym.has(e.date)) ks.add('gym');
    ks.forEach((k) => (f[k] ||= []).push(e));
  });
  const out = Object.entries(f).filter(([, xs]) => xs.length >= 2 && xs.length < rows.length).map(([k, xs]) => {
    const w = jdAvg(xs.map((e) => e.mood)), o = jdAvg(rows.filter((e) => !xs.includes(e)).map((e) => e.mood));
    return { label: k === 'gym' ? 'Gym days' : jdCap(k), n: xs.length, w, o, d: w - o };
  });
  return { lifts: out.filter((x) => x.d >= 0.7).sort((a, b) => b.d - a.d).slice(0, 4), weighs: out.filter((x) => x.d <= -0.7).sort((a, b) => a.d - b.d).slice(0, 4) };
}
const jdFRow = (x) => `<div class="jd-f"><span><b>${esc(x.label)}</b><small>${plural(x.n, 'night')} • mood ${jd1(x.w)}, other nights ${jd1(x.o)}</small></span>
  <em class="${x.d > 0 ? 'up' : 'down'}">${x.d > 0 ? '+' : '−'}${jd1(Math.abs(x.d))}</em></div>`;
const jdEmpty = (t) => `<div class="card jd-card"><p class="jd-calm">${t}</p></div>`;

function jdPeople(rows) {  // people on whose nights your mood ran higher than on every other night (2 or more nights)
  const f = {}; rows.forEach((e) => (e.people || []).forEach((p) => (f[p] ||= []).push(e)));
  return Object.entries(f).filter(([, xs]) => xs.length >= 2 && xs.length < rows.length).map(([p, xs]) => {
    const w = jdAvg(xs.map((e) => e.mood)), o = jdAvg(rows.filter((e) => !xs.includes(e)).map((e) => e.mood));
    return { label: p, n: xs.length, w, o, d: w - o };
  }).filter((x) => x.d >= 0.5).sort((a, b) => b.d - a.d).slice(0, 5);
}
function jdPatterns(rows) {
  if (rows.length < 5) return jdEmpty('Write a few more nights and your patterns start to show here. Five is enough for a first look.');
  const { lifts } = jdFactors(rows), ppl = jdPeople(rows);
  let h = jdMoodCard(rows);
  h += jdCard(JD_IC.sun, 'What lifts you', lifts.length ? `<div class="jd-fs">${lifts.map(jdFRow).join('')}</div><p>Your mood on nights with each, against every other night.</p>`
    : '<p>It shows up here as you write more nights.</p>');
  if (ppl.length) h += jdCard(JD_IC.heart, 'Who lifts you', `<div class="jd-fs">${ppl.map(jdFRow).join('')}</div><p>Your mood on nights you wrote about them, against every other night.</p>`);
  return h + jdSignalsPatterns(rows);
}
function jdFeelings(rows) {
  const fe = {}; rows.forEach((e) => (e.feelings || []).forEach((f) => (fe[f] ||= []).push(e)));
  const list = Object.entries(fe).sort((a, b) => b[1].length - a[1].length);
  if (rows.length < 3 || !list.length) return jdEmpty('Your feelings start to show here after a few nights.');
  const max = list[0][1].length, rec = rows.filter((e) => jdDays(e.date) < 14).length, old = rows.length - rec;
  const lately = (xs) => {
    const r = xs.filter((e) => jdDays(e.date) < 14).length, o = xs.length - r;
    if (rec < 3 || old < 3) return '';
    return r >= 2 && r / rec > (o / old) * 1.5 ? 'more lately' : o >= 2 && o / old > (r / rec) * 1.5 ? 'less lately' : '';
  };
  let h = jdCard(JD_IC.heart, 'What you felt most', `<div class="jd-fe">${list.slice(0, 8).map(([f, xs]) => { const l = lately(xs);
    return `<span class="n">${esc(f)}</span><span class="b"><i style="width:${(xs.length / max) * 100}%"></i></span><span class="c">${xs.length}${l ? `<small>${l}</small>` : ''}</span>`; }).join('')}</div>`);
  const wk = (e) => 7 - Math.floor(jdDays(e.date) / 7);  // 0 = seven weeks ago, 7 = this week
  const top = list.slice(0, 5).map(([f, xs]) => { const c = Array(8).fill(0); xs.forEach((e) => { const i = wk(e); if (i >= 0 && i < 8) c[i]++; }); return [f, c]; });
  const cm = Math.max(1, ...top.flatMap(([, c]) => c));
  h += jdCard(JD_IC.wave, 'The last eight weeks', `<div class="jd-strip">${top.map(([f, c]) => `<span class="n">${esc(f)}</span>${c.map((n) =>
    `<i style="--o:${n ? 22 + (n / cm) * 78 : 0}%"></i>`).join('')}`).join('')}<span></span><small class="s">8 weeks ago</small><small class="e">This week</small></div>`);
  const prev = (e) => { const p = rows[rows.indexOf(e) - 1]; return p && jdDays(p.date, e.date) <= 2 ? p : null; };
  const before = (pick) => { const c = {};
    rows.filter(pick).forEach((e) => { const p = prev(e); if (p) new Set([...(p.feelings || []), ...(p.tags || [])]).forEach((k) => (c[k] = (c[k] || 0) + 1)); });
    return Object.entries(c).filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([k]) => jdCap(k)); };
  const bg = before((e) => e.mood >= 7);
  if (bg.length) h += jdCard(JD_IC.before, 'Before a good night', `${jdChips(bg)}<p>What the night before tended to carry. Not a cause, just what showed up.</p>`);
  return h;
}

function jdGrowth(rows, all, ai) {
  let h = '';
  const ms = {}; rows.forEach((e) => (ms[e.date.slice(0, 7)] ||= []).push(e.mood));
  const mk = Object.keys(ms).filter((k) => ms[k].length >= 3).sort();
  if (mk.length >= 2) {
    const a = jdAvg(ms[mk[0]]), b = jdAvg(ms[mk.at(-1)]);
    h += jdCard(JD_IC.wave, 'Month to month', `<div class="jd-big num">${jdMon(mk[0])} ${jd1(a)}<span>→</span>${jdMon(mk.at(-1))} ${jd1(b)}</div>
      <p>${b - a >= 0.5 ? 'Your nights have been feeling lighter.' : a - b >= 0.5 ? 'This stretch has been heavier. You’re still showing up, and that counts.' : 'Steady. That counts too.'}</p>`);
  }
  let best = [], cur = [];
  rows.forEach((e) => { cur = e.mood >= 6 ? (cur.length && jdDays(cur.at(-1).date, e.date) <= 2 ? [...cur, e] : [e]) : []; if (cur.length > best.length) best = cur; });
  if (best.length >= 3) h += jdCard(JD_IC.calm, 'Your calmest stretch', `<p>${best.length} nights in a row that felt okay or better, ${shortDate(best[0].date)} to ${shortDate(best.at(-1).date)}.${best.at(-1) === rows.at(-1) ? ' And it’s still going.' : ''}</p>`);
  let run = 1, top = all.length ? 1 : 0;
  all.forEach((e, i) => { if (i) { run = jdDays(all[i - 1].date, e.date) === 1 ? run + 1 : 1; top = Math.max(top, run); } });
  h += jdCard(JD_IC.star, 'Showing up', `<div class="jd-stats"><div><b class="num">${all.length}</b><small>${all.length === 1 ? 'night' : 'nights'} written</small></div>
    <div><b class="num">${all.reduce((a, e) => a + e.words, 0).toLocaleString('en-GB')}</b><small>words</small></div><div><b class="num">${top}</b><small>nights in a row, at best</small></div></div>`);
  h += jdCard(JD_IC.sun, 'Wins you may have forgotten', ai ? (ai.wins.length ? ai.wins.map((w) => `<div class="jd-th"><p>${esc(w.win)}</p>${jdDayBtns([w.date])}</div>`).join('') : '<p>They’ll show up here as you write.</p>') : jdAiWait());
  h += jdLonger();
  return h;
}

function renderDeep() {
  if (!J) return;
  const rows = jdRows(), all = J.entries.filter((e) => e.words), ai = JD?.ai, near = jdNear(), back = jdBack();
  const words = all.reduce((a, e) => a + e.words, 0), line = near ? 'Go gently today.' : '';
  let h = `<div class="card jd-hero">${JD_SCENE}<div class="t"><b>${plural(all.length, 'night')} written</b>
    <small>${all.length ? `Since ${shortDate(all[0].date)} • ${words.toLocaleString('en-GB')} words` : 'Your first night starts it'}</small>${line ? `<p>${esc(line)}</p>` : ''}</div></div>`;
  if (near) {
    const past = all.filter((e) => e.date.slice(0, 4) < J.today.slice(0, 4) && Math.abs(jdDays(`${e.date.slice(0, 4)}-${near.md}`, e.date)) <= 3);
    h += jdCard(JD_IC.heart, esc(jdNearTxt(near)), `<p>There’s nothing you need to do here today. Write if it helps, rest if it doesn’t.</p>${past.length
      ? `<p class="jd-k">Around this day before</p><div class="jd-ds">${past.map((e) => `<button class="jd-d" data-jday="${e.date}">${shortDate(e.date)} ${e.date.slice(0, 4)}${e.mood ? ` • ${e.mood}/10` : ''}</button>`).join('')}</div>` : ''}`, 'jd-soft');
  }
  if (jdHeavy(rows)) {
    const helped = jdFactors(rows).lifts.map((x) => x.label);
    h += jdCard(JD_IC.heart, 'The last few nights have been heavy', `<p>You don’t have to fix anything tonight. Writing it down already counts.</p>
      ${helped.length ? `<p class="jd-k">What has helped before</p>${jdChips(helped)}` : ''}
      <p class="jd-help">If it ever feels like too much, ${CFG.support?.therapist ? `talk to ${esc(CFG.support.therapist)}, or ` : 'please talk to someone you trust, or '}${CFG.support?.helpline_tel ? `call ${esc(CFG.support.helpline_name || 'a helpline')} on <a href="tel:${String(CFG.support.helpline_tel).replace(/[^\d+]/g, '')}">${esc(CFG.support.helpline_tel)}</a>` : 'find a local helpline at <a href="https://findahelpline.com">findahelpline.com</a>'}.</p>`, 'jd-soft');
  }
  if (back && !near) h += `<button class="card jd-card jd-back" data-jday="${back.e.date}"><h3>${JD_IC.back}<span>${back.label}</span><small>${shortDate(back.e.date)}</small></h3>
    <p>${esc(back.e.summary || 'Tap to read what you wrote.')}</p></button>`;
  if (near && !jdAll) h += '<button class="jd-sec" data-jd-all>Show my insights</button>';
  else {
    h += jdTop();
    h += `<div class="seg ptabs jd-tabs">${[['patterns', 'Patterns'], ['feelings', 'Feelings'], ['growth', 'Growth']].map(([k, n]) =>
      `<button data-jdt="${k}" class="${jdTab === k ? 'on' : ''}">${n}</button>`).join('')}</div>`;
    h += { patterns: jdPatterns, feelings: jdFeelings, growth: (r, a) => jdGrowth(r, all, a) }[jdTab](rows, ai);
  }
  const rc = JD?.recaps || [], ds = JD?.dates || [];
  const row = (k, ic, b, s) => `<button class="card row-btn" data-jdsub="${k}"><span class="jic">${ic}</span><span><b>${b}</b><small>${s}</small></span><span class="chev">${CHEV}</span></button>`;
  h += '<div class="label">Your spaces</div>'
    + row('therapy', JD_IC.talk, 'Therapy thread', rc.length ? `${plural(rc.length, 'weekly summary').replace('summarys', 'summaries')} and what runs through them` : 'Your weekly summaries, and what runs through them')
    + row('letters', JD_IC.letter, 'Unsent letters', JD?.letters ? `${plural(JD.letters, 'letter')} • only you read these` : 'Only you read these')
    + row('dates', JD_IC.date, 'Dates that matter', ds.length ? esc(ds.map((x) => x.label).join(', ')) : 'Days you want to be gentle with');
  h += '<p class="hint">Everything here is worked out on your server. Nothing leaves it. The numbers are counted from your nights. Gemma writes your morning note and wins each morning, your week in patterns on Sundays, and the chapters on the 1st.</p>';
  const box = $('#jdeep .panel-body'), y = box.scrollTop;
  $('#jdeep-body').innerHTML = h; box.scrollTop = y;
}

function renderJDeep() {  // the button on the Journal page
  if (!J) return;
  const near = JD && jdNear();
  const sub = near ? `Go gently. ${jdNearTxt(near)}` : jdHeavy(jdRows()) ? 'A few heavy nights. Come sit for a minute.' : JD?.note?.text && JD.note.date === isoDay(new Date()) ? 'Your morning note is here' : 'What lifts you, from your nights';
  const h = `<button class="card row-btn jd-pop" id="jdeep-open"><span class="jic">${JMOON}</span><span><b>Deep insights</b><small>${esc(sub)}</small></span><span class="chev">${CHEV}</span></button>`;
  const box = $('#j-deep'); if (box.dataset.h !== h) { box.dataset.h = h; box.innerHTML = h; }
}
$('#j-deep').onclick = (e) => { if (e.target.closest('#jdeep-open') && J) openDeep(); };
async function openDeep() {
  $('#jdeep').hidden = false; document.body.style.overflow = 'hidden'; $('#jdeep .panel-body').scrollTop = 0; jdAll = false;
  if (!JD) $('#jdeep-body').innerHTML = '<div class="card"><div class="skel"></div></div>'; else renderDeep();
  await Promise.all([jdLoad(), getJSON('/api/bot/gym').then((g) => { jdGym = new Set(g.sessions.map((x) => x.date)); }).catch(() => {})]);
  renderDeep(); renderJDeep(); jdReadPoll();
}
function closeDeep() { $('#jdeep').hidden = true; document.body.style.overflow = ''; }
document.querySelector('[data-close-jdeep]').onclick = closeDeep;

// ----- the month's letter (2026-11-01): Gemma writes it on the 1st, 700 to 1,000 words. A card under the weekly summary
// until midnight on the day it's written ("the letter is for one day only"), and always under Letters from your journal
const JLET_IC = $('#jlet-open .jic').innerHTML;
const jlName = (m, o) => dParse(m.month + '-15').toLocaleDateString('en-GB', o);
const jlMins = (m) => Math.max(1, Math.round(m.letter.split(/\s+/).length / 200));
const jlBody = (t) => esc(t).split(/\n\s*\n/).map((p) => `<p>${p.trim().replace(/\n/g, '<br>')}</p>`).join('');
function renderJLetter() {
  const m = JD?.months?.[0], t = new Date(), on = m?.made && isoDay(new Date(m.made * 1000)) === isoDay(t);
  const sub = t.getDay() === 3 && t.getHours() < 18 ? 'One for tonight, after your session' : `From your journal, a ${jlMins(m || { letter: '' })} minute read`;  // one line, like Deep insights below it;
  const h = on ? `<button class="card row-btn jlt-pop" data-jlet><span class="jic">${JLET_IC}</span><span><b>${jlName(m, { month: 'long' })}’s letter is here</b><small>${sub}</small></span><span class="chev">${CHEV}</span></button>` : '';
  const box = $('#j-letter'); if (box.dataset.h !== h) { box.dataset.h = h; box.innerHTML = h; }
}
let jlCur = 0;  // the letter being read; the others sit below it as rows
function renderLetters() {
  const ms = JD?.months || [], m = ms[jlCur] || ms[0], mo = (x) => jlName(x, { month: 'long', year: 'numeric' }), info = (x) => `${plural(x.nights, 'night')} • ${jlMins(x)} min read`;
  $('#jlet-body').innerHTML = m ? `<article class="card jd-card"><h3>${JLET_IC}<span>${mo(m)}</span><small>${info(m)}</small></h3><div class="jlt-txt">${jlBody(m.letter)}</div></article>`
      + (ms.length > 1 ? '<div class="label">Your other letters</div>' + ms.map((x, i) => x === m ? '' : `<button class="card row-btn" data-jlm="${i}"><span class="jic">${JLET_IC}</span><span><b>${mo(x)}</b><small>${info(x)}</small></span><span class="chev">${CHEV}</span></button>`).join('') : '')
      + '<p class="hint">Written on your server from your nights’ summaries. Nothing leaves it.</p>'
    : '<div class="card jd-card"><p class="jd-calm">Your first letter comes on the 1st of next month.</p></div>';
}
$('#jlet-body').onclick = (e) => { const b = e.target.closest('[data-jlm]'); if (!b) return; jlCur = Number(b.dataset.jlm); renderLetters(); $('#jlet .panel-body').scrollTop = 0; };
async function openLetters() {
  jlCur = 0; $('#jlet').hidden = false; document.body.style.overflow = 'hidden'; $('#jlet .panel-body').scrollTop = 0;
  if (!JD) { $('#jlet-body').innerHTML = '<div class="card"><div class="skel"></div></div>'; await jdLoad(); }
  renderLetters();
}
function closeLetters() { $('#jlet').hidden = true; document.body.style.overflow = ''; }
document.querySelector('[data-close-jlet]').onclick = closeLetters;
$('#jlet-open').onclick = () => { if (J) openLetters(); };
$('#j-letter').onclick = (e) => { if (e.target.closest('[data-jlet]') && J) openLetters(); };
$('#jdeep-body').addEventListener('click', (e) => {
  const t = e.target.closest('[data-jdt],[data-jd-all],[data-jday],[data-jdsub],[data-jdr]'); if (!t) return;
  if (t.dataset.jdr) { jdRange = +t.dataset.jdr; return renderDeep(); }
  if (t.dataset.jdt) { jdTab = t.dataset.jdt; renderDeep(); return $('#jdeep-body .jd-tabs')?.scrollIntoView({ block: 'nearest' }); }
  if (t.dataset.jdAll !== undefined) { jdAll = true; return renderDeep(); }
  if (t.dataset.jday) return jOpenEntry(t.dataset.jday);
  if (t.dataset.jdsub) openJdSub(t.dataset.jdsub);
});

// ----- the three spaces, in a sheet over Deep insights
const JD_SUBT = { therapy: 'Therapy thread', letters: 'Unsent letters', dates: 'Dates that matter' };
async function openJdSub(v) {
  jdSubV = v; jdEdit = null; $('#jdsub-t').textContent = JD_SUBT[v]; $('#jdsub').hidden = false; $('#jdsub .panel-body').scrollTop = 0;
  if (v === 'letters' && !jdL) { $('#jdsub-body').innerHTML = '<div class="card"><div class="skel"></div></div>'; try { jdL = (await getJSON('/api/bot/journal/deep/letters')).letters; } catch { jdL = null; } }
  renderJdSub();
}
function closeJdSub() { $('#jdsub').hidden = true; jdSubV = null; jdEdit = null; renderDeep(); }
document.querySelector('[data-close-jdsub]').onclick = closeJdSub;
function renderJdSub() {
  const box = $('#jdsub-body');
  if (jdSubV === 'therapy') {
    box.innerHTML = jdTherHTML();
    return;
  }
  if (jdSubV === 'letters') {
    if (!jdL) { box.innerHTML = '<div class="err">Your letters aren’t reachable right now. Try again in a minute.</div>'; return; }
    if (jdEdit) {
      const x = jdEdit === 'new' ? { to: '', text: '' } : jdL.find((l) => l.id === jdEdit) || { to: '', text: '' };
      box.innerHTML = `<div class="card jd-card"><input class="jd-in" id="jd-lto" placeholder="Who it’s for" value="${esc(x.to)}" maxlength="40" aria-label="Who it’s for">
        <textarea class="jd-ta jd-lt" id="jd-ltx" placeholder="Dear" aria-label="Your letter">${esc(x.text)}</textarea><button class="jgo" data-jd-lsave>Keep this letter</button>
        <button class="jd-sec" data-jd-lcancel>Cancel</button>${x.id ? `<button class="jd-x" data-jd-ldel="${x.id}">Delete this letter</button>` : ''}</div>`;
      return;
    }
    box.innerHTML = jdCard(JD_IC.letter, 'Only you read these', '<p>Write to anyone, about anything you couldn’t say. No AI reads your letters, and they never show up in summaries, insights or search.</p>', 'jd-soft')
      + `<button class="jgo jd-new" data-jd-lnew>${PEN}Write a letter</button>`
      + jdL.map((l) => `<button class="card jth-e" data-jd-ledit="${l.id}"><h4><span>${l.to ? 'To ' + esc(l.to) : 'A letter'}</span><small>${shortDate(isoDay(new Date(l.updated * 1000)))}</small></h4><p class="jd-clamp">${esc(l.text)}</p></button>`).join('');
    return;
  }
  const ds = JD?.dates || [], mdTxt = (md) => dParse('2000-' + md).toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });
  box.innerHTML = jdCard(JD_IC.date, 'Days you want to be gentle with', '<p>A birthday, an anniversary, any day that matters. From three days before, Deep insights goes quieter and softer, and shows how you carried that day in the years before.</p>', 'jd-soft')
    + (ds.length ? `<div class="card jd-card">${ds.map((x) => `<div class="jd-f"><span><b>${esc(x.label)}</b><small>${mdTxt(x.md)}</small></span><button class="jd-rm" data-jd-ddel="${x.id}" aria-label="Remove ${esc(x.label)}">${XMARK}</button></div>`).join('')}</div>` : '')
    + jdCard(JD_IC.heart, 'Add a date', '<input class="jd-in" id="jd-dl" placeholder="What the day is" maxlength="40" aria-label="What the day is"><input class="jd-in" type="date" id="jd-dd" aria-label="Date"><button class="jgo" data-jd-dadd>Add date</button>');
}
function jdTherHTML() {  // your weekly summaries, and the topics that keep coming up across them
  const rc = JD?.recaps || [], c = {};
  rc.flatMap((w) => w.tags || []).forEach((t) => (c[t.toLowerCase()] = (c[t.toLowerCase()] || 0) + 1));
  const th = Object.entries(c).filter(([, n]) => n >= 2).sort((a, b) => b[1] - a[1]).slice(0, 8);
  return (th.length ? jdCard(JD_IC.loop, 'What keeps coming up', jdChips(th.map(([t, n]) => `${jdCap(t)} • ${n}`)) + '<p>Topics from your weekly summaries, and how many weeks each came up.</p>', 'jd-wkc') : '')
    + (rc.length ? '<div class="label">Your weekly summaries</div>' + rc.map(jRecapHTML).join('') : '')
    || jdEmpty('Your weekly summaries gather here, so you can see what runs through them.');
}
$('#jdsub-body').addEventListener('click', async (e) => {
  const t = e.target.closest('button'); if (!t || jWkClick(e)) return;
  const d = t.dataset, msg = (r, ok) => (r?.ok ? (ok && snack(ok), true) : (snack(r?.msg || 'Couldn’t save that. Try again.', { bad: true }), false));
  if (d.jdLnew !== undefined || d.jdLedit) { jdEdit = d.jdLedit || 'new'; renderJdSub(); $('#jdsub .panel-body').scrollTop = 0; return; }
  if (d.jdLcancel !== undefined) { jdEdit = null; return renderJdSub(); }
  if (d.jdLsave !== undefined) {
    t.disabled = true;
    const r = await post('/api/bot/journal/deep/letter', { id: jdEdit === 'new' ? undefined : jdEdit, to: $('#jd-lto').value, text: $('#jd-ltx').value }).catch(() => null);
    t.disabled = false; if (!msg(r, 'Letter kept.')) return;
    jdL = r.letters; if (JD) JD.letters = jdL.length; jdEdit = null; return renderJdSub();
  }
  if (d.jdLdel) {
    if (!await confirmSheet({ title: 'Delete this letter?', text: 'It’s gone for good. There’s no copy.', ok: 'Delete', danger: true })) return;
    const r = await post('/api/bot/journal/deep/letter', { id: d.jdLdel, delete: true }).catch(() => null);
    if (!msg(r)) return; jdL = r.letters; if (JD) JD.letters = jdL.length; jdEdit = null; return renderJdSub();
  }
  if (d.jdDadd !== undefined) {
    const r = await post('/api/bot/journal/deep/date', { label: $('#jd-dl').value, md: $('#jd-dd').value.slice(5) }).catch(() => null);
    if (!msg(r, 'Date added.')) return; JD.dates = r.dates; renderJdSub(); return renderJDeep();
  }
  if (d.jdDdel) {
    const x = (JD?.dates || []).find((y) => y.id === d.jdDdel);
    if (!await confirmSheet({ title: `Remove ${x ? x.label : 'this date'}?`, ok: 'Remove', danger: true })) return;
    const r = await post('/api/bot/journal/deep/date', { id: d.jdDdel, delete: true }).catch(() => null);
    if (!msg(r)) return; JD.dates = r.dates; renderJdSub(); return renderJDeep();
  }
});

// ----- find and replace: this month or every entry; your words, summaries and people lists.
// The preview shows every match and where it is; Replace changes exactly those, after the server keeps a copy.
let jfScope = 'month', jfMode = 'matches', jfTimer = null;
// queued for tonight's run. Without an AI engine nothing will run, so say that and offer the fix instead of promising a summary
const J_NOAI = '<b>No summary yet.</b> Mood and summaries need an AI engine, and none is set up. <button class="linkbtn" data-finish="open:ai">Set one up</button>';
const jWait = (t) => `<p class="jsum wait">${jAi === false ? J_NOAI : t}</p>`;
let jAi = null;  // null until known; false only when the AI engine check says it is missing
const jAiCheck = () => getJSON('/api/bot/capabilities').then((r) => { jAi = !!(r.capabilities || []).find((c) => c.name === 'ollama')?.ok; }).catch(() => {});
const jfN = (n, one, many) => `${n} ${n === 1 ? one : many}`;
const jfIco = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${d}</svg>`;
const JF_SRC = {  // where a match is: his words, Gemma's summary, or Gemma's people list
  text: jfIco('<path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/>') + 'Your words',
  summary: jfIco('<path d="M10 4l1.5 4.5L16 10l-4.5 1.5L10 16l-1.5-4.5L4 10l4.5-1.5z"/><path d="M18 3v4M16 5h4M18 15v4M16 17h4"/>') + 'Summary',
  people: jfIco('<circle cx="9" cy="8" r="3.5"/><path d="M2.5 20a6.5 6.5 0 0 1 13 0"/><path d="M16 4.5a3.5 3.5 0 0 1 0 7M18 14a6.5 6.5 0 0 1 3.5 6"/>') + 'People',
};
function openFind() {
  $('#jfind').hidden = false; document.body.style.overflow = 'hidden';
  jfRun(); setTimeout(() => $('#jf-find').focus(), 60);
}
function closeFind() { $('#jfind').hidden = true; document.body.style.overflow = ''; }
const jfBody = (apply) => ({ find: $('#jf-find').value, replace: $('#jf-rep').value, scope: jfScope, mode: jfMode, apply });
async function jfRun() {
  const box = $('#jf-res'), q = $('#jf-find').value.trim();
  const how = jfMode === 'contains' ? 'Finds it inside words too' : 'Whole words only';
  if (q.length < 2) { box.innerHTML = `<p class="hint">Type at least 2 letters. ${how}, in any case.</p>`; return; }
  let r;
  try { r = await post('/api/bot/journal/replace', jfBody(false)); } catch { box.innerHTML = '<div class="err">Couldn’t search right now. Try again in a minute.</div>'; return; }
  if ($('#jf-find').value.trim() !== q) return;  // typed on meanwhile
  const where = jfScope === 'all' ? 'all entries' : 'this month';
  if (!r.matches.length) { box.innerHTML = `<p class="hint">No “${esc(q)}” in your entries, summaries or people lists (${where}).</p>`; return; }
  const rep = $('#jf-rep').value.trim(), n = r.matches.length, same = rep === q;
  box.innerHTML = `<div class="label">${jfN(r.total, 'match', 'matches')} in ${jfN(n, 'entry', 'entries')}<span class="lr">${esc(where)}</span></div>`
    + r.matches.map((m) => `<div class="card jth-e"><h4><button class="jf-day" data-jday="${m.date}">${jShort(m.date)}</button>${m.n > 3 ? `<small>${m.n} times</small>` : ''}</h4>${m.snips.map((s, i) =>
      `<p>${i && m.snips[i - 1].where === s.where ? '' : `<b class="jf-w ${s.where}">${JF_SRC[s.where]}</b>`}${s.parts ? s.parts.map(([t, hit]) => hit ? `<mark>${esc(t)}</mark>` : esc(t)).join('')
        : `${s.pre.length >= 60 ? '…' : ''}${esc(s.pre)}<mark>${esc(s.hit)}</mark>${esc(s.post)}${s.post.length >= 60 ? '…' : ''}`}</p>`).join('')}</div>`).join('')
    + `<div class="jshare"><button class="pri" id="jf-go"${rep && !same ? '' : ' disabled'}>${!rep ? 'Type what to replace it with' : same ? 'That’s the same word' : `Replace ${r.total === 1 ? 'it' : `all ${r.total}`}`}</button></div>`
    + `<p class="hint">${how}, any case. Replace changes every match above, wherever it is. Moods stay and nothing is re-summarised. A copy of your journal is saved first.</p>`;
}
const jfSoon = () => { clearTimeout(jfTimer); jfTimer = setTimeout(jfRun, 250); };
$('#jf-find').oninput = jfSoon; $('#jf-rep').oninput = jfSoon;
$('#jf-find').onkeydown = (e) => { if (e.key === 'Enter') { e.preventDefault(); $('#jf-rep').focus(); } };
$('#jfind').addEventListener('click', async (e) => {
  const md = e.target.closest('[data-jfm]');
  if (md) {
    jfMode = md.dataset.jfm; $('#jfind').querySelectorAll('[data-jfm]').forEach((b) => b.classList.toggle('on', b === md));
    return jfRun();
  }
  const s = e.target.closest('[data-jfs]');
  if (s) {
    jfScope = s.dataset.jfs; $('#jfind').querySelectorAll('[data-jfs]').forEach((b) => b.classList.toggle('on', b === s));
    return jfRun();
  }
  if (!e.target.closest('#jf-go')) return;
  const q = $('#jf-find').value.trim(), rep = $('#jf-rep').value.trim(), n = $('#jf-res').querySelectorAll('.jth-e').length;
  if (!rep || !await confirmSheet({ title: `Replace “${q}” with “${rep}”?`, text: `Every match shown, in ${jfN(n, 'entry', 'entries')}${jfMode === 'contains' ? ', including inside other words' : ''}. A copy of your journal is saved first.`, ok: n === 1 && $('#jf-res').querySelectorAll('mark').length === 1 ? 'Replace it' : 'Replace all', danger: true })) return;
  try { const r = await post('/api/bot/journal/replace', jfBody(true)); snack(`Replaced ${jfN(r.total, 'time', 'times')}`); }
  catch { snack('Couldn’t replace right now'); return; }
  J.texts = {}; await loadJournal(); jfRun();
});
document.querySelector('[data-close-jfind]').onclick = closeFind;
$('#jfind-open').onclick = () => { if (J) openFind(); };

// ----- days marked for a fresh summary tonight (re-runs only, not tonight's entry), so a mistaken one can be cancelled
const jQueued = () => J.entries.filter((e) => e.sum_due && e.summary && e.date !== J.today && e.date !== J.date);
function renderJQueue() {
  const n = jQueued().length, N = J.now || {}, w = (N.wait || []).length;
  const sub = N.run ? `Writing ${jShort(N.run)} now${w ? `, ${w} waiting` : ''}` : n ? `${n} ${n === 1 ? 'day' : 'days'}, tonight at 4:30 AM` : 'Nothing queued';
  $('#j-queue').innerHTML = `<button class="card row-btn" id="jq-open"${n ? '' : ' disabled'}><span class="jic"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M20 12a8 8 0 1 1-2.3-5.7"/><path d="M20 4v4.5h-4.5"/></svg></span>
    <span><b>Queued for a fresh summary</b><small>${sub}</small></span>${n ? `<span class="chev">${CHEV}</span>` : ''}</button>`;
  jNowPoll();
}
// Run now: the bot writes them straight away, one at a time, oldest first; the rest wait their turn
const jNowSet = () => new Set([J?.now?.run, ...(J?.now?.wait || [])].filter(Boolean));
const jNowSt = (d) => (d === J.now?.run ? 'run' : (J.now?.wait || []).includes(d) ? 'wait' : '');
function renderQueue() {
  const es = jQueued(), idle = es.filter((e) => !jNowSt(e.date)).length;
  const acts = (d) => ({ run: `<span class="jq-st">Writing…</span><button class="jq-x" disabled>Cancel</button>`,
    wait: `<span class="jq-st">Waiting</span><button class="jq-x" data-jq-stop="${d}">Cancel</button>` })[jNowSt(d)]
    || `<button class="jq-x jq-go" data-jq-go="${d}">Run now</button><button class="jq-x" data-jq-x="${d}">Cancel</button>`;
  $('#jq-body').innerHTML = es.length ? (es.length > 1 && idle ? `<button class="sg-go jq-all" data-jq-all>Run all now (${idle})</button>` : '')
    + es.map((e) => `<div class="card jth-e"><h4><span>${jShort(e.date)}</span><span class="jq-acts">${acts(e.date)}</span></h4>
    <p>${esc(e.summary.length > 160 ? e.summary.slice(0, 160).trim() + '…' : e.summary)}</p></div>`).join('')
    + '<p class="hint">Gemma rewrites these at 4:30 AM, including the mood and tags. Run now writes them straight away, a few minutes each, one at a time. Cancel keeps the summary a day has now.</p>'
    : '<div class="empty">Nothing queued. Every summary stays as it is.</div>';
}
let jNowT = null;
function jNowPoll() {  // while summaries are being written: watch them, and say when each one lands
  if (jNowT || !jNowSet().size) return;
  jNowT = setInterval(async () => {
    const was = jNowSet();
    try { J.now = await getJSON('/api/bot/journal/now'); } catch { return; }
    const gone = [...was].filter((d) => !jNowSet().has(d));
    if (gone.length) {
      const r = await getJSON('/api/bot/journal').catch(() => null);
      for (const d of gone) { const i = J.entries.findIndex((e) => e.date === d), f = r?.entries.find((e) => e.date === d); if (i >= 0 && f) J.entries[i] = f; }
      const ok = gone.filter((d) => !jEntry(d)?.sum_due), bad = gone.filter((d) => jEntry(d)?.sum_due);
      if (bad.length) snack(`Couldn’t write ${bad.map(jShort).join(' and ')}. ${bad.length > 1 ? 'They stay' : 'It stays'} queued for 4:30 AM.`, { bad: true });
      else snack(`${ok.map(jShort).join(' and ')} ${ok.length > 1 ? 'have fresh summaries' : 'has a fresh summary'}`);
      renderJRecent();
    }
    if (!jNowSet().size) { clearInterval(jNowT); jNowT = null; }
    renderJQueue(); if (!$('#jq').hidden) { if (jQueued().length) renderQueue(); else closeQueue(); }
  }, 5000);
}
function openQueue() { $('#jq').hidden = false; document.body.style.overflow = 'hidden'; renderQueue(); }
function closeQueue() { $('#jq').hidden = true; document.body.style.overflow = ''; }
document.querySelector('[data-close-jq]').onclick = closeQueue;
$('#j-queue').onclick = (e) => { if (e.target.closest('#jq-open') && J && jQueued().length) openQueue(); };
$('#jq-body').onclick = async (e) => {
  const g = e.target.closest('[data-jq-go], [data-jq-all], [data-jq-stop]');
  if (g) {
    g.disabled = true;
    const stop = 'jqStop' in g.dataset, ds = 'jqAll' in g.dataset ? jQueued().map((x) => x.date).filter((d) => !jNowSt(d)) : [g.dataset.jqGo || g.dataset.jqStop];
    try { for (const d of ds) J.now = (await post('/api/bot/journal/now', stop ? { date: d, cancel: true } : { date: d })).now; if (stop) snack('Back in the queue for 4:30 AM'); }
    catch { snack(stop ? 'Couldn’t cancel right now' : 'Couldn’t start it right now', { bad: true }); }
    renderQueue(); renderJQueue(); return;
  }
  const b = e.target.closest('[data-jq-x]'); if (!b) return;
  b.disabled = true;
  try { const r = await post('/api/bot/journal/unqueue', { date: b.dataset.jqX }); if (r?.entry) Object.assign(jEntry(b.dataset.jqX), r.entry); delete jEntry(b.dataset.jqX).sum_due; snack('Keeps its summary'); }
  catch { b.disabled = false; return snack('Couldn’t cancel right now'); }
  renderQueue(); renderJQueue();
  if (!jQueued().length) closeQueue();
};
document.querySelector('[data-close-jther]').onclick = closeTher;
function jStretch() {
  const days = jStretchDays();
  const es = days.map(jEntry).filter((e) => e && (e.words || e.text?.trim())), moods = es.filter((e) => e.mood && !jThinking(e)).map((e) => e.mood);
  const count = es.flatMap((e) => e.tags || []).reduce((o, t) => ((o[t] = (o[t] || 0) + 1), o), {});
  return { days, es, sofar: days.filter((d) => d <= J.today).length, avg: moods.length ? (moods.reduce((a, b) => a + b, 0) / moods.length).toFixed(1) : null,
    tags: Object.entries(count).sort((a, b) => b[1] - a[1]).slice(0, 3).map(([t]) => t) };
}
function renderTher() {
  const { days, es, sofar, avg, tags } = jStretch(), stat = (v, l) => `<div><b>${esc(v)}</b><small>${l}</small></div>`;
  const rc = jWkAll(), wsub = rc.length ? `${plural(rc.length, 'week')}, latest ${jWeekRng(rc[0])}` : 'A new one every Wednesday by 12 noon';
  $('#jther-body').innerHTML = `<div class="seg jrange">${[[7, 'Wed to Tue'], [14, '2 weeks'], [28, '4 weeks']].map(([n, l]) => `<button class="${n === jRange ? 'on' : ''}" data-jrange="${n}">${l}</button>`).join('')}</div>
    <div class="card jth"><div class="jstats">${stat(`${es.length}/${sofar}`, sofar < jRange ? 'nights so far' : 'nights written')}${stat(avg ?? '–', 'average mood')}${stat(tags[0] || '–', 'came up most')}</div>
      <div class="jstrip" style="grid-template-columns:repeat(${jRange},1fr)">${days.map((d) => { const w = jEntry(d), e = jThinking(w) ? null : w, pend = !e?.mood && (!!(w?.words || w?.text?.trim()) || jAwait(d));
        return `<i class="${e?.mood ? jMoodCls(e.mood) : pend ? 'pend' : ''}" style="height:${e?.mood ? e.mood * 10 : 8}%" title="${esc(jShort(d) + (e?.mood ? `: ${e.mood}/10` : pend ? ': mood arrives by morning' : ''))}"></i>`; }).join('')}</div>
      <div class="jstrip-l"><span>${shortDate(days[0])}</span><span>Mood each day</span><span>${shortDate(days.at(-1))}</span></div></div>
    <button class="card row-btn jwk-row" data-jwks><span class="jic">${JSPARK}</span><span><b>Weekly summaries</b><small>${wsub}</small></span><span class="chev">${CHEV}</span></button>
    ${days.includes(J.today) && jAwait(J.today) && !es.some((e) => e.date === J.today) ? `<div class="card jth-e"><h4><span>${jShort(J.today)}</span></h4>${jWait('<b>Summary pending.</b> Write tonight and your mood and summary arrive by morning.')}</div>` : ''}
    ${es.length ? [...es].reverse().map((e) => { const th = jThinking(e);
      return `<button class="card jth-e" data-jday="${e.date}"><h4><span>${jShort(e.date)}</span>${e.mood && !th ? `<em class="${jMoodCls(e.mood)}">${e.mood}/10</em>` : ''}</h4>
      ${th ? jWait('<b>Summary pending.</b> Your mood and summary arrive by morning.') : `<p>${esc(e.summary || ((e.text || '').length > 220 ? e.text.slice(0, 220).trim() + '…' : e.text || ''))}</p>`}</button>`; }).join('')
      + `<div class="jshare"><button class="pri" data-jshare="sum">${COPY_ICONS}Copy summary</button><button data-jshare="full">${COPY_ICONS}Copy full entries</button></div>`
      : '<div class="empty">No entries in this stretch yet.</div>'}`;
}
async function jShare(full, btn) {
  const { days, es, sofar, avg, tags } = jStretch();
  const week = jRange === 7 && jWeek?.status === 'ready' ? jWeekText(jWeek) + '\n\n' : '';  // the weekly summary goes on top
  const text = week + [`Journal, ${shortDate(days[0])} to ${shortDate(days.at(-1))}`,
    `Nights written: ${es.length} of ${sofar}${avg ? ` • Average mood: ${avg}/10` : ''}`, ...(tags.length ? [`Came up most: ${tags.join(', ')}`] : []), '',
    ...es.flatMap((e) => { const th = jThinking(e);  // still being read: send the words, never the old summary or mood
      return [`${jShort(e.date)}${e.mood && !th ? ` • mood ${e.mood}/10` : ''}`, full || th ? (e.text || '').trim() : e.summary || (e.text || '').trim().slice(0, 300), '']; })].join('\n').trim();
  return jSend(text, btn);
}
function jSend(text, btn) {  // copies (the buttons say Copy, so no share sheet even where one exists); the icon turns into a green tick
  return clipCopy(text).then((ok) => { if (btn) copyFlash(btn, ok); if (!ok) snack('Couldn’t copy on this device.', { bad: true }); });
}

document.addEventListener('click', (ev) => {
  const t = ev.target.closest('[data-jmood],[data-jdone],[data-jclose],[data-jedit],[data-jday],[data-jm],[data-jrange],[data-jshare],[data-jread],[data-jwrite]');
  if (!t || !J) return;
  if (t.dataset.jmood) return jMoodSheet(t.dataset.jmood);
  if (t.dataset.jwrite !== undefined) {
    jWrite = true; renderJToday();
    const ta = $('#j-today [data-jt]'); if (ta) { ta.focus({ preventScroll: true }); ta.setSelectionRange(ta.value.length, ta.value.length); }
    return;
  }
  if (t.dataset.jdone !== undefined) return jDone(t.closest('.jw'));
  if (t.dataset.jclose !== undefined) return jClose(t.closest('.jw'));
  if (t.dataset.jedit) {
    const d = t.dataset.jedit; jEdit.add(d);
    const box = jOpen === d ? $('#jent-body') : $('#j-today');
    jOpen === d ? renderEntry() : renderJToday();
    const ta = box.querySelector('[data-jt]'); if (ta) { ta.focus({ preventScroll: true }); ta.setSelectionRange(ta.value.length, ta.value.length); }
    return;
  }
  if (t.dataset.jread) return jOpenEntry(t.dataset.jread);
  if (t.dataset.jday) {
    if (t.dataset.jday === J.today && $('#jther').hidden && $('#jfind').hidden && !jEntry(J.today)?.done) { toTop(); jWrite = true; renderJToday(); return $('#j-today [data-jt]')?.focus({ preventScroll: true }); }
    return jOpenEntry(t.dataset.jday);
  }
  if (t.dataset.jm) { const [y, m] = jMonth.split('-').map(Number); jMonth = isoDay(new Date(y, m - 1 + +t.dataset.jm, 1)).slice(0, 7);
    renderCal(); if (!J.years.has(jMonth.slice(0, 4))) jNeed([jMonth + '-01']).then(renderCal); return; }  // an older year: its moods load in
  if (t.dataset.jrange) { jRange = +t.dataset.jrange; return jNeed(jStretchDays()).then(renderTher); }
  if (t.dataset.jshare) return jShare(t.dataset.jshare === 'full', t);
});
document.addEventListener('keydown', (ev) => { if ((ev.key === 'Enter' || ev.key === ' ') && ev.target.matches?.('[data-jread]')) { ev.preventDefault(); jOpenEntry(ev.target.dataset.jread); } });
