// ---------- Setup wizard: the first-run steps, and the Finish setup card on Home ----------
// Progress lives in the assistant (setup.json in its data folder), so closing the page or switching device resumes at the same step.
// Every step can be skipped; skipped steps wait on Home in the Finish setup card.
const WZ = { d: null, screen: 'welcome', tg: 'guide', tgWhy: '', ai: 'install', aiWhy: '', aiWarn: [], access: 'local', accessWhy: '', mods: {}, name: '', tz: '', timer: null, busy: false };
const WZ_GOALS = [['Notes and journal', ['journal', 'day', 'planner', 'briefing']], ['Fitness', ['gym', 'health']], ['News and sport', ['news', 'sports']], ['Weather and travel', ['weather', 'flights', 'location', 'currency', 'clock']],
  ['Email and calendar', ['gmail', 'calendar']], ['AI chat and search', ['ai', 'search']], ['My server', ['server', 'alerts']]];
const wzZones = () => { try { return Intl.supportedValuesOf('timeZone'); } catch (e) { return []; } };
const wzBrowserZone = () => { try { return Intl.DateTimeFormat().resolvedOptions().timeZone || ''; } catch (e) { return ''; } };
const WZ_IDS = ['modules', 'apps', 'ai', 'telegram', 'access'];
const WZ_NAMES = { modules: 'What you will use', apps: 'Apps', ai: 'AI engine', telegram: 'Telegram', access: 'Access' };
// apps that go with what you picked in step 1 (the AI engine has its own step)
const WZ_SUGGEST = { searxng: ['search'], 'open-webui': ['ai'], whisper: [] };
const wzBody = () => $('#wiz-body');
const wzToast = (msg) => { const t = document.createElement('div'); t.className = 'toast bad'; t.textContent = msg; wzBody().prepend(t); setTimeout(() => t.remove(), 6000); };
const wzIcon = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;
const WZI = { cpu: 'M9 3v2M15 3v2M9 19v2M15 19v2M3 9h2M3 15h2M19 9h2M19 15h2M7 7h10v10H7z', box: 'M3 8l9-5 9 5v8l-9 5-9-5zM3 8l9 5 9-5M12 13v8', check: 'M5 12l5 5 9-10', spark: 'M12 3l2 6 6 2-6 2-2 6-2-6-6-2 6-2z',
  clock: 'M12 7v5l3 2M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z', info: 'M12 8h.01M11 12h1v5h1M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z', warn: 'M12 9v4M12 17h.01M10.3 4l-8 14a2 2 0 0 0 1.7 3h16a2 2 0 0 0 1.7-3l-8-14a2 2 0 0 0-3.4 0z', lock: 'M6 11h12v9H6zM8 11V8a4 4 0 0 1 8 0v3' };
const wzRow = (icon, title, sub, right) => `<div class="srow"><span class="wz-ico">${wzIcon(WZI[icon] || WZI.box)}</span><span><b>${esc(title)}</b><small>${esc(sub || '')}</small></span>${right || ''}</div>`;
const wzMsg = (kind, icon, text) => `<div class="wz-msg ${kind}">${wzIcon(WZI[icon])}<span>${esc(text)}</span></div>`;
const wzOpt = (id, on, title, sub, badge, off) => `<button class="wz-opt" role="radio" aria-checked="${on}" data-opt="${id}"${off ? ' disabled' : ''}><i class="wz-radio"></i><span><b>${esc(title)}${badge ? `<i class="wz-pill rec">${esc(badge)}</i>` : ''}</b><small>${esc(sub)}</small></span></button>`;

async function wzLoad() { const r = await setApi('/setup'); if (r.ok) { WZ.d = r; if (r.cli) HL_CLI = r.cli; } return r; }
function wzOpen(screen) {
  WZ.screen = screen; WZ.tg = WZ.d?.telegram?.connected ? 'ok' : 'guide'; WZ.tgWhy = WZ.aiWhy = WZ.accessWhy = ''; WZ.aiWarn = []; WZ.aiCmds = WZ.accessCmds = [];
  WZ.mods = Object.fromEntries((WZ.d?.modules || []).map((m) => [m.name, m.enabled]));
  WZ.name = WZ.d?.profile?.name || '';  // the name typed in the terminal is a real value, ready to keep or change
  WZ.tz = wzBrowserZone() || WZ.d?.profile?.timezone || '';
  WZ.cat = null; setApi('/setup/access').then((a) => { if (a.mode === 'lan' && WZ.access === 'local') { WZ.access = 'lan'; if (WZ.screen === 'access') wzRender(); } }).catch(() => {});
  $('#wizp').hidden = false; document.body.style.overflow = 'hidden'; $('#wizp .panel-body').scrollTop = 0; wzRender();
}
function wzClose() { clearInterval(WZ.timer); WZ.single = false; $('#wizp').hidden = true; document.body.style.overflow = ''; wzFinishCard(); }
const wzStatus = (id) => (WZ.d.steps.find((s) => s.id === id) || {}).status;

function wzShell(n, title, sub, body, why, bar) {
  return `${WZ.single ? '' : `<div class="wz-top"><div class="wz-prog"><i style="width:${n * 100 / WZ_IDS.length}%"></i></div><div class="wz-kick"><span>Step ${n} of ${WZ_IDS.length}</span><span>Progress is saved</span></div></div>`}
    <h3 class="wz-h">${title}</h3><p class="wz-sub">${sub}</p><section class="card wz-card">${body}</section>${why ? `<p class="wz-why">${why}</p>` : ''}${bar}`;
}
const wzBar = (id, nextLabel = 'Next', nextAct = 'next') => `<div class="wz-bar"><button data-act="back">${WZ.single ? 'Cancel' : 'Back'}</button>${WZ.single ? '' : '<button class="ghost" data-act="skip">Skip for now</button>'}<button class="main" data-act="${nextAct}">${WZ.single && nextLabel === 'Next' ? 'Save' : nextLabel}</button></div>`;

function wzTzField() {
  const zs = wzZones(), cur = WZ.tz;
  const opts = (zs.includes(cur) || !cur ? zs : [cur, ...zs]).map((z) => `<option value="${esc(z)}"${z === cur ? ' selected' : ''}>${esc(z.replace(/_/g, ' '))}</option>`).join('');
  return zs.length ? `<label class="sfield"><span>Your time zone</span><select id="wz-tz">${opts}</select></label>` : '';
}
const wzHello = () => (WZ.name || WZ.d?.profile?.name || '').trim();

function wzRender() {
  clearInterval(WZ.timer);
  const d = WZ.d, s = WZ.screen, el = wzBody();
  if (s === 'welcome') {
    el.innerHTML = `<div class="wz-ico" style="width:var(--ic);height:var(--ic)">${wzIcon(WZI.spark)}</div><h3 class="wz-h">Welcome home</h3>
      <p class="wz-sub">Your own assistant for the day: notes, journal, gym, budget, news and more. It runs on this machine and your data stays here.</p>
      <section class="card wz-card"><label class="sfield wz-first"><span>What should I call you?</span><input id="wz-name" autocomplete="given-name" maxlength="40" placeholder="Your first name" value="${esc(WZ.name)}"></label>
        <label class="sfield"><span>Your city, for the weather</span><input id="wz-city" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false" placeholder="Start typing, like Pune or Leeds" value="${esc(WZ.home?.city || WZ.d?.profile?.home || '')}"></label><div id="wz-city-hits" class="wz-hits"></div>
        ${wzTzField()}</section>
      <section class="card wz-card">${wzRow('clock', 'About 5 minutes', 'Five short steps')}${wzRow('check', 'Skip anything', 'Skipped steps wait on Home until you want them')}${wzRow('lock', 'Private by default', 'Nothing leaves this machine unless you turn it on')}</section>
      ${WZ.profWhy ? wzMsg('bad', 'warn', WZ.profWhy) : ''}
      <div class="wz-bar"><button class="ghost" data-act="later">I will do this later</button><button class="main" data-act="start">Start</button></div>`;
  } else if (s === 'apps') wzAppsRender();
  else if (s === 'modules') {
    const rows = d.modules.map((m) => `<div class="srow"><span><b>${esc(m.title)}</b><small>${esc(m.unavailable ? (m.why_off || 'Not available on this machine.') : m.description)}</small></span>${m.unavailable ? '<i class="wz-pill">Not available</i>' : ''}${swHTML(WZ.mods[m.name], m.name, m.title, m.unavailable)}</div>`).join('');
    const goals = WZ_GOALS.map(([t, ms]) => [t, ms.filter((m) => m in WZ.mods && !d.modules.find((x) => x.name === m)?.unavailable)]).filter(([, ms]) => ms.length)
      .map(([t, ms]) => `<button class="wz-goal" role="switch" aria-checked="${ms.every((m) => WZ.mods[m])}" data-goal="${esc(t)}">${esc(t)}</button>`).join('');
    el.innerHTML = wzShell(1, 'What will you use it for?', `${wzHello() ? `Nice to meet you, ${esc(wzHello())}. ` : ''}Tap what matters to you, or fine-tune each module below.`, `<div class="wz-goals">${goals}</div>` + rows,
      '<b>Why:</b> fewer modules means less to run and a calmer dashboard. Each one can be turned on later in Settings.', wzBar('modules'));
  } else if (s === 'ai') wzAiRender();
  else if (s === 'telegram') wzTgRender();
  else if (s === 'access') {
    const a = WZ.access;
    const pinBox = a === 'lan' ? `<label class="sfield"><span>PIN (4 to 12 digits)</span><input id="wz-pin" type="password" inputmode="numeric" autocomplete="off"></label>
      <div class="wz-msg">${wzIcon(WZI.info)}<span>Next opens it to your home network for you. The page blinks for a moment while the dashboard restarts.</span></div>` : '';
    const ts = a === 'tailscale' ? `<ol class="wz-steps"><li><span class="n">1</span><span>Install Tailscale on this machine and your phone from tailscale.com/download.</span></li><li><span class="n">2</span><span>Sign in to both with the same account.</span></li><li><span class="n">3</span><span>Open this machine's Tailscale name in your phone's browser. Nothing else to open on your router.</span></li></ol>` : '';
    el.innerHTML = wzShell(5, 'Who can open the dashboard?', 'Choose how you will reach it.',
      wzOpt('local', a === 'local', 'Only this machine', 'Open it at localhost on this computer.', 'Safest') + wzOpt('lan', a === 'lan', 'My home network, with a PIN', 'Phones and laptops at home. Choose a PIN of 4 to 12 digits.')
      + wzOpt('tailscale', a === 'tailscale', 'From anywhere, with Tailscale', 'A private network just for your devices. Steps below.') + pinBox + ts
      + (WZ.accessWhy ? wzMsg('bad', 'warn', WZ.accessWhy) + cmdsHTML(WZ.accessCmds) : ''),
      '<b>Why:</b> the dashboard holds your journal and budget, so it should only open for you. You can change this later in Settings.', wzBar('access'));
  } else if (s === 'done') {
    const what = { modules: `${Object.values(WZ.mods).filter(Boolean).length} modules on`, apps: WZ.cat ? (wzPicked().map((a) => a.title.split(' (')[0]).join(', ') || 'Nothing extra') : '',
      ai: { use: 'Using the Ollama found here', install: 'The suggested models', remote: 'Another machine\u2019s Ollama', none: 'No AI for now' }[WZ.ai] || '',
      telegram: d.telegram.connected ? 'Connected' : '', access: { local: 'Only this machine', lan: 'Home network, with a PIN', tailscale: 'Tailscale' }[WZ.access] || '' };
    const rows = d.steps.map((x) => wzRow(x.status === 'done' ? 'check' : 'clock', x.title, x.status === 'done' ? (what[x.id] || 'Done') : x.status === 'skipped' ? 'Skipped, finish later from Home' : 'Not started',
      `<button class="sact" data-change="${x.id}">Change</button>`)).join('');
    el.innerHTML = `<div class="wz-ico good" style="width:var(--ic);height:var(--ic)">${wzIcon(WZI.check)}</div><h3 class="wz-h">${wzHello() ? `You are set, ${esc(wzHello())}` : 'You are set'}</h3>
      <p class="wz-sub">Here is what is on. Anything you skipped waits for you on the home screen.</p><section class="card wz-card">${rows}</section>
      ${WZ.appsNote ? wzMsg('', 'info', WZ.appsNote) + cmdsHTML(WZ.appsCmds) : ''}${WZ.lanUrl ? `<div class="wz-msg">${wzIcon(WZI.info)}<span>On your phone, at home, open <b>${esc(WZ.lanUrl)}</b></span></div>` : ''}
      ${d.restart ? `<p class="wz-why"><b>One last thing:</b> the assistant restarts once to use your choices. It takes about a minute.</p>` : ''}
      <div class="wz-bar"><button class="main" data-act="finish">${d.restart ? 'Restart and open my dashboard' : 'Open my dashboard'}</button></div>`;
  }
}

// Step 2: the extra apps, the same list as Settings, Apps. What you already have is ticked; apps that go with step 1 are suggested.
const wzPicked = () => (WZ.cat?.apps || []).filter((a) => WZ.apps[a.id]);
function wzAppsRender() {
  if (!WZ.cat) {
    wzBody().innerHTML = wzShell(2, 'Extra apps', 'Loading the list\u2026', '<div class="skel"></div>', '', '');
    setApi('/server/catalog').then((r) => {
      WZ.cat = r.ok ? { ...r, apps: r.apps.filter((a) => a.id !== 'ollama') } : { apps: [], err: true };
      WZ.apps = Object.fromEntries(WZ.cat.apps.map((a) => [a.id, a.chosen || (WZ.cat.apps.every((x) => !x.chosen) && (WZ_SUGGEST[a.id] || []).some((m) => WZ.mods[m]))]));
      if (WZ.screen === 'apps') wzRender();
    });
    return;
  }
  const h = WZ.d.hardware, mb = wzPicked().reduce((n, a) => n + a.memory_mb, 0);
  const rows = WZ.cat.apps.map((a) => `<div class="srow"><span><b>${esc(a.title)}${(WZ_SUGGEST[a.id] || []).some((m) => WZ.mods[m]) ? '<i class="wz-pill rec">Suggested</i>' : ''}</b><small>${esc(a.what)} About ${a.memory_mb} MB.</small></span>${swHTML(WZ.apps[a.id], 'app:' + a.id, a.title)}</div>`).join('');
  wzBody().innerHTML = wzShell(2, 'Extra apps', 'The dashboard and the assistant always run. Add the extras you want; you can change this any time in Settings, Apps.',
    wzRow('cpu', h.summary, `${{ mac: 'Mac', wsl: 'Windows (WSL)' }[h.hardware.os] || 'Linux'}, ${h.hardware.arch}`) + (WZ.cat.err ? wzMsg('bad', 'warn', 'The app list can\u2019t be read right now. Skip this and add apps later in Settings, Apps.') : rows)
    + `<div class="srow"><span><b>${wzPicked().length ? `${wzPicked().length} selected, about ${mb >= 1000 ? (mb / 1000).toFixed(1) + ' GB' : mb + ' MB'}` : 'Nothing extra selected'}</b><small>The AI engine is set up in the next step.</small></span></div>`
    + (WZ.cat.helper === false && wzPicked().some((a) => !a.chosen) ? wzMsg('', 'info', 'Your picks are saved here. One command in the project folder starts them, and it is shown at the end.') : ''),
    '<b>Why:</b> each app uses some memory while it runs. Pick only what you will use; nothing here is needed for the assistant itself.', wzBar('apps'));
}

// Opening Ollama on another machine to this one, for the system that machine runs (tabs). Commands are copyable; the address goes in the field above.
const WZ_OLLAMA_OS = {
  mac: [{ text: 'Let other machines reach it. In Terminal:', cmd: 'launchctl setenv OLLAMA_HOST 0.0.0.0' },
    { text: 'Quit Ollama from the menu bar, then open it again.' },
    { text: 'Find its address on your home network:', cmd: 'ipconfig getifaddr en0' }],
  linux: [{ text: 'Let other machines reach it. This opens an editor:', cmd: 'sudo systemctl edit ollama' },
    { text: 'Add these two lines, then save and close:', cmd: '[Service]\nEnvironment="OLLAMA_HOST=0.0.0.0"' },
    { text: 'Restart it:', cmd: 'sudo systemctl restart ollama' },
    { text: 'Find its address on your home network (the first one):', cmd: 'hostname -I' }],
  windows: [{ text: 'Let other machines reach it. In PowerShell:', cmd: 'setx OLLAMA_HOST 0.0.0.0' },
    { text: 'Quit Ollama from the tray (next to the clock), then open it again.' },
    { text: 'Find its address: look for IPv4 Address.', cmd: 'ipconfig' }],
};
function wzRemoteSteps() {
  const os = WZ.ollOs || 'mac', tabs = [['mac', 'Mac'], ['linux', 'Linux'], ['windows', 'Windows']];
  const steps = [...WZ_OLLAMA_OS[os], { text: 'Type it in the Address field above as http://ADDRESS:11434 (a Tailscale address works too), then press Connect.' }];
  return `<div class="label">On the machine that runs Ollama</div><div class="seg ostabs" role="tablist">${tabs.map(([k, n]) => `<button type="button" role="tab" aria-selected="${k === os}" class="${k === os ? 'on' : ''}" data-oll-os="${k}">${n}</button>`).join('')}</div>`
    + stepsHTML(steps)
    + wzMsg('', 'info', 'Keep it inside your home network or Tailscale. Ollama has no password, so never forward port 11434 on your router.');
}

function wzAiRender() {
  const d = WZ.d, r = d.hardware.recommendation, p = d.pull || {};
  if (p.active || (WZ.pulling && !p.error && !p.done)) {
    const pct = p.total ? Math.round((p.completed / p.total) * 100) : 0, mb = (n) => (n / 1e9).toFixed(1);
    wzBody().innerHTML = wzShell(3, 'AI engine', 'Downloading. You can leave this page and it keeps going.',
      `<div class="srow"><span><b>Downloading ${esc(p.current || '')}</b><small>${p.total ? `${mb(p.completed)} of ${mb(p.total)} GB` : esc(p.status || 'Starting')}</small></span></div><div class="wz-bigbar"><i style="width:${pct}%"></i></div>`
      + (p.models || []).map((m) => `<div class="wz-msg">${wzIcon(WZI[m.status === 'done' ? 'check' : 'clock'])}<span>${esc(m.name)}: ${esc(m.status)}</span></div>`).join(''), '', `<div class="wz-bar"><button class="ghost" data-act="skip">Skip for now</button></div>`);
    WZ.timer = setInterval(wzAiPoll, 1500); return;
  }
  if (p.done && WZ.pulling) { WZ.pulling = false; }
  // look once for an Ollama that is already there (on this machine, or the AI engine app) and offer it first
  if (!WZ.det) { WZ.det = 'looking'; setApi('/setup/ai/detect').then((x) => { WZ.det = x.ok && Array.isArray(x.found) ? x : { found: [] }; if (WZ.det.found.length && WZ.ai === 'install') WZ.ai = 'use'; if (WZ.screen === 'ai') wzRender(); }); }
  const found = WZ.det?.found?.[0];
  const ok = r.models.length > 0, a = WZ.ai;
  const rec = ok ? `${r.models.map((m) => `${m.name} (${m.size_gb} GB)`).join(', ')}. About ${r.download_gb} GB, around ${Math.max(1, Math.round(r.download_gb * 80 / 60))} minutes at 100 Mbit/s.` : 'This machine is too small to run models well.';
  // the address stays in the field after a failed check, the reason sits right under it, and the steps to open Ollama on that machine are on the page
  const remote = a === 'remote' ? `<label class="sfield${WZ.aiWhy ? ' bad' : ''}"><span>Address</span><input id="wz-ollama" inputmode="url" spellcheck="false" placeholder="http://192.168.1.20:11434" value="${esc(WZ.ollamaUrl || '')}"></label>`
    + (WZ.aiWhy ? wzMsg('bad', 'warn', WZ.aiWhy) : '')
    + wzRemoteSteps() : '';
  const warn = (WZ.aiWarn || []).map((w) => wzMsg('warn', 'warn', w)).join('') + (WZ.aiWarn?.length ? `<button class="sbtn" data-act="ai-anyway">Download anyway</button>` : '');
  const names = (m) => m.length ? `${m.length} model${m.length === 1 ? '' : 's'}: ${m.slice(0, 3).join(', ')}${m.length > 3 ? '\u2026' : ''}` : 'no models yet';
  const useOpt = found ? wzOpt('use', a === 'use', `Use the Ollama on ${found.where}`, `Found it, with ${names(found.models)}. Any suggested model it lacks is downloaded.`, 'Recommended') : '';
  const looking = WZ.det === 'looking' ? wzMsg('', 'clock', 'Looking for an Ollama that is already running\u2026') : '';
  wzBody().innerHTML = wzShell(3, 'AI engine', 'The AI answers chats and reads your journal. It runs here, on this machine.',
    looking + useOpt + wzOpt('install', a === 'install', found ? 'Install the suggested models' : d.hardware.hardware.os === 'mac' ? 'Install the AI engine on this Mac, with the suggested models' : 'Install the AI engine and the suggested models',
      d.hardware.hardware.os === 'mac' && !found ? rec + ' It runs on the Mac itself, so it uses the Apple GPU.' : rec, ok && !found ? 'Recommended' : '', !ok) + wzOpt('remote', a === 'remote', "Use another machine's Ollama", 'Paste its address, for example http://192.168.1.20:11434') + remote
    + wzOpt('none', a === 'none', 'No AI for now', 'Everything except chat and the AI journal still works.') + warn + (WZ.aiWhy && a !== 'remote' ? wzMsg('bad', 'warn', WZ.aiWhy) + cmdsHTML(WZ.aiCmds) : (p.error && a !== 'remote' ? wzMsg('bad', 'warn', p.error) : '')),
    '<b>Why:</b> local models are private and free to use, but they need memory. We only suggest ones that fit this machine.', wzBar('ai', a === 'install' || a === 'use' ? 'Download' : a === 'remote' ? (WZ.aiWhy ? 'Try again' : 'Connect') : 'Next', 'ai-go'));
}
async function wzAiPoll() {
  const p = await setApi('/setup/ai/progress'); if (!p.ok) return;
  WZ.d.pull = p;
  if (p.done || p.error) {
    clearInterval(WZ.timer); await wzLoad(); WZ.pulling = false;
    if (p.done && WZ.single) return wzBackToSettings();
    if (p.done) { WZ.screen = 'telegram'; WZ.tg = WZ.d.telegram.connected ? 'ok' : 'guide'; }
  }
  wzRender();
}

function wzTgRender() {
  const d = WZ.d, st = WZ.tg;
  const guide = `<ol class="wz-steps"><li><span class="n">1</span><span>Open Telegram and message <b>@BotFather</b>.</span></li><li><span class="n">2</span><span>Send <b>/newbot</b> and answer the questions. Pick any name.</span></li><li><span class="n">3</span><span>Copy the token it gives you and paste it below.</span></li></ol>`;
  let body;
  if (st === 'ok') body = `<div class="srow"><span class="wz-ico good">${wzIcon(WZI.check)}</span><span><b>Connected</b><small>Your bot is linked to your chat. Say hi to it after the restart at the end.</small></span></div>`;
  else if (st === 'wait') body = guide + `<div class="wz-msg good">${wzIcon(WZI.check)}<span>Token accepted</span></div><div class="srow"><span><b>Now send /start to ${WZ.bot ? '@' + esc(WZ.bot) : 'your new bot'}</b><small>Waiting for your message…</small></span></div>`;
  else body = guide + `<label class="sfield${WZ.tgWhy ? ' bad' : ''}"><span>Bot token</span><input id="wz-token" autocomplete="off" spellcheck="false" placeholder="Paste your token here"></label>${WZ.tgWhy ? `<div class="wz-msg bad">${wzIcon(WZI.warn)}<span>${esc(WZ.tgWhy)}</span></div>` : ''}`;
  wzBody().innerHTML = wzShell(4, 'Connect Telegram', 'Chat with your assistant from your phone.', body,
    '<b>Why:</b> Telegram is how you add notes, ask questions and get your morning briefing. The dashboard works without it. <b>Your token stays on this machine.</b>',
    wzBar('telegram', st === 'ok' ? 'Next' : 'Check token', st === 'ok' ? 'next' : 'tg-token'));
  if (st === 'wait') WZ.timer = setInterval(wzTgPoll, 2000);
}
async function wzTgPoll() {
  const r = await setApi('/setup/telegram/detect', {});
  if (r.state === 'connected') { clearInterval(WZ.timer); WZ.tg = 'ok'; await wzLoad(); wzRender(); }
}

const wzIndex = () => WZ_IDS.indexOf(WZ.screen);
async function wzStep(id, status) { return setApi('/setup/step', { id, status }); }
function wzBackToSettings() {
  if (WZ.single === 'done') { WZ.single = false; WZ.screen = 'done'; return wzLoad().then(wzRender); }  // a Change from the summary goes back to it
  WZ.single = false; wzClose(); openSettings();
}
async function wzGoNext() {
  if (WZ.single) return wzBackToSettings();  // opened from a Settings row: one step, then back there
  const i = wzIndex(); await wzLoad();
  WZ.screen = i >= WZ_IDS.length - 1 ? 'done' : WZ_IDS[i + 1];
  WZ.tg = WZ.d.telegram.connected ? 'ok' : 'guide'; $('#wizp .panel-body').scrollTop = 0; wzRender();
}
const WZ_ACTS = {
  later: () => wzClose(),
  start: async () => {
    WZ.name = ($('#wz-name')?.value || '').trim(); WZ.tz = $('#wz-tz')?.value || WZ.tz; WZ.profWhy = '';
    const r = await setApi('/setup/profile', { name: WZ.name, timezone: WZ.tz, home: WZ.home || undefined });
    if (!r.ok) { WZ.profWhy = r.error || (r.problems || []).join(' ') || 'That did not save.'; return wzRender(); }
    await setApi('/setup/start', {}); await wzLoad(); WZ.screen = 'modules'; wzRender();
  },
  back: () => { if (WZ.single) return wzBackToSettings(); const i = wzIndex(); WZ.screen = i <= 0 ? 'welcome' : WZ_IDS[i - 1]; WZ.tg = WZ.d.telegram.connected ? 'ok' : 'guide'; wzRender(); },
  skip: async () => { await wzStep(WZ.screen, 'skipped'); await wzGoNext(); },
  next: async () => {
    const id = WZ.screen;
    if (id === 'modules') { const r = await setApi('/setup/modules', { enabled: WZ.mods }); if (!r.ok) return wzToast(r.error || (r.problems || []).join(' ') || 'That did not save.'); }
    else if (id === 'access') {
      if (WZ.access === 'lan') {
        const pin = ($('#wz-pin')?.value || '').trim();
        if (pin) { const r = await setApi('/settings/pin', { pin }); if (!r.ok) { WZ.accessWhy = r.error || 'That PIN did not save.'; return wzRender(); } SET.pin = pin; try { sessionStorage.setItem('spin', pin); } catch (e) {} }
        else if (!WZ.d.pin) { WZ.accessWhy = 'Choose a PIN so only you can change things.'; return wzRender(); }
        const r = await setApi('/setup/access', { mode: 'lan' });
        if (!r.ok) { WZ.accessWhy = r.error || 'That did not work.'; WZ.accessCmds = r.cmds || []; return wzRender(); }
        // the dashboard restarts on the new address; wait for it, then show the address for a phone
        for (let i = 0; i < 30; i++) { await new Promise((ok) => setTimeout(ok, 2000)); const a = await setApi('/setup/access').catch(() => null); if (a?.ok && a.mode === 'lan') { WZ.lanUrl = a.url; break; } }
      }
      if (WZ.access === 'local' && (await setApi('/setup/access').catch(() => ({}))).mode === 'lan') {  // back from the home network to this machine only
        const r = await setApi('/setup/access', { mode: 'local' });
        if (!r.ok) { WZ.accessWhy = r.error || 'That did not work.'; WZ.accessCmds = r.cmds || []; return wzRender(); }
      }
      await wzStep('access', 'done');
    } else if (id === 'apps') {
      const r = await setApi('/setup/apps', { apps: wzPicked().map((a) => a.id) });
      if (!r.ok) return wzToast(r.error || r.msg || 'That did not save.');
      WZ.appsNote = r.changed ? r.msg : ''; WZ.appsCmds = r.changed ? r.cmds || [] : []; await wzStep('apps', 'done');
    }
    else if (id === 'telegram' && WZ.d.telegram.connected) await wzStep('telegram', 'done');
    await wzGoNext();
  },
  'tg-token': async () => {
    const t = ($('#wz-token')?.value || '').trim();
    const r = await setApi('/setup/telegram/token', { token: t });
    if (!r.ok) { WZ.tgWhy = r.error || 'That token was not accepted.'; return wzRender(); }
    WZ.bot = r.bot; WZ.tg = 'wait'; WZ.tgWhy = ''; wzRender();
  },
  'ai-go': async () => {
    WZ.aiWhy = ''; WZ.aiWarn = [];
    if (WZ.ai === 'none') { await setApi('/setup/ai', { mode: 'none' }); return wzGoNext(); }
    if (WZ.ai === 'remote') WZ.ollamaUrl = ($('#wz-ollama')?.value || '').trim();
    const body = WZ.ai === 'remote' ? { mode: 'remote', url: WZ.ollamaUrl } : WZ.ai === 'use' ? { mode: 'use', url: WZ.det?.found?.[0]?.url } : { mode: 'install' };
    const r = await setApi('/setup/ai', body);
    if (r.code === 409 && r.warnings) { WZ.aiWarn = r.warnings; return wzRender(); }
    if (!r.ok) { WZ.aiWhy = r.error || (r.problems || []).join(' ') || 'That did not work.'; WZ.aiCmds = r.cmds || []; return wzRender(); }
    if (WZ.ai === 'remote') return wzGoNext();
    WZ.pulling = true; await wzLoad(); wzRender();
  },
  'ai-anyway': async () => { const r = await setApi('/setup/ai', WZ.ai === 'use' ? { mode: 'use', url: WZ.det?.found?.[0]?.url, anyway: true } : { mode: 'install', anyway: true }); if (r.ok) { WZ.aiWarn = []; WZ.pulling = true; await wzLoad(); wzRender(); } else { WZ.aiWhy = r.error || 'That did not work.'; WZ.aiCmds = r.cmds || []; wzRender(); } },
  finish: async () => {
    if (WZ.d.restart) {
      wzBody().innerHTML = `<h3 class="wz-h">Restarting</h3><p class="wz-sub">This page comes back in a minute.</p><div class="wz-bigbar"><i style="width:60%"></i></div>`;
      await setApi('/setup/restart', {});
      for (let i = 0; i < 60; i++) { await new Promise((ok) => setTimeout(ok, 2000)); try { const r = await fetch('/api/bot/doctor', { cache: 'no-store' }); if (r.ok) break; } catch (e) {} }
      return location.reload();
    }
    wzClose();
  },
};
document.addEventListener('click', async (e) => {
  const os = e.target.closest('#wizp [data-oll-os]');  // the Mac, Linux, Windows tabs; keeps what was typed in the address field
  if (os) { WZ.ollamaUrl = ($('#wz-ollama')?.value || WZ.ollamaUrl || '').trim(); WZ.ollOs = os.dataset.ollOs; return wzRender(); }
  const t = e.target.closest('#wizp [data-act], #wizp [data-opt], #wizp [data-goal], #wizp [data-sw], #wizp [data-change], [data-wiz], [data-wiz-step], [data-finish]'); if (!t) return;
  if (t.dataset.act) { if (WZ.busy) return; WZ.busy = true; try { await WZ_ACTS[t.dataset.act](); } finally { WZ.busy = false; } }
  else if (t.dataset.opt) { if (WZ.screen === 'ai') WZ.ai = t.dataset.opt; else WZ.access = t.dataset.opt; WZ.aiWhy = WZ.accessWhy = ''; WZ.aiWarn = []; WZ.aiCmds = WZ.accessCmds = []; wzRender(); }
  else if (t.dataset.goal) {
    const ms = (WZ_GOALS.find(([n]) => n === t.dataset.goal) || [, []])[1].filter((m) => m in WZ.mods && !WZ.d.modules.find((x) => x.name === m)?.unavailable);
    const on = !ms.every((m) => WZ.mods[m]); ms.forEach((m) => { WZ.mods[m] = on; }); wzRender();
  }
  else if (t.dataset.sw && WZ.screen === 'modules') { WZ.mods[t.dataset.sw] = !WZ.mods[t.dataset.sw]; wzRender(); }
  else if (t.dataset.sw && WZ.screen === 'apps') { const id = t.dataset.sw.slice(4); WZ.apps[id] = !WZ.apps[id]; wzRender(); }
  else if (t.dataset.change) { WZ.single = 'done'; WZ.screen = t.dataset.change; WZ.tg = WZ.d.telegram.connected ? 'ok' : 'guide'; $('#wizp .panel-body').scrollTop = 0; wzRender(); }
  else if (t.dataset.wizStep) { await wzLoad(); if (!$('#setp').hidden) closeSettings(); WZ.single = true; wzOpen(t.dataset.wizStep); }
  else if (t.dataset.wiz !== undefined) { await setApi('/setup/reset', {}); await setApi('/setup/start', {}); await wzLoad(); if (!$('#setp').hidden) closeSettings(); wzOpen('welcome'); }
  else if (t.dataset.finish) {
    const [kind, id] = t.dataset.finish.split(':');
    if (kind === 'dismiss') { await setApi('/setup/dismiss', { id }); await wzLoad(); return wzFinishCard(); }
    if (id === 'calendar') { openSettings(); SET.page = 'health'; setRender(); return; }
    await setApi('/setup/step', { id, status: 'pending' }); await wzLoad(); wzOpen(id);
  }
});
$('#wiz-close').onclick = wzClose;

function wzFinishCard() {
  const el = $('#finish'); if (!el) return;
  const list = (WZ.d && WZ.d.checklist) || [];
  if (!list.length) { el.hidden = true; return; }
  el.hidden = false;
  el.innerHTML = `<div class="finish-head"><span class="finish-n">${list.length}</span><span><b>Finish setup</b><small>${list.length === 1 ? 'One thing left' : plural(list.length, 'thing') + ' left'}. Each takes about a minute.</small></span></div>`
    + list.map((c) => `<div class="finish-row"><span><b>${esc(c.title)}</b><small>${esc(c.why)}</small></span><button class="quiet" data-finish="dismiss:${esc(c.id)}">Dismiss</button><button data-finish="go:${esc(c.id)}">Continue</button></div>`).join('');
}
async function wizardInit() {
  const r = await wzLoad(); if (!r.ok) return;
  wzFinishCard();
  if (r.show) { setApi('/setup/seen', {}); wzOpen(r.first_run && !r.steps.some((s) => s.status !== 'pending') ? 'welcome' : (r.next || 'done')); }
}

// Home city: type, then pick from the matches. Picking also sets the time zone to that place's, which is almost always what you want.
let wzCityT = null;
document.addEventListener('input', (e) => {
  if (e.target.id !== 'wz-city') return;
  clearTimeout(wzCityT); WZ.home = null;
  const q = e.target.value.trim(), box = $('#wz-city-hits');
  if (q.length < 2) { box.innerHTML = ''; return; }
  wzCityT = setTimeout(async () => {
    const r = await setApi('/setup/places?q=' + encodeURIComponent(q));
    if (!r.ok) { box.innerHTML = `<div class="wz-msg">${esc(r.error || 'Places can\u2019t be looked up right now.')}</div>`; return; }
    WZ.places = r.places;
    box.innerHTML = r.places.length ? r.places.map((p, i) => `<button class="wz-hit" data-place="${i}"><b>${esc(p.city)}</b><small>${esc([p.region, p.country].filter(Boolean).join(', '))}</small></button>`).join('')
      : '<div class="wz-msg">No place by that name. Try a nearby town.</div>';
  }, 300);
});
document.addEventListener('click', (e) => {
  const b = e.target.closest('[data-place]'); if (!b) return;
  const p = WZ.places[+b.dataset.place]; WZ.home = p;
  $('#wz-city').value = p.city; $('#wz-city-hits').innerHTML = '';
  const tz = $('#wz-tz'); if (p.tz && tz) { if (![...tz.options].some((o) => o.value === p.tz)) tz.add(new Option(p.tz.replace(/_/g, ' '), p.tz), 0); tz.value = p.tz; WZ.tz = p.tz; }
});
