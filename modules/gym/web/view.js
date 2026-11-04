// ---------- Gym ----------
// Days (Chest, Back...) hold exercises; each visit to a day is a session of sets. First set of an exercise is the warm-up.
let G = null, gymDay = null, gymTab = 'log', gymEdit = false, gymMetric = 'top', gymRange = 90;
// gDate: a past day being filled in (null = today). History panel: hMonth shown, hSel = session open, hPick = empty day tapped,
// hDirect = the panel was opened straight onto one workout, so Done closes it instead of going back to the calendar
let gymNext = null, gDate = null, hMonth = null, hSel = null, hPick = null, hDirect = false;
const logDate = () => gDate || G.today;
const gymOpen = new Set(), gymWarm = new Set(), gymSkip = new Set();
const PLUS = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M12 5v14M5 12h14"/></svg>';
const kgTxt = (kg) => kg ? String(Math.round(kg * 100) / 100) : 'BW';
const durTxt = (n) => n < 60 ? `${n} sec` : n % 60 ? `${Math.floor(n / 60)}:${String(n % 60).padStart(2, '0')} min` : `${n / 60} min`;
const setTxt = (s) => s.secs ? durTxt(s.secs) : `${kgTxt(s.kg)}${s.kg ? ' kg' : ''} × ${s.reps}`;
const shortSet = (s) => s.secs ? durTxt(s.secs) : `${kgTxt(s.kg)}${s.kg ? ' kg' : ''} × ${s.reps}`;  // always say kg, so weight and reps can't be mixed up
const daysAgo = (d) => Math.round((dParse(G.today) - dParse(d)) / 864e5);
const agoTxt = (d) => { const n = daysAgo(d); return n <= 0 ? 'today' : n === 1 ? 'yesterday' : n < 14 ? `${n} days ago` : n < 60 ? `${Math.round(n / 7)} weeks ago` : shortDate(d); };
const nKg = (v) => Math.round(v).toLocaleString('en-GB');
const dayOf = (id) => G.days.find((d) => d.id === id);
const dayExercises = (day) => G.exercises.filter((e) => e.day === day && !e.hidden);
const daySessions = (day) => G.sessions.filter((x) => x.day === day).sort((a, b) => a.date.localeCompare(b.date));
const todaySession = (day) => G.sessions.find((x) => x.day === day && x.date === logDate());
// a warm-up that turned out to be the only set of that exercise counts as a main set
const working = (sets) => sets.filter((s) => !s.warm || !sets.some((o) => o !== s && o.ex === s.ex));
const e1rm = (s) => s.reps === 1 ? s.kg : s.kg * (1 + s.reps / 30);
const heaviest = (sets) => sets.reduce((a, b) => !a || b.kg > a.kg || (b.kg === a.kg && b.reps + (b.secs || 0) > a.reps + (a.secs || 0)) ? b : a, null);
const pScore = (s) => s.secs || e1rm(s);  // what a PR beats: estimated max, or the longest hold
const volume = (sets) => working(sets).reduce((a, s) => a + s.kg * s.reps, 0);
function lastFor(ex, before = logDate()) {
  const x = G.sessions.filter((x) => x.date < before && x.sets.some((s) => s.ex === ex)).sort((a, b) => b.date.localeCompare(a.date))[0];
  return x ? { date: x.date, sets: x.sets.filter((s) => s.ex === ex) } : null;
}
// Same idea as the server's gym_key: "DB bench presses" and "dumbbell bench press" are one exercise.
const GW = { db: 'dumbbell', dbs: 'dumbbell', bb: 'barbell', kb: 'kettlebell', inc: 'incline', dec: 'decline', ext: 'extension', extensions: 'extension', ohp: 'overhead press', rdl: 'romanian deadlift', rdls: 'romanian deadlift' };
const gKey = (n) => n.toLowerCase().replace(/[^a-z0-9 ]+/g, ' ').split(/\s+/).filter(Boolean).map((w) => GW[w] || w).join(' ').split(' ')
  .map((w) => w.length > 3 && w.endsWith('s') && !w.endsWith('ss') ? w.slice(0, -1) : w).filter((w) => !['the', 'a', 'on', 'with'].includes(w)).join(' ');
function gSim(typed, name) {
  const a = gKey(typed), b = gKey(name);
  if (!a || !b) return 0;
  if (a === b) return 1;
  const ta = a.split(' '), tb = b.split(' ');
  const hit = ta.filter((w) => tb.some((v) => v === w || (w.length >= 2 && v.startsWith(w)) || (v.length >= 4 && w.startsWith(v)))).length / ta.length;
  const bg = (t) => { const o = []; for (let i = 0; i < t.length - 1; i++) o.push(t.slice(i, i + 2)); return o; };
  const A = bg(a.replace(/ /g, '')), B = bg(b.replace(/ /g, ''));
  const dice = A.length && B.length ? 2 * A.filter((x) => { const i = B.indexOf(x); if (i < 0) return false; B.splice(i, 1); return true; }).length / (A.length + bg(b.replace(/ /g, '')).length) : 0;
  return Math.max(hit * .92, dice);
}

// What a day trains, read from its name ("Chest and Triceps" -> chest, triceps), and common exercises for each muscle.
const MUSCLES = { chest: 'Chest', triceps: 'Triceps', back: 'Back', biceps: 'Biceps', shoulders: 'Shoulders', abs: 'Abs', legs: 'Legs' };
const LIB = {
  chest: ['Bench press', 'Incline dumbbell press', 'Incline chest press', 'Chest press machine', 'Pec fly', 'Cable crossover', 'Dumbbell fly', 'Decline bench press', 'Push-ups'],
  triceps: ['Tricep pushdown', 'Rope pushdown', 'Overhead tricep extension', 'Skull crushers', 'Tricep dips', 'Close-grip bench press', 'Tricep kickback'],
  back: ['Lat pulldown', 'Seated cable row', 'Barbell row', 'Pull-ups', 'One-arm dumbbell row', 'T-bar row', 'Deadlift', 'Straight-arm pulldown'],
  biceps: ['Barbell curl', 'Dumbbell curl', 'Hammer curl', 'Preacher curl', 'Incline dumbbell curl', 'Cable curl', 'Concentration curl'],
  shoulders: ['Overhead press', 'Dumbbell shoulder press', 'Lateral raise', 'Front raise', 'Rear delt fly', 'Face pull', 'Shrugs', 'Upright row'],
  abs: ['Plank', 'Cable crunch', 'Hanging leg raise', 'Crunches', 'Ab wheel rollout', 'Russian twist', 'Decline sit-ups', 'Leg raise'],
  legs: ['Squat', 'Leg press', 'Romanian deadlift', 'Leg extension', 'Leg curl', 'Walking lunges', 'Bulgarian split squat', 'Calf raise', 'Hip thrust'],
};
// first match wins, so the specific ones ("leg curl", "rear delt fly", "close-grip bench") come before the broad ones
const MUSCLE_RX = [
  ['legs', /\b(squats?|leg (press|extension|curl)s?|lunges?|calf|calves|hip thrusts?|romanian|rdls?|glutes?|hamstrings?|quads?|split squat|hack)\b/i],
  ['triceps', /\b(triceps?|pushdowns?|skull|dips?|close[ -]grip|kickbacks?|french press)\b/i],
  ['biceps', /\b(biceps?|curls?)\b/i],
  ['abs', /\b(abs?|crunch(es)?|sit[ -]?ups?|planks?|leg raises?|russian|rollouts?|core|obliques?)\b/i],
  ['shoulders', /\b(shoulders?|overhead press|ohp|military|lateral|front raises?|rear delts?|delts?|face pulls?|shrugs?|upright|arnold)\b/i],
  ['back', /\b(rows?|pulldowns?|pull[ -]?ups?|chin[ -]?ups?|deadlifts?|lats?|back extensions?|pullovers?)\b/i],
  ['chest', /\b(bench|chest|pec|pectoral|fly|flyes|flies|crossovers?|push[ -]?ups?|press)\b/i],
];
const muscleOf = (name) => (MUSCLE_RX.find(([, rx]) => rx.test(name)) || [null])[0];
function dayMuscles(name) {
  const n = name.toLowerCase(), m = new Set();
  if (/full ?body/.test(n)) return Object.keys(MUSCLES);
  if (/\bchest|\bpec/.test(n)) m.add('chest');
  if (/tricep/.test(n)) m.add('triceps');
  if (/\bback\b|\blats?\b/.test(n)) m.add('back');
  if (/bicep/.test(n)) m.add('biceps');
  if (/shoulder|delt/.test(n)) m.add('shoulders');
  if (/\babs?\b|\bcore\b/.test(n)) m.add('abs');
  if (/\blegs?\b|quad|hamstring|glute|calf|calves/.test(n)) m.add('legs');
  if (/\barms?\b/.test(n)) { m.add('biceps'); m.add('triceps'); }
  if (/\bpush\b/.test(n)) { m.add('chest'); m.add('shoulders'); m.add('triceps'); }
  if (/\bpull\b/.test(n)) { m.add('back'); m.add('biceps'); }
  return [...m];
}
const SPLIT = ['Chest and Triceps', 'Back and Biceps', 'Shoulders and Abs', 'Legs'];
// the split goes round in the order you made the days: after the last day you trained comes the next one
function upNext(days) {
  if (!days.length || G.sessions.some((x) => x.date === G.today)) return null;
  const past = G.sessions.filter((x) => days.some((d) => d.id === x.day)).sort((a, b) => a.date.localeCompare(b.date) || a.started - b.started);
  if (!past.length) return days.length >= 2 ? days[0].id : null;
  const i = days.findIndex((d) => d.id === past.at(-1).day);
  return days[(i + 1) % days.length].id;
}
const UP = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 15l6-6 6 6"/></svg>';
const CHECK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
// beat every earlier session's best (estimated max) for this exercise today?
function isPR(exId, sets, date = logDate()) {
  const tw = working(sets.filter((s) => s.ex === exId)); if (!tw.length) return false;
  const prev = Math.max(0, ...G.sessions.filter((x) => x.date < date).flatMap((x) => working(x.sets.filter((s) => s.ex === exId))).map(pScore));
  return prev > 0 && Math.max(...tw.map(pScore)) > prev + 1e-9;
}
const ARROW = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';

async function loadGym() {
  try { G = await getJSON('/api/bot/gym'); } catch {
    if (!G) $('#gym-body').innerHTML = '<div class="err">The gym log is unavailable right now.</div>';
    return false;
  }
  renderGymHome();
  if (gymDay && !$('#gymp').hidden) renderGymDay();
  if (!$('#wtp').hidden) renderWt();
  return true;
}

function renderGymHome() {
  const days = G.days.filter((d) => !d.hidden), el = $('#gym-body');
  $('#gym-sub').textContent = dParse(G.today).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
  const lastOf = (d) => daySessions(d.id).at(-1)?.date || '';
  const next = upNext(days);
  // what you're training today sits on top, one tap to carry on
  const todays = G.sessions.filter((x) => x.date === G.today && dayOf(x.day) && !dayOf(x.day).hidden);
  const hero = gymEdit ? '' : todays.map((x) => {
    const w = working(x.sets), exN = new Set(x.sets.map((s) => s.ex)).size;
    return x.finished
      ? `<button class="ghero fin" data-gday="${x.day}"><span><small>${CHECK}Workout done</small><b>${esc(dayOf(x.day).name)}</b>
      <em>${plural(exN, 'exercise')}${w.length ? ` • ${nKg(volume(x.sets))} kg lifted` : ''}</em></span><i>View${ARROW}</i></button>`
      : `<button class="ghero" data-gday="${x.day}"><span><small>Today</small><b>${esc(dayOf(x.day).name)}</b>
      <em>${plural(exN, 'exercise')}${w.length ? ` • ${nKg(volume(x.sets))} kg lifted` : ''}</em></span><i>Continue${ARROW}</i></button>`;
  }).join('');
  const tiles = days.map((d, i) => {
    const last = lastOf(d), n = dayExercises(d.id).length;
    if (gymEdit) return `<div class="gedit-r">
      <label class="gedit-n"><input value="${esc(d.name)}" data-rename-day="${d.id}" aria-label="Rename ${esc(d.name)}" maxlength="30" enterkeyhint="done">${PEN}</label>
      <button class="gmv" data-gmove="${d.id}|-1" aria-label="Move up" ${i ? '' : 'disabled'}>${UP}</button><button class="gmv" data-gmove="${d.id}|1" aria-label="Move down" ${i < days.length - 1 ? '' : 'disabled'}>${UP}</button>
      <button class="gdel" data-gdel="${d.id}" aria-label="Remove ${esc(d.name)}">${TRASH}</button></div>`;
    return `<button class="card gday" data-gday="${d.id}" style="animation-delay:${i * 30}ms">${next === d.id && !hero ? '<span class="tag">Up next</span>' : ''}
      <b>${esc(d.name)}</b><small>${n ? plural(n, 'exercise') : 'No exercises yet'}</small>
      <span class="gd-when">${last === G.today ? '<i class="dot ok"></i>Done today' : last ? 'Trained ' + agoTxt(last) : 'Not trained yet'}</span></button>`;
  }).join('');
  const add = gymEdit ? '' : `<button class="gday add wide" id="gday-add">${PLUS}Add a day</button>`;
  const quick = days.length ? '' : `<button class="gsplit" data-gsplit><b>Use the 4-day split</b><small>${SPLIT.join(' • ')}</small></button>
    <p class="hint">Or add days one by one. Tap a day to start logging it.</p><div class="gquick">${
    ['Chest', 'Back', 'Legs', 'Shoulders', 'Arms', 'Push', 'Pull', 'Full body'].map((n) => `<button data-gquick="${n}">${n}</button>`).join('')}</div>`;

  // this week, Monday to Sunday
  const t = dParse(G.today), mon = new Date(t); mon.setDate(t.getDate() - ((t.getDay() + 6) % 7));
  const week = [...Array(7)].map((_, i) => { const d = new Date(mon); d.setDate(mon.getDate() + i); return isoDay(d); });
  const wk = G.sessions.filter((x) => week.includes(x.date));
  const vol = wk.reduce((a, x) => a + volume(x.sets), 0);
  const wkStart = (d) => { const x = dParse(d); x.setDate(x.getDate() - ((x.getDay() + 6) % 7)); return isoDay(x); };
  const weeks = new Set(G.sessions.map((x) => wkStart(x.date)));
  let streak = 0; const c = new Date(mon); if (!weeks.has(isoDay(c))) c.setDate(c.getDate() - 7);
  while (weeks.has(isoDay(c))) { streak++; c.setDate(c.getDate() - 7); }
  const weekCard = days.length ? `<div class="label">This week<button data-hopen>See all workouts</button></div><div class="card gweek">
    <div class="h">${plural(wk.length, 'session')}<small>${streak >= 2 ? `${streak} weeks in a row` : ''}</small></div>
    <div class="wk">${week.map((d, i) => { const x = wk.filter((s) => s.date === d).map((s) => dayOf(s.day)?.name || '');
      return `<button data-hday="${d}" ${d > G.today ? 'disabled' : ''} aria-label="${esc(longDate(d) + (x.length ? ': ' + x.join(', ') : ''))}"><i class="${x.length ? 'on' : ''}${d === G.today ? ' now' : ''}">${x.length ? esc(dayAbbr(x[0])) : ''}</i><span>${WD[i]}</span></button>`; }).join('')}</div>
    <p>${vol ? `${nKg(vol)} kg lifted in working sets` : wk.length ? 'Only warm-ups so far, log a working set to count the weight' : 'Nothing logged yet this week'}</p></div>` : '';

  // nothing started today: the day that's up next, one tap to start; every other day is a small card below
  const nd = !hero && !gymEdit && days.length ? dayOf(next) || days[0] : null;
  const start = nd ? `<button class="ghero" data-gday="${nd.id}"><span><small>Up next</small><b>${esc(nd.name)}</b>
      <em>${plural(dayExercises(nd.id).length, 'exercise')} • ${lastOf(nd) ? 'trained ' + agoTxt(lastOf(nd)) : 'not trained yet'}</em></span><i>Start${ARROW}</i></button>` : '';
  const top = new Set([...todays.map((x) => x.day), ...(nd ? [nd.id] : [])]), others = days.filter((d) => !top.has(d.id));
  const pick = others.length ? `<div class="label">${hero ? 'Another day' : 'Or train'}</div><div class="gpick">${others.map((d, i) => { const last = lastOf(d);
    return `<button class="card" data-gday="${d.id}" style="animation-delay:${i * 30}ms"><b>${esc(d.name)}</b><small>${last === G.today ? 'Done today' : last ? 'Trained ' + agoTxt(last) : 'Not trained yet'}</small></button>`; }).join('')}</div>` : '';

  // your last three personal bests, newest first
  const prs = [];
  for (const x of [...G.sessions].sort((a, b) => b.date.localeCompare(a.date) || b.started - a.started)) {
    for (const id of new Set(x.sets.map((s) => s.ex))) {
      if (prs.length < 3 && isPR(id, x.sets, x.date)) prs.push({ x, ex: G.exercises.find((e) => e.id === id), b: working(x.sets.filter((s) => s.ex === id)).reduce((a, s) => !a || e1rm(s) > e1rm(a) ? s : a, null) });
    }
    if (prs.length >= 3) break;
  }
  const prCard = prs.length ? `<div class="label">Recent PRs</div><div class="card sg-list">${prs.map((p) => `<button class="sg-row" data-gses="${p.x.id}">
      <span class="t"><b>${esc(p.ex?.name || 'Exercise')}<span class="pr">PR</span></b><small>${esc(dayOf(p.x.day)?.name || '')} • ${agoTxt(p.x.date)}</small></span>
      <span class="r"><b>${shortSet(p.b)}</b></span></button>`).join('')}</div>` : '';
  const tools = `<div class="gtools"><button data-hopen>${CAL}All workouts</button><button id="gday-add">${PLUS}Add a day</button><button id="gym-edit">${PEN}Edit days</button></div>`;

  el.classList.toggle('settled', !!renderGymHome.done); renderGymHome.done = true;
  el.innerHTML = !days.length ? `<div class="gq"><h2>What did you hit today?</h2></div>${add}${quick}`
    : gymEdit ? `<div class="gq"><h2>Edit your days</h2><button id="gym-edit">Done</button></div><div class="card gedit">${tiles}</div>
      <p class="hint">Tap a name to rename it. The order is your rotation: it decides which day comes up next. Removing a day keeps its history.</p>`
    : `${hero}${start}${pick}${weekCard}${wtBtn()}${prCard}${tools}`;
}

// ----- body weight: one weigh-in a day, a chart and the log (2026-10-30)
const WT_IC = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="3.5" y="3.5" width="17" height="17" rx="4.5"/><path d="M7.5 10a6 6 0 0 1 9 0"/><path d="M12 10.5l1.6-2"/></svg>';
const WT_FWD = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
let wtN = 10;  // the chart: last 10, last 20, or 0 for all
const wtKg = (n) => (Math.round(n * 100) / 100).toLocaleString('en-GB', { maximumFractionDigits: 2 });
const wtDiff = (n) => `${n > 0 ? '+' : n < 0 ? '−' : ''}${wtKg(Math.abs(n))} kg`;
const wtDate = (d, wd) => dParse(d).toLocaleDateString('en-GB', { weekday: wd ? 'short' : undefined, day: 'numeric', month: 'short', year: d.slice(0, 4) === G.today.slice(0, 4) ? undefined : 'numeric' });
const wtChip = (n, txt) => `<span class="wt-c${n < 0 ? ' down' : ''}">${wtDiff(n)} <small>${txt}</small></span>`;
function wtBtn() {
  const l = (G.weight || []).at(-1);
  return `<button class="news-btn" id="wt-open"><span class="nic">${WT_IC}</span><span><b>Weight</b><small>${l ? `${wtKg(l.kg)} kg • ${agoTxt(l.date)}` : 'Log your weight'}</small></span>${WT_FWD}</button>`;
}
function openWt() { $('#wtp').hidden = false; document.body.style.overflow = 'hidden'; renderWt(); $('#wtp .panel-body').scrollTop = 0; }
function closeWt() { $('#wtp').hidden = true; document.body.style.overflow = ''; }
function renderWt() {
  const ws = G.weight || [], el = $('#wt-body');
  if (!ws.length) { el.innerHTML = '<div class="card wt-hero"><p>No weigh-ins yet. Log one and your chart starts here.</p></div><button class="sg-go" data-wt-add>Log weight</button>'; return; }
  const l = ws.at(-1), p = ws.at(-2), f = ws[0];
  el.innerHTML = `<div class="card wt-hero"><small>Latest • ${wtDate(l.date, true)}</small><div class="wt-big num">${wtKg(l.kg)}<span>kg</span></div>
    <div class="wt-chg">${p ? wtChip(l.kg - p.kg, `since ${wtDate(p.date)}`) : ''}${ws.length > 2 ? wtChip(l.kg - f.kg, `since ${wtDate(f.date)}`) : ''}</div></div>
    <div class="seg wt-seg">${[[10, 'Last 10'], [20, 'Last 20'], [0, 'All']].map(([n, t]) => `<button data-wtn="${n}" class="${wtN === n ? 'on' : ''}">${t}</button>`).join('')}</div>
    <div class="card wt-chart"><div class="wt-read"></div><div class="wt-svg"></div></div>
    <button class="sg-go" data-wt-add>Log weight</button>
    <div class="label">Every weigh-in<span>${ws.length}</span></div>
    <div class="card sg-list">${[...ws].reverse().map((w, i, a) => { const prev = a[i + 1], d = prev && w.kg - prev.kg, tot = prev && w.kg - ws[0].kg;  // since last time, then since the first weigh-in
      const c = (n) => (n < 0 ? 'down' : n > 0 ? 'up' : '');
      return `<button class="sg-row" data-wt-edit="${w.date}"><span class="t"><b>${wtDate(w.date, true)}</b>${daysAgo(w.date) < 60 ? `<small>${agoTxt(w.date)}</small>` : ''}</span>
        <span class="r"><b>${wtKg(w.kg)} kg</b>${prev ? `<small class="wt-d"><span class="${c(d)}">${wtDiff(d)}</span> • <span class="tot">${wtDiff(tot)}</span></small>` : ''}</span></button>`; }).join('')}</div>`;
  wtDraw();
}
function wtDraw(sel) {  // drawn to the card's real width, so the labels stay one size on phone and desktop
  const box = $('#wt-body .wt-svg'); if (!box) return;
  const all = G.weight, ws = wtN ? all.slice(-wtN) : all, W = Math.max(240, box.clientWidth), H = 190, L = 36, R = 8, T = 10, B = 24;
  // the axis runs between round numbers: 103.8 at the top makes it 105, 84.5 at the bottom makes it 80, a line every 5 kg
  const ks = ws.map((w) => w.kg), lo = Math.floor(Math.min(...ks) / 5) * 5, hi = Math.max(lo + 5, Math.ceil(Math.max(...ks) / 5) * 5);
  const t0 = dParse(ws[0].date).getTime(), t1 = dParse(ws.at(-1).date).getTime();
  const x = (w) => ws.length < 2 ? (L + W - R) / 2 : L + ((dParse(w.date).getTime() - t0) / (t1 - t0 || 1)) * (W - L - R);
  const y = (kg) => T + ((hi - kg) / (hi - lo)) * (H - T - B);
  const P = ws.map((w) => ({ w, x: x(w), y: y(w.kg) })), f = (n) => n.toFixed(1);
  const line = P.map((p, i) => `${i ? 'L' : 'M'}${f(p.x)} ${f(p.y)}`).join('');
  const ticks = Array.from({ length: (hi - lo) / 5 + 1 }, (_, i) => hi - i * 5);
  const mid = P.reduce((a, p) => Math.abs(p.x - (L + W - R) / 2) < Math.abs(a.x - (L + W - R) / 2) ? p : a, P[0]);  // a middle date only where it has room
  const dates = [ws[0], ...(mid.x - P[0].x > 70 && P.at(-1).x - mid.x > 70 ? [mid.w] : []), ws.at(-1)];
  const s = sel == null ? P.length - 1 : sel, h = P[s];
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" height="${H}" role="img" aria-label="Weight from ${wtDate(ws[0].date)} to ${wtDate(ws.at(-1).date)}">
    ${ticks.map((v) => `<line class="gl" x1="${L}" x2="${W - R}" y1="${f(y(v))}" y2="${f(y(v))}"/><text x="${L - 6}" y="${f(y(v) + 3.5)}" text-anchor="end">${wtKg(v)}</text>`).join('')}
    ${ws.length > 1 ? `<path class="ar" d="${line}L${f(P.at(-1).x)} ${H - B}L${f(P[0].x)} ${H - B}Z"/><path class="ln" d="${line}"/>` : ''}
    ${P.length <= 40 ? P.map((p) => `<circle class="pt" cx="${f(p.x)}" cy="${f(p.y)}" r="2.5"/>`).join('') : ''}
    <g class="hl"><line x1="${f(h.x)}" x2="${f(h.x)}" y1="${T}" y2="${H - B}"/><circle cx="${f(h.x)}" cy="${f(h.y)}" r="4.5"/></g>
    ${[...new Set(dates)].map((w, i, a) => `<text x="${f(x(w))}" y="${H - 6}" text-anchor="${a.length > 1 && i === 0 ? 'start' : i === a.length - 1 && a.length > 1 ? 'end' : 'middle'}">${wtDate(w.date)}</text>`).join('')}</svg>`;
  $('#wt-body .wt-read').innerHTML = `<b class="num">${wtKg(h.w.kg)} kg</b><small>${wtDate(h.w.date, true)}${s === P.length - 1 ? ' • latest' : ''}</small>`;
  const svg = box.firstElementChild;
  const pick = (ev) => { const r = svg.getBoundingClientRect(), px = ((ev.clientX - r.left) / r.width) * W;
    let i = 0; P.forEach((p, j) => { if (Math.abs(p.x - px) < Math.abs(P[i].x - px)) i = j; }); if (i !== s) wtDraw(i); };
  svg.onpointerdown = pick; svg.onpointermove = (ev) => { if (ev.buttons || ev.pointerType === 'mouse') pick(ev); };
}
function wtSheet(date) {
  const ws = G.weight || [], ex = date && ws.find((w) => w.date === date);
  sheetOpen(ex ? 'Edit weigh-in' : 'Log weight', `<form class="sg-f" id="wt-form" autocomplete="off">
    <div class="row2"><div><label for="wt-d">Date</label><input id="wt-d" type="date" max="${G.today}" value="${ex ? ex.date : G.today}"></div>
      <div><label for="wt-k">Weight (kg)</label><input id="wt-k" inputmode="decimal" value="${ex ? ex.kg : ''}" placeholder="${ws.at(-1)?.kg ?? '85.4'}"></div></div>
    <p class="hint" id="wt-h"></p><p class="err-t" id="wt-e"></p><button class="sg-go">Save</button>
    ${ex ? '<button type="button" class="sg-del" id="wt-x">Delete weigh-in</button>' : ''}</form>`);
  const hint = () => { const d = $('#wt-d').value, o = ws.find((w) => w.date === d && w.date !== ex?.date);
    $('#wt-h').textContent = o ? `You logged ${wtKg(o.kg)} kg on this day. Saving replaces it.` : ''; $('#wt-e').textContent = ''; };
  $('#wt-form').oninput = hint; hint();
  const done = (r, msg) => { G.weight = r.weight; closeSheet(); renderWt(); renderGymHome(); snack(msg); };
  $('#wt-form').onsubmit = async (ev) => {
    ev.preventDefault();
    const d = $('#wt-d').value, kg = Number($('#wt-k').value.replace(',', '.').trim());
    if (!d) return ($('#wt-e').textContent = 'Pick a date.');
    if (d > G.today) return ($('#wt-e').textContent = 'Pick today or a day before.');
    if (!(kg >= 30 && kg <= 250)) return ($('#wt-e').textContent = 'Enter your weight in kg, like 85.4.');
    let r = await post('/api/bot/gym/weight', { date: d, kg }).catch(() => null);
    if (r?.ok && ex && ex.date !== d) r = await post('/api/bot/gym/weight', { date: ex.date, delete: true }).catch(() => null);
    if (!r?.ok) return ($('#wt-e').textContent = r?.msg || 'Couldn’t save. Try again.');
    done(r, 'Saved');
  };
  if (ex) $('#wt-x').onclick = async () => { const r = await post('/api/bot/gym/weight', { date: ex.date, delete: true }).catch(() => null);
    if (!r?.ok) return ($('#wt-e').textContent = 'Couldn’t delete. Try again.'); done(r, 'Deleted'); };
}
$('#wt-body').addEventListener('click', (e) => {
  const t = e.target.closest('[data-wtn],[data-wt-add],[data-wt-edit]'); if (!t) return;
  if (t.dataset.wtn) { wtN = +t.dataset.wtn; return renderWt(); }
  wtSheet(t.dataset.wtEdit);
});
document.querySelector('[data-close-wt]').onclick = closeWt;
addEventListener('resize', () => { if (!$('#wtp').hidden) wtDraw(); });

async function addDay(name) {
  name = name.trim(); if (!name) return;
  const r = await post('/api/bot/gym/day', { name }).catch(() => null);
  if (!r?.ok) { alert('Couldn’t add that day. Try again.'); return; }
  await loadGym(); openGymDay(r.day.id);
}
$('#gym-body').addEventListener('click', async (e) => {
  const t = e.target.closest('button'); if (!t) return;
  if (t.id === 'wt-open') return openWt();
  if (t.dataset.gday) return openGymDay(t.dataset.gday);
  if (t.dataset.hopen !== undefined) return openHist();
  if (t.dataset.gses) return openHist({ ses: t.dataset.gses });
  if (t.dataset.hday) {
    const xs = G.sessions.filter((x) => x.date === t.dataset.hday);
    return openHist(xs.length === 1 ? { ses: xs[0].id } : { date: t.dataset.hday });
  }
  if (t.dataset.gquick) return addDay(t.dataset.gquick);
  if (t.dataset.gsplit !== undefined) {
    t.disabled = true;
    for (const name of SPLIT) await post('/api/bot/gym/day', { name }).catch(() => null);
    return loadGym();
  }
  if (t.id === 'gym-edit') { gymEdit = !gymEdit; return renderGymHome(); }
  if (t.id === 'gday-add') {
    (t.closest('.gtools') || t).outerHTML = `<form class="card gday form wide" id="gday-form"><input id="gday-name" placeholder="e.g. Chest" maxlength="30" autocomplete="off" enterkeyhint="done">
      <div class="gd-acts"><button type="button" id="gday-cancel">Cancel</button><button class="main">Add</button></div></form>`;
    $('#gday-name').focus();
    $('#gday-form').onsubmit = (ev) => { ev.preventDefault(); addDay($('#gday-name').value); };
    return;
  }
  if (t.id === 'gday-cancel') return renderGymHome();
  if (t.dataset.gmove) {
    const [id, move] = t.dataset.gmove.split('|');
    await post('/api/bot/gym/day/edit', { id, move: +move }).catch(() => {});
    renderGymHome.done = true; return loadGym();
  }
  if (t.dataset.gdel) {
    const d = dayOf(t.dataset.gdel);
    if (!await confirmSheet({ title: `Remove ${d.name}?`, text: 'Its past workouts stay in your history. Adding a day with the same name brings it back.', ok: 'Remove day', danger: true })) return;
    await post('/api/bot/gym/day/edit', { id: t.dataset.gdel, remove: true }).catch(() => {});
    loadGym();
  }
});
$('#gym-body').addEventListener('keydown', (e) => { if (e.target.dataset?.renameDay !== undefined && e.key === 'Enter') e.target.blur(); });
$('#gym-body').addEventListener('change', async (e) => {
  const i = e.target.closest('[data-rename-day]'); if (!i || !i.value.trim()) return;
  await post('/api/bot/gym/day/edit', { id: i.dataset.renameDay, name: i.value }).catch(() => {});
  G = await getJSON('/api/bot/gym').catch(() => G);
});

// ----- one day: log and progress
// two gym panels can be open at once (history over a day, or a day over history): the last one opened sits on top
const raise = (el) => { $('#gymp').style.zIndex = $('#gymh').style.zIndex = 50; el.style.zIndex = 51; };
function openGymDay(id, date = null) {
  gymDay = id; gDate = date && date !== G.today ? date : null; gymTab = 'log'; gymOpen.clear(); gymWarm.clear(); gymSkip.clear();
  raise($('#gymp')); $('#gymp').hidden = false;
  const ses = todaySession(id);
  if (!(ses?.finished && !gDate)) { renderGymDay(); renderGymDay.last = null; if (gymNext) gymOpen.add(gymNext.id); } document.body.style.overflow = 'hidden'; $('#gymp .panel-body').scrollTop = 0;
  renderGymDay();
}
function closeGym() {
  const day = gymDay, date = logDate();
  renderGymDay.last = null; $('#gymp').hidden = true; gymDay = null; gDate = null; renderGymHome();
  if ($('#gymh').hidden) { document.body.style.overflow = ''; return toTop(); }
  // back in History: show the workout that was just filled in
  const x = G.sessions.find((s) => s.day === day && s.date === date);
  if (x && !hSel) { hSel = x.id; hPick = null; }
  renderHist();
}
document.querySelector('[data-close-gym]').onclick = closeGym;

function drafts() {  // keep what's typed in other open exercises when the screen redraws
  const o = {};
  document.querySelectorAll('#gym-panel .gentry').forEach((g) => { o[g.dataset.ex] = Object.fromEntries([...g.querySelectorAll('.flds input')].map((i) => [i.name, i.value])); });
  return o;
}
function renderGymDay(keep = {}) {
  const d = dayOf(gymDay); if (!d) return closeGym();
  $('#gym-title').textContent = d.name;
  const box = $('#gymp .panel-body'), y = box.scrollTop, view = gymDay + gymTab;
  const pin = [...gymOpen][0], pinEl = pin && document.getElementById('gx-' + pin), pinTop = pinEl && pinEl.getBoundingClientRect().top;
  $('#gym-panel').classList.toggle('settled', renderGymDay.last === view); renderGymDay.last = view;
  $('#gym-panel').innerHTML = gDate ? gymLogHTML(d, keep) : `<div class="gtop"><div class="seg"><button data-gt="log" class="${gymTab === 'log' ? 'on' : ''}">Log</button><button data-gt="progress" class="${gymTab === 'progress' ? 'on' : ''}">Progress</button></div></div>`
    + (gymTab === 'log' ? gymLogHTML(d, keep) : gymProgressHTML(d) + gymPastHTML(d));
  box.scrollTop = y;
  const now = pinTop != null && document.getElementById('gx-' + pin);
  if (now) box.scrollTop += now.getBoundingClientRect().top - pinTop;
}

function gymLogHTML(d, keep) {
  const ses = todaySession(d.id), exs = dayExercises(d.id);
  if (ses?.finished && !gDate) return gymDoneHTML(d, ses);
  const first = (e) => ses?.sets.find((s) => s.ex === e.id)?.at || 0;
  const lastUsed = (e) => lastFor(e.id)?.date || '';
  const doing = exs.filter(first).sort((a, b) => first(a) - first(b));
  const rest = exs.filter((e) => !first(e)).sort((a, b) => lastUsed(b).localeCompare(lastUsed(a)) || a.created - b.created);
  let h = gDate ? `<div class="gpast">${CAL}<span><b>${longDate(gDate)}</b><small>Adding to a past day. Each set saves as you log it.</small></span></div>`
    : exs.length ? `<div class="card gprog"><b>${doing.length ? `${plural(doing.length, 'exercise')} done` : `Today’s ${esc(d.name)}`}</b>
      <small>${longDate(G.today)}</small></div>`
    : `<p class="gdate">${longDate(G.today)}</p>`;
  const mus = dayMuscles(d.name), multi = mus.length > 1;
  // the exercise after the ones done today, in the order they're listed below (worked out before the done cards draw their Next button)
  const byMuscle = (m) => rest.filter((e) => (mus.includes(muscleOf(e.name)) ? muscleOf(e.name) : null) === m);
  gymNext = (multi ? [...mus, null].flatMap(byMuscle) : rest)[0] || null;
  if (doing.length) h += `<div class="label">${gDate ? 'Done that day' : 'Done today'}</div>` + doing.map((e) => gxCard(e, ses, keep, multi)).join('');
  if (rest.length) {
    // on a two-muscle day, list what's left muscle by muscle in the order the day's name gives
    const groups = multi ? [...mus, null].map((m) => [m, rest.filter((e) => (mus.includes(muscleOf(e.name)) ? muscleOf(e.name) : null) === m)]).filter(([, l]) => l.length) : [[null, rest]];
    groups.forEach(([m, l], gi) => {
      const title = m ? MUSCLES[m] : groups.length > 1 ? 'Other' : 'Still to do';
      h += `<div class="label">${title}${gi === 0 && doing.length && m ? '<span style="font-weight:500;text-transform:none;letter-spacing:0">Still to do</span>' : ''}</div>` + l.map((e) => gxCard(e, ses, keep, false)).join('');
    });
  }
  if (ses && working(ses.sets).length && !gDate) h += `<button class="gfinish" data-gfinish>${CHECK}Finish workout</button>`;
  if (!exs.length) h += `<div class="card gempty" style="margin-top:14px">First time logging ${esc(d.name)}.<br>${mus.length ? 'Tap the exercises you do below, or type your own.' : 'Add your first exercise below.'}</div>`;
  h += `<div class="label">Add an exercise</div><div class="card gadd"><div class="gadd-in">${PLUS}<input id="gx-new" placeholder="Type an exercise" autocomplete="off" autocapitalize="words" enterkeyhint="done" maxlength="60"></div><div id="gx-sug"></div></div>`;
  // common exercises for this day's muscles that aren't in it yet
  const have = (n) => exs.some((e) => gSim(n, e.name) >= .8);
  const lib = mus.map((m) => [m, LIB[m].filter((n) => !have(n))]).filter(([, l]) => l.length);
  if (lib.length) h += `<div class="card glib">${lib.map(([m, l]) => `<h4>${multi || mus.length ? MUSCLES[m] : ''}</h4><div class="chips">${
    l.map((n) => `<button data-sg-copy="${esc(n)}">${PLUS}${esc(n)}</button>`).join('')}</div>`).join('')}</div>
    <p class="hint">Tap to add. Anything you add stays with ${esc(d.name)} for next time.</p>`;
  return h;
}

function gymRows(ses, prs) {
  return [...new Set(ses.sets.map((s) => s.ex))].map((id) => {
    // every set, in order: warm-up first, then the main sets numbered
    const e = G.exercises.find((x) => x.id === id), sets = ses.sets.filter((s) => s.ex === id);
    let n = 0;
    const chips = sets.map((s) => { const w = s.warm && sets.length > 1;
      return `<i class="chip num${w ? ' w' : ''}"><em>${w ? 'W' : ++n}</em>${shortSet(s)}</i>`; }).join('');
    return `<div class="gdn-r"><span>${esc(e?.name || 'Exercise')}${prs.includes(id) ? '<span class="pr">PR</span>' : ''}<div class="chips">${chips}</div></span></div>`;
  }).join('');
}
function gymDoneHTML(d, ses) {
  const ids = [...new Set(ses.sets.map((s) => s.ex))], prs = ids.filter((id) => isPR(id, ses.sets, ses.date));
  const stat = (v, l) => `<div><b class="num">${v}</b><small>${l}</small></div>`;
  const rows = gymRows(ses, prs);
  return `<div class="card gdn"><button class="icon-btn gdn-share" data-gshare aria-label="Share this workout as an image">${SHARE}</button><div class="gdn-ic">${CHECK}</div><h3>Workout done</h3>
    <p>${esc(d.name)}</p>
    <div class="gdn-st" style="grid-template-columns:repeat(${prs.length ? 3 : 2},1fr)">${stat(nKg(volume(ses.sets)), 'kg lifted')}${stat(ids.length, ids.length === 1 ? 'exercise' : 'exercises')}${prs.length ? stat(prs.length, prs.length === 1 ? 'PR' : 'PRs') : ''}</div>
    <div class="gdn-l">${rows}</div></div>
    <button class="gmore" data-gshare>${SHARE}Share as image</button>
    <button class="gmore" data-gmore>${PLUS}Add more to this workout</button>
    <p class="hint" style="text-align:center">Finished by mistake? Add more reopens it. Logging a set does too.</p>`;
}

// ----- share card: a 1080 x 1920 portrait image of the finished workout
const COPY = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="8.5" y="8.5" width="12" height="12" rx="2.5"/><path d="M15.5 8.5V6a2.5 2.5 0 0 0-2.5-2.5H6A2.5 2.5 0 0 0 3.5 6v7A2.5 2.5 0 0 0 6 15.5h2.5"/></svg>';
const SHARE = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v12M7.5 7.5 12 3l4.5 4.5M5 12v7a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-7"/></svg>';
function gymShareCanvas(d, ses) {
  const W = 1080, H = 1920, X = 96, CW = W - 2 * X, FONT = '-apple-system, "SF Pro Display", system-ui, "Helvetica Neue", Arial, sans-serif';
  const c = document.createElement('canvas'); c.width = W; c.height = H;
  const g = c.getContext('2d');
  const col = { bg: '#0a0a0a', fg: '#ffffff', mid: 'rgba(255,255,255,.62)', dim: 'rgba(255,255,255,.38)', line: 'rgba(255,255,255,.12)', pill: '#1c1c1e', warm: 'rgba(255,255,255,.07)', good: '#30d158' };
  const font = (w, px) => { g.font = `${w} ${px}px ${FONT}`; };
  const text = (t, x, y, w, px, color, align = 'left', ls = 0) => { font(w, px); g.fillStyle = color; g.textAlign = align; g.letterSpacing = ls + 'px'; g.fillText(t, x, y); g.letterSpacing = '0px'; };
  const rrect = (x, y, w, h, r) => { g.beginPath(); g.roundRect(x, y, w, h, r); g.fill(); };
  const fit = (t, max, w, px) => { font(w, px); if (g.measureText(t).width <= max) return t; while (t.length > 1 && g.measureText(t + '…').width > max) t = t.slice(0, -1); return t + '…'; };
  g.fillStyle = col.bg; g.fillRect(0, 0, W, H);

  // header: dumbbell (same drawing as the Gym tab) + label, date on the right
  g.save(); g.translate(X - 4, 98); g.scale(2.5, 2.5); g.strokeStyle = col.fg; g.lineWidth = 1.9; g.lineCap = g.lineJoin = 'round';
  [[2.5, 9, 3, 6, 1], [5.5, 6.5, 3.5, 11, 1.2], [15, 6.5, 3.5, 11, 1.2], [18.5, 9, 3, 6, 1]].forEach(([x, y, w, h, r]) => { g.beginPath(); g.roundRect(x, y, w, h, r); g.stroke(); });
  g.beginPath(); g.moveTo(9, 12); g.lineTo(15, 12); g.stroke(); g.restore();
  text(CFG.name ? `${CFG.name.toUpperCase()}’S WORKOUT` : 'WORKOUT', X + 70, 138, 650, 26, col.mid, 'left', 4);
  // date in a pill on the right, lined up with the label
  const dt = dParse(ses.date).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
  font(600, 26); const dw = g.measureText(dt).width + 44;
  g.fillStyle = '#ffffff'; rrect(W - X - dw, 104, dw, 50, 25);
  g.textBaseline = 'middle'; text(dt, W - X - dw / 2, 129 + 1, 650, 26, '#000000', 'center'); g.textBaseline = 'alphabetic';  // centred in the pill

  // title
  const ids = [...new Set(ses.sets.map((s) => s.ex))], prs = ids.filter((id) => isPR(id, ses.sets, ses.date));
  let y = 300;
  text(dParse(ses.date).toLocaleDateString('en-GB', { weekday: 'long' }).toUpperCase(), X, y, 600, 28, col.dim, 'left', 3);
  y += 92; text(fit(d.name, CW, 750, 84), X, y, 750, 84, col.fg);
  // stats: weight lifted and exercises (PRs when there are any), no time
  y += 74;
  const stats = [[nKg(volume(ses.sets)), 'Kg lifted'], [String(ids.length), ids.length === 1 ? 'Exercise' : 'Exercises']];
  if (prs.length) stats.push([String(prs.length), prs.length === 1 ? 'PR' : 'PRs']);
  g.fillStyle = col.line; g.fillRect(X, y, CW, 2);
  stats.forEach(([v, l], i) => { const sx = X + i * (CW / 3); text(v, sx, y + 92, 700, 56, l.startsWith('PR') ? col.good : col.fg); text(l.toUpperCase(), sx, y + 138, 600, 22, col.dim, 'left', 2.5); });
  y += 186; g.fillStyle = col.line; g.fillRect(X, y, CW, 2);

  // exercises: name, then the sets as pills; shrink everything evenly if a long workout won't fit
  const top = y + 40, bottom = H - 190;
  const layout = (k, draw) => {
    let yy = top;
    for (const id of ids) {
      const e = G.exercises.find((x) => x.id === id), sets = ses.sets.filter((s) => s.ex === id), pr = prs.includes(id);
      const nameY = yy + 44 * k;
      if (draw) {
        text(fit(e?.name || 'Exercise', CW - (pr ? 120 : 0) * k, 650, Math.round(40 * k)), X, nameY, 650, Math.round(40 * k), col.fg);
        if (pr) { g.fillStyle = col.good; rrect(W - X - 84 * k, nameY - 32 * k, 84 * k, 40 * k, 12 * k); text('PR', W - X - 42 * k, nameY - 3 * k, 750, Math.round(24 * k), '#000', 'center', 1); }
      }
      let px = X, py = nameY + 26 * k; const ph = 62 * k;
      let n = 0;
      for (const st of sets) {
        const isW = st.warm && sets.length > 1, label = isW ? 'W' : String(++n), val = shortSet(st);
        font(650, Math.round(30 * k)); const vw = g.measureText(val).width; font(700, Math.round(22 * k)); const lw = g.measureText(label).width;
        const pw = 30 * k + lw + 14 * k + vw;
        if (px + pw > X + CW) { px = X; py += ph + 12 * k; }
        if (draw) {
          g.fillStyle = isW ? col.warm : col.pill; rrect(px, py, pw, ph, 18 * k);
          g.textBaseline = 'middle';
          text(label, px + 16 * k, py + ph / 2 + 1.5 * k, 700, Math.round(22 * k), col.dim);
          text(val, px + 16 * k + lw + 12 * k, py + ph / 2 + 1.5 * k, 650, Math.round(30 * k), isW ? col.mid : col.fg);
          g.textBaseline = 'alphabetic';
        }
        px += pw + 12 * k;
      }
      yy = py + ph + 46 * k;
      if (draw && id !== ids.at(-1)) { g.fillStyle = col.line; g.fillRect(X, yy - 23 * k, CW, 1.5); }
    }
    return yy - top;
  };
  const need = layout(1, false), k = Math.max(.55, Math.min(1.3, (bottom - top) / need));  // short workouts get a little bigger
  layout(k, true);

  // footer
  text('W  warm-up', X, H - 96, 500, 24, col.dim);
  return c;
}
async function gymShare(d, ses) {
  const c = gymShareCanvas(d, ses), url = c.toDataURL('image/png');
  const name = `${d.name.replace(/[^a-z0-9]+/gi, '-').toLowerCase()}-${ses.date}.png`;
  const blob = await new Promise((r) => c.toBlob(r, 'image/png'));
  const file = blob && typeof File === 'function' ? new File([blob], name, { type: 'image/png' }) : null;
  const canShare = !!(file && navigator.canShare && navigator.canShare({ files: [file] }));
  // a download link would throw the home-screen app out to a broken Safari page, so phones save by pressing and holding the image
  const touch = matchMedia('(pointer: coarse)').matches, box = $('#gshare');
  box.innerHTML = `<div class="gsh-in"><img src="${url}" alt="${esc(d.name)} workout summary">
    <p class="${touch && !canShare ? 'big' : ''}">${canShare ? 'Share it, or press and hold the image to save it to Photos.' : touch ? 'Press and hold the image, then tap <b>Save to Photos</b> or <b>Share</b>.' : 'Save the image, then share it anywhere.'}</p>
    <div class="gsh-b">${canShare ? `<button class="main" data-gsh-go>${SHARE}Share</button>` : touch ? '' : `<a class="main" href="${url}" download="${name}">Save image</a>`}<button data-gsh-x>${touch && !canShare ? 'Done' : 'Close'}</button></div></div>`;
  box.hidden = false;
  box.onclick = async (e) => {
    if (e.target === box || e.target.closest('[data-gsh-x]')) { box.hidden = true; box.innerHTML = ''; return; }
    if (e.target.closest('[data-gsh-go]')) { try { await navigator.share({ files: [file], title: `${d.name} workout` }); } catch {} }
  };
}

function gxCard(e, ses, keep, tagMuscle) {
  const today = ses ? ses.sets.filter((s) => s.ex === e.id) : [], last = lastFor(e.id), open = gymOpen.has(e.id);
  const prevBest = Math.max(0, ...G.sessions.filter((x) => x.date < logDate()).flatMap((x) => working(x.sets.filter((s) => s.ex === e.id))).map(pScore));
  const tw = today.filter((s) => !s.warm), top = heaviest(working(today));
  const pr = top && prevBest > 0 && Math.max(...tw.map(pScore)) > prevBest + 1e-9;
  const sub = today.length ? (tw.length ? `${plural(tw.length, 'set')} done` : 'Warm-up done')
    : last ? `Last logged ${agoTxt(last.date)}` : e.timed ? 'New. Log how long you hold it' : 'New. Starts with a warm-up';
  const right = top ? `<span class="gbest num">${shortSet(top)}${pr ? '<span class="pr">PR</span>' : ''}<em>${gDate ? 'best that day' : 'best today'}</em></span>` : '';
  let body = '';
  if (open) {
    // compare each set with the same set last time (warm-up with warm-up, set 2 with set 2)
    const pos = (list, s) => list.filter((x) => x.warm === s.warm).indexOf(s);
    const rows = today.map((s) => {
      const p = last?.sets.filter((x) => x.warm === s.warm)[pos(today, s)];
      let dl = '';
      if (p && !s.warm) {
        const dk = Math.round((s.kg - p.kg) * 100) / 100, dr = s.reps - p.reps, ds = (s.secs || 0) - (p.secs || 0);
        dl = ds ? `<span class="dl${ds > 0 ? ' up' : ''}">${ds > 0 ? '+' : '−'}${durTxt(Math.abs(ds))}</span>`
          : dk ? `<span class="dl${dk > 0 ? ' up' : ''}">${dk > 0 ? '+' : '−'}${Math.abs(dk)} kg</span>`
          : dr ? `<span class="dl${dr > 0 ? ' up' : ''}">${dr > 0 ? '+' : '−'}${plural(Math.abs(dr), 'rep')}</span>` : '<span class="dl">same as last</span>';
      }
      return `<div class="sset"><span class="badge${s.warm ? ' w' : ''}">${s.warm ? 'W' : pos(today, s) + 1}</span>
        <span><span class="v num">${setTxt(s)}</span>${s.warm ? '<span class="dl"> warm-up</span>' : ''} ${dl}</span>
        <button class="rm" data-rmset="${s.id}" aria-label="Remove set">${XMARK}</button></div>`;
    }).join('');
    const warmNext = !today.length && !gymSkip.has(e.id) && !e.timed;  // one warm-up (skippable), then working sets only
    // fields start empty; the numbers you'd most likely repeat are one tap away
    const pre = keep[e.id] || {};
    const lastSame = last?.sets.filter((s) => s.warm === warmNext)[warmNext ? 0 : tw.length];
    const refs = [];
    if (!warmNext && tw.length) refs.push([`Same as set ${tw.length}`, tw.at(-1)]);
    if (lastSame) refs.push([warmNext ? 'Last warm-up' : `Last time set ${tw.length + 1}`, lastSame]);
    const hintSet = refs[0]?.[1] || {};
    const label = warmNext ? 'Warm-up set' : `Set ${tw.length + 1}`;
    const note = e.note ? `<button class="gnote" data-note-box data-note-edit="${e.id}">${PEN}<span>${esc(e.note)}</span></button>` : '<span data-note-box hidden></span>';
    body = `<div class="gx-b">${note}${last ? `<div class="gprev"><span>Last time • ${shortDate(last.date)}</span><div class="chips">${
      last.sets.map((s) => `<i class="chip num${s.warm ? ' w' : ''}">${s.warm ? 'W ' : ''}${shortSet(s)}</i>`).join('')}</div></div>` : ''}
      ${rows}
      <div class="gentry" data-ex="${e.id}"${e.timed ? ' data-timed' : ''}>
        <div class="lab"><span data-lab>${label}</span>${today.length || e.timed ? '' : `<button data-skipw="${e.id}" class="${gymSkip.has(e.id) ? 'on' : ''}">${gymSkip.has(e.id) ? 'Add warm-up' : 'Skip warm-up'}</button>`}</div>
        <div class="flds">${e.timed ? `
          <div class="fld"><label>Minutes</label><div class="stp"><button data-step="-1" aria-label="One minute less">−</button><input class="num" name="min" inputmode="numeric" value="${esc(pre.min ?? '')}" placeholder="${hintSet.secs ? Math.floor(hintSet.secs / 60) : 0}"><button data-step="1" aria-label="One minute more">+</button></div></div>
          <div class="fld"><label>Seconds</label><div class="stp"><button data-step="-5" aria-label="Five seconds less">−</button><input class="num" name="sec" inputmode="numeric" value="${esc(pre.sec ?? '')}" placeholder="${hintSet.secs ? hintSet.secs % 60 : 0}"><button data-step="5" aria-label="Five seconds more">+</button></div></div>` : `
          <div class="fld"><label>Weight, kg</label><div class="stp"><button data-step="-2.5" aria-label="Less weight">−</button><input class="num" name="kg" inputmode="decimal" value="${esc(pre.kg ?? '')}" placeholder="BW" data-from="${hintSet.kg || 0}"><button data-step="2.5" aria-label="More weight">+</button></div></div>
          <div class="fld"><label>Reps</label><div class="stp"><button data-step="-1" aria-label="Fewer reps">−</button><input class="num" name="reps" inputmode="numeric" value="${esc(pre.reps ?? '')}" placeholder="${hintSet.reps ?? '0'}"><button data-step="1" aria-label="More reps">+</button></div></div>`}
        </div>
        ${refs.length ? `<div class="gsame">${refs.map(([t, x]) => `<button data-fill="${x.secs ? `${Math.floor(x.secs / 60)}|${x.secs % 60}` : `${x.kg}|${x.reps}`}">${t} <b class="num">${shortSet(x)}</b></button>`).join('')}</div>` : ''}
        <button class="gaddset" data-addset="${e.id}">${warmNext ? 'Log warm-up' : `Log set ${tw.length + 1}`}</button>
        ${tw.length && gymNext && gymNext.id !== e.id ? `<button class="gnext" data-gnext="${gymNext.id}">Next: ${esc(gymNext.name)}${ARROW}</button>` : ''}
        <div class="toast" data-msg></div>
        <div class="gx-f"><button data-ren="${e.id}">Rename</button><button data-note-edit="${e.id}">${e.note ? 'Edit note' : 'Add note'}</button><button data-exdel="${e.id}">Remove from this day</button></div>
      </div></div>`;
  }
  return `<div class="card gx${open ? ' open' : ''}${today.length ? ' done' : ''}" id="gx-${e.id}"><div class="gx-h" role="button" tabindex="0" data-gx="${e.id}">${today.length ? `<span class="gx-ok">${CHECK}</span>` : ''}<span class="nm"><b>${esc(e.name)}${tagMuscle && muscleOf(e.name) ? `<span class="mus">${MUSCLES[muscleOf(e.name)]}</span>` : ''}</b><small>${sub}</small></span>${right}${!today.length && !open ? '<span class="gx-go">Log</span>' : `<span class="chev">${CHEV}</span>`}</div>${body}</div>`;
}


// ----- history: every workout on a calendar, tap one to see it
const BACK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M15 6l-6 6 6 6"/></svg>';
const CAL = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M9 3v4M15 3v4"/></svg>';
const newestFirst = (a, b) => b.date.localeCompare(a.date) || b.started - a.started;
const sesName = (x) => dayOf(x.day)?.name || 'Workout';
function histRow(x) {
  const ids = new Set(x.sets.map((s) => s.ex)), kg = volume(x.sets), d = dParse(x.date);
  const prs = [...ids].filter((id) => isPR(id, x.sets, x.date)).length;
  return `<button class="hrow" data-hses="${x.id}"><span class="hd"><b class="num">${d.getDate()}</b><small>${d.toLocaleDateString('en-GB', { weekday: 'short' })}</small></span>
    <span class="hm"><b>${esc(sesName(x))}</b><small>${x.date === G.today ? 'Today • ' : ''}${plural(ids.size, 'exercise')}${kg ? ` • ${nKg(kg)} kg lifted` : ''}</small></span>
    ${prs ? `<span class="pr">${prs > 1 ? prs + ' PRs' : 'PR'}</span>` : ''}<span class="chev">${CHEV}</span></button>`;
}
function gymPastHTML(d) {
  const xs = daySessions(d.id).reverse();
  if (!xs.length) return '';
  return `<div class="label">Past ${esc(d.name)} workouts<button data-hses="${xs[0].id}">Open latest</button></div><div class="card hlist">${xs.slice(0, 12).map(histRow).join('')}</div>`;
}

function openHist(o = {}) {
  hSel = o.ses || null; hDirect = !!o.ses; hPick = o.date || null;
  hMonth = (o.date || G.sessions.find((x) => x.id === o.ses)?.date || G.today).slice(0, 7);
  raise($('#gymh')); $('#gymh').hidden = false; document.body.style.overflow = 'hidden';
  renderHist(true);
}
function closeHist() {
  $('#gymh').hidden = true; hSel = null; hPick = null;
  if ($('#gymp').hidden) document.body.style.overflow = ''; else renderGymDay(drafts());
}
function dayAbbr(name) { return name.split(/[^A-Za-z]+/).filter((w) => w && !/^and$/i.test(w)).map((w) => w[0].toUpperCase()).join(''); }
function renderHist(top) {
  const body = $('#gymh-body'), back = $('#gymh [data-hback]'), all = [...G.sessions].sort(newestFirst);
  const x = hSel && all.find((s) => s.id === hSel);
  if (hSel && !x) { hSel = null; hDirect = false; }
  if (x) {
    // one workout, the same layout as the finish summary
    const i = all.indexOf(x), older = all[i + 1], newer = all[i - 1];
    const ids = [...new Set(x.sets.map((s) => s.ex))], prs = ids.filter((id) => isPR(id, x.sets, x.date));
    const stat = (v, l) => `<div><b class="num">${v}</b><small>${l}</small></div>`;
    const nav = (y, dir) => `<button data-hnav="${y?.id || ''}" ${y ? '' : 'disabled'}><small>${dir === -1 ? 'Older' : 'Newer'}</small><b>${y ? `${esc(sesName(y))}, ${shortDate(y.date)}` : ''}</b></button>`;
    back.className = hDirect ? 'done' : 'done back'; back.innerHTML = hDirect ? 'Done' : `${BACK}History`;
    $('#gymh-title').textContent = x.date === G.today ? 'Today' : dParse(x.date).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short' });
    body.innerHTML = `<div class="card gdn hses"><button class="icon-btn gdn-share" data-hshare aria-label="Share this workout as an image">${SHARE}</button>
      <h3>${esc(sesName(x))}</h3><p>${longDate(x.date)} • ${agoTxt(x.date)}</p>
      <div class="gdn-st" style="grid-template-columns:repeat(${prs.length ? 3 : 2},1fr)">${stat(nKg(volume(x.sets)), 'kg lifted')}${stat(ids.length, ids.length === 1 ? 'exercise' : 'exercises')}${prs.length ? stat(prs.length, prs.length === 1 ? 'PR' : 'PRs') : ''}</div>
      <div class="gdn-l">${gymRows(x, prs)}</div></div>
      <button class="gmore" data-hedit>${PEN}${x.date === G.today ? 'Open in today’s log' : 'Edit this workout'}</button>
      <div class="hnav">${nav(older, -1)}${nav(newer, 1)}</div>
      ${hDirect ? '<button class="gmore" data-hall>' + CAL + 'See all workouts</button>' : ''}`;
  } else {
    back.className = 'done'; back.textContent = 'Done'; $('#gymh-title').textContent = 'History';
    const [yy, mm] = hMonth.split('-').map(Number), first = new Date(yy, mm - 1, 1), n = new Date(yy, mm, 0).getDate();
    const minMonth = isoDay(new Date(dParse(G.today).getFullYear() - 2, dParse(G.today).getMonth() + 1, 1)).slice(0, 7);
    const inMonth = all.filter((s) => s.date.startsWith(hMonth)), kg = inMonth.reduce((a, s) => a + volume(s.sets), 0);
    const cells = [...Array((first.getDay() + 6) % 7)].map(() => '<i></i>').join('') + [...Array(n)].map((_, k) => {
      const iso = `${hMonth}-${String(k + 1).padStart(2, '0')}`, xs = inMonth.filter((s) => s.date === iso);
      const full = xs.map((s) => sesName(s)).join(', ');
      const lab = xs.map((s) => dayAbbr(sesName(s))).join('+');  // Chest and Triceps -> CT, Legs -> L
      return `<button class="hc${xs.length ? ' on' : ''}${iso === G.today ? ' now' : ''}${iso === hPick ? ' sel' : ''}" data-hdate="${iso}" ${iso > G.today ? 'disabled' : ''}
        aria-label="${esc(longDate(iso) + (full ? ': ' + full : ''))}"><b class="num">${k + 1}</b><small>${esc(lab)}</small></button>`;
    }).join('');
    const monthName = first.toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });
    let pick = '';
    if (hPick && hPick.startsWith(hMonth)) {
      const xs = inMonth.filter((s) => s.date === hPick), days = G.days.filter((d) => !d.hidden && !xs.some((s) => s.day === d.id));
      const chips = days.length ? `<div class="chips">${days.map((d) => `<button data-hlog="${d.id}">${PLUS}${esc(d.name)}</button>`).join('')}</div>` : '';
      pick = xs.length
        ? `<div class="card hpick"><b>${longDate(hPick)}</b><small>${plural(xs.length, 'workout')} that day.${chips ? ' Add another:' : ''}</small>${chips}<div class="card hlist" style="margin-top:${chips ? 14 : 0}px">${xs.map(histRow).join('')}</div></div>`
        : `<div class="card hpick"><b>${longDate(hPick)}</b><small>${hPick === G.today ? 'Nothing logged yet today.' : 'Nothing logged. Trained but forgot to log it? Pick the day and add your sets.'}</small>${chips}</div>`;
    }
    body.innerHTML = `<div class="card hcal"><div class="hmh"><button class="icon-btn" data-hm="-1" aria-label="Previous month" ${hMonth <= minMonth ? 'disabled' : ''}>${BACK}</button>
      <div><b>${monthName}</b><small>${inMonth.length ? `${plural(inMonth.length, 'workout')}${kg ? ` • ${nKg(kg)} kg` : ''}` : 'No workouts'}</small></div>
      <button class="icon-btn" data-hm="1" aria-label="Next month" ${hMonth >= G.today.slice(0, 7) ? 'disabled' : ''}>${CHEV}</button></div>
      <div class="hgrid">${WD.map((c) => `<span>${c}</span>`).join('')}${cells}</div></div>
      ${pick}
      ${inMonth.length ? `<div class="label">${first.toLocaleDateString('en-GB', { month: 'long' })}</div><div class="card hlist">${inMonth.map(histRow).join('')}</div>`
        : `<p class="hint" style="text-align:center">${all.length ? 'No workouts this month.' : 'Your workouts will show up here.'} Tap any past day to add one you forgot to log.</p>`}`;
  }
  if (top !== false) $('#gymh .panel-body').scrollTop = 0;
}
$('#gymh').addEventListener('click', (e) => {
  const t = e.target.closest('button'); if (!t) return;
  const x = hSel && G.sessions.find((s) => s.id === hSel);
  if (t.dataset.hback !== undefined) {
    if (hSel && !hDirect) { hMonth = x ? x.date.slice(0, 7) : hMonth; hSel = null; return renderHist(); }
    return closeHist();
  }
  if (t.dataset.hm) {
    const [y, m] = hMonth.split('-').map(Number);
    hMonth = isoDay(new Date(y, m - 1 + +t.dataset.hm, 1)).slice(0, 7); hPick = null; return renderHist(false);
  }
  if (t.dataset.hdate) {
    const xs = G.sessions.filter((s) => s.date === t.dataset.hdate);
    if (xs.length === 1) { hSel = xs[0].id; hDirect = false; hPick = null; return renderHist(); }
    hPick = hPick === t.dataset.hdate ? null : t.dataset.hdate; return renderHist(false);
  }
  if (t.dataset.hses) { hSel = t.dataset.hses; hDirect = false; return renderHist(); }
  if (t.dataset.hnav) { hSel = t.dataset.hnav; return renderHist(); }
  if (t.dataset.hall !== undefined) { hMonth = x ? x.date.slice(0, 7) : hMonth; hSel = null; hDirect = false; return renderHist(); }
  if (t.dataset.hlog) { const date = hPick; hSel = null; return openGymDay(t.dataset.hlog, date); }
  if (t.dataset.hedit !== undefined && x) return openGymDay(x.day, x.date);
  if (t.dataset.hshare !== undefined && x) return gymShare(dayOf(x.day) || { name: sesName(x) }, x);
});

function gymProgressHTML(d) {
  const W = Math.max(260, Math.min(720, innerWidth) - 32 - 36);
  const ctl = `<div class="gctl"><div class="seg">${[['top', 'Heaviest'], ['1rm', 'Est. max'], ['vol', 'Volume']].map(([k, n]) => `<button data-metric="${k}" class="${gymMetric === k ? 'on' : ''}">${n}</button>`).join('')}</div>
    <div class="seg">${[[30, '1M'], [90, '3M'], [365, '1Y'], [0, 'All']].map(([k, n]) => `<button data-range="${k}" class="${gymRange === k ? 'on' : ''}">${n}</button>`).join('')}</div></div>`;
  const what = { top: 'Heaviest working set each session', '1rm': 'Estimated one-rep max from your best set', vol: 'Total kg × reps across working sets' }[gymMetric];
  const cards = dayExercises(d.id).map((e) => {
    const pts = G.sessions.filter((x) => (!gymRange || daysAgo(x.date) <= gymRange)).sort((a, b) => a.date.localeCompare(b.date)).map((x) => {
      const w = working(x.sets.filter((s) => s.ex === e.id)); if (!w.length) return null;
      const bw = w.every((s) => !s.kg), best = heaviest(w), tm = w.some((s) => s.secs);
      const v = tm ? (gymMetric === 'vol' ? w.reduce((a, s) => a + (s.secs || 0), 0) : Math.max(...w.map((s) => s.secs || 0)))
        : bw ? (gymMetric === 'vol' ? w.reduce((a, s) => a + s.reps, 0) : best.reps)
        : gymMetric === 'vol' ? volume(w) : gymMetric === '1rm' ? Math.max(...w.map(e1rm)) : best.kg;
      return { date: x.date, v, best, bw, tm };
    }).filter(Boolean);
    return pts.length ? { e, pts } : null;
  }).filter(Boolean).sort((a, b) => b.pts.at(-1).date.localeCompare(a.pts.at(-1).date));
  if (!cards.length) return ctl + `<div class="card gempty">No working sets ${gymRange ? 'in this period' : 'yet'}.<br>Log a session and your progress shows up here.</div>`;
  return ctl + `<p class="hint" style="margin:0 4px 12px">${what}.</p>` + cards.map(({ e, pts }, i) => {
    const bw = pts.at(-1).bw, tm = pts.at(-1).tm, unit = tm ? '' : bw ? 'reps' : 'kg', fmt = (v) => tm ? durTxt(Math.round(v)) : bw ? Math.round(v) : gymMetric === 'top' ? kgTxt(v) : nKg(v);
    const ch = pts.at(-1).v - pts[0].v, best = pts.reduce((a, p) => p.v > a.v ? p : a);
    return `<div class="card gp" style="animation-delay:${i * 40}ms"><div class="gp-h"><div><b>${esc(e.name)}</b>
      <small>Best ${shortSet(best.best)} on ${shortDate(best.date)} • ${plural(pts.length, 'session')}</small></div>
      <div class="big num"><span>${fmt(pts.at(-1).v)}<small> ${unit}</small></span><small class="ch${ch > 0 ? ' up' : ''}">${pts.length > 1 ? (ch > 0 ? '+' : ch < 0 ? '−' : '±') + fmt(Math.abs(ch)) + ' ' + unit : 'first session'}</small></div></div>
      ${gChart(pts, W, i, fmt)}${pts.length === 1 ? '<p class="one">Log this again next time to see the trend.</p>' : ''}</div>`;
  }).join('');
}

function gChart(pts, W, id, fmt) {
  const H = 150, L = 4, R = 4, T = 16, B = 24, vs = pts.map((p) => p.v);
  let lo = Math.min(...vs), hi = Math.max(...vs);
  if (hi === lo) { lo -= Math.max(1, lo * .1); hi += Math.max(1, hi * .1); } else { const pad = (hi - lo) * .18; lo -= pad; hi += pad; }
  const t0 = +dParse(pts[0].date), span = +dParse(pts.at(-1).date) - t0;
  const xy = pts.map((p, i) => [pts.length === 1 ? W / 2 : L + (span ? (+dParse(p.date) - t0) / span : i / (pts.length - 1)) * (W - L - R),
    T + (1 - (p.v - lo) / (hi - lo)) * (H - T - B)]);
  const line = xy.map(([x, y], i) => `${i ? 'L' : 'M'}${x.toFixed(1)},${y.toFixed(1)}`).join('');
  const base = H - B, top = Math.max(...vs), ty = T + (1 - (top - lo) / (hi - lo)) * (H - T - B);
  const [lx, ly] = xy.at(-1);
  return `<svg class="gchart" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Progress over time">
    <defs><linearGradient id="gg${id}" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".18"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs>
    <path d="M0,${base}H${W}" stroke="var(--line-2)"/>
    <path d="M0,${ty.toFixed(1)}H${W}" stroke="var(--line-2)" stroke-dasharray="3 4"/>
    <text class="pb" x="0" y="${(ty - 5).toFixed(1)}">Best ${fmt(top)}</text>
    ${pts.length > 1 ? `<path d="${line}L${lx.toFixed(1)},${base}L${xy[0][0].toFixed(1)},${base}Z" fill="url(#gg${id})"/>
    <path d="${line}" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>` : ''}
    ${pts.length <= 30 ? xy.slice(0, -1).map(([x, y]) => `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="3" fill="var(--card)" stroke="currentColor" stroke-width="1.6"/>`).join('') : ''}
    <circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="8" fill="currentColor" opacity=".12"/><circle cx="${lx.toFixed(1)}" cy="${ly.toFixed(1)}" r="4.5" fill="currentColor"/>
    <text class="ax" x="0" y="${H - 6}">${shortDate(pts[0].date)}</text>
    ${pts.length > 1 ? `<text class="ax" x="${W}" y="${H - 6}" text-anchor="end">${pts.at(-1).date === G.today ? 'Today' : shortDate(pts.at(-1).date)}</text>` : ''}
  </svg>`;
}

// suggestions while typing a new exercise: this day's first, then ones from other days, then "add new"
function gymSuggest() {
  const q = $('#gx-new').value.trim(), box = $('#gx-sug');
  if (!q) { box.innerHTML = ''; return; }
  const here = dayExercises(gymDay), seen = new Set(here.map((e) => gKey(e.name)));
  const scored = G.exercises.filter((e) => !e.hidden && (e.day === gymDay || !seen.has(gKey(e.name))))
    .map((e) => ({ e, s: gSim(q, e.name) + (e.day === gymDay ? .05 : 0) })).filter((x) => x.s >= .55).sort((a, b) => b.s - a.s);
  const uniq = []; const k = new Set();
  for (const x of scored) { const kk = gKey(x.e.name) + (x.e.day === gymDay ? '' : '*'); if (!k.has(kk) && !(x.e.day !== gymDay && seen.has(gKey(x.e.name)))) { k.add(kk); uniq.push(x); } }
  const exact = here.some((e) => gKey(e.name) === gKey(q));
  const mus = dayMuscles(dayOf(gymDay).name), taken = new Set([...here, ...uniq.map((x) => x.e)].map((e) => gKey(e.name)));
  const libHits = (mus.length ? mus : Object.keys(LIB)).flatMap((m) => LIB[m].map((n) => ({ n, m, s: gSim(q, n) })))
    .filter((x) => x.s >= .55 && !taken.has(gKey(x.n)) && ![...here, ...uniq.map((y) => y.e)].some((e) => gSim(x.n, e.name) >= .85))
    .sort((a, b) => b.s - a.s).slice(0, Math.max(0, 5 - uniq.length));
  box.innerHTML = uniq.slice(0, 5).map(({ e }) => {
    if (e.day === gymDay) { const l = lastFor(e.id); return `<button class="sg" data-sg-open="${e.id}"><span><b>${esc(e.name)}</b><small>Already in ${esc(dayOf(gymDay).name)}${l ? ' • last ' + shortSet(heaviest(working(l.sets)) || heaviest(l.sets)) : ''}</small></span><em>Use</em></button>`; }
    return `<button class="sg" data-sg-copy="${esc(e.name)}"><span><b>${esc(e.name)}</b><small>From ${esc(dayOf(e.day)?.name || 'another day')}</small></span><em>Add</em></button>`;
  }).join('') + libHits.map((x) => `<button class="sg" data-sg-copy="${esc(x.n)}"><span><b>${esc(x.n)}</b><small>Common ${MUSCLES[x.m].toLowerCase()} exercise</small></span><em>Add</em></button>`).join('')
    + (exact || libHits.some((x) => gKey(x.n) === gKey(q)) ? '' : `<button class="sg new" data-sg-new>${PLUS}<span><b>Add “${esc(q)}”</b><small>New exercise for ${esc(dayOf(gymDay).name)}</small></span></button>`);
}
async function gymAddExercise(name) {
  const r = await post('/api/bot/gym/exercise', { day: gymDay, name }).catch(() => null);
  if (!r?.ok) return;
  gymOpenEx(r.exercise.id, true);
}
async function gymOpenEx(id, reload) {
  gymOpen.clear(); gymOpen.add(id);
  const keep = drafts();
  if (reload) G = await getJSON('/api/bot/gym').catch(() => G);
  renderGymDay(keep);
  const c = $('#gx-' + id); if (c) c.scrollIntoView({ behavior: 'smooth', block: 'start' });
}

$('#gym-panel').addEventListener('input', (e) => { if (e.target.id === 'gx-new') gymSuggest(); });
$('#gym-panel').addEventListener('keydown', (e) => {
  if (e.target.id === 'gx-new' && e.key === 'Enter') {
    e.preventDefault();
    const q = e.target.value.trim(); if (!q) return;
    const same = dayExercises(gymDay).find((x) => gKey(x.name) === gKey(q));
    same ? gymOpenEx(same.id) : gymAddExercise(q);
  }
  if (e.target.classList.contains('gx-h') && (e.key === 'Enter' || e.key === ' ')) { e.preventDefault(); e.target.click(); }
  if (e.target.closest('.gentry') && e.key === 'Enter') { e.preventDefault(); e.target.closest('.gentry').querySelector('[data-addset]').click(); }
  if ((e.target.dataset.renEx !== undefined || e.target.dataset.noteEx !== undefined) && e.key === 'Enter') e.target.blur();
});
$('#gym-panel').addEventListener('focusout', async (e) => {
  if (e.target.dataset?.noteEx) {
    const id = e.target.dataset.noteEx;
    await post('/api/bot/gym/exercise/edit', { id, note: e.target.value.trim() }).catch(() => {});
    G = await getJSON('/api/bot/gym').catch(() => G); return renderGymDay(drafts());
  }
  const i = e.target; if (!i.dataset || i.dataset.renEx === undefined) return;
  if (i.value.trim()) await post('/api/bot/gym/exercise/edit', { id: i.dataset.renEx, name: i.value }).catch(() => {});
  G = await getJSON('/api/bot/gym').catch(() => G); renderGymDay(drafts());
});
$('#gym-panel').addEventListener('click', async (e) => {
  const t = e.target.closest('button, .gx-h'); if (!t) return;
  if (t.dataset.hses) return openHist({ ses: t.dataset.hses });
  if (t.dataset.gnext) return gymOpenEx(t.dataset.gnext);
  if (t.dataset.gt) { gymTab = t.dataset.gt; return renderGymDay(); }
  if (t.dataset.metric) { gymMetric = t.dataset.metric; return renderGymDay(); }
  if (t.dataset.range) { gymRange = +t.dataset.range; return renderGymDay(); }
  if (t.dataset.gx) {
    if (e.target.closest('input')) return;
    const id = t.dataset.gx, keep = drafts();
    const was = gymOpen.has(id); gymOpen.clear(); if (!was) gymOpen.add(id);
    renderGymDay(keep);
    if (!was) { const c = $('#gx-' + id); if (c && c.getBoundingClientRect().top < 70) c.scrollIntoView({ block: 'start', behavior: 'smooth' }); }
    return;
  }
  if (t.dataset.sgOpen) { $('#gx-new').value = ''; return gymOpenEx(t.dataset.sgOpen); }
  if (t.dataset.sgCopy) return gymAddExercise(t.dataset.sgCopy);
  if (t.dataset.sgNew !== undefined) return gymAddExercise($('#gx-new').value.trim());
  if (t.dataset.step) {
    // an empty box steps from the hint it shows
    const i = t.closest('.stp').querySelector('input'), st = +t.dataset.step;
    const base = i.value === '' ? parseFloat(i.dataset.from ?? i.placeholder) || 0 : parseFloat(i.value.replace(',', '.')) || 0;
    i.value = Math.max(0, Math.round((base + st) * 100) / 100);
    return;
  }
  if (t.dataset.gfinish !== undefined || t.dataset.gmore !== undefined) {
    t.disabled = true;
    const r = await post('/api/bot/gym/finish', { day: gymDay, undo: t.dataset.gmore !== undefined }).catch(() => null);
    if (!r?.ok) { t.disabled = false; return; }
    G = await getJSON('/api/bot/gym').catch(() => G);
    gymOpen.clear(); renderGymDay.last = null; renderGymDay(); renderGymHome();
    $('#gymp .panel-body').scrollTop = 0;
    return;
  }
  if (t.dataset.gshare !== undefined) { const ses = todaySession(gymDay); if (ses) gymShare(dayOf(gymDay), ses); return; }
  if (t.dataset.fill) {
    const [a, b] = t.dataset.fill.split('|'), [i1, i2] = t.closest('.gentry').querySelectorAll('.flds input');
    i1.value = +a; i2.value = b;
    return;
  }
  if (t.dataset.skipw) {
    const id = t.dataset.skipw; gymSkip.has(id) ? gymSkip.delete(id) : gymSkip.add(id);
    return renderGymDay(drafts());
  }
  if (t.dataset.noteEdit) {
    const e = G.exercises.find((x) => x.id === t.dataset.noteEdit), box = $('#gx-' + e.id + ' [data-note-box]');
    box.outerHTML = `<input class="gnote-in" data-note-ex="${e.id}" value="${esc(e.note || '')}" placeholder="e.g. Next week: same weight" maxlength="120" enterkeyhint="done">`;
    $(`[data-note-ex="${e.id}"]`).focus(); return;
  }
  if (t.dataset.warm) {
    const id = t.dataset.warm, on = !gymWarm.has(id);
    on ? gymWarm.add(id) : gymWarm.delete(id);
    const g = t.closest('.gentry'), n = g.closest('.gx').querySelectorAll('.sset .badge:not(.w)').length + 1;
    t.classList.toggle('on', on);
    g.querySelector('[data-lab]').textContent = on ? 'Warm-up set' : `Set ${n}`;
    g.querySelector('[data-addset]').textContent = on ? 'Log warm-up' : `Log set ${n}`;
    return;
  }
  if (t.dataset.addset && t.closest('.gentry').dataset.timed !== undefined) {
    const g = t.closest('.gentry'), n = (f) => parseInt(g.querySelector(`[name=${f}]`).value, 10) || 0, secs = n('min') * 60 + n('sec');
    if (secs < 1) return flash(g.querySelector('[data-msg]'), 'How long did you hold it?', { bad: true });
    t.disabled = true;
    const r = await post('/api/bot/gym/set', { ex: t.dataset.addset, secs, date: gDate || undefined }).catch(() => null);
    if (!r?.ok) { t.disabled = false; return flash(g.querySelector('[data-msg]'), r?.msg || 'Couldn’t save that. Try again.', { bad: true }); }
    const keep = drafts(); delete keep[t.dataset.addset];
    G = await getJSON('/api/bot/gym').catch(() => G);
    renderGymDay(keep);
    const msg = $('#gx-' + t.dataset.addset + ' [data-msg]'); if (msg) flash(msg, `${durTxt(secs)} logged.`);
    return;
  }
  if (t.dataset.addset) {
    const g = t.closest('.gentry'), kg = parseFloat(g.querySelector('[name=kg]').value.replace(',', '.')) || 0, reps = parseInt(g.querySelector('[name=reps]').value, 10);
    if (!reps || reps < 1) return flash(g.querySelector('[data-msg]'), 'How many reps? Leave the weight empty for bodyweight.', { bad: true });
    t.disabled = true;
    const r = await post('/api/bot/gym/set', { ex: t.dataset.addset, kg, reps, warm: !gymSkip.has(t.dataset.addset), date: gDate || undefined }).catch(() => null);
    if (!r?.ok) { t.disabled = false; return flash(g.querySelector('[data-msg]'), r?.msg || 'Couldn’t save that set. Try again.', { bad: true }); }
    gymSkip.delete(t.dataset.addset);
    const keep = drafts(); delete keep[t.dataset.addset];
    G = await getJSON('/api/bot/gym').catch(() => G);
    renderGymDay(keep);
    if (!$('#gx-' + t.dataset.addset)?.closest('.gx')) return;
    const msg = $('#gx-' + t.dataset.addset + ' [data-msg]'); if (msg) flash(msg, r.set.warm ? 'Warm-up logged. Now your working sets.' : 'Set logged.');
    return;
  }
  if (t.dataset.rmset) {
    const st = G.sessions.flatMap((x) => x.sets).find((x) => x.id === t.dataset.rmset);
    if (!await confirmSheet({ title: `Remove ${st ? setTxt(st) : 'this set'}?`, ok: 'Remove set', danger: true })) return;
    await post('/api/bot/gym/set/delete', { id: t.dataset.rmset }).catch(() => {});
    const keep = drafts(); G = await getJSON('/api/bot/gym').catch(() => G); return renderGymDay(keep);
  }
  if (t.dataset.ren) {
    const b = $('#gx-' + t.dataset.ren + ' .gx-h b'), name = b.textContent;
    b.outerHTML = `<input data-ren-ex="${t.dataset.ren}" value="${esc(name)}" maxlength="60" aria-label="Exercise name">`;
    const i = $(`[data-ren-ex="${t.dataset.ren}"]`); i.focus(); i.select(); return;
  }
  if (t.dataset.exdel) {
    const ex = G.exercises.find((x) => x.id === t.dataset.exdel);
    if (!await confirmSheet({ title: `Remove ${ex.name} from ${dayOf(ex.day)?.name || 'this day'}?`, text: 'Its sets stay in your history and progress.', ok: 'Remove exercise', danger: true })) return;
    await post('/api/bot/gym/exercise/edit', { id: t.dataset.exdel, remove: true }).catch(() => {});
    gymOpen.delete(t.dataset.exdel); G = await getJSON('/api/bot/gym').catch(() => G); return renderGymDay(drafts());
  }
});

function renderToday() {
  const a = X.agenda;
  if (!a) { $('#today').innerHTML = '<div class="empty">Calendar unavailable right now.</div>'; return; }
  const isStay = (e) => e.when === 'All day' && new RegExp('^' + CFG.name.replace(/[.*+?^${}()|[\]\\]/g, '\\$&') + ' in ', 'i').test(e.title);
  const list = (items) => items.map((e) => `<div class="ev"><time class="num">${esc(e.when)}</time>
      <span>${esc(e.title)}${e.loc ? `<em>${esc(e.loc)}</em>` : ''}</span></div>`).join('');
  const today = a.today.filter((e) => !isStay(e)), tom = a.tomorrow.filter((e) => !isStay(e)), rem = X.reminders_today || [];
  $('#today').innerHTML = (list(today) || '<div class="empty">Nothing planned today.</div>')
    + (rem.length ? '<div class="sub">Reminders today</div>' + rem.map((r) => `<div class="ev"><time class="num">${esc(r.time)}</time><span>${esc(r.text)}</span></div>`).join('') : '')
    + `<div class="sub">Tomorrow • ${esc(a.tomorrow_label)}</div>` + (list(tom) || '<div class="empty">Nothing planned.</div>')
    + (X.flights || []).map((f) => `<div class="flight">${SVG(SEC_ICON.travel)}<b>${esc(f.title)}</b>, ${esc(f.when)}. Leave home by <b>${esc(f.leave_by)}</b>.</div>`).join('');
}
