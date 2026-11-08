// Sign Psyche Together's skill release (README "Psyche Together").
//
//   PSYCHE_SKILL_SIGNING_KEY=<base64 PKCS#8 Ed25519 private key> node tools/sign-together.mjs
//
// The same key as PsycheAI's skill, over its own first line ("psyche-together"), so a
// signature for one skill never passes for the other. Run it after any change to
// together/SKILL.md, together/bin/together.py or together/guide.json.
const { createRequire } = await import('node:module');
const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const t = require('../lib/togetherskill.js');

const raw = process.env.PSYCHE_SKILL_SIGNING_KEY || (process.env.PSYCHE_SKILL_SIGNING_KEY_FILE && fs.readFileSync(process.env.PSYCHE_SKILL_SIGNING_KEY_FILE, 'utf8'));
if (!raw) {
  console.error('No signing key: set PSYCHE_SKILL_SIGNING_KEY (or PSYCHE_SKILL_SIGNING_KEY_FILE).');
  process.exit(1);
}
const key = crypto.createPrivateKey({ key: Buffer.from(raw.trim(), 'base64'), format: 'der', type: 'pkcs8' });
const out = path.join(t.DIR, 'SIGNATURE.json');
let before = {};
try { before = JSON.parse(fs.readFileSync(out, 'utf8')); } catch (err) { /* the first */ }
if (t.version() !== before.version) {
  const script = path.join(t.DIR, 'bin', 'together.py');
  const next = Math.max(Number(before.release) || 0, t.release()) + 1;
  fs.writeFileSync(script, fs.readFileSync(script, 'utf8').replace(/^RELEASE = \d+$/m, 'RELEASE = ' + next));
}
const version = t.version();
const hashes = t.hashes();
const release = t.release();
const signature = crypto.sign(null, Buffer.from(t.signedText(version, hashes, release)), key).toString('base64url');
fs.writeFileSync(out, JSON.stringify({ version, release, hashes, signature }, null, 1) + '\n');
console.log('Signed Psyche Together ' + version + ' release ' + release);
