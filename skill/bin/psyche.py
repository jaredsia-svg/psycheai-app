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
  bin/psyche.py show PART              one part of what publish_psyche gave back, kept here:
                                       card (saved as a picture), summary, pdf (saved as a file), links or next (README "One part at a time")
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
RELEASE = 22
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
LAST = os.path.join(HERE, 'last-psyche.json')   # what the latest publish gave back, shown a part at a time

# A saved Psyche's result in parts, so the chat can show each on its own: one
# part a host won't use no longer holds back the rest.
OUT = os.path.join(HERE, 'out')                 # the PDF as a file here, so the chat opens it in Muse, not a browser


def saved_at():
    """When the Psyche being shown was saved, as "1432" (its last-psyche.json's time)."""
    try:
        return datetime.fromtimestamp(os.path.getmtime(LAST)).strftime('%H%M')
    except OSError:
        return datetime.now().strftime('%H%M')


def local_pdf(r):
    """The report's PDF saved in out/, so it's attached as a file rather than linked."""
    link = r.get('pdf')
    files = [f for f in r.get('files', []) if f.get('mimeType') == 'application/pdf']
    name = re.sub(r'[^\w .&()-]', '', r.get('pdfName') or (files[0].get('name') if files else '') or 'Psyche Report.pdf') or 'Psyche Report.pdf'
    # The save's time in the name, so each save's PDF is a new file to the chat, never taken for one sent before.
    name = re.sub(r'\.pdf$', '', name, flags=re.I) + ' ' + saved_at() + '.pdf'
    out = {'pdf': link}
    if not link:
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
            req = urllib.request.Request('%s://%s/api/import/pdf?id=%s' % (parts.scheme, parts.netloc, urllib.parse.quote(pid)),
                                         headers={'Accept': 'application/pdf', 'X-Psyche-Key': parts.fragment})
        else:
            req = urllib.request.Request(link, headers={'Accept': 'application/pdf'})
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
        if not body.startswith(b'%PDF'):
            raise ValueError('not a PDF')
        path = os.path.join(OUT, name)
        with open(path, 'wb') as f:
            f.write(body)
        os.chmod(path, 0o600)
        out['file'] = path
    except (OSError, ValueError, urllib.error.URLError):
        out['files'] = files
    return out


def local_card(r):
    """Their Psyche Card as a picture saved in out/, so it's attached as an image rather than a link preview."""
    link = r.get('image')
    out = {'image': link}
    if not link:
        return out
    try:
        os.makedirs(OUT, exist_ok=True)
        req = urllib.request.Request(link, headers={'Accept': 'image/png'})
        with urllib.request.urlopen(req, timeout=60) as res:
            body = res.read()
        if not body.startswith(b'\x89PNG'):
            raise ValueError('not a PNG')
        for old in os.listdir(OUT):
            if old.lower().endswith('.png'):
                os.remove(os.path.join(OUT, old))
        path = os.path.join(OUT, 'Psyche Card ' + saved_at() + '.png')
        with open(path, 'wb') as f:
            f.write(body)
        os.chmod(path, 0o600)
        out['file'] = path
    except (OSError, ValueError, urllib.error.URLError):
        pass
    return out


PARTS = {
    'card': local_card,
    'summary': lambda r: {'sections': r.get('sections', [])},
    'pdf': local_pdf,
    'links': lambda r: {'url': r.get('url'), 'story': r.get('story')},
    'next': lambda r: {'nextStep': r.get('nextStep'), 'askIdeas': r.get('askIdeas')},
}


def saved(out):
    """Keep a publish result here and say only that it's saved, and its parts."""
    # The last Psyche's PDF goes, so only this one's can be attached: show pdf fetches it.
    shutil.rmtree(OUT, ignore_errors=True)
    write_private([LAST], out)
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
    return {'posts': posts, 'top': top, 'rest': rest}


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


def check_digest(path=DIGEST):
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
    captioned = re.search(r'([\d,]+)\s+captioned', head)
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
                aim = t['top'] if i < 4 else t['rest']
                goal['Conversation %d' % (i + 1)] = [c['chars'], aim]
                if c['chars'] < SHORT * aim and not c['whole']:
                    problems.append('Conversation %d: %d of about %d characters. %s (or mark it "(whole thread)" if it has no more).' % (
                        i + 1, c['chars'], aim, 'Page further back' if i < 4 else 'Read more of its recent pages'))
                elif i < 4 and not c['whole']:
                    room.append('Conversation %d: page further back next read, towards its first year.' % (i + 1))
            # Their own messages in all: short threads ("(whole thread)") excuse one conversation, never the total,
            # while the inbox has more to read (README "Busiest, measured").
            whole = 4 * t['top'] + 6 * t['rest']
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


def post(path, body, token=None, form=False, extra=None):
    data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
    headers = {'Content-Type': 'application/x-www-form-urlencoded' if form else 'application/json', 'Accept': 'application/json'}
    headers.update(extra or {})
    if token:
        headers['Authorization'] = 'Bearer ' + token

    def attempt():
        req = urllib.request.Request(BASE + path, data=data, headers=headers, method='POST')
        try:
            with urllib.request.urlopen(req, timeout=120) as res:
                return res.status, json.loads(res.read().decode() or '{}')
        except urllib.error.HTTPError as err:
            if err.code in BUSY:
                raise
            try:
                return err.code, json.loads(err.read().decode() or '{}')
            except ValueError:
                return err.code, {}
    try:
        return patiently(attempt)
    except urllib.error.HTTPError as err:
        return err.code, {'error': {'message': 'PsycheAI is busy right now.'}}
    except (urllib.error.URLError, http.client.HTTPException, ConnectionError):
        return 503, {'error': {'message': 'PsycheAI is busy right now.'}}


def get(path):
    def attempt():
        req = urllib.request.Request(BASE + path, headers={'Accept': 'application/json'})
        with urllib.request.urlopen(req, timeout=60) as res:
            return res.read()
    return patiently(attempt)


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
    manifest = json.loads(get('/skill/files').decode())
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
        body = get('/skill/' + name)
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


def with_pinned_guide(tool, args, out):
    """get_report_guide and get_sync, with the guide from this signed release in place of a server's."""
    guide = pinned_guide()
    if tool == 'get_report_guide':
        if not guide:
            return {'error': 'The guide that comes with the skill is missing: run bin/psyche.py update.'}
        read = guide['read']
        deep = isinstance(args, dict) and args.get('depth') == 'deep'
        return {'spec': read['spec'] + (guide.get('deepSpec', '') if deep else ''), 'rubric': read.get('rubric'), 'schema': read['schema']}
    if tool == 'get_sync' and isinstance(out, dict) and 'spec' in out:
        if not guide:
            return {'error': 'The guide that comes with the skill is missing: run bin/psyche.py update.'}
        sync = guide['sync']
        out.update(spec=sync['spec'], schema=sync['schema'], task=sync['brief'] + SYNC_TASK)
    return out


def call(tool, args):
    if tool == 'get_report_guide':
        return with_pinned_guide(tool, args, None)
    acc = account()
    if tool == 'sync_with':
        keep_keys(text=args.get('link'))     # the code in a friend's link is the key to their card and your Sync
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
    out = with_pinned_guide(tool, args, out)
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
    strong = 1 + bool(re.search(r'facebook|messenger', sources)) + os.path.exists(os.path.join(SOURCES, 'whatsapp.txt'))
    cap, read = {1: 79, 2: 86}.get(strong, 90), {1: 'Instagram alone', 2: 'two strong sources'}.get(strong, 'Instagram, Facebook and WhatsApp')
    score, problems = conf['score'], []
    if score > cap:
        problems.append('confidence.score is %d: from %s it is at most %d (65 to 79 for Instagram, its messages included; 72 to 86 with Facebook or WhatsApp chats; 76 to 90 with both).' % (score, read, cap))
    level = 'high' if score >= 75 else 'moderate' if score >= 60 else 'low' if score >= 40 else 'very low'
    if conf.get('level') and conf['level'] != level and score <= cap:
        problems.append('confidence.level is "%s" for a score of %d: it is "%s" (high from 75, moderate 60 to 74, low 40 to 59, very low under 40).' % (conf['level'], score, level))
    return problems


# What others wrote is context in the digest, never quoted in the report (README "Threads, never quoted"):
# six words in a row from a "> " line, anywhere in the answer, holds it.
def quote_problems(answer):
    if not isinstance(answer, dict):
        return []
    said = []
    for path in (DIGEST, os.path.join(SOURCES, 'whatsapp.txt')):
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


def main(argv):
    if not argv or argv[0] in ('-h', '--help'):
        print(__doc__)
        return
    if argv[0] in ('status', 'update', 'check-digest', 'prep', 'republish', 'report') or (argv[0] in ('call', 'show') and len(argv) >= 2):
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
    if argv[0] == 'call' and len(argv) >= 2:
        raw = argv[2] if len(argv) > 2 else '{}'
        if raw.startswith('@'):
            with open(raw[1:]) as f:
                raw = f.read()
        args = json.loads(raw)
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
            # What was pulled from Instagram for it goes now: the digest and the report stay.
            shutil.rmtree(WORK, ignore_errors=True)
            out = saved(out)
            send_timing()
        print(json.dumps(out, ensure_ascii=False, indent=1))
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
    if argv[0] == 'show' and len(argv) >= 2:
        last = read_first([LAST])
        if not last or argv[1] not in PARTS:
            print(json.dumps({'error': 'Nothing saved to show yet.' if not last else 'Parts: ' + ', '.join(PARTS)}))
            return
        print(json.dumps(PARTS[argv[1]](last), ensure_ascii=False, indent=1))
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
            for f in (REPORT, REPORT_KEPT, KEYS, KEYS_KEPT):
                if os.path.exists(f):
                    os.remove(f)
        print(json.dumps({'ok': True, 'deleted': ['work/', 'sources/', 'notes/'] + (['digest/', 'report.json', 'keys'] if everything else [])}))
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
