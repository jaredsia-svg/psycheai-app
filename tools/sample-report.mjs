// Builds assets/sample-report.html, the sample report served at /sample (README "A sample report"):
// the report file the skill makes (bin/psyche.py report_html), for psycheai.io's fictional sample
// reader, Emily Carter, with her Psyche Card large at the top. Needs the psycheai repo beside this one
// (its docs/sample.json, the import that turns a read into the report's view, and the sample card).
// Run after a change to the report's layout or the sample: node tools/sample-report.mjs
import { createRequire } from 'node:module';
import { execFileSync } from 'node:child_process';
import { readFileSync, writeFileSync, mkdtempSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { tmpdir } from 'node:os';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const app = join(here, '..');
const site = join(app, '..', 'psycheai');
const require = createRequire(import.meta.url);
const mi = require(join(site, 'lib', 'museimport.js'));
const mp = require(join(site, 'lib', 'musepdf.js'));
const sample = JSON.parse(readFileSync(join(site, 'docs', 'sample.json'), 'utf8'));
const bundled = mi.bundleFrom(sample);
if (!bundled.ok) throw new Error('docs/sample.json no longer imports: ' + JSON.stringify(bundled.problems).slice(0, 300));
const work = mkdtempSync(join(tmpdir(), 'sample-'));
writeFileSync(join(work, 'view.json'), JSON.stringify(mp.fullView(bundled.bundle.data, 'Emily Carter', bundled.answer)));
writeFileSync(join(work, 'bonus.json'), JSON.stringify(sample.bonus || null));
const py = `import importlib.util, json, base64, io, sys
spec = importlib.util.spec_from_file_location('p', sys.argv[1]); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
raw = open(sys.argv[2], 'rb').read()
try:
    from PIL import Image
    im = Image.open(io.BytesIO(raw)).convert('RGB'); im.thumbnail((640, 1140))
    buf = io.BytesIO(); im.quantize(colors=256, method=Image.Quantize.MEDIANCUT).save(buf, 'PNG', optimize=True); raw = buf.getvalue()
except ImportError:
    pass
page = m.report_html(json.load(open(sys.argv[3])), 'Emily Carter', 'A sample report', base64.b64encode(raw).decode(), None,
                     'Sample Psyche Report', json.load(open(sys.argv[4])),
                     {'note': 'A sample: Emily Carter is fictional. This is the report file PsycheAI makes in your Muse chat, written from your own Instagram.',
                      'cta': 'Get yours: paste psycheai.io/skill into Muse'})
sys.stdout.write(page)`;
const page = execFileSync('python3', ['-c', py, join(app, 'skill', 'bin', 'psyche.py'), join(site, 'promo', 'assets', 'card-char-mulan.png'),
  join(work, 'view.json'), join(work, 'bonus.json')], { maxBuffer: 1 << 26 }).toString();
writeFileSync(join(app, 'assets', 'sample-report.html'), page);
console.log('assets/sample-report.html', Math.round(page.length / 1024) + ' KB');
