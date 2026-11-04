// ---------- Updates: a popup when a new version is out, with its notes by kind, and a card on Home once it is in ----------
// The notes come from commit messages: security: is Security, feat: is New, fix: is Fixed (modules/server, parse_notes).
const UPD_KINDS = [['security', 'Security', 'sec'], ['new', 'New', 'new'], ['fixed', 'Fixed', 'fix']];
const UPD = { r: null, from: null, to: null, step: 0, t: null };
const updCount = (n) => n ? UPD_KINDS.reduce((a, [k]) => a + (n[k] || []).length, 0) : 0;
const UPD_SVG = (d, w = 2) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const UPD_SHIELD = UPD_SVG('M12 3l7 3v6c0 4-3 7.5-7 9-4-1.5-7-5-7-9V6zM9 12l2 2 4-4');

function updNotesHTML(n) {
  if (!updCount(n)) return `<p class="upd-none">${n ? 'Small changes behind the scenes.' : 'The notes could not be read right now.'}</p>`;
  return UPD_KINDS.filter(([k]) => (n[k] || []).length).map(([k, label, c]) =>
    `<div class="upd-g"><span class="upd-pill ${c}">${label}<em>${n[k].length}</em></span><ul>${n[k].map((t) => `<li>${esc(t)}</li>`).join('')}</ul></div>`).join('');
}
function updPills(n) {
  return UPD_KINDS.filter(([k]) => n && (n[k] || []).length).map(([k, label, c]) => `<span class="upd-pill ${c}">${n[k].length} ${label.toLowerCase()}</span>`).join('');
}
function updWhen(d) {
  if (!d) return '';
  const t = new Date(d + 'T12:00:00'), days = Math.round((new Date().setHours(12, 0, 0, 0) - t) / 864e5);
  return days <= 0 ? 'Released today' : days === 1 ? 'Released yesterday' : 'Released ' + t.toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}
function updLink(url) { return /^https:\/\/github\.com\//.test(url || '') ? `<a class="upd-full" href="${esc(url)}" target="_blank" rel="noopener">Full release notes on GitHub</a>` : ''; }

function updOpen(title, html) { $('#upd-title').textContent = title; $('#upd-body').innerHTML = html; $('#upd').hidden = false; }
function updClose() { $('#upd').hidden = true; }

// The offer: from and to, the notes, a line on safety, Later and Update now
function updOffer(r) {
  const n = updCount(r.notes), meta = [updWhen(r.notes && r.notes.date), n ? `${n} change${n === 1 ? '' : 's'}` : ''].filter(Boolean).join(' · ');
  const act = r.helper
    ? `<div class="upd-acts"><button data-upd-later>Later</button><button class="pri" data-upd-go>Update now</button></div>`
    : `<div class="snote"><b>Updating from here needs the host helper.</b> ${hlRunIn()} this once, then the button works. Or update from the terminal:${cmdHTML(hlCmd('agent install'))}${cmdHTML(hlCmd('update'))}</div><div class="upd-acts"><button data-upd-later>Later</button></div>`;
  updOpen('Update available', `<div class="upd-v"><i class="upd-ico">${UPD_SVG('M12 3v12M7 10l5 5 5-5M5 21h14')}</i><span><b class="num">${esc(r.version)} <em>→</em> ${esc(r.latest)}</b><small>${esc(meta)}</small></span></div>
    <section class="card upd-notes">${updNotesHTML(r.notes)}</section>
    <p class="upd-safe">${UPD_SHIELD}A snapshot is taken first. If anything fails, it goes back by itself. It takes a few minutes.</p>${act}${updLink(r.url)}`);
}

// While it runs: four steps that tick off, from the helper's log and from the assistant going quiet while it restarts
function updProgress() {
  const steps = ['Snapshot of your data', `Moving to ${UPD.to || 'the new version'}`, 'Restarting the apps', 'Health check'];
  updOpen(`Updating${UPD.to ? ' to ' + UPD.to : ''}`, `<section class="card upd-steps">${steps.map((s, i) => `<div class="upd-step ${i < UPD.step ? 'ok' : i === UPD.step ? 'now' : 'wait'}"><i></i>${esc(s)}</div>`).join('')}</section>
    <p class="upd-safe">${UPD_SHIELD}You can close this. The dashboard reloads by itself when it is done.</p><div class="upd-acts"><button data-upd-close>Close</button></div>`);
}
async function updTick() {
  clearTimeout(UPD.t);
  let r = null;
  try { r = await setApi('/server/update'); } catch (e) {}
  if (r && r.ok && UPD.from && r.version !== UPD.from) { location.reload(); return; }  // the new version is answering
  if (r && r.ok && r.state === 'failed') {
    return updOpen('The update did not finish', `<section class="card upd-notes"><p class="upd-none">Nothing was lost. Your data and settings are as they were, on version ${esc(r.version)}.</p></section>
      ${(r.log || []).length ? `<div class="snote">${r.log.map(esc).join('<br>')}</div>` : ''}<div class="upd-acts"><button data-upd-close>Close</button><button class="pri" data-upd-settings>Open Updates</button></div>`);
  }
  if (r && r.ok && r.state === 'idle' && UPD.step === 0 && !UPD.from) return;
  const log = (r && r.log || []).join('\n');
  if (/Snapshot:/.test(log)) UPD.step = Math.max(UPD.step, 1);
  if (/Data is up to date/.test(log)) UPD.step = Math.max(UPD.step, 2);
  if (!(r && r.ok)) UPD.step = Math.max(UPD.step, 2);  // nothing answers while the apps restart, which is expected
  if (!$('#upd').hidden && $('#upd-body .upd-steps')) updProgress();
  UPD.t = setTimeout(updTick, 3000);
}
async function updGo() {
  const r = await setApi('/server/update', {});
  if (r.locked || r.code === 403 || r.code === 429) { updClose(); openSettings(); SET.page = 'update'; return setRender(); }  // a settings PIN guards updating: Settings asks for it
  if (!r.ok) { updClose(); return toast(r.msg || r.error || 'The update did not start.'); }
  UPD.from = UPD.r.version; UPD.to = UPD.r.latest; UPD.step = 0;
  updProgress(); UPD.t = setTimeout(updTick, 3000);
}

// After an update: a card on Home with what changed, until it is read or closed
function updSeen() { $('#upd-done')?.remove(); setApi('/server/update/seen', {}).catch(() => {}); }
function updCard(u) {
  if ($('#upd-done')) return;
  const pills = updPills(u.notes);
  $('#v-home header.top').insertAdjacentHTML('afterend', `<section class="card upd-done" id="upd-done"><div class="upd-dh"><i class="upd-ok">${UPD_SVG('M5 12l5 5L20 7', 2.4)}</i>
    <span><b>Updated to ${esc(u.to)}</b><small>You were on ${esc(u.from)}. Your data and settings are as they were.</small></span>
    <button class="upd-x" data-upd-seen aria-label="Close">${UPD_SVG('M6 6l12 12M18 6L6 18')}</button></div>
    ${pills ? `<div class="upd-chips">${pills}</div>` : ''}<button class="upd-see" data-upd-see>See what changed</button></section>`);
}

async function updInit() {
  let r = null;
  try { r = await setApi('/server/update'); } catch (e) { return; }
  if (!r || !r.ok) return;  // the assistant is not answering: nothing to offer, nothing breaks
  UPD.r = r;
  if (r.updated) updCard(r.updated);
  if (r.state === 'updating') { UPD.from = r.version; UPD.to = r.to; updProgress(); return updTick(); }
  let later = ''; try { later = localStorage.getItem('updLater') || ''; } catch (e) {}
  const busy = !$('#setp').hidden || ($('#wizp') && !$('#wizp').hidden);  // never on top of Settings or the setup wizard
  if (r.available && r.state === 'idle' && later !== r.latest && !busy) updOffer(r);
}

$('#upd').addEventListener('click', (e) => {
  if (e.target.closest('[data-upd-go]')) return updGo();
  if (e.target.closest('[data-upd-later]')) { try { localStorage.setItem('updLater', UPD.r.latest); } catch (err) {} return updClose(); }
  if (e.target.closest('[data-upd-settings]')) { updClose(); openSettings(); SET.page = 'update'; return setRender(); }
  if (e.target.closest('[data-upd-close], .sheet-bg')) { if ($('#upd-body .upd-whatsnew')) updSeen(); return updClose(); }
});
$('#v-home').addEventListener('click', (e) => {
  if (e.target.closest('[data-upd-seen]')) return updSeen();
  if (e.target.closest('[data-upd-see]')) {
    const u = UPD.r.updated;
    updOpen(`What’s new in ${u.to}`, `<section class="card upd-notes upd-whatsnew">${updNotesHTML(u.notes)}</section><div class="upd-acts"><button class="pri" data-upd-close>Done</button></div>`);
  }
});
