// The private Psyche read as a PDF, without us keeping it.
//
// The host writes the read in the user's chat. When the user asks for a PDF,
// it sends the sections here once; we seal them with a fresh AES-256-GCM key,
// keep only the sealed box, and return a link with the key after the "#":
//
//     https://…/read/<id>#<key>
//
// Browsers never send the part after "#" to a server, so once the box is
// stored we cannot open it. The page fetches the box, opens it in the
// browser, lays it out, and "Save as PDF" uses the browser's own print to PDF
// (works on phones too). The box is deleted after TTL_DAYS.
//
// Honest wording for the privacy page: the read passes through our server in
// memory to make the link; what is stored is encrypted with a key we don't keep.

const crypto = require('node:crypto');
const store = require('./store');
const { BASE_URL } = require('./config');

const TTL_DAYS = 7;
const MAX_SECTIONS = 24;
const HEADING_MAX = 80;
const BODY_MAX = 4000;
const TOTAL_MAX = 60000;
const TABLE = 'reads';

function create(input, now = Date.now()) {
  const title = String((input && input.title) || 'Your Psyche').replace(/\s+/g, ' ').trim().slice(0, HEADING_MAX);
  const sections = (input && Array.isArray(input.sections) ? input.sections : []).map(s => ({
    heading: String((s && s.heading) || '').replace(/\s+/g, ' ').trim(),
    body: String((s && s.body) || '').replace(/\r\n/g, '\n').trim(),
  }));
  if (!sections.length) return { error: 'Add at least one section.' };
  if (sections.length > MAX_SECTIONS) return { error: `At most ${MAX_SECTIONS} sections.` };
  if (sections.some(s => !s.heading || s.heading.length > HEADING_MAX)) return { error: `Every section needs a heading under ${HEADING_MAX} characters.` };
  if (sections.some(s => !s.body || s.body.length > BODY_MAX)) return { error: `Every section needs a body under ${BODY_MAX} characters.` };
  const json = JSON.stringify({ title, sections });
  if (json.length > TOTAL_MAX) return { error: 'The read is too long for one PDF.' };

  const key = crypto.randomBytes(32);
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', key, iv);
  const data = Buffer.concat([c.update(json, 'utf8'), c.final(), c.getAuthTag()]);
  const id = crypto.randomBytes(12).toString('base64url');
  store.kvSet(TABLE, id, { iv: iv.toString('base64url'), data: data.toString('base64url'), expiresAt: now + TTL_DAYS * 86400000 });
  return { url: `${BASE_URL}/read/${id}#${key.toString('base64url')}`, expiresInDays: TTL_DAYS };
}

function box(id, now = Date.now()) {
  const b = store.kvGet(TABLE, String(id));
  if (!b) return null;
  if (b.expiresAt < now) { store.kvDel(TABLE, String(id)); return null; }
  return { iv: b.iv, data: b.data };
}

function sweep(now = Date.now()) {
  for (const [id, b] of store.kvAll(TABLE)) if (b.expiresAt < now) store.kvDel(TABLE, id);
}

// The page. No data in it: it fetches the box and opens it with the key from
// the address, all in the browser.
const PAGE = `<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer"><meta name="robots" content="noindex"><title>Your Psyche</title>
<style>
:root{--ink:#1d1b26;--muted:#6b6878;--accent:#5b4bd6;--paper:#fff}
body{margin:0;background:var(--paper);color:var(--ink);font:16px/1.6 Georgia,serif}
main{max-width:40rem;margin:0 auto;padding:2.5rem 16px 4rem}
h1{font:600 2rem/1.2 system-ui;margin:0 0 .25rem}
.sub{color:var(--muted);font:14px system-ui;margin:0 0 2rem}
h2{font:600 1.15rem/1.3 system-ui;color:var(--accent);margin:2rem 0 .5rem;break-after:avoid}
section{break-inside:avoid-page}
p,li{margin:.4rem 0}
button{font:600 15px system-ui;padding:.7rem 1.3rem;border:0;border-radius:2rem;background:var(--accent);color:#fff;cursor:pointer}
.bar{display:flex;gap:1rem;align-items:center;margin-bottom:2rem}
.note{color:var(--muted);font:13px system-ui}
@media print{.bar,.note{display:none} main{padding:0} body{font-size:11.5pt}}
</style>
<main><div class="bar"><button id="pdf" hidden>Save as PDF</button><span class="note" id="status">Opening your read…</span></div><div id="doc"></div>
<p class="note">Only someone with this exact link can open it, and it is deleted after ${TTL_DAYS} days.</p></main>
<script>
(async () => {
  const status = document.getElementById('status');
  const fail = msg => { status.textContent = msg; };
  try {
    const id = location.pathname.split('/').pop();
    const b64 = s => Uint8Array.from(atob(s.replace(/-/g, '+').replace(/_/g, '/') + '==='.slice((s.length + 3) % 4)), ch => ch.charCodeAt(0));
    const keyText = location.hash.slice(1);
    if (!keyText) return fail('This link is missing its key. Ask Muse for a new one.');
    const res = await fetch('/read/' + id + '/data', { cache: 'no-store' });
    if (!res.ok) return fail('This read has expired. Ask Muse for a new one.');
    const box = await res.json();
    const key = await crypto.subtle.importKey('raw', b64(keyText), 'AES-GCM', false, ['decrypt']);
    const plain = await crypto.subtle.decrypt({ name: 'AES-GCM', iv: b64(box.iv) }, key, b64(box.data));
    const read = JSON.parse(new TextDecoder().decode(plain));
    const doc = document.getElementById('doc');
    const el = (tag, text, cls) => { const n = document.createElement(tag); if (text) n.textContent = text; if (cls) n.className = cls; return n; };
    document.title = read.title;
    doc.append(el('h1', read.title), el('p', 'Psyche Pair · private to you', 'sub'));
    for (const s of read.sections) {
      const sec = el('section');
      sec.append(el('h2', s.heading));
      let list = null;
      for (const raw of s.body.split(/\\n+/)) {
        const t = raw.trim();
        if (!t) continue;
        if (/^[-•*] /.test(t)) { if (!list) { list = el('ul'); sec.append(list); } list.append(el('li', t.slice(2))); }
        else { list = null; sec.append(el('p', t)); }
      }
      doc.append(sec);
    }
    status.textContent = '';
    const btn = document.getElementById('pdf');
    btn.hidden = false;
    btn.onclick = () => window.print();
  } catch (e) { fail('This link could not be opened. Ask Muse for a new one.'); }
})();
</script>`;

module.exports = { TTL_DAYS, create, box, sweep, PAGE };
