// Cloudflare Worker for psycheai.io (README "One name: psycheai.io").
//
// The PsycheAI skill reaches its server at psycheai.io: these paths are
// passed, as they are, to app.psycheai.io, at Cloudflare's edge, so they
// never go through psycheai.io's own server. Everything else on psycheai.io
// is untouched (the Worker runs only on the routes below).
//
// Routes to add in Cloudflare (Workers > this Worker > Settings > Domains & Routes):
//   psycheai.io/skill/*      (bare psycheai.io/skill, the install address, is psycheai.io's own route: README "psycheai.io/skill")
//   psycheai.io/sync/*
//   psycheai.io/mcp
//
// Nothing is logged or kept here: no request or answer body is read, and
// Cloudflare's Workers logs stay off (they would keep addresses, which for
// /sync/<code> carry a Sync code).
const APP = 'https://app.psycheai.io';

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const target = APP + url.pathname + url.search;
    const headers = new Headers(request.headers);
    headers.delete('host');
    // Who asked, for the app server's rate limits: from here every request comes from Cloudflare, so the
    // asker's address goes in its own header, trusted by the app only with the shared secret (EDGE_SECRET,
    // a Worker secret; PSYCHE_EDGE_SECRET on the app). Anything a client sent in those headers is replaced.
    headers.delete('x-psyche-edge');
    headers.delete('x-psyche-client-ip');
    const ip = request.headers.get('cf-connecting-ip');
    if (ip && env.EDGE_SECRET) {
      headers.set('x-psyche-client-ip', ip);
      headers.set('x-psyche-edge', env.EDGE_SECRET);
    }
    const init = { method: request.method, headers, redirect: 'manual' };
    if (request.method !== 'GET' && request.method !== 'HEAD') init.body = request.body;
    const answer = await fetch(target, init);
    // A redirect the app sends back to its own address stays on psycheai.io.
    const location = answer.headers.get('location');
    if (location && location.startsWith(APP)) {
      const out = new Response(answer.body, answer);
      out.headers.set('location', 'https://psycheai.io' + location.slice(APP.length));
      return out;
    }
    return answer;
  },
};
