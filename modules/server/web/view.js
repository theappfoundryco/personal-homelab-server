// ---------- Server status ----------
const prom = async (q) => (await getJSON('/api/prom/query?query=' + encodeURIComponent(q))).data.result;
const NICE = { 'uptime-kuma': 'Website monitor', 'open-webui': 'AI chat', ollama: 'AI engine', n8n: 'Automations',
  grafana: 'Charts', searxng: 'Search', adguard: 'Ad blocker', 'telegram-bot': 'Telegram assistant', whisper: 'Voice to text' };
// running and installed stay null when the Docker reader is not installed: the app dots and counts then show nothing instead of guessing
let running = null, installed = null, rebooting = false;
async function dailyStats() { try { const d = await getJSON('/api/daily.json'); return Date.now() / 1000 - d.generated < 3600 ? d : null; } catch { return null; } }
async function status() {
  const [s, d] = await Promise.all([getJSON('/api/bot/server/status').catch(() => null), dailyStats()]);
  installed = s?.apps ? s.apps.map((a) => a.id) : null;
  running = s?.apps ? s.apps.filter((a) => a.state === 'running').map((a) => a.id) : null;
  paintApps();
  const el = $('#status'), set = (cls, title, sub) => { el.querySelector('.dot').className = 'dot ' + cls; el.className = 'sysline ' + cls; el.querySelector('span').textContent = [title, sub].filter(Boolean).join(' • '); };
  if (!s) { statInfo = { cls: 'bad', title: "Can't reach your assistant", sub: 'It may be restarting', groups: [] }; set('bad', "Can't reach your assistant"); return renderStat(); }
  const apps = (s.apps || []).filter((a) => a.state !== 'running').map((a) => `${NICE[a.id] || a.name} is stopped`);
  const down = (d?.sites || []).filter((x) => !x.up_now).map((x) => `${x.name} website is down`);
  const disk = [...(d?.ssd?.issues || [])], p = [...down, ...apps, ...disk];
  const sites = d?.sites?.length ? `${d.sites.filter((x) => x.up_now).length} of ${d.sites.length} websites online` : '';
  // nothing wrong, but nothing watching either: say so in a neutral colour instead of a false all clear or a false alarm
  const off = !p.length && !s.monitoring && !s.apps;
  const cls = off ? 'off' : !p.length ? 'ok' : p.length > 2 ? 'bad' : 'warn';
  const title = off ? 'Monitoring is off' : !p.length ? 'All systems normal' : p.length === 1 ? p[0] : `${p.length} things need attention`;
  const sub = off ? 'Add the Monitoring app to see app health' : p.length ? '' : sites;
  set(cls, title, sub);
  statInfo = { cls, title, sub, groups: [['Websites', down, 'bad'], ['Apps', apps, 'warn'], ['Storage', disk, 'warn']].filter((g) => g[1].length) };
  renderStat();
}
// Status screen: the home line only shows a headline, the full list lives here
let statInfo = null;
function renderStat() {
  const s = statInfo; if (!s) return;
  $('#stat-body').innerHTML = `<div class="card st-head"><i class="dot ${s.cls}"></i><div><b>${esc(s.title)}</b>${s.sub ? `<small>${esc(s.sub)}</small>` : ''}</div></div>`
    + s.groups.map(([name, items, c]) => `<div class="label">${name}</div><div class="card st-list">${items.map((t) => `<div class="st-row"><i class="dot ${c}"></i><span>${esc(t)}</span></div>`).join('')}</div>`).join('')
    + '<button class="st-go" id="stat-go">Open Server &amp; Apps</button>';
}
function openStat() { if (statInfo) renderStat(); else $('#stat-body').innerHTML = '<div class="skel"></div>'; $('#statp').hidden = false; document.body.style.overflow = 'hidden'; $('#statp .panel-body').scrollTop = 0; status(); }
function closeStat() { $('#statp').hidden = true; document.body.style.overflow = ''; }
$('#status').onclick = openStat;
document.querySelector('[data-close-stat]').onclick = closeStat;
$('#stat-refresh').onclick = () => spinning($('#stat-refresh'), status);
$('#stat-body').addEventListener('click', (e) => { if (e.target.closest('#stat-go')) { closeStat(); showTab('server'); } });
let serverLoading = null;
const loadServer = () => serverLoading || (serverLoading = loadServerNow().finally(() => { serverLoading = null; }));
async function loadServerNow() {
  loadGit();
  const body = $('#server-body');
  if (!body.innerHTML) body.innerHTML = '<div class="skel"></div><div class="skel"></div>';
  const T = 'max(node_hwmon_temp_celsius{chip=~".*coretemp.*"})';
  const vec = async (q) => { try { return await prom(q); } catch { return []; } };
  let [cpu, temp, mem, free, disk, up, d, hw, ghz, ctemp, memb, memt, host] = await Promise.all([
    one('100 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m])) * 100'), one(T),
    one('(1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes) * 100'),
    one('node_filesystem_avail_bytes{mountpoint="/"}'), one('node_filesystem_size_bytes{mountpoint="/"}'), one('time() - node_boot_time_seconds'), dailyStats(),
    getJSON('/api/specs.json').catch(() => null), vec('node_cpu_scaling_frequency_hertz'), vec('node_hwmon_temp_celsius{chip=~".*coretemp.*"}'),
    vec('node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes'), one('node_memory_MemTotal_bytes'), getJSON('/api/host.json').catch(() => null)]);
  // The host helper reads the machine itself. On a Mac that is the only true reading (Monitoring there sees Docker's small VM), so it wins when fresh.
  const hl = host && Date.now() / 1000 - host.generated < 300 ? host.live : null;
  if (hl && hl.cpu_pct != null) {
    const main = (hl.volumes || []).find((v) => !v.external) || {};
    [cpu, temp, free, disk, up] = [hl.cpu_pct, hl.temp ?? null, main.free ?? null, main.size ?? null, hl.uptime ?? null];
    mem = hl.mem_used && hl.mem_total ? (hl.mem_used / hl.mem_total) * 100 : null;
    memb = hl.mem_used ? [{ value: [0, hl.mem_used] }] : []; memt = hl.mem_total ?? null; ghz = []; ctemp = [];
  }
  const hspec = !hw && host?.specs ? { ...host.specs, generated: host.generated } : null;
  const srvErr = $('#server-err'); srvErr.hidden = true;
  await status();
  const [ai, cat] = await Promise.all([getJSON('/api/bot/server/ai').catch(() => null), getJSON('/api/bot/server/catalog').catch(() => null)]);
  $('#act-free').hidden = !ai?.reachable;  // nothing to free without an AI engine
  $('#act-reboot').hidden = !cat?.reboot;  // only when you allowed it (homelab agent install --allow-reboot); otherwise the button could only fail
  if (cpu == null) {  // neither the host helper nor Monitoring: still show what runs and what uses memory
    body.innerHTML = `<div class="card sec mon-off"><h3>Live numbers are off</h3><ul><li class="plain">CPU, memory and disk need the host helper. ${hlRunIn()} this once:${cmdHTML(hlCmd('agent install'))}</li></ul></div>`
      + appsMemHTML(cat) + aiHTML(ai);
    $('#hw-body').innerHTML = hspec ? hostSpecsHTML(hspec, {}) : `<div class="card sec mon-off"><h3>No hardware details yet</h3><ul><li class="plain">The host helper reads them from this machine. ${hlRunIn()} this once:${cmdHTML(hlCmd('agent install'))}</li></ul></div>`;
    $('#server-sub').textContent = 'Updated ' + new Date().toLocaleTimeString('en-US', T12);
    return;
  }
  const feel = temp < 60 ? 'cool' : temp < 80 ? 'warm' : 'hot';
  let html = `<div class="kv">
    <div class="card"><b class="num">${Math.round(cpu)}%</b><small>How busy it is</small></div>
    ${temp != null ? `<div class="card"><b class="num">${Math.round(temp)}°C</b><small>Temperature, ${feel}</small></div>` : ''}
    <div class="card"><b class="num">${Math.round(mem)}%</b><small>Memory used</small></div>
    <div class="card"><b class="num">${Math.round(free / 1e9)} GB</b><small>Free, out of ${Math.round(disk / 1e9)} GB</small></div>
    <div class="card"><b class="num">${(up / 86400).toFixed(1)}d</b><small>Since last restart</small></div>
    ${installed ? `<div class="card"><b class="num">${running.length}/${installed.length}</b><small>Apps running</small></div>` : ''}</div>`;
  html += useHTML(memb[0] ? +memb[0].value[1] : null, memt, free, disk, hw?.external);
  html += appsMemHTML(cat) + aiHTML(ai);
  let more = '';
  if (hw) more += specsHTML(hw, { ghz, ctemp, up, usedMem: memb[0] ? +memb[0].value[1] : null, free, disk });
  else if (hspec) more += hostSpecsHTML(hspec, hl || {});
  if (d?.sites?.length) more += `<div class="card sec"><h3>Websites<small>last 24 hours</small></h3>
    ${d.sites.map((s) => `<div class="srow"><i class="dot ${s.up_now ? 'ok' : 'bad'}"></i><span class="nm">${esc(s.name)}</span><span class="vl num">${s.up_now ? 'Online' : 'Down'} • ${s.uptime}%</span></div>`).join('')}</div>`;
  if (d?.events) more += `<div class="card sec"><h3>Last 24 hours</h3><ul>
    ${d.events.length ? d.events.slice(-8).reverse().map((e) => `<li>${esc(/^\d{1,2}:\d{2}$/.test(e.time) ? ((h, m) => `${h % 12 || 12}:${m} ${h < 12 ? 'AM' : 'PM'}`)(+e.time.split(':')[0], e.time.split(':')[1]) : e.time)} • ${esc(e.text)}</li>`).join('') : '<li class="plain">All quiet.</li>'}</ul></div>`;
  body.classList.toggle('settled', !!body.querySelector('.kv'));  // quiet refreshes don't replay the entrance animation
  body.innerHTML = html;
  const hb = $('#hw-body'); hb.classList.toggle('settled', !!hb.querySelector('.card')); hb.innerHTML = more;
  $('#server-sub').textContent = 'Updated ' + new Date().toLocaleTimeString('en-US', T12);
}
// What each running app uses, biggest first, so it is clear what is eating memory (the AI engine's models are counted in its own line)
function appsMemHTML(cat) {
  if (!cat?.docker) return '';
  const rows = [...cat.core, ...cat.apps].filter((a) => a.state === 'running' && a.memory_now_mb).sort((x, y) => y.memory_now_mb - x.memory_now_mb);
  if (!rows.length) return '';
  const mb = (n) => n >= 1024 ? `${(n / 1024).toFixed(1)} GB` : `${n} MB`;
  return `<div class="card sec"><h3>Memory by app<small>${mb(rows.reduce((n, a) => n + a.memory_now_mb, 0))} in all</small></h3>
    ${rows.map((a) => `<div class="srow"><i class="dot ok"></i><span class="nm">${esc(a.title.split(' (')[0])}</span><span class="vl num">${mb(a.memory_now_mb)}</span></div>`).join('')}</div>`;
}
// The AI models the assistant keeps in memory, and the busy flag while a big job (news, journal) has made room for itself.
// Under them, every other installed model with Load / Unload; Load only when free memory covers it (checked again by the bot).
const LOCK = '<svg class="ai-lock" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-label="Always loaded"><rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
// Other models folds away; while folded, any that are in memory (or on their way) still show so Unload stays one tap away
let aiOpen = false; try { aiOpen = localStorage.getItem('ai-others') === '1'; } catch (e) {}
let aiLast = null;
function aiHTML(a) {
  if (!a?.models?.length) return '';
  aiLast = a;
  const dot = { ready: 'ok', working: 'warn', on: 'ok', loading: 'warn', unloading: 'warn' }, m = a.mem, os = a.others || [];
  const pc = (g) => Math.max(0, g / m.total * 100).toFixed(1) + '%';
  const mem = m ? `<div class="ai-mem"><i style="width:${pc(m.total - m.free - m.ai)}"></i><i class="ai" style="width:${pc(m.ai)}"></i></div>
    <div class="ai-key num">${m.free.toFixed(1)} GB free • AI models using ${m.ai.toFixed(1)} GB</div>` : '';
  const btn = (o) => o.state === 'unloading' ? '<button class="ai-btn wait">Unloading…</button>' : o.state === 'on' ? `<button class="ai-btn" data-ai="unload" data-n="${esc(o.name)}">Unload</button>`
    : o.state === 'loading' ? '<button class="ai-btn wait">Loading…</button>'
    : o.fits && !a.busy ? `<button class="ai-btn" data-ai="load" data-n="${esc(o.name)}">Load</button>`
    : `<button class="ai-btn no" data-ai="no" data-why="${esc(a.busy ? `Busy: ${a.busy.toLowerCase()}. Try again when it's done.` : o.why || '')}">No room</button>`;
  if (os.some((o) => /loading/.test(o.state)) && !aiPoll) aiPoll = setTimeout(aiRefresh, 3000);  // a load or unload already under way when the page opened
  const pb = (x) => x.params ? `<i class="ai-p num">${esc(x.params)}</i>` : '';
  const sub = (o) => [/model$/.test(o.label) && o.name, `${{ on: 'Ready', loading: 'Loading', unloading: 'Unloading', off: 'Off' }[o.state]} • ${o.gb.toFixed(1)} GB`,
    o.state === 'off' && !o.fits && (/slots/.test(o.why) ? 'all slots in use' : `needs ${o.need.toFixed(1)} GB free`)].filter(Boolean).join(' • ');
  return `<div class="card sec" id="ai-card" data-sig="${esc(aiSig(a))}"><h3>AI models<small>${a.busy ? esc(a.busy) : 'Kept loaded'}</small></h3>${mem}
    ${a.models.map((x) => `<div class="srow"><i class="dot ${dot[x.state] || ''}"></i><span class="nm">${esc(x.role)}${pb(x)}<small class="num">${esc([x.name.replace(/:latest$/, ''), x.note, x.gb && x.gb.toFixed(1) + ' GB'].filter(Boolean).join(' • '))}</small></span>${x.state === 'missing' ? `<button class="ai-btn" data-ai="pull" data-n="${esc(x.name)}">Download</button>` : x.state === 'working' ? '' : LOCK}</div>`).join('')}
    ${os.length ? `<button class="ai-sub${aiOpen ? ' open' : ''}" data-ai-tog aria-expanded="${aiOpen}">Other models<em class="num">${os.length} models${os.some((o) => o.state !== 'off') ? ` • ${os.filter((o) => o.state !== 'off').length} in memory` : ''}</em><span class="chev">${CHEV}</span></button>${os.filter((o) => aiOpen || o.state !== 'off').map((o) => `<div class="srow"><i class="dot ${dot[o.state] || ''}"></i><span class="nm">${esc(o.label)}${pb(o)}<small class="num">${esc(sub(o))}</small></span>${btn(o)}</div>`).join('')}` : ''}</div>`;
}
// While a model loads, check quietly in the background: the card only changes when a model's state does (Loading -> Ready),
// and it's updated in place so nothing re-animates or jumps
let aiPoll = null;
function aiSig(a) { return JSON.stringify([a.busy, a.models.map((x) => x.state), (a.others || []).map((o) => [o.name, o.state, o.fits])]); }
async function aiRefresh(force) {
  const a = await getJSON('/api/bot/server/ai').catch(() => null), el = $('#ai-card');
  if (!a || !el) return;
  if (force || el.dataset.sig !== aiSig(a)) { const t = document.createElement('div'); t.innerHTML = aiHTML(a); el.innerHTML = t.firstElementChild.innerHTML; el.dataset.sig = aiSig(a); }
  clearTimeout(aiPoll); aiPoll = null;
  if (a.others?.some((o) => /loading/.test(o.state))) aiPoll = setTimeout(aiRefresh, 3000);
}
$('#server-body').addEventListener('click', async (e) => {
  if (e.target.closest('[data-ai-tog]') && aiLast) {
    aiOpen = !aiOpen; try { localStorage.setItem('ai-others', aiOpen ? '1' : '0'); } catch (er) {}
    const el = $('#ai-card'), t = document.createElement('div'); t.innerHTML = aiHTML(aiLast); el.innerHTML = t.firstElementChild.innerHTML; return;
  }
  const b = e.target.closest('[data-ai]'); if (!b) return;
  if (b.dataset.ai === 'no') return snack(b.dataset.why, { bad: true });
  if (b.dataset.ai === 'pull') {  // download a model that is set but not on the engine yet, then follow it until it is there
    b.classList.add('wait'); b.textContent = 'Starting…';
    const r = await setApi('/setup/ai/pull', { name: b.dataset.n });
    if (!r.ok) { snack(r.error || 'The download did not start.', { bad: true }); return aiRefresh(true); }
    for (let i = 0; i < 2400; i++) {
      await new Promise((ok) => setTimeout(ok, 1500));
      const p = await setApi('/setup/ai/progress'); if (!p.ok) continue;
      if (p.error) { snack(p.error, { bad: true }); break; }
      if (p.done) break;
      if (document.body.contains(b)) b.textContent = p.total ? `${Math.round(p.completed / p.total * 100)}%` : 'Starting…';
    }
    return aiRefresh(true);
  }
  b.classList.add('wait'); b.textContent = b.dataset.ai === 'load' ? 'Loading…' : 'Unloading…';
  const r = await fetch('/api/bot/server/ai/model', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: b.dataset.n, act: b.dataset.ai }) }).catch(() => null);
  const j = await r?.json().catch(() => null);
  if (!j?.ok) snack(j?.error || "Couldn't reach the AI engine.", { bad: true });
  aiRefresh(true);
});
// RAM, NVMe and SATA at a glance; the full details stay in Hardware specs and health
function useHTML(memUsed, memTot, free, disk, ext) {
  const GiB = (b) => (b / 2 ** 30).toFixed(1) + ' GB';
  const bar = (name, used, size, txt) => { const pc = Math.min(100, (used / size) * 100);
    return `<div class="ur"><div class="uh"><span>${name}</span><small class="num">${txt}</small></div><div class="meter"><i${pc >= 90 ? ' class="hi"' : ''} style="width:${pc}%"></i></div></div>`; };
  const rows = [memUsed && memTot ? bar('Memory', memUsed, memTot, `${GiB(memUsed)} of ${Math.round(memTot / 2 ** 30)} GB`) : '',
    free && disk ? bar('Storage', disk - free, disk, usedTxt(disk - free, disk)) : '',
    ext?.size ? bar('Backup drive', ext.used, ext.size, usedTxt(ext.used, ext.size)) : ''].join('');
  return rows ? `<div class="card use">${rows}</div>` : '';
}
function openHw() {
  $('#hwp').hidden = false; document.body.style.overflow = 'hidden'; $('#hwp .panel-body').scrollTop = 0;
  if (!$('#hw-body').innerHTML) $('#hw-body').innerHTML = '<div class="skel"></div><div class="skel"></div>';
}
function closeHw() { $('#hwp').hidden = true; document.body.style.overflow = ''; }
$('#hw-open').onclick = openHw;
// ----- Night log (2026-10-29, v2): the night's schedule, ticked off. Each planned job shows when it was meant to run, when it
// actually did, how long it took and whether it worked; a row opens only when it has more to show (AI calls, retries, errors).
// Anything unplanned (news, manual runs) comes after, news grouped into one row.
let NL = null, nlDay = 0, nlOpenIds = new Set();
// The plan comes from your Schedule (Settings): only jobs that are on, in the night window (before 9 AM), with the journal's two retries
let NL_PLAN = [];
async function nlPlanLoad() {
  const r = await getJSON('/api/bot/schedule').catch(() => null);
  const on = (r?.jobs || []).filter((j) => j.on && j.at24 && j.at24 < '09:30' && !['news', 'weekly', 'recap'].includes(j.id));
  const name = { briefing: 'Morning brief', journal: 'Journal morning', insights: 'Deep insights', backup: 'Backup', github: 'Copy settings to git' };
  const plus = (hhmm, min) => { const [h, m] = hhmm.split(':').map(Number), t = (h * 60 + m + min) % 1440; return `${String(Math.floor(t / 60)).padStart(2, '0')}:${String(t % 60).padStart(2, '0')}`; };
  NL_PLAN = on.flatMap((j) => j.id === 'journal'
    ? [{ at: j.at24, name: name.journal, what: j.what.split('.')[0] }, { at: plus(j.at24, 120), name: name.journal, what: 'Tries again if the first one didn\u2019t finish', opt: true }, { at: plus(j.at24, 240), name: name.journal, what: 'Last try if needed', opt: true }]
    : [{ at: j.at24, name: name[j.id] || j.title, what: j.what }]).sort((x, y) => x.at.localeCompare(y.at));
}
const nlT = (ts) => new Date(ts * 1000).toLocaleTimeString('en-US', T12);
const nlTs = (ts) => new Date(ts * 1000).toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', second: '2-digit', hour12: true });
const nlDur = (s) => s < 1 ? 'under a second' : s < 60 ? `${Math.round(s)} s` : s < 3600 ? `${Math.floor(s / 60)} min ${Math.round(s % 60)} s` : `${Math.floor(s / 3600)} h ${Math.round((s % 3600) / 60)} min`;
const nlAt = (base, hhmm) => { const [h, m] = hhmm.split(':').map(Number), d = new Date(base); d.setHours(h, m, 0, 0); return d / 1000; };
async function loadNl() { try { [NL] = await Promise.all([getJSON('/api/bot/runs'), nlPlanLoad()]); } catch { NL = null; } }
function nlBase(i) {  // the night i nights back: its midnight. A night is 12 to 9 AM; "Tonight" is the current or coming one
  const n = new Date(), d = new Date(n); d.setHours(0, 0, 0, 0);
  if (n.getHours() >= 9) d.setDate(d.getDate() + 1);
  d.setDate(d.getDate() - i); return d;
}
function nlDetail(j, jobs, ais) {  // plain lines about a job, its steps and its AI calls; '' when there's nothing more to say
  const sub = jobs.filter((k) => k.parent === j.id), mine = ais.filter((a) => a.job === j.id), out = [];
  if (j.nights != null) out.push(`<p class="nl-l">Read ${plural(j.nights, 'new night')}.</p>`);
  if (j.waited) out.push(`<p class="nl-l">Waited ${nlDur(j.waited)} for the AI to be free.</p>`);
  if (j['waited for journal']) out.push(`<p class="nl-l">Waited ${nlDur(j['waited for journal'])} for the journal to finish first.</p>`);
  if (j.note) out.push(`<p class="nl-l">Morning note: ${esc(j.note)}.</p>`);
  if (j.insights) out.push(`<p class="nl-l">Deep insights: ${esc(j.insights)}.</p>`);
  sub.forEach((k) => out.push(`<div class="nl-step"><p><i class="nl-dot ${nlCls(k.status)}"></i><b>${esc(k.job)}</b><span>${k.status === 'skipped' ? 'nothing new' : nlDur(k.secs)}</span></p>${nlDetail(k, jobs, ais)}</div>`));
  if (mine.length) out.push(`<div class="nl-ai">${mine.map((a) => `<div><span><b>${esc(jdCap(a.purpose))}</b><small>${esc(a.model)}</small></span>
    <em>${a.attempt > 1 ? `<i class="rt">try ${a.attempt}</i>` : ''}${a.secs ? nlDur(a.secs) : ''}</em></div>`).join('')}</div>`);
  (j.checks || []).forEach((c) => out.push(`<p class="nl-l">${esc(c)}</p>`));
  [j.err, ...(j.errors || [])].filter(Boolean).forEach((e) => out.push(`<p class="nl-l nl-err">${esc(e)}</p>`));
  return out.join('');
}
const nlCls = (st) => ({ ok: 'good', warn: 'warn', failed: 'bad' }[st] || 'skip');
function nlRow(id, time, name, line, pill, cls, det) {
  const open = det && nlOpenIds.has(id);
  return `<div class="nl-r ${cls}"><${det ? `button class="nl-h" data-nlj="${id}"` : 'div class="nl-h"'}><span class="nl-tm">${time}</span><i class="nl-dot ${cls}"></i>
    <span class="nl-tx"><b>${esc(name)}</b><small>${line}</small></span><em class="nl-pill ${cls}">${pill}</em>${det ? `<span class="chev${open ? ' up' : ''}">${CHEV}</span>` : '<span class="nl-sp"></span>'}</${det ? 'button' : 'div'}>
    ${open ? `<div class="nl-det">${det}</div>` : ''}</div>`;
}
function renderNl() {
  const box = $('#nl-body');
  if (!NL) { box.innerHTML = '<div class="err">The night log isn’t reachable right now.</div>'; return; }
  const base = nlBase(nlDay), a = base / 1000, b = a + 9 * 3600, now = Date.now() / 1000;
  // a job that started but hasn't finished is running, or was cut short if the bot restarted after it began
  const ended = new Set(NL.jobs.map((j) => j.id)), live = (NL.starts || []).filter((x) => !ended.has(x.id)).map((x) => {
    const boot = (NL.boots || []).find((t) => t > x.start);
    return { ...x, status: boot ? 'interrupted' : 'running', stop: boot, secs: (boot || now) - x.start };
  });
  const jobs = [...NL.jobs, ...live].filter((j) => j.start >= a && j.start < b), ais = NL.ai.filter((x) => x.at >= a && x.at < b), used = new Set();
  const chips = [0, 1, 2].map((i) => { const d = nlBase(i); return `<button data-nld="${i}" class="${nlDay === i ? 'on' : ''}">${i === 0 ? 'Tonight' : d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric' })}</button>`; }).join('');
  let ok = 0, bad = 0, late = 0, done = 0, unlogged = 0;
  const rows = NL_PLAN.map((p, i) => {
    const at = nlAt(base, p.at);
    const j = jobs.find((x) => !x.parent && !used.has(x.id) && x.job === p.name && (p.loose || !x.sched || x.sched === p.at || x.sched.includes(p.at)) && x.start >= at - 1800);
    const time = p.loose ? 'About 6 AM' : nlT(at).replace(':00', '');
    if (!j && at + (p.loose ? 3 * 3600 : 1800) < (NL.since || 0)) return (unlogged++, nlRow('p' + i, time, p.opt ? 'Journal morning (retry)' : p.name, 'Before the night log started', 'Not logged', 'skip', ''));
    if (!j) {
      const passed = now > at + (p.loose ? 3 * 3600 : 1800);
      const [line, pill, cls] = !passed ? [esc(p.what), 'Not yet', 'skip'] : p.opt ? ['Only runs if the earlier try failed', 'Not needed', 'skip'] : ['No record of it running', 'Didn’t run', 'warn'];
      if (passed && !p.opt) bad++;
      return nlRow('p' + i, time, p.opt ? 'Journal morning (retry)' : p.name, line, pill, cls, '');
    }
    used.add(j.id); done++;
    if (j.status === 'running') return nlRow(j.id, time, p.opt ? 'Journal morning (retry)' : p.name, `Started ${nlTs(j.start)}, running for ${nlDur(j.secs)}.`, 'Running', 'run', nlDetail(j, jobs, ais));
    if (j.status === 'interrupted') { bad++; return nlRow(j.id, time, p.opt ? 'Journal morning (retry)' : p.name, `Started ${nlTs(j.start)}. Cut short by a restart at ${nlTs(j.stop)}.`, 'Interrupted', 'warn', nlDetail(j, jobs, ais)); }
    const delay = p.loose ? 0 : j.start - at, lateTxt = delay > 120 ? `, ${nlDur(delay)} late` : delay < -120 ? ', early' : ', on time';
    if (delay > 120) late++;
    j.status === 'failed' ? bad++ : ok++;
    const pill = { ok: 'Done', warn: 'Done, with problems', failed: 'Failed', skipped: p.opt ? 'Nothing left' : 'Nothing new' }[j.status];
    return nlRow(j.id, time, p.opt ? 'Journal morning (retry)' : p.name, `Started ${nlTs(j.start)}${lateTxt}. Took ${nlDur(j.secs)}.`, pill, nlCls(j.status), nlDetail(j, jobs, ais));
  }).join('');
  const extra = jobs.filter((j) => !j.parent && !used.has(j.id)), news = extra.filter((j) => j.job.startsWith('News')), other = extra.filter((j) => !j.job.startsWith('News'));
  const also = other.map((j) => nlRow(j.id, nlT(j.start), j.job, j.status === 'running' ? `Running for ${nlDur(j.secs)}.` : j.status === 'interrupted' ? `Cut short by a restart at ${nlTs(j.stop)}.` : `Took ${nlDur(j.secs)}.`,
    { ok: 'Done', warn: 'With problems', failed: 'Failed', skipped: 'Nothing new', running: 'Running', interrupted: 'Interrupted' }[j.status], j.status === 'running' ? 'run' : j.status === 'interrupted' ? 'warn' : nlCls(j.status), nlDetail(j, jobs, ais)))
    .concat(news.length ? [nlRow('news', nlT(news[0].start), 'News', `${plural(news.length, 'run')}, ${nlT(news[0].start)} to ${nlT(news.at(-1).end)}. They wait for the journal each morning.`,
      news.some((j) => j.status === 'failed') ? 'Failed' : 'Done', news.some((j) => j.status === 'failed') ? 'bad' : 'good',
      news.map((j) => `<div class="nl-step"><p><i class="nl-dot ${nlCls(j.status)}"></i><b>${esc(j.job.replace('News: ', ''))}</b><span>${nlT(j.start)}, ${nlDur(j.secs)}</span></p>${nlDetail(j, jobs, ais)}</div>`).join(''))] : []).join('');
  const aiSecs = ais.reduce((t, x) => t + (x.secs || 0), 0), tries = ais.filter((x) => x.attempt > 1).length;
  const head = done ? `<p class="nl-sum2">${bad ? `<b class="bad">${plural(bad, 'problem')}</b>` : `<b class="good">${unlogged ? 'Everything logged ran' : 'Everything ran'}</b>`}${late ? `, ${late} late` : ''}.${unlogged ? ' Some jobs ran before the night log started, so they show as not logged.' : ''} ${aiSecs ? `AI worked for ${nlDur(aiSecs)}${tries ? ` with ${plural(tries, 'retry').replace('retrys', 'retries')}` : ', no retries'}.` : ''}</p>`
    : `<p class="nl-sum2">${nlDay === 0 ? `The night runs from 12 to 9 AM. ${NL_PLAN.length ? `The first planned job is at ${nlT(nlAt(nlBase(0), NL_PLAN[0].at))}.` : 'Nothing is planned. Turn jobs on in Settings, Schedule.'}${also ? ' Anything that ran before then is under Also ran.' : ''}` : `Nothing was logged for this night. The log started on ${new Date((NL.since || 0) * 1000).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}.`}</p>`;
  box.innerHTML = `<div class="seg ptabs nl-seg">${chips}</div>${head}<div class="label">The plan</div><div class="card nl-list">${rows}</div>`
    + (also ? `<div class="label">Also ran</div><div class="card nl-list">${also}</div>` : '')
    + '<p class="hint">Times are in your phone’s time zone. The server runs the journal on your local time and the backups on the server’s time zone. Tap a row with an arrow to see its steps and AI calls. Only times, counts and errors are logged, never your journal words.</p>';
}
async function openNl() { $('#nlp').hidden = false; document.body.style.overflow = 'hidden'; $('#nlp .panel-body').scrollTop = 0; $('#nl-body').innerHTML = '<div class="card"><div class="skel"></div></div>'; await loadNl(); renderNl(); }
function closeNl() { $('#nlp').hidden = true; document.body.style.overflow = ''; }
$('#nl-open').onclick = openNl;
document.querySelector('[data-close-nl]').onclick = closeNl;
$('#nl-refresh').onclick = () => spinning($('#nl-refresh'), async () => { await loadNl(); renderNl(); });
$('#nl-body').addEventListener('click', (e) => {
  const v = e.target.closest('[data-nld]'); if (v) { nlDay = +v.dataset.nld; nlOpenIds.clear(); return renderNl(); }
  const h = e.target.closest('[data-nlj]'); if (h) { const id = h.dataset.nlj; nlOpenIds.has(id) ? nlOpenIds.delete(id) : nlOpenIds.add(id); renderNl(); }
});
document.querySelector('[data-close-hw]').onclick = closeHw;
$('#hw-refresh').onclick = () => spinning($('#hw-refresh'), loadServer);
$('#server-refresh').onclick = () => { if (!rebooting) flash($('#act-msg'), ''); spinning($('#server-refresh'), loadServer); };
setInterval(() => { if (!document.hidden && !$('#v-server').hidden && $('#sheet').hidden && !rebooting) loadServer(); }, 30000);

// ---------- Hardware specs ----------
const SI = {
  box: '<rect x="3" y="6" width="18" height="12" rx="2.5"/><path d="M7 14.5h.01M10 14.5h.01M14 10h4"/>',
  cpu: '<rect x="6" y="6" width="12" height="12" rx="2"/><path d="M10 10h4v4h-4zM9 2.5V6M15 2.5V6M9 18v3.5M15 18v3.5M2.5 9H6M2.5 15H6M18 9h3.5M18 15h3.5"/>',
  ram: '<rect x="2.5" y="7" width="19" height="9" rx="1.5"/><path d="M6 10v3M10 10v3M14 10v3M18 10v3M5 16v2.5M19 16v2.5"/>',
  disk: '<rect x="3" y="7" width="18" height="10" rx="2"/><path d="M7 12h6M17 12h.01"/>',
  usb: '<rect x="7" y="2.5" width="10" height="7" rx="1"/><path d="M10 5.5h.01M14 5.5h.01"/><rect x="5" y="9.5" width="14" height="12" rx="2.5"/><path d="M9.5 16h5"/>',
  net: '<path d="M2.5 9a14 14 0 0 1 19 0M5.5 12.5a9.5 9.5 0 0 1 13 0M8.6 16a5 5 0 0 1 6.8 0M12 19.5h.01"/>',
  soft: '<rect x="3" y="4" width="18" height="14" rx="2.5"/><path d="M7 9l3 2.5L7 14M12 14h5M8 21h8"/>',
};
const sIcon = (k, w = 1.7) => `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="${w}" stroke-linecap="round" stroke-linejoin="round">${SI[k]}</svg>`;
const onFor = (h) => (h >= 8766 ? `${(h / 8766).toFixed(1)} years` : h >= 1460 ? `${Math.round(h / 730)} months` : `${Math.round(h / 24)} days`);
const healthTxt = (ok, worn, bad, what) => `${ok ? 'Good' : 'Check it'}${worn != null ? ` • ${worn}% worn` : ''}${bad ? ` <em>${bad} ${what}</em>` : ''}`;
const usedTxt = (used, size) => `${used < 1e9 ? Math.max(1, Math.round(used / 1e6)) + ' MB' : GB(used)} used of ${GB(size)}`;
const tsTxt = (s) => {  // "today, 4:43 PM", "yesterday, 10 PM", "21 Oct, 4 PM"
  const d = new Date(s * 1000), n = Math.round((new Date().setHours(0, 0, 0, 0) - new Date(s * 1000).setHours(0, 0, 0, 0)) / 864e5);
  return `${n === 0 ? 'today' : n === 1 ? 'yesterday' : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}, ${d.toLocaleTimeString('en-US', T12)}`;
};
function extHTML(x, i) {
  const s = x.smart;
  const st = { in_use: ['ok', 'In use, backing up'], idle: ['ok', 'Idle, between backups'], disconnected: ['warn', 'Not found'] }[x.status] || ['', x.status];
  return `<div class="card spec" style="animation-delay:${i * 40}ms"><h3>${sIcon('disk', 2)}SATA internal storage${x.free != null ? `<small>${GB(x.free)} free</small>` : ''}</h3>`
    + (x.size ? `<div class="meter" style="margin-top:8px"><i style="width:${(x.used / x.size) * 100}%"></i></div>` : '')
    + row('Status', `<i class="dot ${st[0]}"></i>${st[1]}`)
    + (s ? row('Drive', esc(s.model.replace(/\s*SATA.*$/, ''))) : '')
    + (s?.capacity ? row('Capacity', `${Math.round(s.capacity / 1e9)} GB SATA SSD`) : '')
    + (s?.sata ? row('Connection', `SATA, ${esc(s.sata.replace(' Gb/s', ''))} Gbps`) : '')
    + (s ? row('Health', healthTxt(s.ok, s.life_pct != null ? 100 - s.life_pct : null, s.bad_sectors, 'bad sectors')) : '')
    + (x.size ? row('Storage', usedTxt(x.used, x.size)) : '')
    + (x.backups != null ? row('Backups', `${x.backups} kept <em>last 30 days</em>`) : '')
    + (s?.hours != null ? row('Powered on', `${s.hours.toLocaleString('en-GB')} hours <em>${onFor(s.hours)}</em>`) : '')
    + (s?.cycles != null ? row('Starts', `${s.cycles.toLocaleString('en-GB')}${s.unsafe != null ? ` <em>${s.unsafe.toLocaleString('en-GB')} unexpected</em>` : ''}`) : '')
    + (s?.temp ? row('Temperature', `${s.temp}°C`) : '')
    + (s?.firmware ? row('Firmware', esc(s.firmware)) : '')
    + (x.last_backup ? row('Last backup', tsTxt(x.last_backup)) : '')
    + (x.checked ? row('Last updated', tsTxt(x.checked)) : '') + '</div>';
}
function specsHTML(h, live) {
  const c = h.cpu, m = h.memory, st = h.storage || {}, n = h.network || {}, sw = h.software || {};
  // live clock and temperature for each core (core N's sensor is temp N+2)
  const byCpu = Object.fromEntries((live.ghz || []).map((r) => [+r.metric.cpu, +r.value[1] / 1e9]));
  const tC = Object.fromEntries((live.ctemp || []).map((r) => [r.metric.sensor, +r.value[1]]));
  const ids = Object.keys(byCpu).map(Number).sort((a, b) => a - b);
  const clocks = ids.map((i) => byCpu[i]), avg = clocks.length ? clocks.reduce((a, b) => a + b, 0) / clocks.length : null;
  const cores = ids.length ? `<div class="cores">${ids.map((i) => `<div class="core"><b class="num">${byCpu[i].toFixed(1)}</b>
    <div class="col"><i style="height:${Math.max(4, Math.min(100, (byCpu[i] / c.max_ghz) * 100))}%"></i></div>
    <span class="num">${tC['temp' + (i + 2)] != null ? Math.round(tC['temp' + (i + 2)]) + '°' : 'C' + i}</span></div>`).join('')}</div>` : '';
  const sig = n.wifi?.signal, sigWord = sig >= 75 ? 'excellent' : sig >= 55 ? 'good' : sig >= 35 ? 'fair' : 'weak';
  const sinceBoot = live.up ? (live.up >= 86400 ? `${Math.floor(live.up / 86400)}d ${Math.floor(live.up % 86400 / 3600)}h` : `${Math.floor(live.up / 3600)}h ${Math.floor(live.up % 3600 / 60)}m`) : '';
  const card = (icon, title, sub, body, i) => `<div class="card spec" style="animation-delay:${i * 40}ms"><h3>${sIcon(icon, 2)}${title}${sub ? `<small>${sub}</small>` : ''}</h3>${body}</div>`;
  return `<div class="label">Hardware</div>
  <div class="card hw-head">${sIcon('box', 1.4)}<div><b>${esc(h.device.name)}</b><small>${esc(sw.os)}${sinceBoot ? ` • up ${sinceBoot}` : ''}</small></div></div>`
  + card('cpu', 'Processor', avg ? `now ${avg.toFixed(2)} GHz avg` : '', cores
    + row('Chip', `Intel ${esc(c.model.replace(/^Intel\s*/, ''))}`)
    + row('Cores', `${c.cores} cores, ${c.threads} threads`)
    + row('Clock speed', `${(+c.base_ghz).toFixed(1)} GHz base, up to ${(+c.max_ghz).toFixed(1)} GHz`)
    + (clocks.length ? row('Right now', `${Math.min(...clocks).toFixed(1)} – ${Math.max(...clocks).toFixed(1)} GHz across cores`) : '')
    + row('Cache', `${parseInt(c.l3)} MB`)
    + (c.power_w != null ? row('Power draw', `${c.power_w} W <em>avg, last ${c.power_mins} min</em>`) : '')
    + row('Power limit', `${c.cap_w} W sustained, ${c.burst_w} W bursts`)
    + row('Graphics', `Intel ${esc(h.gpu)}`)
    + row('Virtual machines', c.virt ? 'Supported' : 'Not supported'), 0)
  + card('ram', 'Memory', live.usedMem ? `${GB(live.usedMem)} in use` : '',
    (live.usedMem ? `<div class="meter" style="margin-top:8px"><i style="width:${(live.usedMem / (m.total_gb * 1.074e9)) * 100}%"></i></div>` : '')
    + row('Installed', `${m.total_gb} GB ${esc(m.type)} ${esc(m.form || '')}`)
    + row('Speed', esc(m.speed))
    + row('Maker', esc(m.maker))
    + row('Slots', `${m.used_slots} of ${m.slots} used • ${esc(m.channel.toLowerCase())}`), 1)
  + (st.model ? card('disk', 'NVMe internal storage', live.free && live.disk ? `${GB(live.free)} free` : '',
    (live.free && live.disk ? `<div class="meter" style="margin-top:8px"><i style="width:${(1 - live.free / live.disk) * 100}%"></i></div>` : '')
    + row('Status', `<i class="dot ${st.health_ok === false ? 'warn' : 'ok'}"></i>In use, system drive`)
    + row('Drive', esc(st.model.split(' ').slice(0, 3).join(' ')))
    + row('Capacity', `${st.size_gb} GB NVMe SSD`)
    + row('Connection', esc(st.link))
    + row('Health', healthTxt(st.health_ok !== false && !st.media_errors, st.worn_pct, st.media_errors, 'media errors'))
    + (live.free && live.disk ? row('Storage', usedTxt(live.disk - live.free, live.disk)) : '')
    + row('Data written', `${st.written_tb} TB`)
    + row('Powered on', `${st.hours.toLocaleString('en-GB')} hours <em>${onFor(st.hours)}</em>`)
    + (st.cycles != null ? row('Starts', `${st.cycles.toLocaleString('en-GB')}${st.unsafe != null ? ` <em>${st.unsafe.toLocaleString('en-GB')} unexpected</em>` : ''}`) : '')
    + row('Temperature', `${st.temp}°C`)
    + (st.firmware ? row('Firmware', esc(st.firmware)) : '')
    + (h.generated ? row('Last updated', tsTxt(h.generated)) : ''), 2) : '')
  + (h.external ? extHTML(h.external, 3) : '')
  + card('net', 'Network', n.wifi?.ssid ? 'Wi-Fi' : n.eth_up ? 'Ethernet' : '',
    (n.wifi?.ssid ? row('Wi-Fi', `${esc(n.wifi.ssid)} <em>${esc(n.wifi.band)}</em>`) + row('Link speed', esc(n.wifi.rate))
      + row('Signal', `${sig}% <em>${sigWord}</em>`) : '')
    + row('Wi-Fi card', `Intel ${esc(n.wifi_card)}`)
    + row('Ethernet', n.eth_up ? `Connected, ${n.eth_speed >= 1000 ? n.eth_speed / 1000 + ' Gbps' : n.eth_speed + ' Mbps'}` : `Intel ${esc(n.eth_card)} <em>not plugged in</em>`)
    + row('Home network IP', esc(n.lan_ip))
    + row('Tailscale IP', esc(n.tailnet_ip)), 3)
  + card('soft', 'Software', '',
    row('System', esc(sw.os))
    + row('Kernel', esc(sw.kernel))
    + row('Docker', `${esc(sw.docker)} <em>${sw.containers} apps</em>`)
    + row('BIOS', `${esc(h.device.bios.replace(/ Ver\. /, ' '))} <em>${esc(h.device.bios_date)}</em>`), 4);
}

// Any machine, from the host helper's host.json: only what this machine has is shown, every disk it has mounted included
function hostSpecsHTML(h, live) {
  const c = h.cpu || {}, m = h.memory || {}, g = h.gpu || {}, n = h.network || {}, sw = h.software || {}, b = h.battery, dev = h.device || {};
  const up = live.uptime, since = up ? (up >= 86400 ? `${Math.floor(up / 86400)}d ${Math.floor(up % 86400 / 3600)}h` : `${Math.floor(up / 3600)}h ${Math.floor(up % 3600 / 60)}m`) : '';
  const card = (icon, title, sub, body, i) => body ? `<div class="card spec" style="animation-delay:${i * 40}ms"><h3>${sIcon(icon, 2)}${title}${sub ? `<small>${sub}</small>` : ''}</h3>${body}</div>` : '';
  const meter = (used, size) => size ? `<div class="meter" style="margin-top:8px"><i${used / size >= 0.9 ? ' class="hi"' : ''} style="width:${Math.min(100, used / size * 100)}%"></i></div>` : '';
  const cores = c.perf_cores ? `${c.cores} cores <em>${c.perf_cores} performance, ${c.eff_cores || 0} efficiency</em>` : c.cores ? `${c.cores} cores${c.threads && c.threads !== c.cores ? `, ${c.threads} threads` : ''}` : '';
  const vols = live.volumes || [];
  return `<div class="label">Hardware</div>
  <div class="card hw-head">${sIcon('box', 1.4)}<div><b>${esc(dev.name || 'This machine')}</b><small>${esc([dev.model, sw.os].filter(Boolean).join(' \u2022 '))}${since ? ` \u2022 up ${since}` : ''}</small></div></div>`
  + card('cpu', 'Processor', live.cpu_pct != null ? `${Math.round(live.cpu_pct)}% busy` : '',
    row('Chip', esc(c.model || '')) + row('Cores', cores) + (c.max_ghz ? row('Clock speed', `up to ${(+c.max_ghz).toFixed(1)} GHz`) : '') + row('Cache', esc(c.cache || ''))
    + row('Graphics', g.model ? `${esc(g.model)}${g.cores ? ` <em>${g.cores} cores</em>` : ''}` : '') + (live.load != null ? row('Load', live.load.toFixed(2)) : '')
    + (c.virt ? row('Virtual machines', 'Supported') : ''), 0)
  + card('ram', 'Memory', live.mem_used ? `${GB(live.mem_used)} in use` : '',
    (live.mem_used && live.mem_total ? meter(live.mem_used, live.mem_total) : '')
    + row('Installed', m.total_gb ? `${m.total_gb} GB${m.type ? ' ' + esc(m.type) : ''}${m.unified ? ' <em>shared with graphics</em>' : ''}` : '') + row('Maker', esc(m.maker || '')), 1)
  + vols.map((v, i) => card(v.external ? 'usb' : 'disk', esc(v.name), `${GB(v.free)} free`,
    meter(v.size - v.free, v.size) + row('Storage', usedTxt(v.size - v.free, v.size)) + row('Kind', v.external ? 'External drive' : 'Inside this machine')
    + (v.mount !== '/' && v.mount !== '/System/Volumes/Data' ? row('Folder', esc(v.mount)) : ''), 2 + i)).join('')
  + card('disk', vols.length ? 'Drives' : 'Storage', '', (h.drives || []).map((d) => row(esc(d.model), `${d.size ? GB(d.size) + ' ' : ''}${esc(d.kind || '')}${d.health_ok === false ? ' <em>check its health</em>' : ''}`)).join(''), 3)
  + (b ? card('soft', 'Battery', b.charge_pct != null ? `${b.charge_pct}%${b.charging ? ', charging' : ''}` : '',
    row('Condition', esc(b.condition || '')) + row('Capacity', b.max_pct != null ? `${b.max_pct}% of new` : '') + row('Charge cycles', b.cycles != null ? String(b.cycles) : ''), 4) : '')
  + card('net', 'Network', esc(n.connection || ''), row('Home network IP', esc(n.lan_ip || '')) + row('Tailscale IP', esc(n.tailnet_ip || '')), 5)
  + card('soft', 'Software', '', row('System', esc(sw.os || '')) + row('Kernel', esc(sw.kernel || '')) + row('Docker', esc(sw.docker || ''))
    + row('Firmware', esc(dev.firmware || '')) + (h.generated ? row('Last updated', tsTxt(h.generated)) : ''), 6);
}

// ---------- Server actions ----------
const actMsg = (t, o) => flash($('#act-msg'), t, o);
// ----- GitHub backup: the hourly sync (homelab-git-sync) and a button that runs one now
let gitB = null, gitBusy = false;
const gitAgo = (s) => { const m = Math.round((Date.now() / 1000 - s) / 60); return m < 1 ? 'Just now' : m < 60 ? `${m}m ago` : m < 1440 ? `${Math.floor(m / 60)}h ${m % 60}m ago` : `${Math.floor(m / 1440)} days ago`; };
const gitClock = (s) => new Date(s * 1000).toLocaleTimeString('en-US', T12);
function renderGit(x, busy = false) {
  const s = $('#gitb-s'), go = $('#gitb-go'), now = Date.now() / 1000;
  go.disabled = busy; go.textContent = busy ? 'Backing up…' : x && !x.ok ? 'Retry' : 'Back up';
  s.className = '';
  if (busy) return void (s.textContent = 'Saving config and data to GitHub');
  if (!x || !x.at) return void (s.textContent = 'Couldn’t read the last backup');
  if (!x.ok) { s.className = 'bad'; s.textContent = `Couldn’t reach GitHub • last good ${x.good ? gitAgo(x.good).toLowerCase() : 'unknown'}`; return; }
  if (now - x.at > 3 * 3600) s.className = 'warn';  // hourly normally: hours without one means the sync is stuck
  const more = x.fresh ? (x.files ? ` • ${x.files} ${x.files === 1 ? 'file' : 'files'} changed` : ' • nothing new') : x.next > now ? ` • next in ${Math.max(1, Math.round((x.next - now) / 60))}m` : '';
  s.textContent = (Date.now() / 1000 - x.at < 3600 ? gitAgo(x.at) : gitClock(x.at)) + more;  // an hour on, the time says more than "1h 5m ago"
}
async function loadGit() {
  if (gitBusy) return;
  try { gitB = await getJSON('/api/git-backup.json'); } catch { gitB = null; }
  if (!gitBusy) renderGit(gitB);
}
$('#gitb-go').onclick = async () => {
  if (gitBusy) return;
  gitBusy = true; renderGit(gitB, true);
  let r = null;
  try { r = await post('/api/bot/server/gitsync', {}); } catch {}
  gitBusy = false;
  gitB = r && r.at ? { ...r, fresh: true } : { ...(gitB || {}), ok: false };
  renderGit(gitB);
};

$('#act-free').onclick = async () => {
  const b = $('#act-free'); b.disabled = true; b.classList.add('busy'); actMsg('Freeing memory…', { stay: true });
  try { const r = await post('/api/bot/server/unload', {}); actMsg((r.ok ? '✓ ' : '') + r.msg, { bad: !r.ok }); } catch { actMsg('The assistant isn’t reachable right now.', { bad: true }); }
  b.disabled = false; b.classList.remove('busy'); loadServer();
};

async function loadSheet() {
  const body = $('#sheet-body');
  let r; try { r = await getJSON('/api/bot/server/apps'); } catch { body.innerHTML = '<div class="err">The assistant isn’t reachable right now.</div>'; return; }
  if (!r.apps) { body.innerHTML = `<div class="err">${esc(r.msg)}</div>`; return; }
  // installed first, then the ones you never installed, each A to Z. Not installed is not a problem: grey dot and no button (a Start would only fail)
  const az = (l) => l.sort((x, y) => x.name.localeCompare(y.name, undefined, { sensitivity: 'base' }));
  const have = az(r.apps.filter((x) => x.state !== 'missing')), not = az(r.apps.filter((x) => x.state === 'missing'));
  const part = (title, l) => l.length ? `<div class="agroup">${title}<span>${l.length}</span></div>` + appRows(l) : '';
  body.innerHTML = part('Installed', have) + part('Not installed', not);
}
function appRows(a) {
  return a.map((x) => `<div class="arow"><i class="dot ${x.state === 'running' ? 'ok' : x.state === 'missing' ? '' : 'bad'}"></i>
    <span class="nm">${esc(x.name)}<small>${x.state === 'running' ? 'Running' : x.state === 'missing' ? 'Not installed' : 'Stopped'}</small></span>
    ${x.state === 'missing' ? '' : `<button data-restart="${esc(x.id)}">${x.state === 'running' ? 'Restart' : 'Start'}</button>`}</div>`).join('');
}
$('#act-restart').onclick = () => { $('#sheet-title').textContent = 'Restart an app'; $('#sheet-body').innerHTML = '<div class="skel"></div>'; showSheet('Done'); loadSheet(); };
let sheetChanged = false;
function showSheet(close = 'Done') { $('#sheet .sheet-head .done').textContent = close; $('#sheet').hidden = false; document.body.style.overflow = 'hidden'; }
document.querySelectorAll('[data-close-sheet]').forEach((b) => b.onclick = closeSheet);
$('#sheet-body').onclick = async (e) => {
  const b = e.target.closest('[data-restart]'); if (!b || b.disabled) return;
  const sub = b.parentElement.querySelector('small');
  const name = b.parentElement.querySelector('.nm')?.firstChild?.textContent.trim() || 'this app', verb = b.textContent.trim();
  if (!await confirmSheet({ title: `${verb} ${name}?`, text: verb === 'Restart' ? 'It goes offline for a few seconds while it starts again.' : '', ok: verb })) return;
  b.style.width = b.offsetWidth + 'px';  // the button keeps its size while it shows "…"
  b.disabled = true; b.textContent = '…'; sub.textContent = 'Restarting…';
  let r; try { r = await post('/api/bot/server/restart', { id: b.dataset.restart }); } catch { r = { ok: false, msg: 'The assistant isn’t reachable right now.' }; }
  sub.textContent = r.msg; if (r.ok) sheetChanged = true;
  if (r.later) await sleep(8000);
  if (r.ok) { await loadSheet(); const row = $(`#sheet-body [data-restart="${CSS.escape(b.dataset.restart)}"]`); if (row) row.parentElement.querySelector('small').textContent = r.later ? 'Restarted' : r.msg; }
  else b.disabled = false, b.textContent = 'Retry';
  status();
};

// Restart the whole server: press and hold for 2 seconds, so a stray tap can't do it.
let holdT = null;
const rb = $('#act-reboot');
const holdStart = (e) => { if (rebooting) return; e.preventDefault(); rb.classList.add('holding'); $('#reboot-label').textContent = 'Keep holding…';
  holdT = setTimeout(reboot, 2000); };
const holdEnd = () => { if (rebooting) return; clearTimeout(holdT); rb.classList.remove('holding'); $('#reboot-label').textContent = 'Hold to restart server'; };
rb.addEventListener('pointerdown', holdStart);
['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => rb.addEventListener(ev, holdEnd));
rb.addEventListener('contextmenu', (e) => e.preventDefault());
rb.onclick = () => { if (!rebooting && !rb.classList.contains('holding')) actMsg('Press and hold to restart the server.'); };
async function reboot() {
  rebooting = true; rb.classList.remove('holding'); rb.disabled = true; $('#reboot-label').textContent = 'Restarting…';
  try { await post('/api/bot/server/reboot', { confirm: 'reboot' }); }
  catch { rebooting = false; rb.disabled = false; $('#reboot-label').textContent = 'Hold to restart server'; return actMsg('The assistant isn’t reachable, so nothing was restarted.', { bad: true }); }
  const t0 = Date.now();
  actMsg('Restarting the server. Back in about 2 minutes. You can leave this page open.', { stay: true });
  await sleep(25000);
  for (;;) {
    const s = Math.round((Date.now() - t0) / 1000);
    try { await getJSON('/api/bot/server/apps'); break; } catch {}
    actMsg(s > 600 ? 'Still not back after 10 minutes. Give it a few more, then check Telegram.' : `Restarting the server… ${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`, { bad: s > 600, stay: true });
    await sleep(5000);
  }
  rebooting = false; rb.disabled = false; $('#reboot-label').textContent = 'Hold to restart server';
  actMsg(`✓ Back online after ${Math.round((Date.now() - t0) / 1000)} seconds.`, { ms: 6000 });
  status(); loadServer();
}
