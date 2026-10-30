// Copies what the plugin's card images draw from PsycheAI, so a Psyche Card
// drawn here looks like one drawn on psycheai.io: the character scenes and
// their round crops, the line icons, the brand mark, the sync table and the
// colour tokens. Run after PsycheAI's art or palette changes:
//
//   node tools/sync-psycheai.mjs [path to the psycheai repo, default ../psycheai]
//
// Writes assets/psycheai.json. The scenes are PsycheAI's own redrawn artwork.
import { readFileSync, writeFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runInNewContext } from 'node:vm';

const here = dirname(fileURLToPath(import.meta.url));
const repo = process.argv[2] || join(here, '..', '..', 'psycheai');
const sandbox = {};
sandbox.globalThis = sandbox;
runInNewContext(readFileSync(join(repo, 'docs', 'character-art.js'), 'utf8'), sandbox);
const copySrc = readFileSync(join(repo, 'docs', 'copy.js'), 'utf8');
runInNewContext(copySrc, sandbox);
const C = sandbox.PsycheCopy;
const crops = runInNewContext('(' + (copySrc.match(/const ART_CROPS = (\{[^;]*\});/) || [])[1] + ')');

const css = readFileSync(join(repo, 'docs', 'styles.css'), 'utf8');
const token = name => ((css.match(new RegExp('--' + name + ':\\s*([^;]+);')) || [])[1] || '').trim();

const out = {
  from: 'psycheai docs/character-art.js, docs/copy.js, docs/styles.css',
  art: sandbox.PsycheCharacterArt,
  crops,
  icons: C.LINE_ICONS,
  cardIcons: C.CARD_ICONS,
  brand: C.BRAND_MARK,
  syncs: C.CHARACTER_SYNCS,
  tokens: { bg: token('bg'), ink: token('ink'), inkSoft: token('ink-soft'), line: token('line'), accent: token('accent'), accent2: token('accent-2'), accentSoft: token('accent-soft') },
};
writeFileSync(join(here, '..', 'assets', 'psycheai.json'), JSON.stringify(out));
console.log('wrote assets/psycheai.json:', Object.keys(out.art).length, 'scenes,', Object.keys(out.icons).length, 'icons, tokens', JSON.stringify(out.tokens));
