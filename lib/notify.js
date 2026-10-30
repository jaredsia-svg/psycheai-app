// Notifications, kept tight: everything happens in the host first, and email
// is only the nudge for someone who has not been back.
//
// Events (someone picked you, it's mutual, a new message) wait in a list per
// person. Any visit to the host clears the list, since the host shows the same
// things there (lib/instructions.js "Every later visit"). Once an hour,
// digest() emails one summary to each person who has events waiting, has not
// visited for AWAY_MS, and has not had a digest for AWAY_MS: at most one email
// a day, never while they are using the app, each event at most once.

const store = require('./store');
const mail = require('./mail');

const AWAY_MS = 24 * 3600000;
const TABLE = 'notes';

/** Queue an event. A second message from the same match folds into the first. */
function note(userId, kind, data, now = Date.now()) {
  const list = store.kvGet(TABLE, userId) || [];
  const same = list.find(n => n.kind === kind && n.data.introId && n.data.introId === data.introId);
  if (same) { same.count = (same.count || 1) + 1; same.at = now; }
  else list.push({ kind, data, at: now, count: 1 });
  store.kvSet(TABLE, userId, list);
}

/** The user is here: remember when, and drop what the host will now show them. */
function seen(userId, now = Date.now()) {
  if (!store.getUser(userId)) return;
  store.updateUser(userId, { lastSeenAt: now });
  store.kvDel(TABLE, userId);
}

const pending = userId => store.kvGet(TABLE, userId) || [];

function line(n) {
  const d = n.data;
  if (n.kind === 'picked') return `${d.name} picked you this week. Yes: ${d.yes}  ·  No thanks: ${d.no}`;
  if (n.kind === 'mutual') return `It's mutual with ${d.name}.` + (d.chat ? ` Chat privately: ${d.chat}` : '');
  if (n.kind === 'message') return `${d.name} sent you ${n.count === 1 ? 'a message' : n.count + ' messages'}.` + (d.chat ? ` Read and reply: ${d.chat}` : '');
  if (n.kind === 'syncAsk') return `${d.name} wants to see how you two sync. Say yes in Muse: "Sync with them".`;
  if (n.kind === 'synced') return `${d.name || 'A friend'} synced with you: your Sync is ready. Ask Muse to "show my Syncs".`;
  if (n.kind === 'readClosing') return 'Your Psyche link closes tomorrow. Open it from your Muse chat to keep them: once opened, they stay in your browser.';
  if (n.kind === 'pairOpen') return `Psyche Pair is open${d.city ? ' in ' + d.city : ''} now, and you were on the list. Open PsycheAI in Muse and say "Find potential romantic matches".`;
  if (n.kind === 'drop') return 'Your matches for this week are ready. Ask Muse to "show my Psyche Pair matches".';
  return null;
}

function subjectFor(list) {
  const first = list[0];
  const head = first.kind === 'picked' ? `${first.data.name} picked you`
    : first.kind === 'mutual' ? `It's mutual with ${first.data.name}`
      : first.kind === 'message' ? `${first.data.name} sent you a message`
        : first.kind === 'syncAsk' ? `${first.data.name} wants to sync with you`
          : first.kind === 'synced' ? (first.data.name ? `Your Sync with ${first.data.name} is ready` : 'A friend synced with you')
            : first.kind === 'readClosing' ? 'Open your Psyche before the link closes'
            : first.kind === 'pairOpen' ? `Psyche Pair is open${first.data.city ? ' in ' + first.data.city : ''}`
            : 'Your matches for this week are ready';
  return 'PsycheAI: ' + head + (list.length > 1 ? `, and ${list.length - 1} more` : '');
}

/**
 * Send what is due. `hasNewDrop(userId)` says whether this week's matches are
 * waiting unseen (lib/weekly.js), so the digest can say so without making the
 * drop itself.
 */
function digest(now = Date.now(), { hasNewDrop = () => false } = {}) {
  let sent = 0;
  for (const user of store.allUsers()) {
    if (user.lastSeenAt && now - user.lastSeenAt < AWAY_MS) continue;
    if (user.lastDigestAt && now - user.lastDigestAt < AWAY_MS) continue;
    const list = [...pending(user.id)];
    if (user.reviewedAt && !list.some(n => n.kind === 'drop') && hasNewDrop(user.id, now)) list.push({ kind: 'drop', data: {}, at: now, count: 1 });
    const email = store.emailOf(user.id);
    if (!list.length || !email) continue;
    const order = { readClosing: -1, picked: 0, mutual: 1, message: 2, synced: 3, syncAsk: 4, pairOpen: 5, drop: 6 };
    list.sort((a, b) => order[a.kind] - order[b.kind]);
    mail.send({
      to: email,
      subject: subjectFor(list),
      text: list.map(line).filter(Boolean).map(l => '• ' + l).join('\n\n') +
        '\n\nOr just open PsycheAI in Muse.\n\n' +
        'You get at most one email a day, and only when you haven\'t been on for a day.',
    });
    store.updateUser(user.id, { lastDigestAt: now });
    store.kvDel(TABLE, user.id);
    sent++;
  }
  return sent;
}

module.exports = { AWAY_MS, note, seen, pending, digest, line };
