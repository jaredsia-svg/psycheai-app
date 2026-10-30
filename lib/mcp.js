// The connector: MCP over HTTP (JSON-RPC 2.0, JSON responses, no streaming).
// Muse and ChatGPT both speak it, so one handler serves both; the only
// difference is the procedure text each host is given (lib/instructions.js).
//
// Every call is made as one signed-in user (the bearer token). Tools never
// take another user's id except as a match the caller was shown.

const store = require('./store');
const weekly = require('./weekly');
const { validateProfile, completeness, draftJsonSchema } = require('./schema');
const pairform = require('./pairform');
const waitlist = require('./waitlist');

// The Psyche Pair details only the user can give, still unanswered on their draft.
const DETAILS = [['photos', (p, u) => require('./photos').countOf(u) >= require('./photos').COUNT], ['age', p => p.basics && p.basics.age], ['gender', p => p.basics && p.basics.gender], ['city', p => p.basics && p.basics.city], ['who they want to meet', p => p.basics && p.basics.seeking && p.basics.seeking.length],
  ['what they are after', p => p.basics && p.basics.intent], ['religion', p => p.traits && p.traits['future.religion']]];
const missingDetails = (profile, user) => DETAILS.filter(([, has]) => !has(profile, user)).map(([name]) => name);
const { validatePreferences, OPS } = require('./preferences');
const { instructionsFor } = require('./instructions');
const questions = require('./questions');
const chat = require('./chat');
const notify = require('./notify');
const reads = require('./reads');
const links = require('./links');
const psyche = require('./psyche');
const sync = require('./sync');
const plans = require('./plans');
const { nextFor } = require('./next');
const { pairGuideFor } = require('./instructions');

const PROTOCOL_VERSION = '2025-06-18';
// The icon and site a host shows beside the connector (MCP's Implementation
// icons and websiteUrl), served by server.js from assets/.
const SERVER_INFO = {
  name: 'psycheai', title: 'PsycheAI', version: '0.2.0', websiteUrl: 'https://psycheai.io/muse',
  icons: [
    { src: require('./config').BASE_URL + '/icon.png', mimeType: 'image/png', sizes: ['512x512'] },
    { src: require('./config').BASE_URL + '/icon-192.png', mimeType: 'image/png', sizes: ['192x192'] },
  ],
};

const ruleSchema = {
  type: 'object',
  properties: {
    field: { type: 'string', description: 'A profile field key, e.g. "lifestyle.smoking", or "basics.age".' },
    op: { type: 'string', enum: OPS },
    value: { description: 'What to compare with. Omit for sameAsMe.' },
  },
  required: ['field', 'op'],
};

// What the user sees first. Muse acts on tool results and its own notes more
// than on the server's instructions, so the menu comes back as data from a
// read-only tool it calls on connecting, with any news before it.
// What a new user sees first is what PsycheAI is and what they'll learn, with
// one thing to do: get their read. Sync, Psyche Pair and Ask PsycheAI all
// work from that read, so they're offered once there is one, not before.
// In psycheai.io's own words (its front page and reels, README "Words from the
// site"): a personal AI coach that already knows you, a full personality
// study with no questions asked, and the four things the front page names.
const INTRO = [
  'I\'m PsycheAI, your personal AI coach that already knows you.',
  'I am able to do a full personality study of you with no questions asked, just based on your Instagram data. You will get a Psyche card (shareable) and a report (private), which will offer insights into your MBTI, attachment style, career strengths and blind spots. It takes about 5 to 10 minutes, and only you can see it.',
  'Once completed, you can ask me for any advice or sync with a friend to see how you click.',
];
// A reel to watch while the card is written, as a link: Muse doesn't play a
// video file in the chat (it downloaded one and never showed it). An Instagram
// reel on @psycheai.io opens in Instagram, where they can follow.
// PSYCHE_REEL_URL swaps it for another without a deploy.
const reel = () => process.env.PSYCHE_REEL_URL || 'https://www.instagram.com/reel/DewpyUayqTN/';
const introLines = () => INTRO;

// Saying yes to the read is one tap, on the first screen: the go-ahead covers
// reading (with or without their message threads) and saving.
const GO_AHEAD = 'Ready? To write your Psyche, I\'ll read your posts, stories and highlights here in Muse, plus your message threads if you choose, with names removed and never quoted. Your posts and messages stay here, and PsycheAI never receives them. All it gets is your finished Psyche, saved as a private link only you can open.';

// WhatsApp as a data source (README "Go deeper"), de-identified in their own
// workspace first. Offered once there is a read. A Deep Psyche is shelved for
// now: the guide's deep plan stays on psycheai.io, with no button for it.
const DEEP_WAIT = 'On it. A Deep Psyche reads every year of your Instagram, one at a time: about 20 to 30 minutes. I\'ll show it here when it\'s ready.';
// The privacy words are psycheai.io's own (its privacy reel: "names and
// handles removed", "de-identified"), said only as far as they're true here.
const WHATSAPP_LABEL = 'Add WhatsApp or Facebook as data source';
// Facebook and Messenger come through Muse's own Facebook connection, read the
// way Instagram is, so there's no file to share (README "Facebook in Muse").
const SOURCE_CHOICES = ['Facebook and Messenger', 'Facebook posts only', 'WhatsApp chats'];
const FACEBOOK_WAIT = 'On it. Reading your Facebook and writing your fresh Psyche takes about 5 to 10 minutes. I\'ll show it here when it\'s ready.';
const WHATSAPP_HOW = 'Add up to three WhatsApp chats you\'re most yourself in, with a close friend, family or a partner. In WhatsApp, open the chat, tap the menu, then More, Export chat, Without media, and share the .zip here.\n\n' +
  'Your chats stay private: each one is de-identified here, in your own Muse workspace, before it\'s read. Your own messages are kept, with what they answer, names removed and never quoted: the people in the chat become Friend A, Friend B, and phone numbers, emails, links and handles are removed. PsycheAI never receives your chats, only the report written from them.';

// Said when they say yes, word for word, before the work starts.
const WAIT = 'On it. Reading your Instagram and writing your Psyche takes about 5 to 10 minutes. I\'ll show it here when it\'s ready. Here\'s what you\'ll get, in a minute, while you wait.';
// A "DMs included" go-ahead checks their messages are connected before that
// line, so a missing connection is the first thing they hear, not something
// found minutes into the read (README "Messages checked first").
const MESSAGES_FIRST = 'Before its line, check only that their Instagram messages are connected, reading nothing. If they aren\'t, say so instead, as the guide\'s step 0 says, with "I\'ve connected them" and "Continue without messages", and start on their answer.';
// How long each thing takes, for the menu.
const TIMES = 'A question takes seconds; a Sync or setting up Psyche Pair, a couple of minutes; a fresh Psyche, 5 to 10 minutes.';
const TIMES_CLOSED = 'A question takes seconds; a Sync, about a minute; a fresh Psyche, 5 to 10 minutes.';
const times = user => (waitlist.openFor(user) ? TIMES : TIMES_CLOSED);

// Ask PsycheAI's ideas, the same questions psycheai.io offers (docs/copy.js,
// TEXT.ask.suggestions): deep ones the report doesn't already answer. Four at a
// time, as buttons, a different four each time.
const ASK_IDEAS = [
  'Who am I when I\'m not being useful, impressive or needed?',
  'What do I keep trying to prove, and to whom?',
  'What am I most insecure about in my life?',
  'What would make my life worthwhile, even if nobody ever knew what I achieved?',
  'What would I regret most about my life when I\'m old?',
  'What do I already know needs attention in my life, but keep putting off because it means a hard choice?',
  'Which commitments deserve my loyalty, and which need rethinking?',
  'How can I show up better for my partner, my family and the people closest to me?',
  'Should I move abroad and start again? If you picked one country for me, which would it be, and why?',
  'How can I become a better leader, at work and with the people around me?',
  'I\'m thinking about a big change in my career. Is it right for me, given everything else in my life?',
];
// With a read, the first idea is about their own strongest pattern, by its
// name on their card: a question only their report could start.
const patternIdea = name => `Where does "${name}" come from in me, and how do I make it work for me?`;
function askIdeas(n = 4, random = Math.random, patterns = []) {
  const pool = ASK_IDEAS.slice();
  for (let i = pool.length - 1; i > 0; i--) { const j = Math.floor(random() * (i + 1)); [pool[i], pool[j]] = [pool[j], pool[i]]; }
  const own = patterns && patterns[0] ? [patternIdea(String(patterns[0]).slice(0, 40))] : [];
  return [...own, ...pool].slice(0, n);
}

const LEARN = 'A full personality study, from what your own posts and messages show. Your Psyche Card: the character you\'re most like and your type in one picture. Your full report: your Big Five and type with the reasons, the patterns that explain you, what drives you, your wellbeing, how you attach and what you need in a partner, and how you work best.';
// Said as far as it's true (README "What leaves Muse"): the posts, messages,
// chats and digest stay in the workspace; the finished Psyche goes to PsycheAI
// to make the PDF and link, sealed under a key only the link holds; its
// card summary is kept 7 days for the card picture and Syncs.
const PRIVATE = 'Your posts, stories and messages are read here in Muse and stay here: PsycheAI never receives them, and what others wrote in your threads is read only for context, with names removed and never quoted. Only your finished Psyche goes to PsycheAI, to make your PDF and your private link, and it\'s stored locked with a key only your link holds. PsycheAI deletes that locked copy after 7 days; once you\'ve opened your link, your Psyche stays in your browser. To draw your card and run your Syncs, PsycheAI keeps a short summary of it (your character, type and patterns), never your posts or messages.';

const listNames = xs => (xs.length < 3 ? xs.join(' and ') : xs.slice(0, 2).join(', ') + ` and ${xs.length - 2} more`);

function startMenu(user, now = Date.now()) {
  const news = [];
  const syncs = sync.list(user, now);
  const intro = weekly.intros(user.id, now);
  const card = psyche.card(user.id, now);
  const hasRead = Boolean(card || psyche.has(user.id, now) || user.profile);
  const inPair = Boolean(user.reviewedAt);
  const show = 'Show news first, one line each, then say as written, keeping its line breaks, then the options as buttons, labels exactly as given. Don\'t list or describe the buttons in the text. No technical words.';
  if (!hasRead) {
    for (const ask of syncs.incoming) news.push(`${ask.name} wants to see how you two sync. Your Psyche come first, then your Sync.`);
    return {
      say: [...introLines(user), GO_AHEAD].join('\n\n'),
      news,
      options: [
        { id: 'read', label: 'Generate my Psyche. DMs included (Recommended)', messages: true, first: MESSAGES_FIRST, say: WAIT },
        { id: 'read', label: 'Generate my Psyche. DMs excluded', messages: false, say: WAIT },
        { id: 'learn', label: 'What will I learn?', answer: LEARN },
        { id: 'private', label: 'Is it private?', answer: PRIVATE },
      ],
      after: 'On either Generate my Psyche button, do its first step if it has one, then say its line, then the reel link on its own line. On "What will I learn?" or "Is it private?", say its answer, then offer the two Generate my Psyche buttons again.',
      reel: reel(),
      show,
    };
  }
  for (const ask of syncs.incoming) news.push(`${ask.name} wants to see how you two sync.`);
  const freshSyncs = syncs.syncs.filter(x => x.new).map(x => x.name);
  if (freshSyncs.length) news.push(`${listNames(freshSyncs)} synced with you: ${freshSyncs.length === 1 ? 'your Sync is' : 'your Syncs are'} ready.`);
  // Just connected again (a new sign-in since start last ran): the same
  // introduction someone new gets, then their own menu.
  const reconnected = Boolean(user.connectedAt && !(user.introAt >= user.connectedAt));
  if (reconnected && user.id && store.getUser(user.id)) store.updateUser(user.id, { introAt: now });
  if (intro.waiting.length) news.push(intro.waiting.length === 1 ? 'Someone picked you this week.' : `${intro.waiting.length} people picked you this week.`);
  if (weekly.hasNewDrop(user.id, now)) news.push('Your matches for this week are ready.');
  const opened = user.id && waitlist.openedNews(user.id);
  if (opened) news.push(opened);
  if (psyche.closingUnopened(user.id, now)) news.unshift('Your Psyche link closes within a day: open it from the chat where it was made, and they stay in your browser.');
  return {
    say: [...(reconnected ? introLines(user) : []), 'Welcome back. What would you like to do? ' + times(user)].join('\n\n'),
    news,
    card: card ? { character: card.character, headline: card.headline, type: card.mbti } : undefined,
    options: [
      { id: 'ask', label: 'Ask PsycheAI questions about myself', askIdeas: askIdeas(4, Math.random, card && card.patterns) },
      { id: 'sync', label: 'Sync with a friend' },
      syncs.count ? { id: 'syncs', label: syncs.newCount ? `My Syncs (${syncs.newCount} new)` : 'My Syncs' } : null,
      inPair && waitlist.openFor(user) ? { id: 'matches', label: 'See this week\'s matches' }
        : waitlist.openFor(user) || !waitlist.onList(user.id) ? { id: 'pair', label: waitlist.label(user) } : null,
      { id: 'sources', label: WHATSAPP_LABEL, answer: 'Which would you like to add?', buttons: SOURCE_CHOICES,
        facebook: { say: FACEBOOK_WAIT }, whatsapp: { answer: WHATSAPP_HOW, buttons: ['I\'ve shared my chats', 'Not now'] } },
      { id: 'read', label: 'Fresh Psyche. DMs included (Recommended)', messages: true, first: MESSAGES_FIRST, say: WAIT },
      { id: 'read', label: 'Fresh Psyche. DMs excluded', messages: false, say: WAIT },
    ].filter(Boolean),
    after: 'On "' + WHATSAPP_LABEL + '", say its answer with its buttons, then go on as the guide\'s FACEBOOK or WHATSAPP section says. On a Fresh Psyche button, do its first step if it has one, then say its line.',
    show,
  };
}

const TOOLS = [
  {
    name: 'start',
    description: 'Call this first: right after the user connects PsycheAI, in the same turn and before you reply (never reply only that it is connected), and whenever they open PsycheAI without saying what they want. Returns what to show them: for someone new, what PsycheAI is and their first step; for someone with a read, any news and a short menu. Read-only.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => startMenu(user),
  },
  {
    name: 'get_report_guide',
    description: 'The format of the PsycheAI read the user asked for: a short specification (spec) with a reading plan, and the JSON schema the finished read must match, for publish_psyche.',
    inputSchema: { type: 'object', properties: { depth: { type: 'string', enum: ['deep'], description: '"deep" when the user chose a Deep Psyche.' } } },
    // Only the guide itself: a line here about what the user agreed to, or
    // telling the host to act without asking, read as prompt injection and
    // failed Muse's safety check. The go-ahead lives in the instructions.
    run: (user, args) => psyche.guide(Date.now(), args && args.depth === 'deep' ? 'deep' : null),
  },
  {
    name: 'publish_psyche',
    description: 'Save the read the user asked for (one JSON object following get_report_guide\'s schema) to psycheai.io, as a private link only they can open. Returns that link and their card image. If it returns problems, fix them and call again.',
    inputSchema: {
      type: 'object',
      properties: {
        answer: { type: 'object', description: 'The read, as the guide\'s schema asks.' },
        name: { type: 'string', description: 'Their full name from their Meta account details.' },
      },
      required: ['answer', 'name'],
    },
    run: async (user, args) => { const out = await psyche.publish(user, args.answer, args.name); return out.ok ? { ...out, pairOpen: waitlist.openFor(user), askIdeas: askIdeas(4, Math.random, ((args.answer && args.answer.patterns) || []).map(p => p && p.name).filter(Boolean)) } : out; },
  },
  {
    name: 'sync_link',
    description: 'The user\'s own Psyche link, to send to a friend (show the full link in the message, never as a page or document): when the friend says "Sync with <link>" in their own Muse, the two are synced at once. Call it as soon as they want to sync with a friend: they never need to give or paste a link.',
    inputSchema: {
      type: 'object',
      properties: {},
    },
    // The first time, the daily Sync check is offered (README "A daily Sync check").
    run: (user, args) => {
      const out = sync.makeLink(user, args);
      if (out.error || user.syncCheckOffered) return out;
      store.updateUser(user.id, { syncCheckOffered: Date.now() });
      return { ...out, offerDailyCheck: true };
    },
  },
  {
    name: 'sync_with',
    description: 'Sync with someone by the Sync link they sent the user (link), which syncs the two at once. Only for a link someone sent them: to start a Sync of their own, or with someone they name, use sync_link and send its invite.',
    inputSchema: {
      type: 'object',
      properties: {
        link: { type: 'string', description: 'A PsycheAI Sync link someone sent the user (app.psycheai.io/sync/…).' },
      },
    },
    run: (user, args) => sync.syncWith(user, args),
  },
  {
    name: 'get_syncs',
    description: 'Who wants to sync with the user (incoming), whom they asked (sent), and all their Syncs, newest first, each marked new until opened and with its summary once written. With check true (the daily Sync check), only what\'s new since the last check.',
    inputSchema: { type: 'object', properties: { check: { type: 'boolean', description: 'true from the daily Sync check: only what is new since the last check, or quiet.' } } },
    run: (user, args) => (args && args.check ? sync.check(user) : sync.list(user)),
  },
  {
    name: 'get_sync',
    description: 'The user\'s Sync with someone. If it is already written, its image (written: true). If not, PsycheAI\'s Sync guide, the two card-level profiles, the derived facts and the schema: write it as one JSON object and call save_sync.',
    inputSchema: { type: 'object', properties: { sync: { type: 'string', description: 'The sync id from get_syncs or sync_with.' }, handle: { type: 'string', description: 'Their Instagram handle, if the Sync was made by handle.' }, rewrite: { type: 'boolean', description: 'true to write it afresh when they ask for a new one.' } } },
    run: (user, args) => sync.get(user, args),
  },
  {
    name: 'save_sync',
    description: 'Save the Sync written from get_sync (one JSON object matching its schema), for both people, in the same format as a Sync on psycheai.io. Returns the Sync image, which holds all of it. If it returns problems, fix them and call again.',
    inputSchema: {
      type: 'object',
      properties: {
        sync: { type: 'string', description: 'The sync id from get_syncs or sync_with.' },
        handle: { type: 'string', description: 'Their Instagram handle, if the Sync was made by handle.' },
        answer: { type: 'object', description: 'The Sync, as get_sync\'s schema asks.' },
      },
      required: ['answer'],
    },
    run: (user, args) => sync.save(user, args),
  },
  {
    name: 'remove_sync',
    description: 'Say no to someone\'s Sync ask, take back the user\'s own, or end a Sync. The other side is not told.',
    inputSchema: { type: 'object', properties: { sync: { type: 'string', description: 'The sync id from get_syncs or sync_with.' }, handle: { type: 'string', description: 'Their Instagram handle, if the Sync was made by handle.' } } },
    run: (user, args) => sync.remove(user, args),
  },
  {
    name: 'join_pair_waitlist',
    description: 'Psyche Pair is not open yet: this puts the user on its waitlist, with their city, so they hear when it opens where they live. Call it when they tap "Join the Psyche Pair waitlist".',
    inputSchema: { type: 'object', properties: { city: { type: 'string', description: 'Their city, from their Meta account details; ask only if you can\'t see it.' } } },
    run: (user, args) => waitlist.join(user, args),
  },
  {
    name: 'get_pair_guide',
    description: 'How to run Psyche Pair for this user: the one message that sets it up, the matching fields, and what to do on every later visit. Call it when they say yes to Psyche Pair, and on later visits if you no longer have it.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => ({ guide: pairGuideFor(user.platform) }),
  },
  {
    name: 'get_instructions',
    description: 'The step-by-step procedure for building this user\'s Psyche Pair profile. Call it first, and follow it.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => ({ instructions: instructionsFor(user.platform) }),
  },
  {
    name: 'save_profile',
    description: 'Save a draft of the user\'s matching profile (structured fields only, never post text or quotes). Returns any issues to fix. The draft is not matched until confirm_profile.',
    inputSchema: draftJsonSchema(),
    run: (user, args) => {
      const { profile, issues } = validateProfile(args);
      // Traits from their psycheai.io read (lib/join.js) stay unless the host
      // sends that field itself.
      for (const [key, cell] of Object.entries((user.draft && user.draft.traits) || {})) {
        if (cell.source === 'uploaded' && !profile.traits[key]) profile.traits[key] = cell;
      }
      store.updateUser(user.id, { draft: profile });
      return { saved: true, issues, completeness: completeness(profile), next: issues.length ? 'Fix the issues, then save again.' : 'Show the user their profile in plain words; call confirm_profile only after they agree.' };
    },
  },
  {
    name: 'add_email',
    description: 'A link where the user adds an email to their PsycheAI account (a 6-digit code to confirm it): for a nudge, at most once a day, when someone picks them or writes to them, and to use their account on the website. Optional; the account works without one.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => (store.emailOf(user.id) ? { done: true, note: 'They already have an email on their account.' }
      : { url: require('./config').BASE_URL + '/account/email/' + links.sign({ u: user.id, k: 'attach' }, Date.now(), 2 * 3600000), show: 'Show the link once, as a link.' }),
  },
  {
    name: 'pair_form',
    description: 'A link to a short form where the user answers the Psyche Pair details themselves (photos, age, gender, city, who they want to meet, an age range, what they are after, religion, kids and marriage each as good to have or a must, and anything else they want in a partner), prefilled from their saved draft. Good for two hours. Call save_profile first.',
    inputSchema: {
      type: 'object',
      properties: {
        instagram_photos: { type: 'array', maxItems: 12, items: { type: 'string' }, description: 'Optional: the image addresses of the user\'s own latest Instagram posts, as you have them, newest first, up to 12. Pass them unsorted, without looking at or choosing among them: the user picks 3 in the form.' },
      },
    },
    run: (user, args = {}) => {
      if (!user.draft && !user.profile) return { error: 'Nothing saved yet. Call save_profile first.' };
      const offered = pairform.offerInstagram(user.id, args.instagram_photos);
      return { url: pairform.link(user.id), instagramPhotos: offered, show: 'Show the link once, as a link.' };
    },
  },
  {
    name: 'get_my_card',
    description: 'The user\'s own Psyche Pair card as an image to show in the chat, and its page: how matches will see them. Their details come first: until they have given them, it returns the details form link (needsDetails) instead of the card.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => {
      const profile = user.draft || user.profile;
      if (!profile) return { error: 'Nothing saved yet. Call save_profile first.' };
      const missing = missingDetails(profile, user);
      // Questions first, then the card (README): enforced here, not only in
      // the guide, because a host can act on an older copy of the guide.
      if (missing.length) return { needsDetails: true, missing, form: pairform.link(user.id), show: 'Show the form link once, as a link; no card yet.' };
      return {
        ...links.cardLinks(user.id, user.id, undefined, require('./photos').countOf(user)), completeness: completeness(profile),
        // Their own words from the form, to turn into rules, and the rules
        // already saved (the form saves kids and marriage), to keep.
        missing, lookingFor: (user.prefs && user.prefs.brief) || null,
        rules: { must: (user.prefs && user.prefs.must) || [], nice: (user.prefs && user.prefs.nice) || [] },
      };
    },
  },
  {
    name: 'confirm_profile',
    description: 'The user has read their profile and said it is right. Makes the saved draft their live profile so it can be matched. Only call after their clear yes.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => {
      if (!user.draft) return { error: 'Nothing saved yet. Call save_profile first.' };
      // Mode follows what they're after (dating, unless new friends): never a question for them.
      if (!user.draft.basics.mode) {
        store.updateUser(user.id, { draft: { ...user.draft, basics: { ...user.draft.basics, mode: user.draft.basics.intent === 'friends' ? 'friends' : 'dating' } } });
        user = store.getUser(user.id);
      }
      const { issues } = validateProfile(user.draft);
      const blocking = issues.filter(i => i.includes('required') || i.includes('ageMin'));
      if (require('./photos').countOf(user) < require('./photos').COUNT) blocking.push('3 photos (they add them in the details form: pair_form)');
      if (blocking.length) return { error: 'Still missing: ' + blocking.join('; ') };
      store.updateUser(user.id, { profile: user.draft, reviewedAt: Date.now() });
      return { confirmed: true, poolSize: weekly.poolSize(store.getUser(user.id)) };
    },
  },
  {
    name: 'set_preferences',
    description: 'Save who the user wants to meet: their own words (brief) plus must-haves (filters) and nice-to-haves (extra points) as rules over profile fields. Read the rules back to the user before calling. Must-haves on a field the other person left empty pass. Returns the pool size the rules leave.',
    inputSchema: {
      type: 'object',
      properties: {
        brief: { type: 'string', description: 'The user\'s own description, under 400 characters.' },
        must: { type: 'array', items: ruleSchema },
        nice: { type: 'array', items: ruleSchema },
      },
    },
    run: (user, args) => {
      const { prefs, issues } = validatePreferences(args);
      const custom = prefs.must.filter(r => String(r.field).startsWith('q.')).length;
      const allowed = plans.limitsFor(user).customMustHaves;
      if (custom > allowed) issues.push(`at most ${allowed} custom must-have${allowed === 1 ? '' : 's'}; keep the one${allowed === 1 ? '' : 's'} that matter${allowed === 1 ? 's' : ''} most`);
      if (issues.length) return { saved: false, issues };
      store.updateUser(user.id, { prefs });
      return { saved: true, poolSize: weekly.poolSize(store.getUser(user.id)) };
    },
  },
  {
    name: 'add_custom_question',
    description: 'For a must-have the profile has no field for (e.g. "must be okay with pet reptiles"): add a yes/maybe/no question to the shared bank, or get the existing one it duplicates. Then use it in set_preferences as a must rule with field "q.<key>". Not for sex, money, race, religion, health, looks, kids, marriage, legal status or politics.',
    inputSchema: {
      type: 'object',
      properties: {
        key: { type: 'string', description: 'Short snake_case name, e.g. open_to_pet_reptiles.' },
        text: { type: 'string', description: 'The question exactly as it will be asked, e.g. "Would you be okay with a partner who keeps pet reptiles?"' },
      },
      required: ['text'],
    },
    run: (user, args) => questions.addQuestion(args),
  },
  {
    name: 'get_pending_questions',
    description: 'Quick questions that would sharpen this user\'s matches (at most 3 a week), each with fixed options. Call at the start of each visit. Show each as a question with its options as buttons, or as a short numbered list if buttons are not available. Ask openly as matching questions; never say or hint that a particular person asked.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => ({ questions: questions.pendingFor(user.id, weekly.weekKey()) }),
  },
  {
    name: 'answer_question',
    description: 'Save the user\'s answer to a pending question, using one of its options, or skip.',
    inputSchema: { type: 'object', properties: { key: { type: 'string' }, answer: { type: 'string', description: 'One of the options get_pending_questions gave for this question (yes, maybe, no, a listed value, or skip); a number for height.' } }, required: ['key', 'answer'] },
    run: (user, args) => questions.answer(user.id, String(args.key || ''), args.answer),
  },
  {
    name: 'get_weekly_matches',
    description: 'This week\'s matches: a few people who scored above the bar, best first, each with a photo, first name, fit % and one line on what they share. The user may pick up to 2 a week.',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => weekly.weeklyDrop(user.id),
  },
  {
    name: 'pick_match',
    description: 'The user picks someone from this week\'s matches. Sends that person an intro. Uses one of the user\'s 2 weekly picks.',
    inputSchema: { type: 'object', properties: { matchId: { type: 'string' } }, required: ['matchId'] },
    run: (user, args) => weekly.pick(user.id, String(args.matchId || '')),
  },
  {
    name: 'get_intros',
    description: 'People who picked this user and are waiting for an answer (with a fuller card), intros the user sent, and mutual matches with their Instagram swap state (handles appear once both have offered).',
    inputSchema: { type: 'object', properties: {} },
    run: (user) => weekly.intros(user.id),
  },
  {
    name: 'respond_to_intro',
    description: 'Answer an intro from someone who picked the user. Yes on both sides shares Instagram handles.',
    inputSchema: { type: 'object', properties: { introId: { type: 'string' }, accept: { type: 'boolean' } }, required: ['introId', 'accept'] },
    run: (user, args) => weekly.respond(user.id, String(args.introId || ''), args.accept === true),
  },
  {
    name: 'share_instagram',
    description: 'Offer (share: true) or withdraw (share: false) the user\'s Instagram to one mutual match. Handles show to both only once both have offered. Ask the user first, for each match.',
    inputSchema: { type: 'object', properties: { introId: { type: 'string' }, share: { type: 'boolean' } }, required: ['introId', 'share'] },
    run: (user, args) => weekly.shareInstagram(user.id, String(args.introId || ''), args.share === true),
  },
  {
    name: 'make_psyche_pdf',
    description: 'Turn the user\'s full private Psyche read into a private link to a page they can read and save as a PDF. This is how the read is delivered: never paste it into the chat. We keep it only encrypted, with a key that exists only in the link.',
    inputSchema: {
      type: 'object',
      properties: {
        title: { type: 'string', description: 'e.g. "Mei\'s Psyche"' },
        sections: { type: 'array', maxItems: 24, items: { type: 'object', properties: { heading: { type: 'string' }, body: { type: 'string', description: 'Paragraphs separated by blank lines; list items start with "- ".' } }, required: ['heading', 'body'] } },
      },
      required: ['sections'],
    },
    run: (user, args) => reads.create(args),
  },
  {
    name: 'send_message',
    description: 'Send a message in the private chat with a mutual match (no contact details shared). Under 1000 characters. Send exactly what the user wrote.',
    inputSchema: { type: 'object', properties: { introId: { type: 'string' }, text: { type: 'string' } }, required: ['introId', 'text'] },
    run: (user, args) => chat.send(String(args.introId || ''), user.id, args.text),
  },
  {
    name: 'get_messages',
    description: 'With introId: the private chat with that match, to show the user word for word. Without: which matches have unread messages.',
    inputSchema: { type: 'object', properties: { introId: { type: 'string' } } },
    run: (user, args) => (args.introId ? chat.read(String(args.introId), user.id) : { unread: chat.unread(user.id) }),
  },
  {
    name: 'end_chat',
    description: 'End the private chat with a match (for example once they have swapped numbers). Deletes the messages.',
    inputSchema: { type: 'object', properties: { introId: { type: 'string' } }, required: ['introId'] },
    run: (user, args) => chat.end(String(args.introId || ''), user.id),
  },
  {
    name: 'log_date',
    description: 'After a date with a mutual match: did they meet, and would they see them again (yes/maybe/no). Only these answers are saved; any reflection stays in this chat.',
    inputSchema: { type: 'object', properties: { introId: { type: 'string' }, met: { type: 'boolean' }, again: { type: 'string', enum: questions.ANSWERS } }, required: ['introId', 'met'] },
    run: (user, args) => weekly.logDate(user.id, String(args.introId || ''), args),
  },
  {
    name: 'block_or_report',
    description: 'Block someone so neither sees the other again, optionally reporting them with a reason. A report on a match you chat with keeps that chat for our safety team to review.',
    inputSchema: { type: 'object', properties: { userId: { type: 'string' }, reason: { type: 'string' } }, required: ['userId'] },
    run: (user, args) => {
      const other = String(args.userId || '');
      if (!store.getUser(other)) return { error: 'No such person.' };
      const intro = store.allIntros().find(i => (i.from === user.id && i.to === other) || (i.to === user.id && i.from === other));
      if (intro) { if (args.reason) chat.holdForReport(intro.id); else chat.dropUnlessHeld(intro.id); }
      store.updateUser(user.id, { blocked: [...new Set([...(user.blocked || []), other])] });
      if (args.reason) store.addReport({ from: user.id, about: other, introId: intro ? intro.id : null, reason: String(args.reason).slice(0, 500) });
      return { blocked: true, reported: Boolean(args.reason) };
    },
  },
  {
    name: 'pause_matching',
    description: 'Pause or resume being matched (paused people get no drops and appear in none).',
    inputSchema: { type: 'object', properties: { paused: { type: 'boolean' } }, required: ['paused'] },
    run: (user, args) => ({ paused: store.updateUser(user.id, { paused: args.paused === true }).paused }),
  },
  {
    name: 'delete_my_data',
    description: 'Permanently delete everything PsycheAI keeps about the user: their card, profile, preferences, matches, intros, chats and Syncs. Confirm with the user first.',
    inputSchema: { type: 'object', properties: { confirm: { type: 'boolean', const: true } }, required: ['confirm'] },
    run: async (user, args) => {
      if (args.confirm !== true) return { error: 'Pass confirm: true once the user has agreed.' };
      const billing = await require('./plus').cancelFor(user);
      if (billing.error) return billing;
      sync.forget(user.id);
      await require('./photos').forget(user.id);
      waitlist.forget(user.id);
      store.deleteUser(user.id);
      return { deleted: true };
    },
  },
];

// What a host shows the user and uses to decide what needs asking: a plain
// title, and MCP's hints. Reads are read-only; everyday actions change only
// the user's own things and are not destructive; only removing things is.
// [title, readOnly, destructive, idempotent, openWorld]
const LABELS = {
  start: ['Start PsycheAI', true, false, true, false],
  get_report_guide: ['Get the PsycheAI guide', true, false, true, true],
  publish_psyche: ['Publish your Psyche', false, false, false, true],
  sync_link: ['Get my Sync link', false, false, true, false],
  sync_with: ['Sync with a friend', false, false, true, false],
  get_syncs: ['See your Syncs', true, false, true, false],
  get_sync: ['Open a Sync', true, false, true, true],
  save_sync: ['Save a Sync', false, false, true, false],
  remove_sync: ['Remove a Sync', false, true, true, false],
  join_pair_waitlist: ['Join the Psyche Pair waitlist', false, false, true, false],
  get_pair_guide: ['Get the Psyche Pair guide', true, false, true, false],
  get_instructions: ['Get the steps', true, false, true, false],
  save_profile: ['Save your profile', false, false, true, false],
  add_email: ['Add an email', true, false, false, false],
  pair_form: ['Psyche Pair details form', true, false, false, false],
  get_my_card: ['See your card', true, false, true, false],
  confirm_profile: ['Confirm your profile', false, false, true, false],
  set_preferences: ['Save who you want to meet', false, false, true, false],
  add_custom_question: ['Add a must-have question', false, false, true, false],
  get_pending_questions: ['Quick questions', true, false, true, false],
  answer_question: ['Answer a question', false, false, true, false],
  get_weekly_matches: ['See this week\'s matches', true, false, true, false],
  pick_match: ['Pick a match', false, false, true, false],
  get_intros: ['See who picked you', true, false, true, false],
  respond_to_intro: ['Answer an intro', false, false, true, false],
  share_instagram: ['Swap Instagram', false, false, true, false],
  make_psyche_pdf: ['Make your PDF', false, false, false, false],
  send_message: ['Send a message', false, false, false, false],
  get_messages: ['Read messages', true, false, true, false],
  end_chat: ['End a chat', false, true, true, false],
  log_date: ['Log a date', false, false, true, false],
  block_or_report: ['Block or report', false, false, true, false],
  pause_matching: ['Pause matching', false, false, true, false],
  delete_my_data: ['Delete your data', false, true, true, false],
};
for (const t of TOOLS) {
  const [title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint] = LABELS[t.name];
  t.title = title;
  t.annotations = { title, readOnlyHint, destructiveHint, idempotentHint, openWorldHint };
}

// What Muse sees decides what it offers. Right after connecting it has made
// its own menu from the tool list ("Show me my Syncs", "Show me this week's
// matches") for someone with no Psyche Card yet, so the list says which tools
// wait for a card or for Psyche Pair, the leftovers of older flows are out of
// it, and a tool that needs a card answers with the way to get one.
const HIDDEN = new Set(['make_psyche_pdf', 'get_instructions']);
const SYNC_TOOLS = ['sync_link', 'get_syncs', 'get_sync', 'save_sync'];
const PAIR_TOOLS = ['get_pair_guide', 'save_profile', 'pair_form', 'get_my_card', 'confirm_profile', 'set_preferences', 'add_custom_question',
  'get_pending_questions', 'answer_question', 'get_weekly_matches', 'pick_match', 'get_intros', 'respond_to_intro', 'share_instagram',
  'send_message', 'get_messages', 'end_chat', 'log_date', 'pause_matching'];
// save_profile stays open: a profile from psycheai.io ("Use for Psyche Pair") or an
// older draft is a start of its own.
const NEEDS_CARD = new Set([...SYNC_TOOLS, ...PAIR_TOOLS].filter(n => n !== 'save_profile'));
for (const t of TOOLS) {
  if (SYNC_TOOLS.includes(t.name)) t.description = 'Only once the user has a Psyche Card. ' + t.description;
  else if (PAIR_TOOLS.includes(t.name)) t.description = 'Psyche Pair only, once the user has a Psyche Card and has chosen Psyche Pair. ' + t.description;
}
const hasCard = (user, now = Date.now()) => Boolean(user && (psyche.has(user.id, now) || user.profile || user.draft));
// A Pair tool while Pair is closed (a host can keep an older tool list).
function pairClosed(user) {
  const city = waitlist.cityOf(user);
  const where = city ? ' in ' + city : '';
  return { pairClosed: true, onList: waitlist.onList(user.id), say: waitlist.onList(user.id) ? `Psyche Pair isn't open${where} yet. You're on the waitlist, and you'll hear here when it opens.` : `Psyche Pair isn't open${where} yet. Join the waitlist to hear when it opens where you live.` };
}
function cardFirst() {
  const first = startMenu({ id: null }).options.filter(o => o.id === 'read');
  return { needsCard: true, say: 'Your Psyche come first: they take about 5 to 10 minutes, and Sync and Psyche Pair work from them.', options: first };
}

const BY_NAME = Object.fromEntries(TOOLS.map(t => [t.name, t]));

const reply = (id, result) => ({ jsonrpc: '2.0', id, result });
const fail = (id, code, message) => ({ jsonrpc: '2.0', id, error: { code, message } });

/** One JSON-RPC message in, one reply out (null for notifications). Resolves. */
async function handle(user, msg) {
  if (!msg || msg.jsonrpc !== '2.0' || typeof msg.method !== 'string') return fail(msg && msg.id !== undefined ? msg.id : null, -32600, 'Invalid request');
  const isNotification = msg.id === undefined;
  if (isNotification) return null;
  switch (msg.method) {
    case 'initialize':
      return reply(msg.id, {
        protocolVersion: PROTOCOL_VERSION,
        capabilities: { tools: {} },
        serverInfo: SERVER_INFO,
        instructions: instructionsFor(user.platform),
      });
    case 'ping':
      return reply(msg.id, {});
    case 'tools/list':
      // Open anywhere: the Pair tools are listed (a host keeps the list it saw), and each call is checked for the user's city.
      return reply(msg.id, { tools: TOOLS.filter(t => !HIDDEN.has(t.name) && (waitlist.isOpen() ? t.name !== 'join_pair_waitlist' : waitlist.anyOpen() || !PAIR_TOOLS.includes(t.name))).map(({ name, title, description, inputSchema, annotations }) => ({ name, title, description, inputSchema, annotations })) });
    case 'tools/call': {
      const tool = BY_NAME[msg.params && msg.params.name];
      if (!tool) return fail(msg.id, -32602, 'Unknown tool');
      let out;
      notify.seen(user.id);
      try {
        const me = store.getUser(user.id);
        out = PAIR_TOOLS.includes(tool.name) && !waitlist.openFor(me) ? pairClosed(me)
          : NEEDS_CARD.has(tool.name) && !hasCard(me) ? cardFirst() : await tool.run(me, (msg.params && msg.params.arguments) || {});
      } catch (err) {
        console.error('[mcp] %s failed', tool.name, err);
        out = { error: 'Something went wrong on our side.' };
      }
      // A concrete next step (a line and buttons) so the chat keeps moving (lib/next.js).
      const nextStep = out && typeof out === 'object' && !Array.isArray(out) ? nextFor(tool.name, out) : null;
      if (nextStep) out = { ...out, nextStep };
      const isError = Boolean(out && (out.error || out.ok === false));
      // A file for the chat (the report's PDF): a resource link beside the text.
      const files = (out && out.attach ? [].concat(out.attach) : []).filter(f => f && /^https:\/\//.test(f.uri || '')).map(f => ({ type: 'resource_link', ...f }));
      return reply(msg.id, { content: [{ type: 'text', text: JSON.stringify(out) }, ...files], structuredContent: out, isError });
    }
    default:
      return fail(msg.id, -32601, 'Method not found');
  }
}

module.exports = { TOOLS, PROTOCOL_VERSION, handle, startMenu, ASK_IDEAS, askIdeas, DEEP_WAIT, WHATSAPP_LABEL, WHATSAPP_HOW, SOURCE_CHOICES, FACEBOOK_WAIT };
