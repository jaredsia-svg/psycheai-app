// The 28 Psyche characters, carried over from PsycheAI (lib/prompts.js
// CHARACTER_CATALOGUE and docs/copy.js CHARACTER_SYNCS, October 2026). Each
// holds one temperament; the host picks the closest for the user and the
// card shows it as a badge beside their type: "Odysseus · ENFJ".
//
// Who can be given which character comes from the gender the user stated
// (basics.gender), so nothing is judged from photos: a woman gets a 'w' or
// 'n' character, a man an 'm' or 'n' one, and a nonbinary person an 'n' one.
// Named alone, never with the studio behind them.
//
// SYNCS is PsycheAI's table of characters who click; it is mutual. On a card
// it is a talking point only, never part of the score.

const CATALOGUE = [
  ['Mulan', 'w'], ['Elsa', 'w'], ['Moana', 'w'], ['Simba', 'm'],
  ['Rapunzel', 'w'], ['Judy Hopps', 'w'], ['Nick Wilde', 'm'], ['Baymax', 'n'],
  ['Dr Watson', 'm'], ['Buzz Lightyear', 'm'], ['The Tin Man', 'n'], ['Remy', 'n'],
  ['Joy', 'w'],
  ['Odysseus', 'm'], ['Captain America', 'm'], ['Spider-Man', 'm'], ['Hulk', 'm'],
  ['Wonder Woman', 'w'], ['Sherlock Holmes', 'm'],
  ['Pikachu', 'n'], ['Princess Peach', 'w'],
  ['Shrek', 'm'], ['Po', 'm'], ['Hiccup', 'm'],
  ['Hermione Granger', 'w'], ['Sailor Moon', 'w'], ['Hello Kitty', 'w'],
  ['Kuromi', 'w'],
];
const NAMES = CATALOGUE.map(([name]) => name);
const SIDE = Object.fromEntries(CATALOGUE);

const SYNCS = {
  'Mulan': ['Baymax', 'Po', 'Hermione Granger'],
  'Elsa': ['Rapunzel', 'Moana', 'Odysseus'],
  'Moana': ['Hiccup', 'Elsa', 'Joy'],
  'Simba': ['Po', 'Judy Hopps', 'Princess Peach'],
  'Rapunzel': ['Elsa', 'Remy', 'Hulk'],
  'Judy Hopps': ['Nick Wilde', 'Simba', 'Wonder Woman'],
  'Nick Wilde': ['Judy Hopps', 'Shrek', 'Kuromi'],
  'Baymax': ['Mulan', 'The Tin Man', 'Hiccup'],
  'Dr Watson': ['Buzz Lightyear', 'Joy', 'The Tin Man'],
  'Buzz Lightyear': ['Dr Watson', 'Wonder Woman', 'Captain America'],
  'The Tin Man': ['Baymax', 'Remy', 'Dr Watson'],
  'Remy': ['Rapunzel', 'The Tin Man', 'Sherlock Holmes'],
  'Joy': ['Dr Watson', 'Pikachu', 'Moana'],
  'Odysseus': ['Captain America', 'Spider-Man', 'Elsa'],
  'Captain America': ['Odysseus', 'Wonder Woman', 'Buzz Lightyear'],
  'Spider-Man': ['Odysseus', 'Hermione Granger', 'Sailor Moon'],
  'Hulk': ['Sherlock Holmes', 'Hiccup', 'Rapunzel'],
  'Wonder Woman': ['Captain America', 'Buzz Lightyear', 'Judy Hopps'],
  'Sherlock Holmes': ['Hermione Granger', 'Hulk', 'Remy'],
  'Pikachu': ['Joy', 'Sailor Moon', 'Shrek'],
  'Princess Peach': ['Hello Kitty', 'Sailor Moon', 'Simba'],
  'Shrek': ['Nick Wilde', 'Kuromi', 'Pikachu'],
  'Po': ['Mulan', 'Simba', 'Hello Kitty'],
  'Hiccup': ['Moana', 'Hulk', 'Baymax'],
  'Hermione Granger': ['Spider-Man', 'Sherlock Holmes', 'Mulan'],
  'Sailor Moon': ['Pikachu', 'Princess Peach', 'Spider-Man'],
  'Hello Kitty': ['Kuromi', 'Princess Peach', 'Po'],
  'Kuromi': ['Hello Kitty', 'Shrek', 'Nick Wilde'],
};

const OPEN_TO = { woman: ['w', 'n'], man: ['m', 'n'], nonbinary: ['n'] };

/** The characters open to someone of this stated gender. */
function allowedFor(gender) {
  const sides = OPEN_TO[gender] || ['n'];
  return CATALOGUE.filter(([, side]) => sides.includes(side)).map(([name]) => name);
}

const click = (x, y) => Boolean(x && y && (SYNCS[x] || []).includes(y));

module.exports = { NAMES, SIDE, SYNCS, allowedFor, click };
