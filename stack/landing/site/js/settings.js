// ---------- Settings: modules, menu and home, your tiles, every setting, security ----------
// Opened from the gear on Home. Changes are saved to the assistant (settings.json in its data folder) and apply the next time it starts,
// except the menu, home cards and tiles, which apply as soon as the page reloads.
const SET = { data: null, page: 'root', pin: '', note: '', restart: false };
try { SET.pin = sessionStorage.getItem('spin') || ''; } catch (e) {}
const setHome = () => $('#set-body');
const SET_TITLES = { profile: 'You', about: 'About', root: 'Settings', modules: 'Modules', layout: 'Menu and home', tiles: 'Your tiles', all: 'All settings', security: 'Security', health: 'Health check', apps: 'Apps', news: 'News and briefing', schedule: 'Schedule', update: 'Updates' };
const SET_GROUPS = { owner: 'You', timezone: 'Time', home: 'Home', dashboard_url: 'Links', world_clock: 'World clock', schedule: 'Schedule', models: 'AI models',
  features: 'Features', support: 'Support', therapy: 'Journal', ollama: 'AI engine' };
const SET_LABELS = { 'owner.name': 'Your name', timezone: 'Timezone', 'home.city': 'Home city', 'home.country': 'Country', 'home.lat': 'Latitude', 'home.lon': 'Longitude',
  'home.tz': 'Home timezone', dashboard_url: 'Dashboard link', world_clock: 'Cities on the world clock', 'schedule.briefing': 'Morning briefing', 'schedule.evening_plan': 'Evening plan',
  'schedule.news_at': 'News digests', 'models.chat': 'Chat model', 'models.embed': 'Understanding model', 'models.journal': 'Journal model', 'models.claude_journal': 'Claude journal model',
  'models.claude_news': 'Claude news model', 'features.therapy_recap': 'Weekly journal summary', 'support.therapist': 'Therapist name', 'support.helpline_name': 'Helpline name',
  'support.helpline_tel': 'Helpline number', 'therapy.calendar_words': 'Words that mark a therapy session in your calendar', 'ollama.url': 'Where the AI engine runs' };
const SET_KEYS = { flag: 'Flag (an emoji)', label: 'City name', tz: 'Time zone, like Europe/London' };
const HOME_CARDS = [['weather', 'Weather'], ['brief', 'Briefing button'], ['shortcuts', 'News and Planner buttons'], ['today', 'Your day'], ['clocks', 'World clock']];
const TAB_NAMES = { home: 'Home', journal: 'Journal', gym: 'Gym', sg: 'Health', server: 'Server and apps' };

async function setApi(path, body) {
  const r = await fetch('/api/bot' + path, { method: body ? 'POST' : 'GET', cache: 'no-store', headers: { 'Content-Type': 'application/json', 'X-Settings-Pin': SET.pin }, body: body ? JSON.stringify(body) : undefined });
  let j = {}; try { j = await r.json(); } catch (e) {}
  return { ok: r.ok, code: r.status, ...j };
}
const swHTML = (on, id, label, off) => `<button class="sw" role="switch" aria-checked="${!!on}" aria-label="${esc(label)}" data-sw="${esc(id)}"${off ? ' disabled' : ''}></button>`;
const SET_ICON = (d) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="${d}"/></svg>`;

function setTitle() {
  $('#set-title').textContent = SET_TITLES[SET.page];
  $('#set-back').textContent = SET.page === 'root' ? 'Done' : 'Back';
}
async function setLoad() {
  const r = await setApi('/settings');
  if (r.locked || r.code === 403 || r.code === 429) { SET.data = null; return r; }
  if (!r.ok) { SET.data = null; return r; }
  SET.data = r; return r;
}
function setLocked(r) {
  setHome().innerHTML = `<div class="snote"><b>${r.code === 429 ? 'Try again in a minute' : 'Enter your PIN'}</b><br>${esc(r.code === 429 ? r.error : SET.pin ? 'That PIN is not right.' : 'A PIN guards these settings.')}</div>
    <label class="sfield"><span>PIN</span><input id="set-pin" type="password" inputmode="numeric" autocomplete="off"></label>
    <button class="sbtn main" id="set-unlock">Unlock</button>`;
  $('#set-unlock').onclick = async () => { SET.pin = $('#set-pin').value.trim(); try { sessionStorage.setItem('spin', SET.pin); } catch (e) {} setRender(); };
}
async function setRender() {
  setTitle();
  const r = await setLoad();
  if (!SET.data) {
    if (r.locked || r.code === 403 || r.code === 429) return setLocked(r);
    setHome().innerHTML = `<div class="err">Settings can't be reached right now. Check that the assistant is running, then try again.</div>`; return;
  }
  const d = SET.data, body = setHome();
  const note = SET.note ? `<div class="snote">${esc(SET.note)}${SET.restart ? ' <b>Restart the assistant to apply.</b><button class="sbtn" id="set-restart">Restart now</button>' : ''}</div>` : '';
  if (SET.page === 'root') await setRootPage(body, d, note);
  else if (SET.page === 'profile') setProfilePage(body, note);
  else if (SET.page === 'about') setAboutPage(body);
  else if (SET.page === 'modules') {
    body.innerHTML = `<section class="card srows">${d.modules.map((m) => `<div class="srow"><span><b>${esc(m.title)}</b><small>${esc(m.why_off && !m.enabled ? m.why_off : m.description)}</small></span>${swHTML(m.enabled, m.name, m.title, m.unavailable)}</div>`).join('')}</section>` + note;
  } else if (SET.page === 'layout') setLayoutPage(body, note);
  else if (SET.page === 'tiles') setTilesPage(body, note);
  else if (SET.page === 'all') setAllPage(body, note);
  else if (SET.page === 'health') await setHealthPage(body);
  else if (SET.page === 'apps') await setAppsPage(body);
  else if (SET.page === 'update') await setUpdatePage(body);
  else if (SET.page === 'news') await setNewsPage(body, note);
  else if (SET.page === 'schedule') await setSchedPage(body, note);
  else if (SET.page === 'security') {
    body.innerHTML = d.pin
      ? `<div class="snote"><b>A PIN guards these settings.</b> Anyone who opens the dashboard needs it to change them.</div><button class="sbtn danger" id="set-pin-off">Turn the PIN off</button>`
      : `<div class="snote">A PIN is optional. If you set one, changing settings needs it. Use 4 to 12 digits.</div>
         <label class="sfield"><span>New PIN</span><input id="set-newpin" type="password" inputmode="numeric" autocomplete="off"></label><div class="sfield bad"><div class="why" id="set-pin-why"></div></div>
         <button class="sbtn main" id="set-pin-on">Turn the PIN on</button>`;
  }
}
// ---------- The first page: four groups, each row saying how it is set right now ----------
const SITE = 'https://theappfoundry.co/homelab';
async function setRootPage(body, d, note) {
  const [st, cat, sch, nw, acc, upd] = await Promise.all(['/setup', '/server/catalog', '/schedule', '/news/setup', '/setup/access', '/server/update'].map((p) => setApi(p).catch(() => ({}))));
  if (SET.page !== 'root') return;
  SET.setup = st.ok ? st : null;
  const f = (p) => (d.fields.find((x) => x.path === p) || {}).value;
  const on = d.modules.filter((m) => m.enabled).length;
  const added = cat.ok ? cat.apps.filter((a) => a.state && a.state !== 'missing') : [];
  const jobs = sch.ok ? sch.jobs : [];
  const ai = { claude: 'Claude', openai: 'OpenAI', ollama: 'local AI' }[nw.ok && nw.using?.provider] || 'plain headlines';
  const you = [f('owner.name') || 'No name yet', f('home.city'), (f('timezone') || '').replace(/_/g, ' ')].filter(Boolean).join(' \u2022 ');
  const engine = f('ollama.url') ? `${f('models.chat') || 'No chat model'} \u2022 ${/host\.docker\.internal|localhost|127\.0\.0\.1|\/\/ollama[:/]/.test(f('ollama.url')) ? 'on this machine' : 'on another machine'}` : 'Not set up';
  const access = { lan: 'Home network, with a PIN', local: 'Only this machine', tailscale: 'Tailscale' }[acc.mode] || 'Only this machine';
  const row = (go, t, s, attr) => `<button class="srow sgo" ${attr || `data-go="${go}"`}><span><b>${t}</b><small>${esc(s)}</small></span><span class="chev">${CHEV}</span></button>`;
  const group = (t, rows) => `<div class="sgroup">${t}</div><section class="card srows">${rows.join('')}</section>`;
  body.innerHTML = note
    + group('You', [row('profile', 'Name, city and time zone', you), row('security', 'PIN', d.pin ? 'On, changing settings needs it' : 'Off')])
    + group('Features', [row('modules', 'Modules', `${on} of ${d.modules.length} on`), row('news', 'News and briefing', `${nw.ok ? plural(nw.chosen.length, 'topic') : 'Topics'} \u2022 ${ai}${nw.ok && nw.briefing ? ' \u2022 at ' + nw.briefing : ''}`),
      row('schedule', 'Schedule', jobs.length ? `${jobs.filter((j) => j.on).length} of ${jobs.length} jobs on` : 'What runs on its own and when'), row('layout', 'Menu and home', 'Order and hide'), row('tiles', 'Your tiles', 'Links to your apps and tools')])
    + group('Apps and AI', [row('apps', 'Apps', cat.ok ? (added.length ? `${added.length} added: ${added.slice(0, 3).map((a) => a.title.split(' (')[0]).join(', ')}${added.length > 3 ? '\u2026' : ''}` : 'Nothing extra yet') : 'Add or remove apps'),
      row('', 'AI engine', engine, 'data-wiz-step="ai"'), row('', 'Telegram', st.ok ? (st.telegram.connected ? 'Connected' : 'Not connected') : 'Chat from your phone', 'data-wiz-step="telegram"')])
    + group('System', [row('', 'Who can open the dashboard', access, 'data-wiz-step="access"'), row('health', 'Health check', 'What works and what to fix'), row('all', 'All settings', 'Every value, for fine-tuning'),
      row('update', 'Updates', upd.ok ? (upd.state === 'updating' ? 'Updating now' : upd.available ? `Version ${upd.latest} is ready` : `Up to date, version ${upd.version}`) : 'Check for a newer version'), row('', 'Run setup again', 'The guided steps from the start', 'data-wiz'), row('about', 'About', st.version ? 'Version ' + st.version : 'Version, privacy and terms')])
    + `<button class="sbtn danger" id="set-reset">Reset everything to defaults</button>`;
}
function setProfilePage(body, note) {
  const st = SET.setup || {}, p = st.profile || {};
  if (!SET.prof) { SET.prof = true; WZ.name = p.name || ''; WZ.tz = p.timezone || wzBrowserZone(); WZ.home = null; }
  body.innerHTML = `<section class="card srows"><label class="sfield"><span>What should I call you?</span><input id="wz-name" autocomplete="given-name" maxlength="40" value="${esc(WZ.name)}"></label>
      <label class="sfield"><span>Your city, for the weather</span><input id="wz-city" autocomplete="off" data-1p-ignore data-lpignore="true" spellcheck="false" placeholder="Start typing, like Pune or Leeds" value="${esc(p.home || '')}"></label><div id="wz-city-hits" class="wz-hits"></div>
      ${wzTzField()}<div class="sfield bad"><div class="why" id="set-prof-why"></div></div></section>
    <button class="sbtn main" id="set-prof-save">Save</button>${note}`;
}
function setAboutPage(body) {
  const v = SET.setup?.version;
  const link = (path, t, s) => `<a class="srow sgo" href="${SITE}${path}" target="_blank" rel="noopener"><span><b>${t}</b><small>${s}</small></span><span class="chev">${CHEV}</span></a>`;
  body.innerHTML = `<section class="card srows"><div class="srow"><span><b>Homelab</b><small>Your own assistant, dashboard and apps, on your own machine.</small></span></div>
      <div class="srow"><span><b>Version</b><small>${esc(v || 'Unknown')}</small></span></div>
</section>
    <div class="sgroup">In your terminal</div><section class="card srows">${[['status', 'What is running and how healthy it is'], ['update', 'Get the newest version'], ['backup', 'Save a copy of your data'],
      ['logs', 'Recent log lines, when something is wrong'], ['uninstall', 'Remove it (lists everything first, keeps your data)']].map(([c, t]) => `<div class="srow scmd"><span><b>${t}</b>${cmdHTML(hlCmd(c))}</span></div>`).join('')}</section>
    ${HL_CLI.startsWith('bin/') ? `<div class="snote">Run these in the project folder. To type just <b>homelab</b> from any folder:${cmdHTML(hlCmd('path add'))}</div>` : ''}
    <section class="card srows">${link('', 'Website', 'theappfoundry.co/homelab')}${link('/privacy', 'Privacy', 'What stays on this machine, and what does not')}${link('/terms', 'Terms', 'The terms for using Homelab')}</section>
    <p class="sfoot">\u00a9 ${new Date().getFullYear()} TheAppFoundryCo</p>`;
}
// ---------- Updates: the newest release, and one button that runs the same safe update as the terminal ----------
let updPoll = null;
async function setUpdatePage(body) {
  clearTimeout(updPoll); updPoll = null;
  const r = await setApi('/server/update' + (SET.updFresh ? '?fresh=1' : ''));
  SET.updFresh = false;
  if (SET.page !== 'update') return;
  if (SET.updFrom && r.ok && r.version !== SET.updFrom) { location.reload(); return; }  // the new version is answering
  if (r.ok && r.state === 'updating' && !SET.updFrom) SET.updFrom = r.version;  // opened while one is running
  const busy = r.state === 'updating' || (SET.updFrom && !r.ok);  // while it restarts nothing answers for a moment, which is expected
  const log = r.ok && r.log && r.log.length ? `<div class="snote">${r.log.map(esc).join('<br>')}</div>` : '';
  const news = r.ok && /^https:\/\/github\.com\//.test(r.url || '') ? `<a class="srow sgo" href="${esc(r.url)}" target="_blank" rel="noopener"><span><b>What\u2019s new</b><small>Release notes for ${esc(r.latest)}</small></span><span class="chev">${CHEV}</span></a>` : '';
  let head, act = '';
  if (busy) head = ['warn', `Updating${r.to ? ' to ' + esc(r.to) : ''}\u2026`, 'Backing up, then rebuilding. This page reloads when it is done. If something fails, it goes back by itself.'];
  else if (!r.ok) head = ['off', 'Can\u2019t check right now', 'The assistant is not answering. Check that it is running, then try again.'];
  else if (r.state === 'failed') head = ['bad', 'The update did not finish', 'Nothing was lost. Your data and settings are as they were.'], act = `<button class="sbtn main" data-upd="go">Try again</button>`;
  else if (r.available) head = ['warn', `Version ${esc(r.latest)} is ready`, `You have ${esc(r.version)}. A backup is taken first, and it goes back by itself if anything fails.`],
    act = r.helper ? `<button class="sbtn main" data-upd="go">Update now</button>` : `<div class="snote"><b>Updating from here needs the host helper.</b> ${hlRunIn()} this once, then the button works. Or update from the terminal:${cmdHTML(hlCmd('agent install'))}${cmdHTML(hlCmd('update'))}</div>`;
  else if (r.latest) head = ['ok', 'You\u2019re up to date', `Version ${esc(r.version)}`];
  else head = ['off', 'Can\u2019t reach the release list', `You have ${esc(r.version)}. Check your connection, or run the update check in the terminal.`], act = cmdHTML(hlCmd('update --check'));
  body.innerHTML = `<section class="card srows"><div class="srow"><i class="sdot ${head[0]}" aria-hidden="true"></i><span><b>${head[1]}</b><small>${head[2]}</small></span></div>${r.available ? news : ''}</section>`
    + log + act + (busy ? '' : `<button class="sbtn" data-upd="check">Check now</button>`);
  if (busy) updPoll = setTimeout(() => SET.page === 'update' && setUpdatePage(setHome()), 4000);
}
async function updAct(what) {
  if (what === 'check') { SET.updFresh = true; return setUpdatePage(setHome()); }
  const cur = await setApi('/server/update'); SET.updFrom = cur.version || null;
  const r = await setApi('/server/update', {});
  if (!r.ok) { SET.updFrom = null; toast(r.msg || r.error || 'The update did not start.'); return setUpdatePage(setHome()); }
  setUpdatePage(setHome());
}
// ---------- Apps: the optional apps, what each one uses, and Add / Remove through the host helper ----------
let appsPoll = null, appsBusy = {};
const mbText = (mb) => mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb} MB`;
async function setAppsPage(body) {
  clearTimeout(appsPoll); appsPoll = null;
  const r = await setApi('/server/catalog');
  if (SET.page !== 'apps') return;
  if (!r.ok) { body.innerHTML = '<div class="err">The app list can\u2019t be reached right now. Check that the assistant is running, then try again.</div>'; return; }
  // a change is done when the app reaches the state it was asked for; until then the row says what is happening
  Object.keys(appsBusy).forEach((id) => { const a = r.apps.find((x) => x.id === id); if (!a || (appsBusy[id] === 'add' ? a.state === 'running' : a.state === 'missing')) delete appsBusy[id]; });
  const state = (a) => appsBusy[a.id] ? (appsBusy[a.id] === 'add' ? 'Adding\u2026 the first time downloads it' : 'Removing\u2026')
    : a.state === 'running' ? `Running${a.custom ? ' on port ' + a.port : ''}${a.memory_now_mb ? ' \u2022 using ' + mbText(a.memory_now_mb) : ''}` : a.state === 'stopped' ? 'Installed but stopped'
    : a.custom ? 'Saved, not running' : a.state === 'missing' ? `Not installed \u2022 about ${mbText(a.memory_mb)}` : `About ${mbText(a.memory_mb)}`;
  const dot = (a) => appsBusy[a.id] ? 'warn' : a.state === 'running' ? 'ok' : a.state === 'stopped' ? 'bad' : 'off';
  const btn = (a) => appsBusy[a.id] ? '' : a.custom && a.state !== 'running' && a.state !== 'stopped' ? `<span class="sacts"><button class="sact" data-app-add="${esc(a.id)}"${r.docker ? '' : ' disabled'}>Start</button><button class="sact" data-app-rm="${esc(a.id)}">Remove</button></span>`
    : a.state === 'missing' || a.state == null ? `<button class="sact" data-app-add="${esc(a.id)}"${r.docker ? '' : ' disabled'}>Add</button>`
    : `<button class="sact" data-app-rm="${esc(a.id)}">Remove</button>`;
  const rowA = (a) => `<div class="srow"><i class="sdot ${dot(a)}" aria-hidden="true"></i><span><b>${esc(a.title)}</b><small>${esc(a.what)}</small><small>${esc(state(a))}</small></span>${btn(a)}</div>`;
  const groups = [...new Set(r.apps.map((a) => a.group))];
  const used = [...r.core, ...r.apps].reduce((n, a) => n + (a.memory_now_mb || 0), 0);
  body.innerHTML = `<div class="snote"><b>The dashboard and the assistant always run.</b> Add the extras you want; you can remove them any time and their data is kept.${used ? ` Apps are using ${mbText(used)} of memory right now.` : ''}</div>`
    + (SET.appsFail ? `<div class="snote"><b>${esc(SET.appsFail.msg)}</b>${cmdsHTML(SET.appsFail.cmds)}</div>` : '')
    + (r.docker ? '' : `<div class="snote"><b>The Docker reader is not running,</b> so apps can\u2019t be listed. Start it:${cmdHTML(hlCmd('start'))}</div>`)
    + (r.helper || SET.appsFail ? '' : `<div class="snote"><b>Add and Remove need the host helper.</b> ${hlRunIn()} this once, and the buttons work from then on:${cmdHTML(hlCmd('agent install'))}</div>`)
    + (r.working && Object.keys(appsBusy).length ? `<div class="snote">Working: ${esc(r.working)}</div>` : '')
    + `<div class="sgroup">Always on</div><section class="card srows">${r.core.map((a) => `<div class="srow"><i class="sdot ${a.state === 'running' ? 'ok' : a.state ? 'bad' : 'off'}" aria-hidden="true"></i><span><b>${esc(a.title)}</b><small>${a.state === 'running' ? `Running${a.memory_now_mb ? ' \u2022 using ' + mbText(a.memory_now_mb) : ''}` : a.state ? 'Stopped' : 'Unknown'}</small></span></div>`).join('')}</section>`
    + groups.map((g) => `<div class="sgroup">${esc(g)}</div><section class="card srows">${r.apps.filter((a) => a.group === g).map(rowA).join('')}</section>`).join('')
    + customFormHTML(r.docker);
  const keep = SET.custom || {};
  CU_FIELDS.forEach((k) => { const f = $('#cu-' + k); if (!f) return; if (keep[k] != null) f.value = keep[k];
    f.oninput = f.onchange = () => { SET.custom = { ...(SET.custom || {}), [k]: f.value }; }; });  // what is typed stays when the list redraws
  if (Object.keys(appsBusy).length) appsPoll = setTimeout(() => SET.page === 'apps' && setAppsPage(setHome()), 3000);
}
// Your own app: any Docker image pinned to a version, one port, and an optional folder to keep. The server checks it; the host helper starts it.
const customFormHTML = (docker) => `<div class="sgroup">Add your own</div>
  <div class="snote">Any app that comes as a Docker image. It gets a tile on the Server page, and Remove keeps its saved data.</div>
  <label class="sfield"><span>Name</span><input id="cu-title" maxlength="30" placeholder="Media server" autocomplete="off"></label>
  <label class="sfield"><span>Image and version</span><input id="cu-image" placeholder="jellyfin/jellyfin:10.10.7" autocapitalize="off" autocorrect="off" spellcheck="false"><div class="hint">Pin a version (not latest), so it only changes when you change it.</div></label>
  <label class="sfield"><span>Port</span><input id="cu-port" inputmode="numeric" maxlength="5" placeholder="8096"><div class="hint">Where you open it, like ${esc(location.hostname || 'this machine')}:8096.</div></label>
  <label class="sfield"><span>Port inside the app (optional)</span><input id="cu-inside" inputmode="numeric" maxlength="5" placeholder="Same as above"><div class="hint">Only if the app's page says it listens on a different port.</div></label>
  <label class="sfield"><span>Folder to keep (optional)</span><input id="cu-keep" placeholder="/config" autocapitalize="off" autocorrect="off" spellcheck="false"><div class="hint">A folder inside the app that holds its settings and data, from the app's own instructions.</div></label>
  <label class="sfield"><span>Shows under</span><select id="cu-group"><option value="apps">Everyday apps</option><option value="tools">Tools</option></select></label>
  <div class="sfield bad"><div class="why" id="cu-why">${esc(SET.customWhy || '')}</div></div>
  <button class="sbtn main" id="cu-add"${docker ? '' : ' disabled'}>Add app</button>`;
const CU_FIELDS = ['title', 'image', 'port', 'inside', 'keep', 'group'];
async function customAdd() {
  const b = Object.fromEntries(CU_FIELDS.map((k) => [k, ($('#cu-' + k)?.value || '').trim()]));
  SET.custom = b; SET.customWhy = '';
  if (!b.title || !b.image || !b.port) { SET.customWhy = 'Fill in the name, image and port.'; $('#cu-why').textContent = SET.customWhy; return; }
  const btn = $('#cu-add'); btn.disabled = true; btn.textContent = 'Checking\u2026';
  const r = await setApi('/server/apps/custom', b);
  SET.appsFail = null;
  if (r.ok) { appsBusy[r.id] = 'add'; SET.custom = null; if (typeof loadInstalled === 'function') setTimeout(loadInstalled, 4000); }
  else if (r.saved) { SET.custom = null; SET.appsFail = { msg: r.msg, cmds: r.cmds }; }
  else SET.customWhy = r.msg || r.error || 'That did not work.';
  setAppsPage(setHome());
}
async function appsChange(action, id) {
  appsBusy[id] = action; setAppsPage(setHome());
  const r = await setApi('/server/apps/change', { action, id });
  SET.appsFail = null;
  if (r.ok && typeof loadInstalled === 'function') setTimeout(loadInstalled, 4000);  // the new tile shows once it is in the list
  if (!r.ok) { delete appsBusy[id]; if (r.cmds) SET.appsFail = { msg: r.msg, cmds: r.cmds }; else toast(r.msg || r.error || 'That did not work.'); setAppsPage(setHome()); }
}
// ---------- Schedule: every job that runs on its own, each with a switch and its time ----------
async function setSchedPage(body, note) {
  const r = await setApi('/schedule');
  if (!r.ok) { body.innerHTML = '<div class="err">The schedule can’t be reached right now.</div>'; return; }
  SET.sched = r.jobs;
  const row = (j) => `<div class="srow sch"><span><b>${esc(j.title)}</b><small>${esc(j.what)}</small>${j.every ? `<small>${esc(j.every)}</small>` : ''}${j.blocked && j.on ? `<small class="warnline">${esc(j.blocked)}</small>` : ''}
      ${j.time ? `<label class="sinline"${j.on ? '' : ' hidden'} data-sch-for="${j.id}">Time <input class="ntime" type="time" data-sch-time="${esc(j.time)}" value="${j.at24}"></label>` : ''}
      ${j.id === 'backup' ? `<div data-sch-for="backup"${j.on ? '' : ' hidden'}><label class="sfield"><span>Folder on this machine (empty: the backups folder in ~/.homelab)</span><input data-sch-text="night.backup_to" spellcheck="false" value="${esc(j.extra.backup_to)}" placeholder="~/.homelab/backups"></label>
        <label class="sfield"><span>How many to keep</span><input data-sch-num="night.backup_keep" type="number" min="1" max="60" value="${esc(j.extra.backup_keep)}"></label></div>` : ''}
      ${j.id === 'github' ? `<div data-sch-for="github"${j.on ? '' : ' hidden'}><label class="sfield"><span>Your private repository</span><input data-sch-text="night.github_repo" spellcheck="false" value="${esc(j.extra.github_repo)}" placeholder="git@github.com:you/homelab-settings.git"></label>
        <small>Make an empty private repository, then add this machine's SSH public key to it with write access (GitHub: the repository, Settings, Deploy keys). Nothing else is needed.</small></div>` : ''}
    </span>${swHTML(j.on, 'sch:' + j.id, j.title)}</div>`;
  const ids = (xs) => r.jobs.filter((j) => xs.includes(j.id));
  body.innerHTML = `<div class="snote">Turn off anything you don't want. Times are in your time zone. Changes apply after a restart.</div>
    <div class="sgroup">Every day</div><section class="card srows">${ids(['briefing', 'news', 'evening']).map(row).join('')}</section>
    <div class="sgroup">Journal</div><section class="card srows">${ids(['journal', 'insights', 'recap']).map(row).join('')}</section>
    <div class="sgroup">Weekly</div><section class="card srows">${ids(['weekly']).map(row).join('')}</section>
    <div class="sgroup">Safety copies</div><section class="card srows">${ids(['backup', 'github']).map(row).join('')}</section>
    <button class="sbtn main" id="sch-save">Save</button>${note}`;
}
async function schedSave() {
  const set = {};
  SET.sched.forEach((j) => { const sw = document.querySelector(`[data-sw="sch:${j.id}"]`); if (sw && (sw.getAttribute('aria-checked') === 'true') !== j.on) set[j.switch] = sw.getAttribute('aria-checked') === 'true'; });
  document.querySelectorAll('[data-sch-time]').forEach((i) => { const j = SET.sched.find((x) => x.time === i.dataset.schTime); if (i.value && i.value !== j.at24) set[i.dataset.schTime] = to12(i.value); });
  document.querySelectorAll('[data-sch-text]').forEach((i) => { set[i.dataset.schText] = i.value.trim(); });
  document.querySelectorAll('[data-sch-num]').forEach((i) => { if (i.value) set[i.dataset.schNum] = Math.max(1, Math.min(60, parseInt(i.value, 10) || 7)); });
  const r = await setApi('/schedule', { set });
  if (!r.ok) return toast(r.error || 'That did not save.');
  SET.note = 'Saved.'; SET.restart = true; setRender();
}
// ---------- News and briefing: when, which topics, your own feeds, and which AI writes it ----------
const to12 = (v) => { const [h, m] = v.split(':').map(Number); return `${h % 12 || 12}:${String(m).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`; };
const to24 = (t) => { const m = /^(\d{1,2}):(\d{2})\s*(AM|PM)$/i.exec(t || ''); if (!m) return ''; let h = +m[1] % 12; if (/pm/i.test(m[3])) h += 12; return `${String(h).padStart(2, '0')}:${m[2]}`; };
const NW_AI = [['auto', 'Automatic', 'Your Claude or OpenAI key if you added one, otherwise the AI on this machine, otherwise plain headlines'],
  ['claude', 'Claude', 'Needs your Anthropic API key'], ['openai', 'OpenAI', 'Needs your OpenAI API key'], ['ollama', 'The AI on this machine', 'Private and free, slower'],
  ['none', 'No AI', 'Plain headlines from your feeds, nothing summarised']];
async function setNewsPage(body, note) {
  if (!SET.news) { const r = await setApi('/news/setup'); if (!r.ok) { body.innerHTML = '<div class="err">News settings can’t be reached right now.</div>'; return; } SET.news = { d: r, draft: { topics: [...r.chosen], feeds: [...r.feeds], ai: r.ai, model: r.model, briefing: r.briefing, news_at: r.news_at[0] } }; }
  const { d, draft: w } = SET.news, nw = SET.news;
  const using = d.using.provider ? `Right now the news is written by ${{ claude: 'Claude', openai: 'OpenAI', ollama: 'the AI on this machine' }[d.using.provider]}${d.using.model ? ` (${d.using.model})` : ''}.` : 'Right now there is no AI, so the brief shows plain headlines.';
  const keyBox = (p) => `<label class="sfield${nw.keyWhy ? ' bad' : ''}"><span>${p === 'claude' ? 'Anthropic' : 'OpenAI'} API key ${d.keys[p] ? '• saved' : ''}${d.keys[p] ? `<button data-nw="key-rm" data-p="${p}">Remove</button>` : ''}</span>
      <input id="nw-key" type="password" autocomplete="off" spellcheck="false" placeholder="${d.keys[p] ? 'Paste a new key to replace it' : 'Paste your key'}"></label>${nw.keyWhy ? `<div class="sfield bad"><div class="why">${esc(nw.keyWhy)}</div></div>` : ''}
    <button class="sbtn" data-nw="key" data-p="${p}">Check and save the key</button>`;
  const models = nw.models?.length ? `<label class="sfield"><span>Model</span><select id="nw-model">${['', ...nw.models].map((m) => `<option value="${esc(m)}"${m === w.model ? ' selected' : ''}>${m ? esc(m) : `Suggested${nw.suggested ? ` (${esc(nw.suggested)})` : ''}`}</option>`).join('')}</select></label>` : '';
  body.innerHTML = `<div class="snote">${esc(using)} Changes apply after a restart.</div>
    <div class="sgroup">When</div><section class="card srows">
      <div class="srow"><span><b>Morning brief</b><small>Weather, your day and the news, on Telegram and Home</small></span><input class="ntime" type="time" id="nw-brief" value="${to24(w.briefing)}"></div>
      <div class="srow"><span><b>News ready by</b><small>The news is written before the brief</small></span><input class="ntime" type="time" id="nw-at" value="${to24(w.news_at)}"></div></section>
    <div class="sgroup">Topics in your brief</div><section class="card srows">${d.topics.map((t) => `<div class="srow"><span><b>${esc(t.name)}</b><small>${esc(t.sources.join(', '))}</small></span>${swHTML(w.topics.includes(t.key), 'nwt:' + t.key, t.name)}</div>`).join('')}</section>
    <div class="sgroup">Your own feeds</div><section class="card srows">${w.feeds.map((f, i) => `<div class="srow"><span><b>${esc(f.name || f.url)}</b><small>${esc(f.topic)} • ${esc(f.url)}</small></span><button class="sact" data-nw="feed-rm" data-i="${i}">Remove</button></div>`).join('')}
      <div class="srow"><span><label class="sfield"><span>Feed address (RSS or Atom)</span><input id="nw-feed" inputmode="url" spellcheck="false" placeholder="https://example.com/feed.xml" value="${esc(nw.feedUrl || '')}"></label>
        <label class="sfield"><span>Section name in the brief</span><input id="nw-ftopic" maxlength="30" placeholder="For example: Cycling" value="${esc(nw.feedTopic || '')}"></label>
        ${nw.feedWhy ? `<div class="sfield bad"><div class="why">${esc(nw.feedWhy)}</div></div>` : ''}<button class="sbtn" data-nw="feed-add">Check and add the feed</button></span></div></section>
    <div class="sgroup">Who writes the news</div><section class="card srows">${NW_AI.map(([k, t, sub]) => `<div class="srow"><span><b>${t}</b><small>${sub}${k === 'ollama' && !d.local ? ' • not running now' : ''}${(k === 'claude' || k === 'openai') && d.keys[k] ? ' • key saved' : ''}</small></span><button class="sw" role="radio" aria-checked="${w.ai === k}" aria-label="${t}" data-nw="ai" data-k="${k}"></button></div>`).join('')}</section>
    ${w.ai === 'claude' || w.ai === 'openai' ? keyBox(w.ai) : ''}${models}
    <button class="sbtn main" data-nw="save">Save</button>${note}`;
  if ((w.ai === 'claude' || w.ai === 'openai' || w.ai === 'ollama') && !nw.models && !nw.loading) {  // fill the model list for the chosen provider
    nw.loading = true; const r = await setApi('/news/models?provider=' + w.ai); nw.loading = false;
    if (r.ok) { nw.models = r.models; nw.suggested = r.suggested; if (SET.page === 'news') setNewsPage(setHome(), ''); }
  }
}
function nwKeep() {  // what is typed stays when the page redraws
  const nw = SET.news, w = nw.draft;
  const b = $('#nw-brief')?.value, a = $('#nw-at')?.value; if (b) w.briefing = to12(b); if (a) w.news_at = to12(a);
  nw.feedUrl = $('#nw-feed')?.value || ''; nw.feedTopic = $('#nw-ftopic')?.value || ''; if ($('#nw-model')) w.model = $('#nw-model').value;
}
async function newsAct(t) {
  const nw = SET.news, w = nw.draft, act = t.dataset.nw; nwKeep();
  if (act === 'ai') { w.ai = t.dataset.k; w.model = ''; nw.models = null; nw.keyWhy = ''; }
  else if (act === 'feed-rm') w.feeds.splice(+t.dataset.i, 1);
  else if (act === 'feed-add') {
    t.disabled = true; const r = await setApi('/news/feed/check', { url: nw.feedUrl.trim() }); t.disabled = false;
    if (!r.ok) nw.feedWhy = r.error || 'That feed did not work.';
    else { w.feeds.push({ name: r.name, url: nw.feedUrl.trim(), topic: nw.feedTopic.trim() || 'My feeds' }); nw.feedUrl = nw.feedTopic = nw.feedWhy = ''; }
  } else if (act === 'key' || act === 'key-rm') {
    t.disabled = true; const r = await setApi('/news/key', { provider: t.dataset.p, key: act === 'key' ? ($('#nw-key')?.value || '').trim() : '' }); t.disabled = false;
    if (!r.ok) nw.keyWhy = r.error || 'That key did not save.';
    else { nw.keyWhy = ''; nw.d.keys[t.dataset.p] = act === 'key'; nw.models = r.models; nw.suggested = r.suggested; }
  } else if (act === 'save') {
    const r = await setApi('/news/setup', { topics: w.topics, feeds: w.feeds, ai: w.ai, model: w.model, briefing: w.briefing, news_at: [w.news_at] });
    if (!r.ok) return toast(r.error || 'That did not save.');
    SET.note = 'Saved.'; SET.restart = true; SET.news = null; return setRender();
  }
  setNewsPage(setHome(), '');
}
async function setHealthPage(body) {
  const r = await setApi('/doctor');
  if (!r.ok) { body.innerHTML = `<div class="err">The health check can't be reached right now. Check that the assistant is running, then try again.</div>`; return; }
  const dot = (k) => `<i class="sdot ${k}" aria-hidden="true"></i>`;
  const row = (k, t, lines) => `<div class="srow">${dot(k)}<span><b>${esc(t)}</b>${lines.map((l) => `<small>${esc(l)}</small>`).join('')}</span></div>`;
  const svc = r.capabilities.map((c) => row(c.ok ? 'ok' : c.off ? 'off' : 'warn', c.title, c.ok ? ['Working'] : c.off ? [c.message] : [c.reason || 'Not available', 'Fix: ' + c.fix]));
  const mod = r.modules.map((m) => row({ on: 'ok', degraded: 'warn', failed: 'bad' }[m.state] || 'off', m.title,
    m.state === 'on' ? ['Working'] : [m.why, ...m.degraded.map((d) => `Limited without ${d.feature}. Fix: ${d.fix}`)].filter(Boolean)));
  const bad = (r.config || []).map((p) => row('bad', 'config.yaml', [p]));
  body.innerHTML = `<div class="snote"><b>${r.ok ? 'Nothing is broken.' : 'Something is broken.'}</b> ${r.ok ? 'Features marked amber work, but with less.' : 'See the red items.'}</div>
    <div class="sgroup">Services</div><section class="card srows">${svc.join('')}</section><div class="sgroup">Modules</div><section class="card srows">${mod.join('')}</section>`
    + (bad.length ? `<div class="sgroup">config.yaml</div><section class="card srows">${bad.join('')}</section>` : '');
}
const setTabs = () => [...document.querySelectorAll('.tabs .tab')].map((b) => b.dataset.tab);
function setLayoutPage(body, note) {
  const L = SET.layout || (SET.layout = { tabs: [...setTabs()], hidden: new Set(CFG.layout?.tabs_hidden || []), home: new Set(CFG.layout?.home_hidden || []) });
  const order = [...(CFG.layout?.tabs || []).filter((t) => setTabs().includes(t)), ...setTabs().filter((t) => !(CFG.layout?.tabs || []).includes(t))];
  if (!SET.layoutInit) { L.tabs = order; SET.layoutInit = true; }
  body.innerHTML = `<div class="sgroup">Bottom menu</div><section class="card srows">${L.tabs.map((t, i) => `<div class="srow"><span><b>${TAB_NAMES[t] || esc(t)}</b></span>
      <button class="mini" data-up="${i}" aria-label="Move up" ${i < 2 ? 'disabled' : ''}>${SET_ICON('M6 15l6-6 6 6')}</button><button class="mini" data-down="${i}" aria-label="Move down" ${i === L.tabs.length - 1 || t === 'home' ? 'disabled' : ''}>${SET_ICON('M6 9l6 6 6-6')}</button>
      ${t === 'home' ? '<span style="flex:none;width:var(--sw-w)"></span>' : swHTML(!L.hidden.has(t), 'tab:' + t, TAB_NAMES[t] || t)}</div>`).join('')}</section>
    <div class="sgroup">Home cards</div><section class="card srows">${HOME_CARDS.map(([id, t]) => `<div class="srow"><span><b>${t}</b></span>${swHTML(!L.home.has(id), 'card:' + id, t)}</div>`).join('')}</section>
    <button class="sbtn main" id="set-layout-save">Save menu and home</button>${note}`;
}
function setTilesPage(body, note) {
  const T = SET.tiles || (SET.tiles = { hidden: new Set(CFG.layout?.tiles_hidden || []), own: (CFG.layout?.tiles || []).map((t) => ({ ...t })) });
  const builtin = [...APPS, ...TOOLS];
  body.innerHTML = `<div class="sgroup">Built in</div><section class="card srows">${builtin.map((a) => `<div class="srow"><span><b>${esc(a.name)}</b><small>${esc(a.sub)}</small></span>${swHTML(!T.hidden.has(a.name), 'tile:' + a.name, a.name)}</div>`).join('')}</section>
    <div class="sgroup">Your own</div><section class="card srows">${T.own.length ? T.own.map((t, i) => `<div class="srow"><span><b>${esc(t.name)}</b><small>${esc(t.url)} (${t.group === 'tools' ? 'Tools' : 'Everyday apps'})</small></span><button class="mini" data-del-tile="${i}" aria-label="Delete ${esc(t.name)}">${SET_ICON('M6 6l12 12M18 6 6 18')}</button></div>`).join('') : '<div class="empty">Nothing yet. Add a link below.</div>'}</section>
    <label class="sfield"><span>Name</span><input id="tile-name" maxlength="30" placeholder="Photos"></label>
    <label class="sfield"><span>Link</span><input id="tile-url" inputmode="url" placeholder="https://photos.example.com"></label>
    <label class="sfield"><span>Shows under</span><select id="tile-group"><option value="apps">Everyday apps</option><option value="tools">Tools</option></select></label>
    <div class="sfield bad"><div class="why" id="tile-why"></div></div>
    <button class="sbtn" id="tile-add">Add tile</button><button class="sbtn main" id="tiles-save">Save tiles</button>${note}`;
}
function setField(f) {
  const id = 'f:' + f.path, label = setLabel(f.path), ex = f.hint && ['time', 'timezone'].includes(f.kind) ? `<small class="hint">For example ${esc(f.hint)}</small>` : '';
  const reset = f.changed ? `<button type="button" data-reset="${esc(f.path)}">Reset</button>` : '';
  if (f.kind === 'switch') return `<div class="srow"><span><b>${esc(label)}</b></span>${swHTML(f.value, id, label)}</div>`;
  if (f.kind === 'list' && Array.isArray(f.items)) {  // world clocks: one row per city
    const rows = (f.value || []).map((c, i) => `<div class="srow2x" data-row="${i}">${f.items.map((k) => `<input data-key="${k.key}" value="${esc(c[k.key] ?? '')}" placeholder="${esc(SET_KEYS[k.key] || k.key)}" aria-label="${esc(SET_KEYS[k.key] || k.key)}">`).join('')}</div>`).join('');
    return `<div class="sfield" data-list="${esc(f.path)}" data-path="${esc(f.path)}"><span>${esc(label)}${reset}</span><div class="rows">${rows}</div><div class="why" hidden></div><button type="button" class="sbtn" data-add-row="${esc(f.path)}">Add a city</button></div>`;
  }
  const val = Array.isArray(f.value) ? f.value.join(', ') : (f.value ?? '');
  const hint = f.kind === 'list' ? '<small class="hint">Separate with commas</small>' : ex;
  return `<label class="sfield" data-path="${esc(f.path)}"><span>${esc(label)}${reset}</span><input id="${esc(id)}" data-kind="${f.kind}" value="${esc(val)}" placeholder="${esc(Array.isArray(f.default) ? f.default.join(', ') : (f.default ?? ''))}">${hint}<div class="why" hidden></div></label>`;
}
// set on their own pages (You, Schedule, News), so All settings leaves them out instead of showing them twice
const SET_OWN_PAGE = /^(owner\.|timezone$|home\.|schedule\.|night\.|news\.|features\.therapy_recap$)/;
const setLabel = (p) => SET_LABELS[p] || (p.split('.').pop().replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase()));
function setAllPage(body, note) {
  let last = '', out = '<div class="snote">Your name and city, the schedule and the news have their own pages in Settings. These are the rest.</div>';
  for (const f of SET.data.fields.filter((x) => !SET_OWN_PAGE.test(x.path))) {
    const g = SET_GROUPS[f.path.split('.')[0]] || 'Other';
    if (g !== last) { out += `<div class="sgroup">${esc(g)}</div>`; last = g; }
    out += setField(f);
  }
  body.innerHTML = out + `<button class="sbtn main" id="set-all-save">Save settings</button>${note}`;
}
// the value a form field holds, in the shape the assistant expects
function setRead(f) {
  const kind = f.kind;
  if (kind === 'switch') return document.querySelector(`[data-sw="f:${f.path}"]`).getAttribute('aria-checked') === 'true';
  if (kind === 'list' && Array.isArray(f.items)) return [...document.querySelectorAll(`[data-list="${f.path}"] [data-row]`)].map((r) => Object.fromEntries([...r.querySelectorAll('input')].map((i) => [i.dataset.key, i.value.trim()]))).filter((c) => Object.values(c).some(Boolean));
  const v = document.getElementById('f:' + f.path).value.trim();
  if (kind === 'list') return v ? v.split(',').map((s) => s.trim()).filter(Boolean) : [];
  if (kind === 'number') return v === '' ? null : Number(v);
  if (kind === 'whole number') return v === '' ? null : Number(v);
  return v;
}
function setProblems(problems, scope) {
  document.querySelectorAll('[data-path]').forEach((el) => { el.classList.remove('bad'); const w = el.querySelector('.why'); if (w) w.hidden = true; });
  let first = null;
  for (const p of problems) {
    const el = [...document.querySelectorAll('[data-path]')].find((e) => p.startsWith(e.dataset.path));
    if (!el) continue;
    el.classList.add('bad'); const w = el.querySelector('.why'); w.textContent = p; w.hidden = false; first = first || el;
  }
  if (first) first.scrollIntoView({ block: 'center', behavior: 'smooth' });
  return !!first;
}
async function setSave(changes, done) {
  const r = await setApi('/settings', { set: changes });
  if (r.ok) {
    const live = Object.keys(changes).every((k) => k.startsWith('dashboard.'));  // menu, home cards and tiles apply now; everything else at the next start
    SET.note = live ? 'Saved. The page is updated.' : 'Saved.'; SET.restart = !live;
    if (live) { try { CFG.layout = (await getJSON('/api/bot/config')).layout || {}; } catch (e) {} applyLayout(); }
    SET.layout = SET.tiles = null; SET.layoutInit = false; if (done) done(); return setRender();
  }
  if (r.locked || r.code === 403) return setRender();
  const shown = r.problems && setProblems(r.problems);
  if (!shown) toast(r.error || (r.problems || ['That did not save.']).join(' '));
}
function toast(msg) { const t = document.createElement('div'); t.className = 'toast bad'; t.textContent = msg; setHome().prepend(t); setTimeout(() => t.remove(), 6000); }

function openSettings() { SET.news = null; SET.page = 'root'; SET.note = ''; SET.restart = false; SET.layout = SET.tiles = null; SET.layoutInit = false; $('#setp').hidden = false; document.body.style.overflow = 'hidden'; $('#setp .panel-body').scrollTop = 0; setRender(); }
function closeSettings() { $('#setp').hidden = true; document.body.style.overflow = ''; }
$('#settings-open').onclick = openSettings;
$('#set-back').onclick = () => { SET.news = null; SET.prof = false; if (SET.page === 'root') closeSettings(); else { SET.page = 'root'; SET.layout = SET.tiles = null; SET.layoutInit = false; $('#setp .panel-body').scrollTop = 0; setRender(); } };

$('#set-body').addEventListener('click', async (e) => {
  const t = e.target.closest('button'); if (!t) return;
  if (t.dataset.upd) return updAct(t.dataset.upd);
  if (t.dataset.appAdd) return appsChange('add', t.dataset.appAdd);
  if (t.dataset.appRm) { if (await confirmSheet({ title: 'Remove this app?', text: 'Its data is kept, so adding it again picks up where it was.', ok: 'Remove' })) appsChange('remove', t.dataset.appRm); return; }
  if (t.dataset.nw) return newsAct(t);
  if (t.id === 'sch-save') return schedSave();
  if (t.id === 'set-prof-save') {
    WZ.name = ($('#wz-name')?.value || '').trim(); WZ.tz = $('#wz-tz')?.value || WZ.tz;
    const r = await setApi('/setup/profile', { name: WZ.name, timezone: WZ.tz, home: WZ.home || undefined });
    if (!r.ok) { $('#set-prof-why').textContent = r.error || (r.problems || []).join(' ') || 'That did not save.'; return; }
    SET.prof = false; SET.page = 'root'; SET.note = 'Saved.'; SET.restart = true; return setRender();
  }
  if (t.dataset.go) { SET.page = t.dataset.go; SET.note = ''; SET.restart = false; $('#setp .panel-body').scrollTop = 0; return setRender(); }
  if (t.dataset.sw) {
    const id = t.dataset.sw, on = t.getAttribute('aria-checked') !== 'true';
    if (id.startsWith('sch:')) { t.setAttribute('aria-checked', String(on)); document.querySelectorAll(`[data-sch-for="${id.slice(4)}"]`).forEach((el) => { el.hidden = !on; }); return; }
    if (id.startsWith('nwt:')) { nwKeep(); const k = id.slice(4), ts = SET.news.draft.topics; if (on) ts.push(k); else ts.splice(ts.indexOf(k), 1); t.setAttribute('aria-checked', String(on)); return; }
    if (id.startsWith('tab:')) { on ? SET.layout.hidden.delete(id.slice(4)) : SET.layout.hidden.add(id.slice(4)); }
    else if (id.startsWith('card:')) { on ? SET.layout.home.delete(id.slice(5)) : SET.layout.home.add(id.slice(5)); }
    else if (id.startsWith('tile:')) { on ? SET.tiles.hidden.delete(id.slice(5)) : SET.tiles.hidden.add(id.slice(5)); }
    t.setAttribute('aria-checked', String(on));
    if (SET.page === 'modules') { const r = await setApi('/settings', { set: { ['modules.' + id]: on } }); if (r.ok) { SET.note = 'Saved.'; SET.restart = true; setRender(); } else { t.setAttribute('aria-checked', String(!on)); toast(r.error || 'That did not save.'); } }
    return;
  }
  if (t.dataset.up != null || t.dataset.down != null) {
    const i = +(t.dataset.up ?? t.dataset.down), j = t.dataset.up != null ? i - 1 : i + 1, a = SET.layout.tabs;
    if (a[j] && a[j] !== 'home' && a[i] !== 'home') { [a[i], a[j]] = [a[j], a[i]]; setLayoutPage(setHome(), ''); }
    return;
  }
  if (t.id === 'set-layout-save') return setSave({ 'dashboard.tabs': SET.layout.tabs.filter((x) => x !== 'home'), 'dashboard.tabs_hidden': [...SET.layout.hidden], 'dashboard.home_hidden': [...SET.layout.home] });
  if (t.dataset.delTile != null) { SET.tiles.own.splice(+t.dataset.delTile, 1); return setTilesPage(setHome(), ''); }
  if (t.id === 'cu-add') return customAdd();
  if (t.id === 'tile-add') {
    const name = $('#tile-name').value.trim(), url = $('#tile-url').value.trim(), why = $('#tile-why');
    if (!name) { why.textContent = 'Give the tile a name.'; return; }
    if (!/^https?:\/\//i.test(url)) { why.textContent = 'The link should start with http:// or https://.'; return; }
    SET.tiles.own.push({ name, url, sub: '', icon: '', group: $('#tile-group').value }); return setTilesPage(setHome(), '');
  }
  if (t.id === 'tiles-save') return setSave({ 'dashboard.tiles': SET.tiles.own, 'dashboard.tiles_hidden': [...SET.tiles.hidden] });
  if (t.dataset.addRow) { const box = document.querySelector(`[data-list="${t.dataset.addRow}"] .rows`), f = SET.data.fields.find((x) => x.path === t.dataset.addRow);
    box.insertAdjacentHTML('beforeend', `<div class="srow2x" data-row="${box.children.length}">${f.items.map((k) => `<input data-key="${k.key}" placeholder="${esc(SET_KEYS[k.key] || k.key)}" aria-label="${esc(SET_KEYS[k.key] || k.key)}">`).join('')}</div>`); return; }
  if (t.dataset.reset) { await setApi('/settings/reset', { path: t.dataset.reset }); SET.note = 'Back to the default.'; SET.restart = true; return setRender(); }
  if (t.id === 'set-all-save') {
    const changes = {}; for (const f of SET.data.fields.filter((x) => !SET_OWN_PAGE.test(x.path))) { const v = setRead(f); if (JSON.stringify(v) !== JSON.stringify(f.value ?? (f.kind === 'list' ? [] : ''))) if (v !== null) changes[f.path] = v; }
    if (!Object.keys(changes).length) { toast('Nothing changed.'); return; }
    return setSave(changes);
  }
  if (t.id === 'set-reset' && await confirmSheet({ title: 'Reset everything?', text: 'All settings made here go back to what config.yaml says. Your data is not touched.', ok: 'Reset', danger: true })) {
    await setApi('/settings/reset', {}); SET.note = 'Everything is back to the defaults.'; SET.restart = true; CFG.layout = {}; applyLayout(); return setRender();
  }
  if (t.id === 'set-restart' && await confirmSheet({ title: 'Restart the assistant?', text: 'It is back in about a minute. Reminders and alerts pause meanwhile.', ok: 'Restart' })) {
    const r = await fetch('/api/bot/server/restart', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ id: 'telegram-bot' }) }).then((x) => x.json()).catch(() => ({}));
    SET.note = r.ok === false ? (r.error || 'That did not work.') : 'Restarting. Reload this page in a minute.'; return setRender();
  }
  if (t.id === 'set-pin-on') { const r = await setApi('/settings/pin', { pin: $('#set-newpin').value.trim() }); if (r.ok) { SET.pin = $('#set-newpin').value.trim(); try { sessionStorage.setItem('spin', SET.pin); } catch (e) {} SET.page = 'root'; return setRender(); } $('#set-pin-why').textContent = r.error || 'That did not save.'; return; }
  if (t.id === 'set-pin-off') { const r = await setApi('/settings/pin', { pin: '' }); if (r.ok) { SET.pin = ''; try { sessionStorage.removeItem('spin'); } catch (e) {} SET.page = 'root'; return setRender(); } toast(r.error || 'That did not work.'); }
});

// ---------- Layout the way you set it: bottom menu, home cards, tiles ----------
function applyLayout() {
  const L = CFG.layout || {};
  const nav = document.querySelector('.tabs .in'), btns = [...nav.querySelectorAll('.tab')];
  (L.tabs || []).forEach((id) => { const b = btns.find((x) => x.dataset.tab === id); if (b) nav.appendChild(b); });
  (L.tabs_hidden || []).forEach((id) => { const b = btns.find((x) => x.dataset.tab === id); if (b && id !== 'home') b.hidden = true; });
  document.querySelectorAll('[data-card]').forEach((el) => { el.hidden = (L.home_hidden || []).includes(el.dataset.card); });
  renderTiles(L);
}

// ---------- Needs cards: a feature that cannot work yet says what to fix, instead of an error ----------
async function showNeeds() {
  let list = []; try { list = (await getJSON('/api/bot/capabilities')).capabilities || []; } catch (e) { return; }
  let used = {}; try { ((await getJSON('/api/bot/modules')).modules || []).forEach((m) => (m.degraded || []).forEach((d) => (used[d.capability] = used[d.capability] || []).push(m.title))); } catch (e) {}
  let off = []; try { off = JSON.parse(localStorage.getItem('needs-off') || '[]'); } catch (e) {}
  const need = list.filter((c) => !c.ok && !c.off && !off.includes(c.name));  // off = left out on purpose (an app not chosen, a link not added), not broken
  const box = $('#needs'); if (!box) return;
  const plain = (m) => [...new Set(String(m).replace(/\s*\([^)]*Errno[^)]*\)/g, '').split(/(?<=[.!?])\s+/))].join(' ');  // no raw error codes, no repeated sentence
  box.innerHTML = need.length ? `<section class="needs"><div><b>${need.length === 1 ? 'A feature needs a fix' : 'Some features need a fix'}</b>
    ${need.map((c) => `<small><strong>${esc(c.title)}:</strong> ${esc(plain(c.message))}${used[c.name] ? ` (affects ${esc(used[c.name].join(', '))})` : ''}</small>`).join('')}
    <div class="acts2"><button id="needs-hide">Not now</button></div></div></section>` : '';
  const hide = $('#needs-hide');
  if (hide) hide.onclick = () => { need.forEach((c) => off.push(c.name)); try { localStorage.setItem('needs-off', JSON.stringify(off)); } catch (e) {} box.innerHTML = ''; };
}
