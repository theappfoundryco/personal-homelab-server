// Loads the views of the modules that are switched on, then starts the page.
// Each module lists its files under dashboard: web: in module.yaml and serves them from /m/<module>/web/.
// If the assistant cannot be reached, every built-in view loads, as before.
(async () => {
  const BUILT_IN = [['gym', 'gym'], ['server', 'server'], ['journal', 'journal'], ['health', 'sg']];  // load order, and the tab each one owns
  let mods = null;
  try { mods = (await getJSON('/api/bot/modules')).modules; } catch (e) {}
  const on = mods ? mods.filter((m) => (m.web || []).length) : BUILT_IN.map(([name]) => ({ name, web: ['view.js'] }));
  on.sort((a, b) => (BUILT_IN.findIndex(([n]) => n === a.name) + 1 || 99) - (BUILT_IN.findIndex(([n]) => n === b.name) + 1 || 99));
  if (mods) {
    const tabs = new Set(mods.filter((m) => m.tab).map((m) => m.tab.id));
    BUILT_IN.forEach(([, tab]) => { if (!tabs.has(tab)) { const b = document.querySelector(`.tab[data-tab="${tab}"]`); if (b) b.hidden = true; } });
  }
  const load = (src) => new Promise((ok) => { const s = document.createElement('script'); s.src = src; s.async = false; s.onload = s.onerror = ok; document.body.appendChild(s); });
  for (const m of on) for (const f of m.web) await load(`/m/${m.name}/web/${f}`);
  await CFG_READY;
  applyLayout();
  showNeeds();
  if (typeof wizardInit === 'function') wizardInit();
  await load('js/start.js');
})();
