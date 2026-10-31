// Rebuilds the stats page share card (assets/img/og-cybertruck-stats.jpg, 2400x1260).
// Run from the repo root with a static server on :8765 serving the repo:
//   python3 -m http.server 8765 &   NODE_PATH=$(npm root -g) node _src/tools/og-card.js [extra-png-path]
// Numbers on the card live in _src/tools/og-card.html; update them there first.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const b = await chromium.launch();
  const m = await b.newPage({ viewport: { width: 2240, height: 2200 }, deviceScaleFactor: 1 });
  await m.goto('http://localhost:8765/_src/tools/og-map.html');
  await m.waitForSelector('#tars2-map.is-ready', { timeout: 30000 });
  await m.waitForTimeout(6000);
  await m.locator('#tars2-map').screenshot({ path: '_src/tools/.og-map.png' });
  await m.close();
  const shot = async (scale, opts) => {
    const p = await b.newPage({ viewport: { width: 1200, height: 630 }, deviceScaleFactor: scale });
    await p.goto('http://localhost:8765/_src/tools/og-card.html');
    await p.waitForTimeout(3000);
    await p.screenshot(opts);
    await p.close();
  };
  await shot(2, { path: 'assets/img/og-cybertruck-stats.jpg', type: 'jpeg', quality: 92 });
  if (process.argv[2]) await shot(3, { path: process.argv[2], type: 'png' });
  await b.close();
  fs.rmSync('_src/tools/.og-map.png', { force: true });
})();
