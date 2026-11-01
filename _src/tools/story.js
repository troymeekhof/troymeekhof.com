// Instagram story previews (2160x3840) for the homepage and the stats page.
// Run from the repo root with a static server on :8765 serving the repo:
//   python3 -m http.server 8765 &   NODE_PATH=$(npm root -g) node _src/tools/story.js OUT_DIR
// Takes fresh 390-wide phone screenshots of the live pages, then renders _src/tools/story.html.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const out = process.argv[2] || '.';
  const b = await chromium.launch();
  for (const [u, n] of [['/', 'home'], ['/cybertruck/stats/', 'stats']]) {
    const p = await b.newPage({ viewport: { width: 390, height: 1100 }, deviceScaleFactor: 4, colorScheme: 'light', isMobile: true, hasTouch: true });
    await p.goto('http://localhost:8765' + u); await p.waitForTimeout(5000);
    await p.screenshot({ path: '_src/tools/.mob-' + n + '.png' }); await p.close();
  }
  for (const n of ['home', 'stats']) {
    const p = await b.newPage({ viewport: { width: 540, height: 960 }, deviceScaleFactor: 4 });
    await p.goto('http://localhost:8765/_src/tools/story.html?p=' + n); await p.waitForTimeout(2500);
    await p.screenshot({ path: out + '/story-' + n + '.png' }); await p.close();
  }
  await b.close();
  for (const n of ['home', 'stats']) fs.rmSync('_src/tools/.mob-' + n + '.png', { force: true });
})();
