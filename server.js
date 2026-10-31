// Psyche Pair server: the MCP connector at /mcp, and the few web pages email
// links need. Plain node:http, no framework.
//
//   POST /mcp                 the connector (bearer token required)
//   GET  /.well-known/oauth-protected-resource, /.well-known/oauth-authorization-server
//   POST /oauth/register      dynamic client registration (lib/oauth.js)
//   GET  /oauth/authorize     sign-in: email, then a 6-digit code
//   POST /oauth/login, /oauth/verify, /oauth/token
//   GET  /read/:id            the private read as a page to save as PDF (lib/reads.js)
//   GET  /card/:token.png     a card as an image, for the chat (lib/cardimage.js)
//   GET  /card/:token.pdf     a Sync as PsycheAI's Sync PDF (lib/sync.js pdfFor)
//   GET  /m/:token            the card page; POST /m/:token/:action for its buttons
//   GET  /, /add-to-muse, /privacy, /terms, /safety   301 to psycheai.io/muse (lib/site.js)
//   GET  /intro/:id?t=&a=     answer an intro from an email link
//   GET  /chat/:id?t=         the private chat page for a mutual match
//   POST /chat/:id?t=         send a message from that page (form post)
//   POST /dev/signup          dev only (PSYCHE_DEV=1): make a user, get a token
//   GET  /health

const http = require('node:http');
const store = require('./lib/store');
const mcp = require('./lib/mcp');
const pairform = require('./lib/pairform');
const skill = require('./lib/skill');
const photos = require('./lib/photos');
const weekly = require('./lib/weekly');
const chat = require('./lib/chat');
const oauth = require('./lib/oauth');
const notify = require('./lib/notify');
const reads = require('./lib/reads');
const psyche = require('./lib/psyche');
const keys = require('./lib/keys');
const sync = require('./lib/sync');
const plus = require('./lib/plus');
const join = require('./lib/join');
const links = require('./lib/links');
const pages = require('./lib/pages');
const site = require('./lib/site');
const { renderCard } = require('./lib/cardimage');

const PORT = Number(process.env.PORT || 8787);
const DEV = process.env.PSYCHE_DEV === '1';
const BODY_LIMIT = 256 * 1024;

function readBody(req, limit = BODY_LIMIT) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', c => {
      size += c.length;
      if (size > limit) { reject(Object.assign(new Error('too large'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => resolve(Buffer.concat(chunks).toString('utf8')));
    req.on('error', reject);
  });
}

function readJson(req) {
  return new Promise((resolve, reject) => {
    let size = 0;
    const chunks = [];
    req.on('data', c => {
      size += c.length;
      if (size > BODY_LIMIT) { reject(Object.assign(new Error('too large'), { status: 413 })); req.destroy(); return; }
      chunks.push(c);
    });
    req.on('end', () => {
      try { resolve(JSON.parse(Buffer.concat(chunks).toString('utf8') || 'null')); }
      catch { reject(Object.assign(new Error('bad json'), { status: 400 })); }
    });
    req.on('error', reject);
  });
}

function send(res, status, body, type = 'application/json', headers = {}) {
  const text = typeof body === 'string' ? body : JSON.stringify(body);
  res.writeHead(status, { 'Content-Type': type + '; charset=utf-8', 'Cache-Control': 'no-store', ...headers });
  res.end(text);
}

const CORS = { 'Access-Control-Allow-Origin': '*', 'Access-Control-Allow-Headers': 'Authorization, Content-Type, Mcp-Protocol-Version' };

/** A form body or a JSON body, as URLSearchParams either way. */
async function readParams(req, limit) {
  const raw = await readBody(req, limit);
  if (/json/.test(req.headers['content-type'] || '')) {
    try { return new URLSearchParams(Object.entries(JSON.parse(raw || '{}')).map(([k, v]) => [k, String(v)])); }
    catch { throw Object.assign(new Error('bad json'), { status: 400 }); }
  }
  return new URLSearchParams(raw);
}

function sendResult(res, r) {
  if (r.cookie) res.setHeader('Set-Cookie', r.cookie);
  if (r.location) { res.writeHead(r.status, { Location: r.location, 'Cache-Control': 'no-store' }); return res.end(); }
  if (r.html) return send(res, r.status, r.html, 'text/html');
  return send(res, r.status, r.body, 'application/json', CORS);
}

const theme = require('./lib/theme');
// PsycheAI's app icon, at the addresses hosts and browsers look for it.
const ICONS = Object.fromEntries([['/favicon.ico', 'favicon.ico', 'image/x-icon'], ['/icon.png', 'icon-512.png', 'image/png'],
  ['/icon-192.png', 'icon-192.png', 'image/png'], ['/apple-touch-icon.png', 'apple-touch-icon.png', 'image/png']]
  .map(([path, file, type]) => [path, { type, body: require('node:fs').readFileSync(require('node:path').join(__dirname, 'assets', file)) }]));
const page = (title, text) => theme.page(title, `<h1>${theme.esc(title)}</h1><p>${text}</p>`);

function bearer(req) {
  const m = /^Bearer (.+)$/.exec(req.headers.authorization || '');
  return m ? store.userByToken(m[1]) : null;
}

// The user's own keys, from their workspace (lib/keys.js): held for this request only.
const requestKeys = req => ({ card: req.headers['x-psyche-card-key'], syncs: req.headers['x-psyche-sync-keys'] });

async function handleMcp(req, res) {
  const user = bearer(req);
  if (!user) {
    res.setHeader('WWW-Authenticate', oauth.challengeHeader());
    return send(res, 401, { error: 'Sign in to PsycheAI first.' });
  }
  const body = await readJson(req);
  if (Array.isArray(body)) {
    const replies = (await keys.withKeys(user.id, requestKeys(req), () => Promise.all(body.map(m => mcp.handle(user, m))))).filter(Boolean);
    return replies.length ? send(res, 200, replies) : send(res, 202, '');
  }
  const out = await keys.withKeys(user.id, requestKeys(req), () => mcp.handle(user, body));
  return out ? send(res, 200, out) : send(res, 202, '');
}

// From an email: the link carries the intro's own secret, so it works without
// signing in. This is where a paid "connect" step would sit (README "Money").
function handleIntroLink(res, id, url) {
  const intro = store.getIntro(id);
  if (!intro || url.searchParams.get('t') !== intro.linkToken) return send(res, 404, page('Link not found', 'This link has expired or was already used.'), 'text/html');
  const accept = url.searchParams.get('a') === 'accept';
  const out = weekly.respond(intro.to, id, accept);
  if (!out.ok) return send(res, 410, page('Already answered', out.error), 'text/html');
  return send(res, 200, accept
    ? page("It's mutual", 'You both said yes. Open Muse and say "Psyche Pair" to chat, or to swap Instagram if you both want to.')
    : page('Thanks', "We won't show you to each other again."), 'text/html');
}

const esc = s => String(s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

// The chat page: no script, no cookies. The link's own token says who you
// are, so keep it to yourself; a form post sends, and redirects back.
function chatUser(id, url) {
  const intro = store.getIntro(id);
  const t = url.searchParams.get('t');
  if (!intro || !intro.chatTokens || !t) return null;
  return Object.keys(intro.chatTokens).find(uid => intro.chatTokens[uid] === t) || null;
}

async function handleChat(req, res, id, url) {
  const userId = chatUser(id, url);
  if (!userId) return send(res, 404, page('Chat not found', 'This link has expired or is not yours.'), 'text/html');
  notify.seen(userId);
  if (req.method === 'POST') {
    const text = new URLSearchParams(await readBody(req)).get('text') || '';
    const out = chat.send(id, userId, text);
    if (!out.ok) return send(res, 400, page("Couldn't send", esc(out.error)), 'text/html');
    res.writeHead(303, { Location: `/chat/${id}?t=${encodeURIComponent(url.searchParams.get('t'))}` });
    return res.end();
  }
  const thread = chat.read(id, userId);
  if (!thread.ok) return send(res, 410, page('Chat closed', esc(thread.error)), 'text/html');
  const rows = thread.messages.map(m => `<p class="msg ${m.mine ? 'me' : 'them'}"><span>${esc(m.text)}</span></p>`).join('');
  const chatForm = thread.ended ? '<p class="muted">This chat was ended.</p>' :
    `<form method="post"><textarea name="text" maxlength="${chat.TEXT_MAX}" required rows="3"></textarea><button>Send</button></form>`;
  return send(res, 200, theme.page('Chat with ' + thread.with,
    `<style>.msg{margin:.4rem 0}.msg span{display:inline-block;padding:.55rem .85rem;border-radius:1.1rem;max-width:80%;white-space:pre-wrap}` +
    `.me{text-align:right}.me span{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff}.them span{background:var(--alt);border:1px solid var(--line)}` +
    `form{margin-top:12px}button{margin-top:8px}</style>` +
    `<h1>You and ${esc(thread.with)}</h1>` + (rows || '<p class="muted">Say hi. No contact details are shared until you choose to.</p>') + chatForm +
    `<p class="note">Messages are deleted after ${chat.RETENTION_DAYS} days. Nobody at PsycheAI reads them unless one of you reports the other.</p>`), 'text/html');
}

// Rendered card images, briefly, so a chat showing a card twice draws it once.
const IMAGE_CACHE_MAX = 200;
const IMAGE_TTL_MS = 10 * 60000;
const imageCache = new Map();

async function handleCardImage(res, token) {
  const p = links.verify(token);
  const ctx = p && weekly.cardContext(p.v, p.o, Date.now(), p.k, p.c);
  if (!ctx) return send(res, 404, { error: 'Not available' });
  const key = token + '|' + JSON.stringify(ctx.card);
  const hit = imageCache.get(key);
  let png = hit && Date.now() - hit.at < IMAGE_TTL_MS ? hit.png : null;
  if (!png) {
    png = await renderCard(ctx.card);
    imageCache.set(key, { png, at: Date.now() });
    if (imageCache.size > IMAGE_CACHE_MAX) imageCache.delete(imageCache.keys().next().value);
  }
  res.writeHead(200, { 'Content-Type': 'image/png', 'Cache-Control': 'private, max-age=300', 'Content-Length': png.length });
  return res.end(png);
}

// A Sync as PsycheAI's own Sync PDF (lib/sync.js pdfFor), through the same
// signed link as its card. Made by psycheai.io when asked, held here for a few
// minutes like the card images, and never written anywhere.
const pdfCache = new Map();
async function handleSyncPdf(res, token) {
  const p = links.verify(token);
  if (!p || p.k !== 'sync') return send(res, 404, { error: 'Not available' });
  // Keyed by what's written too, so "Write it again" is never shown the old one.
  const key = token + '|' + JSON.stringify(sync.writtenFor(p.v, p.o, p.c));
  const hit = pdfCache.get(key);
  let out = hit && Date.now() - hit.at < IMAGE_TTL_MS ? hit.out : null;
  if (!out) {
    out = await sync.pdfFor(p.v, p.o, p.c);
    if (!out) return send(res, 404, { error: 'This Sync isn\'t available. Open it again in Muse.' });
    pdfCache.set(key, { out, at: Date.now() });
    if (pdfCache.size > IMAGE_CACHE_MAX) pdfCache.delete(pdfCache.keys().next().value);
  }
  res.writeHead(200, {
    'Content-Type': 'application/pdf', 'Content-Length': out.pdf.length, 'Cache-Control': 'private, max-age=300',
    'Content-Disposition': 'inline; filename="' + out.name.replace(/[^\w .&-]/g, '') + '"', 'X-Robots-Tag': 'noindex',
  });
  return res.end(out.pdf);
}

const CARD_ACTIONS = {
  pick: (p, ctx) => (ctx.stage === 'drop' ? weekly.pick(p.v, p.o) : null),
  yes: (p, ctx) => (ctx.stage === 'picked' ? weekly.respond(p.v, ctx.introId, true) : null),
  no: (p, ctx) => (ctx.stage === 'picked' ? weekly.respond(p.v, ctx.introId, false) : null),
  share: (p, ctx) => (ctx.stage === 'mutual' ? weekly.shareInstagram(p.v, ctx.introId, true) : null),
  unshare: (p, ctx) => (ctx.stage === 'mutual' ? weekly.shareInstagram(p.v, ctx.introId, false) : null),
};

async function handleCardPage(req, res, token, action) {
  const p = links.verify(token);
  const ctx = p && weekly.cardContext(p.v, p.o, Date.now(), p.k, p.c);
  if (!ctx) return send(res, 404, pages.gonePage(), 'text/html');
  notify.seen(p.v);
  if (req.method === 'POST') {
    const run = CARD_ACTIONS[action];
    const out = run && run(p, ctx);
    if (!out) return send(res, 400, pages.gonePage(), 'text/html');
    if (!out.ok) return send(res, 400, pages.shell('Not done', `<h1>Not done</h1><p>${esc(out.error)}</p><p><a href="/m/${encodeURIComponent(token)}">Back</a></p>`), 'text/html');
    res.writeHead(303, { Location: '/m/' + token });
    return res.end();
  }
  if (action) return send(res, 405, { error: 'POST only' });
  if (ctx.stage === 'declined') return send(res, 404, pages.gonePage(), 'text/html');
  return send(res, 200, pages.cardPage(ctx, token), 'text/html');
}

async function route(req, res) {
  const url = new URL(req.url, 'http://local');
  try {
    if (url.pathname === '/health') return send(res, 200, { ok: true, commit: String(process.env.RENDER_GIT_COMMIT || '').slice(0, 7) || null, readGuide: psyche.guideInfo(), pairWaitlist: require('./lib/waitlist').counts(), readTimings: require('./lib/timing').latest() });
    const icon = req.method === 'GET' && ICONS[url.pathname];
    if (icon) {
      res.writeHead(200, { 'Content-Type': icon.type, 'Content-Length': icon.body.length, 'Cache-Control': 'public, max-age=86400' });
      return res.end(icon.body);
    }
    if (req.method === 'OPTIONS') { res.writeHead(204, { ...CORS, 'Access-Control-Allow-Methods': 'GET, POST, OPTIONS' }); return res.end(); }
    if (url.pathname.startsWith('/.well-known/oauth-protected-resource')) return send(res, 200, oauth.metadata.resource(), 'application/json', CORS);
    if (url.pathname === '/.well-known/oauth-authorization-server') return send(res, 200, oauth.metadata.server(), 'application/json', CORS);
    if (url.pathname === '/oauth/register' && req.method === 'POST') return sendResult(res, oauth.register(await readJson(req)));
    if (url.pathname === '/oauth/authorize' && req.method === 'GET') await oauth.loadMetadataClient(url.searchParams.get('client_id') || '');
    if (url.pathname === '/oauth/authorize' && req.method === 'GET') return sendResult(res, oauth.authorize(url.searchParams, Date.now(), req.headers.cookie, req.headers['user-agent']));
    const attachPath = /^\/account\/email\/([\w.-]+)$/.exec(url.pathname);
    if (attachPath && req.method === 'GET') {
      const p = links.verify(attachPath[1]);
      return sendResult(res, p && p.k === 'attach' && store.getUser(p.u) ? oauth.startAttach(p.u) : { status: 410, html: page('This link has expired', 'Ask Muse for a new one.') });
    }
    if (url.pathname === '/oauth/login' && req.method === 'POST') return sendResult(res, oauth.login(await readParams(req)));
    if (url.pathname === '/oauth/verify' && req.method === 'POST') return sendResult(res, oauth.verify(await readParams(req)));
    if (url.pathname === '/oauth/token' && req.method === 'POST') {
      const params = await readParams(req);
      await oauth.loadMetadataClient(params.get('client_id') || '');
      return sendResult(res, oauth.token(params));
    }
    const socialPath = /^\/oauth\/(google|apple)(\/callback)?$/.exec(url.pathname);
    if (socialPath && !socialPath[2] && req.method === 'GET') return sendResult(res, oauth.startSocial(socialPath[1], url.searchParams));
    if (socialPath && socialPath[2]) {
      const params = req.method === 'POST' ? await readParams(req) : url.searchParams;
      return sendResult(res, await oauth.finishSocial(socialPath[1], params));
    }
    if (url.pathname === '/plus' && req.method === 'GET') return sendResult(res, oauth.startWeb('plus'));
    if (url.pathname === '/join' && req.method === 'POST') {
      // A top-level form post from psycheai.io: the read is in the field "read".
      const held = join.hold((await readParams(req)).get('read') || '');
      if (held.error) return send(res, 400, page('Not sent', esc(held.error)), 'text/html');
      return sendResult(res, oauth.startWeb('join', { joinId: held.id }));
    }
    // The install link (lib/skill.js installPrompt): app.psycheai.io/install, or
    // /sync/<code> for a friend's Psyche link (/p and /p/<code>, the first
    // names, still answer, for invites already sent). Muse fetching it gets a
    // short page pointing at SKILL.md; a person opening a friend's in a browser
    // gets a page.
    const shortPath = /^\/(?:install|p)\/?$/.test(url.pathname) ? [url.pathname, undefined]
      : /^\/(?:sync|p)\/([A-Za-z0-9_-]{22}|[a-z2-9]{8})\/?$/.exec(url.pathname);
    if (shortPath && req.method === 'GET') {
      const code = shortPath[1];
      const owner = code ? sync.linkOwner(url.pathname) : null;
      if (code && !owner) return send(res, 410, page('This Psyche link has expired', 'Ask them for a new one.'), 'text/html');
      // A browser opening a page says so (Sec-Fetch-Dest: document); a fetch tool doesn't.
      const inBrowser = req.headers['sec-fetch-dest'] === 'document' && /text\/html/.test(String(req.headers.accept || ''));
      // /install itself is always the skill's page: whatever Muse fetches it with, it gets the skill.
      if (!inBrowser || !code) {
        const name = owner ? sync.nameByCode(code) : null;
        return send(res, 200, skill.bootstrap(code ? { code, name } : {}), 'text/markdown');
      }
    }
    // A Psyche link, opened in a browser: who sent it, and how to use it in Muse.
    const syncPath = /^\/s\/([\w.-]+)$/.exec(url.pathname) || (shortPath && shortPath[1] ? shortPath : null);
    if (syncPath && req.method === 'GET') {
      const owner = sync.linkOwner(url.pathname);
      if (!owner) return send(res, 410, page('This Sync link has expired', 'Ask them for a new one.'), 'text/html');
      // The name is in the owner's locked card: opened with the code in this link, and only for this page.
      const first = sync.nameByCode(syncPath[1]);
      const name = esc(first || 'Your friend');
      const link = esc(require('./lib/config').BASE_URL + url.pathname);
      return send(res, 200, theme.page(name + ' wants to sync with you',
        `<h1>${name} wants to see how you two sync</h1><p>PsycheAI reads your Instagram, writes your Psyche Card and shows how you click with ${name}: what you share, how you get on, and how to relate to each other better.</p>` +
        `<p><b>Paste this into Muse</b> and send it: it sets up PsycheAI, makes your Psyche and syncs you with ${name}. When Muse asks to allow PsycheAI, tap <b>Allow all</b>, so it only asks once.</p>` +
        `<pre id="invite" style="white-space:pre-wrap;word-break:break-word;background:var(--alt);border:1.5px dashed var(--line);border-radius:12px;padding:12px;font-size:.9rem">${esc(skill.installPrompt({ code: syncPath[1], name: first }))}</pre>` +
        `<p><button type="button" id="copy">Copy</button></p><script>document.getElementById('copy').onclick=function(){navigator.clipboard.writeText(document.getElementById('invite').textContent).then(function(){document.getElementById('copy').textContent='Copied: paste it into Muse'})}</script>` +
        `<p class="note">Already have PsycheAI in Muse? Just say: <b>Sync with ${link}</b></p>` +
        `<p>Free. Your posts and messages are never stored.</p>`), 'text/html');
    }
    // One of their Instagram photos, offered in the form, fetched for the form's own page.
    const igPath = /^\/pair\/form\/([\w.-]+)\/ig\/(\d{1,2})\.jpg$/.exec(url.pathname);
    if (igPath && req.method === 'GET') {
      const img = await pairform.igPhoto(igPath[1], igPath[2]);
      if (!img) return send(res, 404, { error: 'Not available' });
      res.writeHead(200, { 'Content-Type': img.type, 'Cache-Control': 'private, max-age=600', 'Content-Length': img.buf.length });
      return res.end(img.buf);
    }
    const formPath = /^\/pair\/form\/([\w.-]+)$/.exec(url.pathname);
    if (formPath && req.method === 'GET') return sendResult(res, pairform.show(formPath[1]));
    // Three photos ride on this form, each at most photos.MAX_BYTES as base64.
    if (formPath && req.method === 'POST') return sendResult(res, await pairform.submit(formPath[1], await readParams(req, 2.5 * 1024 * 1024)));
    // A photo, only for someone the card is for (the same signed link as the card).
    const photoPath = /^\/photo\/([\w.-]+)\/([0-2])\.jpg$/.exec(url.pathname);
    if (photoPath && req.method === 'GET') {
      const p = links.verify(photoPath[1]);
      const ctx = p && p.k !== 'psyche' && p.k !== 'sync' && weekly.cardContext(p.v, p.o, Date.now(), p.k);
      const buf = ctx ? await photos.get(p.o, photoPath[2]) : null;
      if (!buf) return send(res, 404, { error: 'Not available' });
      res.writeHead(200, { 'Content-Type': 'image/jpeg', 'Cache-Control': 'private, max-age=300', 'Content-Length': buf.length });
      return res.end(buf);
    }
    const plusPath = /^\/plus\/([\w.-]+?)(?:\/(month|year|manage))?$/.exec(url.pathname);
    if (plusPath && req.method === 'GET' && !plusPath[2]) return sendResult(res, plus.show(plusPath[1]));
    if (plusPath && req.method === 'POST' && plusPath[2]) return sendResult(res, await plus.act(plusPath[1], plusPath[2]));
    if (url.pathname === '/stripe/webhook' && req.method === 'POST') {
      const r = plus.webhook(await readBody(req), req.headers['stripe-signature']);
      return send(res, r.status, r.body);
    }
    const cardImage = /^\/card\/([\w.-]+)\.png$/.exec(url.pathname);
    if (cardImage && req.method === 'GET') return await handleCardImage(res, cardImage[1]);
    const syncPdfPath = /^\/card\/([\w.-]+)\.pdf$/.exec(url.pathname);
    if (syncPdfPath && req.method === 'GET') return await handleSyncPdf(res, syncPdfPath[1]);
    const cardPage = /^\/m\/([\w.-]+?)(?:\/(\w+))?$/.exec(url.pathname);
    if (cardPage && (req.method === 'GET' || req.method === 'POST')) return await handleCardPage(req, res, cardPage[1], cardPage[2]);
    const moved = req.method === 'GET' && site.redirectFor(url.pathname);
    if (moved) { res.writeHead(301, { Location: moved }); return res.end(); }
    const read = /^\/read\/([\w-]+)(\/data)?$/.exec(url.pathname);
    if (read && req.method === 'GET') {
      if (!read[2]) return send(res, 200, reads.PAGE, 'text/html');
      const b = reads.box(read[1]);
      return b ? send(res, 200, b) : send(res, 404, { error: 'expired' });
    }
    // PsycheAI as a Muse skill (lib/skill.js): its files, and its account.
    const skillPath = /^\/skill\/(SKILL\.md|bin\/psyche\.py|guide\.json)$/.exec(url.pathname);
    if (skillPath && req.method === 'GET') {
      const f = skill.file(skillPath[1]);
      return f ? send(res, 200, f.body, f.type.split(';')[0]) : send(res, 404, { error: 'Not found' });
    }
    if (url.pathname === '/skill/files' && req.method === 'GET') return send(res, 200, skill.manifest());
    // A Muse read's stages in seconds, from the skill (lib/timing.js): a signed-in workspace only.
    if (url.pathname === '/skill/timing' && req.method === 'POST') {
      if (!bearer(req)) return send(res, 401, { error: 'Sign in to PsycheAI first.' });
      return send(res, 200, require('./lib/timing').record(await readJson(req)));
    }
    if (url.pathname === '/skill/account' && req.method === 'POST') {
      // The address the edge saw, which a client can't set; the first X-Forwarded-For entry it can.
      const ip = String(req.headers['cf-connecting-ip'] || req.headers['true-client-ip'] || '').trim()
        || String(req.headers['x-forwarded-for'] || '').split(',').pop().trim() || req.socket.remoteAddress;
      const r = skill.account(ip);
      return send(res, r.status, r.body);
    }
    if (url.pathname === '/mcp') {
      if (req.method !== 'POST') return send(res, 405, { error: 'POST only' });
      return await handleMcp(req, res);
    }
    const intro = /^\/intro\/([\w-]+)$/.exec(url.pathname);
    if (intro && req.method === 'GET') return handleIntroLink(res, intro[1], url);
    const chatPath = /^\/chat\/([\w-]+)$/.exec(url.pathname);
    if (chatPath && (req.method === 'GET' || req.method === 'POST')) return await handleChat(req, res, chatPath[1], url);
    if (DEV && url.pathname === '/dev/signup' && req.method === 'POST') {
      const body = (await readJson(req)) || {};
      const { user, token } = store.createUser({ email: String(body.email || ''), platform: body.platform === 'chatgpt' ? 'chatgpt' : 'muse' });
      return send(res, 200, { userId: user.id, token });
    }
    return send(res, 404, { error: 'Not found' });
  } catch (err) {
    if (err.status) return send(res, err.status, { error: err.message });
    console.error(err);
    return send(res, 500, { error: 'Server error' });
  }
}

function createServer() {
  return http.createServer((req, res) => { route(req, res); });
}

async function main() {
  await store.load();
  // Nothing readable is kept: any Instagram handle, readable Sync or card
  // kept before goes (README "No email, no handles", "Nothing readable kept").
  require('./lib/sync').forgetReadable();
  require('./lib/psyche').forgetUnlocked();
  // A reviewer's demo world, only while PSYCHE_REVIEWER_* are set (lib/demo.js).
  const reviewer = require('./lib/demo').seed();
  if (reviewer) console.log('[demo] reviewer account ready');
  const server = createServer().listen(PORT, () => console.log(`psycheai-app on :${PORT}${DEV ? ' (dev)' : ''}`));
  // Render stops the old instance with SIGTERM on every deploy: write what is pending first.
  const stop = async () => {
    server.close();
    try { await store.flush(); } catch (err) { console.error('[store] final flush failed:', err.message); }
    process.exit(0);
  };
  process.on('SIGTERM', stop);
  process.on('SIGINT', stop);
  setInterval(() => {
    chat.sweep();
    reads.sweep();
    psyche.sweep();
    sync.sweep();
    join.sweep();
    require('./lib/waitlist').announce();
    psyche.remindUnopened().catch(err => console.error('[psyche] reminder check failed:', err.message));
    notify.digest(Date.now(), { hasNewDrop: weekly.hasNewDrop });
  }, 60 * 60 * 1000).unref();
}

if (require.main === module) main().catch(err => { console.error(err); process.exit(1); });

module.exports = { createServer };
