// Psyche Together's own skill (README "Psyche Together"): served from /together, signed apart from
// PsycheAI's skill with the same key, and sharing none of its files. Off unless PSYCHE_TOGETHER=1,
// like its tools (lib/together.js).
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const together = require('./together');

const DIR = path.join(__dirname, '..', 'together');
const FILES = ['SKILL.md', 'bin/together.py', 'guide.json'];
const TYPES = { 'SKILL.md': 'text/markdown; charset=utf-8', 'bin/together.py': 'text/x-python; charset=utf-8', 'guide.json': 'application/json; charset=utf-8' };
const SIGNATURE = () => process.env.PSYCHE_TOGETHER_SIGNATURE || path.join(DIR, 'SIGNATURE.json');
const sha256 = body => crypto.createHash('sha256').update(body).digest('hex');

function file(name) {
  if (!FILES.includes(name)) return null;
  try {
    return { body: fs.readFileSync(path.join(DIR, name)), type: TYPES[name] };
  } catch (err) {
    return null;
  }
}
const hashes = () => Object.fromEntries(FILES.map(n => [n, sha256((file(n) || { body: '' }).body)]));
const version = () => sha256(FILES.map(n => n + ' ' + hashes()[n]).join('\n')).slice(0, 12);
const release = () => Number((/^RELEASE = (\d+)$/m.exec(String((file('bin/together.py') || { body: '' }).body)) || [])[1] || 0);
/** What is signed: as PsycheAI's skill, under its own first line so one skill's signature can't pass for the other's. */
const signedText = (v, h, rel) => 'psyche-together\nrelease: ' + rel + '\nversion: ' + v + '\n' + Object.keys(h).sort().map(n => n + ' ' + h[n] + '\n').join('');

function signed() {
  try {
    const s = JSON.parse(fs.readFileSync(SIGNATURE(), 'utf8'));
    return s.version === version() && JSON.stringify(s.hashes) === JSON.stringify(hashes()) ? s : null;
  } catch (err) {
    return null;
  }
}
const manifest = () => {
  const s = signed() || {};
  return { version: version(), release: Number.isInteger(s.release) ? s.release : null, files: FILES, hashes: hashes(), signature: s.signature || null };
};

const BASE_URL = () => (process.env.PSYCHE_BASE_URL || 'https://app.psycheai.io').replace(/\/$/, '');
/** GET /together: what the skill is and where its files are, nothing to follow (the code after # never reaches here). */
const bootstrap = () => `# Psyche Together skill for Muse

Psyche Together is a private relationship check-in for two people, each in their own Muse, built on both their PsycheAI Psyches.

- Skill file: ${BASE_URL()}/together/SKILL.md
- Its script: ${BASE_URL()}/together/bin/together.py (standard-library Python)
- Its guide: ${BASE_URL()}/together/guide.json
- Folder: ~/workspace/skills/psyche-together/
- These three files are the whole skill: ${FILES.join(', ')}, each saved into the folder at the same path.
- Psyche Together is its own skill: PsycheAI's menus offer it, but none of its code is in the PsycheAI skill. It reads the Psyche that skill keeps (psycheai.io/skill).
- Psyche Together installs only from app.psycheai.io: its files are signed.
- From a partner's invite: save the three files, then in the folder run \`python3 bin/together.py join <the invite link>\`. join checks for their Psyche and says if there isn't one yet.
`;

/** The routes, for server.js: null when the path isn't Psyche Together's. */
function route(pathname, method) {
  if (!/^\/together(\/|$)/.test(pathname)) return null;
  if (!together.enabled()) return { status: 404, body: { error: 'Not found' } };
  if (method !== 'GET' && method !== 'HEAD') return { status: 405, body: { error: 'GET only' } };
  if (pathname === '/together' || pathname === '/together/') return { status: 200, body: bootstrap(), type: 'text/markdown; charset=utf-8' };
  if (pathname === '/together/files') return { status: 200, body: manifest() };
  const f = file(pathname.slice('/together/'.length));
  return f ? { status: 200, body: f.body, type: f.type } : { status: 404, body: { error: 'Not found' } };
}

module.exports = { FILES, file, hashes, version, release, signedText, signed, manifest, route, DIR };
