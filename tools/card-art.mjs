// Build the card art pack the skill draws the Psyche Card with in Muse (README "The card is drawn
// in Muse"): assets/card-art.zip, served at /skill/card-art.zip.
//
//   node tools/card-art.mjs
//
// Nothing in it is about anyone: every character's scene (its round crop is cut from it), rendered from the same
// art the server's card uses (assets/psycheai.json) by the same renderer (resvg), the brand mark,
// the card's emoji (assets/emoji), the Inter fonts (assets/fonts, SIL OFL) and the card's tokens.
// The whole pack is fetched once, so the fetch says nothing about which character a reader got.
// After a change, put its SHA-256 (printed here) in bin/psyche.py's CARD_ART_SHA256, then sign.
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, writeFileSync, copyFileSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';
import { createHash } from 'node:crypto';

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, '..');
const require = createRequire(import.meta.url);
const { Resvg } = require('@resvg/resvg-js');
const P = require(join(app, 'assets', 'psycheai.json'));
const characters = require(join(app, 'lib', 'characters.js'));

const work = mkdtempSync(join(tmpdir(), 'card-art-'));
const dir = join(work, 'card-art');
for (const d of ['scenes', 'emoji', 'fonts']) mkdirSync(join(dir, d), { recursive: true });
const png = (svg, w) => new Resvg(svg, { fitTo: { mode: 'width', value: w } }).render().asPng();
const file = name => name.replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '');

const index = {};
for (const [name, art] of Object.entries(P.art).sort()) {
  const f = file(name);
  // The scene at 1.6 times its 520x440 box (the card draws it at up to about that), cut to 256 colours
  // below; the card crops it as the SVG's "xMaxYMid slice" would.
  writeFileSync(join(dir, 'scenes', f + '.png'), png(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 520 440" width="832" height="704">${art.replace(/\{id\}/g, 's')}</svg>`, 832));
  index[name] = f;
}
const b = P.brand;
writeFileSync(join(dir, 'brand.png'), png(`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${b.viewBox} ${b.viewBox}" width="${b.viewBox * 2}" height="${b.viewBox * 2}"><g fill="none" stroke="${P.tokens.accent}" stroke-width="${b.strokeWidth}">${b.paths.map(d => `<path d="${d}"/>`).join('')}</g></svg>`, b.viewBox * 2));
for (const f of readdirSync(join(app, 'assets', 'emoji'))) if (/\.png$|LICENSE/.test(f)) copyFileSync(join(app, 'assets', 'emoji', f), join(dir, 'emoji', f));
for (const f of readdirSync(join(app, 'assets', 'fonts'))) copyFileSync(join(app, 'assets', 'fonts', f), join(dir, 'fonts', f));
// Each round crop ("Most in sync with") is cut from its scene by the skill, with the server's own crop boxes.
writeFileSync(join(dir, 'meta.json'), JSON.stringify({ tokens: P.tokens, scenes: index, crops: P.crops, defaultCrop: '220 20 300 300', syncs: characters.SYNCS,
  emoji: { '🧭': 'compass', '📊': 'chart', '⚖️': 'scales', '💡': 'bulb', '✨': 'sparkles', '💝': 'heartgift', '🎁': 'gift', '🤝': 'handshake',
    '🎯': 'target', '🧵': 'thread', '🧲': 'magnet', '💬': 'speech', '🛠️': 'tools', '⏳': 'hourglass', '🫂': 'hug', '💗': 'heart' } }, null, 1));

// 256 colours each, alpha kept (Pillow, as on the reader's side): about a tenth of the size.
execFileSync('python3', ['-c', `import sys, glob
from PIL import Image
for f in glob.glob(sys.argv[1] + '/*.png'):
    Image.open(f).convert('RGBA').quantize(colors=256, method=Image.Quantize.FASTOCTREE).save(f, optimize=True)`, join(dir, 'scenes')]);

// A fixed date on every entry, so the same art always makes the same zip (and hash).
execFileSync('find', [dir, '-exec', 'touch', '-t', '202601010000', '{}', '+']);
const out = join(app, 'assets', 'card-art.zip');
rmSync(out, { force: true });
execFileSync('zip', ['-X', '-q', '-r', '-9', out, 'card-art'], { cwd: work });
rmSync(work, { recursive: true, force: true });
const zip = readFileSync(out);
console.log('Wrote assets/card-art.zip,', Math.round(zip.length / 1024) + ' KB, sha256', createHash('sha256').update(zip).digest('hex'));
