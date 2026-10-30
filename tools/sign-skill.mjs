// Sign the skill's release (README "Signed skill updates").
//
//   PSYCHE_SKILL_SIGNING_KEY=<base64 PKCS#8 Ed25519 private key> node tools/sign-skill.mjs
//
// Writes skill/SIGNATURE.json: the version, each served file's SHA-256 and an
// Ed25519 signature over them, for the files exactly as production serves them
// (its addresses are set here, so the hashes don't depend on where this runs).
// The private key lives only in the signer's own secrets, never in this repo or
// on the server: a server someone got into can't sign an update. Run it after
// any change to SKILL.md (lib/skill.js, lib/instructions.js) or bin/psyche.py;
// npm test fails while the signature is stale.
process.env.PSYCHE_BASE_URL = 'https://app.psycheai.io';
process.env.PSYCHEAI_URL = 'https://psycheai.io';
const { createRequire } = await import('node:module');
const require = createRequire(import.meta.url);
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const skill = require('../lib/skill.js');

const raw = process.env.PSYCHE_SKILL_SIGNING_KEY || (process.env.PSYCHE_SKILL_SIGNING_KEY_FILE && fs.readFileSync(process.env.PSYCHE_SKILL_SIGNING_KEY_FILE, 'utf8'));
if (!raw) {
  console.error('No signing key: set PSYCHE_SKILL_SIGNING_KEY (or PSYCHE_SKILL_SIGNING_KEY_FILE).');
  process.exit(1);
}
const key = crypto.createPrivateKey({ key: Buffer.from(raw.trim(), 'base64'), format: 'der', type: 'pkcs8' });
const out = path.join(path.dirname(new URL(import.meta.url).pathname), '..', 'skill', 'SIGNATURE.json');
let before = {};
try { before = JSON.parse(fs.readFileSync(out, 'utf8')); } catch (err) { /* the first */ }
// A changed release gets the next number, written into bin/psyche.py before it's hashed,
// so installed copies can refuse anything older (README "Releases are numbered").
if (skill.version() !== before.version) {
  const script = path.join(path.dirname(out), 'bin', 'psyche.py');
  const next = Math.max(Number(before.release) || 0, skill.release()) + 1;
  fs.writeFileSync(script, fs.readFileSync(script, 'utf8').replace(/^RELEASE = \d+$/m, 'RELEASE = ' + next));
}
const version = skill.version();
const hashes = skill.hashes();
const release = skill.release();
const signature = crypto.sign(null, Buffer.from(skill.signedText(version, hashes)), key).toString('base64url');
const signature2 = crypto.sign(null, Buffer.from(skill.signedText(version, hashes, release)), key).toString('base64url');
fs.writeFileSync(out, JSON.stringify({ version, release, hashes, signature, signature2 }, null, 2) + '\n');
console.log('Signed skill', version, 'release', release, Object.keys(hashes).join(', '));
