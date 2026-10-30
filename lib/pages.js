// The card page: what opens when someone taps a card image in the chat. The
// image is the glance; the page is the full profile for the stage the two are
// at, and the one decision that stage asks for, as buttons:
//
//   psyche   your PsycheAI card from your latest read (no buttons; the full
//            read is on psycheai.io)
//   self     your own card, as matches will see it (no buttons: changes go
//            through the host, so the read and the card stay in step)
//   drop     their card → Pick <name> (uses one of your weekly picks)
//   sent     you picked them → waiting for their answer
//   picked   they picked you → where you click, a good balance → Yes / No thanks
//   mutual   both said yes → about, career → Open private chat, Swap Instagram
//
// The card itself is the card image (/card/<same token>.png, lib/cardimage.js),
// so the page and the picture in the chat can't drift apart; the page adds
// only what the image can't hold, and the stage's buttons.
//
// In PsycheAI's look (lib/theme.js), light and dark. No script and no
// cookies: the signed link (lib/links.js) is the key, and a button is a form
// post back to the same link.

const { page, esc, icon } = require('./theme');

const STYLE = `
.photos{display:grid;gap:10px;margin:0 0 14px}
.photos img{width:100%;aspect-ratio:4/5;object-fit:cover;border-radius:20px;background:var(--accent-soft);display:block}
.top{display:flex;justify-content:space-between;align-items:flex-start;gap:14px}
.who{margin:.6rem 0 0;font-weight:700;font-size:1.25rem}.who span{font-weight:400;opacity:.9}
.line{color:var(--accent);font-weight:600}
.grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}.grid .box{margin:0}
@media (max-width:420px){.grid{grid-template-columns:1fr}}
.actions{display:flex;flex-direction:column;gap:10px;margin-top:18px;position:sticky;bottom:0;padding:12px 0 calc(12px + env(safe-area-inset-bottom));background:linear-gradient(to bottom,transparent,var(--bg) 30%)}`;

const box = (label, key, inner) => `<div class="box"><p class="lab"><i>${icon(key)}</i>${esc(label)}</p>${inner}</div>`;
const numbered = (items, light) => `<ol class="num${light ? ' light' : ''}">${items.map((t, i) => `<li><b>${i + 1}</b>${esc(t)}</li>`).join('')}</ol>`;
const pills = items => `<div class="pills">${items.map(i => `<span>${esc(i)}</span>`).join('')}</div>`;
const cap = s => String(s || '').replace(/^\s*\w/, m => m.toUpperCase());

// Their photos, through this card's own signed link (server.js /photo/…).
function photos(card, token) {
  const n = Math.max(0, Math.min(3, Number(card.photoCount) || 0));
  if (!n) return '';
  return `<p class="lab" style="margin:6px 0 10px">Photos</p><div class="photos">${Array.from({ length: n }, (_, i) => `<img src="/photo/${esc(token)}/${i}.jpg" alt="Photo ${i + 1} of ${esc(card.firstName || '')}" loading="lazy">`).join('')}</div>`;
}

const form = (token, action, label, cls = '') => `<form method="post" action="/m/${esc(token)}/${action}"><button class="${cls}">${esc(label)}</button></form>`;

// A Sync: the two of them, what they share, and the one line on their types.
// No buttons: Muse writes the Sync itself in the chat.
function syncPage(c, token) {
  const me = c.me || {}, them = c.them || {};
  // A written Sync is the image itself (the same as in the chat), then what
  // the image leaves out: the evidence behind each point, and the caveat.
  if (c.report && c.report.summary) {
    const r = c.report;
    const why = [...(r.align || []), ...(r.differ || [])].filter(p => (p.evidence || []).length)
      .map(p => `<li><b>${esc(p.title)}</b>: ${p.evidence.map(esc).join(' · ')}</li>`).join('');
    return page('Psyche Sync · ' + me.firstName + ' & ' + them.firstName,
      `<style>${STYLE}.cardimg{width:100%;height:auto;border-radius:24px;display:block;margin-bottom:14px}</style>` +
      `<img class="cardimg" src="/card/${esc(token)}.png" alt="${esc(me.firstName)} &amp; ${esc(them.firstName)}: Psyche Sync">` +
      (why ? box('What each point rests on', '🔍', `<ul style="margin:0;padding-left:1.1rem">${why}</ul>`) : '') +
      (r.caveats ? `<p class="note">${esc(r.caveats)}</p>` : ''));
  }
  const parts = [`<style>${STYLE}</style>`];
  parts.push(`<div class="hero" style="text-align:center"><p class="kicker">Psyche Sync</p><h1>${esc(me.firstName)} &amp; ${esc(them.firstName)}</h1>` +
    `<p>${[me.characterName && them.characterName ? esc(me.characterName) + ' &amp; ' + esc(them.characterName) : '', me.mbti && them.mbti ? esc(me.mbti) + ' · ' + esc(them.mbti) : ''].filter(Boolean).join(' · ')}</p></div>`);
  if (c.naturalPair) parts.push(`<p class="line">${esc(c.naturalPair)}</p>`);
  if ((c.interests || []).length) parts.push(box('Into the same things', '✨', pills(c.interests.map(cap))));
  if ((c.values || []).length) parts.push(box('Values you share', '💞', pills(c.values)));
  if ((c.motivators || []).length) parts.push(box('What drives you both', '🧲', numbered(c.motivators.map(cap), true)));
  if (c.sharedAxes >= 2) parts.push(box('Types', '🧭', `<p style="margin:0">You share ${c.sharedAxes} of 4 type letters.</p>`));
  parts.push(`<p class="note">Your full Sync is in Muse: ask it to "show my Sync with ${esc(them.firstName)}".</p>`);
  return page('Psyche Sync · ' + me.firstName + ' & ' + them.firstName, parts.join(''));
}

function cardPage(ctx, token) {
  if (ctx.stage === 'sync') return syncPage(ctx.card, token);
  const c = ctx.card;
  const own = ctx.stage === 'self' || ctx.stage === 'psyche';
  const characterName = c.characterName || (c.character || '').split(' · ')[0];
  // The card image itself, so the page and the picture in the chat are one
  // design (lib/cardimage.js); below it, only what the image can't hold.
  const parts = [`<style>${STYLE}.cardimg{width:100%;height:auto;border-radius:24px;display:block;margin-bottom:14px}</style>`,
    `<img class="cardimg" src="/card/${esc(token)}.png" alt="${esc((own ? 'Your' : (c.firstName || 'Their') + '\u2019s') + ' card')}" width="1080" height="1920">`];
  parts.push(photos(c, token));
  if (c.drawnTo) parts.push(`<p class="line">${esc(c.drawnTo)}</p>`);
  if ((c.whereYouClick || []).length) {
    parts.push(box('Where you click', '📊', c.whereYouClick.map(b =>
      `<div class="bar"><span>${esc(b.area)}</span><i><b style="width:${Math.max(0, Math.min(100, b.fit))}%"></b></i><span>${b.fit}%</span></div>`).join('') +
      ((c.alsoShared || []).length ? `<p class="muted" style="margin:8px 0 0">${c.alsoShared.map(esc).join(' ')}</p>` : '')));
  }
  if (c.balance) parts.push(box('A good balance', '🔗', `<p style="margin:0">${esc(c.balance)}</p>`));
  if (!own && c.characterWhy && (ctx.stage === 'picked' || ctx.stage === 'mutual')) parts.push(box('Why ' + characterName, '✨', `<p style="margin:0">${esc(c.characterWhy)}</p>`));
  // The write-up is on the card itself, so no About here; work, once it's mutual.
  if (ctx.stage === 'mutual' && c.career) parts.push(box('Work', '👤', `<p style="margin:0">${esc(c.career)}</p>`));
  if (ctx.stage === 'self') parts.push(`<p class="note">${c.live ? 'This is your live card.' : 'Matching starts once you confirm.'} To change anything, tell Muse what to fix.</p>`);
  if (ctx.stage === 'psyche') parts.push(`<p class="note">Your full report is at the psycheai.io link Muse gave you.</p>`);

  const actions = [];
  if (ctx.stage === 'drop') {
    if (c.picked) actions.push(`<p class="note">You picked ${esc(c.firstName)}.</p>`);
    else if (ctx.picksLeft > 0) actions.push(form(token, 'pick', `Pick ${c.firstName}`), `<p class="note">${ctx.picksLeft} of ${ctx.picksTotal || 2} picks left this week</p>`);
    else actions.push(`<p class="note">You've used this week's picks.</p>`);
  }
  if (ctx.stage === 'sent') actions.push(`<p class="note">You picked ${esc(c.firstName)}. Waiting for their answer.</p>`);
  if (ctx.stage === 'picked') actions.push(`<p class="note" style="margin-top:0">${esc(c.firstName)} picked you.</p>`, form(token, 'yes', "Yes, I'd like to meet"), form(token, 'no', 'No thanks', 'ghost'));
  if (ctx.stage === 'mutual') {
    if (ctx.chat) actions.push(`<a class="btn" href="${esc(ctx.chat)}">Open private chat</a>`);
    const swap = c.instagramSwap;
    if (swap === 'both') actions.push(`<a class="btn ghost" href="https://instagram.com/${esc((c.instagram || '').replace(/^@/, ''))}" rel="noreferrer">${esc(c.instagram)} on Instagram</a>`);
    else if (swap === 'you_offered') actions.push(`<p class="note">You offered your Instagram. It shows to you both once ${esc(c.firstName)} offers theirs.</p>`, form(token, 'unshare', 'Take back my offer', 'ghost'));
    else actions.push(form(token, 'share', swap === 'they_offered' ? `Swap Instagram (${c.firstName} already offered)` : 'Offer to swap Instagram', 'ghost'));
  }
  if (actions.length) parts.push(`<div class="actions">${actions.join('')}</div>`);
  return page(own ? 'Your Psyche Card' : c.firstName + ' · Psyche Pair', parts.join(''));
}

const gonePage = () => page('Not available', '<h1>Not available</h1><p>This card has expired or is no longer available. Ask Muse for your latest matches.</p>');

// For callers that build their own small pages (server.js, site.js, oauth.js).
const shell = (title, body) => page(title, body);

module.exports = { cardPage, gonePage, shell, esc };
