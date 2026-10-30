// The matching profile: the only thing Psyche Pair stores about a person.
//
// The host assistant (Muse first, ChatGPT later) fills it from what it can see
// and what the user tells it, shows it to the user, and only a profile the
// user has confirmed is matched. No posts, captions, quotes or chat lines ever
// reach this server; the schema has nowhere to put them.
//
// Every scored field is a cell: { value, source, confidence }.
//   source      'observed' (Muse read it from Instagram), 'stated' (the user
//               said it), 'uploaded' (read from a file the user gave the host)
//   confidence  0..1, the host's own rating. Low-confidence cells count for
//               less in the score and never appear on a match card.
// A value the host cannot support is null, never a guess.

const { NAMES, allowedFor } = require('./characters');
const { VOCAB: TRAIT_WORDS } = require('./traits');

const SOURCES = ['observed', 'stated', 'uploaded'];

const GENDERS = ['woman', 'man', 'nonbinary'];
const MODES = ['dating', 'friends'];
const INTENTS = ['serious', 'open', 'casual', 'friends'];
const VALUES = ['honesty', 'kindness', 'ambition', 'family', 'adventure', 'faith', 'humour', 'loyalty',
  'growth', 'independence', 'stability', 'generosity', 'creativity', 'health'];
const LOVE_LANGUAGES = ['words', 'time', 'gifts', 'acts', 'touch'];
const TRAITS = ['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism'];
// Schwartz's ten basic values, in their order around his circle (as in
// PsycheAI): neighbours are compatible, opposites trade off.
const RELIGIONS = ['muslim', 'christian', 'catholic', 'buddhist', 'taoist', 'hindu', 'sikh', 'jewish',
  'free_thinker', 'atheist', 'agnostic', 'spiritual', 'other', 'prefer_not_to_say'];
const ETHNICITIES = ['chinese', 'malay', 'indian', 'eurasian', 'east_asian', 'southeast_asian', 'south_asian',
  'middle_eastern', 'white', 'black', 'latino', 'mixed', 'other'];
const MOTIVATORS = ['self-direction', 'stimulation', 'hedonism', 'achievement', 'power',
  'security', 'conformity', 'tradition', 'benevolence', 'universalism'];

// kind: 'scale' is 1..5, 'score' is 0..100, 'enum' one of options,
// 'set' up to max of options, 'tags' free short strings, 'text' one line,
// 'int' a whole number in [min, max].
// `stated: true` marks fields Instagram cannot show; the host should ask.
// `statedOnly: true` goes further: the value must come from the user
// (source 'stated'). A guess is refused, not stored. These are the sensitive
// ones (religion, ethnicity, politics, drugs) and height, which must never be
// read off photos. Inferring them would be collecting special-category data
// without consent (PDPA, GDPR) and is what gets a connector cut off.
// `required: true` must be present before a profile can go live.
// A must-have on a statedOnly field the other person left empty holds the
// pair back and asks them, openly, whether they want to add it
// (lib/questions.js); it is never filled in for them.
const FIELDS = {
  'personality.mbti': { kind: 'mbti', label: 'Personality type' },
  ...Object.fromEntries(TRAITS.map(t => ['personality.' + t, { kind: 'score', label: t }])),

  'needs.attachment': { kind: 'enum', options: ['secure', 'anxious', 'avoidant', 'fearful'], label: 'Attachment style' },
  'needs.loveGiving': { kind: 'set', options: LOVE_LANGUAGES, max: 2, label: 'How they show care' },
  'needs.loveReceiving': { kind: 'set', options: LOVE_LANGUAGES, max: 2, label: 'How they like to receive care' },
  'needs.closeness': { kind: 'scale', label: 'How much time together they want', low: 'lots of space', high: 'together most days' },
  'needs.reassurance': { kind: 'scale', label: 'How much reassurance they need', low: 'very little', high: 'a lot' },

  'lifestyle.social': { kind: 'scale', label: 'Social energy', low: 'homebody', high: 'always out' },
  'lifestyle.active': { kind: 'scale', label: 'Fitness and outdoors', low: 'rarely', high: 'most days' },
  'lifestyle.travel': { kind: 'scale', label: 'Travel', low: 'rarely', high: 'constantly' },
  'lifestyle.nightlife': { kind: 'scale', label: 'Nightlife', low: 'never', high: 'every weekend' },
  'lifestyle.pace': { kind: 'scale', label: 'Work pace', low: 'relaxed hours', high: 'long hours' },
  'lifestyle.drinking': { kind: 'enum', options: ['never', 'social', 'regular'], label: 'Drinking' },
  'lifestyle.smoking': { kind: 'enum', options: ['no', 'sometimes', 'yes'], label: 'Smoking' },
  'lifestyle.pets': { kind: 'enum', options: ['none', 'wants', 'has'], label: 'Pets' },
  'lifestyle.interests': { kind: 'tags', max: 20, label: 'Interests' },

  'future.kids': { kind: 'enum', options: ['wants', 'open', 'doesnt_want', 'has'], stated: true, label: 'Kids' },
  'future.kidsWhen': { kind: 'enum', options: ['within_2y', '2_5y', '5y_plus', 'na'], stated: true, label: 'Kids, when' },
  'future.marriage': { kind: 'enum', options: ['wants', 'open', 'doesnt_want'], stated: true, label: 'Marriage' },
  'future.settle': { kind: 'text', stated: true, label: 'Where they want to live' },
  'future.ambition': { kind: 'scale', label: 'Career ambition', low: 'work to live', high: 'career first' },
  'future.money': { kind: 'enum', options: ['saver', 'balanced', 'spender'], label: 'Money' },
  'future.religion': { kind: 'enum', options: RELIGIONS, stated: true, statedOnly: true, required: true, label: 'Religion' },
  'future.religionImportance': { kind: 'scale', stated: true, label: 'How much religion matters', low: 'not at all', high: 'central' },
  'future.familyInvolvement': { kind: 'scale', stated: true, label: 'How involved family should be', low: 'independent', high: 'very involved' },

  'communication.conflict': { kind: 'enum', options: ['talk_now', 'cool_off_then_talk', 'avoid', 'confront'], label: 'In a disagreement' },
  'communication.expressive': { kind: 'scale', label: 'How openly they share feelings', low: 'private', high: 'wears heart on sleeve' },
  'communication.repair': { kind: 'scale', label: 'How quickly they make up', low: 'slow', high: 'same day' },

  'values.top': { kind: 'set', options: VALUES, max: 5, label: 'Core values' },
  'partner.appreciates': { kind: 'set', options: TRAIT_WORDS, max: 5, label: 'Traits they are drawn to in other people' },
  'partner.turnOffs': { kind: 'set', options: TRAIT_WORDS, max: 5, label: 'Traits that put them off in other people' },
  'values.motivators': { kind: 'set', options: MOTIVATORS, max: 3, label: 'Top three motivations, strongest first (of the ten in their private read)' },

  'background.education': { kind: 'enum', options: ['secondary', 'diploma', 'bachelor', 'master', 'doctorate'], stated: true, label: 'Education' },
  'background.lifeStage': { kind: 'enum', options: ['studying', 'early_career', 'established', 'settling_down', 'parent', 'later_life'], label: 'Stage of life' },
  'background.upbringing': { kind: 'text', label: 'Where they grew up' },
  'background.familyCloseness': { kind: 'scale', label: 'How close they are to family', low: 'distant', high: 'very close' },

  // Optional, and only ever from the user. Not scored on their own: they
  // count only where someone makes them a must-have or a nice-to-have.
  'background.ethnicity': { kind: 'enum', options: ETHNICITIES, stated: true, statedOnly: true, label: 'Ethnicity (optional)' },
  'background.height': { kind: 'int', min: 120, max: 230, stated: true, statedOnly: true, label: 'Height in cm (optional)' },
  'future.politics': { kind: 'enum', options: ['progressive', 'moderate', 'conservative', 'not_political', 'other'], stated: true, statedOnly: true, label: 'Politics (optional)' },
  'lifestyle.drugs': { kind: 'enum', options: ['never', 'sometimes', 'often'], stated: true, statedOnly: true, label: 'Recreational drugs (optional)' },
  'lifestyle.diet': { kind: 'enum', options: ['no_restrictions', 'vegetarian', 'vegan', 'pescatarian', 'halal', 'kosher', 'other'], label: 'Diet' },
};

// Stated by the user, never inferred, never scored: who they are and who they
// are looking for. These decide who is even in the pool.
const BASICS = {
  firstName: { kind: 'text', max: 40 },
  age: { kind: 'int', min: 18, max: 99 },
  gender: { kind: 'enum', options: GENDERS },
  seeking: { kind: 'set', options: GENDERS, max: 3 },
  ageMin: { kind: 'int', min: 18, max: 99 },
  ageMax: { kind: 'int', min: 18, max: 99 },
  city: { kind: 'text', max: 60 },
  intent: { kind: 'enum', options: INTENTS },
  mode: { kind: 'enum', options: MODES },
  instagram: { kind: 'handle' },
  photos: { kind: 'urls', max: 3 },
};

// The Psyche character (lib/characters.js), shown as a badge on the card,
// and one line on why, shown once someone picks you.
const CHARACTER_WHY_MAX = 140;
// The three signature pattern names from their private read ("The quiet
// organiser"), shown once someone picks you. Names only: the lines and
// evidence stay in the read.
const PATTERN_NAME_MAX = 40;

// The shortened report: what a mutual match gets to read. Career is one line;
// the roast and the development plan are gone.
const SUMMARY = {
  headline: { max: 80 },
  short: { max: 600 },
  career: { max: 200 },
};

const clean = s => String(s).replace(/\s+/g, ' ').trim();

function checkValue(spec, value) {
  if (value === null || value === undefined) return { ok: true, value: null };
  switch (spec.kind) {
    case 'scale': {
      const n = Number(value);
      return Number.isInteger(n) && n >= 1 && n <= 5 ? { ok: true, value: n } : { ok: false, why: 'must be a whole number 1 to 5' };
    }
    case 'score': {
      const n = Number(value);
      return Number.isFinite(n) && n >= 0 && n <= 100 ? { ok: true, value: Math.round(n) } : { ok: false, why: 'must be 0 to 100' };
    }
    case 'int': {
      const n = Number(value);
      return Number.isInteger(n) && n >= spec.min && n <= spec.max ? { ok: true, value: n } : { ok: false, why: `must be ${spec.min} to ${spec.max}` };
    }
    case 'mbti': {
      const s = String(value).toUpperCase();
      return /^[EI][NS][TF][JP]$/.test(s) ? { ok: true, value: s } : { ok: false, why: 'must be four letters like ENFJ' };
    }
    case 'enum':
      return spec.options.includes(value) ? { ok: true, value } : { ok: false, why: 'must be one of ' + spec.options.join(', ') };
    case 'set': {
      if (!Array.isArray(value)) return { ok: false, why: 'must be a list' };
      const bad = value.filter(v => !spec.options.includes(v));
      if (bad.length) return { ok: false, why: 'unknown: ' + bad.join(', ') + ' (allowed: ' + spec.options.join(', ') + ')' };
      if (value.length > spec.max) return { ok: false, why: 'at most ' + spec.max };
      return { ok: true, value: [...new Set(value)] };
    }
    case 'tags': {
      if (!Array.isArray(value)) return { ok: false, why: 'must be a list' };
      const tags = [...new Set(value.map(v => clean(v).toLowerCase()).filter(Boolean))];
      if (tags.some(t => t.length > 30)) return { ok: false, why: 'each under 30 characters' };
      return tags.length <= spec.max ? { ok: true, value: tags } : { ok: false, why: 'at most ' + spec.max };
    }
    case 'text': {
      const s = clean(value);
      return s.length <= (spec.max || 80) ? { ok: true, value: s || null } : { ok: false, why: 'too long' };
    }
    case 'urls': {
      if (!Array.isArray(value)) return { ok: false, why: 'must be a list' };
      if (value.length > spec.max) return { ok: false, why: 'at most ' + spec.max };
      const bad = value.find(v => !/^https:\/\/\S+$/.test(String(v)));
      return bad === undefined ? { ok: true, value: value.map(String) } : { ok: false, why: 'photos must be https links' };
    }
    case 'bool':
      return typeof value === 'boolean' ? { ok: true, value } : { ok: false, why: 'must be true or false' };
    case 'handle': {
      const s = String(value).trim().replace(/^@/, '');
      return /^[A-Za-z0-9._]{1,30}$/.test(s) ? { ok: true, value: s } : { ok: false, why: 'not an Instagram handle' };
    }
  }
  return { ok: false, why: 'unknown field kind' };
}

/**
 * Check a draft from the host. Returns { profile, issues }: the cleaned
 * profile (bad cells dropped, never repaired by guessing) and a list of
 * problems the host should fix with the user. Unknown keys are dropped too —
 * that is what keeps raw content out.
 */
function validateProfile(draft) {
  const issues = [];
  const profile = { basics: {}, traits: {}, summary: {} };
  const basics = (draft && draft.basics) || {};
  for (const [key, spec] of Object.entries(BASICS)) {
    const r = checkValue(spec, basics[key]);
    if (!r.ok) issues.push('basics.' + key + ' ' + r.why);
    else if (r.value !== null) profile.basics[key] = r.value;
  }
  for (const key of ['firstName', 'age', 'gender', 'seeking', 'city', 'intent', 'mode']) {
    if (profile.basics[key] === undefined) issues.push('basics.' + key + ' is required (ask the user)');
  }
  const b = profile.basics;
  if (b.ageMin === undefined && b.age) b.ageMin = Math.max(18, b.age - 5);
  if (b.ageMax === undefined && b.age) b.ageMax = b.age + 5;
  if (b.ageMin > b.ageMax) issues.push('basics.ageMin is above ageMax');
  if (b.mode === 'friends') b.intent = 'friends';

  const ch = draft && draft.character;
  if (ch && ch.name) {
    const allowed = allowedFor(b.gender);
    if (!NAMES.includes(ch.name)) issues.push('character.name must be one of the 28 Psyche characters');
    else if (!allowed.includes(ch.name)) issues.push('character.name is not open to this user; choose from: ' + allowed.join(', '));
    else {
      const why = clean(ch.why || '');
      // A line that's too long loses the line, never the character: a card
      // without one falls back to their first name and loses its art.
      if (why.length > CHARACTER_WHY_MAX) issues.push('character.why is over ' + CHARACTER_WHY_MAX + ' characters');
      profile.character = { name: ch.name, why: why && why.length <= CHARACTER_WHY_MAX ? why : null };
    }
  }

  const patterns = draft && draft.patterns;
  if (patterns !== undefined) {
    if (!Array.isArray(patterns) || patterns.length > 3) issues.push('patterns must be a list of up to 3');
    else {
      const names = patterns.map(p => clean((p && p.name) || p || ''));
      if (names.some(n => !n || n.length > PATTERN_NAME_MAX)) issues.push('each pattern needs a name under ' + PATTERN_NAME_MAX + ' characters');
      else profile.patterns = names.map(name => ({ name }));
    }
  }

  const traits = (draft && draft.traits) || {};
  for (const [key, spec] of Object.entries(FIELDS)) {
    const cell = traits[key];
    if (cell === undefined || cell === null) continue;
    if (typeof cell !== 'object' || Array.isArray(cell)) { issues.push(key + ' must be { value, source, confidence }'); continue; }
    if (!SOURCES.includes(cell.source)) { issues.push(key + '.source must be one of ' + SOURCES.join(', ')); continue; }
    if (spec.statedOnly && cell.source !== 'stated' && cell.value !== null && cell.value !== undefined) {
      issues.push(key + ' must come from the user (source "stated"): ask, never guess (dropped)');
      continue;
    }
    const conf = Number(cell.confidence);
    if (!Number.isFinite(conf) || conf < 0 || conf > 1) { issues.push(key + '.confidence must be 0 to 1'); continue; }
    const r = checkValue(spec, cell.value);
    if (!r.ok) { issues.push(key + ' ' + r.why); continue; }
    if (r.value === null) continue;
    profile.traits[key] = { value: r.value, source: cell.source, confidence: Math.round(conf * 100) / 100 };
  }
  for (const key of Object.keys(traits)) if (!FIELDS[key]) issues.push(key + ' is not a profile field (dropped)');
  for (const [key, spec] of Object.entries(FIELDS)) {
    if (spec.required && !profile.traits[key]) issues.push(key + ' is required (ask the user)');
  }

  const summary = (draft && draft.summary) || {};
  for (const [key, spec] of Object.entries(SUMMARY)) {
    if (summary[key] === undefined) continue;
    const s = clean(summary[key]);
    if (s.length > spec.max) issues.push('summary.' + key + ' is over ' + spec.max + ' characters');
    else if (s) profile.summary[key] = s;
  }
  return { profile, issues };
}

/** The cell's value when it is confident enough to use, else undefined. */
function val(profile, key, minConfidence = 0) {
  const cell = profile && profile.traits && profile.traits[key];
  return cell && cell.confidence >= minConfidence ? cell.value : undefined;
}

/** How complete a profile is, 0..100. Optional stated-only fields never count against it. */
function completeness(profile) {
  const keys = Object.keys(FIELDS).filter(k => !FIELDS[k].statedOnly || FIELDS[k].required);
  const have = keys.filter(k => profile.traits[k]).length;
  return Math.round(100 * have / keys.length);
}

/** The JSON schema the host fills, built from the tables above so the two never drift. */
function draftJsonSchema() {
  const valueSchema = spec => {
    switch (spec.kind) {
      case 'scale': return { type: 'integer', minimum: 1, maximum: 5 };
      case 'score': return { type: 'integer', minimum: 0, maximum: 100 };
      case 'int': return { type: 'integer', minimum: spec.min, maximum: spec.max };
      case 'mbti': return { type: 'string', pattern: '^[EI][NS][TF][JP]$' };
      case 'enum': return { type: 'string', enum: spec.options };
      case 'set': return { type: 'array', items: { type: 'string', enum: spec.options }, maxItems: spec.max };
      case 'tags': return { type: 'array', items: { type: 'string' }, maxItems: spec.max };
      case 'bool': return { type: 'boolean' };
      case 'urls': return { type: 'array', items: { type: 'string', pattern: '^https://' }, maxItems: spec.max };
      default: return { type: 'string' };
    }
  };
  const cell = spec => ({
    type: 'object',
    properties: {
      value: { anyOf: [valueSchema(spec), { type: 'null' }] },
      source: { type: 'string', enum: SOURCES },
      confidence: { type: 'number', minimum: 0, maximum: 1 },
    },
    required: ['value', 'source', 'confidence'],
  });
  return {
    type: 'object',
    properties: {
      basics: { type: 'object', properties: Object.fromEntries(Object.entries(BASICS).map(([k, s]) => [k, valueSchema(s)])) },
      traits: { type: 'object', properties: Object.fromEntries(Object.entries(FIELDS).map(([k, s]) => [k, cell(s)])) },
      summary: { type: 'object', properties: Object.fromEntries(Object.entries(SUMMARY).map(([k, s]) => [k, { type: 'string', maxLength: s.max }])) },
      character: { type: 'object', properties: { name: { type: 'string', enum: NAMES }, why: { type: 'string', maxLength: CHARACTER_WHY_MAX } } },
      patterns: { type: 'array', maxItems: 3, items: { type: 'object', properties: { name: { type: 'string', maxLength: PATTERN_NAME_MAX } }, required: ['name'] } },
    },
    required: ['basics', 'traits'],
  };
}

module.exports = {
  SOURCES, GENDERS, MODES, INTENTS, VALUES, LOVE_LANGUAGES, TRAITS, MOTIVATORS, RELIGIONS, ETHNICITIES, FIELDS, BASICS, SUMMARY,
  validateProfile, checkValue, val, completeness, draftJsonSchema,
};
