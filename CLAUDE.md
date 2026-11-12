# CLAUDE.md

psycheai-app (app.psycheai.io): PsycheAI's Muse connector and skill, Sync, and Psyche Pair, an MCP connector for Meta Muse (and later ChatGPT) that matches people on a structured profile the host fills from the user's own Instagram and a short chat. The user confirms the profile. Weekly drops show matches above a threshold, the user picks up to 2 a week, and a mutual yes shares Instagram handles.

## Commands

```bash
npm test       # tools/selftest.mjs: one script of check(label, ok, detail) calls, no filter
npm run dev    # dev server with POST /dev/signup and state in .data.json
npm start      # production: Upstash, Resend and OAuth from the environment (render.yaml)
```

## Rules that matter

- **README.md is the design log.** Update the relevant section with every behaviour change.
- **No raw content, ever.** The server stores only schema fields. Don't add a field that could carry post text, quotes, captions, other people's names, or DMs. `validateProfile` drops unknown keys, and the selftest checks this.
- **The schema is the single source.** `lib/instructions.js` and `draftJsonSchema()` are generated from `FIELDS` / `BASICS` in `lib/schema.js`. Add a field there, then add its comparison in `DIMENSION_RULES` (`lib/score.js`) if it should be scored.
- **Never infer sensitive traits.** Orientation, gender, age, ethnicity, religion, health, kids and marriage plans are asked, never inferred. This is pinned in the instructions and the selftest.
- **Attraction is behavioural only** (`lib/attraction.js`). Never add model-based judging of photos or looks.
- **Cards** (`lib/card.js`) never carry the bucket, must-haves, raw cells or email. The selftest scans a drop for leaks.
- **Chat text is sealed** (`lib/chat.js`). Never store or log it in the clear, and never open a thread except for the two people in it or a reported thread under review.
- **Custom questions are asked openly and never attributed.** Don't add anything that hides a question in small talk or tells either side who asked or what was answered.
- **Characters come from `lib/characters.js`,** with the side taken from the user's stated gender, never judged.
- **Secrets are stored hashed.** Tokens, sign-in codes and auth codes go through `store.hash`. Never store or log one in the clear.
- **Email is a nudge, not a channel.** Product events go through `notify.note`, never straight to `mail.send`. Only sign-in codes are sent immediately.
- **Stated-only fields stay stated-only.** Religion (required), ethnicity, height, politics and drugs come only from the user (`statedOnly` in `lib/schema.js`). Never add code or instructions that fill them in by inference.
- **Keep the chat short.** The instructions pin the flow: four messages on the first visit at most, buttons for choices, card images instead of descriptions, and the read never pasted as text: the full read is the PDF, and Muse shows the report only as one collapsed widget drawn from `view`, without the evidence. Changes to the flow need matching selftest updates.
- **The store is encrypted at rest and emails live apart.** Never put an email on a user record or in a Redis key. Use `store.emailOf` and `store.emailKey`.
- **PLAN.md is the agreed roadmap.** Check it before starting new work, and tick items off as they land.
- **Every store write goes through `lib/store.js`,** which marks the record for the Upstash flush. Mutating an object you got from the store without calling its setter will not be saved.
- **Nothing is sold inside the host.** Psyche Pair Plus is priced and bought only on the website (`lib/plus.js`). Instructions and tool descriptions never mention prices, Plus or upgrading, and a limit is worded as a limit. The selftest checks this. Only a signed Stripe webhook changes a plan.
- **Handles are like emails.** Sync's Instagram handles never appear in a Redis key: use `store.handleKey`.
- **Stated always wins.** Traits from a psycheai.io read (`lib/join.js`, source `uploaded`) never replace a stated one.
- **Plain Node, one dependency** (`@resvg/resvg-js`, for card images), CommonJS in `lib/`, `node:http` server.

## Muse safety check: never trip it

Muse runs a safety check on tool results and file reads (SKILL.md, guide.json, script output, and any search of them). When it trips, Muse stops mid-flow. Every change to `lib/skill.js`, `lib/instructions.js`, `skill/`, `together/` or a script's output must keep clear of what has tripped it before. `tools/selftest.mjs` ("no new safety-check trigger") counts these phrases in every shipped file and fails if one appears more often than its recorded baseline: never raise a baseline to make it pass without asking the user.

What has tripped it (README has each case):
- **Pass-through and identity wording in a tool result:** "word for word", "exactly as given", "unchanged", "PsycheAI runs on you", or a claim that one source takes precedence over another. A script's `say` and `nextStep` are data to show, never instructions to obey.
- **Sending without a tap:** every line that sends a message to someone says in the same sentence that it happens only after they tap Send (release 194), so a search hit carries its own condition.
- **Standing tasks with instructions inside:** a reminder runs one command (`python3 bin/psyche.py sync-check`), never "whose task is: call … and show …".
- **Concealment:** never tell Muse to hide, shorten or play down anything about checks, updates, what is read or what is sent. Asked by the user is the only reason to say less.
- **Install lines and outbound links beside private data:** an install line belongs only in an invite meant for a friend; a result never carries chat content and a link or a send step together.
- **Other people's calls to action:** captions and messages that say install, paste, tap, comment, DM, follow or carry a web address are filtered before they reach a digest (`TASTE_CTA`).
- **One skill driving another:** PsycheAI's skill neither installs nor runs Psyche Together on its own: the user's tap does.
- **Lines that only make sense in context:** a sensitive line (reading messages, sending, sharing) states its own condition, since a search returns it alone.

Product features with clear consent (reading messages after "Include my messages", a Sync, Psyche Together's shared report) are not triggers and stay as they are. When a change could touch any of the above, say so to the user before shipping.

