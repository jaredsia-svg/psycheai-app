// How long a Muse read takes, stage by stage (README "Measuring a read").
//
// The skill's bin/psyche.py notes when each of its own commands runs (only
// the command's name: start, the guide, check-digest, publish_psyche…) and,
// once a Psyche is saved, sends those marks here as seconds before the save
// finished. Nothing from the read itself and nobody's id is kept: a run is
// its stages in seconds, the digest's size and how many reads it has had.
// /health shows the latest, so a slow stage is visible without asking anyone.

const crypto = require('node:crypto');
const store = require('./store');

const TABLE = 'readtiming';
const KEEP = 20;
const LABEL = /^[a-z][a-z_:-]{0,39}$/;
const WINDOW = 3 * 3600;      // marks older than this before the save aren't this read

const first = (marks, label) => (marks.find(([l]) => l === label) || [])[1];
const last = (marks, label) => ([...marks].reverse().find(([l]) => l === label) || [])[1];
const span = (from, to) => (Number.isFinite(from) && Number.isFinite(to) && to >= from ? Math.round(to - from) : null);

/** The marks as stages: guide → first check-digest is reading, then fixing, writing and saving. */
function stages(marks) {
  const guide = first(marks, 'call:get_report_guide');
  const check1 = first(marks, 'check-digest');
  const checkN = last(marks, 'check-digest');
  const publish = last(marks, 'call:publish_psyche');
  const begin = Number.isFinite(guide) ? guide : marks.length ? marks[0][1] : null;
  return {
    reading: span(begin, check1), fixing: span(check1, checkN), writing: span(checkN, publish),
    saving: span(publish, 0), total: span(begin, 0), checks: marks.filter(([l]) => l === 'check-digest').length,
  };
}

/** Keep one run's timing. Anything malformed is dropped, not stored. */
function record(body, now = Date.now()) {
  const raw = Array.isArray(body && body.marks) ? body.marks.slice(-60) : [];
  const marks = raw.filter(m => Array.isArray(m) && LABEL.test(String(m[0])) && Number.isFinite(m[1]) && m[1] <= 0 && m[1] >= -WINDOW)
    .map(([l, t]) => [String(l), Math.round(t)]).sort((a, b) => a[1] - b[1]);
  if (!marks.length) return { ok: false, error: 'No marks.' };
  const num = (v, max) => (Number.isFinite(v) && v >= 0 ? Math.min(Math.round(v), max) : null);
  const run = { at: new Date(now).toISOString().slice(0, 16), ...stages(marks), chars: num(body.chars, 2e6), reads: num(body.reads, 1000),
    messages: body.messages === true, marks };
  store.kvSet(TABLE, crypto.randomBytes(6).toString('hex'), run);
  const all = store.kvAll(TABLE).sort((a, b) => String(b[1].at).localeCompare(String(a[1].at)));
  for (const [key] of all.slice(KEEP)) store.kvDel(TABLE, key);
  return { ok: true };
}

/** The latest runs, newest first, for /health. */
const latest = (n = 10) => store.kvAll(TABLE).map(([, run]) => run)
  .sort((a, b) => String(b.at).localeCompare(String(a.at))).slice(0, n)
  .map(({ marks, ...run }) => run);

module.exports = { record, latest, stages };
