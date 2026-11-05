// How PsycheAI in Muse is used, as counts (README "Usage counts"), for the
// private page /admin/stats.
//
// Only what the server already sees, counted: nothing new is asked of the
// skill, so nothing about a person leaves Muse for this (the welcome's "None
// of your posts, messages or report go to PsycheAI"; muse-privacy's "a random
// ID for your Muse workspace, when things happened and a few counts").
//
//   Per day (table usage, 'YYYY-MM-DD' → counts): installs (accounts made),
//   Muse fetching the install link and a friend's Sync link, card art fetched
//   (once per workspace, the first time a card is drawn), and update checks by
//   release. No id, address, code or anything from a read is kept with them.
//
//   From records the server keeps anyway: skill accounts, those seen on a
//   later day than they started, those seen in the last 7 days, Sync links
//   made and Syncs written.

const crypto = require('node:crypto');
const store = require('./store');

const TABLE = 'usage';
const KEEP_DAYS = 400;
const KINDS = ['installs', 'installFetch', 'syncFetch', 'cardArt', 'updateChecks'];
const DAY = 86400000;

const dayOf = now => new Date(now).toISOString().slice(0, 10);

/** Add one to a day's count. `release` only for updateChecks. */
function bump(kind, now = Date.now(), release = null) {
  if (!KINDS.includes(kind)) return;
  const day = dayOf(now);
  const before = store.kvGet(TABLE, day);
  const row = { ...(before || {}) };
  row[kind] = (row[kind] || 0) + 1;
  if (kind === 'updateChecks' && /^\d{1,5}$/.test(String(release || ''))) {
    row.releases = { ...(row.releases || {}) };
    row.releases[release] = (row.releases[release] || 0) + 1;
  }
  store.kvSet(TABLE, day, row);
  // Old days go once a day, on a new day's first count.
  if (!before) {
    const cutoff = dayOf(now - KEEP_DAYS * DAY);
    for (const [key] of store.kvAll(TABLE)) if (key < cutoff) store.kvDel(TABLE, key);
  }
}

/** The release in the skill's User-Agent (PsycheAI-skill/161), or null. */
const releaseOf = ua => ((/^PsycheAI-skill\/(\d{1,5})\b/.exec(String(ua || ''))) || [])[1] || null;

/** Everything the page shows. */
function summary(now = Date.now()) {
  const rows = Object.fromEntries(store.kvAll(TABLE));
  const days = [];
  for (let i = 0; i < 30; i++) {
    const day = dayOf(now - i * DAY);
    const r = rows[day] || {};
    days.push({ day, ...Object.fromEntries(KINDS.map(k => [k, r[k] || 0])) });
  }
  const sum = (n, kind) => days.slice(0, n).reduce((t, d) => t + d[kind], 0);
  const allTime = kind => Object.values(rows).reduce((t, r) => t + (r[kind] || 0), 0);
  const window = n => Object.fromEntries(KINDS.map(k => [k, sum(n, k)]));

  const skillUsers = store.allUsers().filter(u => u.via === 'skill');
  const started = u => u.connectedAt || u.createdAt || 0;
  const accounts = {
    total: skillUsers.length,
    cameBack: skillUsers.filter(u => u.lastSeenAt && dayOf(u.lastSeenAt) > dayOf(started(u))).length,
    activeLast7Days: skillUsers.filter(u => u.lastSeenAt && now - u.lastSeenAt < 7 * DAY).length,
    newLast7Days: skillUsers.filter(u => now - started(u) < 7 * DAY).length,
  };
  const syncTimes = store.kvAll('sync').map(([, s]) => (s && s.at) || 0);
  const syncs = {
    linksMade: store.kvAll('synccodeof').length,
    written: syncTimes.length,
    writtenLast7Days: syncTimes.filter(t => now - t < 7 * DAY).length,
  };
  const releases = {};
  for (const day of days.slice(0, 7)) for (const [rel, n] of Object.entries((rows[day.day] || {}).releases || {})) releases[rel] = (releases[rel] || 0) + n;

  return {
    at: new Date(now).toISOString().slice(0, 16).replace('T', ' ') + ' UTC',
    today: days[0], last7Days: window(7), last30Days: window(30),
    allTime: Object.fromEntries(KINDS.map(k => [k, allTime(k)])),
    accounts, syncs, releasesLast7Days: releases, days,
  };
}

/** The page's password: PSYCHE_ADMIN_SECRET, 24 characters at least, else the page is off. */
function authorised(header, secret = process.env.PSYCHE_ADMIN_SECRET) {
  if (!secret || secret.length < 24) return false;
  const m = /^Basic\s+([A-Za-z0-9+/=]+)$/.exec(String(header || ''));
  if (!m) return false;
  const given = Buffer.from(m[1], 'base64').toString('utf8').split(':').slice(1).join(':');
  const a = crypto.createHash('sha256').update(given).digest();
  const b = crypto.createHash('sha256').update(secret).digest();
  return crypto.timingSafeEqual(a, b);
}

const esc = s => String(s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

/** The page itself: plain HTML, no scripts. */
function page(s = summary()) {
  const LABEL = { installs: 'Installs (accounts made)', installFetch: 'Install link fetched by Muse', syncFetch: 'Friend\'s Sync link fetched by Muse',
    cardArt: 'First cards drawn (card art fetched)', updateChecks: 'Update checks' };
  const row = (label, ...cells) => `<tr><th>${esc(label)}</th>${cells.map(c => `<td>${esc(c)}</td>`).join('')}</tr>`;
  const rate = (a, b) => (b ? Math.min(100, Math.round((100 * a) / b)) + '%' : '–');
  // Days from the first one counted (none before this page existed), as "5 Nov".
  const first = s.days.reduce((i, d, n) => (KINDS.some(k => d[k]) ? n : i), 0);
  const shown = s.days.slice(0, first + 1);
  const shortDay = d => Number(d.slice(8)) + ' ' + ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(d.slice(5, 7)) - 1];
  const rel = Object.entries(s.releasesLast7Days).sort((a, b) => Number(b[0]) - Number(a[0]));
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex"><title>PsycheAI in Muse: usage</title>
<style>body{font:15px/1.45 -apple-system,system-ui,sans-serif;margin:0;padding:16px;background:#faf7fb;color:#241a2e}h1{font-size:20px}h2{font-size:16px;margin-top:24px}
table{border-collapse:collapse;width:100%;max-width:760px;background:#fff}th,td{border-bottom:1px solid #e7dfec;padding:6px 6px;text-align:right;white-space:nowrap}th:first-child{text-align:left;white-space:normal}
.wrap{overflow-x:auto}.days th{white-space:nowrap}.days td,.days th{font-size:13px}.note{color:#6b6076;font-size:13px;max-width:760px}@media(prefers-color-scheme:dark){body{background:#17121c;color:#eee}table{background:#221a29}th,td{border-color:#3a2f44}.note{color:#b5a9c0}}</style></head><body>
<h1>PsycheAI in Muse: usage</h1><p class="note">As of ${esc(s.at)}. Counts only: no ids, addresses, codes or anything from a read.</p>
<h2>Funnel</h2><div class="wrap"><table><tr><th></th><td>Today</td><td>7 days</td><td>30 days</td><td>All time</td></tr>
${['installFetch', 'syncFetch', 'installs', 'cardArt'].map(k => row(LABEL[k], s.today[k], s.last7Days[k], s.last30Days[k], s.allTime[k])).join('\n')}
${row('Reached a card, of installs', rate(s.today.cardArt, s.today.installs), rate(s.last7Days.cardArt, s.last7Days.installs), rate(s.last30Days.cardArt, s.last30Days.installs), rate(s.allTime.cardArt, s.allTime.installs))}
</table></div>
<h2>Accounts</h2><div class="wrap"><table>
${row('Skill accounts', s.accounts.total)}${row('New in the last 7 days', s.accounts.newLast7Days)}
${row('Came back on a later day', s.accounts.cameBack + ' (' + rate(s.accounts.cameBack, s.accounts.total) + ')')}${row('Active in the last 7 days', s.accounts.activeLast7Days)}
</table></div>
<h2>Sync</h2><div class="wrap"><table>
${row('Sync links made', s.syncs.linksMade)}${row('Syncs written', s.syncs.written)}${row('Syncs written, last 7 days', s.syncs.writtenLast7Days)}
</table></div>
<h2>Releases checking for updates, last 7 days</h2><div class="wrap"><table>
${rel.length ? rel.map(([r, n]) => row('Release ' + r, n)).join('\n') : row('None yet', '')}
</table></div>
<h2>Last 30 days</h2><div class="wrap"><table class="days"><tr><th>Day</th><td>Installs</td><td>Install link</td><td>Sync link</td><td>First cards</td><td>Updates</td></tr>
${shown.map(d => row(shortDay(d.day), d.installs, d.installFetch, d.syncFetch, d.cardArt, d.updateChecks)).join('\n')}
</table></div>
<p class="note">Install and Sync links count each time Muse fetches them, so a retry counts again. First cards are the card art's one download per workspace: someone who deletes everything and starts again counts twice. Older releases (before 3 Nov 2026) are the only ones still reporting read timings, on /health.</p>
</body></html>`;
}

module.exports = { bump, releaseOf, summary, authorised, page, KINDS, TABLE };
