// How well do you know me? (README "The quiz", PLAN.md "How well do you know me?"): a PsycheAI user makes a quiz
// about themselves in Muse and sends its link to friends, who answer it on a web page with no sign-in.
//
// The quiz is written and locked in the owner's Muse (bin/psyche.py quiz-publish), with the key after the # of its
// link, so it never reaches this server: like a Sync, this is a mailbox of boxes it can't open.
//   - the quiz:            locked with the link's code; the page opens it in the friend's browser to show and mark it
//   - each friend's answers: locked in their browser for the owner's eyes (their first name and picks); only the
//                          owner's skill is given them, and only it can open them, holding the same code
//   - a name for the board: locked with the code too, only when the friend ticked "Show my name"
// What this server can read is a count and a score per answer: enough for "better than 70% of friends" and the news.
//
//   quiz_put   the owner's skill saves a new quiz (its id, the hash of the code, and the locked box); it replaces theirs
//   quiz_get   the owner's quiz with the friends' locked answers, for the results, opened on their device
//   quiz_end   the owner ends it: the quiz and every answer go
//   data()     the page: the locked quiz and the board, by id
//   answer()   the page: a friend's score and locked boxes

const store = require('./store');
const notify = require('./notify');

const QUIZZES = 'quiz';        // id (hash of the code) → { owner, box, n, at, answers: [{ s, box, name, at }], seen }
const OF = 'quizof';           // userId → id of their quiz
const ID = /^[0-9a-f]{64}$/;
const B64 = /^[A-Za-z0-9_-]+$/;
const MIN_Q = 5, MAX_Q = 15;            // release 228: fourteen written, eight or more kept
const QUIZ_MAX = 210000;       // characters of the quiz's ciphertext: fifteen questions and a picture of their card (under /mcp's 256 KB)
const ANSWER_MAX = 1200;       // a first name and up to ten picks
const NAME_MAX = 200;
const MAX_ANSWERS = 500;
const BOARD = 20;
const KEEP_DAYS = 365;

function box(b, max) {
  if (!b || typeof b !== 'object' || Array.isArray(b) || b.v !== 'e2e1') return null;
  const { n, c, t } = b;
  if (![n, c, t].every(x => typeof x === 'string' && B64.test(x)) || n.length !== 22 || t.length !== 43 || c.length > max) return null;
  return { v: 'e2e1', n, c, t };
}

const skillOnly = user => (user && user.via === 'skill' ? null : { error: 'The quiz is made in the PsycheAI skill, which locks it on the device.' });

function mine(user) {
  const id = store.kvGet(OF, user.id);
  const row = id && store.kvGet(QUIZZES, id);
  return row && row.owner === user.id ? { id, row } : null;
}

function drop(id) {
  if (id) store.kvDel(QUIZZES, id);
}

/** The owner's skill saves a quiz: { e2e: { id, box, n } }. A new one replaces their old one, and its answers go with it. */
function put(user, args = {}, now = Date.now()) {
  const no = skillOnly(user);
  if (no) return no;
  const e = args.e2e || {};
  const id = ID.test(String(e.id || '')) ? String(e.id) : null;
  const b = box(e.box, QUIZ_MAX);
  const n = Number(e.n);
  if (!id || !b || !Number.isInteger(n) || n < MIN_Q || n > MAX_Q) return { error: 'The quiz is not valid: update PsycheAI and try again.' };
  const taken = store.kvGet(QUIZZES, id);
  if (taken && taken.owner !== user.id) return { error: 'That quiz id is taken: make the quiz again.' };
  const old = mine(user);
  if (old && old.id !== id) drop(old.id);
  // Saving the same quiz again (a retry) keeps its answers: they were made against these questions.
  const same = taken && taken.n === n ? taken : null;
  store.kvSet(QUIZZES, id, { owner: user.id, box: b, n, at: now, answers: same ? same.answers : [], seen: same ? same.seen : 0 });
  store.kvSet(OF, user.id, id);
  return { ok: true };
}

/** The owner's quiz and every friend's locked answers, for the results; reading them marks them seen. */
function get(user) {
  const no = skillOnly(user);
  if (no) return no;
  const m = mine(user);
  if (!m) return { none: true };
  const { id, row } = m;
  const seen = row.seen || 0;
  if (seen !== row.answers.length) store.kvSet(QUIZZES, id, { ...row, seen: row.answers.length });
  return { id, box: row.box, n: row.n, at: row.at, seen, answers: row.answers.map(a => ({ s: a.s, box: a.box, at: a.at })) };
}

function end(user) {
  const no = skillOnly(user);
  if (no) return no;
  const m = mine(user);
  if (m) drop(m.id);
  store.kvDel(OF, user.id);
  return { ended: true };
}

/** For get_news: how many friends have answered, and how many since the owner last looked. */
function news(user) {
  const m = user && mine(user);
  if (!m) return null;
  const total = m.row.answers.length;
  return { answers: total, new: Math.max(0, total - (m.row.seen || 0)) };
}

function forget(userId) {
  const id = store.kvGet(OF, userId);
  const row = id && store.kvGet(QUIZZES, id);
  if (row && row.owner === userId) drop(id);
  store.kvDel(OF, userId);
}

function sweep(now = Date.now()) {
  for (const [id, row] of store.kvAll(QUIZZES)) {
    if (!row || now - row.at > KEEP_DAYS * 86400000 || !store.getUser(row.owner)) {
      drop(id);
      if (row && store.kvGet(OF, row.owner) === id) store.kvDel(OF, row.owner);
    }
  }
}

// The board: the best scores first, then the earliest, with a locked name only for those who chose to show it.
const ranked = answers => answers.map((a, i) => ({ ...a, i })).sort((x, y) => y.s - x.s || x.at - y.at);
const boardOf = answers => ranked(answers).slice(0, BOARD).map(a => ({ s: a.s, name: a.name || null }));

/** The page, by id: the locked quiz, how many questions, and the board. */
function data(id) {
  const row = ID.test(String(id || '')) ? store.kvGet(QUIZZES, String(id)) : null;
  if (!row) return { error: 'This quiz has ended, or the link isn\'t complete.' };
  return { box: row.box, n: row.n, count: row.answers.length, board: boardOf(row.answers) };
}

/** A friend's answers, from the page: { s, box, name }. The score is the page's count of right answers. */
function answer(id, body = {}, now = Date.now()) {
  const row = ID.test(String(id || '')) ? store.kvGet(QUIZZES, String(id)) : null;
  if (!row) return { error: 'This quiz has ended, or the link isn\'t complete.' };
  const s = Number(body.s);
  const b = box(body.box, ANSWER_MAX);
  const name = body.name == null ? null : box(body.name, NAME_MAX);
  if (!Number.isInteger(s) || s < 0 || s > row.n || !b || (body.name != null && !name)) return { error: 'Those answers couldn\'t be read. Reload the page and try again.' };
  if (row.answers.length >= MAX_ANSWERS) return { error: 'This quiz has all the answers it can take.' };
  const others = row.answers;
  const below = others.filter(a => a.s < s).length;
  const answers = [...others, { s, box: b, name, at: now }];
  store.kvSet(QUIZZES, String(id), { ...row, answers });
  notify.note(row.owner, 'quiz', {}, now);
  const rank = ranked(answers).findIndex(a => a.at === now && a.s === s && a.box === b) + 1;
  return {
    s, n: row.n, count: answers.length, rank,
    better: others.length ? Math.round(100 * below / others.length) : null,
    top: others.every(a => a.s <= s),
    board: boardOf(answers),
  };
}

module.exports = { put, get, end, news, forget, sweep, data, answer, MIN_Q, MAX_Q, QUIZ_MAX, ANSWER_MAX, NAME_MAX, MAX_ANSWERS };
