// What a user wants in a partner, in their own words, turned into rules.
//
// The user types something like "ambitious but not a workaholic, likes hiking,
// wants kids in a few years, no smokers". The host assistant splits it into
// must-haves (filters) and nice-to-haves (extra points) over the same field
// keys as the profile, shows the user the list and the pool size it leaves,
// and only then saves it. Doing the parsing in the host costs us nothing and
// keeps the user's sentence on their side: we store the rules, and the brief
// only as the user's own reminder of what they asked for.
//
// A rule: { field, op, value }
//   field  a profile field key ('lifestyle.smoking') or 'basics.age'
//   op     eq | ne | in | notIn | gte | lte | includes | sameAsMe
//   value  what to compare against (omitted for sameAsMe)
//
// A must-have on a field the candidate has left unknown passes: an empty
// "smoking" cell is common, and failing it would quietly empty the pool. The
// host is told so it can say it to the user.
//
// Custom questions (lib/questions.js) are the exception. A rule on
// 'q.<key>' is always a must-have that the other person is open to it: yes
// passes, maybe passes with fewer points (lib/score.js), no fails, and
// unknown holds the pair back until they answer (pendingKeys).

const { FIELDS, checkValue } = require('./schema');
const store = require('./store');

const OPS = ['eq', 'ne', 'in', 'notIn', 'gte', 'lte', 'includes', 'sameAsMe'];
const MAX_RULES = 12;
const BRIEF_MAX = 400;

const BASIC_RULE_FIELDS = { 'basics.age': { kind: 'int', min: 18, max: 99 } };

function specFor(field) {
  return FIELDS[field] || BASIC_RULE_FIELDS[field];
}

const isQuestion = field => typeof field === 'string' && field.startsWith('q.');

function checkRule(rule, kind) {
  if (!rule || typeof rule !== 'object') return 'must be { field, op, value }';
  if (isQuestion(rule.field)) {
    if (!store.getQuestion(rule.field.slice(2))) return 'unknown question ' + rule.field + ' (add it with add_custom_question first)';
    if (kind !== 'must') return 'custom questions can only be must-haves';
    return null;
  }
  const spec = specFor(rule.field);
  if (!spec) return 'unknown field ' + rule.field;
  if (!OPS.includes(rule.op)) return 'op must be one of ' + OPS.join(', ');
  if (rule.op === 'sameAsMe') return null;
  if (rule.op === 'in' || rule.op === 'notIn') {
    if (!Array.isArray(rule.value) || !rule.value.length) return rule.op + ' needs a list';
    const bad = rule.value.find(v => !checkValue(spec.kind === 'set' ? { ...spec, kind: 'enum' } : spec, v).ok);
    return bad === undefined ? null : 'bad value ' + JSON.stringify(bad) + ' for ' + rule.field;
  }
  if (rule.op === 'includes') {
    if (spec.kind === 'tags') return typeof rule.value === 'string' && rule.value.trim() ? null : 'includes needs a word';
    if (spec.kind !== 'set') return 'includes only works on lists';
    return spec.options.includes(rule.value) ? null : 'bad value for ' + rule.field;
  }
  if ((rule.op === 'gte' || rule.op === 'lte') && !['scale', 'score', 'int'].includes(spec.kind)) {
    return rule.op + ' only works on numbers';
  }
  return checkValue(spec, rule.value).ok ? null : 'bad value for ' + rule.field;
}

function validatePreferences(input) {
  const issues = [];
  const prefs = { brief: '', must: [], nice: [] };
  const brief = String((input && input.brief) || '').replace(/\s+/g, ' ').trim();
  if (brief.length > BRIEF_MAX) issues.push('brief is over ' + BRIEF_MAX + ' characters');
  else prefs.brief = brief;
  for (const kind of ['must', 'nice']) {
    const list = (input && input[kind]) || [];
    if (!Array.isArray(list)) { issues.push(kind + ' must be a list'); continue; }
    list.forEach((rule, i) => {
      const why = checkRule(rule, kind);
      if (why) issues.push(kind + '[' + i + '] ' + why);
      else if (isQuestion(rule.field)) prefs[kind].push({ field: rule.field, op: 'in', value: ['yes', 'maybe'] });
      else prefs[kind].push({ field: rule.field, op: rule.op, ...(rule.op === 'sameAsMe' ? {} : { value: rule.value }) });
    });
  }
  if (prefs.must.length + prefs.nice.length > MAX_RULES) issues.push('at most ' + MAX_RULES + ' rules in all');
  return { prefs, issues };
}

function fieldValue(profile, field) {
  if (field === 'basics.age') return profile.basics.age;
  if (isQuestion(field)) return (profile.answers || {})[field.slice(2)];
  const cell = profile.traits[field];
  return cell ? cell.value : undefined;
}

/** true, false, or undefined when the candidate's field is unknown. */
function ruleHolds(rule, candidate, self) {
  const have = fieldValue(candidate, rule.field);
  if (have === undefined || have === null) return undefined;
  const norm = v => (typeof v === 'string' ? v.toLowerCase() : v);
  switch (rule.op) {
    case 'eq': return norm(have) === norm(rule.value);
    case 'ne': return norm(have) !== norm(rule.value);
    case 'in': return rule.value.map(norm).includes(norm(have));
    case 'notIn': return !rule.value.map(norm).includes(norm(have));
    case 'gte': return have >= rule.value;
    case 'lte': return have <= rule.value;
    case 'includes': {
      const list = Array.isArray(have) ? have.map(norm) : [];
      const want = norm(rule.value);
      return list.some(v => v === want || (typeof v === 'string' && v.includes(want)));
    }
    case 'sameAsMe': {
      const mine = fieldValue(self, rule.field);
      if (mine === undefined || mine === null) return undefined;
      return JSON.stringify(norm(mine)) === JSON.stringify(norm(have));
    }
  }
  return false;
}

/** Does the candidate pass every must-have of the person asking? */
function passesMusts(self, candidate) {
  const musts = (self.prefs && self.prefs.must) || [];
  return musts.every(rule => ruleHolds(rule, candidate, self) !== false);
}

/**
 * What self's must-haves are waiting on the candidate for: custom questions
 * they have not answered (the question key), and stated-only fields they left
 * empty ('f:' + the field), which only they can fill in.
 */
function pendingKeys(self, candidate) {
  const musts = (self.prefs && self.prefs.must) || [];
  const out = [];
  for (const r of musts) {
    if (ruleHolds(r, candidate, self) !== undefined) continue;
    if (isQuestion(r.field)) out.push(r.field.slice(2));
    else if (FIELDS[r.field] && FIELDS[r.field].statedOnly) out.push('f:' + r.field);
  }
  return out;
}

/** How many of self's custom must-haves the candidate answered maybe to. */
function maybeCount(self, candidate) {
  const musts = (self.prefs && self.prefs.must) || [];
  return musts.filter(r => isQuestion(r.field) && fieldValue(candidate, r.field) === 'maybe').length;
}

/** Share of nice-to-haves the candidate meets, 0..1; null when there are none. */
function niceShare(self, candidate) {
  const nice = (self.prefs && self.prefs.nice) || [];
  if (!nice.length) return null;
  return nice.filter(rule => ruleHolds(rule, candidate, self) === true).length / nice.length;
}

module.exports = { OPS, MAX_RULES, validatePreferences, ruleHolds, passesMusts, niceShare, pendingKeys, maybeCount, isQuestion };
