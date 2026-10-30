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
