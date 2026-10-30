// Email: sign-in codes, and the daily digest (lib/notify.js).

const { BASE_URL } = require('./config');

const RESEND_KEY = process.env.RESEND_API_KEY || '';
const FROM = process.env.MAIL_FROM || 'PsycheAI <app@psycheai.io>';

const outbox = [];

// Through Resend when RESEND_API_KEY is set (the From domain must be verified
// there); otherwise only the outbox and, outside tests, the console. Sending
// never blocks or fails the request that caused it; a failure is logged.
function send({ to, subject, text }) {
  const message = { to, subject, text, at: Date.now() };
  outbox.push(message);
  if (outbox.length > 200) outbox.shift();
  if (RESEND_KEY) {
    fetch('https://api.resend.com/emails', {
      method: 'POST',
      headers: { Authorization: 'Bearer ' + RESEND_KEY, 'Content-Type': 'application/json' },
      body: JSON.stringify({ from: FROM, to: [to], subject, text }),
      signal: AbortSignal.timeout(10000),
    }).then(res => { if (!res.ok) console.error('[mail] resend %s for %s', res.status, subject); })
      .catch(err => console.error('[mail] resend failed:', err.message));
  } else if (process.env.NODE_ENV !== 'test') {
    console.log('[mail] to=%s subject=%s\n%s', to, subject, text);
  }
  return message;
}

const introLink = (intro, answer) => `${BASE_URL}/intro/${intro.id}?t=${intro.linkToken}&a=${answer}`;

function chatLink(intro, userId) {
  const token = intro.chatTokens && intro.chatTokens[userId];
  return token ? `${BASE_URL}/chat/${intro.id}?t=${token}` : null;
}

module.exports = { outbox, send, introLink, chatLink };
