// Draws the two Psyche Cards for the sample Psyche Together report and the Psyche Together page
// (README "The Psyche Together page"): psycheai.io's own sample cards, Emily Carter's (Mulan) and
// Lucas Moreau's (Odysseus), drawn by the website itself, each with the other first in Most in sync
// with, since in the sample they are a couple. Needs the psycheai repo beside this one.
// Writes assets/together-card-emily.jpg and assets/together-card-lucas.jpg (640 wide).
// Run after a change to the card's look, then python3 tools/together-sample.py.
import { createRequire } from 'node:module';
import { spawn, execFileSync } from 'node:child_process';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';

const app = join(dirname(fileURLToPath(import.meta.url)), '..');
const site = join(app, '..', 'psycheai');
// Playwright from the website's own install, which this repo doesn't carry.
const { chromium } = createRequire(join(site, 'package.json'))('playwright');
const PORT = 3941;
const server = spawn(process.execPath, [join(site, 'server.js')], {
  env: { ...process.env, PSYCHEAI_MOCK: '1', PORT: String(PORT) }, stdio: ['ignore', 'pipe', 'inherit'],
});
await new Promise((resolve, reject) => {
  server.stdout.on('data', chunk => { if (/running at/.test(String(chunk))) resolve(); });
  server.on('exit', code => reject(new Error('server exited ' + code)));
});
const first = (list, name) => [name].concat((list || []).filter(x => x !== name)).slice(0, 3);
const work = mkdtempSync(join(tmpdir(), 'together-cards-'));
const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 400, height: 1400 }, deviceScaleFactor: 2 });
  await page.route('**/sample.json', async route => {
    const real = await (await route.fetch()).json();
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(Object.assign({}, real, { sampleSyncs: first(real.sampleSyncs, 'Odysseus') })) });
  });
  await page.route('**/sample-cards.json', async route => {
    const real = await (await route.fetch()).json();
    const cards = real.cards.map(c => (c.card && c.card.name === 'Lucas Moreau' ? Object.assign({}, c, { sampleSyncs: first(c.sampleSyncs, 'Mulan') }) : c));
    await route.fulfill({ contentType: 'application/json', body: JSON.stringify(Object.assign({}, real, { cards })) });
  });
  await page.goto('http://localhost:' + PORT + '/');
  await page.click('#insight-card-open');
  await page.waitForSelector('#sample-card-dialog[open] #sample-psyche-card-full .pc-shero');
  const card = page.locator('#sample-psyche-card-full');
  for (const [who, slug] of [['Emily Carter', 'emily'], ['Lucas Moreau', 'lucas']]) {
    for (let step = 0; step < 10; step++) {
      if (new RegExp(who).test(await card.innerText())) break;
      await page.evaluate(() => { const next = document.querySelector('#sample-card-dialog .sample-card-next'); next.style.visibility = ''; next.click(); });
      await page.mouse.move(1, 1);
      await page.waitForTimeout(700);
    }
    await page.evaluate(() => document.querySelectorAll('#sample-card-dialog button').forEach(b => { if (!b.closest('#sample-psyche-card-full')) b.style.visibility = 'hidden'; }));
    await page.mouse.move(1, 1);
    await page.waitForTimeout(600);
    if (!new RegExp(who).test(await card.innerText())) throw new Error('no card for ' + who);
    const png = join(work, slug + '.png');
    await card.screenshot({ path: png });
    execFileSync('python3', ['-c', `import sys
from PIL import Image
im = Image.open(sys.argv[1]).convert('RGB'); im.thumbnail((640, 1200)); im.save(sys.argv[2], 'JPEG', quality=84, optimize=True, progressive=True)`,
      png, join(app, 'assets', 'together-card-' + slug + '.jpg')]);
    console.log('assets/together-card-' + slug + '.jpg');
  }
} finally {
  await browser.close();
  server.kill();
}
