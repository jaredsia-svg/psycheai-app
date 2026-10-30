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
- **Keep the chat short.** The instructions pin the flow: four messages on the first visit at most, buttons for choices, card images instead of descriptions, and the read as a PDF and never pasted. Changes to the flow need matching selftest updates.
- **The store is encrypted at rest and emails live apart.** Never put an email on a user record or in a Redis key. Use `store.emailOf` and `store.emailKey`.
- **PLAN.md is the agreed roadmap.** Check it before starting new work, and tick items off as they land.
- **Every store write goes through `lib/store.js`,** which marks the record for the Upstash flush. Mutating an object you got from the store without calling its setter will not be saved.
- **Nothing is sold inside the host.** Psyche Pair Plus is priced and bought only on the website (`lib/plus.js`). Instructions and tool descriptions never mention prices, Plus or upgrading, and a limit is worded as a limit. The selftest checks this. Only a signed Stripe webhook changes a plan.
- **Handles are like emails.** Sync's Instagram handles never appear in a Redis key: use `store.handleKey`.
- **Stated always wins.** Traits from a psycheai.io read (`lib/join.js`, source `uploaded`) never replace a stated one.
- **Plain Node, one dependency** (`@resvg/resvg-js`, for card images), CommonJS in `lib/`, `node:http` server.
