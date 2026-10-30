# Muse connector directory: submission pack

Answers for Meta's "Submit a connector" form (muse.ai/platform), and the steps
before and after. The form's exact fields weren't public when this was written;
copy what it asks for from below and adjust.

## Before submitting

1. Both services deployed: app.psycheai.io (this repo, `main`) and psycheai.io
   (psycheai, `claude/instagram-personality-compatibility-oqhpa3`).
2. `https://app.psycheai.io/health` answers `{"ok":true,…}`.
3. The pages load: psycheai.io/muse, /muse-privacy, /muse-terms, /muse-docs.
4. **Reviewer account on:** in Render (psycheai-app → Environment) set `PSYCHE_EMAIL_SIGNIN=1` for the review (connecting otherwise makes an account with no sign-in page, so the reviewer couldn't reach their seeded account), and
   - `PSYCHE_REVIEWER_EMAIL`: an address you give Meta, e.g. muse-review@psycheai.io
   - `PSYCHE_REVIEWER_CODE`: six digits you give Meta

   On restart the server seeds that account (lib/demo.js): a read, a confirmed
   Psyche Pair profile, a week of demo matches, one person who picked them, and
   a Sync. Demo people only ever match each other.
5. Before going live to everyone, decide on Psyche Pair: submit it, or submit
   "Know yourself" and Sync first (see "If dating is a concern" below).

## The form

**Name:** PsycheAI

**Short description (one line):** A deep, kind read of who you are, from your own Instagram, and a few strong matches a week.

**Long description:**
PsycheAI reads your own Instagram, with your permission, and writes your Psyche Card and full Psyche Report: your type, Big Five, the patterns that explain you, what drives you, and the character you're most like. It's free. Sync with a friend to see how you two get on. And if you choose, Psyche Pair introduces you to a few people a week who fit you well on needs, lifestyle, future plans, communication and values, with no swiping: you pick up to two, and a mutual yes opens a private chat or an Instagram swap. Sensitive things like religion are only ever asked, never guessed, and PsycheAI never stores your posts or messages.

**Category:** Lifestyle / Social (self-insight; dating as an opt-in mode)

**MCP endpoint:** https://app.psycheai.io/mcp (Streamable HTTP, JSON responses)

**Authentication:** OAuth 2.1 with PKCE (S256). Dynamic client registration (RFC 7591) at /oauth/register; client ID metadata documents (client_id as an https URL); discovery at /.well-known/oauth-protected-resource and /.well-known/oauth-authorization-server. If the form needs a client ID: `psycheai`, or any other (public, no secret; returns only to Meta's hosts). Sign-in is a 6-digit email code, Google or Apple.

**Docs:** https://psycheai.io/muse-docs

**Privacy policy:** https://psycheai.io/muse-privacy

**Terms:** https://psycheai.io/muse-terms

**Support:** admin@psycheai.io

**Icon:** https://app.psycheai.io/icon.png (512×512)

**Test account:** email `<PSYCHE_REVIEWER_EMAIL>`, code `<PSYCHE_REVIEWER_CODE>` (enter it on the sign-in page instead of an emailed code).

**Test steps:**
1. Add the connector and sign in with the test account.
2. Say "Open PsycheAI": the reviewer already has a read, so the menu appears: Ask about my Psyche Report, Sync with a friend, See this week's matches, and a fresh Psyche Card and Report with or without their messages (start). A new account sees what PsycheAI is and the go-ahead: Yes, include my messages / Posts and stories only.
3. "Fresh Psyche Card and Report, with my messages": the assistant reads the reviewer's Instagram (or any test account's), writes the read to get_report_guide's format, and publish_psyche returns the card image and a private psycheai.io link.
4. "Sync with a friend": get_syncs shows a ready Sync with Ravi; "Show my Sync" writes it.
5. "Find people who fit me": get_intros shows Jun picked the reviewer; get_weekly_matches shows this week's demo matches with a Pick button each.
6. "Delete my PsycheAI data" asks first, then removes everything.

**Data handling, in brief:** no posts, captions, stories or messages are received or stored; the read is sealed under a key only the user's link holds and deleted after 7 days; Psyche Pair and Sync keep a card-level profile, encrypted at rest, until the user deletes it; payments are on the website through Stripe, never inside Muse.

## If dating is a concern

Psyche Pair is a separate module. To submit self-insight and Sync alone, hide
the dating tools from tools/list and drop the pair steps from the instructions
(ask Claude: "submit without Psyche Pair"), then add it back once approved.

## After review

Remove `PSYCHE_REVIEWER_EMAIL` and `PSYCHE_REVIEWER_CODE`. The demo people stay
in the store but match only each other; delete them with delete_my_data on the
reviewer account if you want them gone.
