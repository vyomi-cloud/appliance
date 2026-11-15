// usage: node run_browser.cjs <url>; Playwright from portal-OLD node_modules
const { chromium } = require('/Users/sudhirganti/Applications/simulator/portal-OLD/node_modules/playwright');
(async () => {
  const b = await chromium.launch({ args: ['--enable-unsafe-webgpu'] }); const p = await b.newPage();
  p.on('console', m => process.stderr.write('[console] ' + m.text().slice(0, 200) + '\n'));
  await p.goto(process.argv[2]);
  console.log(JSON.stringify(await p.evaluate(() => window.RESULT), null, 1)); await b.close();
})();
