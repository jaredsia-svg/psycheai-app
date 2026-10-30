// What one person may see of another, by stage. The matching profile itself
// is never shown, not even to its owner as numbers; a match card reveals a
// little more at each step so there is something to come back for.
//
//   drop     in this week's drop: the Psyche Card's first look (PLAN.md):
//            photo, first name, age, city, headline, character and type,
//            their three pattern names, what drives them, a few interests,
//            the fit, and one "you two both…" line
//   picked   they picked you and are waiting on your answer: + where you
//            click (only the areas that clear CLICK_BAR, never a low score),
//            one difference worded as a balance, what about them you are
//            drawn to, and why they are their character
//   mutual   both said yes: + the short write-up, career line, and the
//            Instagram swap state ('none', 'you_offered', 'they_offered',
//            'both'); the handle itself only once both have offered it for
//            this match. The private chat is always open.
//
// Never on any card: the attraction bucket, must-haves, raw cell values,
// anything below CARD_MIN_CONFIDENCE, email, the other person's picks, a low
// area score, or any of NEVER_SAY. Everything a match reads is positive or
// neutral (PLAN.md): a pair with a weak area is not matched at all.

const { DIMENSIONS } = require('./score');
const { val } = require('./schema');
const characters = require('./characters');
const traits = require('./traits');

const CLICK_BAR = 70;

// The Psyche Card's own panels on a Pair card (the same design: README "One card").
const LOVE_LABELS = { words: 'Words of affirmation', time: 'Quality time', gifts: 'Gifts', acts: 'Acts of service', touch: 'Physical touch' };
const INTENT_LABELS = { serious: 'Something serious', open: 'Open to see', casual: 'Something casual', friends: 'New friends' };
const KIDS_LABELS = { wants: 'Wants kids', open: 'Open to kids', doesnt_want: "Doesn't want kids", has: 'Has kids' };
const MARRIAGE_LABELS = { wants: 'Wants to marry', open: 'Open to marriage', doesnt_want: "Doesn't want to marry" };
const RELIGION_LABEL = r => (!r || r === 'prefer_not_to_say' ? null : r === 'free_thinker' ? 'Free-thinker' : r.charAt(0).toUpperCase() + r.slice(1));
function cardPanels(profile) {
  const b = profile.basics || {};
  const stated = key => { const c = profile.traits && profile.traits[key]; return c && c.source === 'stated' ? c.value : null; };
  return {
    values: (val(profile, 'values.top', 0.5) || []).slice(0, 3),
    loveGiving: (val(profile, 'needs.loveGiving', 0.5) || []).map(k => LOVE_LABELS[k]).filter(Boolean).slice(0, 2),
    lookingFor: INTENT_LABELS[b.intent] || null,
    // What they stated themselves, never a guess: religion, kids, marriage.
    lookingForLines: [RELIGION_LABEL(stated('future.religion')), KIDS_LABELS[stated('future.kids')], MARRIAGE_LABELS[stated('future.marriage')]].filter(Boolean),
    // The Pair card's write-up: the short summary, third person, as matches read it.
    writeUp: (profile.summary && profile.summary.short) || null,
  };
}
// Never on a card, in any wording (PsycheAI Sync's tone rule).
const NEVER_SAY = /\b(clash\w*|incompatib\w*|problem\w*|tension\w*|conflict\w*|friction|struggl\w*|weak\w*|poor|bad)\b/i;

const cellOf = (p, key) => { const c = p && p.traits && p.traits[key]; return c && c.confidence >= 0.5 ? c.value : null; };

// One difference, said as the balance it can be. The first that applies wins;
// each needs both people's cells and a real gap.
const BALANCES = [
  ['lifestyle.social', (x, y) => Math.abs(x - y) >= 2, 'One of you recharges out with people, the other at home: you can each bring the other somewhere new.'],
  ['lifestyle.travel', (x, y) => Math.abs(x - y) >= 2, 'One of you is always planning the next trip, the other loves home base: adventures with somewhere to come back to.'],
  ['lifestyle.pace', (x, y) => Math.abs(x - y) >= 2, 'One of you runs at full speed, the other at an easier pace: a steadying balance.'],
  ['communication.expressive', (x, y) => Math.abs(x - y) >= 2, 'One of you says what you feel straight away, the other shows it in other ways: you\'ll learn each other\'s language.'],
  ['communication.conflict', (x, y) => x !== y && [x, y].includes('talk_now') && [x, y].includes('cool_off_then_talk'),
    'One of you likes to talk things through right away, the other after a breather: agree on a time and you\'re both heard.'],
  ['lifestyle.active', (x, y) => Math.abs(x - y) >= 2, 'One of you is always on the move, the other enjoys slower days: room to share both.'],
];

function balanceLine(a, b) {
  for (const [key, differs, line] of BALANCES) {
    const x = cellOf(a, key), y = cellOf(b, key);
    if (x !== null && y !== null && differs(x, y)) return line;
  }
  return null;
}

const STAGES = ['drop', 'picked', 'mutual'];
const DIMENSION_LABELS = {
  needs: 'Needs met', lifestyle: 'Lifestyle', future: 'Future plans', communication: 'Communication',
  values: 'Values', background: 'Background', personality: 'Personality',
};

function badge(profile) {
  const name = profile.character && profile.character.name;
  if (!name) return null;
  const type = val(profile, 'personality.mbti', 0.5);
  return type ? name + ' · ' + type : name;
}

/** other is the user being shown; viewer is the matchable profile looking. */
function matchCard(other, stage, fit, lines, viewer, { swap = 'none' } = {}) {
  if (!STAGES.includes(stage)) throw new Error('unknown stage ' + stage);
  const b = other.profile.basics;
  const s = other.profile.summary || {};
  const theirs = other.profile.character && other.profile.character.name;
  const mine = viewer && viewer.character && viewer.character.name;
  const card = {
    id: other.id,
    stage,
    firstName: b.firstName,
    age: b.age,
    city: b.city,
    // How many of their photos this stage shows (lib/photos.js; served through the card's own link).
    photoCount: require('./photos').countOf(other),
    headline: s.headline || null,
    character: badge(other.profile),
    characterName: theirs || null,
    viewerCharacter: mine || null,
    mbti: val(other.profile, 'personality.mbti', 0.5) || null,
    // The Psyche Card's own panels, from the first look (PLAN.md).
    patterns: (other.profile.patterns || []).map(p => p.name),
    motivators: val(other.profile, 'values.motivators', 0.5) || [],
    interests: (val(other.profile, 'lifestyle.interests', 0.5) || []).slice(0, 5),
    charactersClick: characters.click(mine, theirs) ? `${mine} and ${theirs} are a natural pair.` : null,
    ...cardPanels(other.profile),
    fit: fit.fit,
    line: lines.length ? 'You two ' + lines[0] + '.' : null,
  };
  if (stage === 'picked' || stage === 'mutual') {
    card.whereYouClick = DIMENSIONS
      .filter(d => typeof fit.breakdown[d] === 'number' && fit.breakdown[d] >= CLICK_BAR)
      .sort((x, y) => fit.breakdown[y] - fit.breakdown[x])
      .map(d => ({ area: DIMENSION_LABELS[d], fit: fit.breakdown[d] }));
    card.balance = viewer ? balanceLine(viewer, other.profile) : null;
    const drawn = viewer ? traits.appreciated(viewer, other.profile) : [];
    card.drawnTo = drawn.length ? `${b.firstName} is ${traits.phrase(drawn.slice(0, 3))}: the kind of person you're drawn to.` : null;
    card.alsoShared = lines.slice(1, 3).map(l => 'You ' + l + '.');
    card.characterWhy = (other.profile.character && other.profile.character.why) || null;
  }
  if (stage === 'mutual') {
    card.about = s.short || null;
    card.career = s.career || null;
    card.instagramSwap = swap;
    card.instagram = swap === 'both' && b.instagram ? '@' + b.instagram : null;
    card.chat = 'open';
  }
  return card;
}

/** Your own card: how matches will see you, for the review before matching starts. */
function selfCard(user) {
  const profile = user.draft || user.profile;
  if (!profile) return null;
  const b = profile.basics, s = profile.summary || {};
  return {
    id: user.id,
    stage: 'self',
    firstName: b.firstName,
    age: b.age,
    city: b.city,
    photoCount: require('./photos').countOf(user),
    headline: s.headline || null,
    character: badge(profile),
    characterName: (profile.character && profile.character.name) || null,
    mbti: val(profile, 'personality.mbti', 0.5) || null,
    characterWhy: (profile.character && profile.character.why) || null,
    patterns: (profile.patterns || []).map(p => p.name),
    motivators: val(profile, 'values.motivators', 0.5) || [],
    interests: (val(profile, 'lifestyle.interests') || []).slice(0, 5),
    ...cardPanels(profile),
    about: s.short || null,
    live: Boolean(user.reviewedAt),
  };
}

module.exports = { STAGES, CLICK_BAR, NEVER_SAY, BALANCES, matchCard, selfCard, badge, balanceLine };
