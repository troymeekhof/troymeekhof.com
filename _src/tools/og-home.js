// Rebuilds the homepage share card (assets/img/og-home.jpg, 2400x1260) from _src/tools/og-home.html.
// Run from the repo root with a static server on :8765 serving the repo:
//   python3 -m http.server 8765 &   NODE_PATH=$(npm root -g) node _src/tools/og-home.js [x-post-png-path]
// The optional path also writes the 16:9 X-post version (2400x1350 PNG).
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch();
  const shot = async (q, h, opts) => {
    const p = await b.newPage({ viewport: { width: 1200, height: h }, deviceScaleFactor: 2 });
    await p.goto('http://localhost:8765/_src/tools/og-home.html' + q);
    await p.waitForTimeout(2500);
    await p.screenshot(opts);
    await p.close();
  };
  await shot('', 630, { path: 'assets/img/og-home.jpg', type: 'jpeg', quality: 90 });
  if (process.argv[2]) await shot('?x', 675, { path: process.argv[2], type: 'png' });
  await b.close();
})();
