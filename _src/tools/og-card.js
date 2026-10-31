const { chromium } = require('playwright'); const { execSync } = require('child_process');
(async () => {
  const b = await chromium.launch();
  let pg = await b.newPage({ viewport:{width:2240,height:2200}, deviceScaleFactor:1 });
  await pg.goto('http://localhost:8765/_src/tools/og-map.html');
  await pg.waitForSelector('#tars2-map.is-ready',{timeout:30000}); await pg.waitForTimeout(6000);
  await pg.locator('#tars2-map').screenshot({ path: '_src/tools/.og-map-raw.png' }); await pg.close();
  console.log(execSync('python3 -c \"from PIL import Image; Image.open('_src/tools/.og-map-raw.png').convert('RGB').resize((1120,1100),Image.LANCZOS).save('_src/tools/.og-map.png')\"').toString());
  pg = await b.newPage({ viewport:{width:1200,height:630}, deviceScaleFactor:1 });
  await pg.goto('http://localhost:8765/_src/tools/og-card.html'); await pg.waitForTimeout(2500);
  await pg.screenshot({ path: 'assets/img/og-cybertruck-stats.jpg', type:'jpeg', quality:90 });
  const p2 = await b.newPage({ viewport:{width:1200,height:630}, deviceScaleFactor:2 });
  await p2.goto('http://localhost:8765/_src/tools/og-card.html'); await p2.waitForTimeout(2500);
  await p2.screenshot({ path: process.argv[2], type:'png' });
  await b.close();
})();
