// Cards as images, for the host's chat, drawn to look like PsycheAI's own
// Psyche Card: the same palette, the purple-to-pink hero with the character's
// scene, white panels with spaced uppercase labels and line icons, numbered
// lists, pills, and the ring in the corner. The scenes, icons, brand mark and
// tokens are PsycheAI's (assets/psycheai.json, from tools/sync-psycheai.mjs).
//
// Two layouts:
//   psyche   the full Psyche Card, 1080×1920: what "Your Psyche is ready"
//            shows beside the link. The ring is their confidence score.
//   match    the first look at someone (and your own card in the Psyche Pair
//            review), 1080×1350, sized for a chat bubble: the same hero with
//            their photo on the right, their patterns and what drives them,
//            and the "you two both…" line. The ring is the fit.
//
// Rendered with resvg and the bundled Inter (assets/fonts, SIL OFL). Photos
// are fetched at render time and embedded; without one, the character's scene
// stands in.

const fs = require('node:fs');
const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');
const P = require('../assets/psycheai.json');
const characters = require('./characters');

const FONT_DIR = path.join(__dirname, '..', 'assets', 'fonts');
const FONTS = ['Inter_400Regular.ttf', 'Inter_600SemiBold.ttf', 'Inter_700Bold.ttf', 'Inter-SemiBoldItalic.otf'].map(f => path.join(FONT_DIR, f));

// The card's emoji, as psycheai.io's card shows them (docs/copy.js CARD_ICONS
// and LOVE_LANGUAGE_ICONS), drawn from Noto Color Emoji (Apache-2.0,
// assets/emoji/LICENSE): resvg can't draw a colour emoji font, so each is a
// small picture.
const EMOJI_FILES = { '🧭': 'compass', '📊': 'chart', '⚖️': 'scales', '💡': 'bulb', '✨': 'sparkles', '💝': 'heartgift', '🎁': 'gift', '🤝': 'handshake',
  '🎯': 'target', '🧵': 'thread', '🧲': 'magnet', '💬': 'speech', '🛠️': 'tools', '⏳': 'hourglass', '🫂': 'hug', '💗': 'heart' };
const EMOJI = Object.fromEntries(Object.entries(EMOJI_FILES).map(([e, f]) =>
  [e, 'data:image/png;base64,' + fs.readFileSync(path.join(__dirname, '..', 'assets', 'emoji', f + '.png')).toString('base64')]));
const emoji = (e, x, y, size) => (EMOJI[e] ? `<image href="${EMOJI[e]}" x="${x}" y="${y}" width="${size}" height="${size}"/>` : '');
const LOVE_ICONS = { 'Words of affirmation': '💬', 'Acts of service': '🛠️', 'Quality time': '⏳', 'Receiving gifts': '🎁', 'Giving gifts': '🎁', 'Physical touch': '🫂' };

const T = P.tokens;
const C = { bg: T.bg, ink: T.ink, soft: T.inkSoft, line: T.line, accent: T.accent, accent2: T.accent2, accentSoft: T.accentSoft, white: '#ffffff' };

const esc = s => String(s == null ? '' : s).replace(/[&<>"']/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&apos;' }[ch]));
// Sentence case, as the Psyche Card prints them: "Self-direction", "Words of affirmation".
const cap = s => String(s || '').replace(/^\s*\w/, m => m.toUpperCase());

/** Break text into at most maxLines lines of about width px, ellipsis on overflow. */
function wrap(text, size, width, maxLines) {
  const perLine = Math.max(8, Math.floor(width / (size * 0.53)));
  const words = String(text || '').split(/\s+/).filter(Boolean);
  const out = [];
  let line = '';
  for (const w of words) {
    if ((line + ' ' + w).trim().length <= perLine) line = (line + ' ' + w).trim();
    else { if (line) out.push(line); line = w; }
  }
  if (line) out.push(line);
  if (out.length > maxLines) {
    out.length = maxLines;
    out[maxLines - 1] = out[maxLines - 1].replace(/\s*\S*$/, '') + '…';
  }
  return out;
}
const textWidth = (s, size, weight = 400) => String(s).length * size * (weight >= 600 ? 0.6 : 0.55);

// The real width of a line in Inter, measured by resvg: the estimate above runs
// about 20% wide, which drew pills longer than their words and past the panel.
const measured = new Map();
function measure(s, size, weight = 400) {
  const key = size + '|' + weight + '|' + s;
  if (!measured.has(key)) {
    let w;
    try {
      const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="4000" height="${size * 2}"><text x="0" y="${size * 1.4}" font-size="${size}" font-weight="${weight}">${esc(s)}</text></svg>`;
      const box = new Resvg(svg, { font: { fontFiles: FONTS, loadSystemFonts: false, defaultFontFamily: 'Inter' } }).getBBox();
      w = box ? box.width : textWidth(s, size, weight);
    } catch { w = textWidth(s, size, weight); }
    if (measured.size > 2000) measured.clear();
    measured.set(key, w);
  }
  return measured.get(key);
}

/** Lines of at most width px, by measured width, breaking at spaces. */
function wrapMeasured(text, size, weight, width) {
  const out = [];
  let line = '';
  for (const w of String(text || '').split(/\s+/).filter(Boolean)) {
    const next = line ? line + ' ' + w : w;
    if (line && measure(next, size, weight) > width) { out.push(line); line = w; } else line = next;
  }
  if (line) out.push(line);
  return out;
}
const lines = (list, x, y, size, lh, attrs) => list.map((l, i) => `<text x="${x}" y="${y + i * lh}" font-size="${size}" ${attrs}>${esc(l)}</text>`).join('');
const spaced = (s, size, x, y, attrs) => `<text x="${x}" y="${y}" font-size="${size}" letter-spacing="${(size * 0.18).toFixed(1)}" ${attrs}>${esc(String(s).toUpperCase())}</text>`;

let uid = 0;

// ---------- pieces ----------

function defs() {
  return `<linearGradient id="pc-bg" x1="0" y1="0" x2="0.3" y2="1"><stop offset="0" stop-color="#fbf1f6"/><stop offset="1" stop-color="#ece2f5"/></linearGradient>` +
    `<linearGradient id="pc-hero" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="${C.accent}"/><stop offset="1" stop-color="${C.accent2}"/></linearGradient>` +
    `<linearGradient id="pc-fade" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${C.accent}" stop-opacity="1"/><stop offset="0.55" stop-color="${C.accent}" stop-opacity="0.35"/><stop offset="1" stop-color="${C.accent}" stop-opacity="0"/></linearGradient>`;
}

function brand(x, y, size = 30) {
  const s = size / P.brand.viewBox * 1.25;
  return `<g transform="translate(${x},${y - size * 0.95}) scale(${s.toFixed(4)})" fill="none" stroke="${C.accent}" stroke-width="${P.brand.strokeWidth}">` +
    P.brand.paths.map(d => `<path d="${d}"/>`).join('') + `</g>` +
    `<text x="${x + size * 1.5}" y="${y}" font-size="${size}" font-weight="700" fill="${C.ink}">PsycheAI</text>`;
}

function ring(cx, cy, r, value, label) {
  const v = Math.max(0, Math.min(100, Number(value) || 0));
  const circ = 2 * Math.PI * r;
  return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="${C.white}" stroke="${C.accentSoft}" stroke-width="7"/>` +
    `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${C.accent}" stroke-width="7" stroke-linecap="round" ` +
    `stroke-dasharray="${(circ * v / 100).toFixed(1)} ${circ.toFixed(1)}" transform="rotate(-90 ${cx} ${cy})"/>` +
    `<text x="${cx}" y="${cy + (label ? 3 : 10)}" font-size="${label ? 24 : 28}" font-weight="700" fill="${C.ink}" text-anchor="middle">${esc(v + (label ? '%' : ''))}</text>` +
    (label ? `<text x="${cx}" y="${cy + 22}" font-size="14" font-weight="600" fill="${C.soft}" text-anchor="middle">${esc(label)}</text>` : '');
}

function scene(character, x, y, w, h, clipId) {
  const art = P.art[character];
  if (!art) return '';
  const id = 'a' + (++uid);
  // Clipped by a group around it: a clip-path on the nested <svg> itself would
  // be read in the scene's own coordinates and cut it in the wrong place.
  return `<g clip-path="url(#${clipId})"><svg x="${x}" y="${y}" width="${w}" height="${h}" viewBox="0 0 520 440" preserveAspectRatio="xMaxYMid slice">${art.replace(/\{id\}/g, id)}</svg></g>`;
}

function avatar(character, cx, cy, r) {
  const art = P.art[character];
  const id = 'v' + (++uid);
  const crop = P.crops[character] || '220 20 300 300';
  return `<clipPath id="${id}-c"><circle cx="${cx}" cy="${cy}" r="${r}"/></clipPath>` +
    `<circle cx="${cx}" cy="${cy}" r="${r}" fill="url(#pc-hero)"/>` +
    (art ? `<g clip-path="url(#${id}-c)"><svg x="${cx - r}" y="${cy - r}" width="${2 * r}" height="${2 * r}" viewBox="${crop}" preserveAspectRatio="xMidYMid slice">${art.replace(/\{id\}/g, id)}</svg></g>` : '') +
    `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="${C.white}" stroke-width="4"/>`;
}

function panel(x, y, w, h, label, icon) {
  const glyph = P.icons[icon] || '';
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="24" fill="${C.white}" stroke="${C.line}" stroke-width="2"/>` +
    `<circle cx="${x + 44}" cy="${y + 48}" r="20" fill="${C.accentSoft}"/>` +
    (EMOJI[icon] ? emoji(icon, x + 30, y + 34, 28) : glyph ? `<g transform="translate(${x + 32},${y + 36})" fill="none" stroke="${C.accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${glyph}</g>` : '') +
    spaced(label, 21, x + 76, y + 56, `font-weight="600" fill="${C.soft}"`);
}

function numbered(items, x, y, step, { filled = true, size = 29 } = {}) {
  return items.map((t, i) => {
    const cy = y + i * step;
    return `<circle cx="${x + 20}" cy="${cy - 10}" r="20" fill="${filled ? C.accent : C.accentSoft}"/>` +
      `<text x="${x + 20}" y="${cy - 1}" font-size="22" font-weight="700" fill="${filled ? C.white : C.accent}" text-anchor="middle">${i + 1}</text>` +
      fitLine(t, size, 600, 390, x + 56, cy, `fill="${C.ink}"`);
  }).join('');
}

// One line that fits its width: set smaller (down to 22) before it's cut, so
// a long pattern name ("Warm connector, sharp debater") is read whole.
function fitLine(text, size, weight, width, x, y, attrs) {
  let t = String(text || ''), s = size;
  while (s > 22 && measure(t, s, weight) > width) s--;
  while (measure(t, s, weight) > width && /\s/.test(t)) t = t.replace(/\s+\S+$/, '').replace(/[,;:]$/, '') + '…';
  return `<text x="${x}" y="${y}" font-size="${s}" font-weight="${weight}" ${attrs}>${esc(t.replace(/…+/g, '…'))}</text>`;
}

// Pills that stay inside their panel: a pill wider than the panel is cut at
// a word with an ellipsis, and a pill that would start a row past maxRows is
// skipped for the next one that fits (a long value or interest overflowed the panel's edge and bottom).
function fitPill(text, size, maxW) {
  let t = String(text || '').trim();
  while (measure(t, size, 600) + 36 > maxW && /\s/.test(t)) t = t.replace(/\s+\S+$/, '').replace(/[,;:]$/, '') + '…';
  while (measure(t, size, 600) + 36 > maxW && t.length > 2) t = t.replace(/.…?$/, '') + '…';
  return t.replace(/…+/g, '…').replace(/(\S)…/, '$1…');
}

function pills(items, x, y, maxW, { size = 27, maxRows = 2, gap = 61 } = {}) {
  let cx = x, cy = y, row = 1;
  const out = [];
  for (const item of items) {
    const t = fitPill(item, size, maxW);
    const w = measure(t, size, 600) + 36;
    if (cx + w > x + maxW && cx > x) {
      if (row === maxRows) continue; // a shorter one after it may still fit
      cx = x; cy += gap; row++;
    }
    out.push(`<rect x="${cx}" y="${cy - size - 6}" width="${w}" height="${size + 22}" rx="${(size + 22) / 2}" fill="${C.accentSoft}"/>` +
      `<text x="${cx + 18}" y="${cy + 2}" font-size="${size}" font-weight="600" fill="${C.accent}">${esc(t)}</text>`);
    cx += w + 12;
  }
  return out.join('');
}

// ---------- the full Psyche Card ----------

// psycheai.io's story card (docs/styles.css .pc-story), drawn the same way: a
// 1080×1920 canvas with 56/60 px of padding, the top row, the hero, then
// pairs of panels, each as tall as what's in it, 18 px apart, and the
// signature at the foot. Nothing is cut or left out to fit a box: like the
// site, when the whole runs past the canvas it is scaled down just enough.
const S = { pad: 60, top: 56, foot: 44, gap: 18, col: 20, text: 27, label: 22, panelPad: [22, 28], heroPad: [38, 42] };

// A white panel with its icon and spaced label; the body starts at y + head.
function sPanel(x, y, w, h, label, icon) {
  const glyph = P.icons[icon] || '';
  const ly = y + S.panelPad[0] + 26;
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="28" fill="${C.white}" stroke="${C.line}" stroke-width="1.5"/>` +
    `<circle cx="${x + S.panelPad[1] + 17}" cy="${ly - 8}" r="17" fill="${C.accentSoft}"/>` +
    (EMOJI[icon] ? emoji(icon, x + S.panelPad[1] + 5, ly - 20, 24) : glyph ? `<g transform="translate(${x + S.panelPad[1] + 5},${ly - 20})" fill="none" stroke="${C.accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${glyph}</g>` : '') +
    spaced(label, S.label, x + S.panelPad[1] + 48, ly, `font-weight="700" fill="${C.soft}"`);
}
const HEAD = S.panelPad[0] + 26 + 22;   // label row and the 12 px under it, to the first line's top

// A numbered list (.pc-spatterns / .pc-smotives): 42 px discs, names wrapping
// beside them rather than shrinking or being cut. Returns { svg, h }.
function sNumbered(items, x, y, w, filled) {
  const lh = Math.round(S.text * 1.25), o = [];
  let cy = y;
  items.forEach((t, i) => {
    const ls = wrapMeasured(t, S.text, 700, w - 58);
    const h = Math.max(42, ls.length * lh);
    o.push(`<circle cx="${x + 21}" cy="${cy + h / 2}" r="21" fill="${filled ? C.accent : C.accentSoft}"/>` +
      `<text x="${x + 21}" y="${cy + h / 2 + 8}" font-size="22" font-weight="700" fill="${filled ? C.white : C.accent}" text-anchor="middle">${i + 1}</text>` +
      ls.map((l, j) => `<text x="${x + 58}" y="${cy + h / 2 - (ls.length * lh) / 2 + (j + 1) * lh - 7}" font-size="${S.text}" font-weight="700" fill="${C.ink}">${esc(l)}</text>`).join(''));
    cy += h + 12;
  });
  return { svg: o.join(''), h: items.length ? cy - 12 - y : 0 };
}

// Chips (.pc-schips): 26 px, every one shown, a long phrase wrapping inside its chip.
function sChips(items, x, y, w) {
  const size = 26, padX = 18, padY = 10, lh = Math.round(size * 1.2), gap = 10, o = [];
  let cx = x, cy = y, rowH = 0;
  for (const item of items) {
    const text = String(item || '').trim();
    if (!text) continue;
    const ls = measure(text, size, 600) + 2 * padX > w ? wrapMeasured(text, size, 600, w - 2 * padX) : [text];
    const cw = Math.max(...ls.map(l => measure(l, size, 600))) + 2 * padX;
    const ch = ls.length * lh + 2 * padY;
    if (cx + cw > x + w && cx > x) { cx = x; cy += rowH + gap; rowH = 0; }
    o.push(`<rect x="${cx}" y="${cy}" width="${cw.toFixed(0)}" height="${ch}" rx="14" fill="${C.accentSoft}"/>` +
      ls.map((l, i) => `<text x="${cx + padX}" y="${cy + padY + (i + 1) * lh - 7}" font-size="${size}" font-weight="600" fill="${C.accent}">${esc(l)}</text>`).join(''));
    cx += cw + gap;
    rowH = Math.max(rowH, ch);
  }
  return { svg: o.join(''), h: o.length ? cy + rowH - y : 0 };
}

// The Psyche Card, and (pair) the Psyche Pair card in the same design: the
// same hero, character and panels, with what a match needs in place of what
// only the user should see. Pair: their name and age up top with the fit;
// "Looking for" in place of the Big Five (a stranger is never shown a
// sensitivity score: cards are positive or neutral); and "You two" in place
// of "Most in sync with" once there's a line about the pair.
function psycheSvg(card, { pair = false } = {}) {
  const W = 1080, H = 1920, X = S.pad, CW = W - 2 * S.pad, PW = (CW - S.col) / 2, L = X, R = X + PW + S.col;
  const inner = PW - 2 * S.panelPad[1];
  const o = [];
  let y = S.top;

  // The top row: brand, whose card, and the ring.
  o.push(brand(X, y + 58, 30));
  const who = pair ? String(card.firstName || '') + (card.age ? ', ' + card.age : '') : (card.fullName || card.firstName);
  o.push(`<text x="${W / 2}" y="${y + 59}" font-size="32" font-weight="700" fill="${C.ink}" text-anchor="middle">${esc(who)}</text>`);
  if (pair && typeof card.fit === 'number') o.push(ring(X + CW - 46, y + 48, 40, card.fit, 'fit'));
  else if (!pair && typeof card.confidence === 'number') o.push(ring(X + CW - 46, y + 48, 40, card.confidence));
  y += 96 + S.gap;

  // The hero: kicker, name, headline and the whole write-up, in a column left
  // of the character's scene, as tall as it needs to be.
  const TX = X + S.heroPad[1], TW = 560;
  const kicker = !card.characterName ? (card.stage === 'self' ? 'How matches see you' : 'Psyche Pair')
    : pair ? (card.stage === 'self' ? 'How matches see you · most like' : 'Most like') : 'You are most like';
  const name = String(card.characterName || (card.character || '').split(' · ')[0] || card.firstName || '');
  const hl = card.headline ? wrapMeasured(card.headline, 34, 600, TW) : [];
  const why = pair ? (card.writeUp || card.characterWhy) : card.why;
  const blurb = why ? wrapMeasured(why, 26, 400, TW) : [];
  const city = pair && card.city;
  let hy = y + S.heroPad[0] + 24;
  const hero = [spaced(kicker, 24, TX, hy, `font-weight="600" fill="${C.white}" fill-opacity="0.85"`)];
  hy += 14 + 70;
  hero.push(`<text x="${TX}" y="${hy - 8}" font-size="70" font-weight="700" letter-spacing="-2" fill="${C.white}">${esc(name)}</text>`);
  if (city) { hy += 40; hero.push(`<text x="${TX}" y="${hy - 6}" font-size="28" fill="${C.white}" fill-opacity="0.9">${esc(city)}</text>`); }
  if (hl.length) { hy += 22; hero.push(lines(hl, TX, hy + 34, 34, 42, `font-weight="600" font-style="italic" fill="${C.white}"`)); hy += hl.length * 42; }
  if (blurb.length) { hy += 12; hero.push(lines(blurb, TX, hy + 27, 26, 37, `fill="${C.white}" fill-opacity="0.95"`)); hy += blurb.length * 37; }
  const heroH = Math.max(420, hy + S.heroPad[0] - y);
  o.push(`<clipPath id="hero-c"><rect x="${X}" y="${y}" width="${CW}" height="${heroH}" rx="36"/></clipPath>`,
    `<rect x="${X}" y="${y}" width="${CW}" height="${heroH}" rx="36" fill="url(#pc-hero)"/>`,
    scene(card.characterName, X + CW - 640, y, 640, heroH, 'hero-c'),
    `<rect x="${X}" y="${y}" width="680" height="${heroH}" fill="url(#pc-fade)" clip-path="url(#hero-c)"/>`, ...hero);
  y += heroH + S.gap;

  // Two panels side by side, the row as tall as the taller one.
  const row = (left, right) => {
    const h = Math.max(left.h, right ? right.h : 0) + HEAD + 2 * S.panelPad[0] - 4;
    o.push(sPanel(L, y, PW, h, left.label, left.icon), left.svg(L + S.panelPad[1], y + HEAD + S.panelPad[0] - 4));
    if (right) o.push(sPanel(R, y, PW, h, right.label, right.icon), right.svg(R + S.panelPad[1], y + HEAD + S.panelPad[0] - 4));
    y += h + S.gap;
  };
  const own = !pair || card.stage === 'self';
  const part = (label, icon, h, draw) => ({ label, icon, h, svg: draw });
  const numberedPart = (label, icon, items, filled) => part(label, icon, sNumbered(items, 0, 0, inner, filled).h, (x, yy) => sNumbered(items, x, yy, inner, filled).svg);
  row(numberedPart(own ? 'Your patterns' : 'Their patterns', '🧵', (card.patterns || []).slice(0, 3), true),
    numberedPart(own ? 'What motivates you' : 'What motivates them', '🧲', (card.motivators || []).slice(0, 3).map(cap), false));

  // MBTI letters with how firmly each was picked; the Big Five, or what they're looking for.
  const AX = { E: 'Extraversion', I: 'Introversion', N: 'Intuition', S: 'Sensing', T: 'Thinking', F: 'Feeling', J: 'Judging', P: 'Perceiving' };
  const letters = (card.letters && card.letters.length ? card.letters : String(card.mbti || '').split('').map(l => ({ letter: l }))).slice(0, 4);
  const RH = 42;
  const mbti = part('MBTI', '🧭', letters.length * RH - 8, (x, yy) => letters.map((l, i) => {
    const ly = yy + i * RH + 27;
    let out = `<text x="${x}" y="${ly}" font-size="${S.text}" font-weight="700" fill="${C.accent}">${esc(l.letter)}</text>` +
      `<text x="${x + 48}" y="${ly}" font-size="${S.text}" fill="${C.ink}">${esc(AX[l.letter] || '')}</text>`;
    if (l.strength) {
      const sw = measure(l.strength, 19, 700) + 24, clear = /^clear$/i.test(l.strength), slight = /^slight$/i.test(l.strength);
      out += `<rect x="${x + inner - sw}" y="${ly - 25}" width="${sw.toFixed(0)}" height="32" rx="16" fill="${clear ? C.accent : C.accentSoft}" ${slight ? 'fill-opacity="0.55"' : ''}/>` +
        `<text x="${x + inner - sw / 2}" y="${ly - 3}" font-size="19" font-weight="700" fill="${clear ? C.white : slight ? C.soft : C.accent}" text-anchor="middle">${esc(l.strength)}</text>`;
    }
    return out;
  }).join(''));
  let second;
  if (pair) {
    const looking = card.lookingFor ? wrapMeasured(card.lookingFor, 30, 700, inner) : [];
    const more = (card.lookingForLines || []).slice(0, 3).map(t => wrapMeasured(t, S.text - 2, 400, inner - 24));
    second = part('Looking for', '💞', looking.length * 38 + more.reduce((n, ls) => n + ls.length * 33 + 8, 0) + (looking.length && more.length ? 8 : 0), (x, yy) => {
      let ly = yy, out = '';
      if (looking.length) { out += lines(looking, x, ly + 30, 30, 38, `font-weight="700" fill="${C.accent}"`); ly += looking.length * 38 + 8; }
      for (const ls of more) { out += `<circle cx="${x + 6}" cy="${ly + 15}" r="5" fill="${C.accent}"/>` + lines(ls, x + 24, ly + 24, S.text - 2, 33, `fill="${C.ink}"`); ly += ls.length * 33 + 8; }
      return out;
    });
  } else {
    const traits = [['Openness', 'openness'], ['Conscientious', 'conscientiousness'], ['Agreeable', 'agreeableness'], ['Sensitivity', 'neuroticism']];
    second = part('Big Five', '📊', traits.length * RH - 8, (x, yy) => traits.map(([label, key], i) => {
      const v = card.bigFive && card.bigFive[key], ly = yy + i * RH + 27, bx = x + 196, bw = inner - 196 - 58;
      return `<text x="${x}" y="${ly}" font-size="${S.text - 2}" fill="${C.ink}">${label}</text>` +
        `<rect x="${bx}" y="${ly - 16}" width="${bw}" height="16" rx="8" fill="${C.accentSoft}"/>` +
        (typeof v === 'number' ? `<rect x="${bx}" y="${ly - 16}" width="${(bw * v / 100).toFixed(0)}" height="16" rx="8" fill="${C.accent}"/>` +
          `<text x="${x + inner}" y="${ly}" font-size="${S.text}" font-weight="700" fill="${C.ink}" text-anchor="end">${v}</text>` : '');
    }).join(''));
  }
  row(mbti, second);

  // Values and interests as chips, every one of them.
  const values = (card.values || []).slice(0, 4).map(cap), interests = (card.interests || []).slice(0, 5).map(cap);
  row(part('Values & beliefs', '⚖️', sChips(values, 0, 0, inner).h, (x, yy) => sChips(values, x, yy, inner).svg),
    part('Interests', '✨', sChips(interests, 0, 0, inner).h, (x, yy) => sChips(interests, x, yy, inner).svg));

  // How they show care; who they're most in sync with, or the line about the two of you.
  const love = (card.loveGiving || []).slice(0, 2).map(t => (t === 'Receiving gifts' ? 'Giving gifts' : cap(String(t).replace(/_/g, ' '))));
  const care = part('Shows care as', '🎁', love.length * 44 - 8, (x, yy) => love.map((t, i) =>
    emoji(LOVE_ICONS[t] || '💗', x, yy + i * 44, 32) + `<text x="${x + 46}" y="${yy + i * 44 + 27}" font-size="${S.text}" fill="${C.ink}">${esc(t)}</text>`).join(''));
  const youTwo = pair && (card.line || card.charactersClick);
  const syncs = (characters.SYNCS[card.characterName] || []).slice(0, 3);
  let right = null;
  if (youTwo) {
    const ls = wrapMeasured(youTwo, S.text - 1, 600, inner);
    right = part('You two', '🔗', ls.length * 34, (x, yy) => lines(ls, x, yy + 26, S.text - 1, 34, `font-weight="600" fill="${C.ink}"`));
  } else if (syncs.length) {
    right = part('Most in sync with', '🤝', 84 + 34, (x, yy) => syncs.map((n, i) => {
      const cx = x + inner / 6 + i * inner / 3;
      return avatar(n, cx, yy + 42, 40) + `<text x="${cx}" y="${yy + 84 + 28}" font-size="21" font-weight="600" fill="${C.ink}" text-anchor="middle">${esc(n)}</text>`;
    }).join(''));
  }
  row(care, right);

  // The signature, pinned to the foot as the site's is (margin-top: auto).
  y = Math.max(y + 8, H - S.foot - 40);
  const foot = pair ? `<text x="${W / 2}" y="${y + 28}" font-size="28" font-weight="700" fill="${C.ink}" text-anchor="middle">${esc(card.stage === 'self' ? 'How matches see you · tell Muse anything to change' : 'Psyche Pair · psycheai.io')}</text>`
    : `<text x="${W / 2}" y="${y + 28}" font-size="28" text-anchor="middle"><tspan font-weight="700" fill="${C.ink}">psycheai.io</tspan><tspan fill="${C.soft}">  •  Tag us </tspan><tspan font-weight="700" fill="${C.accent}">@psycheai.io</tspan></text>`;
  o.push(foot);
  y += 40;

  // Scaled down about the top centre, just enough, when it runs past the canvas.
  const room = H - S.foot, scale = y > room ? (room - S.top) / (y - S.top) : 1;
  const body = scale < 1 ? `<g transform="translate(${(W / 2) * (1 - scale)},${S.top * (1 - scale)}) scale(${scale.toFixed(4)})">${o.join('')}</g>` : o.join('');
  return { svg: `<rect width="${W}" height="${H}" rx="44" fill="url(#pc-bg)"/>` + body, W, H, scale };
}

// ---------- the match card ----------

// The Pair card is the Psyche Card's design (psycheSvg, pair mode).
function pairSvg(card) {
  return psycheSvg({ ...card, characterName: card.characterName, letters: null }, { pair: true });
}

// ---------- the Sync card ----------

// The full Sync, in the same sections as a Sync on psycheai.io: the summary,
// where they align, where they differ, and how to relate better (for each of
// them and together), all in one tall image so nothing needs the website. The
// evidence and the caveat stay on the card page; the height follows the text.
function fullSyncSvg(card) {
  const W = 1080, X = 48, PW = 984, IN = 34, TW = PW - 2 * IN;
  const me = card.me || {}, them = card.them || {}, r = card.report || {};
  const o = [];
  o.push(brand(60, 92, 28));
  o.push(`<text x="${W / 2}" y="92" font-size="30" font-weight="600" fill="${C.soft}" text-anchor="middle">Psyche Sync</text>`);
  // Hero: the two characters, the names, and the summary line.
  const summary = wrapMeasured(r.summary, 34, 700, 880).slice(0, 4);
  const heroH = 494 + summary.length * 46;
  o.push(`<rect x="${X}" y="140" width="${PW}" height="${heroH}" rx="32" fill="url(#pc-hero)"/>`);
  o.push(avatar(me.characterName, 400, 320, 130), avatar(them.characterName, 680, 320, 130));
  o.push(`<circle cx="540" cy="320" r="36" fill="${C.white}"/>` +
    (P.icons['🔗'] ? `<g transform="translate(524,304) scale(1.35)" fill="none" stroke="${C.accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${P.icons['🔗']}</g>` : ''));
  o.push(`<text x="${W / 2}" y="525" font-size="54" font-weight="700" fill="${C.white}" text-anchor="middle">${esc(me.firstName)} &amp; ${esc(them.firstName)}</text>`);
  const sub = [me.characterName && them.characterName ? me.characterName + ' & ' + them.characterName : '', me.mbti && them.mbti ? me.mbti + ' · ' + them.mbti : ''].filter(Boolean).join('   ·   ');
  if (sub) o.push(`<text x="${W / 2}" y="572" font-size="25" font-weight="600" fill="${C.white}" fill-opacity="0.9" text-anchor="middle">${esc(sub)}</text>`);
  summary.forEach((l, i) => o.push(`<text x="${W / 2}" y="${640 + i * 46}" font-size="34" font-weight="700" fill="${C.white}" text-anchor="middle">${esc(l)}</text>`));
  let y = 140 + heroH + 24;

  // A panel of titled points: the title, then its detail.
  const points = (label, icon, items) => {
    if (!(items || []).length) return;
    const body = [];
    let h = 96;
    for (const it of items) {
      const title = wrapMeasured(it.title, 29, 700, TW);
      const detail = wrapMeasured(it.detail, 25, 400, TW);
      body.push({ title, detail, at: h });
      h += title.length * 38 + detail.length * 35 + 30;
    }
    o.push(panel(X, y, PW, h, label, icon));
    for (const b of body) {
      o.push(lines(b.title, X + IN, y + b.at + 10, 29, 38, `font-weight="700" fill="${C.ink}"`));
      o.push(lines(b.detail, X + IN, y + b.at + 10 + b.title.length * 38, 25, 35, `fill="${C.ink}" fill-opacity="0.82"`));
    }
    y += h + 24;
  };
  points('Where you align', '✨', r.align);
  points('Where you differ', '⚖️', r.differ);

  // How to relate better: a list each, then together.
  const play = r.howToPartner || {};
  const groups = [['For ' + (me.firstName || 'you'), play.forA], ['For ' + (them.firstName || 'them'), play.forB], ['Together', play.together]]
    .filter(([, list]) => (list || []).length);
  if (groups.length) {
    const body = [];
    let h = 96;
    for (const [head, list] of groups) {
      body.push({ head, at: h, items: [] });
      h += 30;
      for (const t of list) {
        const ls = wrapMeasured(t, 25, 400, TW - 40);
        body[body.length - 1].items.push({ ls, at: h });
        h += ls.length * 35 + 12;
      }
      h += 34;
    }
    o.push(panel(X, y, PW, h, 'How to relate better', '🤝'));
    for (const g of body) {
      o.push(`<text x="${X + IN}" y="${y + g.at + 10}" font-size="27" font-weight="700" fill="${C.accent}">${esc(g.head)}</text>`);
      for (const it of g.items) {
        o.push(`<circle cx="${X + IN + 10}" cy="${y + it.at + 22}" r="6" fill="${C.accent}"/>`);
        o.push(lines(it.ls, X + IN + 34, y + it.at + 30, 25, 35, `fill="${C.ink}" fill-opacity="0.85"`));
      }
    }
    y += h + 24;
  }
  o.push(`<text x="${W / 2}" y="${y + 40}" font-size="26" fill="${C.soft}" text-anchor="middle">Psyche Sync · psycheai.io</text>`);
  const H = y + 80;
  return { svg: `<rect width="${W}" height="${H}" rx="44" fill="url(#pc-bg)"/>` + o.join(''), W, H };
}

function syncSvg(card) {
  if (card.report && card.report.summary) return fullSyncSvg(card);
  const W = 1080, H = 1350;
  const me = card.me || {}, them = card.them || {};
  const o = [`<rect width="${W}" height="${H}" rx="44" fill="url(#pc-bg)"/>`];
  o.push(brand(60, 92, 28));
  o.push(`<text x="${W / 2}" y="92" font-size="30" font-weight="600" fill="${C.soft}" text-anchor="middle">Psyche Sync</text>`);

  o.push(`<rect x="48" y="150" width="984" height="580" rx="32" fill="url(#pc-hero)"/>`);
  o.push(avatar(me.characterName, 380, 380, 150), avatar(them.characterName, 700, 380, 150));
  o.push(`<circle cx="540" cy="380" r="40" fill="${C.white}"/>` +
    (P.icons['🔗'] ? `<g transform="translate(522,362) scale(1.5)" fill="none" stroke="${C.accent}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${P.icons['🔗']}</g>` : ''));
  o.push(`<text x="${W / 2}" y="612" font-size="56" font-weight="700" fill="${C.white}" text-anchor="middle">${esc(me.firstName)} &amp; ${esc(them.firstName)}</text>`);
  const sub = [me.characterName && them.characterName ? me.characterName + ' & ' + them.characterName : '', me.mbti && them.mbti ? me.mbti + ' · ' + them.mbti : ''].filter(Boolean).join('   ·   ');
  if (sub) o.push(`<text x="${W / 2}" y="670" font-size="26" font-weight="600" fill="${C.white}" fill-opacity="0.9" text-anchor="middle">${esc(sub)}</text>`);

  const L = 48, R = 548, PW = 484;
  const common = (card.interests || []).length ? card.interests : (card.values || []);
  o.push(panel(L, 754, 984, 250, !common.length ? 'Between you' : common === card.interests ? 'Into the same things' : 'Values you share', '✨'));
  if (common.length) o.push(pills(common.slice(0, 6).map(cap), L + 30, 870, 924));
  else o.push(lines(wrap('Different worlds: plenty to show each other', 30, 900, 1), L + 34, 880, 30, 0, `font-weight="600" fill="${C.ink}"`));

  o.push(panel(L, 1022, PW, 230, 'What drives you both', '🧲'));
  if ((card.motivators || []).length) o.push(numbered(card.motivators.slice(0, 3).map(cap), L + 30, 1130, 50, { filled: false }));
  else o.push(lines(wrap('Different drives, each a strength', 28, 420, 2), L + 34, 1134, 28, 38, `font-weight="600" fill="${C.ink}"`));
  o.push(panel(R, 1022, PW, 230, 'Most in sync', '🔗'));
  const syncLine = card.naturalPair || (card.sharedAxes >= 2 ? `You share ${card.sharedAxes} of 4 type letters` : 'Two ways of seeing the world: each sees what the other misses');
  o.push(lines(wrap(syncLine, 28, 420, 3), R + 34, 1134, 28, 38, `font-weight="600" fill="${C.ink}"`));
  o.push(`<text x="${W / 2}" y="1304" font-size="26" fill="${C.soft}" text-anchor="middle">Ask Muse for your Sync · psycheai.io</text>`);
  return { svg: o.join(''), W, H };
}

/** The SVG for a card: 'psyche' is the full Psyche Card, 'sync' a Sync card, anything else a match card. */
function cardSvg(card) {
  const { svg, W, H } = card.stage === 'psyche' ? psycheSvg(card) : card.stage === 'sync' ? syncSvg(card) : pairSvg(card);
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" font-family="Inter"><defs>${defs()}</defs>${svg}</svg>`;
}

/** A user's photo as a data URI, or null. https only, public addresses only, capped. */
/** The card as a PNG Buffer. */
async function renderCard(card) {
  const png = new Resvg(cardSvg(card), { font: { fontFiles: FONTS, loadSystemFonts: false, defaultFontFamily: 'Inter' }, fitTo: { mode: 'width', value: 1080 } }).render().asPng();
  return Buffer.from(png);
}

module.exports = { renderCard, cardSvg, wrap };
