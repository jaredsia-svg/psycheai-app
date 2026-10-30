// Settings shared across modules.

const BASE_URL = (process.env.PSYCHE_BASE_URL || 'http://localhost:8787').replace(/\/$/, '');

module.exports = { BASE_URL };
