// The preview a shared install link shows (README "Link previews"). Pasted into
// WhatsApp, an Instagram DM or iMessage, app.psycheai.io/install and a Psyche
// link (/sync/<code>) were bare text: the apps' link fetchers got the plain
// text meant for Muse. A fetcher that asks for a preview now gets a small page
// with Open Graph tags and one branded image, and the same install text in its
// body, so a reader that isn't a previewer (Muse itself included, whatever it
// calls itself) still reads what it always did.
'use strict';

const path = require('node:path');
const { Resvg } = require('@resvg/resvg-js');
const P = require('../assets/psycheai.json');
const { esc } = require('./theme');

const FONT_DIR = path.join(__dirname, '..', 'assets', 'fonts');
const FONTS = ['Inter_400Regular.ttf', 'Inter_600SemiBold.ttf', 'Inter_700Bold.ttf'].map(f => path.join(FONT_DIR, f));
const W = 1200;
const H = 630;

// The link fetchers that build previews. Muse fetching a link isn't one of them
// as far as we know; if it is, it gets the preview page, whose body is the same text.
const PREVIEWERS = /WhatsApp|facebookexternalhit|Facebot|Instagram|Twitterbot|TelegramBot|Slackbot|Discordbot|LinkedInBot|SkypeUriPreview|Iframely|redditbot|Pinterest|Embedly|Google-PageRenderer|vkShare|Viber|Line\//i;
const isPreviewer = ua => PREVIEWERS.test(String(ua || ''));

const mark = (x, y, size, colour, width, dot) => {
  const k = size / P.brand.viewBox;
  return `<g transform="translate(${x},${y}) scale(${k})" fill="none" stroke="${colour}" stroke-width="${width / k}" stroke-linecap="round" stroke-linejoin="round">` +
    P.brand.paths.map(d => `<path d="${d}"/>`).join('') + `<circle cx="70" cy="70" r="11" fill="${dot}" stroke="none"/></g>`;
};

/** The preview image: PsycheAI's look, what it is, and the line to paste into Muse. */
function svg() {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}">
<defs><linearGradient id="bg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#5b2a86"/><stop offset=".5" stop-color="#7b3fa0"/><stop offset="1" stop-color="#c2366d"/></linearGradient></defs>
<rect width="${W}" height="${H}" fill="url(#bg)"/>
<g opacity=".14">${mark(760, -70, 560, '#ffffff', 9, '#ffffff')}</g>
${mark(72, 62, 64, '#ffffff', 5.5, '#f7c55a')}
<text x="150" y="106" font-family="Inter" font-weight="700" font-size="36" fill="#ffffff">PsycheAI</text>
<text x="72" y="232" font-family="Inter" font-weight="700" font-size="62" fill="#ffffff">Your personal AI coach</text>
<text x="72" y="306" font-family="Inter" font-weight="700" font-size="62" fill="#ffffff">that already knows you.</text>
<text x="72" y="368" font-family="Inter" font-weight="400" font-size="29" fill="#ffffff" fill-opacity=".9">Your Psyche Card and report, from your own Instagram, in Muse.</text>
<rect x="72" y="438" width="1056" height="124" rx="26" fill="#ffffff" fill-opacity=".14" stroke="#ffffff" stroke-opacity=".45" stroke-width="2" stroke-dasharray="10 8"/>
<text x="104" y="486" font-family="Inter" font-weight="600" font-size="24" fill="#ffffff" fill-opacity=".85">PASTE INTO MUSE</text>
<text x="104" y="538" font-family="Inter" font-weight="700" font-size="40" fill="#ffffff">psycheai.io/skill</text>
</svg>`;
}

let png = null;
/** The image, drawn once. */
function image() {
  if (!png) png = Buffer.from(new Resvg(svg(), { font: { fontFiles: FONTS, loadSystemFonts: false, defaultFontFamily: 'Inter' }, fitTo: { mode: 'width', value: W } }).render().asPng());
  return png;
}

/** The Open Graph tags for a shared link. */
function tags({ title, description, url, base }) {
  const img = base + '/preview.png';
  return `<meta property="og:type" content="website"><meta property="og:site_name" content="PsycheAI">` +
    `<meta property="og:title" content="${esc(title)}"><meta property="og:description" content="${esc(description)}">` +
    `<meta property="og:url" content="${esc(url)}"><meta property="og:image" content="${esc(img)}"><meta property="og:image:secure_url" content="${esc(img)}">` +
    `<meta property="og:image:type" content="image/png"><meta property="og:image:width" content="${W}"><meta property="og:image:height" content="${H}">` +
    `<meta property="og:image:alt" content="PsycheAI: your personal AI coach that already knows you">` +
    `<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="${esc(title)}">` +
    `<meta name="twitter:description" content="${esc(description)}"><meta name="twitter:image" content="${esc(img)}">`;
}

/** What a link fetcher gets: the tags, and the install text a reader would have got, as the body. */
function page({ title, description, url, base, text }) {
  return `<!doctype html><html lang="en"><head><meta charset="utf-8"><title>${esc(title)}</title>` +
    `<meta name="description" content="${esc(description)}">${tags({ title, description, url, base })}</head>` +
    `<body><pre style="white-space:pre-wrap">${esc(text)}</pre></body></html>`;
}

module.exports = { isPreviewer, image, tags, page, svg, W, H };
