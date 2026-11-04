// ---------- Greeting ----------
function tick() {
  const d = new Date(), h = d.getHours();
  const g = h >= 5 && h < 12 ? 'Good morning' : h >= 12 && h < 17 ? 'Good afternoon' : 'Good evening';
  $('#greet').textContent = CFG.name ? `${g}, ${CFG.name}` : g;
  $('#clocks-sub').textContent = CFG.clocks.length ? `Times compared with ${CFG.home_city || 'home'}` : '';
  $('#when').textContent = d.toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' }) + ' • '
    + d.toLocaleTimeString('en-US', T12)
    + (X.location?.city ? ' • ' + X.location.city.replace(/ /g, ' ') : '');
  clocks();
}

// ---------- World clock ----------
const clockList = () => CFG.clocks.map((c) => [c.label, c.tz]);
const zoneMinutes = (tz, d) => { const p = Object.fromEntries(new Intl.DateTimeFormat('en-US', { timeZone: tz, hourCycle: 'h23', year: 'numeric',
  month: 'numeric', day: 'numeric', hour: 'numeric', minute: 'numeric' }).formatToParts(d).map((x) => [x.type, x.value]));
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute) / 60000; };
// night-time mark: a purple crescent with two little twinkling stars
const NIGHT = `<svg viewBox="0 0 24 24" aria-label="Night there"><path class="mn" d="M11.6 6.2a6.6 6.6 0 1 0 6.9 9.6A7.3 7.3 0 0 1 11.6 6.2z"/>
  <path class="st s1" d="M18.6 1.6l.8 2.1 2.1.8-2.1.8-.8 2.1-.8-2.1-2.1-.8 2.1-.8z"/><path class="st s2" d="M22 9.4l.5 1.3 1.3.5-1.3.5-.5 1.3-.5-1.3-1.3-.5 1.3-.5z"/><circle class="st s3" cx="15.2" cy="9.6" r=".9"/></svg>`;
let clkEdit = false;
function clocks() {
  const d = new Date(), here = zoneMinutes(CFG.timezone, d);  // everything is compared with home
  $('#clocks-edit').hidden = !CFG.clocks.length; $('#clocks-edit').textContent = clkEdit ? 'Done' : 'Edit';
  if (!CFG.clocks.length) { clkEdit = false; $('#clocks').innerHTML = '<div class="empty">No cities yet. Tap <b>+ Add</b> to see the time anywhere.</div>'; return; }
  $('#clocks').innerHTML = clockList().map(([city, tz], i) => {
    const there = zoneMinutes(tz, d), diff = Math.round(there - here), h = Math.floor(Math.abs(diff) / 60), m = Math.abs(diff) % 60;
    const gap = `${h ? h + 'h' : ''}${h && m ? ' ' : ''}${m ? m + 'm' : ''}`;
    const off = diff === 0 ? `Same time as ${CFG.home_city || 'home'}` : `${gap} ${diff > 0 ? 'ahead' : 'behind'}`;
    const dayDiff = Math.floor(there / 1440) - Math.floor(here / 1440);
    const hr = new Date(there * 60000).getUTCHours();
    const [t, ap] = new Intl.DateTimeFormat('en-US', { timeZone: tz, ...T12 }).format(d).split(' ');
    const badge = dayDiff ? `<span class="cday ${dayDiff > 0 ? 'nx' : 'pv'}" title="${dayDiff > 0 ? 'Tomorrow' : 'Yesterday'} there">${dayDiff > 0 ? '+1' : '−1'}</span>` : '';
    return `<div class="clock"><div class="c"><b>${city}</b><small>${off}${dayDiff ? `<em class="${dayDiff > 0 ? 'nx' : 'pv'}">${dayDiff > 0 ? 'Tomorrow' : 'Yesterday'}</em>` : ''}</small></div>
      <span class="moon">${hr < 6 || hr >= 22 ? NIGHT : ''}</span><time class="num">${t}<small>${ap}</small>${badge}</time>${clkEdit ? `<button class="clk-del" data-clk-del="${i}" aria-label="Remove ${esc(city)}">×</button>` : ''}</div>`;
  }).join('');
}
// Adding a city: type a few letters, pick from the matches. Time zone names cover most cities; a few big ones that share a zone are added by hand.
const CLK_ALIAS = {
  'San Francisco': 'America/Los_Angeles', Seattle: 'America/Los_Angeles', Boston: 'America/New_York', Washington: 'America/New_York', Miami: 'America/New_York', Atlanta: 'America/New_York',
  Austin: 'America/Chicago', Dallas: 'America/Chicago', Houston: 'America/Chicago', Beijing: 'Asia/Shanghai', Shenzhen: 'Asia/Shanghai', Osaka: 'Asia/Tokyo', Munich: 'Europe/Berlin',
  Barcelona: 'Europe/Madrid', Milan: 'Europe/Rome', Geneva: 'Europe/Zurich', 'Abu Dhabi': 'Asia/Dubai', Riyadh: 'Asia/Riyadh', Manchester: 'Europe/London', Edinburgh: 'Europe/London' };
let clkZones = null;
function clkFind(q) {
  if (!clkZones) {
    let zs = []; try { zs = Intl.supportedValuesOf('timeZone'); } catch (e) {}
    clkZones = [...zs.filter((z) => z.includes('/') && !z.startsWith('Etc/')).map((z) => [z.split('/').pop().replace(/_/g, ' '), z]), ...Object.entries(CLK_ALIAS)];
  }
  q = q.trim().toLowerCase(); if (!q) return [];
  const have = new Set(CFG.clocks.map((c) => c.label.toLowerCase()));
  return clkZones.filter(([n]) => n.toLowerCase().includes(q) && !have.has(n.toLowerCase()))
    .sort((a, b) => (b[0].toLowerCase().startsWith(q) - a[0].toLowerCase().startsWith(q)) || a[0].localeCompare(b[0])).slice(0, 6);
}
async function clkSave(list, done) {
  const r = await setApi('/clocks', { clocks: list });
  if (!r.ok) { snack(r.error || 'That did not save.', { bad: true }); return; }
  CFG.clocks = r.clocks; tick();
  if (done) snack(done);
}
function clkFindClose() { $('#clocks-find').hidden = true; $('#clocks-q').value = ''; $('#clocks-hits').innerHTML = ''; }
$('#clocks-add').onclick = () => { const f = $('#clocks-find'); if (!f.hidden) return clkFindClose(); f.hidden = false; $('#clocks-q').focus(); };
$('#clocks-edit').onclick = () => { clkEdit = !clkEdit; clocks(); };
$('#clocks-q').oninput = (e) => {
  const hits = clkFind(e.target.value);
  $('#clocks-hits').innerHTML = hits.length ? hits.map(([n, z]) => `<button class="clk-hit" data-clk-add="${esc(n)}|${esc(z)}"><b>${esc(n)}</b><small>${esc(z.split('/')[0].replace(/_/g, ' '))}</small></button>`).join('')
    : e.target.value.trim() ? '<div class="empty">No city by that name. Try a nearby big city.</div>' : '';
};
$('#clocks-q').onkeydown = (e) => { if (e.key === 'Escape') clkFindClose(); if (e.key === 'Enter') $('#clocks-hits .clk-hit')?.click(); };
$('#clocks-hits').onclick = (e) => { const b = e.target.closest('[data-clk-add]'); if (!b) return; const [label, tz] = b.dataset.clkAdd.split('|'); clkFindClose(); clkSave([...CFG.clocks, { label, tz }]); };
$('#clocks').onclick = (e) => { const b = e.target.closest('[data-clk-del]'); if (!b) return; const prev = [...CFG.clocks], gone = prev[+b.dataset.clkDel];
  clkSave(prev.filter((_, i) => i !== +b.dataset.clkDel), `Removed ${gone.label}`); };

// ---------- Assistant extras: location, agenda, FX ----------
// fresh: read the calendar feed again instead of the server's few-minute cache (refresh button)
async function loadExtras(fresh) {
  try { X = await getJSON('/api/bot/extras' + (fresh ? '?fresh=1' : '')); loadExtras.at = Date.now(); } catch (e) { X = X || {}; }
  if (X.location) try { localStorage.setItem('wxloc', JSON.stringify(X.location)); } catch (e) {}
  if (typeof renderToday === 'function') renderToday();
  weather(); tick();
}
let hrHold = null, hrHeld = false;
$('#home-refresh').onpointerdown = () => { hrHeld = false; clearTimeout(hrHold);
  hrHold = setTimeout(() => { hrHeld = true; $('#home-refresh').classList.add('spin'); location.reload(); }, 600); };
['pointerup', 'pointerleave', 'pointercancel'].forEach((ev) => $('#home-refresh').addEventListener(ev, () => clearTimeout(hrHold)));
$('#home-refresh').oncontextmenu = (e) => e.preventDefault();
$('#home-refresh').onclick = () => { if (!hrHeld) spinning($('#home-refresh'), () => Promise.all([loadExtras(true), typeof status === 'function' ? status() : null])); };
const WX = { 0: 'Clear', 1: 'Mostly clear', 2: 'Partly cloudy', 3: 'Cloudy', 45: 'Foggy', 48: 'Foggy', 51: 'Light drizzle', 53: 'Drizzle',
  55: 'Drizzle', 61: 'Light rain', 63: 'Rain', 65: 'Heavy rain', 71: 'Light snow', 73: 'Snow', 75: 'Heavy snow', 80: 'Showers',
  81: 'Showers', 82: 'Heavy showers', 95: 'Thunderstorms', 96: 'Thunderstorms', 99: 'Thunderstorms' };
// The last forecast is kept on the phone, so the card shows it the moment the page opens and refreshes behind it every 15 minutes.
const WX_TTL = 15 * 60000, wxKey = (l) => `${l.lat},${l.lon}`;
const stored = (k) => { try { return JSON.parse(localStorage.getItem(k) || 'null'); } catch (e) { return null; } };
const wxLoc = () => X.location || stored('wxloc') || { city: CFG.home_city || 'London', lat: CFG.home_lat ?? 51.51, lon: CFG.home_lon ?? -0.13 };
let wxCache = (({ key, at, w, air } = stored('wx') || {}) => (w ? { key, at, p: Promise.resolve([w, air]) } : null))();
function wxData(force) {  // forecast + air quality, shared by the card and the weather screen
  const loc = wxLoc(), key = wxKey(loc);
  if (!force && wxCache && wxCache.key === key && Date.now() - wxCache.at < WX_TTL) return wxCache.p;
  const q = `latitude=${loc.lat}&longitude=${loc.lon}&timezone=auto`;
  const p = Promise.all([
    getJSON(`https://api.open-meteo.com/v1/forecast?${q}&forecast_days=10`
      + '&current=temperature_2m,apparent_temperature,relative_humidity_2m,dew_point_2m,weather_code,is_day,wind_speed_10m,wind_direction_10m,wind_gusts_10m,pressure_msl,visibility,uv_index,precipitation'
      + '&hourly=temperature_2m,weather_code,precipitation_probability,is_day'
      + '&daily=weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,precipitation_sum,sunrise,sunset,uv_index_max'),
    getJSON(`https://air-quality-api.open-meteo.com/v1/air-quality?${q}&current=us_aqi,pm2_5`).catch(() => null)]);
  const prev = wxCache;
  wxCache = { key, at: Date.now(), p };
  p.then(([w, air]) => { try { localStorage.setItem('wx', JSON.stringify({ key, at: Date.now(), w, air })); } catch (e) {} },
    () => { wxCache = prev && prev.key === key ? prev : null; });  // offline: keep showing the last one
  return p;
}
function paintWeather(w, at) {
  const c = w.current, d = w.daily, rain = d.precipitation_probability_max[0], old = Date.now() - at > WX_TTL;
  $('#weather').innerHTML = `<div class="deg num">${Math.round(c.temperature_2m)}°</div>
      <div><div class="t">${esc(WX[c.weather_code] || 'Mixed')}</div><div class="d">${old ? 'Updated ' + new Date(at).toLocaleTimeString('en-US', T12) : `Feels like ${Math.round(c.apparent_temperature)}°`}</div></div>
      <div class="r num">${Math.round(d.temperature_2m_min[0])}° – ${Math.round(d.temperature_2m_max[0])}°<br>${rain}% rain${X.fx?.rates?.length ? `<br>1 ${esc(X.fx.rates[0][0])} ₹${X.fx.rates[0][1]}` : ''}</div>`;
}
async function weather() {
  const mine = wxCache && wxCache.key === wxKey(wxLoc()) ? wxCache : null;
  if (mine) try { paintWeather((await mine.p)[0], mine.at); } catch (e) {}  // the last one, straight away
  if (mine && Date.now() - mine.at < WX_TTL) return;
  try { const [w] = await wxData(); paintWeather(w, Date.now()); }
  catch { if (!mine) $('#weather .d').textContent = 'Weather unavailable right now'; }
}

// Line icons in the page's own style, picked from the weather code and day or night.
const WI = {
  sun: '<circle cx="12" cy="12" r="4.2"/><path d="M12 2.5v2M12 19.5v2M4.6 4.6l1.4 1.4M18 18l1.4 1.4M2.5 12h2M19.5 12h2M4.6 19.4 6 18M18 6l1.4-1.4"/>',
  moon: '<path d="M20 14.5A8 8 0 1 1 9.5 4a6.3 6.3 0 0 0 10.5 10.5z"/>',
  cloud: '<path d="M7 18.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 11.5a3.5 3.5 0 0 0 0 7z"/>',
  part: '<path d="M8.5 3.2v1.3M3.6 8.5H2.3M4.9 4.9l.9.9M12.1 4.9l-.9.9"/><path d="M5.2 10.6a3.6 3.6 0 0 1 6.6-2.9"/><path d="M9 20h8.5a3.5 3.5 0 0 0 .5-6.96A4.8 4.8 0 0 0 9 13.6a3.2 3.2 0 0 0 0 6.4z"/>',
  partn: '<path d="M11.5 6.6A4.2 4.2 0 0 1 6 11.2a4.2 4.2 0 0 0 5.5-4.6z"/><path d="M9 20h8.5a3.5 3.5 0 0 0 .5-6.96A4.8 4.8 0 0 0 9 13.6a3.2 3.2 0 0 0 0 6.4z"/>',
  drizzle: '<path d="M7 14.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 7.5a3.5 3.5 0 0 0 0 7z"/><path d="M9 18v.5M13 18v.5M17 18v.5M11 21v.5M15 21v.5"/>',
  rain: '<path d="M7 14.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 7.5a3.5 3.5 0 0 0 0 7z"/><path d="M9 17.5l-1 3M13 17.5l-1 3M17 17.5l-1 3"/>',
  storm: '<path d="M7 14.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 7.5a3.5 3.5 0 0 0 0 7z"/><path d="M12.5 15.5 10.5 19h3l-2 3.5"/>',
  snow: '<path d="M7 14.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 7.5a3.5 3.5 0 0 0 0 7z"/><path d="M9 18.5h.01M13 18.5h.01M17 18.5h.01M11 21.5h.01M15 21.5h.01"/>',
  fog: '<path d="M7 12.5h10a4 4 0 0 0 .6-7.95A5.5 5.5 0 0 0 7 5.5a3.5 3.5 0 0 0 0 7z"/><path d="M4 16h16M6 19.5h12"/>',
  rise: '<path d="M4 18h16M7.5 18a4.5 4.5 0 0 1 9 0M12 4v6M9.5 6.5 12 4l2.5 2.5"/>',
  set: '<path d="M4 18h16M7.5 18a4.5 4.5 0 0 1 9 0M12 4v6M9.5 7.5 12 10l2.5-2.5"/>',
  drop: '<path d="M12 3.5s-6 6.6-6 10.5a6 6 0 0 0 12 0c0-3.9-6-10.5-6-10.5z"/>',
  wind: '<path d="M3 8.5h11a3 3 0 1 0-3-3M3 12.5h15a3 3 0 1 1-3 3M3 16.5h7"/>',
  therm: '<path d="M10 14.5V5a2 2 0 0 1 4 0v9.5a4 4 0 1 1-4 0z"/>',
  leaf: '<path d="M5 19c0-8 5-13 15-14-1 10-6 15-14 15M5 19l7-7"/>',
  eye: '<path d="M2.5 12S6 5.5 12 5.5 21.5 12 21.5 12 18 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  gauge: '<path d="M4.5 17a8.5 8.5 0 1 1 15 0M12 13l3.5-4"/>',
  cal: '<rect x="3.5" y="5" width="17" height="15" rx="2.5"/><path d="M3.5 10h17M8 3v4M16 3v4"/>',
  clock: '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3 2"/>',
};
const wIcon = (k, cls = 'wx-ic') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${WI[k]}</svg>`;
const wxKind = (code, day = 1) => code <= 1 ? (day ? 'sun' : 'moon') : code === 2 ? (day ? 'part' : 'partn') : code === 3 ? 'cloud' : code <= 48 ? 'fog'
  : code <= 57 ? 'drizzle' : code <= 67 || (code >= 80 && code <= 82) ? 'rain' : code <= 77 || code === 85 || code === 86 ? 'snow' : code >= 95 ? 'storm' : 'cloud';
const hm = (iso) => iso.slice(11, 16);
const compass = (deg) => ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west'][Math.round(deg / 45) % 8];
const uvLevel = (u) => u < 3 ? 'Low' : u < 6 ? 'Moderate' : u < 8 ? 'High' : u < 11 ? 'Very high' : 'Extreme';
const aqiLevel = (a) => a <= 50 ? 'Good' : a <= 100 ? 'Moderate' : a <= 150 ? 'Unhealthy for some' : a <= 200 ? 'Unhealthy' : a <= 300 ? 'Very unhealthy' : 'Hazardous';
const hourName = (iso) => { const h = +iso.slice(11, 13); return h === 0 ? 'midnight' : h === 12 ? 'noon' : `${h % 12} ${h < 12 ? 'AM' : 'PM'}`; };

function wxSummary(w, i0) {  // one plain sentence about the next 12 hours
  const H = w.hourly, c = w.current, wet = (k) => H.precipitation_probability[k] >= 50 || (H.weather_code[k] >= 51 && H.weather_code[k] !== 45 && H.weather_code[k] !== 48);
  const out = [];
  if (c.weather_code >= 51 && c.weather_code < 95 || c.precipitation > 0) {
    let k = i0; while (k < i0 + 12 && wet(k)) k++;
    out.push(k < i0 + 12 ? `Rain should ease around ${hourName(H.time[k])}.` : 'Rain on and off for the next few hours.');
  } else {
    let k = i0 + 1; while (k < i0 + 12 && !wet(k)) k++;
    out.push(k < i0 + 12 ? `Rain likely around ${hourName(H.time[k])}.` : 'Dry for the next 12 hours.');
  }
  if (c.wind_gusts_10m >= 40) out.push(`Gusts up to ${Math.round(c.wind_gusts_10m)} km/h.`);
  if (w.daily.uv_index_max[0] >= 8 && +c.time.slice(11, 13) < 15) out.push('Strong sun today, UV is very high.');
  return out.join(' ');
}

function renderWx(w, air) {
  const c = w.current, H = w.hourly, D = w.daily, loc = wxLoc();
  const i0 = Math.max(0, H.time.findIndex((t) => t.slice(0, 13) === c.time.slice(0, 13)));
  // hourly: now + 24 hours, with sunrise and sunset slotted in
  const sun = D.sunrise.map((t) => ['rise', t]).concat(D.sunset.map((t) => ['set', t]));
  let hours = '';
  for (let k = i0; k <= i0 + 24 && k < H.time.length; k++) {
    const pp = H.precipitation_probability[k];
    hours += `<div class="wx-h"><span>${k === i0 ? 'Now' : hm(H.time[k])}</span>${wIcon(wxKind(H.weather_code[k], H.is_day[k]))}
      <span class="pp">${pp >= 20 ? pp + '%' : ''}</span><b class="num">${Math.round(k === i0 ? c.temperature_2m : H.temperature_2m[k])}°</b></div>`;
    for (const [kind, t] of sun) if (t.slice(0, 13) === H.time[k].slice(0, 13) && k > i0 - 1 && t > c.time)
      hours += `<div class="wx-h"><span>${hm(t)}</span>${wIcon(kind)}<span class="pp"></span><b>${kind === 'rise' ? 'Sunrise' : 'Sunset'}</b></div>`;
  }
  // 10 days: range bars on one shared scale, today's dot at the current temperature
  const lo = Math.min(...D.temperature_2m_min), hi = Math.max(...D.temperature_2m_max), pos = (t) => ((t - lo) / (hi - lo || 1)) * 100;
  const days = D.time.map((t, i) => {
    const name = i === 0 ? 'Today' : new Date(t + 'T12:00').toLocaleDateString('en-GB', { weekday: 'short' }), pp = D.precipitation_probability_max[i];
    return `<div class="wx-day"><span class="dn">${name}</span>${wIcon(wxKind(D.weather_code[i]))}<span class="pp">${pp >= 20 ? pp + '%' : ''}</span>
      <span class="lo num">${Math.round(D.temperature_2m_min[i])}°</span>
      <span class="wx-bar"><i style="left:${pos(D.temperature_2m_min[i])}%;right:${100 - pos(D.temperature_2m_max[i])}%"></i>${i === 0 ? `<em style="left:${pos(c.temperature_2m)}%"></em>` : ''}</span>
      <span class="hi num">${Math.round(D.temperature_2m_max[i])}°</span></div>`;
  }).join('');
  // detail tiles
  const feels = Math.round(c.apparent_temperature), temp = Math.round(c.temperature_2m);
  const nextSun = [...sun].filter(([, t]) => t > c.time).sort((a, b) => a[1] < b[1] ? -1 : 1);
  const [sk, st] = nextSun[0] || ['set', D.sunset[0]], other = nextSun[1];
  const tile = (icon, label, big, sub, extra = '') => `<div class="card wx-tile"><h3>${wIcon(icon, '')}${label}</h3>${big}${extra}<small>${sub}</small></div>`;
  const aqi = air?.current?.us_aqi;
  const tiles = [
    tile('therm', 'Feels like', `<b class="num">${feels}°</b>`, feels > temp + 1 ? 'Humidity makes it feel warmer.' : feels < temp - 1 ? 'Wind makes it feel cooler.' : 'Close to the actual temperature.'),
    tile('drop', 'Humidity', `<b class="num">${Math.round(c.relative_humidity_2m)}%</b>`, `The dew point is ${Math.round(c.dew_point_2m)}° right now.`),
    tile('sun', 'UV index', `<b class="num">${Math.round(c.uv_index)}</b><span class="lv">${uvLevel(c.uv_index)}</span>`,
      `Peaks at ${Math.round(D.uv_index_max[0])} today.`, `<div class="wx-scale"><em style="left:${Math.min(100, c.uv_index / 11 * 100)}%"></em></div>`),
    aqi != null ? tile('leaf', 'Air quality', `<b class="num">${Math.round(aqi)}</b><span class="lv">${aqiLevel(aqi)}</span>`,
      `PM2.5 at ${Math.round(air.current.pm2_5)} µg/m³.`, `<div class="wx-scale"><em style="left:${Math.min(100, aqi / 300 * 100)}%"></em></div>`) : '',
    tile('wind', 'Wind', `<b class="num">${Math.round(c.wind_speed_10m)}<span class="lv"> km/h</span></b>`, `From the ${compass(c.wind_direction_10m)}, gusts to ${Math.round(c.wind_gusts_10m)} km/h.`),
    tile(sk, sk === 'rise' ? 'Sunrise' : 'Sunset', `<b class="num">${hm(st)}</b>`, other ? `${other[0] === 'rise' ? 'Sunrise' : 'Sunset'} at ${hm(other[1])}.` : ''),
    tile('drop', 'Rain', `<b class="num">${D.precipitation_sum[0].toFixed(D.precipitation_sum[0] < 10 ? 1 : 0)}<span class="lv"> mm</span></b>`,
      D.precipitation_sum[1] > 0.2 ? `${D.precipitation_sum[1].toFixed(1)} mm expected tomorrow.` : 'Expected today. Little or none tomorrow.'),
    tile('eye', 'Visibility', `<b class="num">${c.visibility >= 10000 ? Math.round(c.visibility / 1000) : (c.visibility / 1000).toFixed(1)}<span class="lv"> km</span></b>`,
      c.visibility >= 10000 ? 'Clear view.' : c.visibility >= 4000 ? 'Slightly hazy.' : 'Haze or fog is cutting the view.'),
  ].filter(Boolean);
  if (tiles.length % 2) tiles.push(tile('gauge', 'Pressure', `<b class="num">${Math.round(c.pressure_msl)}<span class="lv"> hPa</span></b>`, 'At sea level.'));
  $('#wx-body').innerHTML = `
    <div class="wx-hero"><div class="city">${esc(loc.city)}</div><div class="big num">${temp}°</div>
      <div class="cond">${esc(WX[c.weather_code] || 'Mixed')}</div>
      <div class="hl num">H ${Math.round(D.temperature_2m_max[0])}°  L ${Math.round(D.temperature_2m_min[0])}°</div></div>
    <div class="card wx-card"><p>${esc(wxSummary(w, i0))}</p><div class="wx-hours">${hours}</div></div>
    <div class="card wx-card" style="animation-delay:40ms"><h3>${wIcon('cal', '')}10-day forecast</h3>${days}</div>
    <div class="wx-tiles">${tiles.join('')}</div>
    <p class="wx-src">Open-Meteo • updated ${new Date().toLocaleTimeString('en-US', T12)}</p>`;
}
async function loadWx(force) {
  if (!$('#wx-body').innerHTML) $('#wx-body').innerHTML = '<div class="skel" style="height:200px;margin-top:16px"></div><div class="skel"></div><div class="skel" style="height:300px"></div>';
  try { const [w, air] = await wxData(force); renderWx(w, air); weather(); }
  catch { $('#wx-body').innerHTML = '<div class="err" style="margin-top:16px">Weather is unavailable right now. Try again in a minute.</div>'; }
}
function openWx() { $('#wxp').hidden = false; document.body.style.overflow = 'hidden'; $('#wxp .panel-body').scrollTop = 0; loadWx(); }
function closeWx() { $('#wxp').hidden = true; document.body.style.overflow = ''; }
$('#weather').onclick = openWx;
$('#weather').onkeydown = (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openWx(); } };
document.querySelector('[data-close-wx]').onclick = closeWx;
$('#wx-refresh').onclick = () => spinning($('#wx-refresh'), () => loadWx(true));
