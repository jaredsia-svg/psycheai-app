// The Psyche Pair details as one form, in place of a chat of questions
// (README "Questions first, then the card"). Muse can only show text and
// buttons, so the fields a person has to answer themselves (who they want to
// meet, what they're after, religion, kids, marriage, an age range) are a
// short page here, prefilled from what Muse already saved. The link is signed
// for this user and lasts two hours; one submit saves every answer as stated
// (source "stated"), the same as answering in the chat, and the chat stays a
// fallback ("Answer here instead").
//
// Nothing here is inferred: every field is the user's own answer. Religion and
// city are required, as in the chat. Kids and marriage each carry "Good to
// have" or "Must have", saved straight away as a nice or must rule on the
// partner's answer. "Anything else" is a few short rows, each good to have or
// a must; they go in prefs.brief ("Must have: …. Good to have: ….") where Muse
// reads them back (get_my_card) and turns them into rules with set_preferences.

const store = require('./store');
const links = require('./links');
const { BASE_URL } = require('./config');
const { validateProfile, GENDERS, INTENTS, RELIGIONS, FIELDS } = require('./schema');
const theme = require('./theme');
const characters = require('./characters');
const psyche = require('./psyche');
const photos = require('./photos');
const { validatePreferences } = require('./preferences');

const TTL_MS = 2 * 3600000;
const esc = theme.esc;

const LABELS = {
  gender: { woman: 'Woman', man: 'Man', nonbinary: 'Nonbinary' },
  seeking: { woman: 'Women', man: 'Men', nonbinary: 'Nonbinary people' },
  intent: { serious: 'Something serious', open: 'Open to see', casual: 'Something casual', friends: 'New friends' },
  kids: { wants: 'Want them', open: 'Open', doesnt_want: "Don't want them", has: 'Have kids' },
  marriage: { wants: 'Want to marry', open: 'Open', doesnt_want: "Don't want to" },
};
const RELIGION_LABEL = r => (r === 'free_thinker' ? 'Free-thinker' : r === 'prefer_not_to_say' ? 'Prefer not to say' : r.charAt(0).toUpperCase() + r.slice(1));

// The Psyche Card's line on their character, cut to what a Pair card holds
// (140): at the end of a sentence if one fits, else at a word, never mid-word.
function shortWhy(text) {
  const t = String(text || '').replace(/\s+/g, ' ').trim();
  if (t.length <= 140) return t;
  const sentence = t.slice(0, 140).match(/^.*[.!?](?=\s|$)/);
  if (sentence && sentence[0].length >= 40) return sentence[0];
  return t.slice(0, 139).replace(/\s+\S*$/, '').replace(/[,;:]$/, '') + '.';
}

/** A link to this user's form, good for two hours. */
function link(userId, now = Date.now()) {
  return BASE_URL + '/pair/form/' + links.sign({ u: userId, k: 'pairform' }, now, TTL_MS);
}

function userOf(token, now) {
  const p = links.verify(token, now);
  if (!p || p.k !== 'pairform') return null;
  return store.getUser(p.u);
}

const statedOf = (profile, key) => {
  const cell = profile && profile.traits && profile.traits[key];
  return cell && cell.value != null ? cell.value : null;
};

function radios(name, options, labels, current, required = true) {
  return '<div class="opts">' + options.map(o => `<label class="opt"><input type="radio" name="${name}" value="${esc(o)}"${o === current ? ' checked' : ''}${required ? ' required' : ''}><span>${esc(labels[o] || o)}</span></label>`).join('') + '</div>';
}

// "Good to have" or "Must have", for one thing they're looking for.
function matters(name, current) {
  return `<div class="seg" role="radiogroup">${[['nice', 'Good to have'], ['must', 'Must have']].map(([v, l]) =>
    `<label><input type="radio" name="${name}" value="${v}"${v === (current || 'nice') ? ' checked' : ''}><span>${l}</span></label>`).join('')}</div>`;
}

// Kids and marriage: the partner answers that fit theirs. "Open" fits anyone,
// so it makes no rule.
const FITS = {
  'future.kids': { wants: ['wants', 'open', 'has'], has: ['wants', 'open', 'has'], doesnt_want: ['doesnt_want', 'open'] },
  'future.marriage': { wants: ['wants', 'open'], doesnt_want: ['doesnt_want', 'open'] },
};
const FORM_RULES = Object.keys(FITS);
const kindOf = (prefs, field) => ((prefs && prefs.must) || []).some(r => r.field === field) ? 'must' : 'nice';

// "Anything else": rows of a few words, each good to have or a must, kept as
// the brief ("Must have: a; b. Good to have: c."), which Muse turns into rules.
const WISH_MAX = 6;
const WISH_CHARS = 80;
function briefOf(wishes) {
  const part = (label, list) => (list.length ? `${label}: ${list.join('; ')}.` : '');
  return [part('Must have', wishes.filter(w => w.must).map(w => w.text)), part('Good to have', wishes.filter(w => !w.must).map(w => w.text))].filter(Boolean).join(' ');
}
function wishesOf(brief) {
  const text = String(brief || '').trim();
  if (!text) return [];
  const re = /(Must have|Good to have): (.*?)\.(?=\s*(?:Must have:|Good to have:|$))/g;
  // Written some other way (in the chat, say): one row, as it is.
  if (text.replace(re, '').trim()) return [{ text: text.slice(0, WISH_CHARS * WISH_MAX), must: false }];
  const out = [];
  for (const m of text.matchAll(re)) for (const t of m[2].split('; ')) if (t.trim()) out.push({ text: t.trim(), must: m[1] === 'Must have' });
  return out;
}

function wishRow(i, w = { text: '', must: false }) {
  return `<div class="wish"><input type="text" name="wish${i}" value="${esc(w.text)}" maxlength="${WISH_CHARS}" placeholder="${i === 0 ? 'e.g. loves the outdoors' : 'Something else'}" aria-label="Something you're looking for">` +
    matters('wishMust' + i, w.must ? 'must' : 'nice') + '</div>';
}

// Their latest Instagram photos, offered here so they can tap three instead of
// finding them on their phone. Muse passes the image addresses without
// looking or choosing (pair_form); only Instagram's own image hosts are
// taken. They're kept for the form's two hours, fetched only through this
// form's signed link (igPhoto), so the page can shrink the chosen ones like
// any other photo, and dropped once the form is saved.
const IG_MAX = 12;
const IG_HOSTS = /(^|\.)(cdninstagram\.com|fbcdn\.net)$/i;
const IG_BYTES = 8 * 1024 * 1024;
function offerInstagram(userId, urls, now = Date.now()) {
  const list = (Array.isArray(urls) ? urls : []).map(String).filter(u => {
    try { const x = new URL(u); return x.protocol === 'https:' && IG_HOSTS.test(x.hostname); } catch { return false; }
  }).slice(0, IG_MAX);
  if (list.length) store.kvSet('igpick', userId, { urls: list, until: now + TTL_MS });
  return list.length;
}
const igOf = (userId, now) => { const v = store.kvGet('igpick', userId); return v && v.until > now ? v.urls : []; };

/** GET /pair/form/<token>/ig/<n>.jpg: one offered photo, or null. */
async function igPhoto(token, n, now = Date.now()) {
  const user = userOf(token, now);
  const url = user && igOf(user.id, now)[Number(n)];
  if (!url) return null;
  try {
    const res = await fetch(url, { headers: { Accept: 'image/jpeg,image/webp,image/*' }, redirect: 'error', signal: AbortSignal.timeout(8000) });
    const type = (res.headers.get('content-type') || '').split(';')[0].trim();
    if (!res.ok || !/^image\/(jpeg|png|webp|avif|heic)$/.test(type) || Number(res.headers.get('content-length') || 0) > IG_BYTES) return null;
    const buf = Buffer.from(await res.arrayBuffer());
    return buf.length <= IG_BYTES ? { type, buf } : null;
  } catch { return null; }
}

// Three photos, chosen by them, shrunk here in the browser to a JPEG of at
// most 900 px (about 100-200 KB) before they're sent, as data: URLs in three
// hidden fields. Already have three? Keeping them is the default.
function photoField(user, token, now) {
  const have = photos.countOf(user) >= photos.COUNT;
  const ig = igOf(user.id, now);
  return `<p class="hint">Clear photos of you, on your own. Only people you're matched with see them.${have ? ' You have 3 already: choose new ones to replace them.' : ''}</p>` +
    (ig.length ? `<div class="q" id="igbox"><p>From your Instagram <span class="hint" id="igcount">tap 3</span></p><div class="ig" id="ig">` +
      ig.map((_, i) => `<button type="button" class="igp" data-src="/pair/form/${esc(token)}/ig/${i}.jpg" aria-pressed="false"><img src="/pair/form/${esc(token)}/ig/${i}.jpg" alt="Instagram photo ${i + 1}" loading="lazy"><b></b></button>`).join('') +
      `</div></div>` : '') +
    `<label class="pick"><input type="file" id="pick" accept="image/*" multiple${have || ig.length ? '' : ' required'}><span>${ig.length ? 'Or choose from your phone' : have ? 'Choose 3 new photos' : 'Choose 3 photos'}</span></label>` +
    `<div class="thumbs" id="thumbs"></div>` +
    Array.from({ length: photos.COUNT }, (_, i) => `<input type="hidden" name="photo${i}" id="photo${i}">`).join('') +
    `<input type="hidden" name="keepPhotos" value="${have ? '1' : ''}">`;
}

const PHOTO_SCRIPT = `<script>
(function () {
  var pick = document.getElementById('pick'), thumbs = document.getElementById('thumbs'), form = pick.form;
  function shrink(file) {
    return new Promise(function (done, fail) {
      var img = new Image(), url = URL.createObjectURL(file);
      img.onload = function () {
        var s = Math.min(1, 900 / Math.max(img.width, img.height)), c = document.createElement('canvas');
        c.width = Math.round(img.width * s); c.height = Math.round(img.height * s);
        c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        var q = 0.82, out = c.toDataURL('image/jpeg', q);
        while (out.length > 520000 && q > 0.4) { q -= 0.1; out = c.toDataURL('image/jpeg', q); }
        done(out);
      };
      img.onerror = fail; img.src = url;
    });
  }
  function useAll(urls) {
    urls.forEach(function (u, i) { document.getElementById('photo' + i).value = u; });
  }
  function clear() { for (var i = 0; i < ${photos.COUNT}; i++) document.getElementById('photo' + i).value = ''; }

  // From Instagram: tap three, in order; each is fetched through this form and
  // shrunk like a photo from the phone.
  var ig = document.getElementById('ig'), chosen = [];
  if (ig) {
    var count = document.getElementById('igcount');
    ig.querySelectorAll('img').forEach(function (img) {
      img.addEventListener('error', function () {
        img.parentNode.remove();
        if (!ig.children.length) document.getElementById('igbox').remove();
      });
    });
    ig.addEventListener('click', function (e) {
      var b = e.target.closest('.igp');
      if (!b) return;
      var at = chosen.indexOf(b);
      if (at >= 0) chosen.splice(at, 1);
      else if (chosen.length < ${photos.COUNT}) chosen.push(b);
      ig.querySelectorAll('.igp').forEach(function (x) {
        var n = chosen.indexOf(x);
        x.setAttribute('aria-pressed', n >= 0 ? 'true' : 'false');
        x.querySelector('b').textContent = n >= 0 ? n + 1 : '';
      });
      clear();
      count.textContent = chosen.length < ${photos.COUNT} ? 'tap ' + (${photos.COUNT} - chosen.length) + ' more' : 'ready';
      if (chosen.length < ${photos.COUNT}) return;
      pick.value = ''; thumbs.textContent = ''; pick.removeAttribute('required');
      Promise.all(chosen.map(function (x) { return fetch(x.dataset.src).then(function (r) { if (!r.ok) throw r; return r.blob(); }).then(shrink); }))
        .then(useAll, function () { count.textContent = "couldn't get those: try others"; });
    });
  }

  pick.addEventListener('change', function () {
    var files = Array.prototype.slice.call(pick.files, 0, ${photos.COUNT});
    thumbs.textContent = '';
    if (ig) { chosen = []; ig.querySelectorAll('.igp').forEach(function (x) { x.setAttribute('aria-pressed', 'false'); x.querySelector('b').textContent = ''; }); }
    for (var i = 0; i < ${photos.COUNT}; i++) document.getElementById('photo' + i).value = '';
    if (files.length && files.length < ${photos.COUNT}) { pick.setCustomValidity('Choose ${photos.COUNT} photos.'); pick.reportValidity(); return; }
    pick.setCustomValidity('');
    Promise.all(files.map(shrink)).then(function (urls) {
      urls.forEach(function (u, i) {
        document.getElementById('photo' + i).value = u;
        var t = document.createElement('img'); t.src = u; t.alt = 'Photo ' + (i + 1); thumbs.appendChild(t);
      });
    }, function () { pick.setCustomValidity("One of those photos couldn't be read. Try others."); pick.reportValidity(); });
  });
  form.addEventListener('submit', function (e) {
    var ready = document.getElementById('photo${photos.COUNT - 1}').value;
    if ((pick.files.length || chosen.length) && !ready) { e.preventDefault(); pick.setCustomValidity('Choose ${photos.COUNT} photos.'); pick.reportValidity(); pick.setCustomValidity(''); }
  });

  // The age range: two handles on one track, kept apart, 60 shown as 60+.
  var lo = form.ageMin, hi = form.ageMax, out = document.getElementById('agesOut'), fill = document.getElementById('agesFill');
  function ages(e) {
    if (+lo.value > +hi.value) { if (e && e.target === lo) lo.value = hi.value; else hi.value = lo.value; }
    var span = lo.max - lo.min, a = (lo.value - lo.min) / span * 100, b = (hi.value - lo.min) / span * 100;
    fill.style.left = a + '%'; fill.style.width = (b - a) + '%';
    out.textContent = lo.value + ' to ' + (+hi.value >= +hi.max ? hi.max + '+' : hi.value);
  }
  lo.addEventListener('input', ages); hi.addEventListener('input', ages); ages();

  // Anything else: one more row at a time, up to ${WISH_MAX}.
  var wishes = document.getElementById('wishes'), more = document.getElementById('more');
  more.hidden = false;
  more.addEventListener('click', function () {
    var n = wishes.children.length;
    if (n >= ${WISH_MAX}) return;
    var row = wishes.children[n - 1].cloneNode(true);
    row.querySelectorAll('input').forEach(function (el) {
      el.name = el.name.replace(/\\d+$/, n);
      if (el.type === 'text') { el.value = ''; el.placeholder = 'Something else'; } else el.checked = el.value === 'nice';
    });
    wishes.appendChild(row);
    row.querySelector('input[type=text]').focus();
    if (n + 1 >= ${WISH_MAX}) more.hidden = true;
  });
})();
</script>`;

const STYLE = `<style>
form{display:grid;gap:14px;margin-top:16px}
.sec{background:var(--alt);border:1px solid var(--line);border-radius:22px;padding:18px 16px;display:grid;gap:18px}
.sec h2{display:flex;align-items:center;gap:10px;font-size:1.05rem;margin:0}
.sec h2 b{display:inline-grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--accent-soft);color:var(--accent);font-size:.85rem;flex:none}
.sec h2 small{font-weight:400;color:var(--soft);font-size:.85rem;margin-left:auto}
.q{display:grid;gap:8px}
.q>p{margin:0;font-weight:600;font-size:.95rem}
.hint{margin:-6px 0 0;color:var(--soft);font-size:.88rem}
.sec input[type=text],.sec input[type=number],.sec select{background:var(--bg)}
.opts{display:flex;flex-wrap:wrap;gap:8px}
.opt input,.seg input,.pick input{position:absolute;opacity:0;width:1px;height:1px}
.opt span{display:inline-block;padding:.5rem .9rem;border-radius:999px;border:1.5px solid var(--line);cursor:pointer;font-size:.95rem}
.opt input:checked+span{background:var(--accent);border-color:var(--accent);color:#fff}
.opt input:focus-visible+span,.seg input:focus-visible+span{outline:2px solid var(--accent);outline-offset:2px}
.seg{display:inline-flex;background:var(--bg);border:1.5px solid var(--line);border-radius:999px;padding:3px;gap:2px;justify-self:start}
.seg span{display:inline-block;padding:.32rem .8rem;border-radius:999px;cursor:pointer;font-size:.85rem;color:var(--soft);font-weight:600}
.seg input:checked+span{background:var(--accent-soft);color:var(--accent)}
.seg input[value=must]:checked+span{background:var(--accent);color:#fff}
.sub{display:flex;align-items:center;gap:10px;flex-wrap:wrap;font-size:.85rem;color:var(--soft)}
.age{max-width:6.5rem}
select{width:100%;font:inherit;padding:.7rem .8rem;border-radius:12px;border:1.5px solid var(--line);color:var(--ink)}
.pick span{display:block;text-align:center;padding:.8rem;border:1.5px dashed var(--accent);border-radius:14px;color:var(--accent);font-weight:600;cursor:pointer}
.ig{display:grid;grid-template-columns:repeat(4,1fr);gap:6px}
.igp{position:relative;padding:0;border:0;border-radius:10px;overflow:hidden;background:var(--accent-soft);aspect-ratio:1;width:auto}
.igp img{width:100%;height:100%;object-fit:cover;display:block}
.igp[aria-pressed=true]{outline:3px solid var(--accent);outline-offset:-3px}
.igp b{position:absolute;top:5px;right:5px;width:22px;height:22px;border-radius:50%;background:var(--accent);color:#fff;font-size:.8rem;display:none;place-items:center}
.igp[aria-pressed=true] b{display:grid}
details.more>summary,details.sum>summary{list-style:none;cursor:pointer;display:flex;align-items:center;gap:10px}
details>summary::-webkit-details-marker{display:none}
details.sum>summary{justify-content:space-between;font-weight:600}
.edit{color:var(--accent);font-weight:600;font-size:.9rem}
details[open] .edit{display:none}
details.sum[open]>summary{margin-bottom:14px}
details.more>summary h2{flex:1}
details.more>summary::after{content:'+';font-size:1.4rem;color:var(--accent);line-height:1}
details.more[open]>summary::after{content:'\\2212'}
details.more[open]>summary{margin-bottom:18px}
.inner{display:grid;gap:18px}
.thumbs{display:flex;gap:8px}.thumbs:empty{display:none}.thumbs img{width:32%;aspect-ratio:4/5;object-fit:cover;border-radius:12px}
.range{position:relative;height:34px}
.range .track{position:absolute;left:0;right:0;top:15px;height:6px;border-radius:6px;background:var(--line)}
.range .track i{position:absolute;top:0;bottom:0;border-radius:6px;background:var(--accent)}
.range input{position:absolute;left:0;top:0;width:100%;height:34px;margin:0;padding:0;border:0;background:none;-webkit-appearance:none;appearance:none;pointer-events:none}
.range input::-webkit-slider-thumb{-webkit-appearance:none;pointer-events:auto;width:26px;height:26px;border-radius:50%;background:#fff;border:3px solid var(--accent);box-shadow:0 1px 4px rgba(0,0,0,.2);cursor:pointer}
.range input::-moz-range-thumb{pointer-events:auto;width:20px;height:20px;border-radius:50%;background:#fff;border:3px solid var(--accent);cursor:pointer}
.range input::-moz-range-track{background:none}
.rangeval{margin:0;font-weight:700;color:var(--accent)}
.ends{display:flex;justify-content:space-between;font-size:.8rem;color:var(--soft);margin-top:-4px}
.wishes{display:grid;gap:12px}
.wish{display:grid;gap:6px}
.add{background:none;color:var(--accent);border:1.5px dashed var(--line);padding:.6rem;font-size:.95rem}
.err{color:#b3261e;font-weight:600;margin:12px 0 0}
</style>`;

function form(user, token, problem, now = Date.now()) {
  const d = user.draft || user.profile || { basics: {}, traits: {} };
  const b = d.basics || {};
  const prefs = user.prefs || {};
  const seeking = b.seeking || [];
  const age = b.age || '';
  const lo = b.ageMin || (age ? Math.max(18, age - 5) : 25);
  const hi = Math.min(60, b.ageMax || (age ? age + 5 : 35));
  const importance = statedOf(d, 'future.religionImportance') || 3;
  const wishes = wishesOf(prefs.brief);
  const sec = (n, title, inner, note) => `<section class="sec"><h2><b>${n}</b>${esc(title)}${note ? `<small>${esc(note)}</small>` : ''}</h2>${inner}</section>`;
  const q = (label, inner) => `<div class="q"><p>${esc(label)}</p>${inner}</div>`;
  // What Muse already has (from their Meta account or the chat) folds into one
  // line to check; what's optional folds away until they want it.
  const known = Boolean(age && b.gender && b.city);
  const fold = (cls, open, head, inner) => `<details class="${cls}"${open ? ' open' : ''}><summary>${head}</summary><div class="inner">${inner}</div></details>`;
  const kids = statedOf(d, 'future.kids'), marriage = statedOf(d, 'future.marriage');
  const aboutYou =
    q('Age', `<input class="age" type="number" name="age" min="18" max="99" inputmode="numeric" value="${esc(age)}" required>`) +
    q('You are', radios('gender', GENDERS, LABELS.gender, b.gender)) +
    q('Your city', `<input type="text" name="city" maxlength="60" value="${esc(b.city || '')}" placeholder="e.g. Singapore" required>`) +
    `<p class="hint">You're matched with people in the same city.</p>`;
  const body =
    `<h1>A few details for your matches</h1><p class="muted" style="margin:.4rem 0 0">Under a minute. These are only ever asked, never guessed, and only the people you match with see your card.</p>` +
    (problem ? `<p class="err">${esc(problem)}</p>` : '') +
    `<form method="post" action="/pair/form/${esc(token)}">` +
    sec(1, 'Your photos', photoField(user, token, now), '3, required') +
    (known
      ? `<section class="sec">${fold('sum', false, `<span>${esc(age)} · ${esc(LABELS.gender[b.gender])} · ${esc(b.city)}</span><span class="edit">Edit</span>`, aboutYou)}</section>`
      : sec(2, 'About you', aboutYou)) +
    sec(known ? 2 : 3, "Who you'd like to meet",
      q('Interested in', `<div class="opts">${GENDERS.map(g => `<label class="opt"><input type="checkbox" name="seeking" value="${g}"${seeking.includes(g) ? ' checked' : ''}><span>${LABELS.seeking[g]}</span></label>`).join('')}</div>`) +
      q('Ages', `<p class="rangeval" id="agesOut">${esc(lo)} to ${hi >= 60 ? '60+' : esc(hi)}</p>` +
        `<div class="range"><div class="track"><i id="agesFill"></i></div>` +
        `<input type="range" name="ageMin" min="18" max="60" value="${esc(lo)}" aria-label="Youngest">` +
        `<input type="range" name="ageMax" min="18" max="60" value="${esc(hi)}" aria-label="Oldest"></div><div class="ends"><span>18</span><span>60+</span></div>`) +
      q("What you're after", radios('intent', INTENTS, LABELS.intent, b.intent))) +
    sec(known ? 3 : 4, 'Your religion',
      `<select name="religion" required aria-label="Your religion"><option value="">Choose…</option>${RELIGIONS.map(r => `<option value="${esc(r)}"${r === statedOf(d, 'future.religion') ? ' selected' : ''}>${esc(RELIGION_LABEL(r))}</option>`).join('')}</select>` +
      `<div class="sub">How much it matters in a partner</div><div class="opts">${[1, 2, 3, 4, 5].map(n => `<label class="opt"><input type="radio" name="religionImportance" value="${n}"${n === importance ? ' checked' : ''}><span>${n === 1 ? '1 · not at all' : n === 5 ? '5 · central' : n}</span></label>`).join('')}</div>`) +
    `<section class="sec">${fold('more', Boolean(kids || marriage || wishes.length), `<h2><b>${known ? 4 : 5}</b>Kids, marriage and more<small>optional</small></h2>`,
      q('Kids', radios('kids', FIELDS['future.kids'].options, LABELS.kids, kids, false) +
        `<div class="sub">A partner who fits this is ${matters('kidsMatters', kindOf(prefs, 'future.kids'))}</div>`) +
      q('Marriage', radios('marriage', FIELDS['future.marriage'].options, LABELS.marriage, marriage, false) +
        `<div class="sub">A partner who fits this is ${matters('marriageMatters', kindOf(prefs, 'future.marriage'))}</div>`) +
      q('Anything else in a partner?', `<p class="hint" style="margin:0">A few words each.</p><div class="wishes" id="wishes">${(wishes.length ? wishes : [undefined]).slice(0, WISH_MAX).map((w, i) => wishRow(i, w)).join('')}</div>` +
        `<button type="button" class="add" id="more" hidden>+ Add another</button>`))}</section>` +
    `<button type="submit">Save and go back to Muse</button></form>` + STYLE + PHOTO_SCRIPT;
  return theme.page('Your Psyche Pair details', body);
}

const done = () => theme.page('Saved', '<h1>Saved</h1><p>Go back to Muse and tap <b>Done</b>: your Psyche Pair card is next.</p>');
const expired = () => theme.page('This link has expired', '<h1>This link has expired</h1><p>Go back to Muse and ask for the form again, or answer there instead.</p>');

/** GET /pair/form/<token> */
function show(token, now = Date.now()) {
  const user = userOf(token, now);
  if (!user) return { status: 410, html: expired() };
  return { status: 200, html: form(user, token, null, now) };
}

/** POST /pair/form/<token>: every answer saved as stated, or the form again with what to fix. */
async function submit(token, params, now = Date.now()) {
  const user = userOf(token, now);
  if (!user) return { status: 410, html: expired() };
  const draft = JSON.parse(JSON.stringify(user.draft || user.profile || { basics: {}, traits: {} }));
  draft.basics = draft.basics || {};
  draft.traits = draft.traits || {};
  const int = k => Number.parseInt(params.get(k), 10);
  const one = (k, options) => (options.includes(params.get(k)) ? params.get(k) : null);
  const age = int('age');
  // The slider's top end, 60, means 60 and over; handles that crossed are swapped.
  let [ageMin, ageMax] = [int('ageMin'), int('ageMax')].sort((x, y) => x - y);
  if (ageMax >= 60) ageMax = 99;
  const city = String(params.get('city') || '').replace(/\s+/g, ' ').trim().slice(0, 60);
  const seeking = params.getAll('seeking').filter(g => GENDERS.includes(g));
  const fields = {
    gender: one('gender', GENDERS), intent: one('intent', INTENTS), religion: one('religion', RELIGIONS),
    kids: one('kids', FIELDS['future.kids'].options),
    marriage: one('marriage', FIELDS['future.marriage'].options),
  };
  const importance = int('religionImportance');
  const wishes = [];
  for (let i = 0; i < WISH_MAX; i++) {
    const text = String(params.get('wish' + i) || '').replace(/[;.]+/g, ',').replace(/\s+/g, ' ').replace(/^[\s,]+|[\s,]+$/g, '').slice(0, WISH_CHARS);
    if (text) wishes.push({ text, must: params.get('wishMust' + i) === 'must' });
  }
  const brief = briefOf(wishes);
  let problem = null;
  if (!(age >= 18 && age <= 99)) problem = 'Add your age (18 or over).';
  else if (!fields.gender) problem = 'Choose how you describe yourself.';
  else if (!city) problem = 'Add your city.';
  else if (!seeking.length) problem = "Choose who you'd like to meet.";
  else if (!(ageMin >= 18 && ageMax <= 99 && ageMin <= ageMax)) problem = 'Check the age range.';
  else if (!fields.intent) problem = "Choose what you're after.";
  else if (!fields.religion) problem = 'Choose your religion, or "prefer not to say".';
  else if (brief.length > 400) problem = 'Make the things you\'re looking for a little shorter.';
  const chosen = Array.from({ length: photos.COUNT }, (_, i) => photos.fromDataUrl(params.get('photo' + i)));
  const newPhotos = chosen.every(Boolean);
  if (!problem && !newPhotos && photos.countOf(user) < photos.COUNT) {
    problem = chosen.some(Boolean) || params.get('photo0') ? `Choose ${photos.COUNT} photos (JPEG or PNG; each is made smaller for you).` : `Add ${photos.COUNT} photos of you.`;
  }
  if (problem) return { status: 400, html: form(user, token, problem, now) };
  if (newPhotos) {
    const saved = await photos.save(user.id, chosen, now);
    if (saved.error) return { status: 400, html: form(user, token, saved.error, now) };
  }

  // Psyche Pair is for dating unless they're after new friends (basics.mode).
  Object.assign(draft.basics, { age, gender: fields.gender, city, seeking, ageMin, ageMax, intent: fields.intent, mode: fields.intent === 'friends' ? 'friends' : 'dating' });
  // Their character, now that their gender is known: their Psyche Card's, if it's
  // open to them (a card drawn before this fell back to one open to anyone).
  const open = characters.allowedFor(fields.gender);
  const fromCard = (psyche.card(user.id, now) || {}).character;
  const current = draft.character && draft.character.name;
  if (fromCard && open.includes(fromCard) && fromCard !== current) {
    draft.character = { name: fromCard, why: shortWhy((psyche.card(user.id, now) || {}).why) };
  } else if (current && !open.includes(current)) delete draft.character;
  const stated = value => ({ value, source: 'stated', confidence: 0.9 });
  draft.traits['future.religion'] = stated(fields.religion);
  if (importance >= 1 && importance <= 5) draft.traits['future.religionImportance'] = stated(importance);
  for (const [k, key] of [['kids', 'future.kids'], ['marriage', 'future.marriage']]) {
    if (fields[k]) draft.traits[key] = stated(fields[k]);
  }
  const { profile } = validateProfile(draft);
  // Kids and marriage become rules here, good to have (nice) or a must; the
  // rest of their list stays as the brief, for Muse to turn into rules.
  const old = user.prefs || {};
  const rules = { must: (old.must || []).filter(r => !FORM_RULES.includes(r.field)), nice: (old.nice || []).filter(r => !FORM_RULES.includes(r.field)) };
  for (const [k, field] of [['kids', 'future.kids'], ['marriage', 'future.marriage']]) {
    const fits = FITS[field][fields[k]];
    if (fits) rules[params.get(k + 'Matters') === 'must' ? 'must' : 'nice'].push({ field, op: 'in', value: fits });
  }
  const { prefs } = validatePreferences({ brief, ...rules });
  store.updateUser(user.id, { draft: profile, prefs, pairFormAt: now });
  store.kvDel('igpick', user.id);
  return { status: 200, html: done() };
}

module.exports = { TTL_MS, link, show, submit, offerInstagram, igPhoto };
