// ---------- Money: one month at a time, in your-name tab next to Health. Names and amounts stay hidden until you show them ----------
var MND = null;
const MN = { show: false, step: null, hideAt: null, kind: null, item: null };
const MN_COMMON = ['USD', 'EUR', 'GBP', 'INR', 'JPY', 'CAD', 'AUD', 'SGD', 'AED', 'CHF', 'CNY', 'HKD', 'NZD', 'SEK', 'NOK', 'DKK', 'PLN', 'BRL', 'MXN', 'ZAR', 'KRW', 'THB', 'IDR', 'MYR', 'PHP', 'SAR', 'TRY', 'ILS', 'NGN', 'KES'];
const MN_REGION = { US: 'USD', IN: 'INR', GB: 'GBP', JP: 'JPY', CA: 'CAD', AU: 'AUD', SG: 'SGD', AE: 'AED', CH: 'CHF', CN: 'CNY', HK: 'HKD', NZ: 'NZD', SE: 'SEK', NO: 'NOK', DK: 'DKK',
  PL: 'PLN', BR: 'BRL', MX: 'MXN', ZA: 'ZAR', KR: 'KRW', TH: 'THB', ID: 'IDR', MY: 'MYR', PH: 'PHP', SA: 'SAR', TR: 'TRY', IL: 'ILS', NG: 'NGN', KE: 'KES',
  DE: 'EUR', FR: 'EUR', ES: 'EUR', IT: 'EUR', NL: 'EUR', IE: 'EUR', PT: 'EUR', AT: 'EUR', BE: 'EUR', FI: 'EUR', GR: 'EUR', LU: 'EUR' };
const mnName = (c) => { try { return new Intl.DisplayNames(undefined, { type: 'currency' }).of(c); } catch { return c; } };
const mnSym = (c) => { try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: c }).formatToParts(0).find((p) => p.type === 'currency').value; } catch { return c; } };
const mnAll = () => { try { return Intl.supportedValuesOf('currency'); } catch { return MN_COMMON; } };
const mnGuess = () => { try { const r = new Intl.Locale(navigator.language).maximize().region; return MN_REGION[r] || 'USD'; } catch { return 'USD'; } };
const mnFmt = (minor) => minor == null ? `${mnSym(MND.currency)}****` : new Intl.NumberFormat(undefined, { style: 'currency', currency: MND.currency }).format(minor / 100);
const mnNth = (n) => n + (n % 10 === 1 && n !== 11 ? 'st' : n % 10 === 2 && n !== 12 ? 'nd' : n % 10 === 3 && n !== 13 ? 'rd' : 'th');
const MN_EYE = (open) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${open ? '<path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/>' : '<path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3 3.9M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/>'}</svg>`;
let mnPin = ''; try { mnPin = sessionStorage.getItem('spin') || ''; } catch (e) {}

async function mnFetch(path, body, show = MN.show) {
  const q = show ? (path.includes('?') ? '&' : '?') + 'show=1' : '';
  const r = await fetch('/api/bot' + path + q, { method: body ? 'POST' : 'GET', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-Settings-Pin': mnPin }, body: body ? JSON.stringify(body) : undefined });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw Object.assign(new Error('failed'), { code: r.status, msg: j.msg || j.error });
  return j;
}

// ---------- The Health | Money switch at the top of your-name tab ----------
(() => {
  const v = $('#v-sg'); if (!v || $('#mn-seg')) return;
  v.querySelector('.top').insertAdjacentHTML('afterend', `<div class="seg mn-seg" id="mn-seg" role="tablist"><button role="tab" data-mnseg="health">Health</button><button role="tab" data-mnseg="money">Money</button></div>`);
  $('#sg-body').insertAdjacentHTML('afterend', '<div id="money-body" hidden></div>');
  let side = 'health'; try { side = sessionStorage.getItem('mnside') || 'health'; } catch (e) {}
  mnSide(side, false);
  $('#mn-seg').addEventListener('click', (e) => { const b = e.target.closest('[data-mnseg]'); if (b) mnSide(b.dataset.mnseg, true); });
  new MutationObserver(() => { if (v.hidden) mnHide(); else if (!$('#money-body').hidden) loadMoney(); }).observe(v, { attributes: true, attributeFilter: ['hidden'] });
  document.addEventListener('visibilitychange', () => { if (document.hidden) mnHide(); });
})();
function mnSide(side, load) {
  const money = side === 'money';
  $('#mn-seg').querySelectorAll('button').forEach((b) => { b.classList.toggle('on', b.dataset.mnseg === side); b.setAttribute('aria-selected', b.dataset.mnseg === side); });
  $('#sg-body').hidden = money; $('#money-body').hidden = !money;
  const top = $('#v-sg .top'); top.querySelector('h1').textContent = money ? 'Money' : 'Health'; top.querySelector('p').textContent = money ? 'This month, and what you can spend today' : 'Medicines and appointments';
  try { sessionStorage.setItem('mnside', side); } catch (e) {}
  if (money && load) loadMoney();
}
function mnHide() { if (MN.show) { MN.show = false; clearTimeout(MN.hideAt); if (MND) loadMoney(); } }  // leaving the tab or the page hides the amounts again

async function loadMoney() {
  const box = $('#money-body');
  if (!MND) box.innerHTML = '<div class="skel"></div><div class="skel"></div>';
  try { MND = await mnFetch('/money', null, MN.show || !!MN.step); }
  catch (err) { if (err.code === 403 && MN.show) { MN.show = false; return mnAskPin(); } box.innerHTML = '<div class="err">Money can’t be loaded right now. Try again in a minute.</div>'; return; }
  if (!MND.setup && !MN.step) MN.step = 'currency';
  renderMoney();
}

// ---------- First time: currency, income, bills ----------
function mnSetupHTML() {
  const D = MND, step = MN.step, n = { currency: 1, income: 2, bills: 3, done: 4 }[step];
  const bar = `<div class="mn-steps">${[1, 2, 3].map((i) => `<i class="${i <= n ? 'on' : ''}"></i>`).join('')}</div>`;
  if (step === 'currency') {
    const q = (MN.q || '').toLowerCase(), guess = D.currency || mnGuess();
    const list = (q ? mnAll() : MN_COMMON).filter((c) => !q || c.toLowerCase().includes(q) || mnName(c).toLowerCase().includes(q)).slice(0, 40);
    const row = (c) => `<button class="srow mn-cur${c === guess && !q ? ' on' : ''}" data-mncur="${c}"><span><b>${esc(mnName(c))}</b><small>${c} ${esc(mnSym(c))}</small></span>${c === guess && !q ? '<i class="mn-chk">✓</i>' : ''}</button>`;
    return `<div class="label">Set up your budget<span class="lr">Step 1 of 3</span></div>${bar}
      <section class="card mn-intro"><b>Which currency do you use?</b><small>Everything here is in one currency. You can change it later.</small></section>
      <label class="sfield"><span>Search</span><input id="mn-q" value="${esc(MN.q || '')}" placeholder="Type a currency or country" autocomplete="off"></label>
      ${q ? '' : `<div class="label">For you</div><section class="card srows">${row(guess)}</section><div class="label">Common</div>`}
      <section class="card srows">${list.filter((c) => q || c !== guess).map(row).join('') || '<div class="srow"><span><small>Nothing matches.</small></span></div>'}</section>`;
  }
  if (step === 'income') return `<div class="label">Set up your budget<span class="lr">Step 2 of 3</span></div>${bar}
      <section class="card mn-intro"><b>Money coming in each month</b><small>Your salary and anything else that comes every month. After tax, as it lands in your account.</small></section>
      ${mnRows('income')}<button class="sbtn" data-mnadd="income">+ Add income</button>
      <button class="sbtn main" data-mnstep="bills"${D.income.length ? '' : ' disabled'}>Next: your bills</button>`;
  if (step === 'bills') return `<div class="label">Set up your budget<span class="lr">Step 3 of 3</span></div>${bar}
      <section class="card mn-intro"><b>Bills each month</b><small>Rent, phone, subscriptions: anything charged every month, and the day it is charged.</small></section>
      ${mnRows('bills')}<button class="sbtn" data-mnadd="bill">+ Add a bill</button>
      <p class="hint">For now this covers bills that come every month. Yearly and quarterly bills are coming soon.</p>
      <button class="sbtn main" data-mnstep="done">Show my daily budget</button>`;
  return '';
}
function mnRows(kind) {
  const rows = MND[kind];
  if (!rows.length) return '';
  return `<section class="card srows">${rows.map((r) => `<button class="srow sgo" data-mnedit="${kind}:${esc(r.id)}"><span><b>${esc(r.name)}</b>${kind === 'bills' ? `<small>Every month on the ${mnNth(r.day)}</small>` : '<small>Every month</small>'}</span><span class="mn-amt">${mnFmt(r.amount)}</span></button>`).join('')}</section>`;
}

// ---------- Every day after: what you can spend today ----------
function renderMoney() {
  const box = $('#money-body'); if (!box || !MND) return;
  if (MN.step && MN.step !== 'done') { box.innerHTML = mnSetupHTML(); return; }
  const D = MND, f = mnFmt;
  const eye = `<button class="mn-eye" data-mneye aria-label="${MN.show ? 'Hide amounts' : 'Show amounts'}" aria-pressed="${MN.show}">${MN_EYE(MN.show)}<span>${MN.show ? 'Hide' : 'Show'}</span></button>`;
  const over = D.over || (D.today_budget != null && D.today_budget < 0);
  const hero = !D.income.length ? `<section class="card mn-hero"><small>Today you can spend</small><p>Add your income to see your daily budget.</p><button class="sbtn main" data-mnadd="income">+ Add income</button></section>`
    : `<section class="card mn-hero${over ? ' over' : ''}"><div class="mn-hh"><small>${over ? 'This month is over budget' : 'Today you can spend'}</small>${eye}</div>
      <b class="mn-big num">${over && D.today_budget != null ? f(-D.today_budget) : f(D.today_budget)}</b>
      <small>${over ? 'Spent more than this month leaves, spread over the days left.' : D.spent_today == null ? 'Bills for the whole month are already counted.' : D.spent_today ? `${f(D.left_today)} left today, after ${f(D.spent_today)} spent` : 'Nothing spent yet today. Bills for the whole month are already counted.'}</small>
      <button class="sbtn main" data-mnadd="spent">+ Spent</button></section>`;
  const line = (t, v, sub) => `<div class="srow"><span><b>${t}</b>${sub ? `<small>${sub}</small>` : ''}</span><span class="mn-amt">${v}</span></div>`;
  const month = new Date(D.today + 'T12:00:00').toLocaleDateString(undefined, { month: 'long' });
  const sums = `<div class="label">${esc(month)}</div><section class="card srows">${line('Income', f(D.total_income))}${line('Bills', f(D.total_bills == null ? null : -D.total_bills), 'All of them, paid or not')}
      ${line('Spent so far', f(D.total_spent == null ? null : -D.total_spent))}${line('Left for the month', f(D.left_month), `Spread over ${D.days_left} day${D.days_left === 1 ? '' : 's'}, today included`)}</section>`;
  const bill = (b, paid) => `<button class="srow sgo" data-mnedit="bills:${esc(b.id)}"><span><b>${esc(b.name)}</b><small>${paid ? 'Charged' : 'Coming'} on the ${mnNth(b.on)}${b.on !== b.day ? ` (the ${mnNth(b.day)} is after this month ends)` : ''}</small></span><span class="mn-amt">${f(b.amount)}</span></button>`;
  const bills = `<div class="label">Bills this month<button class="sg-add" data-mnadd="bill">+ Bill</button></div><section class="card srows">${D.upcoming.map((b) => bill(b, false)).join('')}${D.paid.map((b) => bill(b, true)).join('')
      || ''}${D.bills.length ? '' : '<div class="srow"><span><small>No bills yet.</small></span></div>'}</section>`;
  const spends = D.spent.length ? `<div class="label">Spent this month</div><section class="card srows">${D.spent.map((s) => `<button class="srow" data-mnspent="${esc(s.id)}"><span><b>${esc(s.note || 'Spent')}</b><small>${new Date(D.month + '-' + String(s.day).padStart(2, '0') + 'T12:00:00').toLocaleDateString(undefined, { weekday: 'short', day: 'numeric', month: 'short' })}</small></span><span class="mn-amt">${f(s.amount)}</span></button>`).join('')}</section>` : '';
  const income = `<div class="label">Income each month<button class="sg-add" data-mnadd="income">+ Income</button></div>${mnRows('income') || '<section class="card srows"><div class="srow"><span><small>No income yet.</small></span></div></section>'}`;
  box.innerHTML = hero + sums + bills + spends + income
    + `<p class="hint mn-foot">In ${esc(mnName(D.currency))} (${esc(mnSym(D.currency))}). <button class="mn-link" data-mncurrency>Change</button> Amounts and names stay hidden until you tap Show, and hide again after a minute.</p>`;
}

// ---------- The sheet: income, a bill, something spent, or the PIN ----------
function mnSheet() {
  let w = $('#mns'); if (w) return w;
  document.body.insertAdjacentHTML('beforeend', `<div class="sheet-wrap" id="mns" hidden><div class="sheet-bg" data-mnclose></div><div class="sheet" role="dialog" aria-modal="true" aria-labelledby="mns-t"><div class="grab"></div>
    <div class="sheet-head"><button class="done" data-mnclose>Cancel</button><h2 id="mns-t"></h2><div class="head-acts"></div></div><div class="sheet-body sg-f" id="mns-b"></div></div></div>`);
  w = $('#mns');
  if (typeof sheetDrag === 'function') sheetDrag(w, () => { w.hidden = true; });
  w.addEventListener('click', mnSheetClick);
  return w;
}
async function mnOpen(kind, item) {
  if (kind !== 'pin' && !MN.show && !MN.step && item) {  // to change an amount you have to see it
    if (!await mnReveal()) return;
    item = (MND[kind === 'income' ? 'income' : 'bills'] || []).find((x) => x.id === item.id) || item;
  }
  MN.kind = kind; MN.item = item || null;
  const sym = esc(mnSym(MND.currency)), val = (v) => v == null ? '' : (v / 100).toString();
  const amt = (label, v) => `<label for="mnf-a">${label}</label><div class="mn-ain"><span>${sym}</span><input id="mnf-a" inputmode="decimal" value="${esc(val(v))}" placeholder="0" autocomplete="off"></div>`;
  const today = +MND.today.slice(8);
  const body = kind === 'pin' ? `<p class="hint">A PIN guards your settings and your money. Type it to show the amounts.</p><label for="mnf-pin">PIN</label><input id="mnf-pin" type="password" inputmode="numeric" autocomplete="off">`
    : kind === 'spent' ? `${amt('How much', null)}<label for="mnf-n">What for (optional)</label><input id="mnf-n" maxlength="40" placeholder="Lunch" autocomplete="off">
      <label for="mnf-d">When</label><select id="mnf-d">${[...Array(today)].map((_, i) => today - i).map((d) => `<option value="${d}">${d === today ? 'Today' : d === today - 1 ? 'Yesterday' : 'The ' + mnNth(d)}</option>`).join('')}</select>
      <p class="hint">It comes off today’s budget, and the days left share what remains.</p>`
    : `<label for="mnf-n">Name</label><input id="mnf-n" maxlength="40" value="${esc(item?.name || '')}" placeholder="${kind === 'income' ? 'Salary' : 'Rent'}" autocomplete="off">
      ${amt(kind === 'income' ? 'Each month' : 'Amount each month', item?.amount)}
      ${kind === 'bill' ? `<label for="mnf-day">Charged on</label><select id="mnf-day">${[...Array(31)].map((_, i) => `<option value="${i + 1}"${(item?.day || 1) === i + 1 ? ' selected' : ''}>The ${mnNth(i + 1)}</option>`).join('')}</select>
        <p class="hint">Only bills that come every month for now. Yearly and quarterly bills are coming soon.</p>` : ''}`;
  mnSheet().hidden = false;
  $('#mns-t').textContent = kind === 'pin' ? 'Show amounts' : kind === 'spent' ? 'Spent' : `${item ? 'Change' : 'Add'} ${kind === 'income' ? 'income' : 'a bill'}`;
  $('#mns-b').innerHTML = body + `<div class="err-t" id="mnf-err"></div><button class="sg-go" data-mnsave>${kind === 'pin' ? 'Show' : 'Save'}</button>${item ? `<button class="sg-del" data-mndel>Delete</button>` : ''}`;
  setTimeout(() => $('#mns-b input')?.focus(), 50);
}
async function mnSheetClick(e) {
  const t = e.target.closest('button, .sheet-bg'); if (!t) return;
  if (t.matches('[data-mnclose]')) { $('#mns').hidden = true; return; }
  const err = (m) => { $('#mnf-err').textContent = m; };
  const k = MN.kind, path = k === 'income' ? '/money/income' : k === 'bill' ? '/money/bill' : '/money/spent';
  if (t.matches('[data-mndel]')) {
    if (!await confirmSheet({ title: 'Delete this?', text: MN.item.name, ok: 'Delete', danger: true })) return;
    return mnSend(path + '/delete', { id: MN.item.id });
  }
  if (!t.matches('[data-mnsave]')) return;
  if (k === 'pin') { mnPin = $('#mnf-pin').value.trim(); try { sessionStorage.setItem('spin', mnPin); } catch (x) {} $('#mns').hidden = true; return mnReveal(); }
  const a = $('#mnf-a').value.trim();
  if (!a) return err('Type an amount.');
  if (k === 'spent') return mnSend(path, { amount: a, note: $('#mnf-n').value, day: +$('#mnf-d').value });
  const name = $('#mnf-n').value.trim();
  if (!name) return err('Give it a name.');
  return mnSend(path, { id: MN.item?.id, name, amount: a, day: k === 'bill' ? +$('#mnf-day').value : undefined });
}
async function mnSend(path, body) {
  const b = $('#mns-b [data-mnsave]'); if (b) b.disabled = true;
  try { MND = await mnFetch(path, body, MN.show || !!MN.step); $('#mns').hidden = true; renderMoney(); }
  catch (err) { if (err.code === 403) { $('#mns').hidden = true; return mnAskPin(); } $('#mnf-err').textContent = err.msg || 'That did not save. Try again.'; if (b) b.disabled = false; }
}
function mnAskPin() { mnOpen('pin'); }
async function mnReveal() {
  try { MND = await mnFetch('/money', null, true); } catch (err) { if (err.code === 403) { mnAskPin(); return false; } return false; }
  if (!MND.shown) { mnAskPin(); return false; }
  MN.show = true; clearTimeout(MN.hideAt); MN.hideAt = setTimeout(mnHide, 60000);  // hidden again after a minute
  renderMoney(); return true;
}

$('#money-body') && document.addEventListener('click', async (e) => {
  if (!e.target.closest('#money-body')) return;
  const t = e.target.closest('button'); if (!t) return;
  if (t.dataset.mncur) {
    try { MND = await mnFetch('/money/currency', { currency: t.dataset.mncur }, true); } catch (err) { if (err.code === 403) return mnAskPin(); return toast?.('That did not save.'); }
    MN.q = '';
    if (MND.income.length) { MN.step = null; MN.show = false; return loadMoney(); }  // a change of currency: back to the hidden view
    MN.step = 'income'; return renderMoney();
  }
  if (t.dataset.mnstep === 'done') { MN.step = null; MN.show = false; return loadMoney(); }  // set up: from now on amounts start hidden
  if (t.dataset.mnstep) { MN.step = t.dataset.mnstep; return renderMoney(); }
  if (t.dataset.mncurrency !== undefined) { MN.step = 'currency'; MN.q = ''; return loadMoney(); }
  if ('mneye' in t.dataset) { if (MN.show) { MN.show = false; clearTimeout(MN.hideAt); return loadMoney(); } return mnReveal(); }
  if (t.dataset.mnadd) return mnOpen(t.dataset.mnadd);
  if (t.dataset.mnedit) { const [kind, id] = t.dataset.mnedit.split(':'); return mnOpen(kind === 'income' ? 'income' : 'bill', MND[kind].find((x) => x.id === id)); }
  if (t.dataset.mnspent) {
    if (!await confirmSheet({ title: 'Remove this spending?', text: 'It goes back into today’s budget.', ok: 'Remove', danger: true })) return;
    try { MND = await mnFetch('/money/spent/delete', { id: t.dataset.mnspent }); renderMoney(); } catch (err) { if (err.code === 403) mnAskPin(); }
  }
});
document.addEventListener('input', (e) => { if (e.target.id === 'mn-q') { MN.q = e.target.value; const pos = e.target.selectionStart; renderMoney(); const i = $('#mn-q'); if (i) { i.focus(); i.setSelectionRange(pos, pos); } } });
