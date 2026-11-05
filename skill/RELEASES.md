# PsycheAI skill releases

Every release of the PsycheAI skill for Muse, newest first, with the SHA-256 of each of its three files.
An installed copy lives in `~/workspace/skills/psycheai/`. To check yours, ask Muse:

> Run sha256sum on SKILL.md, bin/psyche.py and guide.json in ~/workspace/skills/psycheai, and compare them with github.com/jaredsia-svg/psycheai-app/blob/main/skill/RELEASES.md

All three must match one row. `sha256sum` is part of the system, not PsycheAI's code, and this list is on
GitHub, not on app.psycheai.io, so the check holds even if PsycheAI's server were in someone else's hands.
The release number is in bin/psyche.py (`RELEASE = …`).

Releases are signed with Ed25519. The public key, built into bin/psyche.py as `SKILL_PUBLIC_KEY`, is:

`ff295f50202afe5313924d4ed60e397996164ad8db9aa8079d937c17d0bcbb8d`

| Release | Date | SKILL.md | bin/psyche.py | guide.json |
|---|---|---|---|---|
| 153 | 2026-11-05 | `a5e80f55cb0dcc0f63eddec2a5cba8059443076bdb818270a814f329aa18e97f` | `0020d47fde472b97e2426d88c9000e8faf69896b2c10a630edb05fe0ec191e71` | `211ed58351ca2be7f4eaa51bbb61be48f2fa08844696d6102222870d82af8edb` |
| 152 | 2026-11-05 | `23c9ec74fee8d3bfaa2d43f1ed7c7b8cb7e45a1fddcbb29fbae5d6dfef9103e8` | `1441771d627dd1bc81f8136b57382eb153f68fd7fba0f55a3ed477fb28b2e67d` | `211ed58351ca2be7f4eaa51bbb61be48f2fa08844696d6102222870d82af8edb` |
