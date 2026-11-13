// What to offer the user after each tool: one line to say and the buttons to
// show. Muse acts on what tools return more than on the server's
// instructions, so a result that ends with a concrete next step keeps the
// chat moving instead of ending on "What would you like to do next?".
// Plain words only; the host shows the buttons and acts on the one tapped.

const step = (say, buttons, extra) => ({ say, buttons, asButtons: true, ...(extra || {}) });

const waitlist = require('./waitlist');

const MENU = ['Ask PsycheAI questions about myself', 'Sync with a friend', 'Find potential romantic matches'];

const NEXT = {
  get_report_guide: () => null,
  publish_psyche: out => (out.ok ? step('What\'s next?',
  // Ask first, then Sync, then a source (README "Ask first, then sources"; no PDF: README "The report file, not a PDF"); the roast is in the report's appendix.
  ['Ask PsycheAI questions about myself', 'Sync with a friend', 'Psyche Together with my partner', 'Add WhatsApp or Facebook', 'More'], { sources: ['WhatsApp, Facebook and Messenger', 'WhatsApp chats', 'Facebook and Messenger', 'Facebook posts only'], more: { buttons: ['Weekly check-ins on my plan', (out.pairOpen === undefined ? waitlist.isOpen() : out.pairOpen) ? waitlist.OPEN_LABEL : waitlist.JOIN, 'My data and privacy'] } }) : null),
  // An email is how they hear when their city opens, unless they come back first.
  // No email asked for (README "No email, no handles"): they hear here, in Muse, when it opens.
  join_pair_waitlist: out => (out.joined ? step(`You're on the list${out.city ? ' for ' + out.city : ''}. I'll tell you here when Psyche Pair opens there.`, ['Ask PsycheAI questions about myself', 'Sync with a friend', 'Back to the menu'])
    : out.open ? step(out.say, ['Find potential romantic matches', 'Not now']) : null),

  // Release 197 (README "Sync, shared by them"): they send the invite themselves; nothing is sent from Muse.
  sync_link: out => (out.url ? step('Send it to a friend, then tap below once you have.', ['I\'ve shared it. Show our results', 'Back to the menu']) : null),
  sync_with: out => {
    // synced: the guide goes straight on to get_sync, with no tap in between.
    // invite: they named the person, which is their yes to sending it.
    if (out.status === 'sent') return step('Asked. You\'ll see your Sync as soon as they say yes.', ['Sync with someone else', 'Back to the menu']);
    return null;
  },
  // A Sync made from a link names the person, not a handle.
  get_syncs: out => {
    if (out.quiet !== undefined) return null;
    if (out.incoming && out.incoming.length) return step(`${out.incoming[0].name} wants to see how you two sync.`, ['Yes', 'No thanks']);
    if (out.syncs && out.syncs.length) {
      const n = out.syncs.length, fresh = out.newCount || 0;
      return step(`${n} ${n === 1 ? 'Sync' : 'Syncs'}${fresh ? `, ${fresh} new` : ''}. Which one?`, [...out.syncs.slice(0, 10).map(x => 'Show my Sync with ' + (x.label || x.name)), 'Sync with someone new', 'Back to the menu']);
    }
    return step('No Syncs yet. Sync with a friend?', ['Sync with a friend', 'Not now']);
  },
  get_sync: out => (out.written ? step(`Your Sync with ${out.name || 'them'}.`, ['Sync with someone else', 'Write it again', 'Back to the menu']) : null),
  save_sync: out => (out.saved ? step(`Your Sync with ${out.name || 'them'} is ready. They'll see the same Sync on their side.`, ['Sync with someone else', 'Back to the menu']) : null),

  // The card comes after their details (the pair guide), so saving says nothing.
  save_profile: () => null,
  pair_form: out => (out.url ? step('A few quick details for your matches, about a minute.', ['Done', 'Answer here instead']) : null),
  get_my_card: out => (out.needsDetails ? step('A few quick details for your matches first, about a minute.', ['Done', 'Answer here instead'])
    : step('This is how your matches will see you. Does this look right?', ['Looks right', 'Change something'])),
  confirm_profile: out => (out.confirmed ? step('You\'re in. Your first matches arrive this week. Anything else for now?', ['Sync with a friend', 'Add a must-have', 'Back to the menu']) : null),
  set_preferences: out => (out.saved ? step('Saved. Anything else you\'re looking for?', ['Add another', 'That\'s all']) : null),

  get_pending_questions: out => (out.questions && out.questions.length ? null : step('All caught up. What next?', ['See this week\'s matches', 'Sync with a friend', 'Back to the menu'])),
  get_weekly_matches: out => {
    const cards = out.cards || [];
    if (!cards.length) return step('No one cleared the bar this week. New people join every week.', ['Sync with a friend', 'Back to the menu']);
    if (out.picksLeft > 0) return step(`Who would you like to meet? ${out.picksLeft} pick${out.picksLeft === 1 ? '' : 's'} left this week.`, [...cards.filter(c => !c.picked).slice(0, 8).map(c => 'Pick ' + c.firstName), 'Not this week']);
    return step('You\'ve used this week\'s picks.', ['See who picked me', 'Back to the menu']);
  },
  pick_match: out => (out.ok ? step('Sent. If they pick you back, it\'s mutual.', ['See my other matches', 'Back to the menu']) : null),
  get_intros: out => {
    const w = (out.waiting || [])[0];
    if (w) return step(`${w.firstName || 'Someone'} picked you.`, ['Yes, I\'d like to meet', 'No thanks']);
    const m = (out.mutual || [])[0];
    if (m) return step(`It's mutual with ${m.firstName || 'your match'}.`, ['Chat privately', 'Swap Instagram']);
    return null;
  },
  respond_to_intro: out => (out.ok && out.status === 'mutual' ? step('It\'s mutual!', ['Chat privately', 'Swap Instagram']) : null),
  share_instagram: () => null,
  log_date: () => step('Thanks. Anything else?', ['See this week\'s matches', 'Back to the menu']),
};

/** The next step for a tool's result, or null. Never throws. */
function nextFor(name, out) {
  try {
    if (!out || out.error) return null;
    if (out.needsCard) return step(out.say, out.options.map(o => o.label));
    if (out.pairClosed) return step(out.say, out.onList ? ['Sync with a friend', 'Back to the menu'] : [waitlist.JOIN, 'Not now']);
    const make = NEXT[name];
    return make ? make(out) : null;
  } catch { return null; }
}

NEXT.save_card = NEXT.publish_psyche;
NEXT.psyche_saved = NEXT.publish_psyche;

module.exports = { MENU, nextFor };
