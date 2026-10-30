// Turns a raw pair score into the fit % people see, so that a number always
// means the same thing: fit 80 is the top 5% of eligible pairs in the pool,
// 90 about the top 1%, 97 about the top 0.1%.
//
//   fit = 100 − 20 · √((1 − p) / 0.05),   p = the pair's percentile
//
// The reference is every eligible pair in the pool once there are
// MIN_REFERENCE of them; before that, a seeded synthetic pool
// (tools/calibrate.mjs prints DEFAULT_REFERENCE).
//
// Rank alone is not enough: in a weak pool the top 5% can still be poor. So a
// match must also clear RAW_FLOOR on the raw score. When nobody clears both,
// the drop is empty, by design: showing no one beats showing the wrong one.

const TOP_SHARE = 0.05;
const FIT_AT_TOP_SHARE = 80;
const MIN_REFERENCE = 500;
const RAW_FLOOR = Number(process.env.PSYCHE_RAW_FLOOR || 66);
const DEFAULT_REFERENCE = [46, 56, 57, 59, 60, 60, 61, 62, 63, 63, 64, 65, 65, 66, 67, 67, 68, 69, 70, 72, 85];

/** Where raw falls in a sorted list, 0..1, interpolating between points and splitting ties. */
function percentile(raw, sorted) {
  const n = sorted.length;
  if (n < 2) return 0.5;
  if (raw <= sorted[0]) return 0;
  if (raw >= sorted[n - 1]) return 1;
  let below = 0, upTo = 0;
  for (const v of sorted) { if (v < raw) below++; if (v <= raw) upTo++; }
  if (upTo > below) return ((below + upTo - 1) / 2) / (n - 1);
  const a = sorted[below - 1], b = sorted[below];
  return (below - 1 + (raw - a) / (b - a)) / (n - 1);
}

function toFit(raw, sorted) {
  const p = percentile(raw, sorted);
  const fit = 100 - (100 - FIT_AT_TOP_SHARE) * Math.sqrt((1 - p) / TOP_SHARE);
  return Math.max(0, Math.min(99, Math.round(fit)));
}

/** The reference to rank against: the pool's own raw scores once it has enough pairs. */
function referenceFrom(poolRaws) {
  return poolRaws.length >= MIN_REFERENCE ? [...poolRaws].sort((x, y) => x - y) : DEFAULT_REFERENCE;
}

module.exports = { RAW_FLOOR, MIN_REFERENCE, DEFAULT_REFERENCE, percentile, toFit, referenceFrom };
