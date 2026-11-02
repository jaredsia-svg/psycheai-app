#!/usr/bin/env python3
"""PsycheAI for Muse, as a skill: calls PsycheAI's tools at app.psycheai.io.

  bin/psyche.py status                 make (or check) this workspace's PsycheAI account,
                                       and say whether a newer version of this skill exists
  bin/psyche.py update                 fetch the newest version of this skill's files
  bin/psyche.py call TOOL [JSON]       run a PsycheAI tool, e.g. call start, or
                                       call publish_psyche '{"answer": {...}, "name": "..."}'
  bin/psyche.py call TOOL @FILE        the same, with the JSON arguments read from FILE
  bin/psyche.py report                 their latest Psyche Report (kept here when it was
                                       saved), for answering their questions in later chats
  bin/psyche.py prep FILE... [--me NAME] [--deep]
                                       WhatsApp chats they exported (.zip or .txt), made
                                       ready here, on their device: their own messages, dated,
                                       after what they answer, everyone else "Friend A", "Friend B"..., numbers,
                                       emails, links and handles taken out. Writes
                                       sources/whatsapp.txt; the export itself is never read
                                       for the report and never sent anywhere
  bin/psyche.py collect-facebook [--me NAME] [--no-messenger]
                                       their own Facebook posts and their side of their busiest
                                       Messenger chats, de-identified, into sources/facebook.txt; a
                                       service not connected answers with its connect link
  bin/psyche.py show PART              one part of what publish_psyche gave back, kept here:
                                       card (saved as a picture), summary, pdf (saved as a file), links or next (README "One part at a time")
  bin/psyche.py checkin [ID done|not-yet|drop] [--note TEXT]
                                       their plan from the kept report and where each step
                                       stands; with an ID, record their answer (kept here only)
  bin/psyche.py why [ID]               the report's main findings to pick from; with an ID,
                                       what that finding rests on, from the report and the digest
  bin/psyche.py correct [ID not-me|partly|used-to-be --note TEXT]
                                       what they say is off (kept here only); no ID lists them
  bin/psyche.py build-digest           digest/digest.md built from work/items.jsonl and work/meta.json
                                       (what was read, saved as it was read), then checked
  bin/psyche.py check-answer FILE      the answer file checked as publish_psyche will take it:
                                       JSON, the schema, and what may leave the workspace
  bin/psyche.py republish              save their kept report (report.json) to PsycheAI again,
                                       for a fresh link, card and PDF, with no new read
  bin/psyche.py check-digest           check digest/digest.md, the summary of their own
                                       words a read is written from: its size, its dates,
                                       and that no handle, link, email or number is left
  bin/psyche.py forget [--everything]  delete the working files (work/, sources/, notes/);
                                       with --everything, the digest and the report too

The account is private and needs nothing typed: on first use this asks
PsycheAI for one and keeps its keys in .account.json next to this folder's
SKILL.md, with a spare copy in ~/.psycheai/, so deleting or reinstalling the
skill keeps the same account. Both are readable only by this workspace.
Never print or send either.
Standard library only.
"""
import base64
import hashlib
import http.client
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
import socket
import sys
import time
import zipfile
from datetime import datetime
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get('PSYCHEAI_BASE', 'https://app.psycheai.io')
# This release's number, set by tools/sign-skill.mjs and signed with the rest:
# update never installs a release older than this one.
RELEASE = 122
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ACCOUNT = os.path.join(HERE, '.account.json')
CLIENT_ID = 'psycheai-skill'
REPORT = os.path.join(HERE, 'report.json')
# A second copy of the account and the report outside this folder, so deleting
# or reinstalling the skill keeps the same account (README "The account
# outlives the skill folder"). PSYCHEAI_HOME moves it (the selftest uses it).
KEEP = os.environ.get('PSYCHEAI_HOME') or os.path.join(os.path.expanduser('~'), '.psycheai')
ACCOUNT_KEPT = os.path.join(KEEP, 'account.json')
REPORT_KEPT = os.path.join(KEEP, 'report.json')
# Weekly check-ins on their plan (README "Check-ins"): what they said, in this workspace only, never sent.
COACH = os.path.join(HERE, 'coach.json')
COACH_KEPT = os.path.join(KEEP, 'coach.json')
# What they said is off in a report (README "Explain and correct"): their own words, kept here only.
CORRECTIONS = os.path.join(HERE, 'corrections.json')
CORRECTIONS_KEPT = os.path.join(KEEP, 'corrections.json')
# The keys PsycheAI keeps nothing readable without (README "Nothing readable
# kept"): their card summary's key, from each publish, and the Sync codes
# from their own Psyche links and the ones they used. Sent with each call and
# never kept by PsycheAI, so only this workspace opens what's theirs.
# PsycheAI's guides, pinned in this signed release (README "The guide is
# signed"): what Muse is asked to write comes from here, never from a server.
GUIDE = os.path.join(HERE, 'guide.json')
SYNC_TASK = ('\n\nWrite the Sync as one JSON object matching the schema, with "mode" set to "platonic", then call save_sync with it as answer. '
             "Don't write it in the chat: save_sync gives back its PDF, which holds all of it.")
KEYS = os.path.join(HERE, '.keys.json')
KEYS_KEPT = os.path.join(KEEP, 'keys.json')
SYNC_CODE = re.compile(r'/sync/([A-Za-z0-9_-]{22})(?![A-Za-z0-9_-])')
SOURCES = os.path.join(HERE, 'sources')
NOTES = os.path.join(HERE, 'notes')
WORK = os.path.join(HERE, 'work')        # what was pulled from Instagram for a read; deleted once it's published
DIGEST = os.path.join(HERE, 'digest', 'digest.md')
LAST_COLLECT = os.path.join(os.path.dirname(DIGEST), 'last-collect.json')
LAST = os.path.join(HERE, 'last-psyche.json')   # what the latest publish gave back, shown a part at a time

# A saved Psyche's result in parts, so the chat can show each on its own: one
# part a host won't use no longer holds back the rest.
OUT = os.path.join(HERE, 'out')                 # the PDF as a file here, so the chat opens it in Muse, not a browser


def file_label(kind):
    """A saved file's name: "Psyche Report - Mei Tan - 01112026", their full name and the save's date
    (as psycheai.io names its PDFs), never the time."""
    kept = read_first([REPORT, REPORT_KEPT]) or {}
    name = re.sub(r'[^\w .&()-]', '', str(kept.get('name') or '')).strip()[:60]
    try:
        day = datetime.fromtimestamp(os.path.getmtime(LAST)).strftime('%d%m%Y')
    except OSError:
        day = datetime.now().strftime('%d%m%Y')
    return ' - '.join(x for x in [kind, name, day] if x)


# Where the card and PDF may be fetched from (README "Fetched only from PsycheAI"): a server
# answer can't send this workspace, or the PDF's key, anywhere else. Off production (tests,
# a local server) any address is allowed.
FETCH_HOSTS = ('app.psycheai.io', 'psycheai.io')


def fetchable(link):
    if BASE != 'https://app.psycheai.io':
        return True
    parts = urllib.parse.urlsplit(link or '')
    return parts.scheme == 'https' and parts.hostname in FETCH_HOSTS


def local_pdf(r):
    """The report's PDF saved in out/, so it's attached as a file rather than linked."""
    link = r.get('pdf')
    files = [f for f in r.get('files', []) if f.get('mimeType') == 'application/pdf']
    name = re.sub(r'[^\w .&()-]', '', r.get('pdfName') or (files[0].get('name') if files else '') or 'Psyche Report.pdf') or 'Psyche Report.pdf'
    # The save's time in the name, so each save's PDF is a new file to the chat, never taken for one sent before.
    name = file_label('Psyche Report') + '.pdf'
    out = {'pdf': link}
    # Fetched already, right after the save (saved()): that copy is this save's, since out/ is
    # emptied at each save, and the link may have expired since.
    try:
        kept = [f for f in os.listdir(OUT) if f.lower().endswith('.pdf')]
    except OSError:
        kept = []
    if kept:
        out['file'] = os.path.join(OUT, kept[0])
        return out
    if not link or not fetchable(link):
        return out
    try:
        os.makedirs(OUT, exist_ok=True)
        for old in os.listdir(OUT):
            if old.lower().endswith('.pdf'):
                os.remove(os.path.join(OUT, old))
        parts = urllib.parse.urlsplit(link)
        if parts.fragment:
            # /report-pdf?m=<id>#<key>: the key goes in a header, never in an address a server or log keeps.
            pid = urllib.parse.parse_qs(parts.query).get('m', [''])[0]
            status, body = fetch('GET', '%s://%s/api/import/pdf?id=%s' % (parts.scheme, parts.netloc, urllib.parse.quote(pid)),
                                 {'Accept': 'application/pdf', 'X-Psyche-Key': parts.fragment, 'User-Agent': agent()})
        else:
            status, body = fetch('GET', link, {'Accept': 'application/pdf', 'User-Agent': agent()})
        if not body.startswith(b'%PDF'):
            raise ValueError('not a PDF')
        path = os.path.join(OUT, name)
        with open(path, 'wb') as f:
            f.write(body)
        os.chmod(path, 0o600)
        out['file'] = path
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        out['files'] = files
    return out


def local_card(r):
    """Their Psyche Card as a picture saved in out/, so it's attached as an image rather than a link preview."""
    link = r.get('image')
    out = {'image': link}
    if not link or not fetchable(link):
        return out
    try:
        os.makedirs(OUT, exist_ok=True)
        status, body = fetch('GET', link, {'Accept': 'image/png', 'User-Agent': agent()})
        if not body.startswith(b'\x89PNG'):
            raise ValueError('not a PNG')
        for old in os.listdir(OUT):
            if old.lower().endswith('.png'):
                os.remove(os.path.join(OUT, old))
        path = os.path.join(OUT, file_label('Psyche Card') + '.png')
        with open(path, 'wb') as f:
            f.write(body)
        os.chmod(path, 0o600)
        out['file'] = path
    except (OSError, ValueError, urllib.error.URLError, http.client.HTTPException):
        pass
    return out


# ---------- the report file (README "The report as a file") ----------
# The whole report as one HTML file in the reader's own workspace, attached to the chat:
# opened, it is a normal page, so every tap works and opening a section can bring the
# reader to it, which a widget inside Muse's phone app couldn't. Built here from what
# publish_psyche gave back (full: every write-up and its evidence; else view), styled like
# psycheai.io's report. It loads nothing from anywhere and keeps nothing anywhere else.

import html as _html

W_FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif'
# psycheai.io's mark as its front page's header draws it (docs/index.html .hero-mark): the symbol alone,
# large and faint, partly off the banner's top right corner (README "The mark in the banner").
W_LOGO = ('<svg class="mark" viewBox="0 0 140 140" fill="none" stroke="currentColor" stroke-width="3" '
          'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
          '<path d="M12 70C12 56.745 37.967 46 70 46C102.033 46 128 56.745 128 70C128 83.255 102.033 94 70 94C37.967 94 12 83.255 12 70Z"/>'
          '<path d="M46 70C46 37.967 56.745 12 70 12C83.255 12 94 37.967 94 70C94 102.033 83.255 128 70 128C56.745 128 46 102.033 46 70Z"/>'
          '<path d="M41 19.771C52.479 13.143 74.768 30.259 90.785 58C106.801 85.741 110.479 113.602 99 120.229C87.521 126.857 65.232 109.741 49.215 82C33.199 54.259 29.521 26.398 41 19.771Z"/>'
          '<circle cx="70" cy="70" r="11" fill="currentColor" stroke="none"/></svg>')

W_PARTS = [
    ('overview', 'Overview', '#7b3fa0'),
    ('whoYouAre', 'Who you are', '#2f7d6b'),
    ('whatDrivesYou', 'What drives you', '#c2571a'),
    ('howYouConnect', 'How you connect', '#c2366d'),
    ('howYouWork', 'How you work', '#2d5fa8'),
    ('puttingItTogether', 'Putting it together', '#6a4bb5'),
]
W_BANDS = {'steady': ('#2f7d5b', '#e3f4ec'), 'mixed': ('#9a5b12', '#fdf1e2'), 'under strain': ('#b3261e', '#fbe7e5')}

W_CSS = '''
:root{color-scheme:light;--ink:#241a2e;--soft:#5a4f66;--mute:#6b6076;--line:#ece4f1;--accent:#7b3fa0;--accent2:#d1477a}
*{box-sizing:border-box;font-family:inherit}
html{scrollbar-width:thin;scrollbar-color:#cdb6dd transparent}
html,body{margin:0;padding:0;background:#faf7fb}
body{font-family:__FONT__;color:var(--ink);font-size:15px;line-height:1.55;-webkit-text-size-adjust:100%;text-rendering:optimizeLegibility}
.wrap{max-width:760px;margin:0 auto;padding:0 14px 40px}
.banner{position:relative;overflow:hidden;margin:0 -14px;padding:26px 20px 24px;color:#fff;background:linear-gradient(135deg,#5b2a86 0%,#7b3fa0 45%,#c2366d 100%)}
.banner:before{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;border-radius:50%;background:radial-gradient(circle,rgba(255,230,190,.55),rgba(255,230,190,0) 70%)}
.banner .row{position:relative;display:flex;gap:18px;align-items:center}
.banner .txt{flex:1;min-width:0}
.facts{display:inline-block;padding:5px 12px;border-radius:999px;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.3);font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}
.lede{margin:6px 0 0;font-size:14.5px;line-height:1.5;opacity:.92;max-width:34em}
.banner .mark{position:absolute;top:-4.6rem;right:-3.8rem;width:240px;height:auto;color:#fff;opacity:.16;pointer-events:none}
.banner .row{position:relative}
.banner h1{margin:10px 0 2px;font-size:28px;line-height:1.15;letter-spacing:-.02em}
.banner .sub{margin-top:8px;font-size:12.5px;opacity:.75}
.cardbtn{all:unset;flex:none;cursor:zoom-in;-webkit-tap-highlight-color:transparent}
.viewer{position:fixed;inset:0;z-index:20;background:rgba(20,8,30,.88);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:max(16px,env(safe-area-inset-top)) max(16px,env(safe-area-inset-right)) calc(28px + env(safe-area-inset-bottom)) max(16px,env(safe-area-inset-left));cursor:zoom-out}
.viewer[hidden]{display:none}
.viewer img{max-width:100%;max-height:calc(100% - 64px);border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.viewer span{margin-top:14px;padding:8px 16px;border-radius:999px;background:rgba(255,255,255,.14);color:#fff;font-size:14px;font-weight:600}
.cardbtn#cardopen{float:right;margin:16px 0 10px 22px}
.hero.withcard{display:flow-root}
.cardbtn{display:flex;flex-direction:column;align-items:center;gap:8px}
.cardpic{display:block;width:132px;border-radius:14px;box-shadow:0 14px 30px rgba(70,20,100,.28),0 2px 6px rgba(70,20,100,.15);transform:rotate(2.5deg);border:3px solid #fff;transition:transform .2s ease,box-shadow .2s ease}
.cardbtn:hover .cardpic,.cardbtn:focus-visible .cardpic{transform:rotate(0) scale(1.04);box-shadow:0 18px 36px rgba(70,20,100,.34)}
.cardbtn em{font-style:normal;font-size:11.5px;line-height:1.3;font-weight:700;color:#7b3fa0;text-align:center}
@media (max-width:480px){.banner .mark{top:-3.6rem;right:-3.4rem;width:165px;opacity:.14}.cardpic{width:112px}.cardbtn#cardopen{margin:32px 16px 8px 12px}.hero.withcard{display:block}.hero.withcard .cardbtn{margin-left:12px}.banner h1{font-size:24px}.facts{font-size:9.5px;letter-spacing:.04em;padding:4px 9px;white-space:nowrap}.lede{font-size:13.5px}}
nav{position:sticky;top:0;z-index:5;margin:0 -14px 14px;padding:10px 14px;background:rgba(250,247,251,.94);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
@media (min-width:700px){nav{flex-wrap:wrap;overflow:visible}}
nav a{flex:none;display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;border:1px solid #e2d8e9;background:#fff;color:var(--soft);font-size:13px;font-weight:650;text-decoration:none;white-space:nowrap;-webkit-tap-highlight-color:transparent}
nav a i{font-style:normal;font-weight:800;color:var(--c)}
nav a[aria-current=true]{background:var(--c);border-color:var(--c);color:#fff}
nav a[aria-current=true] i{color:#fff}
nav button,.foldall{all:unset;box-sizing:border-box;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}
nav button{flex:none;margin-left:auto;padding:6px 12px;border-radius:999px;color:var(--accent);font-size:13px;font-weight:700;white-space:nowrap}
.part{background:#fff;border:1px solid #e6dcec;border-radius:20px;margin:0 0 14px;box-shadow:0 1px 2px rgba(36,26,46,.04),0 10px 30px rgba(36,26,46,.06);overflow:hidden;scroll-margin-top:var(--navh,62px)}
.part.open{border-top:4px solid var(--c)}
.part>button{all:unset;box-sizing:border-box;display:grid;grid-template-columns:auto 1fr auto;align-items:center;column-gap:14px;width:100%;padding:16px 18px;cursor:pointer;touch-action:manipulation;-webkit-tap-highlight-color:transparent}
.part>button:focus-visible{outline:2px solid var(--c);outline-offset:-2px;border-radius:18px}
.num{grid-row:1/span 2;font-size:30px;font-weight:800;line-height:1;letter-spacing:-.03em;background:linear-gradient(135deg,var(--c),#d1477a);-webkit-background-clip:text;background-clip:text;color:transparent}
.ttl{font-size:18px;font-weight:750;letter-spacing:-.01em}
.tease{grid-column:2;font-size:13px;color:var(--mute);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.part.open .tease{display:none}
.chev{grid-row:1/span 2;grid-column:3;width:24px;height:24px;color:var(--mute);transition:transform .2s}
.part.open .chev{transform:rotate(180deg)}
.body{display:none;padding:2px 18px 18px;border-top:1px solid #f1eaf5}
.part.open .body{display:block}
h3{margin:22px 0 10px;font-size:12px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--c);display:flex;align-items:center;gap:8px}
h3:after{content:"";flex:1;height:1px;background:linear-gradient(90deg,#efe6f3,transparent)}
p{margin:0 0 10px}
.soft{color:var(--soft);font-size:14.5px}
.lead{font-size:16.5px;font-weight:650;line-height:1.45}
.intro{font-size:16px;line-height:1.55;color:var(--ink)}
.hero{margin-top:16px;padding:16px;border-radius:16px;background:linear-gradient(135deg,#f3e9f8,#fdf0f6);border:1px solid #ead9f1}
.hero small{display:block;font-size:11.5px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}
.hero b{display:block;margin:2px 0;font-size:26px;line-height:1.15;letter-spacing:-.02em;background:linear-gradient(135deg,#7b3fa0,#d1477a);-webkit-background-clip:text;background-clip:text;color:transparent}
.hero span{display:block;color:var(--mute);font-size:13.5px;margin-bottom:8px}
.hero p{margin:0;color:#3b2a49}
.it{padding:11px 0;border-bottom:1px solid #f4eff7}
.it:last-child{border-bottom:0}
.it>b{display:block;font-weight:700;line-height:1.35}
.it>span{display:block;margin-top:3px;color:var(--soft);font-size:14px}
.pat{display:grid;grid-template-columns:34px 1fr;gap:12px;padding:14px 0;border-bottom:1px solid #f2ecf5}
.pat:last-child{border-bottom:0}
.pat .n{width:34px;height:34px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;color:#fff;background:linear-gradient(135deg,#7b3fa0,#d1477a)}
.pat b{display:block;font-size:16px;line-height:1.3}
.pills{display:flex;flex-wrap:wrap;gap:5px;margin-top:8px}
.pill{display:inline-block;padding:2px 9px;border-radius:999px;font-size:11.5px;font-weight:700;background:#f3e9f8;color:#6a3590;vertical-align:middle}
.pill.prim{background:var(--c);color:#fff}
.pill.g{background:#eef1f4;color:#4d5866}
.ev{margin:6px 0 0;padding:0;list-style:none}
.ev li{position:relative;margin:3px 0;padding-left:14px;font-size:13px;line-height:1.45;color:#776b84}
.ev li:before{content:"";position:absolute;left:3px;top:.6em;width:4px;height:4px;border-radius:50%;background:#b9a6c7}
.ev li b{color:#5a4f66;font-weight:700}
.letter{display:inline-flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:9px;background:var(--c);color:#fff;font-weight:800;font-size:15px;margin-right:10px;vertical-align:middle}
.type{display:flex;align-items:baseline;gap:10px;margin:14px 0 2px}
.type b{font-size:30px;font-weight:800;letter-spacing:.06em;color:var(--c)}
.type span{color:var(--mute);font-weight:650}
.slider{padding:12px 0;border-bottom:1px solid #f2ecf5}
.slider:last-child{border-bottom:0}
.slider .top{display:flex;justify-content:space-between;align-items:baseline;gap:10px}
.slider .top em{font-style:normal;color:var(--mute);font-weight:500;font-size:13.5px}
.track{position:relative;height:8px;border-radius:8px;background:linear-gradient(90deg,#efe7f4,#e2d6ea);margin:8px 0}
.track i{position:absolute;left:0;top:0;bottom:0;border-radius:8px;background:linear-gradient(90deg,var(--c),#d1477a);opacity:.85}
.track u{position:absolute;top:50%;width:18px;height:18px;margin:-9px 0 0 -9px;border-radius:50%;background:#fff;border:4px solid var(--c);box-shadow:0 1px 4px rgba(0,0,0,.15)}
.score{font-weight:800;font-variant-numeric:tabular-nums;font-size:17px}
.band{display:inline-block;padding:3px 10px;border-radius:999px;font-size:12.5px;font-weight:700;margin-left:6px;vertical-align:middle}
.callout{padding:14px 16px;border-radius:14px;background:linear-gradient(135deg,#f3e9f8,#fbf2f8);color:#3b2a49;margin:12px 0 4px}
.callout b{color:var(--ink)}
.radar{display:block;width:100%;max-width:440px;height:auto;margin:6px auto 0;overflow:visible}
.radar text{font-family:__FONT__;font-size:11.5px;fill:#5a4f66}
.radar text.top{font-weight:800;fill:var(--c);font-size:12.5px}
.radar text,.radar .pt,.radar .hit{cursor:pointer}
.radar .hit{fill:transparent;pointer-events:all}
.radar{touch-action:manipulation}
.radar .on{stroke:var(--ink);stroke-width:2.5}
.tip{margin:8px 0 2px;padding:11px 14px;border-radius:14px;background:#faf6fc;border:1px solid #efe5f4;font-size:14px;color:var(--soft);min-height:46px}
.tip b{color:var(--ink)}
.tip i{display:block;font-style:normal;margin-top:3px;color:#3b2a49}
.mots{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin:8px 0 4px}
.mots.low{grid-template-columns:repeat(2,1fr)}
@media (max-width:540px){.mots{grid-template-columns:1fr}.mots.low{grid-template-columns:1fr 1fr}}
.mot{border-radius:14px;padding:10px 12px;border:1px solid #efe5f4;background:#fdfbfe}
.mot.hi{background:linear-gradient(135deg,#fff3ea,#fdf0f6);border-color:#f3d9c6}
.mot b{display:flex;justify-content:space-between;gap:6px;font-weight:750;font-size:14.5px;line-height:1.3}
.mot b i{font-style:normal;color:var(--c)}
.mots.low .mot b i{color:var(--mute)}
.mot span{display:block;margin-top:3px;color:var(--soft);font-size:13px;line-height:1.4}
.motlabel{margin:14px 0 0;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
.lang{display:grid;grid-template-columns:34px 1fr;column-gap:10px;padding:12px 0;border-bottom:1px solid #f2ecf5}
.lang:last-child{border-bottom:0}
.lang .ico{font-size:24px;line-height:1.2}
.cols{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin-top:12px}
@media (max-width:560px){.cols{grid-template-columns:1fr}}
.box{border-radius:16px;padding:12px 14px;background:#faf8fb}
.box.good{background:#f3faf6}
.box.hard{background:#fdf7ef}
.where,.it>span.where{display:block;margin-top:5px;font-size:12.5px;color:#8a7f96}
.areas{display:flex;flex-wrap:wrap;align-items:center;gap:5px;margin-top:7px}
.def{margin:-4px 0 12px;font-size:13.5px}
.areas span{font-size:12px;color:#8a7f96;margin-right:2px}
.areas i{font-style:normal;padding:2px 9px;border-radius:999px;background:#f4eef8;color:#6a3590;font-size:11.5px;font-weight:650}
.fine{margin:10px 0 0;font-size:12.5px;line-height:1.45;color:#8a7f96}
.box h4{display:flex;align-items:center;gap:7px;margin:2px 0 4px;font-size:12px;font-weight:800;letter-spacing:.07em;text-transform:uppercase;color:var(--mute)}
.box h4 i{font-style:normal;display:inline-flex;align-items:center;justify-content:center;width:19px;height:19px;border-radius:50%;font-size:11px;color:#fff}
.box.good h4 i{background:#2f7d5b}
.box.hard h4 i{background:#b26a14}
.box .it{padding:9px 0}
.edge{margin-top:14px;padding:16px;border-radius:16px;background:linear-gradient(135deg,#eef4fd,#f6f2fd);border:1px solid #dbe5f4}
.edge small{display:block;font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--c)}
.edge b{display:block;font-size:19px;margin:3px 0 6px;letter-spacing:-.01em}
.edge p{margin:0;color:#3b3550}
.plan{position:relative;margin:6px 0 0 8px;padding-left:20px;border-left:2px solid #e6dcec}
.plan>div{position:relative;padding:2px 0 12px}
.plan>div:before{content:"";position:absolute;left:-28px;top:4px;width:14px;height:14px;border-radius:50%;background:var(--c);border:3px solid #fff;box-shadow:0 0 0 1px var(--c)}
.plan small{display:block;font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--mute)}
.plan p{margin:6px 0 8px}
.plan p b{display:block;font-weight:700;line-height:1.35}
.plan p span{display:block;color:var(--soft);font-size:14px}
.plan p em{display:inline-block;margin-top:4px;padding:1px 8px;border-radius:999px;background:#f3e9f8;color:#6a3590;font-size:11.5px;font-style:normal;font-weight:700}
.sample{display:grid;justify-items:center;gap:10px;margin:14px 0 16px;padding:16px;border-radius:20px;background:#fff;border:1px solid #e6dcec;text-align:center}
.sample p{margin:0;color:var(--soft);font-size:14px;max-width:46ch}
.sample p.get{color:var(--accent);font-weight:700}
.sample .cardbtn#cardopen{float:none;margin:4px 0 0}
.sample .cardpic{width:min(320px,76vw);transform:none}
.roast{background:#fff;border:1px solid #f0c9d7;border-radius:20px;padding:0;margin:4px 0 14px;overflow:hidden}
.roast summary{list-style:none;cursor:pointer;display:grid;gap:4px;padding:16px 18px;background:linear-gradient(120deg,#5b2a86,#c2366d);color:#fff}
.roast summary::-webkit-details-marker{display:none}
.roast summary b{font-size:19px}
.roast summary .soft{color:#f6e6f0;font-size:13.5px}
.roast .badge{justify-self:start;font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;background:rgba(255,255,255,.18);padding:3px 8px;border-radius:999px}
.roast .salt{margin:14px 18px 0;font-size:13px;color:var(--soft)}
.roast .burn,.roast .kind{margin:12px 18px 18px;padding:14px 16px;border-radius:14px}
.roast .burn{background:#fdecf1}.roast .kind{background:#f3e9f8}
.roast h3{margin:0 0 6px;font-size:15px;text-transform:none;letter-spacing:0}
.method{background:#fff;border:1px solid #e6dcec;border-radius:20px;padding:18px;margin:4px 0 14px;box-shadow:0 10px 30px rgba(36,26,46,.05)}
.method .big{display:flex;align-items:center;gap:14px}
.method .big b{font-size:30px;font-weight:800;letter-spacing:-.02em}
.bar{height:8px;border-radius:8px;background:#ece4f1;margin:10px 0;overflow:hidden}
.bar i{display:block;height:100%;border-radius:8px;background:linear-gradient(90deg,#7b3fa0,#d1477a)}
.foldall{display:block;width:100%;margin:6px 0 0;padding:13px;border-radius:14px;border:1px solid #d9cde2;background:#fff;color:var(--accent);font-weight:750;font-size:14.5px;text-align:center}
footer{margin-top:22px;text-align:center;color:var(--mute);font-size:13px}
footer b{color:var(--ink)}
@media print{nav,.foldall{display:none}.part .body{display:block!important}.part{break-inside:avoid-page;box-shadow:none}.banner{-webkit-print-color-adjust:exact;print-color-adjust:exact}}
'''.replace('__FONT__', W_FONT)

# One section open at a time. Overview is open to start with; tapping a closed section's
# title, or its chip in the bar, closes the others first, then opens it and brings its title
# to the top of the screen, under the bar. Tapping an open one's title closes it. "Collapse
# all" closes every section and goes back to the top. Printing opens everything.
W_JS = '''
(function(){
var parts=[].slice.call(document.querySelectorAll('.part')),chips=[].slice.call(document.querySelectorAll('nav a')),bar=document.querySelector('nav');
// An opened section lands just under the bar, however tall the bar is on this screen.
function navh(){if(bar)document.documentElement.style.setProperty('--navh',(bar.offsetHeight+10)+'px');}navh();window.addEventListener('resize',navh);
function set(p,open){p.classList.toggle('open',open);p.querySelector('button').setAttribute('aria-expanded',open?'true':'false');
  chips.forEach(function(c){if(c.getAttribute('href')==='#'+p.id){c.setAttribute('aria-current',open?'true':'false');
    if(open){var n=c.parentNode;n.scrollLeft=Math.max(0,c.offsetLeft-n.clientWidth/2+c.clientWidth/2);}}});}
function go(el){requestAnimationFrame(function(){requestAnimationFrame(function(){try{el.scrollIntoView({block:'start',behavior:'instant'});}catch(e){el.scrollIntoView(true);}});});}
function only(p){parts.forEach(function(q){if(q!==p)set(q,false);});set(p,true);go(p);}
parts.forEach(function(p){p.querySelector('button').addEventListener('click',function(){if(p.classList.contains('open'))set(p,false);else only(p);});});
chips.forEach(function(c){c.addEventListener('click',function(e){e.preventDefault();var p=document.querySelector(c.getAttribute('href'));if(p)only(p);});});
function all(){parts.forEach(function(q){set(q,false);});go(document.getElementById('top'));}
[].slice.call(document.querySelectorAll('[data-fold]')).forEach(function(b){b.addEventListener('click',all);});
// The radar: a tap on a point or a name shows its score, what it is, and the reader's own line.
var tip=document.getElementById('mtip'),pts=[].slice.call(document.querySelectorAll('.radar .pt'));
[].slice.call(document.querySelectorAll('.radar [data-m]')).forEach(function(el){el.addEventListener('click',function(){
  if(!tip)return;var m=JSON.parse(el.getAttribute('data-m'));tip.innerHTML='';
  var b=document.createElement('b');b.textContent=m[0]+' \u00b7 '+m[1]+' / 100';tip.appendChild(b);
  if(m[2]){var s=document.createElement('span');s.textContent=' \u2013 '+m[2];tip.appendChild(s);}
  if(m[3]){var i=document.createElement('i');i.textContent=m[3];tip.appendChild(i);}
  pts.forEach(function(p){p.classList.toggle('on',p.getAttribute('data-m')===el.getAttribute('data-m'));});
});});
// The card picture opens full screen; a tap anywhere closes it.
var open=document.getElementById('cardopen'),view=document.getElementById('viewer');
if(open&&view){open.addEventListener('click',function(){var big=view.querySelector('img'),small=open.querySelector('img');if(big&&small&&!big.src)big.src=small.src;view.hidden=false;});view.addEventListener('click',function(){view.hidden=true;});
  document.addEventListener('keydown',function(e){if(e.key==='Escape')view.hidden=true;});}
})();
'''


def _e(x):
    return _html.escape(str(x if x is not None else ''), quote=True)


def _l(x):
    return [i for i in x if i] if isinstance(x, list) else []


def _s(d, *keys):
    for k in keys:
        d = d.get(k) if isinstance(d, dict) else None
    return d if d is not None else ''


def _num(x):
    try:
        n = float(x)
        return None if n != n else max(0, min(100, int(round(n))))
    except (TypeError, ValueError):
        return None


def _cap(t):
    t = str(t or '')
    return t[:1].upper() + t[1:]


def _chips(items):
    items = [i for i in _l(items) if isinstance(i, str)]
    return '<div class="pills">' + ''.join('<span class="pill">' + _e(i) + '</span>' for i in items) + '</div>' if items else ''


def _block(title, inner):
    return '<h3>' + _e(title) + '</h3>' + inner if inner else ''


def _ev(evidence, label='', extra=''):
    """The evidence behind a finding: small grey bullet points under it, no heading and no box."""
    ev = [x for x in _l(evidence) if isinstance(x, str)]
    if not ev and not extra:
        return ''
    # Each line starts with a capital, as a sentence would ("your May 2018 messages…" came through lower-case).
    return '<ul class="ev">' + ''.join('<li>' + _e(x[:1].upper() + x[1:]) + '</li>' for x in ev) + extra + '</ul>'


def _items(xs, details=True):
    """Title-and-detail items, each its title in bold, its detail under it, and its evidence folded away."""
    out = ''
    for x in _l(xs):
        if isinstance(x, str):
            x = {'title': x}
        if isinstance(x, dict) and x.get('title'):
            d = _cap(x.get('detail')) if details else ''
            out += ('<div class="it"><b>' + _e(x['title']) + '</b>' + ('<span>' + _e(d) + '</span>' if d else '')
                    + _ev(x.get('evidence')) + '</div>')
    return out


def _pair(good_title, good, hard_title, hard):
    g, h = _items(good), _items(hard)
    if not g and not h:
        return ''
    box = lambda cls, mark, t, inner: ('<div class="box ' + cls + '"><h4><i>' + mark + '</i>' + _e(t) + '</h4>' + inner + '</div>') if inner else ''
    return '<div class="cols">' + box('good', '✓', good_title, g) + box('hard', '!', hard_title, h) + '</div>'


def _wrap(label, width=13):
    words, lines, cur = str(label).split(), [], ''
    for w in words:
        if cur and len(cur) + 1 + len(w) > width:
            lines.append(cur)
            cur = w
        else:
            cur = (cur + ' ' + w).strip()
    if cur:
        lines.append(cur)
    return lines[:2] if len(lines) <= 2 else [lines[0], ' '.join(lines[1:])]


def _radar(mots, top):
    import math
    mots = [m for m in _l(mots) if isinstance(m, dict) and m.get('name') and _num(m.get('score')) is not None][:10]
    if len(mots) < 3:
        return ''
    tops = set(t for t in _l(top) if isinstance(t, str))
    n, R = len(mots), 92
    f = lambda v: ('%.1f' % v).rstrip('0').rstrip('.')
    ang = lambda i: -math.pi / 2 + 2 * math.pi * i / n
    out = []
    for ring in (25, 50, 75, 100):
        r = R * ring / 100
        out.append('<polygon points="%s" fill="none" stroke="#e3dae9" stroke-width="1"/>' % ' '.join(f(r * math.cos(ang(i))) + ',' + f(r * math.sin(ang(i))) for i in range(n)))
    for i in range(n):
        out.append('<line x1="0" y1="0" x2="%s" y2="%s" stroke="#e3dae9" stroke-width="1"/>' % (f(R * math.cos(ang(i))), f(R * math.sin(ang(i)))))
    shape = ' '.join(f(R * _num(m['score']) / 100 * math.cos(ang(i))) + ',' + f(R * _num(m['score']) / 100 * math.sin(ang(i))) for i, m in enumerate(mots))
    out.append('<polygon points="%s" fill="var(--c)" fill-opacity=".16" stroke="var(--c)" stroke-width="2" stroke-linejoin="round"/>' % shape)
    for i, m in enumerate(mots):
        s, a, hot = _num(m['score']), ang(i), m['name'] in tops
        x, y = R * s / 100 * math.cos(a), R * s / 100 * math.sin(a)
        data = _e(json.dumps([m['name'], s, m.get('meaning') or '', m.get('line') or ''], ensure_ascii=False))
        out.append(('<circle class="pt" data-m="%s" cx="%s" cy="%s" r="7" fill="var(--c)" stroke="#fff" stroke-width="2"/>' if hot else '<circle class="pt" data-m="%s" cx="%s" cy="%s" r="3.5" fill="#fff" stroke="#9a8fa6" stroke-width="1.5"/>') % (data, f(x), f(y)))
        out.append('<circle class="hit" data-m="%s" cx="%s" cy="%s" r="15"/>' % (data, f(x), f(y)))
        lx, ly = (R + 14) * math.cos(a), (R + 14) * math.sin(a)
        anchor = 'middle' if abs(math.cos(a)) < 0.3 else ('start' if math.cos(a) > 0 else 'end')
        lines = _wrap(m['name'])
        dy0 = -13 * (len(lines) - 1) if math.sin(a) < -0.3 else (10 if math.sin(a) > 0.3 else 4 - 6.5 * (len(lines) - 1))
        spans = ''.join('<tspan x="%s" dy="%s">%s</tspan>' % (f(lx), f(dy0) if k == 0 else '13', _e(t)) for k, t in enumerate(lines))
        out.append('<text class="%s" data-m="%s" x="%s" y="%s" text-anchor="%s">%s</text>' % ('top' if hot else '', data, f(lx), f(ly), anchor, spans))
        w, h = max(len(t) for t in lines) * 7 + 14, 13 * len(lines) + 14
        x0 = lx - w / 2 if anchor == 'middle' else (lx - 7 if anchor == 'start' else lx - w + 7)
        out.append('<rect class="hit" data-m="%s" x="%s" y="%s" width="%s" height="%s"/>' % (data, f(x0), f(ly + dy0 - 13), f(w), f(h)))
    return ('<svg class="radar" viewBox="-200 -150 400 300" role="img" aria-label="What motivates you: your top three are highlighted">' + ''.join(out) + '</svg>'
            '<div class="tip" id="mtip" aria-live="polite">Tap any point or name on the chart to see its score and what it means.</div>')


def _motive_boxes(mots, top):
    """Under the radar: the top three, each its score, meaning and, where written, their own line."""
    ms = [m for m in _l(mots) if isinstance(m, dict) and m.get('name') and _num(m.get('score')) is not None]
    if len(ms) < 5:
        return ''
    by = {m['name']: m for m in ms}
    tops = [by[t] for t in _l(top) if isinstance(t, str) and t in by][:3] or sorted(ms, key=lambda m: -_num(m['score']))[:3]
    box = lambda m, hi: ('<div class="mot%s"><b>%s<i>%d</i></b>%s</div>' % (' hi' if hi else '', _e(m['name']), _num(m['score']),
                         '<span>' + _e(m.get('line') or m.get('meaning')) + '</span>' if (m.get('line') or m.get('meaning')) else ''))
    return ('<p class="motlabel">Strongest</p><div class="mots">' + ''.join(box(m, True) for m in tops) + '</div>'
)


def _overview(v, card_png=None):
    # The card sits beside "You are most like", big enough to want a tap, and opens full size
    # (README "The card in the Overview"); it is embedded here once.
    card = ('<button type="button" class="cardbtn" id="cardopen" aria-label="Open your Psyche Card full size">'
            '<img class="cardpic" alt="Your Psyche Card" src="data:image/png;base64,' + card_png + '"><em>Your Psyche Card<br>Tap to open</em></button>') if card_png else ''
    hero = ''
    if _s(v, 'character') or card:
        text = (('<small>You are most like</small><b>' + _e(_s(v, 'character')) + '</b>'
                 + ('<span>' + _e(_s(v, 'source')) + '</span>' if _s(v, 'source') else '') + ('<p>' + _e(_s(v, 'why')) + '</p>' if _s(v, 'why') else ''))
                if _s(v, 'character') else '')
        # The card floats beside the box and the start of the Executive summary (laptop), or sits
        # inside the box's top right where the text wraps round it (phone): one picture either way.
        hero = card + ('<div class="hero%s">%s</div>' % (' withcard' if card else '', text) if text else '')
    paras = [p for p in _l(_s(v, 'summaryFull')) if isinstance(p, str)] or [x for x in [_s(v, 'summary')] if x]
    summ = ''.join('<p%s>%s</p>' % (' class="intro"' if i == 0 else '', _e(p)) for i, p in enumerate(paras))
    # As psycheai.io shows them: the name, its line, the evidence, then where it shows up, under the
    # heading's one-line definition (README "Signature patterns as the site writes them").
    pats = ''.join('<div class="pat"><span class="n">%d</span><div><b>%s</b>%s%s%s</div></div>' % (
        i + 1, _e(p.get('name')), '<span class="soft">' + _e(p.get('line')) + '</span>' if p.get('line') else '',
        _ev(p.get('evidence')),
        ('<div class="areas"><span>Shows up in</span>' + ''.join('<i>' + _e(x) + '</i>' for x in _l(p.get('showsUpIn')) if isinstance(x, str)) + '</div>') if _l(p.get('showsUpIn')) else '')
        for i, p in enumerate(p for p in _l(_s(v, 'patterns')) if isinstance(p, dict) and p.get('name')))
    if pats:
        pats = '<p class="soft def">The behaviours that explain the most about you.</p>' + pats
    return hero + _block('Executive summary', summ) + _block('Your signature patterns', pats), _s(v, 'character')


def _who(v, nickname=''):
    letters = [l for l in _l(_s(v, 'mbti')) if isinstance(l, dict) and l.get('letter')]
    types = ''.join(l.get('letter', '') for l in letters)
    mbti = (('<div class="type"><b>' + _e(types) + '</b>' + ('<span>' + _e(nickname) + '</span>' if nickname else '') + '</div>') if types else '') + ''.join(
        '<div class="it"><b><span class="letter">' + _e(l.get('letter')) + '</span>' + _e(l.get('name'))
        + (' <span class="pill">' + _e(l.get('strength')) + '</span>' if l.get('strength') else '') + '</b>'
        + ('<span>' + _e(l.get('reading') or l.get('line')) + '</span>' if (l.get('reading') or l.get('line')) else '')
        + ('<span class="where">In practice: ' + _e(l.get('inPractice')) + '</span>' if l.get('inPractice') else '') + _ev(l.get('evidence')) + '</div>'
        for l in letters) + ('<p class="fine">' + _e(_s(v, 'mbtiCaveat')) + '</p>' if _s(v, 'mbtiCaveat') else '')
    five = ''
    for t in _l(_s(v, 'bigFive')):
        s = _num(t.get('score')) if isinstance(t, dict) else None
        if s is None:
            continue
        five += ('<div class="slider"><div class="top"><b>' + _e(t.get('trait')) + (' <em>· ' + _e(t.get('band')) + '</em>' if t.get('band') else '') + '</b>'
                 '<span class="score">' + str(s) + '</span></div><div class="track"><i style="width:' + str(s) + '%"></i><u style="left:' + str(s) + '%"></u></div>'
                 + ('<div class="soft">' + _e(t.get('reading') or t.get('line')) + '</div>' if (t.get('reading') or t.get('line')) else '') + _ev(t.get('evidence')) + '</div>')
    wb = _s(v, 'wellbeing') or {}
    band = lambda a: '<span class="band" style="color:%s;background:%s">%s</span>' % (W_BANDS.get(a.get('band'), ('#5a4f66', '#f1edf4')) + (_e(a.get('band')),))
    well = ''.join('<div class="it"><b>' + _e(a.get('area')) + band(a)  + '</b>'
                   + ('<span>' + _e(a.get('reading')) + '</span>' if a.get('reading') else '') + _ev(a.get('evidence')) + '</div>'
                   for a in _l(_s(wb, 'areas')) if isinstance(a, dict) and a.get('area'))
    together = _s(wb, 'together') or _s(wb, 'summary')
    well += ('<div class="callout"><b>Taken together.</b> ' + _e(together) + '</div>') if together else ''
    fives = sorted([t for t in _l(_s(v, 'bigFive')) if isinstance(t, dict) and _num(t.get('score')) is not None], key=lambda t: -_num(t.get('score')))
    tease = ' · '.join(([types] if types else []) + ['%s %d' % (t.get('trait'), _num(t.get('score'))) for t in fives[:2]])
    return _block('MBTI', mbti) + _block('Big Five', five) + _block('Wellbeing', well), tease


def _drives(v):
    radar = _radar(_s(v, 'motivators'), _s(v, 'top')) + _motive_boxes(_s(v, 'motivators'), _s(v, 'top'))
    reading = '<div class="callout">' + _e(_s(v, 'reading')) + '</div>' if _s(v, 'reading') else ''
    vb_full = _l(_s(v, 'valuesFull')) + _l(_s(v, 'beliefsFull'))
    vb = _items(vb_full) if vb_full else _chips(_l(_s(v, 'values')) + _l(_s(v, 'beliefs')))
    ints = _items(_s(v, 'interestsFull')) if _l(_s(v, 'interestsFull')) else _chips(_s(v, 'interests'))
    tease = ' · '.join(t for t in _l(_s(v, 'top')) if isinstance(t, str))
    return _block('What motivates you', radar + reading) + _block('Values and beliefs', vb) + _block('Interests', ints), tease


def _langs(xs):
    return ''.join('<div class="lang"><span class="ico">' + _e(l.get('icon') or '💗') + '</span><div><b>' + _e(l.get('language')) + '</b> '
                   + '<span class="pill' + (' prim' if l.get('strength') == 'primary' else '') + '">' + _e(l.get('strength') or 'secondary') + '</span>'
                   + ('<div class="soft">' + _e(l.get('line')) + '</div>' if l.get('line') else '')
                   + _ev([l.get('why')] if l.get('why') and not _says_same(l.get('why'), l.get('line')) else []) + '</div></div>'
                   for l in _l(xs) if isinstance(l, dict) and l.get('language'))


def _says_same(a, b):
    """Whether two lines say the same thing (most of the shorter one's words in the other): shown once."""
    wa, wb = set(re.findall(r"[\w']+", str(a or '').lower())), set(re.findall(r"[\w']+", str(b or '').lower()))
    return bool(wa and wb) and len(wa & wb) >= 0.7 * min(len(wa), len(wb))


def _connect(v):
    ll = _s(v, 'loveLanguages') or {}
    attach = ''
    if _s(v, 'attachment'):
        read_from = _ev(_s(v, 'derivedFrom'))
        attach = ('<p class="lead">' + _e(_s(v, 'attachment')) + '</p>' + ('<p>' + _e(_s(v, 'attachmentTone')) + '</p>' if _s(v, 'attachmentTone') else '')
                  + ('<p class="soft">' + _e(_s(v, 'attachmentReading')) + '</p>' if _s(v, 'attachmentReading') else '') + read_from
                  + _items(_s(v, 'implications')) + ('<p class="fine">' + _e(_s(v, 'attachmentCaveat')) + '</p>' if _s(v, 'attachmentCaveat') else ''))
    conflict = '<p>' + _e(_s(v, 'conflict')) + '</p>' if _s(v, 'conflict') else ''
    friction = _pair('What you bring', _s(v, 'bring') or _s(v, 'atYourBest'), 'Where it gets hard', _s(v, 'hard') or _s(v, 'watchFor'))
    suits = (('<p>' + _e(_s(v, 'whoSuits') or _s(v, 'bestPartner')) + '</p>') if (_s(v, 'whoSuits') or _s(v, 'bestPartner')) else '') \
        + _pair('What you actually need', _s(v, 'needs') or _s(v, 'partnerNeeds'), 'What to be careful of', _s(v, 'careful') or _s(v, 'carefulOf'))
    love = _block('How you want to be loved', _langs(_s(ll, 'receiving'))) + _block('How you show love', _langs(_s(ll, 'giving'))) \
        + ('<p class="fine">' + _e(_s(ll, 'caveat')) + '</p>' if _s(ll, 'caveat') else '')
    first = next((l.get('language') for l in _l(_s(ll, 'receiving')) if isinstance(l, dict)), '')
    tease = ' · '.join(x for x in [first, _s(v, 'attachment')] if x)
    return (love + _block('Attachment style', attach) + _block('How you deal with conflict', conflict)
            + _block('Strengths and friction', friction) + _block('Who suits you', suits)), tease


def _work(v):
    situation = '<p class="intro" style="margin-top:14px">' + _e(_s(v, 'situation')) + '</p>' if _s(v, 'situation') else ''
    edge = ''
    if _s(v, 'edge'):
        edge = ('<div class="edge"><small>Your edge</small><b>' + _e(_s(v, 'edge')) + '</b>' + ('<p>' + _e(_s(v, 'edgeDetail')) + '</p>' if _s(v, 'edgeDetail') else '')
                + _ev(_s(v, 'edgeEvidence')) + '</div>')
    others = _s(v, 'others') or ([x for x in _l(_s(v, 'strengths'))] + (['Not yet using: ' + _s(v, 'underused')] if _s(v, 'underused') else []))
    holding = _s(v, 'holding') or ([_s(v, 'holdingBack')] if _s(v, 'holdingBack') else [])
    sides = _pair('Your other strengths', others, 'What holds you back', holding)
    style = ''.join('<div class="it"><b>' + t + '</b><span>' + _e(_s(v, k)) + '</span></div>' for k, t in (('workStyle', 'How you work best'), ('watchOuts', 'Watch out for')) if _s(v, k))
    fit = _pair('Suits you best', _s(v, 'suitsFull') or _s(v, 'suits'), 'Likely to drain you', _s(v, 'drainsFull') or _s(v, 'drains'))
    return situation + edge + sides + _block('Your working style', style) + _block('Careers that suit you', fit), _s(v, 'edge')


def _together(v):
    build = _items(_s(v, 'build') or _s(v, 'buildOn'))
    dev = ''
    for d in _l(_s(v, 'develop')):
        if not isinstance(d, dict) or not d.get('title'):
            continue
        signs = [x for x in _l(d.get('signs')) if isinstance(x, str)]
        more = (''.join('<li>' + ('<b>Early signs:</b> ' if not k else '') + _e(x.strip().rstrip(';')) + '</li>' for k, x in enumerate(signs))
                + ('<li><b>Counter-move:</b> ' + _e(d.get('counterMove')) + '</li>' if d.get('counterMove') else '')
                + ('<li><b>Ask yourself:</b> ' + _e(d.get('reflect')) + '</li>' if d.get('reflect') else ''))
        dev += ('<div class="it"><b>' + _e(d['title']) + '</b>' + ('<span>' + _e(d.get('detail')) + '</span>' if d.get('detail') else '')
                + (_ev([], '', more) if more else '') + '</div>')
    if not dev:
        dev = _items(_s(v, 'workOn'))
    steps = [p for p in _l(_s(v, 'steps')) if isinstance(p, dict) and p.get('step')] or [p for p in _l(_s(v, 'plan')) if isinstance(p, dict) and p.get('step')]
    plan = ''
    for when in ('This week', 'This quarter', 'This year'):
        here = [p for p in steps if p.get('when') == when]
        if here:
            plan += '<div><small>' + when + '</small>' + ''.join(
                '<p><b>' + _e(p['step']) + '</b>' + ('<span>' + _e(p.get('detail')) + '</span>' if p.get('detail') else '')
                + ('<em>' + _e(p.get('from')) + '</em>' if p.get('from') else '') + '</p>' for p in here) + '</div>'
    tease = ' · '.join(t for t in ([d.get('title') for d in _l(_s(v, 'develop')) if isinstance(d, dict)] or _l(_s(v, 'workOn'))) if isinstance(t, str))[:90]
    two = ('<div class="cols">' + ('<div class="box good"><h4><i>✓</i>Build on</h4>' + build + '</div>' if build else '')
           + ('<div class="box hard"><h4><i>!</i>Develop</h4>' + dev + '</div>' if dev else '') + '</div>') if build or dev else ''
    return two + _block('Your plan', '<div class="plan">' + plan + '</div>' if plan else ''), tease


W_BUILD = {'overview': _overview, 'whoYouAre': _who, 'whatDrivesYou': _drives, 'howYouConnect': _connect, 'howYouWork': _work, 'puttingItTogether': _together}
W_CHEV = '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'


def report_html(view, name='', when='', card_png=None, pages=None, doc_title=None, bonus=None, sample=None):
    """The whole report as one self-contained HTML file, from view (full, with the evidence, when given), and
    the roast (bonus, from the report kept here) as its appendix, closed until they open it (README "The roast in the appendix")."""
    if not isinstance(view, dict):
        return None
    ov = view.get('overview') if isinstance(view.get('overview'), dict) else {}
    parts, nav, i = [], [], 0
    for key, title, colour in W_PARTS:
        data = view.get(key) if isinstance(view.get(key), dict) else {}
        inner, tease = (_who(data, ov.get('nickname') or '') if key == 'whoYouAre' else _overview(data, None if sample else card_png) if key == 'overview' else W_BUILD[key](data))
        if not inner:
            continue
        sid = 'p%d' % i
        parts.append('<section class="part%s" id="%s" style="--c:%s" data-section="%s"><button type="button" aria-expanded="%s">'
                     '<span class="num">%02d</span><span class="ttl">%s</span><span class="tease">%s</span>%s</button><div class="body">%s</div></section>'
                     % (' open' if i == 0 else '', sid, colour, _e(title), 'true' if i == 0 else 'false', i, _e(title), _e(tease), W_CHEV, inner))
        nav.append('<a href="#%s" style="--c:%s" aria-current="%s"><i>%02d</i>%s</a>' % (sid, colour, 'true' if i == 0 else 'false', i, _e(title)))
        i += 1
    if not parts:
        return None
    c = view.get('confidence') if isinstance(view.get('confidence'), dict) else {}
    score = _num(c.get('score'))
    m = view.get('method') if isinstance(view.get('method'), dict) else {}
    method = ''
    if score is not None or m:
        method = ('<div class="method" style="--c:#7b3fa0"><h3 style="margin-top:0">How this was read</h3>'
                  + ('<div class="big"><b>%d%%</b><span class="soft">confidence%s</span></div><div class="bar"><i style="width:%d%%"></i></div>'
                     % (score, (' · ' + _e(c.get('level'))) if c.get('level') else '', score) if score is not None else '')
                  + ('<p>' + _e(m.get('rationale')) + '</p>' if m.get('rationale') else '')
                  + _ev(c.get('basedOn'))
                  + '</div>')
    roast = ''
    if isinstance(bonus, dict) and isinstance(bonus.get('harsh'), str) and bonus['harsh'].strip():
        paras = lambda t: ''.join('<p>' + _e(x.strip()) + '</p>' for x in re.split(r'\n\s*\n', t) if x.strip())
        roast = ('<details class="roast" id="roast"><summary><span class="badge">Appendix</span><b>Your roast 🔥</b>'
                 '<span class="soft">Deliberately unkind, and just for you. Not on your card, never in a link. Tap to open.</span></summary>'
                 '<p class="salt">🧂 An AI being deliberately harsh about your data: not an assessment and not a diagnosis. Argue with it, and if any of it lands heavier than that, talk to someone you trust or a professional.</p>'
                 '<div class="burn"><h3>🔥 The least charitable assessment of you</h3>' + paras(bonus['harsh']) + '</div>'
                 + ('<div class="kind"><h3>💬 What an honest friend would tell you</h3>' + paras(bonus['advice']) + '</div>' if isinstance(bonus.get('advice'), str) and bonus['advice'].strip() else '')
                 + '</details>')
    first = str(name or '').split(' ')[0]
    title = (first + '’s Psyche Report') if first else 'Your Psyche Report'
    facts = ' · '.join(x for x in ['%d parts' % len(parts), ('%d pages' % pages) if pages else '', ('%d%% signal strength' % score) if score is not None else ''] if x)
    banner = ('<header class="banner" id="top">' + W_LOGO + '<div class="row"><div class="txt"><div class="facts">' + _e(facts) + '</div><h1>' + _e(title) + '</h1>'
              + '<p class="lede">The explanation behind your Psyche Card: what each result means, the evidence for it in your own data, and what to do with it.</p>'
              + ('<div class="sub">' + _e(when) + '</div>' if when else '')
              + '</div></div></header>')
    # A sample (README "A sample report"): the card large at the top, with a line saying whose it is and how to get one's own.
    if sample and card_png:
        banner += ('<div class="sample"><p>' + _e(sample.get('note') or '') + '</p>'
                   '<button type="button" class="cardbtn top" id="cardopen" aria-label="Open the Psyche Card full size">'
                   '<img class="cardpic" alt="A sample Psyche Card" src="data:image/png;base64,' + card_png + '"><em>Tap to open</em></button>'
                   + ('<p class="get">' + _e(sample['cta']) + '</p>' if sample.get('cta') else '') + '</div>')
    bar = '<nav aria-label="Sections">' + ''.join(nav) + '<button type="button" data-fold>Collapse all ▲</button></nav>'
    # The picture is embedded once, in the Overview; the full-screen view borrows it when opened.
    viewer = '<div class="viewer" id="viewer" role="dialog" aria-label="Your Psyche Card" hidden><img alt="Your Psyche Card"><span>Tap to close</span></div>' if card_png else ''
    foot = ('<footer><b>PsycheAI</b> · psycheai.io<br>' + ('A sample report for a fictional reader. Yours is made in your own Muse workspace, and PsycheAI keeps no copy of it.'
            if sample else 'This file was made in your own Muse workspace. PsycheAI keeps no copy of your report.') + '</footer>')
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<title>' + _e(doc_title or title) + '</title><style>' + W_CSS + '</style></head><body><div class="wrap">' + banner + bar + ''.join(parts) + method + roast
            + '<button type="button" class="foldall" data-fold>Collapse all ▲</button>' + foot + '</div>' + viewer + '<script>' + W_JS + '</script></body></html>')


# ---------- the phone check (README "The phone check") ----------
# A test page, not the report: shown once when someone asks for it, it measures
# what the chat app lets a widget do (see the chat scroll, scroll the chat to a
# point, collapse without the chat jumping), so the report's phone behaviour can
# be built on what works rather than guesses. It sends nothing anywhere.
PROBE_HTML = '''<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Phone check</title><style>
:root{color-scheme:light}*{box-sizing:border-box;font-family:inherit}
html,body{margin:0;background:#faf7fb}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;color:#241a2e;font-size:15px;line-height:1.45}
main{max-width:640px;margin:0 auto;padding:12px}
h1{font-size:17px;margin:2px 4px 10px}
.card{background:#fff;border:1px solid #e2d8e9;border-radius:14px;padding:12px 14px;margin:0 0 12px}
.res div{display:flex;justify-content:space-between;gap:10px;padding:5px 0;border-bottom:1px solid #f0eaf4;font-size:14px}
.res div:last-child{border-bottom:0}
.res b{font-weight:700;text-align:right}
.ok{color:#2f7d5b}.no{color:#b3261e}.wait{color:#9a5b12}
button{all:unset;box-sizing:border-box;display:block;width:100%;text-align:center;padding:12px;border-radius:12px;background:#7b3fa0;color:#fff;font-weight:700;margin:8px 0;cursor:pointer;touch-action:manipulation}
.step{font-size:14px;color:#5a4f66}
.tall{height:1400px;border-radius:12px;background:repeating-linear-gradient(#f3e9f8 0 60px,#fff 60px 120px);display:flex;align-items:center;justify-content:center;color:#6b6076;font-size:13px}
.tall.gone{height:0;overflow:hidden}
#target{padding:14px;border-radius:12px;background:#e3f4ec;border:1px solid #bfe3cf;font-weight:700}
</style></head><body><main>
<h1>Phone check</h1>
<div class="card res" id="res"></div>
<div class="card"><p class="step"><b>1.</b> Scroll the chat up and down a little, past this box and back.</p>
<p class="step"><b>2.</b> Tap "Jump to the green box". It's far below; see whether the chat moves there.</p>
<button id="jump" type="button">Jump to the green box</button>
<p class="step"><b>3.</b> Scroll down to "Collapse the block above" and tap it. Note whether the button stays under your finger.</p>
<p class="step"><b>4.</b> Tap the green box at the very bottom too.</p>
<p class="step"><b>5.</b> Come back up and take a screenshot of the results above.</p></div>
<div class="tall" id="block">A tall block (1,400px) to collapse in step 3</div>
<button id="collapse" type="button">Collapse the block above</button>
<div style="height:900px"></div>
<div id="target">The green box: step 2 jumps here. Tap it (step 4).</div>
<div style="height:200px"></div>
</main><script>
(function(){
var r={}, order=[];
function set(k,v,c){if(order.indexOf(k)<0)order.push(k);r[k]=[v,c||''];draw();}
function draw(){var el=document.getElementById('res');el.innerHTML='';order.forEach(function(k){var d=document.createElement('div');var a=document.createElement('span');a.textContent=k;var b=document.createElement('b');b.textContent=r[k][0];if(r[k][1])b.className=r[k][1];d.appendChild(a);d.appendChild(b);el.appendChild(d);});}
var inFrame=false;try{inFrame=window.top!==window;}catch(e){inFrame=true;}
set('In a frame',inFrame?'yes':'no');
set('Frame size',innerWidth+' x '+innerHeight+' px');
set('Page height',document.documentElement.scrollHeight+' px');
set('Frame grows to the page',document.documentElement.scrollHeight<=innerHeight+4?'yes (the chat scrolls)':'no (it scrolls inside)');
set('Touch screen',(window.matchMedia&&matchMedia('(hover: none) and (pointer: coarse)').matches)?'yes':'no');
set('Taps received','none yet: tap the buttons and the page lower down','wait');
set('1. Sees the chat scroll','waiting: scroll a little','wait');
set('2. Jump moves the chat','not tried yet','wait');
set('3. Collapse keeps your place','not tried yet','wait');
// Every tap the page receives, wherever it lands, with how far down the page it was:
// if taps lower down never arrive, the chat app isn't passing them to the widget.
var taps=0,lowest=0,sizes=0;
function tapAt(y){taps++;lowest=Math.max(lowest,Math.round(y));set('Taps received',taps+' (lowest at '+lowest+' px of '+document.documentElement.scrollHeight+')',lowest>innerHeight0?'ok':'wait');}
var innerHeight0=innerHeight;
if(window.PointerEvent)document.addEventListener('pointerdown',function(e){tapAt(e.pageY);},true);
else document.addEventListener('touchstart',function(e){if(e.touches&&e.touches[0])tapAt(e.touches[0].pageY);},{capture:true,passive:true});
window.addEventListener('resize',function(){sizes++;set('Frame size',innerWidth+' x '+innerHeight+' px (changed '+sizes+' times, started '+innerHeight0+')');});
var moved=0,last=null,block=document.getElementById('block');
var hasIO='IntersectionObserver' in window;
if(!hasIO)set('1. Sees the chat scroll','no (no IntersectionObserver)','no');
var th=[];for(var i=0;i<=40;i++)th.push(i/40);
var target=document.getElementById('target');
// How much of the tall block is on screen changes as the chat scrolls, even when the
// frame itself never scrolls: that is what tells a widget where the reader is.
if(hasIO){
  new IntersectionObserver(function(es){es.forEach(function(e){
    if(last!==null&&Math.abs(e.intersectionRatio-last)>0.01)moved++;last=e.intersectionRatio;
    set('1. Sees the chat scroll',moved>0?'yes ('+moved+' changes seen)':'waiting: scroll a little',moved>0?'ok':'wait');
  });},{threshold:th}).observe(block);
  new IntersectionObserver(function(es){es.forEach(function(e){
    if(e.isIntersecting&&window.__jumped&&!window.__jumpDone){window.__jumpDone=true;set('2. Jump moves the chat','yes: the green box came into view','ok');}
  });},{threshold:[0,0.5]}).observe(target);
}
document.getElementById('jump').addEventListener('click',function(){
  window.__jumped=true;window.__jumpDone=false;var y0=window.scrollY;
  try{target.scrollIntoView({block:'start',behavior:'smooth'});}catch(e){target.scrollIntoView(true);}
  setTimeout(function(){if(!window.__jumpDone)set('2. Jump moves the chat',window.scrollY!==y0?'inside the frame only':'no: nothing moved','no');},1500);
});
document.getElementById('collapse').addEventListener('click',function(){
  block.classList.add('gone');
  set('3. Collapse keeps your place','tapped: tell me whether the button stayed under your finger or the chat jumped','wait');
});
})();
</script></body></html>'''


def local_report(r):
    """The report as one HTML file in out/, to attach right after the card (README "The report as a file")."""
    out = {'sections': r.get('sections', [])}
    kept = read_first([REPORT, REPORT_KEPT]) or {}
    card = None
    try:
        pics = sorted(f for f in os.listdir(OUT) if f.lower().endswith('.png'))
        if pics:
            with open(os.path.join(OUT, pics[-1]), 'rb') as f:
                card = base64.b64encode(f.read()).decode()
    except OSError:
        pass
    try:
        when = datetime.fromtimestamp(os.path.getmtime(LAST)).strftime('%-d %B %Y')
    except (OSError, ValueError):
        when = ''
    # The PDF's page count, from its page tree, for the banner (the PDF is saved here at publish).
    pages = None
    try:
        pdfs = [f for f in os.listdir(OUT) if f.lower().endswith('.pdf')]
        if pdfs:
            with open(os.path.join(OUT, pdfs[0]), 'rb') as f:
                counts = [int(n) for n in re.findall(rb'/Count\s+(\d+)', f.read())]
            pages = max(counts) if counts else None
    except (OSError, ValueError):
        pages = None
    page = report_html(r.get('full') or r.get('view'), kept.get('name') or '', when, card, pages, file_label('Psyche Report'),
                       (kept.get('report') or {}).get('bonus') if isinstance(kept.get('report'), dict) else None)
    if not page:
        return out
    try:
        os.makedirs(OUT, exist_ok=True)
        for old in os.listdir(OUT):
            if old.lower().endswith('.html'):
                os.remove(os.path.join(OUT, old))
        path = os.path.join(OUT, file_label('Psyche Report') + '.html')
        with open(path, 'w', encoding='utf-8') as f:
            f.write(page)
        os.chmod(path, 0o600)
        out['report'] = path
        out['show'] = 'Attach report, this file, right after the card: it is their whole Psyche Report. No widget, and no PDF unless they ask for it.'
    except OSError:
        pass
    return out


def local_ready(r):
    """show ready: the card and the report file saved, and What's next, in one call; the PDF fetched
    and the read's timings sent beside them, so none of it waits on the others (README "Straight to the card")."""
    side = [threading.Thread(target=local_pdf, args=(r,)), threading.Thread(target=send_timing)]
    for t in side:
        t.start()
    card, report = local_card(r), local_report(r)
    for t in side:
        t.join(15)
    # Short, so a helper passes it on as it is: the two files (named only once saved, with their size:
    # this is the check, nothing to list after it) and What's next. The report's text is in the file.
    files = {}
    for key, part in (('card', card), ('report', report)):
        f = (part.get('file') or part.get('report')) if isinstance(part, dict) else None
        if f and os.path.exists(f):
            files[key] = {'file': f, 'bytes': os.path.getsize(f)}
    out = {'say': 'Your Psyche Card and Report are ready.', **files,
           'next': {'nextStep': r.get('nextStep'), 'askIdeas': r.get('askIdeas')}}
    # What was read, for the receipt under the report (counts only, from the last collect).
    last = read_first([LAST_COLLECT]) or {}
    if isinstance(last.get('read'), dict):
        out['read'] = {k: v for k, v in last['read'].items() if k in ('stories', 'posts', 'comments', 'threads') and isinstance(v, int)}
    if len(files) < 2:
        out['missing'] = [k for k in ('card', 'report') if k not in files]
    return out


PARTS = {
    'ready': local_ready,
    'card': local_card,
    'summary': local_report,
    'pdf': local_pdf,
    'next': lambda r: {'nextStep': r.get('nextStep'), 'askIdeas': r.get('askIdeas')},
}


def saved(out):
    """Keep a publish result here and say only that it's saved, and its parts."""
    # The last Psyche's PDF goes, so only this one's can be attached: show pdf fetches it.
    shutil.rmtree(OUT, ignore_errors=True)
    write_private([LAST], out)
    # The PDF (its link lasts 30 minutes) is fetched by show ready, beside the card and report,
    # or by show pdf if that comes first: never on the way to the card.
    return {'ok': True, 'saved': True, 'parts': list(PARTS)}

# ---------- the digest (README "The digest in the workspace") ----------
# The summary of their own words a read is written from, in the reading
# plan's shares, kept instead of the raw pulls. Muse writes it; this checks it.

DIGEST_LIMITS = {
    'normal': {'total': 275000, 'Messages': 115000, 'Context': 60000, 'Interests': 16000, 'Comments': 16000},
    'deep': {'total': 1050000, 'Messages': 450000, 'Context': 220000, 'Interests': 31000, 'Comments': 41000},
}
SECTIONS = ['Posts and stories', 'Comments', 'Messages', 'Interests']
LEAKS = [
    ('a handle', re.compile(r'(?<![\w@])@[A-Za-z0-9._]{2,30}')),
    ('a link', re.compile(r'https?://|www\.', re.I)),
    ('an email', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')),
    ('a phone number', re.compile(r'\+?\d[\d ()\-]{7,}\d')),
]
DATED = re.compile(r'^\d{4}-\d{2}-\d{2}\b')
STAMP = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2})?\s*')
TIMED = re.compile(r'^\d{4}-\d{2}-\d{2}[ T]\d{1,2}:\d{2}\b')
# The plan's share for each section, to say where a Deep Psyche has room for more.
SHARES = {'Posts and stories': 85000, 'Messages': 110000, 'Comments': 15000, 'Interests': 15000}
# What one read reaches (README "Targets, not ceilings"): a first read about
# 110,000 characters (with what replies answer), each later one about 40,000 more, towards the plan's shares.
SHORT = 0.7                 # under this share of a target is a problem, not room


def targets(reads, messages_in):
    k = max(0, reads - 1)
    posts = min(85000, 35000 + 15000 * k)
    top, rest = min(16000, 9000 + 2500 * k), min(6500, 2300 + 1500 * k)
    if not messages_in:
        posts = min(195000, 80000 + 40000 * k)
    # Conversations as psycheai.io's digest takes them (README "Conversations as the site reads them"):
    # the 10 busiest, up to 5 more when those run short, the room shared by how much is in each,
    # none over `cap`, and room a short one leaves going to the ones with more.
    return {'posts': posts, 'top': top, 'rest': rest, 'convos': 4 * top + 6 * rest, 'cap': max(15000, top)}


CONVO_TOP, CONVO_SPARE = 10, 5


def convo_quotas(sizes, total, cap):
    """Each conversation's share of `total`: by how much is in it, none over cap or over what it has."""
    quota, left, open_ = [0] * len(sizes), total, [i for i, n in enumerate(sizes) if n > 0]
    while open_ and left > 0:
        pool = sum(sizes[i] for i in open_)
        done = [i for i in open_ if left * sizes[i] / pool >= min(sizes[i], cap)]
        if not done:
            for i in open_:
                quota[i] = int(left * sizes[i] / pool)
            break
        for i in done:
            quota[i] = min(sizes[i], cap)
            left -= quota[i]
        open_ = [i for i in open_ if i not in done]
    return quota


def words_of(line):
    return re.sub(r'^\[[^\]]*\]\s*', '', STAMP.sub('', line)).strip()


# When they're active, counted from the times on the digest's lines (README "Rhythm is counted"): only what
# was read, so the read says so, but a count rather than an impression. None under 30 timed lines.
def rhythm(stamps):
    if len(stamps) < 30:
        return None
    n = len(stamps)
    bands = [('late night (00-04)', range(0, 5)), ('morning (05-11)', range(5, 12)), ('afternoon (12-17)', range(12, 18)), ('evening (18-23)', range(18, 24))]
    hours = [0] * 24
    for _, h in stamps:
        hours[h % 24] += 1
    peak = max(range(24), key=lambda h: hours[h] + hours[(h + 1) % 24] + hours[(h + 2) % 24])
    days = [0] * 7
    for d, _ in stamps:
        try:
            days[datetime.strptime(d, '%Y-%m-%d').weekday()] += 1
        except ValueError:
            pass
    names = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
    return {'of': '%d timed lines read, not all their activity' % n,
            'hours': ', '.join('%s %d%%' % (b, round(100 * sum(hours[h] for h in r) / n)) for b, r in bands),
            'peak': '%02d:00 to %02d:00' % (peak, (peak + 3) % 24),
            'busiest day': names[max(range(7), key=lambda i: days[i])], 'weekend': '%d%%' % round(100 * (days[5] + days[6]) / max(1, sum(days)))}


def check_digest(path=None):
    path = path or DIGEST
    if not os.path.exists(path):
        return {'ok': False, 'problems': ['No digest yet: build digest/digest.md as the reading plan says.']}
    with open(path, encoding='utf-8') as f:
        lines = f.read().splitlines()
    head = '\n'.join(lines[:6])
    depth = 'deep' if re.search(r'depth:\s*deep', head) else 'normal'
    limits = DIGEST_LIMITS[depth]
    last = re.search(r'last:\s*(\d{4}-\d{2}-\d{2})', head)
    reads = int((re.search(r'reads:\s*(\d+)', head) or [0, '1'])[1]) or 1
    inbox = re.search(r'([\d,]+)\s+conversations', head)
    captioned = re.search(r'([\d,]+)\s+(?:captioned|with words)', head)
    problems, sizes, section, dates, leaks, room = [], {}, None, [], [], []
    post_dates, convos, said, timed, all_read, stamps = [], [], {}, 0, False, []
    context = 0
    messages_in = not re.search(r'messages:\s*(not included|excluded|no)\b', head)
    if not lines or not lines[0].startswith('# Psyche digest'):
        problems.append('The first line must be "# Psyche digest".')
    if not last:
        problems.append('The header needs "last: YYYY-MM-DD", the date of the newest item.')
    for n, line in enumerate(lines, 1):
        if line.startswith('## '):
            section = line[3:].strip()
            if section == 'Posts and stories (all read)':
                section, all_read = 'Posts and stories', True
            if section not in SECTIONS:
                problems.append('Line %d: unknown section "%s" (use %s).' % (n, section, ', '.join(SECTIONS)))
            continue
        if line.startswith('### ') and section == 'Messages':
            convos.append({'line': n, 'chars': 0, 'whole': '(whole thread)' in line})
            continue
        # The header (before the first section) and headings aren't items.
        if not line.strip() or line.startswith('#') or section is None:
            continue
        # What a reply answers ("> Friend: …"): context, not their words, so no date and not in their counts.
        if section == 'Messages' and line.startswith('>'):
            context += len(line) + 1
            for what, rx in LEAKS:
                if rx.search(line):
                    leaks.append('Line %d has %s: take it out.' % (n, what))
            continue
        sizes[section] = sizes.get(section, 0) + len(line) + 1
        if section == 'Messages' and convos:
            convos[-1]['chars'] += len(line) + 1
        if section in ('Posts and stories', 'Comments', 'Messages'):
            if not DATED.match(line):
                problems.append('Line %d: an item starts with its date, YYYY-MM-DD.' % n)
            else:
                dates.append(line[:10])
                if TIMED.match(line):
                    timed += 1
                    stamps.append((line[:10], int(line[11:13].rstrip(':'))))
                if section == 'Posts and stories':
                    post_dates.append(line[:10])
                text = words_of(line)
                if not text:
                    problems.append('Line %d has no words: count it in the header ("without words: 2022 12 · 2023 30") instead.' % n)
                key = re.sub(r'[^\w]+', ' ', text.lower()).strip()
                if section == 'Messages' and convos and len(key) >= 25:
                    said.setdefault(key, {'line': n, 'in': set()})['in'].add(len(convos))
        if len(line) > 2000:
            problems.append('Line %d is %d characters: one item per line, at most about 1,600.' % (n, len(line)))
        body = STAMP.sub('', line)[:2000]
        # A date inside the text is not a phone number.
        body = re.sub(r'\b\d{4}-\d{2}(-\d{2})?\b', '', body)
        for what, rx in LEAKS:
            if rx.search(body):
                leaks.append('Line %d has %s: take it out.' % (n, what))
    total = sum(sizes.values()) + context
    if total > limits['total']:
        problems.append('%d characters in all, over about %d: thin it evenly across the years.' % (total, limits['total']))
    for name in ('Messages', 'Interests', 'Comments'):
        if sizes.get(name, 0) > limits[name]:
            problems.append('%s has %d characters, over about %d.' % (name, sizes[name], limits[name]))
    # What their replies answer is there to read the replies by: it never outweighs them.
    if context > limits['Context'] or context > sizes.get('Messages', 0):
        problems.append('What their replies answer ("> " lines) is %d characters, more than %s: keep only what each reply needs.' % (
            context, 'their own messages' if context > sizes.get('Messages', 0) else 'about %d' % limits['Context']))
    problems += leaks[:10]
    if len(leaks) > 10:
        problems.append('…and %d more lines like those.' % (len(leaks) - 10))
    repeated = [r for r in said.values() if len(r['in']) >= 2]
    for r in repeated[:5]:
        problems.append('Line %d: the same message is in %d conversations (one message sent to several people): keep it once.' % (r['line'], len(r['in'])))
    goal = {}
    if depth == 'normal':
        t = targets(reads, messages_in)
        have = sizes.get('Posts and stories', 0) + sizes.get('Comments', 0)
        # Every captioned post the header counts is already in: nothing more to read there.
        if captioned and len(post_dates) >= 0.9 * int(captioned.group(1).replace(',', '')):
            all_read = True
        goal['Posts and stories'] = [have, t['posts']]
        if have < SHORT * t['posts'] and not all_read:
            problems.append('Posts and stories: %d of about %d characters for this read. Read more, across every year (or head the section "## Posts and stories (all read)" if every caption and story with words is in).' % (have, t['posts']))
        if messages_in:
            want = min(10, int(inbox.group(1).replace(',', ''))) if inbox else 0
            if len(convos) < want:
                problems.append('Messages: %d conversations of the %d busiest. Add the rest, busiest first.' % (len(convos), want))
            top, rest = convos[:4], convos[4:10]
            if top and rest and max(c['chars'] for c in rest) > max(1000, 1.5 * min(c['chars'] for c in top)):
                problems.append('Conversations go busiest first: Conversation %d holds more than Conversation %d. Put the 4 they write in most at the top.' % (
                    4 + 1 + max(range(len(rest)), key=lambda j: rest[j]['chars']), 1 + min(range(len(top)), key=lambda j: top[j]['chars'])))
            for i, c in enumerate(convos[:10]):
                # A conversation with more to read holds at least an even share of the room.
                aim = min(t['cap'], t['convos'] // 10)
                goal['Conversation %d' % (i + 1)] = [c['chars'], aim]
                if c['chars'] < SHORT * aim and not c['whole']:
                    problems.append('Conversation %d: %d of about %d characters. %s (or mark it "(whole thread)" if it has no more).' % (
                        i + 1, c['chars'], aim, 'Page further back'))
                elif i < 4 and not c['whole']:
                    room.append('Conversation %d: page further back next read, towards its first year.' % (i + 1))
            # Their own messages in all: short threads ("(whole thread)") excuse one conversation, never the total,
            # while the inbox has more to read (README "Busiest, measured").
            whole = t['convos']
            mine = sizes.get('Messages', 0)
            if inbox and int(inbox.group(1).replace(',', '')) > len(convos) and mine < SHORT * whole:
                goal['Messages'] = [mine, whole]
                problems.append('Messages: %d of about %d characters of their own across %d conversations. Measure the inbox, which lists newest first, '
                                'and read the next busiest conversations until the total is reached.' % (mine, whole, len(convos)))
    else:
        # Where a Deep Psyche's sample is well short of its share: read more there, if there is more.
        for name, share in SHARES.items():
            if name == 'Messages' and not messages_in:
                continue
            want = share * 4 + (110000 * 4 if name == 'Posts and stories' and not messages_in else 0)
            if sizes.get(name, 0) < want / 2:
                room.append('%s: %d of about %d characters. Read more of it, if there is more.' % (name, sizes.get(name, 0), want))
    if dates and timed < len(dates) / 2:
        room.append('%d of %d lines have a time: add it ("2025-06-01 21:14") where Instagram gives one.' % (timed, len(dates)))
    if len(post_dates) >= 20:
        years = sorted({d[:4] for d in post_dates})
        if int(years[-1]) - int(years[0]) >= 3:
            recent = sum(1 for d in post_dates if int(d[:4]) >= int(years[-1]) - 1)
            if recent / len(post_dates) > 0.6:
                room.append('Posts and stories: %d%% are from %s and %s. Go back through the earlier years too.' % (round(100 * recent / len(post_dates)), int(years[-1]) - 1, years[-1]))
    return {'ok': not problems, 'depth': depth, 'reads': reads, 'characters': total, 'sections': sizes, 'targets': goal,
            'span': [min(dates), max(dates)] if dates else None, 'last': last.group(1) if last else None,
            'context': context, 'rhythm': rhythm(stamps), 'problems': problems, 'room': room}


# ---------- WhatsApp chats, made ready on the device (prep) ----------
# The same reading as psycheai.io's docs/whatsapp.js: its line format, its
# system lines, and how it tells whose export it is. Only the reader's own
# messages are kept; nobody else is named.

CHATS_MAX = 3
# Each chat's share. Larger than psycheai.io's 25,000 beside Instagram, where
# every character is paid for: here it's read in the user's own workspace, so
# it's psycheai.io's own chats-only sizes (docs/digest.js waChatChars).
CHAT_CHARS = {1: 45000, 2: 45000, 3: 30000}
CHAT_CHARS_DEEP = 75000     # a Deep Psyche
TEXT_CHARS = 483            # a long message: its opening and its end
SYSTEM = re.compile(r'(<media omitted>|<attached:|\b(image|video|audio|sticker|gif|document|contact card) omitted\b|this message was deleted|'
                    r'you deleted this message|messages and calls are end-to-end encrypted|missed (voice|video) call|waiting for this message|\bnull\b$|^\u200e)', re.I)
LINE = re.compile(r'^[\u200e\u200f\ufeff]?\[?(\d{1,4})[/.\-](\d{1,2})[/.\-](\d{1,4}),?\s+(\d{1,2})[:.](\d{2})(?:[:.](\d{2}))?'
                  r'(?:[\s\u202f\u00a0]*([AaPp])\.?\s?[Mm]\.?)?\]?\s*(?:[-\u2013]\s*)?(.*)$')
SCRUB = [
    (re.compile(r'https?://\S+|www\.\S+', re.I), '[link]'),
    (re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+'), '[email]'),
    (re.compile(r'(?<![\w@])@[A-Za-z0-9._]{2,30}'), '[handle]'),
    (re.compile(r'\+?\d[\d ()\-]{6,}\d'), '[number]'),
]


def clean_name(value):
    return re.sub(r'\s+', ' ', re.sub(r'[\u200e\u200f\u202a-\u202e\ufeff~]', '', value or '')).strip()


def norm(value):
    return re.sub(r'[^\w ]', '', clean_name(value).lower()).strip()


def title_from(name):
    # Hosts save uploads as "WhatsApp_Chat_with_Kai_Ng.zip", sometimes with a prefix or a "(1)".
    base = re.sub(r'\.(txt|zip)$', '', os.path.basename(name or ''), flags=re.I).replace('_', ' ')
    base = re.sub(r'\s*\(\d+\)$', '', base)
    m = re.search(r'WhatsApp Chat (?:with|-|\u2013)\s*(.+)$', base, re.I)
    return clean_name(m.group(1)) if m else ''


def parse_chat(text):
    out, last = [], None
    for raw in text.splitlines():
        m = LINE.match(raw)
        if not m:
            if last is not None and raw.strip():
                last['text'] += ' ' + raw.strip()
            continue
        rest = m.group(8) or ''
        colon = rest.find(': ')
        if colon <= 0:
            last = None
            continue
        sender = clean_name(rest[:colon])
        if not sender:
            last = None
            continue
        hour = int(m.group(4))
        ampm = (m.group(7) or '').lower()
        if ampm == 'p' and hour < 12:
            hour += 12
        if ampm == 'a' and hour == 12:
            hour = 0
        last = {'a': int(m.group(1)), 'b': int(m.group(2)), 'c': int(m.group(3)), 'h': hour, 'mi': int(m.group(5)), 'sender': sender, 'text': rest[colon + 2:]}
        out.append(last)
    order = 'ymd' if any(x['a'] > 31 for x in out) else 'mdy' if any(x['b'] > 12 for x in out) else 'dmy'
    for x in out:
        y, mo, d = (x['a'], x['b'], x['c']) if order == 'ymd' else (x['c'], x['a'], x['b']) if order == 'mdy' else (x['c'], x['b'], x['a'])
        if y < 100:
            y += 2000
        try:
            x['t'] = datetime(y, max(1, min(12, mo)), max(1, d), x['h'] % 24, x['mi'] % 60)
        except ValueError:
            try:
                x['t'] = datetime(y, max(1, min(12, mo)), 28, x['h'] % 24, x['mi'] % 60)
            except ValueError:
                x['t'] = None
    return [x for x in out if x.get('t') and x['text'].strip() and not SYSTEM.search(x['text'].strip())]


def texts_of(path):
    if path.lower().endswith('.txt'):
        with open(path, encoding='utf-8', errors='replace') as f:
            return [(path, f.read())]
    out = []
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.filename.lower().endswith('.txt') and info.file_size <= 60 * 1024 * 1024:
                out.append((path, z.read(info).decode('utf-8', errors='replace')))
    return out


def read_chats(paths):
    chats = []
    for path in paths:
        for name, text in texts_of(path):
            messages = parse_chat(text)
            if len(messages) < 2:
                continue
            counts = {}
            for x in messages:
                counts[x['sender']] = counts.get(x['sender'], 0) + 1
            chats.append({'title': title_from(name), 'people': sorted(counts, key=lambda k: -counts[k]), 'counts': counts, 'messages': messages})
    return chats[:CHATS_MAX]


def resolve_owner(chats, hints):
    sets = [set(c['people']) for c in chats]
    if len(chats) > 1:
        common = [p for p in sets[0] if all(p in s for s in sets)]
        if len(common) == 1:
            return common[0], []
    for c in chats:
        if len(c['people']) == 2 and c['title']:
            t = norm(c['title'])
            other = [p for p in c['people'] if norm(p) == t or (len(t) >= 3 and (norm(p).startswith(t) or t.startswith(norm(p))))]
            if other:
                owner = [p for p in c['people'] if p != other[0]][0]
                if len(chats) == 1 or all(owner in s for s in sets):
                    return owner, []
    wanted = [norm(h) for h in hints if norm(h)]
    everyone = sorted({p for c in chats for p in c['people']})
    if wanted:
        pool = [p for p in everyone if all(p in s for s in sets)] or everyone
        exact = [p for p in pool if norm(p) in wanted]
        if len(exact) == 1:
            return exact[0], []
        firsts = [w.split(' ')[0] for w in wanted if len(w.split(' ')[0]) >= 2]
        by_first = [p for p in pool if norm(p).split(' ')[0] in firsts]
        if len(by_first) == 1:
            return by_first[0], []
    tally = {}
    for c in chats:
        for p, n in c['counts'].items():
            tally[p] = tally.get(p, 0) + n
    candidates = [p for p in sorted(tally, key=lambda k: -tally[k]) if len(chats) == 1 or all(p in s for s in sets)][:8]
    return None, candidates or list(tally)[:8]


def keep_ends(text):
    text = re.sub(r'\s+', ' ', text).strip()
    return text if len(text) <= TEXT_CHARS else text[:320].rstrip() + ' … ' + text[-150:].lstrip()


# ---------- which of their messages, as psycheai.io picks them ----------
# The same choices as docs/digest.js sampleConversations: a burst of messages
# sent within two minutes is one line; filler ("lol", "ok") is left out, and a
# message under 30 characters stays only if it says something (it opens a
# conversation after six quiet hours, apologises, names a feeling or asks);
# pasted or forwarded text and link shares are left out. Then ten periods of
# equal length across the chat, each given places by the square root of its
# messages, and in each a mix of long (120+ characters), ordinary and short
# ones (50/40/10), the most telling first: an opener, an apology or a feeling
# counts 2, a question 1. Ties break on a hash, so a chat always gives the
# same sample. Each keeps what it answered, as psycheai.io's do (ctx,
# docs/instagram.js): the other side's last messages before it, within
# 12 hours, de-identified, context only, never longer than their own.

MSG_FLOOR, MSG_LONG, MSG_CREDIT = 30, 120, 280
CTX_CHARS, CTX_WINDOW, CTX_SHARE = 240, 12 * 3600, 1.0
MSG_MIX = [50, 40, 10]
PERIODS = 10
OPENER_GAP = 6 * 3600
BURST = 120
FILLER = re.compile(r'^((ha)+h?|(he)+|lo+l+|lmao|ok|okay|okie|k|kk|omw|yes|yeah|ya|yup|no|nope|sure|hm+|cool|nice|thanks|thx|ty|icic|alr|wah|wtf+|omg+)$')
APOLOGY = re.compile(r'\b(sorry|soz|apologi[sz]e|my bad|forgive me|i was wrong|paiseh)\b', re.I)
FEELING = re.compile(r'\b(love|loved|miss(?:ed)? you|hate|angry|mad at|upset|sad|hurt|worried|worry|anxious|scared|afraid|stressed|lonely|proud|grateful|thankful|disappoint\w*|frustrat\w*|annoy\w*|jealous|cry|crying|cried|happy|excited|feel|feeling|felt|sick of|tired of|overwhelm\w*|argu\w*|fight|fought|sian|emo)\b', re.I)
FORWARD = re.compile(r'^(?:forwarded(?: many times)?\b|fwd?:)', re.I)
LINKED = re.compile(r'\b(?:https?://|www\.)\S+', re.I)


def norm_text(text):
    return re.sub(r'(.)\1+', r'\1', re.sub(r'[^\w]+', '', text.lower()))


def allocate(weights, total, caps):
    """total places shared by weight (largest remainder), none over its cap; what a capped one can't take goes on."""
    out = [0] * len(weights)
    left = total
    live = [i for i, c in enumerate(caps) if c > 0 and weights[i] > 0]
    while left > 0 and live:
        w = sum(weights[i] for i in live)
        shares = {i: left * weights[i] / w for i in live}
        given = 0
        for i in live:
            take = min(int(shares[i]), caps[i] - out[i])
            out[i] += take
            given += take
        rest = left - given
        for i in sorted(live, key=lambda i: shares[i] - int(shares[i]), reverse=True):
            if rest <= 0:
                break
            if out[i] < caps[i]:
                out[i] += 1
                rest -= 1
        if given == 0 and rest == left:
            break
        left = rest
        live = [i for i in live if out[i] < caps[i]]
    return out


def choose_messages(messages, owner, cap):
    """(their messages, the ones picked, oldest first) for a chat, within about cap characters."""
    import zlib
    units, merged, prev, theirs = [], [], None, []
    for x in messages:
        mine = x['sender'] == owner
        if not mine:
            theirs = (theirs + [x])[-2:]
        if mine:
            gap = (x['t'] - prev['t']).total_seconds() if prev else None
            last = merged[-1] if merged else None
            if (last and prev is last['_last'] and (x['t'] - last['_last']['t']).total_seconds() <= BURST
                    and len(last['text']) + len(x['text']) + 3 <= 483 and len(x['text']) <= 800):
                last['text'] += ' / ' + x['text']
                last['_last'] = x
            else:
                ctx = [y for y in theirs if (x['t'] - y['t']).total_seconds() <= CTX_WINDOW]
                merged.append({'t': x['t'], 'text': x['text'], 'opener': gap is None or gap >= OPENER_GAP, '_last': x, 'ctx': ctx})
            theirs = []
        prev = x
    mine_all = [x for x in messages if x['sender'] == owner]
    seen = set()
    for m in merged:
        raw = m['text']
        if len(raw) > 800 or FORWARD.search(raw) or (LINKED.search(raw) and len(raw) > 280):
            continue
        # A link with hardly a word of their own says nothing about them.
        if LINKED.search(raw) and len(re.findall(r'\w{2,}', LINKED.sub(' ', raw))) < 4:
            continue
        # A link stays in place here, to be counted and replaced with [link] when the line is de-identified.
        text = re.sub(r'\s{2,}', ' ', raw).strip()
        key = norm_text(text) or text
        if not text or key in seen:
            continue
        if len(text) < MSG_FLOOR and (FILLER.match(key) or not (m['opener'] or APOLOGY.search(text) or FEELING.search(text) or '?' in text)):
            continue
        seen.add(key)
        score = (2 if m['opener'] else 0) + (2 if APOLOGY.search(text) else 0) + (2 if FEELING.search(text) else 0) + (1 if '?' in text else 0)
        units.append({'t': m['t'], 'text': text, 'len': len(text), 'score': score, 'hash': zlib.crc32(text.encode()), 'ctx': m.get('ctx') or []})
    if not units:
        return mine_all, []
    cost = lambda u: min(u['len'], 483) + 13
    avg = sum(cost(u) for u in units) / len(units)
    want = min(len(units), int(cap / avg * 1.1) + 1)
    first, span = units[0]['t'], (units[-1]['t'] - units[0]['t']).total_seconds()
    n = PERIODS if span > 0 else 1
    periods = [[] for _ in range(n)]
    for u in units:
        k = min(n - 1, int((u['t'] - first).total_seconds() * n / (span + 1))) if span > 0 else 0
        periods[k].append(u)
    places = allocate([round(len(p) ** 0.5 * 100) for p in periods], want, [len(p) for p in periods])
    chosen = []
    for period, room in zip(periods, places):
        if room <= 0:
            continue
        bands = [[u for u in period if u['len'] >= MSG_LONG], [u for u in period if MSG_FLOOR <= u['len'] < MSG_LONG],
                 [u for u in period if u['len'] < MSG_FLOOR]]
        per = allocate(MSG_MIX, room, [len(b) for b in bands])
        for b, (band, k) in enumerate(zip(bands, per)):
            band.sort(key=lambda u: (-u['score'], -(min(u['len'], MSG_CREDIT) if b == 0 else 0), u['hash']))
            chosen.extend(band[:k])
    chosen.sort(key=lambda u: u['t'])
    # Within about cap characters: thinned evenly through time.
    while len(chosen) > 1 and sum(cost(u) for u in chosen) > cap:
        over = sum(cost(u) for u in chosen) - cap
        drop = max(1, min(len(chosen) - 1, int(over / (sum(cost(u) for u in chosen) / len(chosen))) + 1))
        step = len(chosen) / drop
        gone = {int(k * step) for k in range(drop)}
        chosen = [u for i, u in enumerate(chosen) if i not in gone]
    # Context never outweighs their own words: past their length, the least telling lines keep none.
    room = CTX_SHARE * sum(cost(u) for u in chosen)
    for u in sorted(chosen, key=lambda u: (-u['score'], u['hash'])):
        size = sum(min(len(y['text']), CTX_CHARS) + 12 for y in u['ctx'])
        if size > room:
            u['ctx'] = []
        room -= size if u['ctx'] else 0
    return mine_all, chosen


def prep(paths, me=None, deep=False):
    chats = read_chats(paths)
    if not chats:
        return {'error': 'No WhatsApp chat was found in that file. In the chat, tap the menu, then More, Export chat, Without media, and send the .zip it saves.'}
    owner, candidates = resolve_owner(chats, [me] if me else [])
    if not owner:
        # Their names, for the user to pick themselves from, in the chat only.
        # The names in the chat, for the user to pick their own; prep runs again with --me.
        return {'ok': False, 'whoAreYou': candidates}
    cap = CHAT_CHARS_DEEP if deep else CHAT_CHARS[min(len(chats), 3)]
    out, summary = [], []
    removed = {'names': 0, 'links': 0, 'emails': 0, 'handles': 0, 'numbers': 0}
    for i, c in enumerate(chats):
        others = [p for p in c['people'] if p != owner]
        label = {p: 'Friend ' + chr(65 + j) if j < 26 else 'Friend' for j, p in enumerate(others)}
        # Their names in the user's own words too: full names, then first names of three letters or more.
        names = []
        for p in others:
            names.append((p, label[p]))
            first = p.split(' ')[0]
            if len(first) >= 3 and first != p:
                names.append((first, label[p]))
        names.sort(key=lambda n: -len(n[0]))
        # Their own messages, picked as psycheai.io's digest picks them
        # (docs/digest.js sampleConversations): see choose_messages.
        mine, chosen = choose_messages(c['messages'], owner, cap)
        # In what they answer, their own name goes too, as psycheai.io's context does.
        own = [(owner, '[you]')] + ([(owner.split(' ')[0], '[you]')] if len(owner.split(' ')[0]) >= 3 and ' ' in owner else [])

        def clean(text, pairs):
            for name, lab in pairs:
                text, n = re.subn(r'(?<!\w)' + re.escape(name) + r'(?!\w)', lab, text, flags=re.I)
                removed['names'] += n
            for (rx, sub), kind in zip(SCRUB, ('links', 'emails', 'handles', 'numbers')):
                text, n = rx.subn(sub, text)
                removed[kind] += n
            return text
        lines, answered = [], 0
        for x in chosen:
            for y in x['ctx']:
                said = clean(re.sub(r'\s+', ' ', y['text']).strip(), sorted(names + own, key=lambda n: -len(n[0])))
                lines.append('> %s: %s' % (label.get(y['sender'], 'Friend'), said if len(said) <= CTX_CHARS else said[:CTX_CHARS].rstrip() + ' …'))
                answered += 1
            lines.append(x['t'].strftime('%Y-%m-%d') + '  ' + keep_ends(clean(x['text'], names)))
        first, last = (mine[0]['t'], mine[-1]['t']) if mine else (None, None)
        group = len(others) > 1
        head = 'Chat %d: %s, %d of their messages from %s to %s, %d kept here' % (
            i + 1, 'a group chat of %d people' % (len(others) + 1) if group else 'a one-to-one chat', len(mine),
            first.strftime('%b %Y') if first else '-', last.strftime('%b %Y') if last else '-', len(chosen))
        out.append('# ' + head + '\n' + '\n'.join(lines))
        summary.append({'chat': i + 1, 'kind': 'group' if group else 'one-to-one', 'theirMessages': len(mine), 'kept': len(chosen), 'answered': answered,
                        'from': first.strftime('%Y-%m') if first else None, 'to': last.strftime('%Y-%m') if last else None})
    os.makedirs(SOURCES, exist_ok=True)
    os.chmod(SOURCES, 0o700)
    target = os.path.join(SOURCES, 'whatsapp.txt')
    with open(target, 'w', encoding='utf-8') as f:
        f.write('WhatsApp chats, made ready on this device: their own messages, each after what it answers as "> " lines '
                '(context only, never quoted), everyone else as Friend A, B..., numbers, emails, links and handles taken out.\n\n' + '\n\n'.join(out) + '\n')
    os.chmod(target, 0o600)
    # What happened, not what to do next: a result telling the assistant what
    # to read and to delete the export failed Muse's safety check.
    return {'ok': True, 'deidentified': True, 'file': os.path.relpath(target, HERE), 'chats': summary,
            'othersMessages': 'only what each kept message answers, as context', 'removed': removed, 'characters': sum(len(o) for o in out)}



# A busy or restarting server (a deploy, or the host replacing an instance)
# answers 502/503/504 or drops the connection for a minute or two. Those are
# waited out here, so the chat never sees them: about three minutes in all.
WAITS = (2, 4, 8, 15, 25, 40, 50, 50)
BUSY = (502, 503, 504)


def busy(err):
    """Whether this failure is the server being busy or restarting, so trying again helps."""
    if isinstance(err, urllib.error.HTTPError):
        return err.code in BUSY
    if isinstance(err, (http.client.IncompleteRead, http.client.RemoteDisconnected, ConnectionError)):
        return True
    if isinstance(err, urllib.error.URLError):
        # Never a timeout: the request may have gone through, and a POST must not run twice.
        return not isinstance(err.reason, (socket.timeout, TimeoutError))
    return False


def patiently(attempt):
    for wait in WAITS + (None,):
        try:
            return attempt()
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError) as err:
            if wait is None or not busy(err):
                raise
            time.sleep(wait)


# Every request goes through curl when the workspace has it, Python's own client otherwise
# (README "Answers that arrive whole"). In some Muse workspaces Python's reads came back cut
# short at about 20 KB, every time, while curl read the same answers whole: a republish then
# failed for minutes as "busy". Secrets (the token, a PDF's key) reach curl on its standard
# input, never its command line; a body goes through a private file. PSYCHEAI_TRANSPORT=python
# forces Python's client.
class Busy(Exception):
    pass


def _curl_quote(v):
    return '"' + str(v).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ').replace('\r', ' ') + '"'


def fetch(method, url, headers, data=None, timeout=60):
    """(status, body bytes) for one request. Raises URLError or ConnectionError when it doesn't get a whole answer."""
    curl = shutil.which('curl') if os.environ.get('PSYCHEAI_TRANSPORT') != 'python' else None
    if not curl:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as err:
            try:
                return err.code, err.read()
            except (OSError, http.client.HTTPException):
                return err.code, b''
    tmp = tempfile.mkdtemp(prefix='psyche-')
    try:
        out = os.path.join(tmp, 'out')
        conf = ['url = ' + _curl_quote(url), 'request = ' + _curl_quote(method), 'silent', 'show-error',
                'max-time = %d' % timeout, 'connect-timeout = 20', 'output = ' + _curl_quote(out), 'write-out = "%{http_code}"']
        conf += ['header = ' + _curl_quote('%s: %s' % (k, v)) for k, v in headers.items()]
        if data is not None:
            body = os.path.join(tmp, 'body')
            with open(body, 'wb') as f:
                f.write(data)
            conf.append('data-binary = ' + _curl_quote('@' + body))
        done = subprocess.run([curl, '--config', '-'], input=('\n'.join(conf) + '\n').encode(), capture_output=True, timeout=timeout + 30)
        if done.returncode == 28:
            raise urllib.error.URLError(socket.timeout('timed out'))
        if done.returncode in (18, 52, 55, 56, 92):
            raise ConnectionError('the answer arrived cut short (curl %d)' % done.returncode)
        if done.returncode != 0:
            raise urllib.error.URLError('curl %d' % done.returncode)
        try:
            with open(out, 'rb') as f:
                got = f.read()
        except OSError:
            got = b''
        return int(done.stdout.decode().strip() or 0), got
    except subprocess.TimeoutExpired:
        raise urllib.error.URLError(socket.timeout('timed out'))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def post(path, body, token=None, form=False, extra=None):
    data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
    headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json', 'Accept': 'application/json', 'User-Agent': agent()}
    headers.update(extra or {})
    if token:
        headers['Authorization'] = 'Bearer ' + token

    def attempt():
        status, raw = fetch('POST', BASE + path, headers, data, timeout=120)
        if status in BUSY:
            raise urllib.error.HTTPError(BASE + path, status, 'busy', {}, None)
        try:
            return status, json.loads(raw.decode() or '{}')
        except ValueError:
            if 200 <= status < 300:
                raise ConnectionError('the answer arrived cut short')
            return status, {}
    try:
        return patiently(attempt)
    except urllib.error.HTTPError as err:
        return err.code, {'error': {'message': 'PsycheAI is busy right now.'}}
    except (urllib.error.URLError, http.client.HTTPException, ConnectionError):
        return 503, {'error': {'message': 'PsycheAI is busy right now.'}}


def agent():
    return 'PsycheAI-skill/%s' % RELEASE


def get(path):
    def attempt():
        status, body = fetch('GET', BASE + path, {'Accept': 'application/json', 'User-Agent': agent()})
        if status >= 400:
            raise urllib.error.HTTPError(BASE + path, status, 'error', {}, None)
        return body
    return patiently(attempt)


# An update's files (README "Updates that arrive whole"), through fetch like every request.
# However a file arrives, update() installs it only if its hash matches the signed
# manifest, so the route can't change what's installed.
def fetch_file(path):
    return get(path)


# When each of this script's commands ran in a read (only its name), sent once
# the Psyche is saved, so PsycheAI can see which stage takes the time
# (README "Measuring a read"). Nothing from the read itself is in it.
TIMING = os.path.join(HERE, '.timing.json')


def mark(label):
    try:
        with open(TIMING) as f:
            marks = json.load(f)
    except (OSError, ValueError):
        marks = []
    marks = [m for m in marks if isinstance(m, list) and len(m) == 2 and time.time() - m[1] < 3 * 3600][-50:]
    marks.append([label, time.time()])
    try:
        write_private([TIMING], marks)
    except OSError:
        pass


def send_timing():
    """The read's marks, as seconds before now, to PsycheAI; then they're cleared. Never holds up the read."""
    try:
        with open(TIMING) as f:
            marks = json.load(f)
        os.remove(TIMING)
        now = time.time()
        digest = check_digest()
        body = {'marks': [[m[0], round(m[1] - now)] for m in marks], 'chars': digest.get('characters'), 'reads': digest.get('reads'),
                'messages': 'Messages' in (digest.get('sections') or {})}
        req = urllib.request.Request(BASE + '/skill/timing', data=json.dumps(body).encode(), method='POST',
                                     headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + account()['access_token']})
        urllib.request.urlopen(req, timeout=5).close()
    except Exception:
        pass


# ---------- first-run: status, start and both account lists in one call (README "First run in one call") ----------
STEP_ONE = ("On it. Reading your Instagram and writing your Psyche takes about 5 minutes. I'll show it here when it's ready. "
            "Here's what you'll get, in a minute, while you wait.")
# A later read's line, with no reel (the guide's step 1).
FRESH_STEP_ONE = "On it. Writing your fresh Psyche takes about 5 minutes. I'll show it here when it's ready."


def instagram_accounts(data, messages=False):
    """Each account in an accounts answer: its username, ID, whether it's professional, and (messages) connected.
    Read defensively, since the tools don't document the shape: any dict with a username and an ID."""
    found = []

    def walk(v):
        if isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            name = v.get('username') or v.get('user_name')
            fbid = next((str(v[k]) for k in ('user_fbid', 'fbid', 'account_id', 'id') if v.get(k) not in (None, '')), None)
            if isinstance(name, str) and name and fbid:
                pro = next((bool(v[k]) for k in ('is_professional', 'professional', 'is_business', 'is_business_account') if k in v), False)
                conn = next((bool(v[k]) for k in ('connected', 'is_connected', 'messaging_connected', 'messages_connected') if k in v), None)
                found.append({'username': name.lstrip('@'), 'id': fbid, 'professional': pro, 'connected': conn})
                return
            for k, x in v.items():
                if k != '_meta':
                    walk(x)
    walk(data)
    return found


def account_tag(account_id):
    """A short hash of the account read, so last-collect can mark it next time without keeping its ID."""
    return hashlib.sha256(('psyche-account:' + str(account_id)).encode()).hexdigest()[:12]


def account_choice():
    """The account question (README "Messages, then the account"): one button per personal account, with its
    IDs and whether its messages are connected. The question only with more than one account, and the one read
    last time first, marked "(last time)". Raises when a list can't be read."""
    ig_list = [a for a in instagram_accounts(ig(IG_CLI, 'accounts')) if not a['professional']]
    msg = {a['username']: a for a in instagram_accounts(ig(IGM_CLI, 'accounts'), True)}
    if not ig_list:
        return {'accounts': None, 'problem': 'No personal Instagram account came back.'}
    last = (read_first([LAST_COLLECT]) or {}).get('account')
    buttons = []
    for a in ig_list:
        m = msg.get(a['username'])
        was = len(ig_list) > 1 and last == account_tag(a['id'])
        buttons.append(dict(label='@' + a['username'] + (' (last time)' if was else ''), last=was,
                            account_id=a['id'], messages_account_id=m['id'] if m and m['id'] != a['id'] else None,
                            messages_connected=bool(m and m['connected'])))
    buttons.sort(key=lambda b: not b['last'])
    return {'question': 'Which account should I read?' if len(buttons) > 1 else None, 'buttons': buttons}


def first_run():
    """Data only (README "First run in one call"): what start says and its two messages buttons (the welcome,
    sent before this ran), the account question and its buttons, and step 1's line. No instruction to Muse
    rides in a tool result: SKILL.md says what to do."""
    account()
    out = {'version': local_version()}
    start = call('start', {})
    out['say'], out['reel'] = start.get('say'), start.get('reel')
    if start.get('error'):
        out['error'] = start['error']
        return out
    try:
        out.update(account_choice())
    except (RuntimeError, RateLimited) as err:
        out['accounts'] = None
        out['problem'] = 'The account lists could not be read here (%s).' % type(err).__name__
        return out
    out['stepOne'] = STEP_ONE + '\n▶ PsycheAI in a minute: ' + str(out.get('reel') or '')
    return out

def local_version():
    try:
        with open(os.path.join(HERE, 'SKILL.md')) as f:
            for line in f:
                if line.startswith('version:'):
                    return line.split(':', 1)[1].strip().strip('"')
    except OSError:
        pass
    return None


# ---------- signed updates (README "Signed skill updates") ----------
# An update is installed only when PsycheAI's signature checks out: Ed25519,
# made with a key kept away from PsycheAI's servers, over the version and each
# file's SHA-256. A server someone else got into can't sign, so it can't change
# what runs here. Ed25519 verification as in RFC 8032, standard library only.

SKILL_PUBLIC_KEY = bytes.fromhex(os.environ.get('PSYCHEAI_SKILL_PUBLIC_KEY')
                                 or 'ff295f50202afe5313924d4ed60e397996164ad8db9aa8079d937c17d0bcbb8d')
_P = 2 ** 255 - 19
_Q = 2 ** 252 + 27742317777372353535851937790883648493
_D = -121665 * pow(121666, _P - 2, _P) % _P
_SQRT_M1 = pow(2, (_P - 1) // 4, _P)


def _add(a, b):
    A, B = (a[1] - a[0]) * (b[1] - b[0]) % _P, (a[1] + a[0]) * (b[1] + b[0]) % _P
    C, D = 2 * a[3] * b[3] * _D % _P, 2 * a[2] * b[2] % _P
    E, F, G, H = B - A, D - C, D + C, B + A
    return (E * F, G * H, F * G, E * H)


def _mul(s, point):
    out = (0, 1, 1, 0)
    while s > 0:
        if s & 1:
            out = _add(out, point)
        point = _add(point, point)
        s >>= 1
    return out


def _same(a, b):
    return (a[0] * b[2] - b[0] * a[2]) % _P == 0 and (a[1] * b[2] - b[1] * a[2]) % _P == 0


def _x(y, sign):
    if y >= _P:
        return None
    x2 = (y * y - 1) * pow(_D * y * y + 1, _P - 2, _P) % _P
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (_P + 3) // 8, _P)
    if (x * x - x2) % _P:
        x = x * _SQRT_M1 % _P
    if (x * x - x2) % _P:
        return None
    return _P - x if (x & 1) != sign else x


def _point(raw):
    if len(raw) != 32:
        return None
    y = int.from_bytes(raw, 'little')
    x = _x(y & ((1 << 255) - 1), y >> 255)
    return None if x is None else (x, y & ((1 << 255) - 1), 1, x * (y & ((1 << 255) - 1)) % _P)


_GY = 4 * pow(5, _P - 2, _P) % _P
_G = (_x(_GY, 0), _GY, 1, _x(_GY, 0) * _GY % _P)


def ed25519_verify(public, message, sig):
    if len(public) != 32 or len(sig) != 64:
        return False
    A, R = _point(public), _point(sig[:32])
    s = int.from_bytes(sig[32:], 'little')
    if A is None or R is None or s >= _Q:
        return False
    h = int.from_bytes(hashlib.sha512(sig[:32] + public + message).digest(), 'little') % _Q
    return _same(_mul(s, _G), _add(R, _mul(h, A)))


def signed_text(version, hashes, release=None):
    head = 'psycheai-skill\n' + ('release: %d\n' % release if release is not None else '') + 'version: %s\n' % version
    return (head + ''.join('%s %s\n' % (n, hashes[n]) for n in sorted(hashes))).encode()


NOT_SIGNED = "This update isn't signed by PsycheAI, so it wasn't installed. The version you have keeps working."
OLDER = "This is an older release than the one installed, so it wasn't installed. The version you have keeps working."


def update():
    manifest = json.loads(fetch_file('/skill/files').decode())
    # The signature that covers the release number too (signature2): one without it could be an old release served again.
    hashes, sig, release = manifest.get('hashes') or {}, manifest.get('signature2') or '', manifest.get('release')
    try:
        good = isinstance(release, int) and ed25519_verify(SKILL_PUBLIC_KEY, signed_text(manifest.get('version'), hashes, release), base64.urlsafe_b64decode(sig + '=' * (-len(sig) % 4)))
    except (ValueError, TypeError):
        good = False
    if good and release < RELEASE:
        return {'updated': False, 'error': OLDER}
    names = [n for n in manifest.get('files', []) if '..' not in n and not n.startswith('/')]
    if not good or sorted(names) != sorted(hashes):
        return {'updated': False, 'error': NOT_SIGNED}
    # Every file fetched and checked before any is written: all of a release, or none of it.
    bodies = {}
    for name in names:
        body = fetch_file('/skill/' + name)
        if hashlib.sha256(body).hexdigest() != hashes[name]:
            return {'updated': False, 'error': NOT_SIGNED}
        if name.endswith('.py'):
            compile(body.decode(), name, 'exec')
        bodies[name] = body
    for name, body in bodies.items():
        target = os.path.join(HERE, name)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, 'wb') as f:
            f.write(body)
    return {'updated': True, 'version': manifest.get('version'), 'signed': True}


def write_private(paths, data):
    """The same JSON to each path, readable only by this workspace."""
    for path in paths:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.dirname(path) == KEEP:
                os.chmod(KEEP, 0o700)
            with open(path, 'w') as f:
                json.dump(data, f, ensure_ascii=False)
            os.chmod(path, 0o600)
        except OSError:
            pass  # the copy outside the folder is a spare; the folder's own is what counts


def read_first(paths):
    for path in paths:
        try:
            with open(path) as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def save(account):
    write_private([ACCOUNT, ACCOUNT_KEPT], account)


def account():
    kept = read_first([ACCOUNT, ACCOUNT_KEPT])
    if kept and kept.get('access_token'):
        if not os.path.exists(ACCOUNT) or not os.path.exists(ACCOUNT_KEPT):
            save(kept)  # put back whichever copy was missing
        return kept
    status, body = post('/skill/account', {})
    if status != 200 or not body.get('access_token'):
        sys.exit('PsycheAI could not make an account just now (%s). Try again in a minute.' % status)
    save(body)
    return body


def refresh(acc):
    status, body = post('/oauth/token', {'grant_type': 'refresh_token', 'refresh_token': acc['refresh_token'], 'client_id': CLIENT_ID}, form=True)
    if status != 200 or not body.get('access_token'):
        for path in (ACCOUNT, ACCOUNT_KEPT):
            if os.path.exists(path):
                os.remove(path)
        return account()
    acc.update(access_token=body['access_token'], refresh_token=body.get('refresh_token', acc['refresh_token']))
    save(acc)
    return acc


def held_keys():
    kept = read_first([KEYS, KEYS_KEPT]) or {}
    return {'card': kept.get('card') if isinstance(kept.get('card'), str) else None,
            'syncs': [c for c in kept.get('syncs', []) if isinstance(c, str)][-200:]}


def keep_keys(card=None, text=''):
    """Keep a new card key, and any Sync code in text (a Psyche link), here and in the spare copy."""
    held = held_keys()
    codes = [c for c in SYNC_CODE.findall(str(text or '')) if c not in held['syncs']]
    if card or codes or not os.path.exists(KEYS):
        write_private([KEYS, KEYS_KEPT], {'card': card or held['card'], 'syncs': (held['syncs'] + codes)[-200:]})


def key_headers():
    held = held_keys()
    out = {}
    if held['card']:
        out['X-Psyche-Card-Key'] = held['card']
    if held['syncs']:
        out['X-Psyche-Sync-Keys'] = ','.join(held['syncs'])
    return out


def pinned_guide():
    guide = read_first([GUIDE])
    return guide if isinstance(guide, dict) and isinstance(guide.get('read'), dict) and isinstance(guide.get('sync'), dict) else None


# ---------- the digest, built from what was read (README "The skill builds the digest") ----------
# As Muse reads, it saves each item as one JSON line in work/items.jsonl:
#   {"kind": "post"|"story"|"comment"|"message", "date": "2024-05-01 21:14", "text": "...",
#    "thread": "t1", "mine": true, "with": ["Kai Ng"]}      (thread, mine, with: messages only)
# and work/meta.json: {"me": their name, "bio", "messages": true|false, "sources", "counts": {"conversations",
# "followers", "following", "saved"}, "interests": [...], "complete": ["t1", ...]} (threads read
# back to their first message). build-digest picks and de-identifies as psycheai.io's digest does,
# writes digest/digest.md and checks it, so Muse never writes the digest by hand.
ITEMS = os.path.join(WORK, 'items.jsonl')
META = os.path.join(WORK, 'meta.json')
POSTS_MAX, COMMENTS_MAX, MESSAGES_MAX, THREADS_MAX = 85000, 15000, 115000, 30


def when(value):
    """A date as datetime, from "2024-05-01", "2024-05-01 21:14", ISO with T/Z, or unix seconds."""
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000 if value > 1e11 else value)
        except (OverflowError, OSError, ValueError):
            return None
    v = str(value or '').strip().replace('T', ' ').rstrip('Z')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d'):
        try:
            return datetime.strptime(v[:len(datetime(2000, 1, 1).strftime(fmt))], fmt)
        except ValueError:
            continue
    return None


def scrub(text, names=()):
    # Links, emails, handles and numbers first, so a name inside one ("jun@…") goes with it.
    for rx, sub in SCRUB:
        text = rx.sub(sub, text)
    for name, lab in names:
        text = re.sub(r'(?<!\w)' + re.escape(name) + r'(?!\w)', lab, text, flags=re.I)
    return re.sub(r'\s+', ' ', text).strip()


def thin(lines, cap):
    """Lines within about cap characters, dropped evenly through time rather than cut at one end."""
    total = sum(len(l) + 1 for l in lines)
    if total <= cap or not lines:
        return lines
    keep = max(1, int(len(lines) * cap / total))
    step = len(lines) / keep
    return [lines[int(k * step)] for k in range(keep)]


def build_digest(given=None, given_meta=None):
    """The digest from work/items.jsonl and work/meta.json, or from items and meta handed in (collect)."""
    if given is None and not os.path.exists(ITEMS):
        return {'ok': False, 'problems': ['No work/items.jsonl yet: save what you read there as you go, one JSON line per item.']}
    # It builds a first digest (or one after starting over): rebuilding from work/ alone would drop what earlier reads kept.
    if os.path.exists(DIGEST) and not os.path.exists(os.path.join(os.path.dirname(DIGEST), '.built')):
        return {'ok': False, 'problems': ['A digest from an earlier read is already here: add what is new to it as SKILL.md says for a later read; build-digest makes a first one.']}
    items, bad = [], 0
    if given is None:
        with open(ITEMS, encoding='utf-8') as f:
            lines = f.read().splitlines()
    else:
        lines = given
    for line in lines:
        try:
            x = json.loads(line) if isinstance(line, str) else dict(line)
        except (ValueError, TypeError):
            bad += str(line).strip() != ''
            continue
        t = when(x.get('date')) if isinstance(x, dict) else None
        if isinstance(x, dict) and t and x.get('kind') in ('post', 'story', 'comment', 'message'):
            x['t'] = t
            items.append(x)
    meta = given_meta if given_meta is not None else (read_first([META]) or {})
    reads = 1
    messages_in = meta.get('messages', True) is not False
    t = targets(reads, messages_in)
    stamp = lambda x: x['t'].strftime('%Y-%m-%d %H:%M') if (x['t'].hour or x['t'].minute) else x['t'].strftime('%Y-%m-%d')
    # Posts and stories, and their comments: every one with words, thinned evenly past the ceiling.
    seen, posts, words = set(), [], 0
    no_words = {}
    for x in sorted((x for x in items if x['kind'] in ('post', 'story')), key=lambda x: x['t']):
        text = scrub(str(x.get('text') or ''))
        # Only tags ("[handle] [handle]") is a story without words: nothing of theirs to read.
        if not re.search(r'\w', re.sub(r'\[(handle|link|email|number)\]', '', text)):
            no_words[x['t'].year] = no_words.get(x['t'].year, 0) + 1
            continue
        key = norm_text(text) + stamp(x)[:10]
        if key in seen:
            continue
        seen.add(key)
        words += 1
        posts.append('%s [%s] %s' % (stamp(x), x['kind'], keep_ends(text) if len(text) > 1500 else text))
    all_posts = len(posts)
    posts = thin(posts, POSTS_MAX)
    comments = thin(['%s %s' % (stamp(x), scrub(str(x.get('text') or ''))) for x in sorted((x for x in items if x['kind'] == 'comment'), key=lambda x: x['t'])
                     if re.search(r'\w', str(x.get('text') or ''))], COMMENTS_MAX)
    # Conversations: busiest first by how much of their own is in each, the room shared as the site
    # shares it (convo_quotas); what each reply answers kept as context.
    threads = {}
    for x in items:
        if x['kind'] == 'message':
            threads.setdefault(str(x.get('thread') or 'thread'), []).append(x)
    mine_size = lambda msgs: sum(len(str(m.get('text') or '')) for m in msgs if m.get('mine'))
    ranked = sorted(threads.items(), key=lambda kv: -mine_size(kv[1]))
    complete = set(str(c) for c in meta.get('complete') or [])
    convo_blocks, own_total = [], 0
    # The 10 busiest, and up to 5 more while those hold less than the room (as the site's spare threads).
    sizes = [mine_size(m) for _, m in ranked]
    keep = CONVO_TOP
    while keep < min(len(ranked), CONVO_TOP + CONVO_SPARE) and sum(sizes[:keep]) < t['convos']:
        keep += 1
    ranked = ranked[:keep]
    quotas = convo_quotas(sizes[:keep], t['convos'], t['cap'])
    # Their own name, in what others wrote to them, is "[you]", as psycheai.io's context does.
    me = str(meta.get('me') or '').strip()
    own_names = [(me, '[you]')] + ([(me.split(' ')[0], '[you]')] if ' ' in me and len(me.split(' ')[0]) >= 3 else []) if me else []
    said_once = set()   # a message sent word for word to several people is one thing they did, kept once
    # Everyone read in any conversation: named in another one, they are "a friend" there too.
    everyone = sorted({str(n) for x in items if x['kind'] == 'message' for n in (x.get('with') or []) if str(n).strip() and str(n) != 'Friend'})
    elsewhere = []
    for n in everyone:
        elsewhere.append((n, 'a friend'))
        if ' ' in n and len(n.split(' ')[0]) >= 3:
            elsewhere.append((n.split(' ')[0], 'a friend'))
    if messages_in:
        for i, (tid, msgs) in enumerate(ranked):
            if own_total >= MESSAGES_MAX:
                break
            others = sorted({str(n) for m in msgs for n in (m.get('with') or []) if n})
            label = {n: ('Friend' if len(others) <= 1 else 'Friend ' + chr(65 + j)) for j, n in enumerate(others[:26])}
            names = []
            for n in others:
                names.append((n, label.get(n, 'Friend')))
                first = n.split(' ')[0]
                if len(first) >= 3 and first != n:
                    names.append((first, label.get(n, 'Friend')))
            names += [e for e in elsewhere if e[0] not in {x[0] for x in names}]
            names.sort(key=lambda n: -len(n[0]))
            parsed = [{'t': m['t'], 'sender': 'me' if m.get('mine') else str((m.get('with') or ['Friend'])[0]), 'text': str(m.get('text') or '')}
                      for m in sorted(msgs, key=lambda m: m['t']) if str(m.get('text') or '').strip()]
            mine, chosen = choose_messages(parsed, 'me', max(quotas[i], 300) if quotas[i] < sizes[i] else 2 * sizes[i] + 300)
            if not chosen:
                continue
            lines = []
            for u in chosen:
                key = norm_text(u['text'])
                if len(key) >= 25 and key in said_once:
                    continue
                said_once.add(key)
                for y in u['ctx']:
                    said = scrub(y['text'], sorted(names + own_names, key=lambda n: -len(n[0])))
                    lines.append('> %s: %s' % (label.get(y['sender'], 'Friend'), said if len(said) <= CTX_CHARS else said[:CTX_CHARS].rstrip() + ' …'))
                lines.append('%s %s' % (u['t'].strftime('%Y-%m-%d %H:%M'), keep_ends(scrub(u['text'], names))))
            own_total += sum(len(l) + 1 for l in lines if not l.startswith('>'))
            first_t, last_t = (mine[0]['t'], mine[-1]['t']) if mine else (chosen[0]['t'], chosen[-1]['t'])
            convo_blocks.append('### Conversation %d: %s, %s to %s%s\n%s' % (
                len(convo_blocks) + 1, 'one-to-one' if len(others) <= 1 else 'a group of %d' % (len(others) + 1),
                first_t.strftime('%Y-%m'), last_t.strftime('%Y-%m'), ' (whole thread)' if tid in complete else '', '\n'.join(lines)))
    # An interest that scrubs to nothing but a placeholder ("[number]") says nothing about them.
    interests = [x for x in ('- ' + scrub(str(i)) for i in (meta.get('interests') or []) if str(i).strip())
                 if re.search(r'\w', re.sub(r'\[(handle|link|email|number)\]', '', x))][:40]
    every = [x['t'] for x in items]
    counts = meta.get('counts') or {}
    head_counts = ['%d posts and stories' % (all_posts + sum(no_words.values())), '%d with words' % words, '%d comments' % len(comments)]
    for k in ('conversations', 'followers', 'following', 'saved'):
        if isinstance(counts.get(k), int):
            # collect counts the conversations it read, not the inbox: said so, or a read takes the
            # sample for their life ("you keep 15 conversations").
            head_counts.append('%s %s%s' % ('{:,}'.format(counts[k]), k, ' read (the busiest)' if k == 'conversations' and meta.get('sampled') else ''))
        if k == 'conversations' and messages_in:
            # What "How this was read" cites: read off here, never remembered from a tool's output.
            head_counts.append('{:,} own messages read'.format(sum(1 for x in items if x['kind'] == 'message' and x.get('mine'))))
    if no_words:
        head_counts.append('without words: ' + ' · '.join('%d %d' % (y, n) for y, n in sorted(no_words.items())))
    out = ['# Psyche digest',
           'built: %s · reads: %d · depth: normal · messages: %s · sources: %s · span: %s to %s · last: %s' % (
               datetime.now().strftime('%Y-%m-%d'), reads, 'included' if messages_in else 'not included', meta.get('sources') or 'instagram',
               min(every).strftime('%Y-%m') if every else '-', max(every).strftime('%Y-%m') if every else '-', max(every).strftime('%Y-%m-%d') if every else '-'),
           'counts: ' + ' · '.join(head_counts)]
    if meta.get('bio'):
        out.append('bio: ' + scrub(str(meta['bio']))[:300])
    out.append('## Posts and stories' + (' (all read)' if len(posts) == all_posts else ''))
    out += posts
    if comments:
        out += ['## Comments'] + comments
    if convo_blocks:
        out += ['## Messages'] + convo_blocks
    if interests:
        out += ['## Interests'] + interests
    os.makedirs(os.path.dirname(DIGEST), exist_ok=True)
    # Built in this read, so building again (after reading more) may replace it; publishing ends that.
    open(os.path.join(os.path.dirname(DIGEST), '.built'), 'w').close()
    write_text = '\n'.join(out) + '\n'
    with open(DIGEST, 'w', encoding='utf-8') as f:
        f.write(write_text)
    os.chmod(DIGEST, 0o600)
    result = check_digest()
    result['built'] = {'items': len(items), 'unreadable lines': bad, 'conversations': len(convo_blocks), 'posts and stories': len(posts)}
    return result


# ---------- collect: a first read in one command (README "Collect in one command") ----------
# A read spent most of its time between Muse's own tool calls: 43 of them, two scripts it
# wrote and debugged, two that failed. `collect` does the reading itself, through the same
# Instagram tools Muse uses (instagram-cli, instagram-messages-cli), as the connectors' docs
# say to: every call's exit status checked, pages followed only while they add something and
# never with a cursor already used, everything stopped at a rate limit, a read stopped after
# repeated server errors. Messages are read in memory, from their busiest contacts only, one
# thread at a time and only as far as the digest needs, and never written to a file as they
# came: what reaches disk is the digest, built from them (names, handles, links and numbers
# taken out) as build-digest builds it. IDs and cursors never leave this function.

IG_CLI = os.environ.get('PSYCHEAI_IG_CLI') or '/opt/hatch/bin/instagram-cli'
IGM_CLI = os.environ.get('PSYCHEAI_IGM_CLI') or '/opt/hatch/bin/instagram-messages-cli'
COLLECT_TYPES = (('POST,REEL', 'post'), ('STORY,HIGHLIGHT', 'story'))
COLLECT_PAGES = 60          # a list's pages at most
THREAD_FIRST, THREAD_FIRST_SAFE = 100, 50   # messages a page: 100 asked first, 50 if the tool refuses it (README "Bigger pages")
COLLECT_WORKERS = 3          # conversations read at once (README "Three at a time")
COLLECT_THREADS = CONVO_TOP + CONVO_SPARE   # their busiest contacts read, as the site's 10 and 5 spares
THREAD_PAGES = 8            # a thread's pages at most (20 for the 4 busiest, which the plan wants most from)


class RateLimited(Exception):
    pass


def ig(cli, *args, timeout=120):
    """One Instagram tool call: its JSON, or raises. A 429 stops the whole collect."""
    try:
        done = subprocess.run([cli] + [str(a) for a in args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as err:
        raise RuntimeError('could not run: ' + type(err).__name__)
    out = (done.stdout or b'').decode('utf-8', 'replace')
    said = out + (done.stderr or b'').decode('utf-8', 'replace')
    # Only a failed call, or an answer that is itself an error, is a rate limit: a caption,
    # a message or a count that happens to say 429 is their data, never a reason to stop.
    if done.returncode != 0:
        if re.search(r'too many requests|rate.?limit|\b429\b', said, re.I):
            raise RateLimited()
        raise RuntimeError('exit %d%s' % (done.returncode, ' (server error)' if re.search(r'\b50\d\b', said) else ''))
    try:
        got = json.loads(out or '{}')
    except ValueError:
        raise RuntimeError('not JSON')
    err = got.get('error') if isinstance(got, dict) else None
    code = [got.get('status_code'), got.get('code')] + ([err.get('code'), err.get('status'), err.get('status_code')] if isinstance(err, dict) else [])
    if isinstance(got, dict) and (429 in code or '429' in code or (isinstance(err, str) and re.search(r'too many requests|rate.?limit|\b429\b', err, re.I))):
        raise RateLimited()
    return got


def caption_of(p):
    """A post's words, wherever its answer puts them (post_caption, as the docs say, or a caption object)."""
    for v in (p.get('post_caption'), p.get('caption'), p.get('text')):
        if isinstance(v, dict):
            v = v.get('text')
        if isinstance(v, str) and v.strip():
            return v
    return ''


def local_time(stamp, raw=None):
    """A post's or message's time: the user's local time, else UTC, else the raw provider time."""
    if stamp is not None and not isinstance(stamp, dict):
        stamp, raw = None, stamp if raw in (None, '') else raw
    for v in ((stamp or {}).get('user_local'), (stamp or {}).get('utc')) if isinstance(stamp, dict) else ():
        if when(v):
            return when(v)
    try:
        return when(int(str(raw))) if raw not in (None, '') else None
    except ValueError:
        return when(raw)


def pages(fetch, cursor_of, limit=COLLECT_PAGES):
    """Each page of a list, following its cursor while pages add something, never reusing one."""
    used, after = set(), None
    for _ in range(limit):
        page = fetch(after)
        yield page
        nxt = cursor_of(page)
        if not nxt or nxt in used:
            return
        used.add(nxt)
        after = nxt


def collect(account, messages_account=None, me=None, threads=COLLECT_THREADS, with_messages=True):
    if os.path.exists(DIGEST) and not os.path.exists(os.path.join(os.path.dirname(DIGEST), '.built')):
        return {'ok': False, 'problems': ['A digest from an earlier read is already here: collect makes a first one. For a later read, add to it as SKILL.md says.']}
    account = str(account or '').strip()
    if not re.fullmatch(r'[\w-]{3,40}', account):
        return {'ok': False, 'problems': ['--account-id must be their own user_fbid from instagram-cli accounts.']}
    m_account = str(messages_account or account).strip()
    items, notes, stopped = [], [], None
    meta = {'me': me or '', 'messages': bool(with_messages), 'counts': {}, 'interests': [], 'complete': [], 'sources': 'instagram'}
    read = {'posts': 0, 'stories': 0, 'comments': 0, 'threads': 0, 'own messages': 0}

    def note(what, err):
        notes.append('%s: %s' % (what, err))

    # Posts, stories, comments, saved and interests are read beside the conversations, at the same
    # time (README "Posts beside messages"); a rate limit in either stops both before another call.
    halt = threading.Event()

    def igc(*args):
        if halt.is_set():
            raise RateLimited()
        try:
            return ig(*args)
        except RateLimited:
            halt.set()
            raise

    def public():
        try:
                # Profile: their bio and counts.
                try:
                    prof = (igc(IG_CLI, 'profile', '--account-id', account).get('profiles') or [{}])[0]
                    meta['bio'] = str(prof.get('bio') or '')[:300]
                    for key, names in (('followers', ('follower_count', 'followers_count', 'followers')), ('following', ('following_count', 'follows_count', 'following'))):
                        v = next((prof.get(n) for n in names if isinstance(prof.get(n), int)), None)
                        if v is not None:
                            meta['counts'][key] = v
                    if not meta['me']:
                        meta['me'] = str(prof.get('full_name') or prof.get('name') or '')
                except RuntimeError as err:
                    note('profile', err)
                # Posts, reels, stories and highlights, every page, each kept once. When a type gives
                # nothing usable, notes say what came back (none on the account, or none with a time).
                seen = set()
                for types, kind in COLLECT_TYPES:
                    label = 'posts' if kind == 'post' else 'stories'
                    for ask in [types]:
                        got = {'returned': 0, 'without a time': 0}
                        try:
                            for page in pages(lambda after: igc(IG_CLI, 'posts', '--account-id', account, '--post-types', ask, '--sort-order', 'desc', '--limit', 100,
                                                               *(('--after', after) if after else ())),
                                              lambda p: p.get('next_cursor') if p.get('has_next_page') and p.get('posts') else None):
                                for p in page.get('posts') or []:
                                    got['returned'] += 1
                                    pid = str(p.get('post_id') or '')
                                    t = local_time(p.get('post_created_at') or p.get('created_at'), p.get('taken_at') or p.get('timestamp'))
                                    if not t:
                                        got['without a time'] += 1
                                        continue
                                    if pid and pid in seen:
                                        continue
                                    seen.add(pid)
                                    items.append({'kind': kind, 'date': t.strftime('%Y-%m-%d %H:%M'), 'text': caption_of(p)})
                                    read[label] += 1
                                if page.get('provider_error'):
                                    note(label, 'a page came back partial')
                        except RuntimeError as err:
                            note(label, err)
                        if not read[label]:
                            note(label, 'none on the account' if not got['returned'] else '%(returned)d returned, none with a time' % got)
                # Their own comments: the posts they commented on, then their comments on those.
                try:
                    commented = []
                    for page in pages(lambda after: igc(IG_CLI, 'recently-commented-posts', '--account-id', account, '--limit', 50, *(('--after', after) if after else ())),
                                      lambda p: (p.get('next_cursor') or p.get('end_cursor') or (p.get('page_info') or {}).get('end_cursor'))
                                      if (p.get('has_next_page') or (p.get('page_info') or {}).get('has_next_page')) else None, limit=6):
                        for p in page.get('posts') or page.get('items') or []:
                            pid = str(p.get('post_id') or p.get('media_id') or p.get('id') or '')
                            if pid and pid not in commented:
                                commented.append(pid)
                    for i in range(0, min(len(commented), 100), 10):
                        got = igc(IG_CLI, 'fetch-post-comments', '--account-id', account, '--post-ids', ','.join(commented[i:i + 10]), '--author-ids', account)
                        for group in got.get('post_groups') or []:
                            for c in group.get('comments') or []:
                                t = local_time(c.get('created_at') if isinstance(c.get('created_at'), dict) else c.get('comment_created_at'),
                                               c.get('created_at') if not isinstance(c.get('created_at'), dict) else c.get('timestamp'))
                                text = str(c.get('comment_text') or '')
                                if t and text.strip():
                                    items.append({'kind': 'comment', 'date': t.strftime('%Y-%m-%d %H:%M'), 'text': text})
                                    read['comments'] += 1
                except RuntimeError as err:
                    note('comments', err)
                # Saved (a count) and their interests (topics only).
                try:
                    n = 0
                    for page in pages(lambda after: igc(IG_CLI, 'saved-posts', '--account-id', account, '--limit', 50, *(('--after', after) if after else ())),
                                      lambda p: (p.get('end_cursor') or p.get('next_cursor') or (p.get('page_info') or {}).get('end_cursor'))
                                      if (p.get('has_next_page') or (p.get('page_info') or {}).get('has_next_page')) else None, limit=10):
                        n += len(page.get('posts') or page.get('items') or [])
                    meta['counts']['saved'] = n
                except RuntimeError as err:
                    note('saved', err)
                try:
                    got = igc(IG_CLI, 'current-interests', '--account-id', account)
                    found = []

                    def topics(v):
                        if isinstance(v, str) and 1 < len(v) <= 80:
                            found.append(v)
                        elif isinstance(v, list):
                            for x in v:
                                topics(x)
                        elif isinstance(v, dict):
                            for k in ('text', 'topic', 'name', 'title'):
                                if isinstance(v.get(k), str):
                                    return topics(v[k])
                            for k, x in v.items():
                                if k not in ('_meta', 'model_response_guidance', 'retrieved_at', 'status', 'type', 'id'):
                                    topics(x)
                    topics(got)
                    meta['interests'] = list(dict.fromkeys(found))[:40]
                except RuntimeError as err:
                    note('interests', err)
        except RateLimited:
            halt.set()

    try:
        side = threading.Thread(target=public)
        side.start()
        try:
            # Messages: their busiest contacts, one thread at a time, only as far as needed.
            if with_messages:
                t = targets(1, True)
                try:
                    ranked, score = [], {}
                    for page in pages(lambda after: igc(IGM_CLI, 'top-recipients', '--account-id', m_account, '--count', threads, *(('--page-max-id', after) if after else ())),
                                      lambda p: p.get('page_max_id') if p.get('has_next_page') else None, limit=3):
                        for r in page.get('ranking') or []:
                            for s in r.get('score_map') or []:
                                if isinstance(s.get('score'), (int, float)):
                                    score[str(s.get('key'))] = max(score.get(str(s.get('key')), 0), s['score'])
                        for th in (page.get('entities') or {}).get('thread') or []:
                            if th.get('thread_fbid') and th['thread_fbid'] not in [x['thread_fbid'] for x in ranked]:
                                ranked.append(th)
                        if len(ranked) >= threads:
                            break
                    ranked.sort(key=lambda th: -score.get(str(th.get('score_map_key')), 0))
                    # Two passes: every thread to an even share of the room first, then, ranked by their own
                    # words as the digest ranks them, the room left goes to the busiest with more to read,
                    # none past the site's ceiling. Cursors stay in memory.
                    states = []
                    for i, th in enumerate(ranked[:threads]):
                        others = [u for u in th.get('users') or [] if str(u.get('id')) != account and str(u.get('id')) != m_account]
                        states.append({'tid': 't%d' % (i + 1), 'fbid': th['thread_fbid'], 'names': [str(u.get('full_name') or u.get('username') or 'Friend') for u in others] or ['Friend'],
                                       'others': {str(v) for u in others for v in (u.get('id'), u.get('interop_messaging_user_fbid')) if v},
                                       'mine': 0, 'whole': False, 'after': None, 'used': set(), 'pages': 0, 'failed': False})

                    # Three conversations at a time, each read in order with its own cursor; a rate limit in
                    # any one stops them all (no call starts after it) and the read stops as it always has.
                    lock, size, paged = threading.Lock(), {'n': THREAD_FIRST}, {'pages': 0, 'messages': 0}

                    def read_thread(st, want, limit):
                        while not halt.is_set() and not st['whole'] and not st['failed'] and st['mine'] < want and st['pages'] < limit:
                            first = size['n']
                            try:
                                page = igc(IGM_CLI, 'thread', '--account-id', m_account, '--thread-fbid', st['fbid'], '--first', first,
                                          *(('--after', st['after']) if st['after'] else ()))
                            except RateLimited:
                                halt.set()
                                return
                            except RuntimeError as err:
                                # The docs give no most a page: a refusal at 100 is read again at 50, for the rest of the read.
                                if first > THREAD_FIRST_SAFE:
                                    with lock:
                                        if size['n'] > THREAD_FIRST_SAFE:
                                            size['n'] = THREAD_FIRST_SAFE
                                            note('conversations', '%d messages a page refused (%s), read %d a page' % (first, err, THREAD_FIRST_SAFE))
                                    continue
                                st['failed'] = True
                                with lock:
                                    note('a conversation', err)
                                return
                            st['pages'] += 1
                            got, own = [], 0
                            for msg in page.get('messages') or []:
                                text = str(((msg.get('content') or {}).get('text_body')) or '')
                                when_sent = local_time(msg.get('message_sent_at'), msg.get('timestamp'))
                                if not text.strip() or not when_sent:
                                    continue
                                sender = str(msg.get('sender_fbid') or '')
                                mine = sender in (account, m_account) or (bool(st['others']) and sender not in st['others'])
                                got.append({'kind': 'message', 'date': when_sent.strftime('%Y-%m-%d %H:%M'), 'text': text,
                                            'thread': st['tid'], 'mine': mine, 'with': st['names']})
                                if mine:
                                    st['mine'] += len(text)
                                    own += 1
                            with lock:
                                items.extend(got)
                                read['own messages'] += own
                                paged['pages'] += 1
                                paged['messages'] += len(page.get('messages') or [])
                            info = page.get('messages_page_info') or {}
                            nxt = info.get('end_cursor') if info.get('has_next_page') else None
                            if not nxt or nxt in st['used']:
                                st['whole'] = not nxt
                                return
                            st['used'].add(nxt)
                            st['after'] = nxt

                    def at_once(jobs, limit):
                        with ThreadPoolExecutor(COLLECT_WORKERS) as pool:
                            list(pool.map(lambda job: read_thread(job[0], job[1], limit), jobs))
                        if halt.is_set():
                            raise RateLimited()

                    at_once([(st, t['convos'] / CONVO_TOP * 1.3) for st in states], THREAD_PAGES)
                    # The room left, given out busiest first before any is read, so the three can run together.
                    left, deeper = t['convos'] * 1.3 - sum(st['mine'] for st in states), []
                    for st in sorted(states, key=lambda x: -x['mine'])[:CONVO_TOP]:
                        if left <= 0:
                            break
                        if st['whole'] or st['failed']:
                            continue
                        want = min(t['cap'] * 1.3, st['mine'] + left)
                        left -= want - st['mine']
                        deeper.append((st, want))
                    at_once(deeper, 30)
                    # Room set aside for one that ran out goes to the next with more, for two more rounds.
                    for _ in range(2):
                        left, deeper = t['convos'] * 1.3 - sum(st['mine'] for st in states), []
                        for st in sorted(states, key=lambda x: -x['mine'])[:CONVO_TOP]:
                            if left <= 0:
                                break
                            if st['whole'] or st['failed'] or st['pages'] >= 30 or st['mine'] >= t['cap'] * 1.3:
                                continue
                            want = min(t['cap'] * 1.3, st['mine'] + left)
                            left -= want - st['mine']
                            deeper.append((st, want))
                        if not deeper:
                            break
                        at_once(deeper, 30)
                    for st in states:
                        if st['pages']:
                            read['threads'] += 1
                        if st['whole']:
                            meta['complete'].append(st['tid'])
                    meta['counts']['conversations'] = len(ranked)
                    meta['sampled'] = True
                    # How many messages a page actually came back, against how many were asked for (README "Bigger pages").
                    if paged['pages']:
                        read['conversation pages'] = '%d pages, %d messages a page on average, %d asked' % (
                            paged['pages'], round(paged['messages'] / paged['pages']), size['n'])
                except RuntimeError as err:
                    note('messages', err)
        finally:
            side.join()
        if halt.is_set():
            raise RateLimited()
    except RateLimited:
        stopped = 'Instagram said too many requests, so every call stopped there, as its docs ask: the digest has what came before.'
    if not items:
        return {'ok': False, 'read': read, 'notes': notes, 'stopped': stopped, 'problems': ['Nothing came back from Instagram to build a digest from.']}
    result = build_digest(items, meta)
    result['read'] = read
    if notes:
        result['notes'] = notes
    if stopped:
        result['stopped'] = stopped
    return result


# ---------- collect-facebook: Facebook posts and Messenger, read like Instagram (README "Facebook and Messenger") ----------
# Through Muse's own Facebook and Messenger tools, as their connectors' docs say: their own
# timeline posts only (a post on their wall by someone else is left out), and their own side of
# their busiest Messenger chats, each reply after what it answers as "> " context, read in memory.
# Names, handles, links and numbers come out as the digest's do; IDs and cursors never leave this
# function. Messenger is read narrowly, for one purpose: the busiest few chats, a set amount of
# their own words, and the "> " context dropped once the report is saved (drop_context), never
# a copy of their history. What reaches disk is sources/facebook.txt.
FB_CLI = os.environ.get('PSYCHEAI_FB_CLI') or '/opt/hatch/bin/facebook-cli'
MSGR_CLI = os.environ.get('PSYCHEAI_MSGR_CLI') or '/opt/hatch/bin/hatch_messenger_cli'
FB_PAGES = 15               # timeline pages of 20, newest first
FB_POSTS_MAX = 30000        # their posts' characters at most
MSGR_THREADS = 8            # their busiest Messenger chats
MSGR_CHARS = 40000          # their own words across them, as a later read adds
MSGR_PAGES = 10             # a chat's pages at most
UNREADABLE = re.compile(r'^\((decrypt failed|no thread key)\)$', re.I)
SIDE_CHAT = re.compile(r'\b(muse|meta ai)\b', re.I)


def _first_str(d, keys):
    for k in keys:
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, dict):
            v = v.get('text') or v.get('body')
        if isinstance(v, str) and v.strip():
            return v
    return ''


def _rows(got, keys):
    if isinstance(got, list):
        return got
    for k in keys:
        if isinstance(got, dict) and isinstance(got.get(k), list):
            return got[k]
    if isinstance(got, dict) and isinstance(got.get('data'), dict):
        return _rows(got['data'], keys)
    return []


def _names_in(v, out):
    """Every person's name a post tags or mentions (with_tags, mentions, tagged…), to take out."""
    if isinstance(v, list):
        for x in v:
            _names_in(x, out)
    elif isinstance(v, dict):
        n = v.get('name') or v.get('full_name')
        if isinstance(n, str) and n.strip():
            out.add(n.strip())
    elif isinstance(v, str) and v.strip():
        out.add(v.strip())


def _not_connected(got, err=None):
    said = json.dumps(got) if got is not None else str(err or '')
    return got == {} or bool(re.search(r"not connected|isn'?t connected|no (linked )?account|not linked", said, re.I))


def collect_facebook(me=None, with_messenger=True):
    """Their own Facebook posts and, with_messenger, their side of their busiest Messenger chats, into
    sources/facebook.txt. A service that isn't connected answers with its connect link, as data."""
    read = {'facebook posts': 0, 'messenger chats': 0}
    notes, connect = [], {}
    owner = str(me or '').strip()
    posts, tagged = [], set()
    # Facebook: who they are, then their own timeline.
    try:
        who = ig(FB_CLI, 'me')
    except RuntimeError as err:
        who = None
        if not _not_connected(None, err):
            notes.append('facebook: %s' % err)
    if isinstance(who, dict) and who.get('consent_url'):
        connect['facebook'] = who['consent_url']
    elif who is None or _not_connected(who) or not who.get('fb_user_id'):
        if who is not None or not notes:
            try:
                connect['facebook'] = (ig(FB_CLI, 'connect-url') or {}).get('connect_url') or 'Meta Accounts Center'
            except RuntimeError:
                connect['facebook'] = 'Meta Accounts Center'
    else:
        fbid = str(who['fb_user_id'])
        owner = owner or str(who.get('name') or '')
        try:
            for page in pages(lambda after: ig(FB_CLI, 'timeline', 'fetch', '--profile-id', fbid, '--limit', 20, *(('--after', after) if after else ())),
                              lambda p: (p.get('next_cursor') or ((p.get('paging') or {}).get('cursors') or {}).get('after')) if isinstance(p, dict) else None,
                              limit=FB_PAGES):
                for p in _rows(page, ('posts', 'items', 'timeline')):
                    author, own = str(p.get('author_id') or ''), str(p.get('owner_id') or fbid)
                    if author and author != own:
                        continue        # someone else's post on their wall
                    text = _first_str(p, ('message', 'text', 'post_text', 'body', 'caption', 'content'))
                    t = local_time(p.get('post_created_at') or p.get('created_at'), p.get('created_time') or p.get('timestamp'))
                    if not t or not text.strip():
                        continue
                    for k in ('with_tags', 'tags', 'tagged', 'mentions', 'message_tags', 'with'):
                        _names_in(p.get(k), tagged)
                    posts.append((t, text))
        except RateLimited:
            notes.append('facebook: too many requests, so it stopped there')
        except RuntimeError as err:
            notes.append('facebook: %s' % err)
    names = sorted([(n, 'a friend') for n in tagged if n.lower() != owner.lower()], key=lambda n: -len(n[0]))
    lines = []
    for t, text in sorted(posts, key=lambda x: x[0]):
        said = scrub(text, names)
        if re.search(r'\w', re.sub(r'\[(handle|link|email|number)\]', '', said)):
            lines.append('%s [facebook post] %s' % (t.strftime('%Y-%m-%d %H:%M'), keep_ends(said) if len(said) > 1500 else said))
    read['facebook posts'] = len(lines)
    lines = thin(lines, FB_POSTS_MAX)
    blocks = []
    if lines:
        blocks.append('# Facebook posts: %d of their own, %s to %s\n%s' % (read['facebook posts'], lines[0][:7], lines[-1][:7], '\n'.join(lines)))
    # Messenger: the busiest chats by what's held for each, their own words, what each answers as context.
    if with_messenger:
        try:
            state = ig(MSGR_CLI, 'check')
            if _not_connected(state) or (isinstance(state, dict) and state.get('connected') is False):
                connect['messenger'] = (ig(MSGR_CLI, 'connect-url') or {}).get('connect_url') or 'Messenger settings'
            else:
                try:
                    ig(MSGR_CLI, 'sync', 'both', '--since-days', 365, timeout=240)
                except RuntimeError as err:
                    notes.append('messenger: refresh %s' % err)
                listed = _rows(ig(MSGR_CLI, 'threads', '--limit', 30), ('threads', 'conversations', 'items'))
                ranked = []
                for th in listed:
                    cid = str(th.get('conversation_id') or th.get('cid') or th.get('id') or '')
                    found = set()
                    _names_in(th.get('participants') or th.get('members') or [], found)
                    people = sorted(found)
                    title = str(th.get('name') or th.get('thread_name') or th.get('title') or '')
                    if not cid or SIDE_CHAT.search(title + ' ' + ' '.join(people)):
                        continue        # Muse's own side chat is never read
                    probe = ig(MSGR_CLI, 'messages', '--cid', cid, '--limit', 1)
                    size = ((probe.get('_cache') or {}).get('cached_message_count') if isinstance(probe, dict) else 0) or 0
                    ranked.append((size, cid, people, (probe.get('_cache') or {}).get('self_user_id') if isinstance(probe, dict) else None))
                ranked.sort(key=lambda r: -r[0])
                repaired, share, gathered = False, MSGR_CHARS // max(1, min(MSGR_THREADS, len(ranked))), []
                for size, cid, people, self_id in ranked[:MSGR_THREADS]:
                    try:
                        ig(MSGR_CLI, 'sync', 'messages', '--cid', cid, '--older', 200, timeout=120)
                    except RuntimeError:
                        pass
                    msgs, before, unreadable = [], None, 0
                    for _ in range(MSGR_PAGES):
                        got = ig(MSGR_CLI, 'messages', '--cid', cid, '--limit', 100, *(('--before', before) if before else ()))
                        self_id = self_id or ((got.get('_cache') or {}).get('self_user_id') if isinstance(got, dict) else None)
                        rows = _rows(got, ('messages', 'items'))
                        if not rows:
                            break
                        oldest = None
                        for m in rows:
                            text = _first_str(m, ('text', 'body', 'message', 'snippet'))
                            raw_t = m.get('timestamp_ms') or m.get('timestamp') or m.get('sent_at')
                            t = local_time(m.get('message_sent_at') if isinstance(m.get('message_sent_at'), dict) else None, raw_t or m.get('message_sent_at'))
                            ms = raw_t if isinstance(raw_t, (int, float)) else (int(t.timestamp() * 1000) if t else None)
                            oldest = ms if oldest is None or (ms is not None and ms < oldest) else oldest
                            if UNREADABLE.match(text.strip()):
                                unreadable += 1
                                continue
                            if m.get('poll') or not text.strip() or not t:
                                continue
                            sender = str(m.get('sender_id') or m.get('sender') or '')
                            name = str(m.get('sender_name') or '') or 'Friend'
                            msgs.append({'t': t, 'sender': 'me' if self_id and sender == str(self_id) else name, 'text': text})
                        mine = sum(len(x['text']) for x in msgs if x['sender'] == 'me')
                        if mine >= share * 1.3 or oldest is None or oldest == before:
                            break
                        before = oldest
                    if unreadable and not repaired:
                        repaired = True
                        try:
                            ig(MSGR_CLI, 'repair')
                        except RuntimeError:
                            pass
                    msgs = sorted({(x['t'], x['sender'], x['text']): x for x in msgs}.values(), key=lambda x: x['t'])
                    if any(x['sender'] == 'me' for x in msgs):
                        gathered.append((msgs, people))
                # Everyone read in any chat is "a friend" in the others, as the digest does.
                everyone = sorted({n for msgs, people in gathered for n in [x['sender'] for x in msgs if x['sender'] != 'me'] + people
                                   if n and n != 'Friend' and n.lower() != owner.lower()})
                elsewhere = [(n, 'a friend') for n in everyone] + [(n.split(' ')[0], 'a friend') for n in everyone if ' ' in n and len(n.split(' ')[0]) >= 3]
                for msgs, people in gathered:
                    others = sorted({x['sender'] for x in msgs if x['sender'] != 'me'} | set(people) - {owner})
                    label = {n: ('Friend' if len(others) <= 1 else 'Friend ' + chr(65 + j)) for j, n in enumerate(others[:26])}
                    pairs = []
                    for n in others:
                        pairs.append((n, label.get(n, 'Friend')))
                        first = n.split(' ')[0]
                        if len(first) >= 3 and first != n:
                            pairs.append((first, label.get(n, 'Friend')))
                    pairs += [e for e in elsewhere if e[0] not in {x[0] for x in pairs}]
                    pairs.sort(key=lambda n: -len(n[0]))
                    own_names = [(owner, '[you]')] + ([(owner.split(' ')[0], '[you]')] if ' ' in owner and len(owner.split(' ')[0]) >= 3 else []) if owner else []
                    mine, chosen = choose_messages(msgs, 'me', share)
                    out = []
                    for u in chosen:
                        for y in u['ctx']:
                            said = scrub(y['text'], sorted(pairs + own_names, key=lambda n: -len(n[0])))
                            out.append('> %s: %s' % (label.get(y['sender'], 'Friend'), said if len(said) <= CTX_CHARS else said[:CTX_CHARS].rstrip() + ' …'))
                        out.append('%s %s' % (u['t'].strftime('%Y-%m-%d %H:%M'), keep_ends(scrub(u['text'], pairs))))
                    if not chosen:
                        continue
                    read['messenger chats'] += 1
                    blocks.append('# Messenger chat %d: %s, %s to %s\n%s' % (
                        read['messenger chats'], 'one-to-one' if len(others) <= 1 else 'a group of %d' % (len(others) + 1),
                        mine[0]['t'].strftime('%Y-%m') if mine else '-', mine[-1]['t'].strftime('%Y-%m') if mine else '-', '\n'.join(out)))
        except RateLimited:
            notes.append('messenger: too many requests, so it stopped there')
        except RuntimeError as err:
            notes.append('messenger: %s' % err)
    if not blocks:
        out = {'ok': False, 'read': read}
        if connect:
            out['connect'] = connect
        if notes:
            out['notes'] = notes
        if not connect:
            out['problems'] = ['Nothing of their own came back from Facebook or Messenger.']
        return out
    os.makedirs(SOURCES, exist_ok=True)
    os.chmod(SOURCES, 0o700)
    target = os.path.join(SOURCES, 'facebook.txt')
    with open(target, 'w', encoding='utf-8') as f:
        f.write('Facebook%s, read on this device through Muse\'s own connections: their own posts%s, everyone else as a friend or Friend A, B..., '
                'numbers, emails, links and handles taken out.\n\n' % (' and Messenger' if read['messenger chats'] else '',
                ' and their own Messenger messages, each after what it answers as "> " lines (context only, never quoted)' if read['messenger chats'] else '')
                + '\n\n'.join(blocks) + '\n')
    os.chmod(target, 0o600)
    # Counts kept beside the last collect, for the receipt and My data and privacy (posts only: Messenger's
    # own guidance is never to say how many messages were read).
    last = read_first([LAST_COLLECT]) or {}
    last['facebook'] = {'posts': read['facebook posts'], 'messenger': bool(read['messenger chats'])}
    write_private([LAST_COLLECT], last)
    out = {'ok': True, 'deidentified': True, 'file': os.path.relpath(target, HERE), 'read': read}
    if connect:
        out['connect'] = connect
    if notes:
        out['notes'] = notes
    return out


# ---------- the report's outline and a local check (README "A faster read") ----------
# The schema runs to about 33,000 characters; the outline is each section and
# its fields on a line (a "?" marks one that may be left out, [..]N-M a list's
# length), so the report is written from it and the schema only looked up.

def schema_ref(node, defs):
    return defs.get(node['$ref'].split('/')[-1], {}) if isinstance(node, dict) and '$ref' in node else node


def outline_of(node, defs, depth=0):
    node = schema_ref(node, defs)
    kind = node.get('type')
    if kind == 'object' and 'properties' in node and depth < 4:
        req = set(node.get('required', []))
        parts = []
        for k, v in node['properties'].items():
            inner = outline_of(v, defs, depth + 1)
            parts.append(k + ('' if k in req else '?') + (':' + inner if inner else ''))
        return '{' + ', '.join(parts) + '}'
    if kind == 'array':
        size = '%s-%s' % (node.get('minItems', ''), node.get('maxItems', '')) if ('minItems' in node or 'maxItems' in node) else ''
        return '[' + outline_of(node.get('items', {}), defs, depth + 1) + ']' + size
    if 'enum' in node and len(node['enum']) <= 6:
        return '|'.join(str(e) for e in node['enum'])
    return ''


def schema_outline(schema):
    defs = schema.get('$defs', {})
    req = set(schema.get('required', []))
    return '\n'.join('%s%s: %s' % (k, '' if k in req else '?', outline_of(v, defs)) for k, v in schema.get('properties', {}).items())


def schema_problems(value, node, defs, at='answer', out=None):
    """Where an answer doesn't fit the schema: missing or unknown fields, wrong types, values outside a list, list sizes."""
    out = [] if out is None else out
    if len(out) >= 20:
        return out
    node = schema_ref(node, defs)
    kind = node.get('type')
    kinds = {'object': dict, 'array': list, 'string': str, 'integer': int, 'number': (int, float), 'boolean': bool}
    if kind in kinds and (not isinstance(value, kinds[kind]) or (kind in ('integer', 'number') and isinstance(value, bool))):
        out.append('%s should be %s' % (at, 'an ' + kind if kind[0] in 'aeiou' else 'a ' + kind))
        return out
    if 'enum' in node and value not in node['enum']:
        out.append('%s is "%s", not one of the allowed values' % (at, str(value)[:40]))
    if kind == 'object':
        props = node.get('properties', {})
        for k in node.get('required', []):
            if k not in value:
                out.append('%s is missing %s' % (at, k))
        for k, v in value.items():
            if k in props:
                schema_problems(v, props[k], defs, at + '.' + k, out)
    if kind == 'array':
        if 'minItems' in node and len(value) < node['minItems']:
            out.append('%s has %d items, fewer than %d' % (at, len(value), node['minItems']))
        if 'maxItems' in node and len(value) > node['maxItems']:
            out.append('%s has %d items, more than %d' % (at, len(value), node['maxItems']))
        for i, v in enumerate(value[:50]):
            schema_problems(v, node.get('items', {}), defs, '%s[%d]' % (at, i), out)
    return out


# The checks psycheai.io runs when a read is saved (lib/museimport.js eiProblems, planProblems,
# listProblems), run here first so a rewrite happens before the first publish, not after it
# (README "Saved checks, checked first"). Same words, same thresholds: keep the two in step.
CLOSE_CIRCLE = re.compile(r'\b(close|small|tight|tight-knit|trusted|familiar)\b[\w ,:-]{0,32}\b(circle|core)\b', re.I)
PRIVATE_ACCOUNT = re.compile(r'\b(private account|account is private)\b', re.I)
SAME_COMMON = set('the and you your one this that with for from into next week weeks month year quarter each before after then them their what when will would more than about which have has its are was were can could just only also'.split())
SAME_FRAME = set('a an of to in on at as so or be by is it not but no too very strength strengths pressure under becomes become behind tired turns'.split())


def ei_problems(data):
    letters = ((data.get('mbti') or {}).get('letters') or []) if isinstance(data.get('mbti'), dict) else []
    letter = next((l for l in letters if isinstance(l, dict) and re.fullmatch(r'[EI]', str(l.get('choice') or ''))), None)
    if not letter:
        return []
    said = ' '.join(str(x) for x in [letter.get('why') or ''] + list(letter.get('evidence') or []))
    out = []
    if CLOSE_CIRCLE.search(said):
        out.append('mbti E/I: its reasons rest on a close circle, which is loyalty rather than energy: it follows who starts things, the groups and new people they join, and how they recharge')
    if PRIVATE_ACCOUNT.search(said):
        out.append('mbti E/I: whether the account is private is not a reason for either letter')
    return out


def same_point(a, b):
    stems = lambda t: [w[:5] for w in re.findall(r'[a-z]{3,}', str(t or '').lower()) if w not in SAME_COMMON]
    words = lambda t: re.findall(r'[a-z0-9]+', str(t or '').lower())
    text_of = lambda x: str(x.get('title')) + ' ' + str(x.get('detail') or '')

    def title_in(x, y):
        t = list(dict.fromkeys(stems(x.get('title'))))
        other = set(stems(text_of(y) if len(t) >= 4 else y.get('title')))
        return len(t) >= 2 and sum(1 for w in t if w in other) / len(t) >= 0.75
    if title_in(a, b) or title_in(b, a):
        return True
    wa, wb = words(text_of(a)), words(text_of(b))
    weighty = lambda run: sum(1 for w in run if w not in SAME_COMMON and w not in SAME_FRAME) >= 3
    runs = {' '.join(wa[i:i + 6]) for i in range(len(wa) - 5) if weighty(wa[i:i + 6])}
    return any(' '.join(wb[i:i + 6]) in runs for i in range(len(wb) - 5))


def first_same(items, what):
    xs = [x for x in items if isinstance(x, dict) and isinstance(x.get('title'), str) and x['title'].strip()]
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            if same_point(xs[i], xs[j]):
                return ['%s: "%s" and "%s" make the same point; %s' % (what, xs[i]['title'][:60], xs[j]['title'][:60],
                        'the plan keeps one of them and gives the other place to a different step' if what == 'the plan' else 'the list keeps one of them and gives the other place to a different point')]
    return []


def holding_problems(data):
    """psycheai.io's holdingProblems: the career weakness shown beside "What holds you back" repeating it."""
    ca = data.get('careerAssessment') if isinstance(data.get('careerAssessment'), dict) else {}
    hb = ca.get('holdingBack') if isinstance(ca.get('holdingBack'), dict) else None
    if not hb or not hb.get('headline'):
        return []
    back = {'title': hb['headline'], 'detail': hb.get('detail') or ''}
    car = data.get('career') if isinstance(data.get('career'), dict) else {}
    same = next((w for w in car.get('weaknesses') or [] if isinstance(w, dict) and isinstance(w.get('title'), str) and same_point(back, w)), None)
    return ['career.weaknesses: "%s" makes the same point as careerAssessment.holdingBack "%s": leave it empty or name a different cost'
            % (same['title'][:60], hb['headline'][:60])] if same else []


NUMBER_WORDS = 'zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen twenty'.split()


def sample_problems(answer):
    """The number of conversations read, cited as if it were a fact about them ("15 conversations running from 2018")."""
    try:
        with open(DIGEST, encoding='utf-8') as f:
            head = f.read(2000)
    except OSError:
        return []
    m = re.search(r'([\d,]+) conversations read', head)
    if not m:
        return []
    n = int(m.group(1).replace(',', ''))
    said = [str(n)] + ([NUMBER_WORDS[n]] if n < len(NUMBER_WORDS) else [])
    rx = re.compile(r'\b(?:%s)\s+(?:conversations|threads|chats)\b' % '|'.join(map(re.escape, said)), re.I)
    return ['%s cites "%s": that is how many conversations were read, the sample\'s size, not a fact about them; say what a conversation shows instead' % (at, rx.search(text).group(0))
            for at, text in strings_in(answer) if rx.search(text)][:3]


# What a plan step is about, by theme, as psycheai.io's planProblems has it (README "One step, once"):
# three themes in common is one step asked for twice, in different words.
PLAN_THEMES = {
    'plan': ['plan', 'meetu', 'meet', 'dinne', 'lunch', 'run', 'game', 'night', 'trip', 'hango', 'catch', 'drink'],
    'commit': ['pick', 'fix', 'lock', 'book', 'choos', 'close', 'commi', 'decid', 'confi', 'sched', 'set'],
    'time': ['time', 'day', 'slot', 'hour', 'date', 'eveni', 'weekd', 'weeke'],
    'finish': ['finis', 'ship', 'relea', 'publi', 'share', 'send', 'launc', 'compl', 'deliv'],
    'sleep': ['sleep', 'bed', 'wake', 'alarm', 'morni'],
    'write': ['write', 'note', 'journ', 'draft'],
}
THEME_OF = {w: t for t, ws in PLAN_THEMES.items() for w in ws}


def themes_of(x):
    words = re.findall(r'[a-z]{3,}', (str(x.get('title') or '') + ' ' + str(x.get('detail') or '')).lower())
    return {THEME_OF.get(w[:5]) or THEME_OF.get(w) for w in words} - {None}


def plan_problems(data):
    dev = data.get('development') if isinstance(data.get('development'), dict) else {}
    car = data.get('careerAssessment') if isinstance(data.get('careerAssessment'), dict) else {}
    well = data.get('wellness') if isinstance(data.get('wellness'), dict) else {}
    # A develop step is a "step", with no title: it is compared like the rest.
    acts = [({'title': a['step'], 'detail': '', 'horizon': a.get('horizon')} if isinstance(a, dict) and isinstance(a.get('step'), str) and not a.get('title') else a)
            for d in (dev.get('develop') or []) if isinstance(d, dict) for a in (d.get('actions') or [])]
    steps = [x for x in acts + list(car.get('actions') or []) + list(well.get('suggestions') or [])
             if isinstance(x, dict) and isinstance(x.get('title'), str) and x['title'].strip()]
    same = first_same(steps, 'the plan')
    if same:
        return same
    for i in range(len(steps)):
        for j in range(i + 1, len(steps)):
            shared = [t for t in PLAN_THEMES if t in themes_of(steps[i]) and t in themes_of(steps[j])]
            if len(shared) >= 3:
                return ['the plan: "%s" and "%s" ask for the same move (%s); the plan keeps one of them and gives the other place to a different step'
                        % (steps[i]['title'][:60], steps[j]['title'][:60], ', '.join(shared))]
    return []


def edge_problems(data):
    """psycheai.io's edgeProblems: "Your edge" repeating one of their other strengths."""
    ca = data.get('careerAssessment') if isinstance(data.get('careerAssessment'), dict) else {}
    e = ca.get('edge') if isinstance(ca.get('edge'), dict) else None
    if not e or not e.get('headline'):
        return []
    edge = {'title': e['headline'], 'detail': e.get('detail') or ''}
    car = data.get('career') if isinstance(data.get('career'), dict) else {}
    same = next((x for x in car.get('strengths') or [] if isinstance(x, dict) and isinstance(x.get('title'), str) and same_point(edge, x)), None)
    return ['career.strengths: "%s" makes the same point as careerAssessment.edge "%s": name a different strength there'
            % (same['title'][:60], e['headline'][:60])] if same else []


def list_problems(data):
    out = []

    def walk(node, path):
        if out or not isinstance(node, (dict, list)):
            return
        if isinstance(node, list):
            if len(node) > 1 and all(isinstance(x, dict) and isinstance(x.get('title'), str) for x in node):
                out.extend(first_same(node, path))
            for x in node:
                walk(x, path)
            return
        for k, v in node.items():
            if k not in ('actions', 'suggestions'):
                walk(v, path + '.' + k if path else k)
    walk(data, '')
    return out[:1]


def check_answer(path):
    """bin/psyche.py check-answer FILE: the answer file as publish_psyche will take it, checked here first."""
    try:
        with open(path.lstrip('@'), encoding='utf-8') as f:
            raw = f.read()
        args = json.loads(raw)
    except OSError:
        return {'ok': False, 'problems': ['No file at %s.' % path]}
    except ValueError as err:
        return {'ok': False, 'problems': ['Not valid JSON: %s.' % err]}
    answer = args.get('answer') if isinstance(args, dict) and 'answer' in args else args
    if not isinstance(answer, dict):
        return {'ok': False, 'problems': ['The answer is not a JSON object.']}
    guide = pinned_guide()
    schema = guide['read']['schema'] if guide else {}
    # What would stop or hold the publish: these are fixed first.
    problems = ['answer is missing the %s section' % k for k in schema.get('required', []) if k not in answer]
    problems += answer_problems(answer) + confidence_problems(answer) + quote_problems(answer)
    problems += ei_problems(answer) + holding_problems(answer) + edge_problems(answer) + plan_problems(answer) + list_problems(answer) + sample_problems(answer)
    if isinstance(args, dict) and 'answer' in args and not args.get('name'):
        problems.append('name is empty: put their full name from their Meta account details.')
    if isinstance(args, dict) and 'answer' not in args:
        notes_first = 'publish it as bin/psyche.py call publish_psyche @answer.json --name "<their full name>" (a bare answer needs --name), or wrap it as {"answer": ..., "name": "<their full name>"}'
    else:
        notes_first = None
    # Where it differs from the guide's schema below the top: worth fixing, but publish_psyche is the judge.
    notes = [n for n in schema_problems(answer, schema, schema.get('$defs', {})) if not n.startswith('answer is missing ')] if schema else []
    out = {'ok': not problems, 'problems': problems[:25], 'schema': notes[:20]}
    if notes_first:
        out['publish'] = notes_first
    return out


def read_starting(now=None):
    """Whether this get_report_guide call starts a read: none other in the last half hour (its own mark is the latest)."""
    now = now or time.time()
    try:
        with open(TIMING) as f:
            marks = json.load(f)
    except (OSError, ValueError):
        return True
    return sum(1 for m in marks if isinstance(m, list) and len(m) == 2 and m[0] == 'call:get_report_guide' and now - m[1] < 1800) <= 1


def with_pinned_guide(tool, args, out):
    """get_report_guide and get_sync, with the guide from this signed release in place of a server's."""
    guide = pinned_guide()
    if tool == 'get_report_guide':
        if not guide:
            return {'error': 'The guide that comes with the skill is missing: run bin/psyche.py update.'}
        read = guide['read']
        deep = isinstance(args, dict) and args.get('depth') == 'deep'
        out = {'spec': read['spec'] + (guide.get('deepSpec', '') if deep else ''), 'rubric': read.get('rubric'), 'schema': read['schema']}
        out['outline'] = schema_outline(read['schema'])
        # The first guide call of a read is where reading starts: the line saying how long it takes goes out
        # before it, as its own message (README "The wait line comes first"), not at the end with the card.
        if read_starting():
            out['sayFirst'] = ('Before reading anything: if step 1\'s line ("On it. ... takes about 5 minutes ...") is not '
                               'already in the chat for this read, send it now as its own message, then read.')
        return out
    if tool == 'get_sync' and isinstance(out, dict) and 'spec' in out:
        if not guide:
            return {'error': 'The guide that comes with the skill is missing: run bin/psyche.py update.'}
        sync = guide['sync']
        out.update(spec=sync['spec'], schema=sync['schema'], task=sync['brief'] + SYNC_TASK)
    return out


# ---------- result lines (README "Result lines are signed") ----------
# A result's own lines on how to show it, and its buttons, come live from the
# server, unsigned. Its show, after and first lines are left out (SKILL.md
# carries the signed ones), and a button stays only if its label is one this
# skill knows, or one of the few that carry a name or a count.
UNSIGNED = ('show', 'after', 'first', 'namesFirst')
LABELS = frozenset([
    'Generate my Psyche', 'Generate my Psyche. DMs included (Recommended)', 'Generate my Psyche. DMs excluded', 'What will I learn?', 'Is it private?',
    'Fresh Psyche. DMs included (Recommended)', 'Fresh Psyche. DMs excluded', 'I\'ve connected them', 'Continue without messages', 'Not now',
    'Reveal my roast 🔥', 'Get the PDF', 'Ask PsycheAI questions about myself', 'Sync with a friend', 'Weekly check-ins on my plan',
    'Add WhatsApp or Facebook as data source', 'Find potential romantic matches', 'Join the Psyche Pair waitlist', 'See this week\'s matches',
    'Facebook and Messenger', 'Facebook posts only', 'Facebook posts', 'Add WhatsApp or Facebook', 'WhatsApp chats', 'I\'ve shared my chats', 'I\'ve connected it', 'My Syncs',
    'Done', 'Yes', 'No thanks', 'Someone else', 'I\'ll share it myself', 'Sync with someone else', 'Sync with someone new', 'Write it again',
    'Answer here instead', 'Looks right', 'Change something', 'Add a must-have', 'Add another', 'That\'s all', 'Not this week',
    'See who picked me', 'See my other matches', 'Yes, I\'d like to meet', 'Chat privately', 'Swap Instagram',
    'Sunday evening', 'Monday morning', 'Not yet', 'Change it', 'Stop check-ins', 'Try again', 'Save to PsycheAI',
    'Explain why you said this', 'Correct something', 'More', 'Fresh Psyche', 'Add WhatsApp as data source', 'My data and privacy',
    'Delete everything', 'Yes, delete everything', 'Cancel', 'Privacy policy', 'Include my messages (Recommended)', 'Posts only'])
LABEL_FORMS = [re.compile(r'^My Syncs \(\d{1,3} new\)$'), re.compile(r'^Show my Sync with [^\n@/:]{1,40}$'), re.compile(r'^Pick [^\n@/:]{1,30}$')]


def known_label(label):
    return isinstance(label, str) and (label in LABELS or any(f.match(label) for f in LABEL_FORMS))


def clean_result(value):
    """The result with its unsigned lines left out and only known buttons kept."""
    if isinstance(value, list):
        return [clean_result(v) for v in value if not (isinstance(v, dict) and 'label' in v and not known_label(v['label']))]
    if not isinstance(value, dict):
        return value
    out = {}
    for k, v in value.items():
        if k in UNSIGNED:
            continue
        if k == 'buttons' and isinstance(v, list):
            out[k] = [b for b in v if known_label(b)]
            continue
        out[k] = clean_result(v)
    return out


def call(tool, args):
    if tool == 'get_report_guide':
        return with_pinned_guide(tool, args, None)
    acc = account()
    if tool == 'sync_with':
        keep_keys(text=args.get('link'))     # the code in a friend's link is the key to their card and your Sync
    if tool == 'publish_psyche':
        args = dict(args, forFile=True)     # the whole report, evidence included, for the report file (README "The report as a file")
    msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': tool, 'arguments': args}}
    status, body = post('/mcp', msg, acc['access_token'], extra=key_headers())
    if status == 401:
        acc = refresh(acc)
        status, body = post('/mcp', msg, acc['access_token'], extra=key_headers())
    if 'error' in body:
        return {'error': body['error'].get('message', 'PsycheAI could not run that.')}
    result = body.get('result', {})
    out = result.get('structuredContent') or {}
    if out.get('cardKey'):
        keep_keys(card=out.pop('cardKey'))
    if tool == 'sync_link' and out.get('url'):
        keep_keys(text=out['url'])
    out = clean_result(with_pinned_guide(tool, args, out))
    files = [c for c in result.get('content', []) if c.get('type') == 'resource_link']
    if files:
        out['files'] = files
    return out


def passages(value, out=None):
    """Every sentence-long string in a report (40 characters or more), to compare two reports by."""
    out = set() if out is None else out
    if isinstance(value, dict):
        for v in value.values():
            passages(v, out)
    elif isinstance(value, list):
        for v in value:
            passages(v, out)
    elif isinstance(value, str) and len(value) >= 40:
        out.add(re.sub(r'\s+', ' ', value).strip())
    return out


REUSED = 0.3        # this share of last time's passages, word for word, is last time's report: a rewrite from scratch shares almost none


# What a report may hold when it leaves the workspace (README "What leaves the
# workspace"): checked here, by the signed script, whatever a guide or a tool
# result says, so nothing outside this folder can make it carry raw content.
ANSWER_CHARS = 150000       # a full report is about 50,000
STRING_CHARS = 4000         # its longest paragraph is about 1,500
ANSWER_LEAKS = [
    ('a handle', re.compile(r'(?<![\w@])@[A-Za-z0-9._]{2,30}')),
    ('a link', re.compile(r'https?://|www\.', re.I)),
    ('an email', re.compile(r'[\w.+-]+@[\w-]+\.[\w.-]+')),
    ('a phone number', re.compile(r'\+\d[\d ]{7,}\d|(?<!\d)\d{8,}(?!\d)')),
]


def strings_in(value, at='answer'):
    if isinstance(value, dict):
        for k, v in value.items():
            yield from strings_in(v, '%s.%s' % (at, k))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from strings_in(v, '%s[%d]' % (at, i))
    elif isinstance(value, str):
        yield at, value


def answer_problems(answer):
    """Why a report can't leave the workspace as it is: too big for a report, or holding a handle, link, email or number."""
    if not isinstance(answer, dict):
        return []
    problems = []
    size = len(json.dumps(answer, ensure_ascii=False))
    if size > ANSWER_CHARS:
        problems.append('The report is %d characters, more than a report holds (about %d at most): it carries the report only, never messages or posts as they are.' % (size, ANSWER_CHARS))
    for at, text in strings_in(answer):
        if len(text) > STRING_CHARS:
            problems.append('%s is %d characters: no part of a report runs past %d.' % (at, len(text), STRING_CHARS))
        for label, rx in ANSWER_LEAKS:
            if rx.search(text):
                problems.append('%s has %s: take it out.' % (at, label))
                break
    return problems[:20]


# The website's confidence rubric (psycheai.io lib/prompts.js CONFIDENCE_SCORING, README "Confidence follows
# the rubric"): Instagram, its messages included, is one strong source and stops at 79; Facebook (posts or
# Messenger) or WhatsApp chats lift it to 86, both to 90. Checked here because the score is a number, not a judgement.
def confidence_problems(answer):
    conf = answer.get('confidence') if isinstance(answer, dict) else None
    if not isinstance(conf, dict) or not isinstance(conf.get('score'), (int, float)):
        return []
    head = ''
    if os.path.exists(DIGEST):
        with open(DIGEST, encoding='utf-8') as f:
            head = '\n'.join(f.read().splitlines()[:6])
    sources = (re.search(r'sources:\s*([^\n·]+)', head) or [0, 'instagram'])[1].lower()
    strong = 1 + bool(re.search(r'facebook|messenger', sources) or os.path.exists(os.path.join(SOURCES, 'facebook.txt'))) + os.path.exists(os.path.join(SOURCES, 'whatsapp.txt'))
    cap, read = {1: 79, 2: 86}.get(strong, 90), {1: 'Instagram alone', 2: 'two strong sources'}.get(strong, 'Instagram, Facebook and WhatsApp')
    score, problems = conf['score'], []
    if score > cap:
        problems.append('confidence.score is %d: from %s it is at most %d (65 to 79 for Instagram, its messages included; 72 to 86 with Facebook or WhatsApp chats; 76 to 90 with both).' % (score, read, cap))
    level = 'high' if score >= 75 else 'moderate' if score >= 60 else 'low' if score >= 40 else 'very low'
    if conf.get('level') and conf['level'] != level and score <= cap:
        problems.append('confidence.level is "%s" for a score of %d: it is "%s" (high from 75, moderate 60 to 74, low 40 to 59, very low under 40).' % (conf['level'], score, level))
    return problems


# Once a report is published, what others wrote goes (README "Their own words stay"): the
# "> " lines are context for writing a read, and every check that uses them runs before
# publishing. Their own lines stay, for "explain" and for the next read to add to.
def drop_context():
    for path in (DIGEST, os.path.join(SOURCES, 'whatsapp.txt'), os.path.join(SOURCES, 'facebook.txt')):
        if not os.path.exists(path):
            continue
        with open(path, encoding='utf-8') as f:
            lines = f.read().splitlines()
        kept = [l for l in lines if not l.startswith('>')]
        if len(kept) != len(lines):
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(kept) + '\n')
            os.chmod(path, 0o600)


# What others wrote is context in the digest, never quoted in the report (README "Threads, never quoted"):
# six words in a row from a "> " line, anywhere in the answer, holds it.
def quote_problems(answer):
    if not isinstance(answer, dict):
        return []
    said = []
    for path in (DIGEST, os.path.join(SOURCES, 'whatsapp.txt'), os.path.join(SOURCES, 'facebook.txt')):
        if os.path.exists(path):
            with open(path, encoding='utf-8') as f:
                said += [re.findall(r"[\w']+", l.lower().split(':', 1)[-1]) for l in f if l.startswith('>')]
    runs = {' '.join(w[i:i + 6]) for w in said for i in range(len(w) - 5)}
    if not runs:
        return []
    problems = []
    for at, text in strings_in(answer):
        w = re.findall(r"[\w']+", text.lower())
        if any(' '.join(w[i:i + 6]) in runs for i in range(len(w) - 5)):
            problems.append('%s quotes what someone else wrote in a thread: it is context only, never quoted.' % at)
    return problems[:10]


def before_publish(args):
    """Why a new Psyche isn't saved yet, or None: the report holds what it can't, the digest still has
    problems, or it's mostly the report already saved although what it's read from has changed since."""
    leaving = answer_problems(args.get('answer')) + confidence_problems(args.get('answer')) + quote_problems(args.get('answer'))
    if leaving:
        return {'saved': False, 'report': 'not ready', 'problems': leaving}
    if not os.path.exists(DIGEST):
        return None
    digest = check_digest()
    if digest.get('problems'):
        return {'saved': False, 'digest': 'not ready', 'problems': digest['problems']}
    kept = read_first([REPORT, REPORT_KEPT])
    answer = args.get('answer')
    if not kept or not isinstance(answer, dict) or not isinstance(kept.get('report'), dict):
        return None
    kept_at = max((os.path.getmtime(f) for f in (REPORT, REPORT_KEPT) if os.path.exists(f)), default=0)
    sources = [DIGEST] + [os.path.join(SOURCES, f) for f in os.listdir(SOURCES)] if os.path.isdir(SOURCES) else [DIGEST]
    if max(os.path.getmtime(f) for f in sources) <= kept_at:
        return None
    before, now = passages(kept['report']), passages(answer)
    same = json.dumps(kept['report'], sort_keys=True) == json.dumps(answer, sort_keys=True)
    if same or (before and len(before & now) / len(before) >= REUSED):
        return {'saved': False, 'report': 'unchanged',
                'problems': [('This is the report saved last time, word for word' if same else 'Most of this is the report saved last time, word for word (%d of its %d passages)' % (len(before & now), len(before))) +
                             ', and what it is read from has grown since: a fresh Psyche is written anew from the digest and any added chats, so what they add can change its conclusions.']}
    return None


# ---------- check-ins (README "Check-ins") ----------
# The plan their report made (develop steps, career actions, wellness
# suggestions), one step at a time, and what they said about each, kept only
# here. A step closes on done or drop; "not yet" keeps it open.

def plan_of(report):
    out = []
    dev = (report.get('development') or {}).get('develop') or []
    for d in dev:
        for a in d.get('actions') or []:
            if a.get('step'):
                out.append({'horizon': a.get('horizon') or '', 'step': a['step'], 'from': d.get('title') or ''})
    for a in (report.get('careerAssessment') or {}).get('actions') or []:
        if a.get('title'):
            out.append({'horizon': a.get('horizon') or '', 'step': a['title'] + (': ' + a['detail'] if a.get('detail') else ''), 'from': 'How you work'})
    for a in (report.get('wellness') or {}).get('suggestions') or []:
        if a.get('title'):
            out.append({'horizon': 'this week', 'step': a['title'] + (': ' + a['detail'] if a.get('detail') else ''), 'from': 'Wellbeing'})
    order = {'this week': 0, 'this quarter': 1, 'this year': 2}
    out.sort(key=lambda x: order.get(x['horizon'], 3))
    for i, x in enumerate(out):
        x['id'] = 'p%d' % (i + 1)
    return out


def checkin(args):
    kept = read_first([REPORT, REPORT_KEPT])
    if not kept or not isinstance(kept.get('report'), dict):
        return {'error': 'No Psyche Report kept here yet, so there is no plan to check in on. Make one first.'}
    plan = plan_of(kept['report'])
    coach = read_first([COACH, COACH_KEPT]) or {}
    saved_at = max((os.path.getmtime(f) for f in (REPORT, REPORT_KEPT) if os.path.exists(f)), default=time.time())
    # A new Psyche makes a new plan: answers about the old one don't carry over.
    if coach.get('report') != int(saved_at):
        coach = {'report': int(saved_at), 'steps': {}, 'notes': []}
    if args:
        sid, said = args[0], (args[1] if len(args) > 1 else '')
        if sid not in {x['id'] for x in plan} or said not in ('done', 'not-yet', 'drop'):
            return {'error': 'Use: checkin ID done|not-yet|drop [--note TEXT], with an ID from the plan.'}
        note = args[args.index('--note') + 1][:500] if '--note' in args and args.index('--note') + 1 < len(args) else ''
        today = datetime.now().strftime('%Y-%m-%d')
        coach['steps'][sid] = {'status': said, 'on': today}
        if note:
            coach['notes'] = (coach.get('notes') or [])[-19:] + [{'on': today, 'step': sid, 'said': note}]
        write_private([COACH, COACH_KEPT], coach)
    status = coach.get('steps') or {}
    for x in plan:
        x['status'] = (status.get(x['id']) or {}).get('status', 'open')
    open_ = [x for x in plan if x['status'] in ('open', 'not-yet')]
    weeks = int((time.time() - saved_at) / (7 * 86400))
    return {'ok': True, 'next': open_[0] if open_ else None, 'open': len(open_), 'done': sum(1 for x in plan if x['status'] == 'done'),
            'plan': plan, 'lastNotes': (coach.get('notes') or [])[-3:], 'weeksSincePsyche': weeks, 'freshDue': weeks >= 4}


# ---------- explain and correct (README "Explain and correct") ----------
# The report's main findings, each with what it rests on: its own evidence and
# the digest lines of theirs it came from (never anyone else's words), and,
# for a type letter, what pulled the other way.
AXES_NAMES = {'E': 'Extraversion', 'I': 'Introversion', 'N': 'Intuition', 'S': 'Sensing', 'T': 'Thinking', 'F': 'Feeling', 'J': 'Judging', 'P': 'Perceiving'}
MONTHS = {m: i + 1 for i, m in enumerate(['january', 'february', 'march', 'april', 'may', 'june', 'july', 'august', 'september', 'october', 'november', 'december'])}


def findings(report):
    out = []
    ess = report.get('essence') or {}
    if ess.get('character'):
        out.append({'id': 'character', 'label': 'Most like %s' % ess['character'], 'said': ess.get('why') or '', 'evidence': []})
    for l in (report.get('mbti') or {}).get('letters') or []:
        axis, pick = l.get('axis') or '', l.get('choice') or ''
        other = ''.join(c for c in axis if c.isalpha() and c != pick)[:1]
        if pick:
            out.append({'id': 'type-' + pick, 'label': '%s over %s' % (AXES_NAMES.get(pick, pick), AXES_NAMES.get(other, other)), 'said': l.get('why') or '',
                        'evidence': l.get('evidence') or [], 'otherWay': [r.get('note') for r in l.get('ledger') or [] if r.get('pointsTo') == other and r.get('note')][:3]})
    for i, pt in enumerate(report.get('patterns') or []):
        if pt.get('name'):
            out.append({'id': 'pattern-%d' % (i + 1), 'label': pt['name'], 'said': pt.get('line') or '', 'evidence': pt.get('evidence') or []})
    att = report.get('attachment') or {}
    if att.get('style'):
        out.append({'id': 'attachment', 'label': 'Attachment: %s' % att['style'], 'said': att.get('why') or '', 'evidence': att.get('derivedFrom') or []})
    top = report.get('topMotivators') or []
    if top:
        out.append({'id': 'drive', 'label': 'Top drive: %s' % str(top[0]).capitalize(), 'said': (report.get('motivators') or {}).get('reading') or '', 'evidence': []})
    edge = (report.get('careerAssessment') or {}).get('edge') or {}
    if edge.get('headline'):
        out.append({'id': 'career', 'label': 'Your edge at work', 'said': edge['headline'] + ('. ' + edge['detail'] if edge.get('detail') else ''), 'evidence': edge.get('evidence') or []})
    return out


def digest_lines_for(evidence, limit=3):
    """Their own digest lines behind evidence phrases ("your June 2026 comment ..."): same month, shared words."""
    if not os.path.exists(DIGEST):
        return []
    with open(DIGEST, encoding='utf-8') as f:
        lines = [l.rstrip('\n') for l in f if DATED.match(l)]
    out = []
    for item in evidence:
        m = re.search(r'(january|february|march|april|may|june|july|august|september|october|november|december)\s+(\d{4})', str(item).lower())
        stems = lambda t: {w[:4] for w in re.findall(r'[a-z]{4,}', t.lower())} - {'your', 'with', 'from', 'that', 'this', 'they', 'thei', 'abou', 'mess', 'post', 'stor', 'comm'}
        words = stems(str(item))
        best = None
        for l in lines:
            if m and not l.startswith('%s-%02d' % (m.group(2), MONTHS[m.group(1)])):
                continue
            score = len(words & stems(l))
            if score >= 2 and (best is None or score > best[0]):
                best = (score, l)
        if best and best[1] not in out:
            out.append(best[1][:400])
        if len(out) >= limit:
            break
    return out


def why(args):
    kept = read_first([REPORT, REPORT_KEPT])
    if not kept or not isinstance(kept.get('report'), dict):
        return {'error': 'No Psyche Report kept here yet. Make one first.'}
    found = findings(kept['report'])
    if not args:
        return {'ok': True, 'pick': [{'id': f['id'], 'label': f['label']} for f in found]}
    f = next((x for x in found if x['id'] == args[0]), None)
    if not f:
        return {'error': 'Pick one of: ' + ', '.join(x['id'] for x in found)}
    return {'ok': True, **f, 'fromTheirOwnWords': digest_lines_for(f['evidence'])}


def correct(args):
    data = read_first([CORRECTIONS, CORRECTIONS_KEPT]) or {'corrections': []}
    if not args:
        return {'ok': True, 'corrections': data.get('corrections') or []}
    kept = read_first([REPORT, REPORT_KEPT])
    found = findings(kept['report']) if kept and isinstance(kept.get('report'), dict) else []
    f = next((x for x in found if x['id'] == args[0]), None)
    # A 👎 on a section of "Your report in short": the section's title stands in for a finding.
    if not f and args[0].startswith('section:') and args[0][8:].strip():
        f = {'id': args[0], 'label': args[0][8:].strip()[:60], 'said': ''}
    how = args[1] if len(args) > 1 else ''
    if not f or how not in ('not-me', 'partly', 'used-to-be'):
        return {'error': 'Use: correct ID not-me|partly|used-to-be --note TEXT, with an ID from bin/psyche.py why.'}
    note = args[args.index('--note') + 1][:500] if '--note' in args and args.index('--note') + 1 < len(args) else ''
    entry = {'on': datetime.now().strftime('%Y-%m-%d'), 'finding': f['label'], 'said': f['said'][:300], 'how': how, 'theirWords': note}
    data['corrections'] = [c for c in data.get('corrections') or [] if c.get('finding') != f['label']][-29:] + [entry]
    write_private([CORRECTIONS, CORRECTIONS_KEPT], data)
    return {'ok': True, 'saved': entry}


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return
    if argv[0] in ('status', 'update', 'check-digest', 'build-digest', 'collect', 'prep', 'republish', 'report', 'checkin', 'why', 'correct') or (argv[0] in ('call', 'show') and len(argv) >= 2):
        mark(argv[0] if argv[0] not in ('call', 'show') else argv[0] + ':' + re.sub(r'[^a-z_]', '', argv[1].lower())[:30])
    if argv[0] == 'status':
        account()
        out = {'ok': True, 'connected': True, 'version': local_version()}
        try:
            latest = json.loads(get('/skill/files').decode()).get('version')
            out['update_available'] = bool(latest and latest != out['version'])
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError, ValueError):
            pass
        print(json.dumps(out))
        return
    if argv[0] == 'update':
        print(json.dumps(update()))
        return
    if argv[0] == 'first-run':
        print(json.dumps(first_run(), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'accounts':
        try:
            out = account_choice()
        except (RuntimeError, RateLimited) as err:
            out = {'accounts': None, 'problem': 'The account lists could not be read here (%s).' % type(err).__name__}
        out['stepOne'] = FRESH_STEP_ONE
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if argv[0] == 'call' and len(argv) >= 2:
        raw = argv[2] if len(argv) > 2 else '{}'
        if raw.startswith('@'):
            with open(raw[1:]) as f:
                raw = f.read()
        args = json.loads(raw)
        # A bare answer file is taken as the answer, with --name "<their full name>" (README "Straight to the card").
        if argv[1] == 'publish_psyche' and isinstance(args, dict) and 'answer' not in args:
            name = argv[argv.index('--name') + 1] if '--name' in argv[:-1] else ''
            args = {'answer': args, 'name': name}
        if argv[1] == 'publish_psyche' and isinstance(args, dict) and '--name' in argv[:-1] and not args.get('name'):
            args['name'] = argv[argv.index('--name') + 1]
        if argv[1] == 'save_sync' and answer_problems(args.get('answer')):
            print(json.dumps({'saved': False, 'problems': answer_problems(args.get('answer'))}, ensure_ascii=False, indent=1))
            return
        if argv[1] == 'publish_psyche':
            held = before_publish(args)
            if held:
                print(json.dumps(held, ensure_ascii=False, indent=1))
                return
        out = call(argv[1], args)
        # Their report stays in this workspace for Ask PsycheAI in later chats.
        if argv[1] == 'publish_psyche' and out.get('ok') and isinstance(args.get('answer'), dict):
            write_private([REPORT, REPORT_KEPT], {'name': args.get('name'), 'report': args['answer']})
            built = os.path.join(os.path.dirname(DIGEST), '.built')
            if os.path.exists(built):
                os.remove(built)
            # What was pulled from Instagram for it goes now, and what others wrote with it:
            # the digest (their own words) and the report stay.
            shutil.rmtree(WORK, ignore_errors=True)
            drop_context()
            out = saved(out)
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if argv[0] == 'collect-facebook':
        me = argv[argv.index('--me') + 1] if '--me' in argv and argv.index('--me') + 1 < len(argv) else None
        print(json.dumps(collect_facebook(me, '--no-messenger' not in argv), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'prep' and len(argv) >= 2:
        files, me, deep, i = [], None, False, 1
        while i < len(argv):
            if argv[i] == '--me' and i + 1 < len(argv):
                me, i = argv[i + 1], i + 2
            elif argv[i] == '--deep':
                deep, i = True, i + 1
            else:
                files.append(argv[i])
                i += 1
        print(json.dumps(prep(files, me, deep), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'republish':
        kept = read_first([REPORT, REPORT_KEPT])
        if not kept or not isinstance(kept.get('report'), dict):
            print(json.dumps({'error': 'No Psyche Report kept here yet. Make one first.'}))
            return
        leaving = answer_problems(kept['report'])
        if leaving:
            print(json.dumps({'saved': False, 'report': 'not ready', 'problems': leaving}, ensure_ascii=False, indent=1))
            return
        out = call('publish_psyche', {'answer': kept['report'], 'name': kept.get('name') or ''})
        print(json.dumps(saved(out) if out.get('ok') else out, ensure_ascii=False, indent=1))
        return
    if argv[0] == 'show' and len(argv) >= 2 and argv[1] == 'probe':
        print(json.dumps({'widget': PROBE_HTML, 'show': 'The phone check: show widget as one interactive HTML widget, exactly as given.'}, ensure_ascii=False))
        return
    if argv[0] == 'show' and len(argv) >= 2:
        last = read_first([LAST])
        if not last or argv[1] not in PARTS:
            print(json.dumps({'error': 'Nothing saved to show yet.' if not last else 'Parts: ' + ', '.join(PARTS)}))
            return
        print(json.dumps(PARTS[argv[1]](last), ensure_ascii=False, indent=1), flush=True)
        if os.path.exists(TIMING) and argv[1] != 'ready':
            send_timing()
        return
    if argv[0] == 'check-digest':
        print(json.dumps(check_digest(), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'forget':
        everything = '--everything' in argv[1:]
        for d in (WORK, SOURCES, NOTES) + ((os.path.dirname(DIGEST), OUT) if everything else ()):
            shutil.rmtree(d, ignore_errors=True)
        if everything:
            # Without its keys, what PsycheAI keeps locked for them can't be opened by anyone.
            for f in (REPORT, REPORT_KEPT, KEYS, KEYS_KEPT, COACH, COACH_KEPT, CORRECTIONS, CORRECTIONS_KEPT):
                if os.path.exists(f):
                    os.remove(f)
        print(json.dumps({'ok': True, 'deleted': ['work/', 'sources/', 'notes/'] + (['digest/', 'report.json', 'keys', 'check-ins', 'corrections'] if everything else [])}))
        return
    if argv[0] == 'build-digest':
        print(json.dumps(build_digest(), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'collect':
        if '--help' in argv or '-h' in argv:
            print(json.dumps({'usage': 'bin/psyche.py collect --account-id <instagram-cli user_fbid> [--messages-account-id <instagram-messages-cli user_fbid>] [--me "<their full name>"] [--no-messages]'}, indent=1))
            return
        opts, i = {}, 1
        while i < len(argv):
            if argv[i] == '--no-messages':
                opts['no'], i = True, i + 1
            elif argv[i] in ('--account-id', '--messages-account-id', '--me', '--threads') and i + 1 < len(argv):
                opts[argv[i]], i = argv[i + 1], i + 2
            else:
                i += 1
        try:
            n = max(1, min(30, int(opts.get('--threads') or COLLECT_THREADS)))
        except ValueError:
            n = COLLECT_THREADS
        mark('collect')             # a read starts here: an earlier attempt's marks don't count (lib/timing.js)
        out = collect(opts.get('--account-id'), opts.get('--messages-account-id'), opts.get('--me'), n, not opts.get('no'))
        if out.get('ok') is not False or out.get('built'):
            mark('check-digest')    # the digest is built and checked: the read's reading stage ends here
        # What it read, kept beside the digest (counts and notes only: no ID, cursor or message), so
        # "last-collect" can show it after a helper ran it (README "The last collect, kept").
        if out.get('read'):
            write_private([LAST_COLLECT], {'at': datetime.now().strftime('%Y-%m-%d %H:%M'), 'account': account_tag(opts.get('--account-id')), 'messages': not opts.get('no'),
                                           **{k: out[k] for k in ('ok', 'read', 'notes', 'stopped', 'problems', 'characters') if k in out}})
        print(json.dumps(out, ensure_ascii=False, indent=1))
        return
    if argv[0] == 'last-collect':
        print(json.dumps(read_first([LAST_COLLECT]) or {'error': 'No collect has run here yet.'}, ensure_ascii=False, indent=1))
        return
    if argv[0] == 'check-answer' and len(argv) >= 2:
        print(json.dumps(check_answer(argv[1]), ensure_ascii=False, indent=1))
        return
    if argv[0] in ('why', 'correct'):
        print(json.dumps((why if argv[0] == 'why' else correct)(argv[1:]), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'checkin':
        print(json.dumps(checkin(argv[1:]), ensure_ascii=False, indent=1))
        return
    if argv[0] == 'report':
        kept = read_first([REPORT, REPORT_KEPT])
        if not kept:
            print(json.dumps({'error': 'No Psyche Report kept here yet. Make one first.'}))
            return
        if not os.path.exists(REPORT):
            write_private([REPORT], kept)
        print(json.dumps(kept, ensure_ascii=False))
        return
    sys.exit('Usage: bin/psyche.py status | update | report | republish | show PART | prep FILE... [--me NAME] [--deep] | check-digest | forget [--everything] | call TOOL [JSON | @FILE]')


if __name__ == '__main__':
    main(sys.argv[1:])
