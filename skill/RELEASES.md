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
| 162 | 2026-11-06 | `ba993222af717a57ce53eb4ab55cb985d941308bba35ab3dcd9abd28432a1446` | `68b1e7e441a971e8444f5af742ef0d15ec3fdd4077a0df7e5db1c199e24f4eeb` | `2290ca723685f7d5a61b304df52fe298833a1ee770dc771649a06053873f0592` |
| 161 | 2026-11-05 | `e3936186aba88ca6c56f8d20dde76fd39d9c07ec2541bfe920920820aa0d761f` | `d24b659d3bca642f49a8f3b3fed7cdba59a15780b343adedc736979cf33c143f` | `2290ca723685f7d5a61b304df52fe298833a1ee770dc771649a06053873f0592` |
| 160 | 2026-11-05 | `dfd87a42b953fae136ec49ce302be38bbe1e9a0817270359ecf7a7f485e7947a` | `657c37104baaeb5793e0171f21baa4855283864af574f05eeba2650af4051662` | `2290ca723685f7d5a61b304df52fe298833a1ee770dc771649a06053873f0592` |
| 158 | 2026-11-05 | `12410adb27c074ad926fbb6f403ae844dfff71e45cd2db522cb9d10e7fb0778e` | `fb0d3ccb9c037de71c8a71466524b4c4e950247dff51a86a374d118d7cbc4f97` | `2290ca723685f7d5a61b304df52fe298833a1ee770dc771649a06053873f0592` |
| 156 | 2026-11-05 | `5ea37ffcab392757ee91a5b1d999bc49c0e0d074caaf47d62c2b0f60a487c8ed` | `f7e31e53813b926e1bb299b65372f403fe75924573e3135b3439bdb076705561` | `2290ca723685f7d5a61b304df52fe298833a1ee770dc771649a06053873f0592` |
| 155 | 2026-11-05 | `0cabb13b56a3e6af06a7a06897da4e29ea2d0cc792dd6c66539dd242d945cdf9` | `9ed72f62866710ce73bbc7fbc1f87054edb738d879a7a0e16f1efa27bd8c27c7` | `2290ca723685f7d5a61b304df52fe298833a1ee770dc771649a06053873f0592` |
| 154 | 2026-11-05 | `c257ad8be940ec04166bc323fee031c55943f700ecb26426859e8de994b3b970` | `45798ba924751f7fd2fde93015130fc519750b75a469adc8aff48710fa9aa44c` | `211ed58351ca2be7f4eaa51bbb61be48f2fa08844696d6102222870d82af8edb` |
| 153 | 2026-11-05 | `a5e80f55cb0dcc0f63eddec2a5cba8059443076bdb818270a814f329aa18e97f` | `0020d47fde472b97e2426d88c9000e8faf69896b2c10a630edb05fe0ec191e71` | `211ed58351ca2be7f4eaa51bbb61be48f2fa08844696d6102222870d82af8edb` |
| 152 | 2026-11-05 | `23c9ec74fee8d3bfaa2d43f1ed7c7b8cb7e45a1fddcbb29fbae5d6dfef9103e8` | `1441771d627dd1bc81f8136b57382eb153f68fd7fba0f55a3ed477fb28b2e67d` | `211ed58351ca2be7f4eaa51bbb61be48f2fa08844696d6102222870d82af8edb` |
