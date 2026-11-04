// ---------- Sections (briefing and news come from the assistant as ready-made lines) ----------
// Briefing and news sections come from the bot with emoji (Telegram needs them); the page shows line icons instead.
const SVG = (d) => `<svg class="si" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${d}</svg>`;
const SEC_ICON = {
  weather: '<path d="M12 2v2M4.9 4.9l1.4 1.4M20 12h2M19.1 4.9l-1.4 1.4M16 12.6A4 4 0 0 0 8.1 11"/><path d="M13 22H7a5 5 0 1 1 4.9-6H13a3 3 0 0 1 0 6Z"/>',
  today: '<rect x="4" y="5" width="16" height="15" rx="2.5"/><path d="M4 10h16M9 3v4M15 3v4"/>',
  travel: '<path d="M17.8 19.2 16 11l3.5-3.5C21 6 21.5 4 21 3c-1-.5-3 0-4.5 1.5L13 8 4.8 6.2c-.5-.1-.9.1-1.1.5l-.3.5c-.2.5-.1 1 .3 1.3L9 12l-2 3H4l-1 1 3 2 2 3 1-1v-3l3-2 3.5 5.3c.3.4.8.5 1.3.3l.5-.2c.4-.3.6-.7.5-1.2z"/>',
  reminders: '<circle cx="12" cy="13" r="8"/><path d="M12 9v4l2 2M5 3 2 6M22 6l-3-3"/>',
  notes: '<rect x="5" y="3" width="14" height="18" rx="2.5"/><path d="M9 8h6M9 12h6M9 16h4"/>',
  money: '<circle cx="12" cy="12" r="9"/><path d="M15 9.5c-.5-1-1.6-1.5-3-1.5-1.7 0-3 .8-3 2s1.3 1.7 3 2 3 .8 3 2-1.3 2-3 2c-1.4 0-2.5-.5-3-1.5M12 6v2M12 16v2"/>',
  world: '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
  india: '<path d="M5 21V4M5 4h12l-2.5 4L17 12H5"/>',
  f1: '<path d="M4 21V4h15v9H4"/><path d="M9 4v9M14 4v9M4 8.5h15"/>',
  cricket: '<circle cx="12" cy="12" r="9"/><path d="M8 4.5c2 4.5 2 10.5 0 15M16 4.5c-2 4.5-2 10.5 0 15"/>',
  tech: '<rect x="3" y="4" width="18" height="12" rx="2"/><path d="M2 20h20"/>',
  business: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>',
  science: '<path d="M9 3h6M10 3v6l-5.5 9.5A2 2 0 0 0 6.2 21.5h11.6a2 2 0 0 0 1.7-3L14 9V3"/><path d="M7 15h10"/>',
  new: '<path d="M4.5 16.5c-1.5 1.3-2 5-2 5s3.7-.5 5-2c.7-.8.7-2.1-.1-2.9a2.2 2.2 0 0 0-2.9-.1z"/><path d="M12 15l-3-3a22 22 0 0 1 2-3.9A12.9 12.9 0 0 1 22 2c0 2.7-.8 7.5-6 11a22 22 0 0 1-4 2z"/><path d="M9 12H4s.6-3 2-4c1.6-1.1 5 0 5 0M12 15v5s3-.6 4-2c1.1-1.6 0-5 0-5"/>',
  server: '<rect x="3.5" y="4" width="17" height="6.5" rx="2"/><rect x="3.5" y="13.5" width="17" height="6.5" rx="2"/><path d="M7 7.25h.01M7 16.75h.01M13 7.25h4M13 16.75h4"/>',
};
const noEmoji = (t) => String(t).replace(/[\p{Extended_Pictographic}\p{Regional_Indicator}\uFE0E\uFE0F\u200D]/gu, '').replace(/\s{2,}/g, ' ').trim();
const secKey = (n) => { const k = noEmoji(n).toLowerCase(); return k === 'formula 1' ? 'f1' : k.split(/[\s&]/)[0]; };
const secHTML = (s, i) => { const name = noEmoji(s.name), ic = SEC_ICON[secKey(s.name)];
  return `<div class="card sec" style="animation-delay:${i * 40}ms"><h3>${ic ? SVG(ic) : ''}${esc(name)}${s.sub ? `<small>${esc(s.sub)}</small>` : ''}</h3>
  <ul>${s.rows.map(noEmoji).map((r) => r.startsWith('•') ? `<li>${r.slice(1).trim()}</li>` : `<li class="plain">${r}</li>`).join('')}</ul></div>`; };

async function loadNews() {
  const body = $('#news-body');
  body.innerHTML = '<div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  try {
    const n = await getJSON('/api/bot/news');
    body.innerHTML = n.sections.map(secHTML).join('') || '<div class="err">No news right now.</div>';
    loaded.news = Date.now();
    $('#news-when').textContent = 'Updated ' + new Date().toLocaleTimeString('en-US', T12);
  } catch { body.innerHTML = '<div class="err">News is unavailable right now. Try again in a minute.</div>'; }
}
$('#news-refresh').onclick = () => spinning($('#news-refresh'), loadNews);
function openNews() {
  $('#newsp').hidden = false; document.body.style.overflow = 'hidden';
  if (!loaded.news || Date.now() - loaded.news > 10 * 60000) loadNews();
}
function closeNews() { $('#newsp').hidden = true; document.body.style.overflow = ''; }
$('#news-open').onclick = openNews;
document.querySelector('[data-close-news]').onclick = closeNews;

// ---------- Briefing ----------
async function loadBrief() {
  const body = $('#brief-body');
  body.innerHTML = '<div class="skel" style="height:60px"></div><div class="skel"></div><div class="skel"></div><div class="skel"></div>';
  try {
    const b = await getJSON('/api/bot/brief');
    body.innerHTML = `<h1 class="brief-title">${esc(b.title)}</h1><p class="page-sub" style="margin-bottom:16px">${esc(b.city)} • ${new Date(b.at * 1000).toLocaleString('en-GB', { weekday: 'long', day: 'numeric', month: 'long', hour: 'numeric', minute: '2-digit', hour12: true }).replace(/\b(am|pm)\b/g, (x) => x.toUpperCase())}</p>`
      + b.sections.map(secHTML).join('');
  } catch { body.innerHTML = '<div class="err">Couldn’t make your briefing. Try again in a minute.</div>'; }
}
function openBrief() { $('#brief').hidden = false; document.body.style.overflow = 'hidden'; loadBrief(); }
function closeBrief() { $('#brief').hidden = true; document.body.style.overflow = ''; }
$('#brief-open').onclick = openBrief;
$('#brief-refresh').onclick = () => spinning($('#brief-refresh'), loadBrief);
document.querySelector('[data-close-brief]').onclick = closeBrief;
