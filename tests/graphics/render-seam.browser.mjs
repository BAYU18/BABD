// Task 1 — browser pipeline tracer bullet.
//
// Proves the descriptor seam is wired end-to-end in a real browser: the page
// loads with zero non-file:///data: requests, steps deterministically, and
// renderState() returns the six layers. Later tasks extend this file with
// pixel, HUD, preference and viewport assertions.
import puppeteer from 'puppeteer';
import { fileURLToPath } from 'node:url';
import { dirname, resolve } from 'node:path';

const __dirname = dirname(fileURLToPath(import.meta.url));
const GAME = 'file://' + resolve(__dirname, '..', '..', 'index.html');
const CHROME = process.env.CHROME_BIN || '/tmp/chrome-extract/chrome-linux64/chrome';

const checks = [];
function check(name, ok, detail) {
  checks.push({ name, ok: !!ok, detail: detail === undefined ? '' : String(detail) });
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${name}${detail !== undefined ? ' — ' + detail : ''}`);
}

const browser = await puppeteer.launch({
  headless: 'new',
  executablePath: CHROME,
  args: ['--no-sandbox', '--allow-file-access-from-files', '--disable-gpu', '--mute-audio'],
});

try {
  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });

  const requests = [];
  const consoleErrors = [];
  page.on('request', (req) => requests.push(req.url()));
  page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text()); });
  page.on('pageerror', (err) => consoleErrors.push(String(err && err.message || err)));

  await page.goto(GAME, { waitUntil: 'load' });
  await new Promise((r) => setTimeout(r, 150));

  const result = await page.evaluate(async () => {
    const G = window.__GAME__;
    G.start();
    G.pause();
    for (let i = 0; i < 120; i++) G.step(1 / 60);
    await new Promise((r) => requestAnimationFrame(r));
    const rs = G.renderState();
    return {
      hasRenderState: !!rs,
      layerIds: rs ? rs.layers.map((l) => l.id) : null,
      layerCount: rs ? rs.layers.length : -1,
      canvas: rs ? rs.canvas : null,
    };
  });

  const external = requests.filter((u) => !(u.startsWith('file://') || u.startsWith('data:')));
  const expectedIds = ['road', 'scenery', 'cars', 'effects', 'hud', 'lighting'];

  // ---- Task 2: road pixel check ----------------------------------------
  // Note: the headless rasterizer composites the CSS-scaled canvas, so exact
  // logical columns (0/199) do not read back the drawn colour even on the
  // pristine baseline (col0 is uniformly 88-grey there too). We therefore
  // classify the whole backing store by palette instead of sampling columns.
  const road = await page.evaluate(async () => {
    const G = window.__GAME__;
    G.start(); G.pause();
    for (let i = 0; i < 60; i++) G.step(1 / 60);
    await new Promise((r) => requestAnimationFrame(r));
    const cvs = document.getElementById('game');
    const ctx = cvs.getContext('2d');
    const img = ctx.getImageData(0, 0, cvs.width, cvs.height).data;
    let asphaltGreen = 0, dashGrey = 0, nearWhite = 0;
    for (let i = 0; i < img.length; i += 4) {
      const r = img[i], g = img[i + 1], b = img[i + 2];
      if (g > r && g > b && g > 10 && g < 60) asphaltGreen++;
      if (Math.abs(r - 207) < 25 && Math.abs(g - 207) < 25 && Math.abs(b - 207) < 25) dashGrey++;
      if (r > 200 && g > 200 && b > 200) nearWhite++;
    }
    return { asphaltGreen, dashGrey, nearWhite };
  });

  check('road: asphalt pixels present', road.asphaltGreen > 100000, `asphaltPixels=${road.asphaltGreen}`);
  check('road: dash pixels present', road.dashGrey > 0, `dashPixels=${road.dashGrey}`);
  check('road: bright pixels present', road.nearWhite > 0, `brightPixels=${road.nearWhite}`);

  check('renderState() present', result.hasRenderState);
  check('layerCount=6', result.layerCount === 6, `layers=${result.layerCount}`);
  check('layer ids', JSON.stringify(result.layerIds) === JSON.stringify(expectedIds),
    JSON.stringify(result.layerIds));
  check('externalRequests=0', external.length === 0, `count=${external.length}`);
  check('errors=0', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' | '));

  const failed = checks.filter((c) => !c.ok);
  console.log(`\nrender-seam.browser: externalRequests=${external.length} errors=${consoleErrors.length} layers=${result.layerCount}`);
  console.log(`road: dashPixels=${road.dashGrey} asphaltPixels=${road.asphaltGreen} brightPixels=${road.nearWhite}`);
  if (failed.length) { console.log(`FAILED: ${failed.length}`); process.exitCode = 1; }
  else console.log('PASS');
} finally {
  await browser.close();
}
