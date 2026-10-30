// PsycheAI's look for every page this server serves (card pages, chat,
// sign-in, the email-link pages): its colour tokens, light and dark, and the
// few components those pages use, matching psycheai.io (docs/styles.css).
// Light tokens come from assets/psycheai.json; the dark ones are PsycheAI's
// dark theme.

const P = require('../assets/psycheai.json');

const LIGHT = { bg: P.tokens.bg, alt: '#ffffff', ink: P.tokens.ink, soft: P.tokens.inkSoft, line: P.tokens.line, accent: P.tokens.accent, accent2: P.tokens.accent2, accentSoft: P.tokens.accentSoft };
const DARK = { bg: '#16121b', alt: '#1f1926', ink: '#f1ebf5', soft: '#a99fb4', line: '#322a3c', accent: '#c79bec', accent2: '#e889ad', accentSoft: '#2a2033' };

const vars = t => `--bg:${t.bg};--alt:${t.alt};--ink:${t.ink};--soft:${t.soft};--line:${t.line};--accent:${t.accent};--accent-2:${t.accent2};--accent-soft:${t.accentSoft}`;

const CSS = `
:root{${vars(LIGHT)};color-scheme:light dark;--radius:20px;--font:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,"Helvetica Neue",Arial,sans-serif}
@media (prefers-color-scheme:dark){:root{${vars(DARK)}}}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:16px/1.5 var(--font);-webkit-font-smoothing:antialiased}
main{max-width:30rem;margin:0 auto;padding:16px 16px 48px}
a{color:var(--accent)}
h1{font-size:1.7rem;margin:0;line-height:1.2;letter-spacing:-.02em}
.brand{display:flex;align-items:center;gap:8px;font-weight:700;color:var(--ink);text-decoration:none;margin:4px 0 14px}
.brand svg{width:22px;height:22px}
.hero{background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;border-radius:26px;padding:22px 22px 24px;position:relative;overflow:hidden}
.hero .kicker{font-size:.72rem;letter-spacing:.18em;text-transform:uppercase;opacity:.85;margin:0 0 4px;font-weight:600}
.hero h1{color:#fff;font-size:2.1rem}
.hero p{margin:.5rem 0 0}
.box{background:var(--alt);border:1px solid var(--line);border-radius:var(--radius);padding:14px 16px;margin:14px 0}
.lab{display:flex;align-items:center;gap:8px;font-size:.72rem;letter-spacing:.18em;text-transform:uppercase;color:var(--soft);font-weight:600;margin:0 0 10px}
.lab i{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:50%;background:var(--accent-soft);font-style:normal}
.lab svg{width:15px;height:15px;stroke:var(--accent);fill:none;stroke-width:2;stroke-linecap:round;stroke-linejoin:round}
.muted{color:var(--soft)}
.pills span{display:inline-block;background:var(--accent-soft);color:var(--accent);border-radius:999px;padding:.25rem .75rem;margin:0 6px 6px 0;font-weight:600;font-size:.9rem}
.num{list-style:none;padding:0;margin:0}
.num li{display:flex;align-items:center;gap:10px;margin:6px 0;font-weight:600}
.num b{display:inline-grid;place-items:center;width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;font-size:.8rem}
.num.light b{background:var(--accent-soft);color:var(--accent)}
.bar{display:grid;grid-template-columns:8.5rem 1fr 2.6rem;align-items:center;gap:8px;margin:6px 0;font-size:.92rem}
.bar i{display:block;height:8px;border-radius:8px;background:var(--accent-soft)}.bar i b{display:block;height:100%;border-radius:8px;background:var(--accent)}
.ring{display:inline-grid;place-items:center;min-width:4.6rem;height:4.6rem;border-radius:50%;border:5px solid var(--accent);background:var(--alt);color:var(--ink);font-weight:700;font-size:1.15rem;line-height:1.05;text-align:center}
.ring small{display:block;font-size:.62rem;color:var(--soft);font-weight:600}
button,.btn{font:600 1rem var(--font);padding:.85rem 1rem;border-radius:999px;border:0;background:linear-gradient(135deg,var(--accent),var(--accent-2));color:#fff;width:100%;text-align:center;text-decoration:none;display:block;cursor:pointer}
.ghost{background:var(--alt);color:var(--ink);border:1.5px solid var(--line)}
input,textarea{width:100%;font:inherit;padding:.7rem .8rem;border-radius:12px;border:1.5px solid var(--line);background:var(--alt);color:var(--ink)}
.note{color:var(--soft);font-size:.9rem;text-align:center;margin-top:10px}
.error{color:#b3261e}
.foot{color:var(--soft);font-size:.8rem;text-align:center;margin-top:28px}`;

const BRAND_SVG = `<svg viewBox="0 0 ${P.brand.viewBox} ${P.brand.viewBox}" fill="none" stroke="currentColor" stroke-width="${P.brand.strokeWidth * 1.6}" aria-hidden="true" style="color:var(--accent)">` +
  P.brand.paths.map(d => `<path d="${d}"/>`).join('') + `</svg>`;

/** A line icon from the Psyche Card's set, by its emoji key. */
const icon = key => (P.icons[key] ? `<svg viewBox="0 0 24 24" aria-hidden="true">${P.icons[key]}</svg>` : '');

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

/** A whole page in PsycheAI's look. */
function page(title, body, { robots = 'noindex' } = {}) {
  return `<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">` +
    `<meta name="referrer" content="no-referrer"><meta name="robots" content="${robots}"><meta name="theme-color" content="${LIGHT.accent}">` +
    `<link rel="icon" href="/favicon.ico" sizes="any"><link rel="apple-touch-icon" href="/apple-touch-icon.png">` +
    `<title>${esc(title)}</title><style>${CSS}</style><body><main>` +
    `<a class="brand" href="https://psycheai.io">${BRAND_SVG}<span>PsycheAI</span></a>${body}` +
    `<p class="foot">PsycheAI · <a href="https://psycheai.io/muse-privacy">Privacy</a></p></main></body></html>`;
}

module.exports = { LIGHT, DARK, CSS, BRAND_SVG, icon, esc, page };
