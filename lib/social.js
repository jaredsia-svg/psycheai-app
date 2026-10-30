// One-tap sign-in with Google or Apple, on the same sign-in page as the email
// code (lib/oauth.js), which stays as the fallback. Each provider is on only
// when its client id is set.
//
//   Google  GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET. Authorization code flow:
//           we swap the code for an ID token at Google's token endpoint.
//   Apple   APPLE_CLIENT_ID (the Services ID). Apple posts the ID token back
//           to us (response_mode form_post), so no client secret is needed
//           just to sign in.
//
// Either way the ID token is verified here: signature against the provider's
// published keys (RS256 for Google, ES256 for Apple), issuer, audience,
// expiry, and the nonce we put in the request. Only a verified email is used,
// and it is the account's email, as an email code would have proved.
//
// State: the sign-in request id plus a nonce, kept on the request record
// (lib/oauth.js), so a callback can only finish the request it started.

const crypto = require('node:crypto');
const { BASE_URL } = require('./config');

const PROVIDERS = {
  google: {
    label: 'Continue with Google',
    clientId: () => process.env.GOOGLE_CLIENT_ID || '',
    secret: () => process.env.GOOGLE_CLIENT_SECRET || '',
    authUrl: () => process.env.GOOGLE_AUTH_URL || 'https://accounts.google.com/o/oauth2/v2/auth',
    tokenUrl: () => process.env.GOOGLE_TOKEN_URL || 'https://oauth2.googleapis.com/token',
    jwksUrl: () => process.env.GOOGLE_JWKS_URL || 'https://www.googleapis.com/oauth2/v3/certs',
    issuers: ['https://accounts.google.com', 'accounts.google.com'],
    alg: 'RS256',
  },
  apple: {
    label: 'Continue with Apple',
    clientId: () => process.env.APPLE_CLIENT_ID || '',
    authUrl: () => process.env.APPLE_AUTH_URL || 'https://appleid.apple.com/auth/authorize',
    jwksUrl: () => process.env.APPLE_JWKS_URL || 'https://appleid.apple.com/auth/keys',
    issuers: ['https://appleid.apple.com'],
    alg: 'ES256',
  },
};

const enabled = name => Boolean(PROVIDERS[name] && PROVIDERS[name].clientId() && (name !== 'google' || PROVIDERS.google.secret()));
const available = () => Object.keys(PROVIDERS).filter(enabled);
const callbackUrl = name => `${BASE_URL}/oauth/${name}/callback`;

/** Where to send the user to sign in with a provider. */
function startUrl(name, state, nonce) {
  const p = PROVIDERS[name];
  const q = new URLSearchParams({ client_id: p.clientId(), redirect_uri: callbackUrl(name), response_type: 'code', state, nonce });
  if (name === 'google') { q.set('scope', 'openid email'); q.set('prompt', 'select_account'); }
  // Apple posts the ID token back only when it is asked for one.
  if (name === 'apple') { q.set('response_type', 'code id_token'); q.set('scope', 'email'); q.set('response_mode', 'form_post'); }
  return p.authUrl() + '?' + q.toString();
}

// ---------- ID token verification ----------

const jwksCache = new Map();
async function keysFor(name, now = Date.now()) {
  const hit = jwksCache.get(name);
  if (hit && now - hit.at < 3600000) return hit.keys;
  const res = await fetch(PROVIDERS[name].jwksUrl(), { signal: AbortSignal.timeout(10000) });
  if (!res.ok) throw new Error('jwks ' + res.status);
  const keys = (await res.json()).keys || [];
  jwksCache.set(name, { at: now, keys });
  return keys;
}

const b64json = part => JSON.parse(Buffer.from(part, 'base64url').toString('utf8'));

/** The verified claims of an ID token from this provider, or null. */
async function verifyIdToken(name, token, nonce, now = Date.now()) {
  const p = PROVIDERS[name];
  const parts = String(token || '').split('.');
  if (parts.length !== 3) return null;
  let header, claims;
  try { header = b64json(parts[0]); claims = b64json(parts[1]); } catch { return null; }
  if (header.alg !== p.alg) return null;
  let keys;
  try { keys = await keysFor(name, now); } catch { return null; }
  let jwk = keys.find(k => k.kid === header.kid);
  if (!jwk) { jwksCache.delete(name); try { jwk = (await keysFor(name, now)).find(k => k.kid === header.kid); } catch { return null; } }
  if (!jwk) return null;
  const key = crypto.createPublicKey({ key: jwk, format: 'jwk' });
  const data = Buffer.from(parts[0] + '.' + parts[1]);
  const sig = Buffer.from(parts[2], 'base64url');
  const ok = p.alg === 'RS256'
    ? crypto.verify('sha256', data, key, sig)
    : crypto.verify('sha256', data, { key, dsaEncoding: 'ieee-p1363' }, sig);
  if (!ok) return null;
  const secs = Math.floor(now / 1000);
  if (!p.issuers.includes(claims.iss)) return null;
  if (claims.aud !== p.clientId() && !(Array.isArray(claims.aud) && claims.aud.includes(p.clientId()))) return null;
  if (!(claims.exp > secs - 60) || (claims.iat && claims.iat > secs + 300)) return null;
  if (!nonce || claims.nonce !== nonce) return null;
  const verified = claims.email_verified === true || claims.email_verified === 'true';
  if (!claims.email || !verified) return null;
  return claims;
}

/** Google: swap the code for tokens, then verify the ID token. Resolves to the email or null. */
async function googleEmail(code, nonce, now = Date.now()) {
  const p = PROVIDERS.google;
  const res = await fetch(p.tokenUrl(), {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ code: String(code || ''), client_id: p.clientId(), client_secret: p.secret(), redirect_uri: callbackUrl('google'), grant_type: 'authorization_code' }),
    signal: AbortSignal.timeout(10000),
  }).catch(() => null);
  if (!res || !res.ok) return null;
  const body = await res.json().catch(() => ({}));
  const claims = await verifyIdToken('google', body.id_token, nonce, now);
  return claims ? String(claims.email).toLowerCase() : null;
}

/** Apple: the ID token arrives with the callback. Resolves to the email or null. */
async function appleEmail(idToken, nonce, now = Date.now()) {
  const claims = await verifyIdToken('apple', idToken, nonce, now);
  return claims ? String(claims.email).toLowerCase() : null;
}

const newNonce = () => crypto.randomBytes(16).toString('base64url');
function resetCache() { jwksCache.clear(); }

module.exports = { PROVIDERS, enabled, available, startUrl, callbackUrl, verifyIdToken, googleEmail, appleEmail, newNonce, resetCache };
