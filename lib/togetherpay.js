// Psyche Together, bought on the website (README "Psyche Together, paid on the website"). Nothing is sold inside
// the host (CLAUDE.md): when payment is on, starting one without a purchase answers with a link here, worded as a
// limit, and the purchase happens on this page through Stripe Checkout.
//
//   GET  /together/buy/<token>            what it is, and the button (or "you're set")
//   POST /together/buy/<token>/checkout   off to Stripe Checkout, one payment
//   POST /stripe/webhook                  (lib/plus.js passes Together's sessions here) the only place a purchase lands
//
// One purchase is one Psyche Together, started by the one who bought it: joining stays free, and so do writing the
// read again and the four-week check-ins; and if the partner never joins, the link goes after 30 days and the
// purchase is refunded (PLAN.md). The token is a signed link for one account that lasts an hour, as Plus's
// is. A purchase is credited only from a webhook whose signature checks out, never from the return from Checkout,
// and each Checkout session is credited once.

const store = require('./store');
const links = require('./links');
const { page, esc, icon } = require('./theme');
const { BASE_URL } = require('./config');

const PAID = 'togetherpaid';         // userId → { credits, sessions: [Checkout session ids credited] }
const LINK_MS = 60 * 60000;

// US$5, and rounded local prices in the same markets as psycheai.io's US$5 report (psycheai docs/prices.js, `unlock`).
// Amounts in each currency's minor unit, as Stripe takes them; JPY has none. Everywhere else pays in USD.
const PRICES = {
  usd: { shown: 'US$5', amount: 500 }, sgd: { shown: 'S$7', amount: 700 }, gbp: { shown: '£4', amount: 400 },
  eur: { shown: '€5', amount: 500 }, aud: { shown: 'A$8', amount: 800 }, cad: { shown: 'C$7', amount: 700 },
  nzd: { shown: 'NZ$9', amount: 900 }, hkd: { shown: 'HK$39', amount: 3900 }, jpy: { shown: '¥800', amount: 800 },
  chf: { shown: 'CHF 5', amount: 500 }, myr: { shown: 'RM22', amount: 2200 },
};
const EUROZONE = ['AT', 'BE', 'CY', 'DE', 'EE', 'ES', 'FI', 'FR', 'GR', 'HR', 'IE', 'IT', 'LT', 'LU', 'LV', 'MT', 'NL', 'PT', 'SI', 'SK'];
const COUNTRY_CURRENCY = Object.assign({ US: 'usd', SG: 'sgd', GB: 'gbp', AU: 'aud', CA: 'cad', NZ: 'nzd', HK: 'hkd', JP: 'jpy', CH: 'chf', LI: 'chf', MY: 'myr' },
  Object.fromEntries(EUROZONE.map(c => [c, 'eur'])));

/** The currency to charge in: one asked for by the page (?cur=), else from the country Cloudflare saw, else the
 *  region of the browser's language, else USD. A guess, and an honest one: the prices are rounded equivalents. */
function currencyFor(asked, country, language) {
  if (PRICES[String(asked || '').toLowerCase()]) return String(asked).toLowerCase();
  const c = String(country || '').toUpperCase();
  if (COUNTRY_CURRENCY[c]) return COUNTRY_CURRENCY[c];
  const region = (String(language || '').split(',')[0].split('-')[1] || '').toUpperCase();
  return COUNTRY_CURRENCY[region] || 'usd';
}

/** Payment is on only when asked for and fully set up: otherwise everyone may start one, as before. */
const enabled = () => process.env.PSYCHE_TOGETHER_PAID === '1' && Boolean(process.env.STRIPE_SECRET_KEY && process.env.STRIPE_WEBHOOK_SECRET);

const tokenFor = (userId, now = Date.now()) => links.sign({ v: userId, k: 'together' }, now, LINK_MS);
function userFor(token, now = Date.now()) {
  const p = links.verify(token, now);
  return p && p.k === 'together' ? store.getUser(p.v) : null;
}

const credits = userId => Math.max(0, Number((store.kvGet(PAID, userId) || {}).credits) || 0);

/** For lib/together.js: null when this account may start one, else what to say and where to buy it. */
function gate(user, now = Date.now()) {
  if (!enabled() || !user || credits(user.id) > 0) return null;
  return {
    say: 'Starting a Psyche Together needs it set up on the PsycheAI website first. Open this link, then come back and tap the button. Joining a partner\'s stays free.',
    url: BASE_URL + '/together/buy/' + tokenFor(user.id, now),
  };
}

/** A new couple was made: one purchase is used. Returns { session, pi } for the couple to keep, so it can be refunded
 *  if the partner never joins, or null. */
function use(userId) {
  if (!enabled()) return null;
  const row = store.kvGet(PAID, userId) || { credits: 0, sessions: [] };
  if (!(row.credits > 0)) return null;
  const unused = [...(row.unused || [])];
  const paid = unused.shift() || null;
  store.kvSet(PAID, userId, { ...row, credits: row.credits - 1, unused });
  return paid;
}

/** The partner never joined (lib/together.js sweep): the purchase is refunded through Stripe. Resolves true once done. */
async function refund(paid, stripe = require('./plus').stripeCall) {
  if (!paid || !paid.pi) return true;            // nothing to refund (free, or paid before refunds were kept)
  if (!process.env.STRIPE_SECRET_KEY) return false;
  try {
    await stripe('/v1/refunds', { payment_intent: paid.pi, metadata: { kind: 'together', reason: 'partner never joined' } });
    return true;
  } catch (err) {
    return false;
  }
}

/** From a verified webhook: credit one Psyche Together for this Checkout session, once. */
function credit(userId, sessionId, pi) {
  if (!userId || !sessionId || !store.getUser(userId)) return false;
  const row = store.kvGet(PAID, userId) || { credits: 0, sessions: [] };
  if ((row.sessions || []).includes(sessionId)) return false;
  store.kvSet(PAID, userId, { credits: (Number(row.credits) || 0) + 1, sessions: [...(row.sessions || []), sessionId].slice(-50),
                              unused: [...(row.unused || []), { session: sessionId, pi: pi || null }] });
  return true;
}

// The buy page (README "The Psyche Together page"): the sample couple's two Psyche Cards, what it reads (the
// triangle, as on psycheai.io), the five chapters, three steps, privacy, the price for both and one button that stays
// in reach. In short, plain lines. The price is shown here only, never in Muse.
const CHAPTERS = [
  ['#c2366d', 'Care and connection', 'How you each feel loved, and how to show it.'],
  ['#2d5fa8', 'Living together', 'What feels fair at home, and what doesn’t.'],
  ['#6a4bb5', 'Shared meaning', 'Your values and big decisions, side by side.'],
  ['#2f7d6b', 'Feeling secure', 'How sure you both are, and what helps.'],
  ['#c2571a', 'Conflict and repair', 'The loop behind your rows, and how to break it.'],
];
const SOURCES = [['📘', 'Both Psyches', 'who you are'], ['💬', 'Your chat', 'what you say'], ['📓', 'Questions', 'how it feels']];
const BUY_CSS = `
main{padding-bottom:0}
.hero2{position:relative;margin:0 -16px;padding:22px 16px 26px;text-align:center;color:#fff;overflow:hidden;
  background:radial-gradient(120% 80% at 50% 0%,#8b4bb8 0%,#5b2a86 45%,#2e1446 100%);border-radius:0 0 30px 30px}
.hero2:before{content:"";position:absolute;inset:0;background:radial-gradient(60% 40% at 50% 38%,rgba(255,122,162,.35),transparent 70%)}
.fan{position:relative;height:300px;max-width:340px;margin:0 auto}
.fan img{position:absolute;top:8px;width:46%;height:auto;border-radius:14px;box-shadow:0 18px 40px rgba(20,4,40,.55);border:1px solid rgba(255,255,255,.35)}
.fan .l{left:4%;transform:rotate(-9deg)}.fan .r{right:4%;transform:rotate(9deg)}
.fan .hz{position:absolute;left:50%;top:118px;transform:translateX(-50%);width:58px;height:58px;border-radius:50%;background:#fff;display:grid;place-items:center;
  box-shadow:0 8px 24px rgba(194,54,109,.55),0 0 0 6px rgba(255,255,255,.18);z-index:2}
.fan .hz svg{width:30px;height:30px}
.names{position:relative;display:flex;justify-content:space-between;max-width:300px;margin:-4px auto 10px;font-size:.82rem;opacity:.9}
.names b{display:block;font-size:.95rem}
.new{display:inline-block;padding:.15rem .6rem;border-radius:999px;font-size:.7rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;background:linear-gradient(135deg,#ff7aa2,#c2366d);margin-bottom:8px}
.hero2 h1{color:#fff;font-size:2.2rem;position:relative}
.hero2 .lede{position:relative;margin:.5rem auto 0;max-width:22rem;font-size:1.08rem;opacity:.95}
.chipp{position:relative;display:inline-block;margin-top:12px;padding:.3rem .8rem;border-radius:999px;background:rgba(255,255,255,.16);border:1px solid rgba(255,255,255,.3);font-weight:700;font-size:.9rem}
.sample2{position:relative;display:inline-block;margin-top:16px;padding:.7rem 1.3rem;border-radius:999px;background:#fff;color:#5b2a86;font-weight:700;text-decoration:none;box-shadow:0 8px 20px rgba(20,4,40,.35)}
.hook{margin:22px 0 0;padding:14px 16px;border-radius:18px;background:var(--alt);border:1px solid var(--line);border-left:4px solid #d1477a;font-style:italic}
.hook b{font-style:normal;color:#c2366d}
h2{font-size:1.25rem;margin:30px 0 4px;letter-spacing:-.01em}
.sub{color:var(--soft);margin:0 0 12px}
.tri{position:relative;width:280px;height:250px;margin:6px auto 0}
.tri svg.lines{position:absolute;inset:0;width:280px;height:250px}
.tri polygon{fill:rgba(123,63,160,.08);stroke:rgba(123,63,160,.5);stroke-width:1.6;stroke-dasharray:4 4}
.node{position:absolute;width:104px;display:flex;flex-direction:column;align-items:center;text-align:center;font-size:12px;line-height:15px;color:var(--soft)}
.node b{font-size:13.5px;line-height:17px;color:var(--ink)}
.node .dot{width:38px;height:38px;border-radius:50%;display:grid;place-items:center;background:linear-gradient(135deg,#7b3fa0,#d1477a);box-shadow:0 0 0 5px var(--bg)}
.node .dot svg{width:19px;height:19px;stroke:#fff;fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.n0{top:0;left:88px}.n0 b{order:1}.n0 span{order:2}.n0 .dot{order:3;margin-top:4px}
.n1,.n2{top:178px}.n1{left:0}.n2{left:176px}.n1 .dot,.n2 .dot{margin-bottom:4px}
.mid{position:absolute;left:140px;top:160px;transform:translate(-50%,-50%);width:118px;margin:0;display:flex;flex-direction:column;gap:3px;text-align:center;font-size:12px;font-weight:700}
.mid span+span{color:#c2366d}
.ch2{list-style:none;padding:0;margin:0;display:grid;gap:8px}
.ch2 li{display:flex;gap:12px;align-items:center;background:var(--alt);border:1px solid var(--line);border-radius:16px;padding:10px 12px}
.ch2 .k{flex:0 0 38px;height:38px;border-radius:12px;display:grid;place-items:center;color:#fff;font-weight:800;font-size:.85rem}
.ch2 b{display:block}.ch2 span{color:var(--soft);font-size:.92rem}
.steps{list-style:none;padding:0;margin:0;counter-reset:s}
.steps li{position:relative;padding:0 0 16px 44px}
.steps li:before{counter-increment:s;content:counter(s);position:absolute;left:0;top:0;width:30px;height:30px;border-radius:50%;background:linear-gradient(135deg,#7b3fa0,#d1477a);color:#fff;display:grid;place-items:center;font-weight:700;font-size:.85rem}
.steps li:not(:last-child):after{content:"";position:absolute;left:14px;top:34px;bottom:4px;width:2px;background:var(--line)}
.steps b{display:block}.steps span{color:var(--soft);font-size:.95rem}
.priv{display:flex;gap:12px;align-items:flex-start}
.priv .lk{flex:0 0 38px;height:38px;border-radius:12px;background:var(--accent-soft);display:grid;place-items:center}
.priv .lk svg{width:19px;height:19px;stroke:var(--accent);fill:none;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.priv p{margin:0 0 .3rem}
.price2{position:relative;text-align:center;border-radius:22px;padding:20px 16px;margin:26px 0 0;color:#fff;background:linear-gradient(135deg,#5b2a86,#7b3fa0 50%,#c2366d)}
.price2 .big{font-size:2.6rem;font-weight:800;letter-spacing:-.02em;margin:0;line-height:1.1}
.price2 p{margin:.3rem 0 0;opacity:.95}
.price2 .ok{display:inline-block;margin-top:10px;padding:.3rem .8rem;border-radius:999px;background:rgba(255,255,255,.16);font-size:.88rem}
details{background:var(--alt);border:1px solid var(--line);border-radius:14px;padding:11px 14px;margin:8px 0}
summary{font-weight:600;cursor:pointer}details p{margin:.4rem 0 0;color:var(--soft)}
.dock{position:sticky;bottom:0;padding:14px 0 12px;background:linear-gradient(rgba(250,247,251,0),var(--bg) 35%);margin-top:18px;z-index:5}
.dock button{font-size:1.05rem;padding:1rem;box-shadow:0 10px 26px rgba(123,63,160,.35)}
.dock .note{margin-top:6px}
.done{text-align:center}.done .tick{width:56px;height:56px;border-radius:50%;background:#2f7d5b;color:#fff;display:grid;place-items:center;font-size:1.7rem;margin:6px auto 10px}`;
const HEART = '<svg viewBox="0 0 24 24" aria-hidden="true"><path fill="#c2366d" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.4 5c2 0 3.6 1.1 4.6 2.6l1 1.4 1-1.4C14 6.1 15.6 5 17.6 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21z"/></svg>';

/** What the page says between its header and its button, the same on the buy page and the public one. */
function sections(price) {
  const body = [];
  body.push('<p class="hook">Couples who stay together turn toward each other’s small moments <b>86 times in 100</b>. Couples who split: 33 (Gottman). What’s yours?</p>');
  body.push('<h2>What it reads</h2><p class="sub">Three views of you both. Where they agree is a strength; where they differ is a blind spot.</p>' +
    '<div class="tri" role="group" aria-label="Both Psyches, your chat, questions"><svg class="lines" viewBox="0 0 280 250" aria-hidden="true"><polygon points="140,56 52,196 228,196"/></svg>' +
    SOURCES.map(([k, what, why], n) => `<div class="node n${n}"><span class="dot">${icon(k)}</span><b>${esc(what)}</b><span>${esc(why)}</span></div>`).join('') +
    '<p class="mid"><span>Agree: a strength</span><span>Differ: a blind spot</span></p></div>');
  body.push('<h2>What you get</h2><p class="sub">One report for you both, in five chapters.</p><ol class="ch2">' +
    CHAPTERS.map(([c, t, d], n) => `<li><span class="k" style="background:${c}">0${n + 1}</span><div><b>${esc(t)}</b><span>${esc(d)}</span></div></li>`).join('') +
    '<li><span class="k" style="background:#2f7d5b">28</span><div><b>A 28-day plan</b><span>Small things to do together, one a day.</span></div></li></ol>');
  body.push('<h2>How it works</h2><ol class="steps" style="margin-top:12px">' +
    '<li><b>You start it in Muse</b><span>Your partner joins for free.</span></li>' +
    '<li><b>You each answer 8 quick screens</b><span>About 2 minutes, in your own Muse.</span></li>' +
    '<li><b>You both get the report</b><span>Then check in again every 4 weeks to see what changed.</span></li></ol>');
  body.push(`<div class="box priv"><span class="lk">${icon('🔒')}</span><div><p><b>Private</b></p><p>Your answers stay private. Only a few, like your big decisions, are shown side by side.</p>` +
    '<p>PsycheAI can’t read your answers or your report.</p></div></div>');
  body.push(`<div class="price2"><p class="big">${esc(price.shown)}</p><p>One payment, for both of you. No subscription.</p>` +
    '<span class="ok">Money back if your partner doesn’t join within 30 days</span></div>');
  body.push('<h2>Questions</h2>' +
    '<details><summary>Does my partner need to pay?</summary><p>No. One payment covers you both.</p></details>' +
    '<details><summary>What do we need first?</summary><p>You each need your own Psyche from PsycheAI in Muse. It’s free.</p></details>' +
    '<details><summary>What happens after I pay?</summary><p>Go back to Muse and tap <b>I’ve paid, start it</b>. Nothing to copy or paste.</p></details>');
  return body;
}

const heroHtml = () => '<div class="hero2"><div class="fan"><img class="l" src="/together/cards/emily.jpg" alt="Emily’s Psyche Card: most like Mulan" width="640" height="1139">' +
  `<div class="hz">${HEART}</div><img class="r" src="/together/cards/lucas.jpg" alt="Lucas’s Psyche Card: most like Odysseus" width="640" height="1139"></div>` +
  '<div class="names"><span><b>Emily</b>Mulan</span><span><b>Lucas</b>Odysseus</span></div>' +
  '<span class="new">New</span><h1>Psyche Together</h1><p class="lede">Your AI relationship coach, built from both your Psyches.</p>';

function buyPage(user, token, note, done, cur = 'usd') {
  const set = credits(user.id) > 0;
  const price = PRICES[cur] || PRICES.usd;
  const hero = heroHtml();
  const body = [`<style>${BUY_CSS}</style>`];
  if (set || done) {
    body.push(hero + '</div>');
    if (note) body.push(`<p class="error">${esc(note)}</p>`);
    body.push(`<div class="box done"><div class="tick">✓</div><h2 style="margin:0 0 6px">${set ? 'You’re all set' : 'Thank you!'}</h2>` +
      `<p style="margin:0">${set ? '' : 'Your payment is going through. '}Go back to Muse and tap <b>I’ve paid, start it</b>. There’s nothing to copy or paste.</p></div>`);
    return page('Psyche Together', body.join(''));
  }
  body.push(hero + `<span class="chipp">${esc(price.shown)} for both of you</span><br>` +
    '<a class="sample2" href="/together/sample" target="_blank" rel="noopener">See a sample report →</a></div>');
  if (note) body.push(`<p class="error">${esc(note)}</p>`);
  body.push(...sections(price));
  if (enabled()) {
    body.push(`<div class="dock"><form method="post" action="/together/buy/${esc(token)}/checkout?cur=${esc(cur)}"><button>Get Psyche Together · ${esc(price.shown)}</button></form>` +
      '<p class="note">Secure payment by Stripe.</p></div>');
  } else body.push('<p class="note">Psyche Together needs nothing here right now: say Start Psyche Together in Muse.</p>');
  return page('Psyche Together', body.join(''));
}

// The public page (README "The Psyche Together page"), at app.psycheai.io/psyche-together and psycheai.io/psyche-together:
// the same page with no account and no pay button. It ends in how to start: PsycheAI's own install line for someone
// new, then the line to say in Muse. Payment happens only from the link Muse gives when they start, tied to their account.
const START_CSS = `
.start{margin:26px 0 0;padding:18px 16px;border-radius:22px;background:var(--alt);border:1px solid var(--line)}
.start h2{margin:0 0 10px}
.start ol{margin:0;padding-left:1.2rem}.start li{margin:0 0 12px}
.paste{display:flex;gap:8px;align-items:center;margin-top:6px;padding:10px 12px;border-radius:14px;background:var(--accent-soft);font-weight:600;font-size:.95rem;color:var(--ink);word-break:break-word}
.paste span{flex:1}
.paste button{width:auto;flex:0 0 auto;padding:.45rem .9rem;font-size:.85rem}`;
const INSTALL_LINE = 'Install https://psycheai.io/skill and generate my Psyche';
const START_LINE = 'Psyche Together with my partner';

function publicPage(cur = 'usd') {
  const price = PRICES[cur] || PRICES.usd;
  const copy = text => `<div class="paste"><span>${esc(text)}</span><button type="button" data-copy="${esc(text)}">Copy</button></div>`;
  const body = [`<style>${BUY_CSS}${START_CSS}</style>`, heroHtml() + `<span class="chipp">${esc(price.shown)} for both of you</span><br>` +
    '<a class="sample2" href="/together/sample" target="_blank" rel="noopener">See a sample report →</a></div>'];
  body.push(...sections(price));
  body.push('<div class="start" id="start"><h2>Start in Meta Muse</h2><ol>' +
    `<li><b>New to PsycheAI?</b> Open a new chat in the Muse app and paste this. Your own Psyche is free and takes about 5 minutes.${copy(INSTALL_LINE)}</li>` +
    `<li><b>Then say this</b>, or tap Psyche Together with my partner in PsycheAI’s menu.${copy(START_LINE)}</li>` +
    `<li><b>Pay once on PsycheAI’s website</b> when Muse gives you the link (${esc(price.shown)}), then send your partner the invite. They join free.</li></ol></div>`);
  body.push('<div class="dock"><a class="btn" href="#start">Get started in Muse</a></div>');
  body.push('<script>document.addEventListener("click",function(e){var b=e.target.closest("[data-copy]");if(!b)return;' +
    'var t=b.getAttribute("data-copy");(navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){b.textContent="Copied";setTimeout(function(){b.textContent="Copy"},1600)},function(){});});</script>');
  return page('Psyche Together · PsycheAI', body.join(''), { robots: 'index,follow', head: '<meta name="description" content="Your AI relationship coach, built from both your Psyches. One payment for both of you, in Meta Muse.">' });
}

/** GET /psyche-together */
function about(where = {}) {
  return { status: 200, html: publicPage(currencyFor(where.cur, where.country, where.language)) };
}

/** GET /together/buy/<token> */
function show(token, now = Date.now(), done = false, where = {}) {
  const user = userFor(token, now);
  if (!user) return { status: 404, html: page('Link expired', '<h1>This link has expired</h1><p>Say Start Psyche Together in Muse for a new one.</p>') };
  return { status: 200, html: buyPage(user, token, '', done, currencyFor(where.cur, where.country, where.language)) };
}

/** POST /together/buy/<token>/checkout */
async function checkout(token, now = Date.now(), stripe = require('./plus').stripeCall, where = {}) {
  const user = userFor(token, now);
  if (!user) return show(token, now);
  const cur = currencyFor(where.cur, where.country, where.language);
  if (!enabled()) return { status: 503, html: buyPage(user, token, 'Psyche Together can\'t be bought here right now.', false, cur) };
  if (credits(user.id) > 0) return { status: 303, location: BASE_URL + '/together/buy/' + token };
  const back = BASE_URL + '/together/buy/' + tokenFor(user.id, now);
  try {
    const session = await stripe('/v1/checkout/sessions', {
      mode: 'payment',
      // The amount comes from PRICES only, never from the page: the page can pick a currency, not a price.
      line_items: [{ quantity: 1, price_data: { currency: cur, unit_amount: PRICES[cur].amount, product_data: { name: 'Psyche Together', description: 'One Psyche Together for you and your partner' } } }],
      client_reference_id: user.id,
      metadata: { kind: 'together', userId: user.id },
      payment_intent_data: { metadata: { kind: 'together', userId: user.id } },
      customer_email: store.emailOf(user.id) || undefined,
      allow_promotion_codes: 'true',
      success_url: back + '?done=1',
      cancel_url: back,
    });
    return { status: 303, location: session.url };
  } catch (err) {
    return { status: 502, html: buyPage(user, token, 'Stripe could not be reached. Try again in a minute.', false, cur) };
  }
}

/** For lib/plus.js's webhook, once the signature has been checked: a paid Together session is credited. */
function fromWebhook(event) {
  const obj = (event.data && event.data.object) || {};
  if (!/^checkout\.session\.(completed|async_payment_succeeded)$/.test(event.type)) return false;
  if (!obj.metadata || obj.metadata.kind !== 'together') return false;
  // A 100%-off promotion code completes with no_payment_required (README "A free Psyche Together by promotion code"):
  // credited as a paid one, with no payment to refund.
  if (obj.payment_status !== 'paid' && obj.payment_status !== 'no_payment_required') return true;          // ours, not paid yet: async_payment_succeeded credits it
  credit(obj.client_reference_id || obj.metadata.userId, obj.id, typeof obj.payment_intent === 'string' ? obj.payment_intent : null);
  return true;
}

/** For delete_my_data. */
function forget(userId) {
  store.kvDel(PAID, userId);
}

module.exports = { PRICES, currencyFor, about, enabled, gate, use, refund, credit, credits, tokenFor, userFor, show, checkout, fromWebhook, forget };
