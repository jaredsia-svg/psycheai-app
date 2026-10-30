// The public pages now live on psycheai.io, as one page in PsycheAI's own
// markup (psycheai repo, docs/muse.html): what PsycheAI in Muse is, how to add
// it, and the plugin's privacy, terms and safety. The plugin's old addresses
// redirect there, so links already handed out (and the ones Meta's review
// asks for) keep working.

const SITE = () => (process.env.PSYCHEAI_URL || 'https://psycheai.io').replace(/\/$/, '');

const REDIRECTS = { '/': '/muse', '/add-to-muse': '/muse#add', '/privacy': '/muse-privacy', '/terms': '/muse-terms', '/safety': '/muse#safety', '/docs': '/muse-docs' };

/** Where an old plugin page now lives, or null. */
const redirectFor = path => (path in REDIRECTS ? SITE() + REDIRECTS[path] : null);

module.exports = { REDIRECTS, redirectFor };
