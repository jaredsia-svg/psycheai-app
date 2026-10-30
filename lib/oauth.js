// Sign-in for hosts, as the MCP authorization spec asks: OAuth 2.1 with PKCE,
// dynamic client registration, and the two discovery documents.
//
//   1. The host calls /mcp, gets 401 with resource_metadata pointing at
//      /.well-known/oauth-protected-resource, which names us as the
//      authorization server (/.well-known/oauth-authorization-server).
//   2. It registers itself (/oauth/register), or names itself with the
//      address of its own client metadata document (client_id is an https
//      URL, which we fetch: loadMetadataClient), or uses the fixed public ID,
//      and sends the user to /oauth/authorize with a PKCE challenge.
//   3. The user types their email; we email a 6-digit code; they type it.
//      No password, no third-party account. A new email makes a new account.
//   4. We redirect back with a one-time code, which the host swaps at
//      /oauth/token (with the PKCE verifier) for an access token and a
//      refresh token. Refreshing rotates both.
//
// Codes, requests and tokens are stored only as hashes. Our own accounts, not
// Meta's or OpenAI's, so a user can move between hosts and keep everything.

const crypto = require('node:crypto');
const store = require('./store');
const mail = require('./mail');
const { BASE_URL } = require('./config');
const social = require('./social');

const REQUEST_TTL = 15 * 60000;
const LOGIN_CODE_TTL = 10 * 60000;
const AUTH_CODE_TTL = 5 * 60000;
const MAX_ATTEMPTS = 5;
const CODES_PER_HOUR = 5;
const ACCESS_SECONDS = 30 * 86400;

const metadata = {
  resource: () => ({
    resource: BASE_URL + '/mcp',
    authorization_servers: [BASE_URL],
    bearer_methods_supported: ['header'],
    resource_name: 'PsycheAI',
  }),
  server: () => ({
    issuer: BASE_URL,
    authorization_endpoint: BASE_URL + '/oauth/authorize',
    token_endpoint: BASE_URL + '/oauth/token',
    registration_endpoint: BASE_URL + '/oauth/register',
    response_types_supported: ['code'],
    grant_types_supported: ['authorization_code', 'refresh_token'],
    code_challenge_methods_supported: ['S256'],
    token_endpoint_auth_methods_supported: ['none'],
    client_id_metadata_document_supported: true,
    scopes_supported: ['psycheai'],
  }),
};

const challengeOf = verifier => crypto.createHash('sha256').update(verifier).digest('base64url');
const sameHash = (a, b) => a.length === b.length && crypto.timingSafeEqual(Buffer.from(a), Buffer.from(b));
const esc = s => String(s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
const validEmail = e => /^[^\s@]{1,64}@[^\s@]{1,190}\.[^\s@]{2,}$/.test(e);

function goodRedirect(uri) {
  try {
    const u = new URL(uri);
    if (u.hash) return false;
    return u.protocol === 'https:' || (u.protocol === 'http:' && ['localhost', '127.0.0.1'].includes(u.hostname));
  } catch { return false; }
}

const platformOf = client => (/openai|chatgpt/i.test((client.client_name || '') + ' ' + client.redirect_uris.join(' ')) ? 'chatgpt' : 'muse');

// A fixed public client for hosts that ask for a client ID instead of
// registering (Muse's "Add custom connector" on mobile). Like a registered
// one it has no secret and needs PKCE. Because anyone can use a shared ID, it
// only returns to Meta's own web hosts, so a sign-in code can't be sent
// anywhere else; PSYCHE_PUBLIC_REDIRECT_HOSTS adds hosts and
// PSYCHE_PUBLIC_REDIRECT_SCHEMES app schemes (e.g. "fb-muse").
const PUBLIC_CLIENT_ID = 'psycheai';
const PUBLIC_HOSTS = ['muse.ai', 'meta.ai', 'meta.com', 'facebook.com', 'instagram.com'];
const listEnv = name => String(process.env[name] || '').split(',').map(x => x.trim().toLowerCase()).filter(Boolean);
function publicRedirectOk(uri) {
  try {
    const u = new URL(uri);
    if (u.hash) return false;
    if (u.protocol === 'https:') {
      const host = u.hostname.toLowerCase();
      return PUBLIC_HOSTS.concat(listEnv('PSYCHE_PUBLIC_REDIRECT_HOSTS')).some(h => host === h || host.endsWith('.' + h));
    }
    return listEnv('PSYCHE_PUBLIC_REDIRECT_SCHEMES').includes(u.protocol.slice(0, -1).toLowerCase());
  } catch { return false; }
}
const PUBLIC_CLIENT = { client_id: PUBLIC_CLIENT_ID, client_name: 'PsycheAI (public)', redirect_uris: [], token_endpoint_auth_method: 'none', public: true };
// Any other client ID is the public client under that name: Muse's box asks
// for one and says nothing about what, so a guess or a typo ("PsycheAI",
// "psycheai ", "x") must work as well as "psycheai" does. It's safe for the
// same reason the fixed ID is: a public client returns only to Meta's hosts.
const TYPED_ID = /^[\x21-\x7e]{1,100}$/;
function clientOf(raw) {
  const id = String(raw || '').trim();
  if (id === PUBLIC_CLIENT_ID) return PUBLIC_CLIENT;
  return store.kvGet('oauthClients', id) || (TYPED_ID.test(id) ? { ...PUBLIC_CLIENT, client_id: id } : null);
}

// Client ID metadata documents (the MCP authorization spec's way for a host
// to sign in without registering or asking the user for a client ID): the
// client_id is an https address, and the document there lists the host's own
// name and return addresses. We fetch it once a day at most, with the same
// care as any outside fetch (https, public addresses only, no redirects, a
// size cap, a short timeout), and keep it beside registered clients.
const METADATA_DAY = 86400000;
const METADATA_BYTES = 64 * 1024;
const isMetadataId = id => { try { const u = new URL(id); return u.protocol === 'https:' && u.pathname.length > 1 && !u.hash; } catch { return false; } };
function privateAddress(ip) {
  const net = require('node:net');
  if (net.isIPv4(ip)) {
    const [a, b] = ip.split('.').map(Number);
    return a === 10 || a === 127 || a === 0 || (a === 169 && b === 254) || (a === 172 && b >= 16 && b <= 31) || (a === 192 && b === 168) || (a === 100 && b >= 64 && b <= 127);
  }
  const v = ip.toLowerCase();
  return v === '::1' || v === '::' || v.startsWith('fc') || v.startsWith('fd') || v.startsWith('fe80') || v.startsWith('::ffff:');
}
/** Check a fetched metadata document and keep it as a client; null if it doesn't hold up. */
function acceptMetadata(id, doc, now = Date.now()) {
  if (!doc || typeof doc !== 'object' || doc.client_id !== id) return null;
  const uris = Array.isArray(doc.redirect_uris) ? doc.redirect_uris.map(String) : [];
  if (!uris.length || uris.length > 20 || !uris.every(goodRedirect)) return null;
  if (doc.token_endpoint_auth_method && doc.token_endpoint_auth_method !== 'none') return null;
  const client = { client_id: id, client_name: String(doc.client_name || '').slice(0, 100), redirect_uris: uris, token_endpoint_auth_method: 'none', metadataDocument: true, fetchedAt: now };
  store.kvSet('oauthClients', id, client);
  return client;
}
/** Make sure a URL client_id's document is loaded (call before authorize and token). */
async function loadMetadataClient(id, now = Date.now()) {
  if (!isMetadataId(id)) return null;
  const known = store.kvGet('oauthClients', id);
  if (known && now - known.fetchedAt < METADATA_DAY) return known;
  try {
    const u = new URL(id);
    const addrs = await require('node:dns').promises.lookup(u.hostname, { all: true });
    if (!addrs.length || addrs.some(a => privateAddress(a.address))) return known || null;
    const res = await fetch(u, { headers: { Accept: 'application/json' }, redirect: 'error', signal: AbortSignal.timeout(5000) });
    const text = res.ok ? await res.text() : '';
    if (!text || text.length > METADATA_BYTES) return known || null;
    return acceptMetadata(id, JSON.parse(text), now) || null;
  } catch { return known || null; }
}
const redirectAllowed = (client, uri) => (client.public ? publicRedirectOk(uri) : client.redirect_uris.includes(uri));

/** RFC 7591: any host may register; redirect URIs must be https (or localhost). */
function register(body, now = Date.now()) {
  const uris = body && Array.isArray(body.redirect_uris) ? body.redirect_uris.map(String) : [];
  if (!uris.length || !uris.every(goodRedirect)) return { status: 400, body: { error: 'invalid_redirect_uri' } };
  const client = { client_id: store.newId('c'), client_id_issued_at: Math.floor(now / 1000), redirect_uris: uris,
    client_name: String((body && body.client_name) || '').slice(0, 100), token_endpoint_auth_method: 'none',
    grant_types: ['authorization_code', 'refresh_token'], response_types: ['code'] };
  store.kvSet('oauthClients', client.client_id, client);
  return { status: 201, body: client };
}

// ---------- the sign-in pages ----------

const theme = require('./theme');
const shell = (title, inner) => theme.page(title, `<h1>${esc(title)}</h1>${inner}`);
const input = (name, attrs) => `<p><input name="${name}" ${attrs}></p>`;
const button = label => `<button>${label}</button>`;

function socialButtons(reqId) {
  const names = social.available();
  if (!names.length) return '';
  return names.map(name => `<p><a class="btn ghost" href="/oauth/${name}?req=${encodeURIComponent(reqId)}">${esc(social.PROVIDERS[name].label)}</a></p>`).join('') +
    `<p class="note" style="margin:1rem 0">or</p>`;
}

function emailPage(reqId, note, purpose) {
  return shell(purpose === 'attach' ? 'Add your email' : 'Sign in to PsycheAI', (note ? `<p class="error">${esc(note)}</p>` : '') +
    (purpose === 'join' ? `<p>Sign in to put your read on your Psyche Pair profile. Use the email you use, or will use, with PsycheAI in Muse.</p>` : '') +
    (purpose === 'attach' ? `<p>For a nudge when someone picks you or writes to you, at most once a day, and to use your account on the website.</p>` : socialButtons(reqId)) +
    `<p>Your email, and we'll send you a 6-digit code. No password.</p>` +
    `<form method="post" action="/oauth/login"><input type="hidden" name="req" value="${esc(reqId)}">` +
    input('email', 'type="email" autocomplete="email" required autofocus') + button('Send my code') + `</form>`);
}

function codePage(reqId, email, note) {
  return shell('Check your email', (note ? `<p class="error">${esc(note)}</p>` : '') +
    `<p>We sent a code to <b>${esc(email)}</b>.</p>` +
    `<form method="post" action="/oauth/verify"><input type="hidden" name="req" value="${esc(reqId)}">` +
    input('code', 'inputmode="numeric" autocomplete="one-time-code" pattern="[0-9]{6}" required autofocus') + button('Sign in') + `</form>`);
}

const errorPage = msg => ({ status: 400, html: shell('Something went wrong', `<p>${esc(msg)}</p>`) });

function redirectTo(uri, params) {
  const u = new URL(uri);
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null) u.searchParams.set(k, v);
  return { status: 302, location: u.toString() };
}

/** GET /oauth/authorize: check the request, then show the email page. */
function authorize(q, now = Date.now(), cookie = '', userAgent = '') {
  const client = clientOf(q.get('client_id'));
  if (!client) return errorPage('Unknown app. Try connecting PsycheAI again.');
  const redirectUri = q.get('redirect_uri') || (client.redirect_uris.length === 1 ? client.redirect_uris[0] : '');
  if (!redirectAllowed(client, redirectUri)) {
    // Name the address (scheme and host only) so it can be allowed if it is a real host's.
    let where = '';
    try { const u = new URL(redirectUri); where = u.protocol + '//' + u.host; } catch { /* not an address */ }
    if (client.public) console.warn('[oauth] public client refused return address %s', where || '(none)');
    return errorPage('That return address is not registered for this app' + (where ? ': ' + where : '') + '.');
  }
  const state = q.get('state');
  if (q.get('response_type') !== 'code') return redirectTo(redirectUri, { error: 'unsupported_response_type', state });
  const challenge = q.get('code_challenge') || '';
  if (q.get('code_challenge_method') !== 'S256' || !/^[A-Za-z0-9_-]{43,128}$/.test(challenge)) {
    return redirectTo(redirectUri, { error: 'invalid_request', error_description: 'PKCE S256 is required', state });
  }
  // The invisible account (README "No sign-in to type"): no email and no code.
  // The account this browser made before (a signed cookie) comes back; else a
  // new one is made, and the host gets its code straight away. Email sign-in
  // stays for a reviewer, another device, or anyone who asks (?signin=email,
  // or PSYCHE_EMAIL_SIGNIN=1 for all).
  if (invisible() && q.get('signin') !== 'email') {
    const known = accountFromCookie(cookie, now);
    const user = known || store.createUser({ email: null, platform: platformOf(client) }).user;
    const out = issueCode(user, { clientId: client.client_id, redirectUri, state, challenge }, now);
    // On a phone the sign-in runs in a browser sheet, and a redirect nobody
    // tapped doesn't open the app (iOS and Android only hand a link to an app
    // on a tap), so the sheet sat on a blank page. There, one button does it.
    if (MOBILE.test(String(userAgent || ''))) return { status: 200, html: backPage(out.location), cookie: accountCookie(user.id, now) };
    return { ...out, cookie: accountCookie(user.id, now) };
  }
  const reqId = crypto.randomBytes(18).toString('base64url');
  store.kvSet('oauthRequests', reqId, { clientId: client.client_id, redirectUri, state, challenge, expiresAt: now + REQUEST_TTL, attempts: 0 });
  return { status: 200, html: emailPage(reqId) };
}

const invisible = () => process.env.PSYCHE_EMAIL_SIGNIN !== '1';
const MOBILE = /iPhone|iPad|iPod|Android|Mobile/i;
const backPage = location => theme.page('Connected', `<h1>You're connected</h1><p>PsycheAI is ready in Muse. Nothing to sign up for.</p>` +
  `<p><a class="btn" href="${esc(location)}">Back to Muse</a></p><p class="note">If the button doesn't take you back, close this page and return to Muse.</p>`);
const ACCOUNT_COOKIE = 'pp_account';
const ACCOUNT_DAYS = 400;
/** The Set-Cookie value that lets this browser come back to the same invisible account. */
function accountCookie(userId, now = Date.now()) {
  const token = require('./links').sign({ u: userId, k: 'account' }, now, ACCOUNT_DAYS * 86400000);
  return `${ACCOUNT_COOKIE}=${token}; Max-Age=${ACCOUNT_DAYS * 86400}; Path=/oauth; HttpOnly; Secure; SameSite=Lax`;
}
function accountFromCookie(header, now = Date.now()) {
  const m = new RegExp('(?:^|;\\s*)' + ACCOUNT_COOKIE + '=([^;]+)').exec(String(header || ''));
  const p = m && require('./links').verify(m[1], now);
  return p && p.k === 'account' ? store.getUser(p.u) : null;
}

/** The auth code for a user, back to the host. */
function issueCode(user, r, now) {
  const authCode = crypto.randomBytes(32).toString('base64url');
  store.kvSet('oauthCodes', store.hash(authCode), { userId: user.id, clientId: r.clientId, redirectUri: r.redirectUri, challenge: r.challenge, expiresAt: now + AUTH_CODE_TTL });
  return redirectTo(r.redirectUri, { code: authCode, state: r.state });
}

/** Adding an email to an invisible account, for nudges and the website: the same email-and-code page. */
function startAttach(userId, now = Date.now()) {
  const reqId = crypto.randomBytes(18).toString('base64url');
  store.kvSet('oauthRequests', reqId, { web: 'attach', userId, expiresAt: now + REQUEST_TTL, attempts: 0 });
  return { status: 200, html: emailPage(reqId, null, 'attach') };
}

/** The same sign-in, for the website: 'plus' (GET /plus) or 'join' (POST /join, with the held read's id). */
function startWeb(purpose = 'plus', extra = {}, now = Date.now()) {
  const reqId = crypto.randomBytes(18).toString('base64url');
  store.kvSet('oauthRequests', reqId, { web: purpose === 'join' ? 'join' : 'plus', ...extra, expiresAt: now + REQUEST_TTL, attempts: 0 });
  return { status: 200, html: emailPage(reqId, null, purpose) };
}

function liveRequest(reqId, now) {
  const r = store.kvGet('oauthRequests', String(reqId || ''));
  return r && r.expiresAt > now ? r : null;
}

/** POST /oauth/login: email in, code out (by email). */
function login(form, now = Date.now()) {
  const reqId = form.get('req');
  const r = liveRequest(reqId, now);
  if (!r) return errorPage('This sign-in expired. Go back and connect again.');
  const email = String(form.get('email') || '').trim().toLowerCase();
  if (!validEmail(email)) return { status: 400, html: emailPage(reqId, 'That email does not look right.') };
  const rateKey = store.emailKey(email);
  const rate = (store.kvGet('loginRate', rateKey) || []).filter(t => now - t < 3600000);
  if (rate.length >= CODES_PER_HOUR) return { status: 429, html: emailPage(reqId, 'Too many codes for this email. Try again in an hour.') };
  store.kvSet('loginRate', rateKey, [...rate, now]);
  const code = String(crypto.randomInt(0, 1000000)).padStart(6, '0');
  store.kvSet('oauthRequests', reqId, { ...r, email, codeHash: store.hash(code), codeExpiresAt: now + LOGIN_CODE_TTL, attempts: 0 });
  mail.send({ to: email, subject: `Your PsycheAI code: ${code}`, text: `Your sign-in code is ${code}. It works for 10 minutes.\n\nIf you didn't ask for this, ignore this email.` });
  return { status: 200, html: codePage(reqId, email) };
}

/** POST /oauth/verify: code in, back to the host with a one-time auth code. */
function verify(form, now = Date.now()) {
  const reqId = form.get('req');
  const r = liveRequest(reqId, now);
  if (!r || !r.codeHash) return errorPage('This sign-in expired. Go back and connect again.');
  if (r.attempts >= MAX_ATTEMPTS || r.codeExpiresAt < now) {
    store.kvDel('oauthRequests', reqId);
    return errorPage('That code has expired. Go back and connect again.');
  }
  const code = String(form.get('code') || '').trim();
  // A reviewer's fixed code, only while PSYCHE_REVIEWER_* are set (lib/demo.js).
  if (require('./demo').reviewerSignIn(r.email, code)) return signedIn(reqId, r, r.email, now);
  if (!sameHash(store.hash(code), r.codeHash)) {
    store.kvSet('oauthRequests', reqId, { ...r, attempts: r.attempts + 1 });
    return { status: 400, html: codePage(reqId, r.email, 'That code is not right.') };
  }
  return signedIn(reqId, r, r.email, now);
}

// An email proved (by a code, or by Google or Apple): the account, a one-time
// code, and back to the host.
function signedIn(reqId, r, email, now) {
  store.kvDel('oauthRequests', reqId);
  if (r.web === 'join') {
    // Joining Psyche Pair from a read on psycheai.io (lib/join.js): a new
    // email makes an account, as from a host.
    const user = store.userByEmail(email) || store.createUser({ email, platform: 'muse' }).user;
    const out = require('./join').joinRead(user.id, r.joinId, now);
    if (out.error) return errorPage(out.error);
    return { status: 200, html: shell('You\'re in', `<p>Your read is on your Psyche Pair profile${out.live ? ', and your live card is updated' : ''}.</p>` +
      `<p>${out.live ? 'Nothing else to do: your next matches use it.' : 'Open Muse, add PsycheAI if you haven\'t (<a href="https://psycheai.io/muse">how</a>), and say <b>"Psyche Pair"</b>. Muse shows you your card to check and asks the few things only you can answer.'}</p>`) };
  }
  if (r.web === 'plus') {
    // The website, not a host: only an account that already exists, and back
    // to its Plus page rather than to an app.
    const user = store.userByEmail(email);
    if (!user) return { status: 404, html: shell('No account yet', `<p>There's no PsycheAI account with that email yet. If you use PsycheAI in Muse, say <b>"Add my email to PsycheAI"</b> there first, then come back. New to PsycheAI? Add it to Muse (<a href="https://psycheai.io/muse">how</a>).</p>`) };
    return { status: 302, location: '/plus/' + require('./plus').tokenFor(user.id, now) };
  }
  if (r.web === 'attach') {
    if (!store.getUser(r.userId)) return errorPage('This link has expired. Ask Muse for a new one.');
    if (!store.setEmail(r.userId, email)) return { status: 409, html: shell('That email has an account', `<p>That email already has a PsycheAI account. To use it in Muse instead, remove PsycheAI from Muse, add it again, and choose <b>Sign in with email</b>.</p>`) };
    return { status: 200, html: shell('Email added', `<p>Done. We'll email you at most once a day when something's waiting, like someone picking you. Go back to Muse.</p>`) };
  }
  const client = clientOf(r.clientId);
  const user = store.userByEmail(email) || store.createUser({ email, platform: platformOf(client) }).user;
  // This browser now knows the account, so a later connect needs no sign-in.
  return { ...issueCode(user, r, now), cookie: accountCookie(user.id, now) };
}

/** GET /oauth/<google|apple>?req=: off to the provider, with a nonce kept on the request. */
function startSocial(name, q, now = Date.now()) {
  if (!social.enabled(name)) return errorPage('That sign-in is not available. Use your email instead.');
  const reqId = q.get('req');
  const r = liveRequest(reqId, now);
  if (!r) return errorPage('This sign-in expired. Go back and connect again.');
  const nonce = social.newNonce();
  store.kvSet('oauthRequests', reqId, { ...r, social: name, socialNonce: nonce });
  return { status: 302, location: social.startUrl(name, reqId, nonce) };
}

/** The provider's callback: Google with ?code&state, Apple posting id_token and state. */
async function finishSocial(name, params, now = Date.now()) {
  const reqId = params.get('state');
  const r = liveRequest(reqId, now);
  if (!r || r.social !== name || !r.socialNonce) return errorPage('This sign-in expired. Go back and connect again.');
  const email = name === 'google'
    ? await social.googleEmail(params.get('code'), r.socialNonce, now)
    : await social.appleEmail(params.get('id_token'), r.socialNonce, now);
  if (!email) return { status: 400, html: emailPage(reqId, `That didn't work. Try again, or use your email.`) };
  return signedIn(reqId, r, email, now);
}

const tokenError = (error, description) => ({ status: 400, body: { error, ...(description ? { error_description: description } : {}) } });

function tokensFor(userId, clientId) {
  return { status: 200, body: {
    access_token: store.issueToken(userId, 'access', clientId), token_type: 'Bearer', expires_in: ACCESS_SECONDS,
    refresh_token: store.issueToken(userId, 'refresh', clientId), scope: 'psycheai',
  } };
}

/** POST /oauth/token: auth code (with PKCE verifier) or refresh token in, tokens out. */
function token(params, now = Date.now()) {
  const grant = params.get('grant_type');
  const clientId = String(params.get('client_id') || '').trim();
  if (!clientOf(clientId)) return tokenError('invalid_client');
  if (grant === 'authorization_code') {
    const key = store.hash(params.get('code') || '');
    const c = store.kvGet('oauthCodes', key);
    store.kvDel('oauthCodes', key);
    if (!c || c.expiresAt < now || c.clientId !== clientId) return tokenError('invalid_grant');
    if (params.get('redirect_uri') && params.get('redirect_uri') !== c.redirectUri) return tokenError('invalid_grant', 'redirect_uri does not match');
    const verifier = params.get('code_verifier') || '';
    if (!/^[A-Za-z0-9._~-]{43,128}$/.test(verifier) || !sameHash(challengeOf(verifier), c.challenge)) return tokenError('invalid_grant', 'PKCE check failed');
    // A fresh sign-in (the connector added, or added again), not a refresh:
    // start shows the introduction once more (mcp.js startMenu).
    store.updateUser(c.userId, { connectedAt: now });
    return tokensFor(c.userId, clientId);
  }
  if (grant === 'refresh_token') {
    const raw = params.get('refresh_token') || '';
    const rec = store.tokenRecord(raw, 'refresh', now);
    if (!rec || rec.clientId !== clientId) return tokenError('invalid_grant');
    store.revokeToken(raw);
    return tokensFor(rec.userId, clientId);
  }
  return tokenError('unsupported_grant_type');
}

const challengeHeader = () => `Bearer realm="psyche-pair", resource_metadata="${BASE_URL}/.well-known/oauth-protected-resource"`;

module.exports = { loadMetadataClient, acceptMetadata, isMetadataId, ACCOUNT_COOKIE, accountCookie, accountFromCookie, startAttach, PUBLIC_CLIENT_ID, publicRedirectOk, metadata, register, authorize, startWeb, login, verify, token, startSocial, finishSocial, challengeOf, challengeHeader, platformOf };
