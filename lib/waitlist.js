// Psyche Pair, switched off for now (README "Pair behind a switch"): the
// PsycheAI card, report and Sync launch first, and Pair opens city by city
// once enough people are waiting to give everyone real matches.
//
// PSYCHE_PAIR=1 opens it everywhere. City by city (README "Pair opens city by
// city"): PSYCHE_PAIR_CITIES="singapore, london" opens those, and
// PSYCHE_PAIR_AUTO=150 opens any city once that many are waiting there. A
// city is the user's own (the waitlist's, or their Pair profile's), compared
// as the matcher does, in lower case. Someone whose city isn't known yet sees
// the waitlist, and joining it with an open city lets them start at once.
//
// Closed, Muse doesn't see the Pair tools, the menu
// offers "Join the Psyche Pair waitlist" instead, and joining keeps only that
// they want it and their city, so we can see where to open first (/health
// gives the counts). Once it opens, everyone on the list hears so on their next
// visit (start's news), once.

const store = require('./store');

const TABLE = 'pairwait';   // userId → { city, at, told }
const JOIN = 'Join the Psyche Pair waitlist';
const OPEN_LABEL = 'Find potential romantic matches';

/** Open everywhere. */
const isOpen = () => process.env.PSYCHE_PAIR === '1';
const cityKey = city => String(city || '').replace(/\s+/g, ' ').trim().slice(0, 60);
const lower = city => cityKey(city).toLowerCase();
const listed = () => String(process.env.PSYCHE_PAIR_CITIES || '').split(',').map(lower).filter(Boolean);
const autoAt = () => Math.max(0, Number(process.env.PSYCHE_PAIR_AUTO) || 0);

// Waiting per city, counted at most once a minute.
let tally = null;
function waiting(now = Date.now()) {
  if (tally && now - tally.at < 60000) return tally.cities;
  const cities = {};
  for (const [, row] of store.kvAll(TABLE)) if (row && row.city) cities[lower(row.city)] = (cities[lower(row.city)] || 0) + 1;
  tally = { at: now, cities };
  return cities;
}

/** Whether Pair is open in this city. */
function cityOpen(city, now = Date.now()) {
  if (isOpen()) return true;
  const c = lower(city);
  if (!c) return false;
  return listed().includes(c) || (autoAt() > 0 && (waiting(now)[c] || 0) >= autoAt());
}
/** Open anywhere at all: then the Pair tools are listed. */
const anyOpen = () => isOpen() || listed().length > 0 || autoAt() > 0;

/** The user's city, as far as we know it: their Pair profile's, else the waitlist's. */
function cityOf(user) {
  if (!user) return null;
  const fromProfile = user.profile && user.profile.basics && user.profile.basics.city;
  const fromDraft = user.draft && user.draft.basics && user.draft.basics.city;
  const row = store.kvGet(TABLE, user.id);
  return cityKey(fromProfile || fromDraft || (row && row.city)) || null;
}
/** Whether Pair is open for this user. */
const openFor = (user, now = Date.now()) => isOpen() || cityOpen(cityOf(user), now);
/** The menu label for Pair, for this user (or everywhere, with none). */
const label = user => ((user === undefined ? isOpen() : openFor(user)) ? OPEN_LABEL : JOIN);

/** join_pair_waitlist: note that they want Psyche Pair, and where. */
function join(user, args = {}, now = Date.now()) {
  const before = store.kvGet(TABLE, user.id);
  const city = cityKey(args.city) || (before && before.city) || cityOf(user) || null;
  if (cityOpen(city, now)) return { open: true, city, say: `Psyche Pair is open${city && !isOpen() ? ' in ' + city : ''}: you can start now.` };
  store.kvSet(TABLE, user.id, { city, at: (before && before.at) || now, told: false });
  tally = null;
  const hasEmail = Boolean(store.emailOf && store.emailOf(user.id));
  return { joined: true, city, already: Boolean(before), hasEmail };
}

const onList = userId => Boolean(store.kvGet(TABLE, userId));

/** Once Pair is open where they are: a line for someone on the list who hasn't been told. */
function openedNews(userId) {
  const row = store.kvGet(TABLE, userId);
  if (!row || row.told || !cityOpen(row.city)) return null;
  store.kvSet(TABLE, userId, { ...row, told: true, emailed: true });
  return `Psyche Pair is open${row.city && !isOpen() ? ' in ' + row.city : ''} now, and you were on the list: tap "Find potential romantic matches" to start.`;
}

/**
 * Hourly: everyone waiting in a city that has opened, not yet told, gets a
 * note (the email digest's, for those with an email), once.
 */
function announce(now = Date.now()) {
  const notify = require('./notify');
  let noted = 0;
  for (const [userId, row] of store.kvAll(TABLE)) {
    if (!row || row.told || row.emailed || !cityOpen(row.city, now) || !store.getUser(userId)) continue;
    notify.note(userId, 'pairOpen', { city: row.city || null }, now);
    store.kvSet(TABLE, userId, { ...row, emailed: true });
    noted++;
  }
  return noted;
}

/** How many are waiting, and where (cities by count). */
function counts() {
  const cities = {};
  let total = 0;
  for (const [, row] of store.kvAll(TABLE)) {
    total++;
    const c = row && row.city ? row.city.toLowerCase() : 'unknown';
    cities[c] = (cities[c] || 0) + 1;
  }
  return {
    open: isOpen(), openCities: listed(), autoAt: autoAt() || null, total,
    cities: Object.entries(cities).sort((a, b) => b[1] - a[1]).slice(0, 20).map(([c, n]) => [c, n, cityOpen(c)]),
  };
}

const forget = userId => store.kvDel(TABLE, userId);

module.exports = { JOIN, OPEN_LABEL, isOpen, anyOpen, cityOpen, cityOf, openFor, label, join, onList, openedNews, announce, counts, forget };
