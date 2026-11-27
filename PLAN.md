# Plan: PsycheAI plugin with Psyche Pair

Agreed 28–29 October 2026. README.md stays the design log of what is built. This file is what comes next, in order. Tick items off as they land.

## The product

- **One Muse plugin, named PsycheAI, at `app.psycheai.io/mcp`.** Two modes:
  - **Know yourself** (default, free): Muse reads Instagram, writes the PsycheAI card and full report in PsycheAI's own format, and they open on psycheai.io.
  - **Psyche Pair** (opt-in, one tap after the read): the same read becomes the matching profile.
- **Combined but separable.** Dating is its own module (tools, data, instructions), so it can become a separate connector if Meta approves PsycheAI but not dating.
- **Self first.** The user answers no questions until they opt into dating.
- **Muse writes the report.** No Gemini on the Muse path. "Ask PsycheAI" becomes "Ask in Muse" for Muse reads.
- **The upload path stays** (Instagram export, WhatsApp, Google, Facebook), as today:
  - the first card and report per username are free, later ones US$5, and the merged path stays on
  - Gemini Ask stays for uploads and deepened reads
- **Muse users can add WhatsApp and Google later** on psycheai.io: a "deeper read" anchored to the Muse card. The first one counts as that username's free upload read.

## The flow

**Know yourself: three taps and a wait.** Add the plugin, sign in (one tap: Google or Apple, with an email code as the fallback), allow Instagram. Then one message: "Your Psyche is ready", with the card image, the report link, and "Want PsycheAI to introduce you to people who fit you? [Yes] [Not now]".

**Psyche Pair: one message.** On Yes, one message containing:
- the card plus the photos Muse picked: "Does this look right?"
- who to meet, intent, religion (required), kids and marriage, as buttons
- "Anything you're looking for? (optional)"

The dispute happens here, until the user says it looks right, then `confirm_profile`.

**Weekly: one message.** "3 matches · 2 picks left", then card images with Pick buttons. Pending questions, intros and messages sit above it, and only when there are any.

**Chat defaults to Muse and the Instagram swap.** The web chat page is the email fallback only.

## Cards

- **The match card is the Psyche Card, plus the photo, plus the fit ring.**
  - Same panels and design, with the artwork kept.
  - First name, age and city instead of the full name.
  - The fit ring sits where the confidence ring is.
  - A "you two both…" line and "a natural pair" stand in for "most in sync with".
- **The shareable Psyche Card never shows a photo.**
- **What's revealed by stage:**
  - picked: + where you click, why the character, what they want
  - mutual: + about, chat, Instagram swap
  - The other person's full report is never shown.
- **Only positive or neutral wording.** "Where you click" lists only areas that clear the bar. Differences are worded as balance (PsycheAI Sync tone). No low scores, and never "clash", "incompatible" or "problem".

## Matching changes

- **No weak areas:** every scored area must clear a minimum, not just the overall fit.
- **Appreciates and turn-offs:** two short lists per user, from a fixed vocabulary (calm, outgoing, homebody, adventurous, planner, spontaneous, ambitious, easygoing, expressive, reserved, …).
  - Muse infers them, or the user states them, and they're reviewed in the dating message.
  - A turn-off hit means never matched. An appreciation hit adds points, and the card says it positively ("the calm planner you appreciate").

## Muse Sync

- **Sync with a friend:** "Sync me with @handle". The friend accepts in their own Muse, or gets an Instagram invite.
- **Scoring:** friends-mode weights. Muse writes the Sync in PsycheAI's Sync tone.
- **Result:** a Sync card image in the Psyche Card design.
- **Storage:** card-level profiles are stored with consent at first Sync.
- **Later, maybe:** couples Sync.

## Money

- The read is free on the Muse path.
- **Psyche Pair Plus, US$4.99 a month or US$29 a year:**
  - 5 picks a week instead of 2
  - a drop of 8 instead of 5
  - up to 5 custom must-haves instead of 1
- **Free tier:** 2 picks a week, unlimited answers to people who pick you, chat, the Instagram swap.
- **Payment** goes through Stripe on psycheai.io, tied to the same email account. No prices or upgrade prompts inside Muse.

## Security

1. **Encrypted at rest.** Every Upstash value is sealed under `PSYCHE_STORE_KEY`. Done.
2. **Emails apart from profiles.** Lookup is by HMAC. Done.
3. **Later:** privacy-page wording: "If you join Psyche Pair or use Sync, we keep your card-level profile, encrypted, so we can match you. We never keep your posts, messages or report."
4. **Before launch:**
   - two-factor sign-in on Render, Upstash, GitHub, Resend and Stripe
   - delete profiles inactive for 12 months, after one reminder
   - a one-page breach plan (PDPA notification to the PDPC)

## Build order

1. **PsycheAI repo, on a branch, for review before deploy:**
   - an import endpoint for Muse reads (encrypted, key in the link)
   - a "from Muse" source, free
   - an "Ask in Muse" button
   - "Add more data" giving a deeper read anchored to the Muse card
2. **Plugin.** Done.
   - rename to PsycheAI, with the two modes and self first
   - one-tap Google/Apple sign-in
   - a tool that hands Muse PsycheAI's report rules and structure
   - publishing to psycheai.io
   - mapping the read to the matching profile
   - appreciates and turn-offs, no weak areas, positive-only cards
3. **Design.** Done.
   - PsycheAI's tokens, components and dark mode on every page
   - the match card redrawn from the Psyche Card
   - site pages moved to psycheai.io
4. **Muse Sync.** Done. No score, as on psycheai.io: PsycheAI's Sync is read, not rated.
5. **Psyche Pair Plus** with Stripe. Done.
6. **Upload users joining Psyche Pair,** and deeper reads updating the matching profile. Done (`lib/join.js`, and "Use for Psyche Pair" on psycheai.io).


## Psyche Together

Agreed 8 November 2026 (plan, fifth draft). Standalone skill in together/, off unless PSYCHE_TOGETHER=1. README "Psyche Together".

- [x] Server mailbox (lib/together.js): locked boxes by the code's hash, hidden tools, end and forget.
- [x] Its own skill, served from /together and signed apart (tools/sign-together.mjs).
- [x] The check-in: adults, stage, nine core questions, private safety question, deeper questions from the Psyche, big decisions by stage.
- [x] The couple view, the joint read and each person's For you, with their checks; the page; End.
- [ ] Phase 0: install fresh several times to see whether Muse's safety check passes it; counsellor review of the questions, safety wording and resources.
- [x] Phase 1: payment on the website (built 9 Nov 2026 as app.psycheai.io/together/buy, tied to the PsycheAI account rather than a code in the prompt: lib/togetherpay.js), credited only by a signed webhook, refunded if the partner never joins. Off until `PSYCHE_TOGETHER_PAID=1` and `STRIPE_PRICE_TOGETHER` are set. Not yet: a refund made in Stripe by hand doesn't take a credit back. 18 Nov 2026: US$5 for both in eleven currencies, a buy page that shows what you get, and a sample report at /together/sample (README "The Psyche Together page").
- [x] Offered from PsycheAI's menus ("Psyche Together with my partner"), and a partner's invite kept while they make their Psyche.
- [x] Phase 4: message signals (turning towards, repair, being there when it counts, who plans) and the three-view gaps.
- [ ] The offer in PsycheAI: only when relevant, said to be paid, with price and refund terms before the link; CLAUDE.md's "nothing sold inside the host" narrowed for it.
- [x] The four-week re-check (release 17): the same questions again every four weeks, what moved on top of the page.
- [x] Overall satisfaction and how satisfied each thinks the other is (release 17), for the couple only.
- [ ] The six-month redo.

## How well do you know me? (the quiz)

Agreed 27 November 2026. Not built yet. A PsycheAI user makes a quiz about themselves in Muse, sends the link to friends, and each friend answers on a web page with no sign-in. Making a quiz needs Muse; taking one doesn't.

**Decisions**
- Muse only for making a quiz. No web quiz for someone without Muse: the turnaround is "make your quiz in Muse".
- 5 to 10 questions, 4 options each. The owner picks every right answer; the read's pick is only a starting point.
- Right or wrong shows straight after each answer (✓ "You know me" / ✗ "Not quite"), and a wrong answer never shows the right one. The end screen keeps the ✓ and ✗.
- A friend sees the answers they missed only once they've made their own quiz.
- Deep, not trivia: hypotheticals, motivations, the report's findings, blind spots, regrets.

**Where questions come from**
- Posts, stories, interests and motivations: may be stated outright ("What did I post about most this year?").
- The report's findings (traits, patterns, the character, blind spots): may be stated as findings.
- Messages: nothing in them is quoted, paraphrased or described, no events and no conversations. A finding they helped shape is used only in words that would hold from posts alone.
- Other people: never, even from posts (no names, handles, or who is in a photo).
- Politics, religion, kids and marriage are allowed, but they're stated-only (CLAUDE.md), so the read never suggests or pre-fills an answer: they're a "Beliefs and future" group the owner adds on purpose, with the answer left blank for the owner to set. They never appear on the score card or the Story image.
- Age, gender, orientation, ethnicity, health, height and drugs stay out.
- Every question, including ones the owner writes, goes through the custom questions' keyword filter (`lib/questions.js`).

**A quiz of 10:** 2 warm-ups (posts, interests), 5 deep (findings, motivations, hypotheticals), 2 hard (blind spots, how they come across vs who they are) and the finale, "Which character am I?". The wrong options are plausible: drawn from the owner's own traits, so only a friend who knows them gets it.

**The owner, in Muse**
1. After the Psyche is published, What's next is, in order: "Make a quiz for my friends", "Sync with a friend", "Add WhatsApp or Facebook and generate a Fresh Psyche", "Psyche Together with my partner", "More". "Ask PsycheAI questions about myself" moves under More. When a friend's Sync link is waiting (release 223) or the Together read is ready (release 224), the quiz goes under More.
2. One widget with the questions: each has Keep / Swap / Edit / Remove, the options, and the answer to confirm; "Add a question" and "Beliefs and future" at the end.
3. "Your quiz is ready": the quiz card image and the quiz link with a one-line invite in a code box to copy, as the Sync invite is (`Take my quiz: how well do you know me? <quiz link>`), and "Save for my Story" (an image for Instagram's link sticker). PsycheAI sends nothing itself: the user copies the line and sends it wherever they like.
4. Results: a line on the next menu tap ("3 friends took your quiz: Ana got 9/10"), the digest when away, and, at 3 answers, "What friends get wrong about you" (counts only).

**The friend, on the quiz page**
1. The owner's Psyche Card and "How well do you know Jared?", and a first name to type.
2. One question at a time, ✓ or ✗ after each.
3. The score card: "8/10, you know Jared better than 70% of his friends", a "Best friend" badge for the top score, their rank (others' first names only for friends who ticked "Show my name"), and "Share my score".
4. "Your turn: make your quiz in Muse": one tap copies `Install https://psycheai.io/skill and make my quiz for Jared: <quiz link>`. Shown only after the score and only on that tap, never beside the friend's answers.

**The friend, back in Muse:** the pasted line installs PsycheAI and makes their Psyche, as a Sync link does. Then What's next is "Make my quiz for <name>" and "More", and their finished quiz shows the link and its invite line in a code box to copy, headed "For <name>", the same as any quiz: nothing is sent through Instagram messages. Making it unlocks the answers they missed on the owner's quiz.

**Privacy and storage**
- The quiz is locked on the owner's device, with its key after the # of the quiz link, so the server never receives the key.
- The server keeps only boxes it can't open: the quiz, and each friend's first name and answers, locked in the friend's browser with the quiz key, so only the owner's device opens them. It keeps a count and a score per answer, for "better than X%" and the news.
- The page is `noindex` and out of the sitemap.
- The browser holds the answers to mark them, so a determined friend can read them in the page: accepted, it's a game.
- The quiz ends when the owner ends it or deletes their data, and with it every answer.

**Muse safety check (flag before shipping)**
- The instruction that writes the questions states the messages limit in the same line: "from posts, stories, interests and the report's findings; nothing from messages is quoted or described".
- The "Beliefs and future" line says in the same sentence that the owner states the answer.
- The invite line and the Story image carry a link: they appear only in a code box or image for the user to copy or save, never sent by Muse, and never beside private data.
- Results come back as counts and scores, never a friend's answers as text beside a link.
- New wording in SKILL.md and results goes to Jared before release; no safety-check baseline is raised without asking.

**Build**
- [ ] `bin/psyche.py quiz`: writes the questions from the read under the rules above, the widget, locking, the link; `tap` handles its buttons.
- [ ] Menus: "Make a quiz for my friends" after the Psyche; "Make my quiz for <name>" after a quiz link; quiz news on the menu.
- [ ] Server (`lib/quiz.js`): create, get, answer and end, with locked boxes only; counts for "better than X%" and the news; the digest line.
- [ ] The quiz page `/quiz/<id>`: one question at a time, ✓/✗, score card, rank, "Show my name", the turnaround.
- [ ] Images (`lib/cardimage.js`): the quiz card, the score card and the Story image, with no beliefs-and-future content.
- [ ] "What friends get wrong about you", at 3 answers.
- [ ] Unlocking a friend's missed answers once their own quiz exists.
- [ ] Selftest: no stated-only answer pre-filled; nothing from messages; no other people's names; nothing readable on the server; the sensitive group off the images; safety-check phrase counts.
- [ ] README design-log entry; sign a new skill release.
