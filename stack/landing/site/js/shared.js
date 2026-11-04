// Small helpers the views share (formatting, icons, the sheet opener). Loaded before any view.
const one = async (q) => { try { const r = await prom(q); return r.length ? Number(r[0].value[1]) : null; } catch { return null; } };
const row = (k, v) => v === '' || v == null ? '' : `<div class="srow2"><span>${k}</span><b>${v}</b></div>`;
const GB = (b) => (b / 1e9).toFixed(b < 10e9 ? 1 : 0) + ' GB';
function sheetOpen(title, html, close = 'Cancel') { $('#sheet-title').textContent = title; $('#sheet-body').innerHTML = html; showSheet(close); }
const jdCap = (t) => t.charAt(0).toUpperCase() + t.slice(1);
const CHEV = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 6l6 6-6 6"/></svg>';
const XMARK = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M6 6l12 12M18 6 6 18"/></svg>';
const dParse = (d) => new Date(d + 'T12:00:00');
const isoDay = (d) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const shortDate = (d) => dParse(d).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;
const WD = ['M', 'T', 'W', 'Th', 'F', 'Sa', 'S'];  // weekday letters, Monday first
const longDate = (d) => dParse(d).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
const PEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 20h4L19 9a2.8 2.8 0 0 0-4-4L4 16v4zM13.5 6.5l4 4"/></svg>';
const TRASH = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>';
const hhmm = (t) => new Date(t * 1000).toLocaleTimeString('en-US', T12);
const closeSheet = () => { $('#sheet').hidden = true; document.body.style.overflow = ''; if (sheetChanged) { sheetChanged = false; loadServer(); } };

// Commands the dashboard asks you to run: each in a code block with a Copy button, written the way your terminal runs it
// (homelab when install put it on the PATH, else bin/homelab from the project folder; /setup says which)
let HL_CLI = 'bin/homelab';
const hlCmd = (args) => `${HL_CLI} ${args}`;
const hlRunIn = () => HL_CLI.startsWith('bin/') ? 'In the project folder, run' : 'Run';
// Copy buttons everywhere: a copy icon that turns into a green tick for a moment, both the same size (copyFlash)
const ICON_COPY = '<svg class="ic-copy" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V6a2 2 0 0 1 2-2h8"/></svg>';
const ICON_TICK = '<svg class="ic-tick" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const COPY_ICONS = `<span class="cp">${ICON_COPY}${ICON_TICK}</span>`;
const cmdHTML = (cmd) => `<div class="cmd"><code>${esc(cmd)}</code><button type="button" class="cmd-copy" data-copy="${esc(cmd)}" aria-label="Copy: ${esc(cmd)}" title="Copy">${COPY_ICONS}</button></div>`;
const cmdsHTML = (cmds) => (cmds || []).map(cmdHTML).join('');
// steps: [{ text | html, cmd | cmds }] -> a numbered list, commands under the step they belong to
const stepsHTML = (steps) => `<ol class="wz-steps">${steps.map((s, i) => `<li><span class="n">${i + 1}</span><span class="st">${s.html ?? esc(s.text)}${cmdsHTML(s.cmds || (s.cmd ? [s.cmd] : []))}</span></li>`).join('')}</ol>`;
// Plain http (a phone on the home network) hides navigator.clipboard, and Safari only allows the old textarea copy inside the tap itself,
// so that runs first, synchronously; the clipboard API is the fallback. -> Promise of true when it copied.
function clipCopy(text) {
  const ta = document.createElement('textarea');
  ta.value = text; ta.readOnly = true; ta.setAttribute('aria-hidden', 'true'); ta.className = 'cmd-hidden';
  document.body.appendChild(ta); ta.focus({ preventScroll: true }); ta.select(); ta.setSelectionRange(0, text.length);
  let ok = false; try { ok = document.execCommand('copy'); } catch (e) {}
  ta.remove();
  if (ok) return Promise.resolve(true);
  return navigator.clipboard ? navigator.clipboard.writeText(text).then(() => true, () => false) : Promise.resolve(false);
}
function copyFlash(btn, ok) {  // the icon becomes a green tick (or the button shakes its head) for a moment
  btn.classList.remove('copied', 'copy-bad'); void btn.offsetWidth; btn.classList.add(ok ? 'copied' : 'copy-bad');
  clearTimeout(btn._t); btn._t = setTimeout(() => btn.classList.remove('copied', 'copy-bad'), 1600);
}
document.addEventListener('click', async (e) => {
  const b = e.target.closest('[data-copy]'); if (!b) return;
  e.preventDefault(); e.stopPropagation();
  const ok = await clipCopy(b.dataset.copy);
  if (!ok) { const r = document.createRange(); r.selectNodeContents(b.previousElementSibling); getSelection().removeAllRanges(); getSelection().addRange(r); }  // selected, ready for Ctrl+C
  copyFlash(b, ok);
});
