// In-app chat for a mutual match, for anyone who would rather not hand over
// their Instagram or number yet. Read and written in the host ("show my
// Psyche Pair messages"), or from the private web page linked in the digest
// for someone who has been away.
//
// This is the one place Psyche Pair holds words people wrote, so:
//   - each message is sealed with AES-256-GCM under PSYCHE_CHAT_KEY, and the
//     store only ever sees the sealed box;
//   - nobody at Psyche Pair reads chats. A thread is opened for review only
//     when one of the two reports the other, and is then kept REPORT_HOLD_DAYS
//     instead of being deleted on schedule;
//   - messages are deleted after RETENTION_DAYS, and the whole thread is
//     deleted when either person ends it ("we've swapped numbers"), blocks,
//     or deletes their data.
// The host shows messages to the user as they read them, so they also pass
// through Meta (or OpenAI); README "Chat" says so, and so must the privacy page.

const crypto = require('node:crypto');
const store = require('./store');
const mail = require('./mail');
const notify = require('./notify');

const TEXT_MAX = 1000;
const RETENTION_DAYS = 30;
const REPORT_HOLD_DAYS = 90;
const RATE_PER_HOUR = 30;
const DAY = 86400000;

// Any secret string works: 32 bytes of base64 is used as is, anything else is
// hashed down to a key. It must never change once chats exist.
const RAW_KEY = process.env.PSYCHE_CHAT_KEY || '';
const asBytes = RAW_KEY ? Buffer.from(RAW_KEY, 'base64') : null;
const KEY = !RAW_KEY ? crypto.randomBytes(32)
  : asBytes.length === 32 ? asBytes : crypto.createHash('sha256').update(RAW_KEY).digest();
if (!process.env.PSYCHE_CHAT_KEY && process.env.NODE_ENV !== 'test') {
  console.warn('[chat] PSYCHE_CHAT_KEY not set: using a key that dies with this process');
}

function seal(text, aad) {
  const iv = crypto.randomBytes(12);
  const c = crypto.createCipheriv('aes-256-gcm', KEY, iv);
  c.setAAD(Buffer.from(aad));
  const data = Buffer.concat([c.update(text, 'utf8'), c.final()]);
  return [iv, c.getAuthTag(), data].map(x => x.toString('base64url')).join('.');
}

function open(box, aad) {
  const [iv, tag, data] = box.split('.').map(x => Buffer.from(x, 'base64url'));
  const d = crypto.createDecipheriv('aes-256-gcm', KEY, iv);
  d.setAAD(Buffer.from(aad));
  d.setAuthTag(tag);
  return Buffer.concat([d.update(data), d.final()]).toString('utf8');
}

/** The mutual intro if this user is in it and it is open for chat, else null. */
function threadFor(introId, userId) {
  const intro = store.getIntro(introId);
  if (!intro || intro.status !== 'mutual' || (intro.from !== userId && intro.to !== userId)) return null;
  const other = intro.from === userId ? intro.to : intro.from;
  const me = store.getUser(userId), them = store.getUser(other);
  if (!me || !them) return null;
  if ((me.blocked || []).includes(other) || (them.blocked || []).includes(userId)) return null;
  return { intro, me, them };
}

const emptyChat = () => ({ messages: [], lastRead: {}, heldUntil: null, ended: false });

function send(introId, userId, text, now = Date.now()) {
  const t = threadFor(introId, userId);
  if (!t) return { ok: false, error: 'No open chat with that match.' };
  const body = String(text || '').replace(/\r\n/g, '\n').trim();
  if (!body) return { ok: false, error: 'Write something first.' };
  if (body.length > TEXT_MAX) return { ok: false, error: `Keep it under ${TEXT_MAX} characters.` };
  const chat = store.getChat(introId) || emptyChat();
  if (chat.ended) return { ok: false, error: 'This chat was ended.' };
  const recent = chat.messages.filter(m => m.from === userId && now - m.at < 3600000).length;
  if (recent >= RATE_PER_HOUR) return { ok: false, error: 'Slow down a little: try again in a while.' };
  chat.messages.push({ from: userId, at: now, box: seal(body, introId) });
  chat.lastRead[userId] = now;
  store.setChat(introId, chat);
  notify.note(t.them.id, 'message', { introId, name: t.me.profile.basics.firstName, chat: mail.chatLink(t.intro, t.them.id) }, now);
  return { ok: true };
}

/** The thread for this user, newest last, and mark it read. */
function read(introId, userId, now = Date.now()) {
  const t = threadFor(introId, userId);
  if (!t) return { ok: false, error: 'No open chat with that match.' };
  const chat = store.getChat(introId) || emptyChat();
  const messages = chat.messages.map(m => ({ mine: m.from === userId, at: new Date(m.at).toISOString(), text: open(m.box, introId) }));
  if (chat.messages.length) { chat.lastRead[userId] = now; store.setChat(introId, chat); }
  return { ok: true, with: t.them.profile.basics.firstName, ended: chat.ended, messages };
}

/** Each mutual match with unread messages for this user. */
function unread(userId) {
  const out = [];
  for (const [introId, chat] of store.allChats()) {
    const t = threadFor(introId, userId);
    if (!t) continue;
    const since = chat.lastRead[userId] || 0;
    const count = chat.messages.filter(m => m.from !== userId && m.at > since).length;
    if (count) out.push({ introId, from: t.them.profile.basics.firstName, unread: count });
  }
  return out;
}

/** Either person ends the chat: every message is deleted, unless a report holds it. */
function end(introId, userId) {
  const t = threadFor(introId, userId);
  if (!t) return { ok: false, error: 'No open chat with that match.' };
  const chat = store.getChat(introId) || emptyChat();
  chat.ended = true;
  if (!chat.heldUntil) chat.messages = [];
  store.setChat(introId, chat);
  return { ok: true };
}

/** A block without a report: the thread goes, unless an earlier report holds it. */
function dropUnlessHeld(introId, now = Date.now()) {
  const chat = store.getChat(introId);
  if (chat && !(chat.heldUntil && chat.heldUntil > now)) store.setChat(introId, null);
}

/** A report keeps the thread for review instead of letting it be deleted. */
function holdForReport(introId, now = Date.now()) {
  const chat = store.getChat(introId);
  if (!chat) return false;
  chat.heldUntil = now + REPORT_HOLD_DAYS * DAY;
  store.setChat(introId, chat);
  return true;
}

/** Delete what is past its time. Run on a timer. */
function sweep(now = Date.now()) {
  let removed = 0;
  for (const [introId, chat] of store.allChats()) {
    if (chat.heldUntil && chat.heldUntil > now) continue;
    if (chat.heldUntil) chat.heldUntil = null;
    const before = chat.messages.length;
    chat.messages = chat.ended ? [] : chat.messages.filter(m => now - m.at < RETENTION_DAYS * DAY);
    removed += before - chat.messages.length;
    store.setChat(introId, chat.messages.length || !chat.ended ? chat : null);
  }
  return removed;
}

module.exports = { TEXT_MAX, RETENTION_DAYS, REPORT_HOLD_DAYS, send, read, unread, end, holdForReport, dropUnlessHeld, sweep, seal, open };
