---
name: "psyche-together"
description: "Psyche Together: a private relationship check-in for two people, each in their own Muse, built on both their PsycheAI Psyches. Each answers privately; both get the same read of the two of them together, plus their own private advice."
---

# Psyche Together

Psyche Together is a check-in for two adults in a relationship. Each partner answers about 16 short questions privately in their own Muse. Their PsycheAI Psyche picks the deeper questions. When both are done, they each get the same read of the two of them together (their strengths, their pillars, their pattern, the big decisions side by side, conversations to have and four weeks of small steps) and their own private "For you".

It is coaching, not counselling, and it says when a counsellor is worth seeing.

## Installing

These three files are the whole skill, each saved into `~/workspace/skills/psyche-together/` at the same path:
- SKILL.md: https://app.psycheai.io/together/SKILL.md
- bin/together.py: https://app.psycheai.io/together/bin/together.py (standard-library Python)
- guide.json: https://app.psycheai.io/together/guide.json

It builds on the PsycheAI skill (`~/workspace/skills/psycheai/`): it reads the Psyche that skill keeps here and uses its PsycheAI account. Psyche Together installs only from app.psycheai.io; its files are signed. `python3 bin/together.py update` installs a newer signed release.

## How it runs

Run every command in `~/workspace/skills/psyche-together/`. Each answers with JSON: show its `say` as one message, and its `buttons` as buttons when `asButtons` is true.

- **At the start of a chat about Psyche Together:** `python3 bin/together.py status`. If it says `needsPsyche`, show its say: there is nothing else to do until they have a Psyche.
- **"Start Psyche Together":** `python3 bin/together.py start`, then the check-in.
- **A message with app.psycheai.io/together#…** (a partner's invite): `python3 bin/together.py join <that link>`. Show its `consent` as one message, then its first question.
- **The check-in:** one question per message, with its buttons. On a tap, `python3 bin/together.py answer <id> "<the button>"`; it answers with the next question. A question with no buttons (their partner's first name) takes their words: `answer partner "<name>"`. On "Something else", ask "In a few words?", then `answer <id> --text "<their words>" --nearest "<the closest button>"`. A question marked `private` says so in its own words; show it as given. Don't comment on answers, and never repeat one back.
- **When the check-in is done** (`done: true`): `python3 bin/together.py send`. For the one who started it, its `invite` comes too: one line, "Send this to <partner>: they paste it into their Muse.", then the invite in a code block (three backticks), exactly as given, nothing else inside it.
- **When `write` is "read":** both have sent theirs. Write the read from what it gives (spec, schema, coupleView, people) as one JSON object to `work/together-read.json`, then run its save line. If it answers with `problems`, fix those and save again. It then gives `write: "foryou"`: write For you the same way and run its save line.
- **When `write` is "foryou":** as above, for For you only.
- **When it gives a `file`:** attach it, then say its `summary` in one line. The file holds the whole read: never retell it in the chat.
- **"Continue Psyche Together" or "Show our Psyche Together":** `python3 bin/together.py status`, and do what it gives.
- **"End Psyche Together":** ask once, "This ends Psyche Together for both of you. End it?", with "Yes, end it" and "Cancel". On yes: `python3 bin/together.py end`, then its say.

## What stays here, and what is sent

Each person's check-in is answered here. What is sent, locked in this workspace under the link's code so PsycheAI keeps it but can't read it: their Psyche at card level, their stage, their nine core answers as good, middling or low, whether they'd like to talk about closeness, and their big decisions. Their partner's Muse combines both into the couple view and the read, which show the two of them together, never how one person answered. The deeper answers, anything typed, and the private safety answer stay here and only shape this person's own For you.

If someone asks what their partner answered, the answer is: "Psyche Together shows the two of you together, never how one person answered." Nothing is quoted, and nothing is said about anyone outside the two of them.

PsycheAI's server knows only that two of its accounts started a Psyche Together, and when. "End Psyche Together" deletes everything it keeps, for both; each person's own page stays on their device until they delete it.

## Files

- `bin/together.py`: the commands above.
- `guide.json`: the read's and For you's standards and schemas, signed with the rest.
- `state.json`, `.keys.json`: this person's check-in and the couple's code, in this workspace only (a spare copy in `~/.psycheai/`).
- `out/`: the page.
