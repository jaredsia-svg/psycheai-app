#!/usr/bin/env python3
"""Psyche Together: a relationship check-in for two people, in each one's own Muse (README "Psyche Together").

Standard-library Python. It builds on the person's Psyche, which the PsycheAI skill keeps in this
workspace, and on PsycheAI's account, but it runs none of PsycheAI's code. Everything about the two
of them is answered and written here and locked before it's sent: the server keeps boxes it can't open.

  python3 bin/together.py status              what's next for this person
  python3 bin/together.py start               start a new Psyche Together (the one who invites): the stage, then the invite
  python3 bin/together.py join <link>         join with a partner's link
  python3 bin/together.py questions           what Muse writes their questions from (both Psyches), once both have joined
  python3 bin/together.py save-questions @f   save the openers and follow-ups Muse wrote; makes the questions page
  python3 bin/together.py form                the questions page again
  python3 bin/together.py code <PT-…>         the answer code from the page: their answers, then sent
  python3 bin/together.py next | answer <id> <button>   the same questions in the chat, one at a time
  python3 bin/together.py save @f             save the joint read Muse wrote
  python3 bin/together.py save-foryou @f      save their own private "For you"
  python3 bin/together.py show                their page
  python3 bin/together.py end                 end it, for both
  python3 bin/together.py forget              delete everything of it in this workspace
  python3 bin/together.py update              install the latest signed release
"""
import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

BASE = os.environ.get('PSYCHEAI_BASE', 'https://app.psycheai.io')
# This release's number, set by tools/sign-together.mjs and signed with the rest.
RELEASE = 7
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = os.path.join(HERE, 'work')
OUT = os.path.join(HERE, 'out')
STATE = os.path.join(HERE, 'state.json')
KEYS = os.path.join(HERE, '.keys.json')
GUIDE = os.path.join(HERE, 'guide.json')
# PsycheAI's own copies, read and never changed (except the account's token, refreshed as PsycheAI refreshes it).
KEEP = os.environ.get('PSYCHEAI_HOME') or os.path.join(os.path.expanduser('~'), '.psycheai')
PSYCHE_DIR = os.environ.get('PSYCHEAI_SKILL_DIR') or os.path.join(os.path.dirname(HERE), 'psycheai')
ACCOUNTS = [os.path.join(PSYCHE_DIR, '.account.json'), os.path.join(KEEP, 'account.json')]
REPORTS = [os.path.join(PSYCHE_DIR, 'report.json'), os.path.join(KEEP, 'report.json')]
# A spare of this skill's own state and keys outside its folder, so a reinstall keeps the couple.
STATE_KEPT = os.path.join(KEEP, 'together-state.json')
KEYS_KEPT = os.path.join(KEEP, 'together-keys.json')
CLIENT_ID = 'psycheai-skill'
LINK = re.compile(r'/together#([A-Za-z0-9_-]{22})(?![A-Za-z0-9_-])')
FILES = ['SKILL.md', 'bin/together.py', 'guide.json']


# ---------------------------------------------------------------- the check-in

STAGES = ['Dating', 'Living together', 'Engaged', 'Married', 'Separated, co-parenting']
SEPARATED = 'Separated, co-parenting'
SOMETHING_ELSE = 'Something else'
PILLARS = {
    'security': 'Security', 'appreciation': 'Feeling appreciated', 'connection': 'Everyday connection',
    'desire': 'Desire and closeness', 'disagreements': 'Disagreements and repair', 'needs': 'Needs met and fairness',
    'life': 'Life fit', 'future': 'A shared future', 'growth': 'Growing as yourselves',
}
PILLAR_ORDER = ['security', 'appreciation', 'connection', 'desire', 'disagreements', 'needs', 'life', 'future', 'growth']

# The nine core questions, the same for both: asked easy first, security and desire later. Each option's
# score (2 good, 1 middling, 0 low) makes the couple view; the words never leave this workspace.
CORE = [
    ('appreciation', 'How often do you feel appreciated by {p}?', [('Almost always', 2), ('Often', 2), ('Sometimes', 1), ('Rarely', 0)]),
    ('connection', 'When you reach for {p}\'s attention in small ways, how often do they turn towards you?',
     [('Almost always', 2), ('Often', 2), ('Sometimes', 1), ('Rarely', 0)]),
    ('needs', 'How easy is it to get your needs met with {p}?', [('Easy', 2), ('Mostly', 1), ('Difficult', 0)]),
    ('life', 'How comfortable are you with how {p} spends their free time, money and energy?',
     [('Comfortable', 2), ('Mostly', 1), ('Some things bother me', 0)]),
    ('growth', 'Does being with {p} help you grow into who you want to be?', [('Very much', 2), ('Somewhat', 1), ('Not really', 0)]),
    ('disagreements', 'After a disagreement, how do you two usually end up?',
     [('Closer', 2), ('Back to normal soon', 2), ('It lingers', 0), ('It never quite ends', 0)]),
    ('future', 'Do you two want the same things for the next 5 to 10 years?',
     [('Yes, and we\'ve talked', 2), ('Probably, not talked', 1), ('Not sure', 0), ('No', 0)]),
    ('security', 'How sure are you that {p} is in this relationship for the long run?', [('Completely', 2), ('Mostly', 1), ('Not sure', 0)]),
    ('desire', 'How happy are you with physical closeness and desire between you? You can skip this one.',
     [('Very', 2), ('Mostly', 1), ('Something to talk about', 0), ('Skip', None)]),
]
# Worded for working together when they've separated; desire and growth aren't asked then.
CORE_SEPARATED = {
    'security': 'How sure are you that {p} will keep showing up for the children?',
    'future': 'Do you two agree on what the children need over the next few years?',
    'life': 'How comfortable are you with how {p} handles time, money and energy around the children?',
}
SKIP_SEPARATED = {'desire', 'growth'}

SAFETY = ('safety', 'One private question, never shared with anyone: do you ever feel unsafe or afraid with {p}?',
          ['No', 'Sometimes', 'Yes', 'I\'d rather not say'])
SAFETY_FLAGGED = {'Sometimes', 'Yes'}

# The big decisions, stated only, never inferred: shown side by side, since they exist to be compared.
DECISIONS = {
    'hope': ('What do you hope this becomes?', ['Something lasting', 'We\'ll see where it goes', 'Not sure yet']),
    'children': ('Do you want children?', ['Yes', 'No', 'Unsure', 'We have them already']),
    'more_children': ('Do you want more children?', ['Yes', 'No', 'Unsure']),
    'marriage': ('Do you want to get married?', ['Yes', 'No', 'Unsure']),
    'money': ('How should you two handle money?', ['All shared', 'Some shared', 'Kept separate', 'Unsure']),
    'place': ('Where do you see yourselves living in five years?', ['Where we are now', 'Another city or country', 'Unsure']),
    'faith': ('How much should faith shape your life together?', ['A lot', 'A little', 'Not at all', 'Unsure']),
    'parents': ('How involved should your parents be in your life together?', ['Very', 'Somewhat', 'A little', 'Unsure']),
    'kids_routine': ('The children\'s routines between your two homes:', ['We agree', 'We mostly agree', 'We don\'t agree yet']),
    'kids_money': ('Money for the children:', ['We agree', 'We mostly agree', 'We don\'t agree yet']),
    'new_partners': ('New partners and the children:', ['We agree', 'We mostly agree', 'We don\'t agree yet']),
    'handovers': ('Handovers between your homes:', ['We agree', 'We mostly agree', 'We don\'t agree yet']),
}
DECISION_LABELS = {
    'hope': 'What this becomes', 'children': 'Children', 'more_children': 'More children', 'marriage': 'Marriage', 'money': 'Money',
    'place': 'Where to live', 'faith': 'Faith', 'parents': 'Parents', 'kids_routine': 'The children\'s routines',
    'kids_money': 'Money for the children', 'new_partners': 'New partners', 'handovers': 'Handovers',
}
BY_STAGE = {
    'Dating': ['hope', 'children'],
    'Living together': ['children', 'marriage', 'money', 'place', 'faith'],
    'Engaged': ['children', 'money', 'place', 'faith', 'parents'],
    'Married': ['more_children', 'money', 'place', 'parents'],
    SEPARATED: ['kids_routine', 'kids_money', 'new_partners', 'handovers'],
}
UNDECIDED = {'Unsure', 'Not sure yet', 'We\'ll see where it goes', 'We don\'t agree yet'}

SUPPORT = ('You said you sometimes feel unsafe or afraid. That matters more than anything in this read. You don\'t have to raise '
           'anything with your partner because of it. If you\'re ever in danger, contact your local emergency number. A relationship '
           'or family-violence helpline where you live can talk it through in confidence, and a counsellor can help you plan what '
           'feels safe. You can end Psyche Together at any time: your partner sees only that it ended.')


# ---------------------------------------------------------------- small helpers

def _e(x):
    return html.escape(str(x if x is not None else ''), quote=True)


def read_first(paths):
    for path in paths:
        try:
            with open(path, encoding='utf-8') as f:
                return json.load(f)
        except (OSError, ValueError):
            continue
    return None


def write_private(paths, data):
    for path in paths:
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False)
            os.chmod(path, 0o600)
        except OSError:
            pass


def state():
    s = read_first([STATE, STATE_KEPT])
    return s if isinstance(s, dict) else {}


def save_state(s):
    write_private([STATE, STATE_KEPT], s)


def keys():
    k = read_first([KEYS, KEYS_KEPT])
    return k if isinstance(k, dict) else {}


def save_keys(k):
    write_private([KEYS, KEYS_KEPT], k)


def say(text, buttons=None):
    out = {'say': text}
    if buttons:
        out.update(buttons=buttons, asButtons=True)
    return out


SCRUB = [(re.compile(r'https?://\S+|www\.\S+', re.I), '[link]'), (re.compile(r'[\w.+-]+@[\w-]+\.[\w.]+'), '[email]'),
         (re.compile(r'(?<!\w)@[A-Za-z0-9_.]{2,}'), '[handle]'), (re.compile(r'\+?\d[\d ()-]{6,}\d'), '[number]')]


def clean_typed(text, names=()):
    """A typed answer, kept in this workspace only: short, and with names, handles, numbers and links taken out."""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()[:200]
    for rx, sub in SCRUB:
        t = rx.sub(sub, t)
    for n in names:
        if n and len(n) >= 2:
            t = re.sub(r'(?<!\w)' + re.escape(n) + r'(?!\w)', '[name]', t, flags=re.I)
    return t


# ---------------------------------------------------------------- their Psyche

def psyche():
    """Their Psyche as the PsycheAI skill kept it, or None."""
    kept = read_first(REPORTS)
    return kept if isinstance(kept, dict) and isinstance(kept.get('report'), dict) else None


def _first(name):
    return (str(name or '').strip().split(' ') or [''])[0][:30]


def _score(v):
    try:
        n = round(float(v))
    except (TypeError, ValueError):
        return None
    return n if 0 <= n <= 100 else None


def psyche_profile(kept):
    """What of their Psyche the joint read uses: card-level, no evidence lines, nothing anyone else wrote."""
    r = kept.get('report') or {}
    pick = lambda xs, f, n: [y for y in (f(x) for x in (xs if isinstance(xs, list) else [])[:n]) if isinstance(y, str) and y][:n]
    big = r.get('bigFive') if isinstance(r.get('bigFive'), dict) else {}
    rel = r.get('relationship') if isinstance(r.get('relationship'), dict) else {}
    love = rel.get('loveLanguages') if isinstance(rel.get('loveLanguages'), dict) else {}
    att = r.get('attachment') if isinstance(r.get('attachment'), dict) else {}
    card = r.get('card') if isinstance(r.get('card'), dict) else {}
    motives = {}
    for m in ((r.get('motivators') or {}).get('scores') or []) if isinstance(r.get('motivators'), dict) else []:
        if isinstance(m, dict) and isinstance(m.get('value'), str) and _score(m.get('score')) is not None:
            motives[m['value']] = _score(m['score'])
    return {
        'name': _first(kept.get('name')),
        'character': str((r.get('essence') or {}).get('character') or '')[:40] if isinstance(r.get('essence'), dict) else '',
        'mbti': str((r.get('mbti') or {}).get('type') or '')[:4] if isinstance(r.get('mbti'), dict) else '',
        'headline': str(card.get('headline') or '')[:120],
        'bigFive': {k: _score((big.get(k) or {}).get('score')) if isinstance(big.get(k), dict) else None
                    for k in ['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism']},
        'motives': motives,
        'patterns': pick(r.get('patterns'), lambda p: (p or {}).get('name') if isinstance(p, dict) else None, 3),
        'values': pick(r.get('values'), lambda v: (v or {}).get('value') if isinstance(v, dict) else None, 3),
        'attachment': str(att.get('style') or '')[:80],
        'conflict': str(att.get('conflict') or card.get('conflictStyle') or '')[:400],
        'caresBy': pick(love.get('giving'), lambda l: (l or {}).get('language') if isinstance(l, dict) else None, 2),
        'feelsCaredForBy': pick(love.get('receiving'), lambda l: (l or {}).get('language') if isinstance(l, dict) else None, 2),
        'relationshipStrengths': pick(rel.get('strengths'), lambda x: (x or {}).get('title') if isinstance(x, dict) else None, 3),
        'relationshipEdges': pick(rel.get('weaknesses'), lambda x: (x or {}).get('title') if isinstance(x, dict) else None, 3),
    }


def signals(kept):
    """Patterns in their Psyche known to strain a pillar, for picking the deeper questions."""
    r = (kept or {}).get('report') or {}
    p = psyche_profile(kept) if kept else {}
    style = p.get('attachment', '').lower()
    rel = r.get('relationship') if isinstance(r.get('relationship'), dict) else {}
    edges = ' '.join(str((w or {}).get('title', '')) + ' ' + str((w or {}).get('detail', '')) for w in (rel.get('weaknesses') or []) if isinstance(w, dict)).lower()
    conflict = p.get('conflict', '').lower()
    based = ' '.join(str(x) for x in ((r.get('confidence') or {}).get('basedOn') or [])).lower() if isinstance(r.get('confidence'), dict) else ''
    extra = (p.get('bigFive') or {}).get('extraversion')
    out = {
        'anxious': 'anxious' in style,
        'avoidant': 'avoidant' in style,
        'keepsin': bool(re.search(r'\b(hide|hides|hiding|keep|keeps|to yourself|quiet|withdraw|pull back|pulls back|joke)', edges + ' ' + conflict)),
        'alone': extra is not None and extra < 45,
        'achieve': (p.get('motives') or {}).get('achievement', 0) >= 70,
        'nomessages': 'message' not in based and 'conversation' not in based and 'chat' not in based,
    }
    return out


def pillar_reasons(sig, core):
    """Each pillar's need for a deeper question: 3 for their own low answer, 2 for a pattern, 1 for a gap."""
    out = {}
    for pid in PILLAR_ORDER:
        if pid == 'desire':
            continue
        n = 3 if core.get(pid) == 0 else 0
        if (pid == 'security' and (sig.get('anxious') or sig.get('avoidant'))) or (pid == 'disagreements' and sig.get('keepsin')) \
                or (pid in ('connection', 'needs') and sig.get('alone')) or (pid in ('needs', 'future') and sig.get('achieve')):
            n += 2
        if pid == 'disagreements' and sig.get('nomessages'):
            n += 1
        if n:
            out[pid] = n
    return out


# ---------------------------------------------------------------- the flow
#
# README "Psyche Together, release 3": both Psyches are exchanged first, then each person's Muse writes one
# opener and one follow-up per pillar from the two of them, so the questions are about these two people, not
# a questionnaire. The core question under each opener is fixed, with the same options for both, so the couple
# view stays fair. A follow-up shows only where it helps: when the answer above it is low, or where this person's
# Psyche points to strain there, four at most.

FLOW = ['appreciation', 'connection', 'needs', 'life', 'growth', 'disagreements', 'future', 'security']
FOLLOW_MAX = 4


def core_for(stage):
    out = []
    for pid, text, opts in CORE:
        if stage == SEPARATED and pid in SKIP_SEPARATED:
            continue
        out.append((pid, CORE_SEPARATED.get(pid, text) if stage == SEPARATED else text, opts))
    return out


def decisions_for(stage, answers):
    topics = list(BY_STAGE.get(stage) or [])
    future = (answers.get('core:future') or {}).get('label')
    if stage == 'Dating' and future == 'Yes, and we\'ve talked':
        return []
    return topics


def stage_of(s):
    return s.get('stage') or (s.get('answers') or {}).get('stage', {}).get('label')


def items(s):
    """Every question this person is asked once their questions are written, in order. Each is a dict:
    id, kind, pillar, opener, text, options, scores (core), follows (a follow-up's core id)."""
    stage, q, out = stage_of(s), s.get('questions') or {}, []
    core = {pid: (text, opts) for pid, text, opts in core_for(stage)}
    for pid in FLOW:
        if pid not in core:
            continue
        text, opts = core[pid]
        out.append({'id': 'core:' + pid, 'kind': 'core', 'pillar': pid, 'opener': (q.get('openers') or {}).get(pid, ''),
                    'text': text, 'options': [o for o, _ in opts], 'scores': [sc for _, sc in opts]})
        f = (q.get('followUps') or {}).get(pid)
        if isinstance(f, dict) and f.get('q') and f.get('options'):
            out.append({'id': 'deep:' + pid, 'kind': 'deeper', 'pillar': pid, 'opener': '', 'text': f['q'], 'options': list(f['options']), 'follows': 'core:' + pid})
    if 'desire' in core:
        text, opts = core['desire']
        out.append({'id': 'core:desire', 'kind': 'core', 'pillar': 'desire', 'opener': '', 'text': text, 'options': [o for o, _ in opts], 'scores': [sc for _, sc in opts]})
    out.append({'id': 'safety', 'kind': 'safety', 'pillar': '', 'opener': '', 'text': SAFETY[1], 'options': SAFETY[2], 'private': True})
    for t in BY_STAGE.get(stage) or []:
        out.append({'id': 'decide:' + t, 'kind': 'decision', 'pillar': '', 'opener': '', 'text': DECISIONS[t][0], 'options': DECISIONS[t][1],
                    'onlyIf': 'hope' if t in ('hope', 'children') and stage == 'Dating' else None})
    return out


def base_priority(s):
    """How much this person's own Psyche points to each pillar (a pattern 2, a gap 1), for the follow-ups."""
    return pillar_reasons(signals(psyche()), {})


def certain(s):
    """The pillars whose follow-up always shows: where this person's own Psyche points (2 or more), four at most."""
    base = base_priority(s)
    return [p for p in FLOW if base.get(p, 0) >= 2][:FOLLOW_MAX]


def shown(s, its, answers):
    """The ids shown, given the answers: a follow-up always where their Psyche makes it certain, and any other
    under a low answer to its pillar's question; the Dating decisions only when they haven't talked about the future."""
    sure, out = certain(s), []
    scores = {it['id']: dict(zip(it['options'], it['scores'])) for it in its if it['kind'] == 'core'}
    for it in its:
        if it['kind'] == 'deeper' and it['pillar'] not in sure:
            core = answers.get(it['follows'])
            if core is None or scores.get(it['follows'], {}).get(core.get('label')) != 0:
                continue
        if it.get('onlyIf') and (answers.get('core:future') or {}).get('label') == 'Yes, and we\'ve talked':
            continue
        out.append(it['id'])
    return out


def say_for(s, it):
    p = s.get('partner') or 'your partner'
    text = it['text'].replace('{p}', p)
    return (it['opener'] + '\n\n' + text) if it.get('opener') else text


def next_step(s=None):
    """The next question in the chat (when the form can't be used), or what comes before the questions."""
    s = s if s is not None else state()
    if not s.get('role'):
        return {'error': 'There\'s no Psyche Together here yet: start one ("Start Psyche Together") or join with a partner\'s link.'}
    if s.get('role') == 'a' and not stage_of(s):
        return {'id': 'stage', 'say': 'Which stage of a relationship are you two at right now?', 'kind': 'stage', 'buttons': STAGES, 'asButtons': True}
    if not s.get('questions'):
        return {'notReady': True}
    answers = s.get('answers') or {}
    its = items(s)
    ids = shown(s, its, answers)
    todo = [it for it in its if it['id'] in ids and it['id'] not in answers]
    if not todo:
        return {'done': True}
    it = todo[0]
    out = {'id': it['id'], 'say': say_for(s, it), 'kind': it['kind'], 'buttons': list(it['options']), 'asButtons': True,
           'progress': '%d of %d' % (len([i for i in ids if i in answers]) + 1, len(shown(s, its, dict(answers, **{x['id']: {'label': x['options'][0]} for x in its if x['kind'] == 'core' and x['id'] not in answers}))))}
    if it.get('private'):
        out['private'] = True
    return out


def answer(qid, label=None, text=None, nearest=None):
    s = state()
    if not s.get('role'):
        return {'error': 'There\'s no Psyche Together here yet.'}
    if qid == 'stage' and s.get('role') == 'a' and not stage_of(s):
        if label not in STAGES:
            return {'error': '"%s" isn\'t one of the stages: %s.' % (label, ', '.join(STAGES))}
        s['stage'] = label
        save_state(s)
        return after_stage(s)
    it = next((x for x in items(s) if x['id'] == qid), None) if s.get('questions') else None
    if not it:
        return {'error': 'There\'s no question %s right now.' % qid}
    if label not in it['options']:
        return {'error': '"%s" isn\'t one of the buttons: %s.' % (label, ', '.join(it['options']))}
    s.setdefault('answers', {})[qid] = {'label': label}
    save_state(s)
    q = next_step(s)
    return send() if q.get('done') else q


def shared_profile(s, answered=True):
    """What leaves this workspace, locked: their Psyche at card level and the stage (from the start), then the
    core answers as good / middling / low, whether they'd like to talk about closeness, and the big decisions.
    Never the follow-up answers or the safety answer."""
    kept = psyche()
    out = {'v': 3, 'psyche': psyche_profile(kept) if kept else {}, 'stage': stage_of(s) if s.get('role') == 'a' else None}
    if not answered:
        return out
    answers = s.get('answers') or {}
    stage = stage_of(s)
    core = {}
    for pid, _, opts in core_for(stage):
        a = answers.get('core:' + pid)
        if a and pid != 'desire' and dict(opts).get(a.get('label')) is not None:
            core[pid] = dict(opts)[a['label']]
    out.update(core=core, desireTalk=(answers.get('core:desire') or {}).get('label') == 'Something to talk about',
               decisions={k[7:]: v.get('label') for k, v in answers.items() if k.startswith('decide:') and v.get('label')})
    return out


LEVELS = {2: 'Strong', 1: 'Steady', 0: 'Worth attention'}


def couple_view(a, b):
    """The two profiles as one couple: each pillar Strong when both answered well, Worth attention when either
    answered low (never saying whose), Steady otherwise; the big decisions side by side."""
    pillars = {}
    for pid in PILLAR_ORDER:
        x, y = (a.get('core') or {}).get(pid), (b.get('core') or {}).get(pid)
        if x is None or y is None:
            continue
        pillars[pid] = LEVELS[2 if x == 2 and y == 2 else 0 if 0 in (x, y) else 1]
    decisions = []
    da, db = a.get('decisions') or {}, b.get('decisions') or {}
    for t in DECISION_LABELS:
        if t in da or t in db:
            x, y = da.get(t), db.get(t)
            result = ('Not decided yet' if not x or not y or x in UNDECIDED or y in UNDECIDED
                      else 'Aligned' if x == y else 'Talk about')
            decisions.append({'topic': t, 'label': DECISION_LABELS[t], 'a': x, 'b': y, 'result': result})
    return {'stage': a.get('stage') or b.get('stage'), 'stages': [a.get('stage'), b.get('stage')], 'pillars': pillars,
            'desireTalk': bool(a.get('desireTalk') and b.get('desireTalk')), 'decisions': decisions,
            'names': [(a.get('psyche') or {}).get('name') or 'Partner A', (b.get('psyche') or {}).get('name') or 'Partner B']}


# ---------------------------------------------------------------- the check-in widget
# README "Psyche Together, release 6": the questions are ONE HTML widget the script builds (as the PsycheAI
# skill built its report widget), so it looks the same everywhere: PsycheAI's colours on its own white, one
# question at a time with Back, a tap moving on, follow-ups slotting in, and a review at the end. It keeps its
# answers in real radio buttons and one hidden field (no storage: Muse's widgets refuse it), short enough that
# every tap reaches it on a phone. A widget can't send, so "Submit my answers" is a button under it.

W_CSS = '''
:root{color-scheme:light;--ink:#241a2e;--soft:#5a4f66;--line:#ece4f1;--plum:#6e3796;--rose:#c2366d;--wash:#f6effb}
*{box-sizing:border-box}html,body{margin:0;padding:0;background:#fff}
body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Inter,Roboto,Arial,sans-serif;color:var(--ink);-webkit-text-size-adjust:100%}
.pt{background:#fff;border-radius:18px;overflow:hidden;border:1px solid var(--line);max-width:560px;margin:0 auto}
.top{padding:14px 16px 12px;color:#fff;background:linear-gradient(135deg,#5b2a86,#7b3fa0 45%,#c2366d)}
.top small{display:block;font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;opacity:.85}
.top b{display:block;font-size:19px;margin-top:2px}
.prog{height:5px;background:rgba(255,255,255,.3);border-radius:9px;margin-top:10px;overflow:hidden}.prog i{display:block;height:100%;width:0;background:#fff;transition:width .25s}
.count{font-size:12px;opacity:.9;margin-top:5px}
.card{padding:16px 16px 14px}.card[hidden]{display:none}
.chip{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--plum);background:var(--wash);border-radius:999px;padding:4px 10px;margin-bottom:10px}
.lock{color:var(--rose);background:#fcebf2}
.opener{margin:0 0 8px;font-size:15px;line-height:1.5;color:var(--ink)}
.question{margin:0 0 12px;font-size:18px;line-height:1.35;font-weight:750;color:var(--ink)}
.opts{display:flex;flex-direction:column;gap:8px}
.opts label{display:flex;align-items:center;gap:10px;padding:12px 14px;border:1.5px solid var(--line);border-radius:14px;font-size:16px;cursor:pointer;-webkit-tap-highlight-color:transparent;background:#fff}
.opts input{position:absolute;opacity:0;pointer-events:none}
.opts label:before{content:"";flex:none;width:18px;height:18px;border-radius:50%;border:2px solid #cdb6dd;background:#fff}
.opts input:checked+span{font-weight:700}
.opts label.on{border-color:var(--plum);background:var(--wash)}.opts label.on:before{border-color:var(--plum);background:radial-gradient(circle,var(--plum) 45%,#fff 50%)}
.nav{display:flex;justify-content:space-between;align-items:center;margin-top:14px}
.nav button{all:unset;cursor:pointer;font-size:15px;font-weight:700;color:var(--plum);padding:8px 4px}
.nav button[disabled]{opacity:.3;cursor:default}
.nav button[hidden]{display:none}
.done h3{margin:0 0 4px;font-size:19px}.done p{margin:0 0 10px;color:var(--soft);font-size:14.5px}
.done ol{margin:0;padding-left:20px;max-height:240px;overflow:auto;font-size:14px}.done li{margin:4px 0}.done li b{display:block;font-weight:650}
'''

W_JS = r'''
(function(){
var D=JSON.parse(document.getElementById('pt-data').textContent),ans={},at=0,field=document.getElementById('pt-answers');
function score(id){var it=D.items.filter(function(x){return x.id===id})[0];return it&&it.scores&&(id in ans)?it.scores[it.options.indexOf(ans[id])]:null;}
function shown(){return D.items.filter(function(it){
 if(it.follows&&D.certain.indexOf(it.pillar)<0&&!(it.follows in ans&&score(it.follows)===0))return false;
 if(it.onlyIf&&ans['core:future']===D.talked)return false;return true;}).map(function(it){return it.id});}
function card(id){return document.getElementById('c-'+id.replace(':','-'));}
function show(){var ids=shown(),n=ids.filter(function(i){return i in ans}).length;
 [].slice.call(document.querySelectorAll('.card')).forEach(function(c){c.hidden=true});
 document.querySelector('.prog i').style.width=Math.round(100*n/ids.length)+'%';
 document.querySelector('.count').textContent=Math.min(at+1,ids.length)+' of '+ids.length;
 field.value=JSON.stringify(ans);
 if(at>=ids.length){var d=document.getElementById('c-done');d.hidden=false;var ol=d.querySelector('ol');ol.innerHTML='';
  ids.forEach(function(i){var it=D.items.filter(function(x){return x.id===i})[0];var li=document.createElement('li');var b=document.createElement('b');b.textContent=it.short;li.appendChild(b);li.appendChild(document.createTextNode(ans[i]||'—'));ol.appendChild(li);});
  document.querySelector('.count').textContent='All '+ids.length+' answered';return;}
 var c=card(ids[at]);c.hidden=false;c.querySelector('.back').disabled=at===0;c.querySelector('.next').hidden=!(ids[at] in ans);}
document.addEventListener('change',function(e){var t=e.target;if(!t||t.type!=='radio')return;ans[t.name]=t.value;
 [].slice.call(document.querySelectorAll('input[name="'+t.name+'"]')).forEach(function(x){x.parentNode.classList.toggle('on',x.checked)});
 var ids=shown();Object.keys(ans).forEach(function(k){if(ids.indexOf(k)<0)delete ans[k];});
 setTimeout(function(){at=Math.min(shown().indexOf(t.name)+1,shown().length);show();},220);});
document.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('button'):null;if(!b)return;
 if(b.classList.contains('back')){at=Math.max(0,at-1);show();}
 if(b.classList.contains('next')){at=Math.min(at+1,shown().length);show();}
 if(b.classList.contains('edit')){at=0;show();}});
show();})();
'''


def widget_html(s):
    its = items(s)
    p = s.get('partner') or 'your partner'
    data = {'certain': certain(s), 'talked': 'Yes, and we\'ve talked',
            'items': [{'id': it['id'], 'pillar': it['pillar'], 'options': it['options'], 'scores': it.get('scores'), 'follows': it.get('follows'),
                       'onlyIf': it.get('onlyIf'), 'short': it['text'].replace('{p}', p)} for it in its]}
    cards = []
    for it in its:
        chip = ('<span class="chip lock">Private · never shared</span>' if it.get('private') else
                '<span class="chip">%s</span>' % _e('Going deeper' if it['kind'] == 'deeper' else 'The big decisions' if it['kind'] == 'decision' else PILLARS.get(it['pillar'], '')))
        opts = ''.join('<label><input type="radio" name="%s" value="%s"><span>%s</span></label>' % (_e(it['id']), _e(o), _e(o)) for o in it['options'])
        cards.append('<section class="card" id="c-%s" hidden>%s%s<p class="question">%s</p><div class="opts">%s</div>'
                     '<div class="nav"><button type="button" class="back">‹ Back</button><button type="button" class="next" hidden>Next ›</button></div></section>'
                     % (it['id'].replace(':', '-'), chip, ('<p class="opener">%s</p>' % _e(it['opener'])) if it.get('opener') else '',
                        _e(it['text'].replace('{p}', p)), opts))
    return ('<div class="pt"><style>%s</style><div class="top"><small>Psyche Together</small><b>You &amp; %s</b><div class="prog"><i></i></div>'
            '<div class="count"></div></div><form id="pt-form" onsubmit="return false">%s'
            '<section class="card done" id="c-done" hidden><h3>All done ✓</h3><p>Check your answers, then tap <b>Submit my answers</b> below.</p><ol></ol>'
            '<div class="nav"><button type="button" class="edit">‹ Change an answer</button><span></span></div></section>'
            '<input type="hidden" id="pt-answers" name="psyche-together-answers" value="{}"></form>'
            '<script type="application/json" id="pt-data">%s</script><script>%s</script></div>'
            % (W_CSS, _e(p), ''.join(cards), json.dumps(data).replace('</', '<\\/'), W_JS))


def take_answers(raw):
    """Everything entered in the widget at once (id → the option tapped). Saves what's there; anything still
    to answer comes back as `missing`, asked one at a time with buttons; otherwise their answers are sent."""
    s = state()
    if not s.get('questions'):
        return {'error': 'There are no questions here yet.'}
    try:
        got = json.loads(open(raw[1:], encoding='utf-8').read() if str(raw).startswith('@') else raw)
    except (OSError, ValueError) as err:
        return {'error': 'Couldn\'t read the answers: %s' % err}
    if not isinstance(got, dict):
        return {'error': 'The answers are one JSON object: question id → the option tapped.'}
    its, bad = items(s), []
    byid = {it['id']: it for it in its}
    answers = dict(s.get('answers') or {})
    for k, v in got.items():
        it = byid.get(k)
        if not it:
            bad.append('%s isn\'t one of the questions' % k)
        elif v in it['options']:
            answers[k] = {'label': v}
        elif v not in (None, ''):
            bad.append('%s: "%s" isn\'t one of its options' % (k, v))
    ids = shown(s, its, answers)
    s['answers'] = {k: v for k, v in answers.items() if k in ids}
    save_state(s)
    if bad:
        return {'saved': False, 'problems': bad}
    q = next_step(s)
    return send() if q.get('done') else {'missing': True, 'next': q}


# ---------------------------------------------------------------- the answer code
# The form page can't send anything to the chat, so it gives one short code to paste: the form's id, then one
# character per question, its button's number, or "-" when it wasn't shown. Nothing in it but numbers.

def form_id(s):
    return hashlib.sha256(json.dumps(s.get('questions') or {}, sort_keys=True).encode()).hexdigest()[:4]


def read_code(code):
    s = state()
    m = re.search(r'\bPT-([0-9a-f]{4})-([0-9-]+)\b', str(code or ''))
    if not m:
        return {'error': 'That isn\'t an answer code: it looks like PT-1a2b-0120…, from the end of the questions page.'}
    if not s.get('questions') or m.group(1) != form_id(s):
        return {'error': 'That code is from another set of questions: use the latest questions page.'}
    its, digits = items(s), m.group(2)
    if len(digits) != len(its):
        return {'error': 'That code is cut short: copy it again from the end of the questions page.'}
    answers = {}
    for it, ch in zip(its, digits):
        if ch != '-' and int(ch) < len(it['options']):
            answers[it['id']] = {'label': it['options'][int(ch)]}
    ids = shown(s, its, answers)
    answers = {k: v for k, v in answers.items() if k in ids}
    missing = [i for i in ids if i not in answers]
    if missing:
        return {'error': 'Some questions aren\'t answered yet (%d): finish them on the page and copy the code again.' % len(missing)}
    s['answers'] = answers
    save_state(s)
    return send()


# ---------------------------------------------------------------- locking (as the PsycheAI skill's Sync does)

def _b64e(raw):
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


def _b64d(text):
    return base64.urlsafe_b64decode(str(text) + '=' * (-len(str(text)) % 4))


def key_for(purpose, code):
    return hashlib.sha256(('psyche|%s|%s' % (purpose, code)).encode()).digest()


def couple_id(code):
    return key_for('together-id', code).hex()


def _stream(key, nonce, size):
    out = bytearray()
    for i in range((size + 31) // 32):
        out += hmac.new(key, nonce + i.to_bytes(8, 'big'), hashlib.sha256).digest()
    return bytes(out[:size])


def seal(value, key):
    data = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()
    nonce = os.urandom(16)
    enc, mac = hmac.new(key, b'psyche-e2e-enc', hashlib.sha256).digest(), hmac.new(key, b'psyche-e2e-mac', hashlib.sha256).digest()
    ct = bytes(x ^ y for x, y in zip(data, _stream(enc, nonce, len(data))))
    return {'v': 'e2e1', 'n': _b64e(nonce), 'c': _b64e(ct), 't': _b64e(hmac.new(mac, b'e2e1' + nonce + ct, hashlib.sha256).digest())}


def unseal(box, key):
    try:
        if not isinstance(box, dict) or box.get('v') != 'e2e1':
            return None
        nonce, ct, tag = _b64d(box['n']), _b64d(box['c']), _b64d(box['t'])
        mac = hmac.new(key, b'psyche-e2e-mac', hashlib.sha256).digest()
        if len(nonce) != 16 or not hmac.compare_digest(tag, hmac.new(mac, b'e2e1' + nonce + ct, hashlib.sha256).digest()):
            return None
        enc = hmac.new(key, b'psyche-e2e-enc', hashlib.sha256).digest()
        return json.loads(bytes(x ^ y for x, y in zip(ct, _stream(enc, nonce, len(ct)))).decode())
    except (KeyError, ValueError, TypeError, binascii.Error):
        return None


# ---------------------------------------------------------------- talking to PsycheAI

WAITS = (2, 4, 8, 15, 25)


def fetch(method, url, headers, data=None, timeout=60):
    """(status, body) for one request; through curl when there is one, since some workspaces cut Python's reads short."""
    curl = shutil.which('curl') if os.environ.get('PSYCHEAI_TRANSPORT') != 'python' else None
    if not curl:
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                return res.status, res.read()
        except urllib.error.HTTPError as err:
            return err.code, err.read() or b''
    tmp = tempfile.mkdtemp(prefix='together-')
    q = lambda v: '"' + str(v).replace('\\', '\\\\').replace('"', '\\"').replace('\n', ' ') + '"'
    try:
        out = os.path.join(tmp, 'out')
        conf = ['url = ' + q(url), 'request = ' + q(method), 'silent', 'max-time = %d' % timeout, 'output = ' + q(out), 'write-out = "%{http_code}"']
        conf += ['header = ' + q('%s: %s' % (k, v)) for k, v in headers.items()]
        if data is not None:
            body = os.path.join(tmp, 'body')
            with open(body, 'wb') as f:
                f.write(data)
            conf.append('data-binary = ' + q('@' + body))
        done = subprocess.run([curl, '--config', '-'], input=('\n'.join(conf) + '\n').encode(), capture_output=True, timeout=timeout + 30)
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


def agent():
    return 'PsycheTogether-skill/%s' % RELEASE


def request(method, path, body=None, token=None, form=False):
    data = None if body is None else (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
    headers = {'Accept': 'application/json', 'User-Agent': agent()}
    if body is not None:
        headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
    if token:
        headers['Authorization'] = 'Bearer ' + token
    for wait in WAITS + (None,):
        try:
            status, raw = fetch(method, BASE + path, headers, data)
            if status in (502, 503, 504) and wait is not None:
                time.sleep(wait)
                continue
            try:
                return status, json.loads(raw.decode() or '{}')
            except ValueError:
                return status, {'raw': raw}
        except (urllib.error.URLError, ConnectionError):
            if wait is None:
                return 503, {'error': {'message': 'PsycheAI is busy right now.'}}
            time.sleep(wait)
    return 503, {}


def account():
    acc = read_first(ACCOUNTS)
    return acc if isinstance(acc, dict) and acc.get('access_token') else None


def refresh(acc):
    status, body = request('POST', '/oauth/token', {'grant_type': 'refresh_token', 'refresh_token': acc.get('refresh_token', ''), 'client_id': CLIENT_ID}, form=True)
    if status != 200 or not body.get('access_token'):
        return None
    acc.update(access_token=body['access_token'], refresh_token=body.get('refresh_token', acc.get('refresh_token')))
    write_private([p for p in ACCOUNTS if os.path.exists(p)] or ACCOUNTS[-1:], acc)
    return acc


def tool(name, args):
    acc = account()
    if not acc:
        return {'error': 'needsPsyche'}
    msg = {'jsonrpc': '2.0', 'id': 1, 'method': 'tools/call', 'params': {'name': name, 'arguments': args}}
    status, body = request('POST', '/mcp', msg, acc['access_token'])
    if status == 401:
        acc = refresh(acc)
        if not acc:
            return {'error': 'PsycheAI\'s sign-in has lapsed: open PsycheAI once ("PsycheAI status"), then try again.'}
        status, body = request('POST', '/mcp', msg, acc['access_token'])
    if isinstance(body.get('error'), dict):
        return {'error': body['error'].get('message', 'PsycheAI could not run that.')}
    res = body.get('result') or {}
    out = res.get('structuredContent') or {}
    if res.get('isError') and not out.get('error'):
        out = {'error': ' '.join(c.get('text', '') for c in res.get('content') or [] if isinstance(c, dict)) or 'PsycheAI could not run that.'}
    return out


# ---------------------------------------------------------------- the couple

def needs_psyche():
    return {'needsPsyche': True, 'say': 'Psyche Together builds on your Psyche, so make yours first. Say "Install psycheai.io/skill and generate my Psyche", then come back here.'}


CONSENT = ('Psyche Together: each of you answers privately, in your own Muse, and your partner never sees how you answered: the read shows '
           'the two of you together. Your Psyche Card\'s summary (your character, type, patterns, how you show care and handle disagreements) '
           'goes to your partner\'s Muse, locked, so both your questions are about the two of you. PsycheAI can\'t read any of it.')


def start():
    if not psyche() or not account():
        return needs_psyche()
    s = state()
    if s.get('role'):
        return {'error': 'There\'s a Psyche Together here already: "Continue Psyche Together", or "End Psyche Together" first.'}
    code = secrets.token_urlsafe(16)
    got = tool('together_link', {'e2e': {'id': couple_id(code)}})
    if got.get('error'):
        return got
    save_keys({'code': code, 'role': 'a'})
    save_state({'role': 'a', 'v': 3, 'started': int(time.time()), 'answers': {}})
    return dict(next_step(), consent=CONSENT)


def put_profile(s, answered):
    k = keys()
    return tool('together_put', {'e2e': {'profile': seal(shared_profile(s, answered), key_for('together-box', k['code']))}})


def after_stage(s):
    """The stage is in: their card goes, locked, and the invite comes back."""
    got = put_profile(s, False)
    if got.get('error'):
        return got
    return {'invite': invite(), 'say': 'Your Psyche is ready for the two of you. Once your partner joins, you\'ll each get your own questions, written from both your Psyches.',
            'buttons': ['Has my partner joined?'], 'asButtons': True, 'setCheck': True}


def join(link):
    m = LINK.search(str(link or ''))
    if not m:
        return {'error': 'That isn\'t a Psyche Together link: it looks like app.psycheai.io/together#… . Ask your partner to send it again.'}
    if not psyche() or not account():
        return needs_psyche()
    s = state()
    if s.get('role'):
        return {'error': 'There\'s a Psyche Together here already: "End Psyche Together" first to join a new one.'}
    code = m.group(1)
    got = tool('together_join', {'e2e': {'id': couple_id(code)}})
    if got.get('error'):
        return got
    save_keys({'code': code, 'role': 'b'})
    s = {'role': 'b', 'v': 3, 'started': int(time.time()), 'answers': {}}
    save_state(s)
    got = put_profile(s, False)
    if got.get('error'):
        return got
    return dict(questions_task(), joined=True, consent=CONSENT)


def invite():
    k, s = keys(), state()
    if s.get('role') != 'a' or not k.get('code'):
        return {'error': 'Only the one who started it has the invite.'}
    me = psyche_profile(psyche() or {}).get('name') or 'Your partner'
    link = BASE + '/together#' + k['code']
    return {'url': link, 'invite': '%s invited you to Psyche Together, a private check-in for the two of you. Paste this into your Muse app: Install %s and join our Psyche Together.'
            % (me, link.replace('https://', '')), 'say': 'Send this to your partner: they paste it into their Muse.'}


def couple():
    """The couple's boxes, opened here: (keys, server's answer, profiles {a, b}, read)."""
    k = keys()
    if not k.get('code'):
        return k, {'error': 'There\'s no Psyche Together here.'}, {}, None
    got = tool('together_get', {})
    if got.get('error') or got.get('none'):
        return k, got if got.get('error') else {'error': 'This Psyche Together has ended.', 'ended': True}, {}, None
    e = got.get('e2e') or {}
    key = key_for('together-box', k['code'])
    profiles = {r: unseal((e.get('profiles') or {}).get(r), key) for r in ('a', 'b')}
    return k, got, profiles, unseal(e.get('read'), key)


def mine_theirs(s, profiles):
    me, them = ('a', 'b') if s.get('role') == 'a' else ('b', 'a')
    return profiles.get(me) or {}, profiles.get(them) or {}


def questions_task():
    """Data for Muse to write this person's openers and follow-ups (README "Psyche Together, release 3"): both
    Psyches at card level, the stage, and where this person's own Psyche points. Data only: what to do with it is
    in SKILL.md and guide.json."""
    s = state()
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    mine, theirs = mine_theirs(s, profiles)
    if not theirs.get('psyche'):
        return {'waiting': True, 'say': 'Waiting for your partner to join.'}
    s['partner'] = (theirs.get('psyche') or {}).get('name') or 'your partner'
    s['stage'] = stage_of(s) or (profiles.get('a') or {}).get('stage')
    save_state(s)
    stage = s['stage']
    pillars = [p for p in FLOW if p in dict((pid, 1) for pid, _, _ in core_for(stage))]
    focus = {p: n for p, n in base_priority(s).items() if p in pillars}
    return {'write': 'questions', 'you': psyche_profile(psyche() or {}), 'partner': theirs.get('psyche'), 'stage': stage,
            'pillars': pillars, 'focus': focus, 'saveTo': 'work/together-questions.json'}


def check_questions(q, partner, pillars):
    problems = []
    if not isinstance(q, dict):
        return ['The questions are not a JSON object.']
    op = q.get('openers') if isinstance(q.get('openers'), dict) else {}
    fu = q.get('followUps') if isinstance(q.get('followUps'), dict) else {}
    for p in pillars:
        o = op.get(p)
        if not isinstance(o, str) or not 20 <= len(o.strip()) <= 240:
            problems.append('openers.%s: one or two sentences, 20 to 240 characters' % p)
        f = fu.get(p)
        if not (isinstance(f, dict) and isinstance(f.get('q'), str) and 10 <= len(f['q']) <= 180 and isinstance(f.get('options'), list)
                and 3 <= len(f['options']) <= 5 and all(isinstance(x, str) and 1 <= len(x) <= 40 for x in f['options'])
                and len(set(f['options'])) == len(f['options'])):
            problems.append('followUps.%s: q (10 to 180 characters) and 3 to 5 different options, each under 40 characters' % p)
    extra = [p for p in list(op) + list(fu) if p not in pillars]
    if extra:
        problems.append('%s aren\'t pillars for this stage: leave them out' % ', '.join(sorted(set(extra))))
    named = sum(1 for p in pillars if partner and partner.lower() in str(op.get(p, '')).lower())
    if partner and named < (len(pillars) + 1) // 2:
        problems.append('openers: name %s in at least half of them, so each reads as about the two of you' % partner)
    _plain(problems, {'openers': op, 'followUps': fu}, 240)
    return problems[:16]


def save_questions(path):
    try:
        with open(str(path).lstrip('@'), encoding='utf-8') as f:
            q = json.load(f)
    except (OSError, ValueError) as err:
        return {'saved': False, 'problems': ['Couldn\'t read %s: %s' % (path, err)]}
    s = state()
    if not s.get('role') or s.get('questions'):
        return {'saved': False, 'problems': ['There are no questions to write here now.']}
    pillars = [p for p in FLOW if p in dict((pid, 1) for pid, _, _ in core_for(stage_of(s)))]
    problems = check_questions(q, s.get('partner'), pillars)
    if problems:
        return {'saved': False, 'problems': problems}
    s['questions'] = {'openers': {p: q['openers'][p].strip() for p in pillars}, 'followUps': {p: q['followUps'][p] for p in pillars}}
    save_state(s)
    try:
        os.remove(str(path).lstrip('@'))
    except OSError:
        pass
    return {'widget': widget_html(s), 'say': 'Your questions, written from both your Psyches.', 'buttons': ['Submit my answers'], 'asButtons': True}


def form():
    """The questions as one page: tap through, then copy one code back into the chat."""
    s = state()
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, 'Psyche-Together-Questions.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(form_page(s))
    os.chmod(path, 0o600)
    its = items(s)
    return {'file': path, 'questions': len(shown(s, its, {})),
            'say': 'Your questions are ready, written from both your Psyches. Tap through them on this page (about 3 minutes), then copy your answer code and paste it here.'}


def send():
    s = state()
    if not s.get('role'):
        return {'error': 'There\'s no Psyche Together here.'}
    if s.get('v') == 3:
        q = next_step(s)
        if not q.get('done'):
            return {'error': 'The check-in isn\'t finished yet.', 'next': q}
    got = put_profile(s, True)
    if got.get('error'):
        return got
    s['sent'] = int(time.time())
    save_state(s)
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    if all('core' in (profiles.get(r) or {}) for r in ('a', 'b')):
        return dict(write_task(profiles), sent=True)
    return {'sent': True, 'waiting': True, 'setCheck': True, 'buttons': ['Is our read ready?'], 'asButtons': True,
            'say': 'Your answers are locked and sent. When %s has done theirs, your read is written: you\'ll both get the same one.' % (s.get('partner') or 'your partner')}


def write_task(profiles=None):
    """What Muse needs to write the joint read: both Psyches at card level and the couple view, never either
    person's own answers. Data only."""
    if profiles is None:
        k, got, profiles, read = couple()
        if got.get('error'):
            return got
    if not all('core' in (profiles.get(r) or {}) for r in ('a', 'b')):
        return {'waiting': True, 'say': 'Still waiting for your partner\'s answers.'}
    view = couple_view(profiles['a'], profiles['b'])
    return {'write': 'read', 'coupleView': view,
            'people': [profiles['a'].get('psyche') or {}, profiles['b'].get('psyche') or {}],
            'saveTo': 'work/together-read.json'}


BANNED = re.compile(r'\b(score[sd]?|percent\w*|compatib\w*|incompatib\w*|divorc\w*|predict\w*|toxic|contempt\w*|stonewall\w*|narcissis\w*|'
                    r'diagnos\w*|therap\w*|treatment|disorder\w*|abus\w*|red flags?|verdict)\b|%', re.I)
WHO_ANSWERED = re.compile(r'\b(rated|answered|chose|picked|ticked|replied that|said that|told us)\b', re.I)
QUOTED = re.compile(r'["“][^"”]*\s[^"”]*\s[^"”]*\s[^"”]*["”]')


def _texts(x, at=''):
    if isinstance(x, str):
        yield at, x
    elif isinstance(x, dict):
        for k, v in x.items():
            yield from _texts(v, (at + '.' if at else '') + str(k))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _texts(v, '%s[%d]' % (at, i))


def _plain(problems, value, limit=900):
    for at, t in _texts(value):
        if len(t) > limit:
            problems.append('%s is over %d characters' % (at, limit))
        if BANNED.search(t):
            problems.append('%s uses "%s": no scores, percentages, verdicts, predictions or clinical words' % (at, BANNED.search(t).group(0)))
        if WHO_ANSWERED.search(t):
            problems.append('%s says what one of them answered ("%s"): the read shows the two of them together, never one person\'s answers' % (at, WHO_ANSWERED.search(t).group(0)))
        if QUOTED.search(t):
            problems.append('%s quotes something: nothing is ever quoted' % at)


def check_read(r, view):
    problems = []
    if not isinstance(r, dict):
        return ['The read is not a JSON object.']
    strong = {p for p, lv in view['pillars'].items() if lv != 'Worth attention'}
    worth = {p for p, lv in view['pillars'].items() if lv == 'Worth attention'}
    if not isinstance(r.get('summary'), str) or not r['summary'].strip() or len(r['summary'].split()) > 25:
        problems.append('summary: one warm line, under 25 words')
    pl = r.get('pillars') if isinstance(r.get('pillars'), dict) else {}
    missing = [p for p in view['pillars'] if not isinstance(pl.get(p), str) or not pl[p].strip()]
    if missing:
        problems.append('pillars: a line for each of %s' % ', '.join(missing))
    extra = [p for p in pl if p not in view['pillars']]
    if extra:
        problems.append('pillars: %s aren\'t in the couple view; leave them out' % ', '.join(extra))
    st = r.get('strengths') if isinstance(r.get('strengths'), list) else []
    if not 1 <= len(st) <= 3 or not all(isinstance(x, dict) and x.get('pillar') in strong and x.get('title') and x.get('detail') for x in st):
        problems.append('strengths: one to three, each a pillar that is Strong or Steady in the couple view (%s), with title and detail' % ', '.join(sorted(strong)) or 'none')
    pat = r.get('pattern') if isinstance(r.get('pattern'), dict) else {}
    if not all(isinstance(pat.get(k), str) and pat[k].strip() for k in ('title', 'detail', 'breakTheLoop')):
        problems.append('pattern: title, detail and breakTheLoop')
    conv = r.get('conversations') if isinstance(r.get('conversations'), list) else []
    if len(conv) > 5 or not all(isinstance(c, dict) and c.get('pillar') in worth and c.get('title') and c.get('why')
                                and isinstance(c.get('script'), list) and 3 <= len(c['script']) <= 5 for c in conv):
        problems.append('conversations: up to five, each from a pillar Worth attention (%s), with title, why and a script of 3 to 5 steps' % (', '.join(sorted(worth)) or 'none, so leave it empty'))
    if worth and not conv:
        problems.append('conversations: at least one, for a pillar Worth attention')
    wk = r.get('weeks') if isinstance(r.get('weeks'), dict) else {}
    pr = wk.get('practice') if isinstance(wk.get('practice'), dict) else {}
    if not (pr.get('pillar') in view['pillars'] and pr.get('title') and isinstance(pr.get('days'), list) and len(pr['days']) == 7) \
            or not (isinstance(wk.get('steps'), list) and len(wk['steps']) == 3):
        problems.append('weeks: practice (a pillar from the couple view, a title, and seven days) and three steps for weeks 2 to 4')
    dec = r.get('decisions') if isinstance(r.get('decisions'), list) else []
    topics = {d['topic'] for d in view['decisions']}
    if topics and not all(isinstance(d, dict) and d.get('topic') in topics and d.get('line') for d in dec):
        problems.append('decisions: a line for each big decision, by topic (%s)' % ', '.join(sorted(topics)))
    if not isinstance(r.get('caveats'), str) or not r['caveats'].strip():
        problems.append('caveats: what this can\'t see, in a sentence or two')
    _plain(problems, {k: v for k, v in r.items()})
    return problems[:20]


def save_read(path):
    try:
        with open(str(path).lstrip('@'), encoding='utf-8') as f:
            r = json.load(f)
    except (OSError, ValueError) as err:
        return {'saved': False, 'problems': ['Couldn\'t read %s: %s' % (path, err)]}
    r = r.get('answer', r) if isinstance(r, dict) else r
    k, got, profiles, old = couple()
    if got.get('error'):
        return got
    if not profiles.get('a') or not profiles.get('b'):
        return {'saved': False, 'problems': ['Both of you need to have sent your answers first.']}
    view = couple_view(profiles['a'], profiles['b'])
    problems = check_read(r, view)
    if problems:
        return {'saved': False, 'problems': problems}
    box = {'read': r, 'view': view, 'at': int(time.time())}
    put = tool('together_put', {'e2e': {'read': seal(box, key_for('together-box', k['code']))}})
    if put.get('error'):
        return put
    try:
        os.remove(str(path).lstrip('@'))
    except OSError:
        pass
    s = state()
    s['readAt'] = box['at']
    save_state(s)
    return dict(foryou_task(box), saved=True)


def foryou_task(box=None):
    s = state()
    if box is None:
        k, got, profiles, box = couple()
        if got.get('error'):
            return got
        if not box:
            return {'waiting': True, 'say': 'Your read isn\'t written yet.'}
    guide = read_first([GUIDE]) or {}
    answers = s.get('answers') or {}
    mine = {}
    for it in items(s):
        a = answers.get(it['id'])
        if a and it['kind'] in ('core', 'deeper'):
            mine[it['text'].replace('{p}', s.get('partner') or 'your partner')] = a.get('text') or a.get('label')
    flagged = (answers.get('safety') or {}).get('label') in SAFETY_FLAGGED
    return {'write': 'foryou',
            'yourAnswers': mine, 'coupleView': box.get('view'), 'yourPsyche': psyche_profile(psyche() or {}),
            'gentle': flagged,
            'saveTo': 'work/together-foryou.json'}


def check_foryou(f, gentle=False):
    problems = []
    if not isinstance(f, dict):
        return ['For you is not a JSON object.']
    focus = f.get('focus') if isinstance(f.get('focus'), list) else []
    if not 1 <= len(focus) <= 3 or not all(isinstance(x, dict) and x.get('pillar') in PILLARS and x.get('title') and x.get('detail') for x in focus):
        problems.append('focus: one to three, each with a pillar, title and detail')
    if not gentle and not all(isinstance(x, dict) and x.get('howToRaise') for x in focus):
        problems.append('focus: each with howToRaise')
    if gentle and any(isinstance(x, dict) and x.get('howToRaise') for x in focus):
        problems.append('focus: no howToRaise here: this For you is about looking after yourself, not raising things')
    if not isinstance(f.get('practice'), str) or not f['practice'].strip():
        problems.append('practice: one thing to try this week')
    _plain(problems, f)
    return [p for p in problems if 'says what one of them answered' not in p][:12]


def save_foryou(path):
    try:
        with open(str(path).lstrip('@'), encoding='utf-8') as f:
            fy = json.load(f)
    except (OSError, ValueError) as err:
        return {'saved': False, 'problems': ['Couldn\'t read %s: %s' % (path, err)]}
    fy = fy.get('answer', fy) if isinstance(fy, dict) else fy
    s = state()
    gentle = ((s.get('answers') or {}).get('safety') or {}).get('label') in SAFETY_FLAGGED
    problems = check_foryou(fy, gentle)
    if problems:
        return {'saved': False, 'problems': problems}
    s['forYou'] = fy
    save_state(s)
    try:
        os.remove(str(path).lstrip('@'))
    except OSError:
        pass
    return show()


def status():
    if not psyche() or not account():
        return needs_psyche()
    s = state()
    if not s.get('role'):
        return {'none': True, 'say': 'Psyche Together is a private check-in for you and your partner, built on both your Psyches.', 'buttons': ['Start Psyche Together'], 'asButtons': True}
    if s.get('role') == 'a' and not stage_of(s):
        return next_step(s)
    if not s.get('sent'):
        if not s.get('questions'):
            k, got, profiles, box = couple()
            if got.get('error'):
                return got
            mine, theirs = mine_theirs(s, profiles)
            if not theirs.get('psyche'):
                return {'waiting': True, 'say': 'Your partner hasn\'t joined yet.', 'invite': invite(), 'buttons': ['Has my partner joined?'], 'asButtons': True}
            return questions_task()
        return {'widget': widget_html(s), 'say': 'Your questions, written from both your Psyches.', 'buttons': ['Submit my answers'], 'asButtons': True}
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    if not box:
        return write_task(profiles) if all('core' in (profiles.get(r) or {}) for r in ('a', 'b')) else {
            'waiting': True, 'say': '%s hasn\'t finished theirs yet.' % (s.get('partner') or 'Your partner'), 'buttons': ['Is our read ready?'], 'asButtons': True}
    if not s.get('forYou'):
        return foryou_task(box)
    return show(box)


def check():
    """For the "Psyche Together check" reminder: quiet until something is waiting for them, then one line and a
    button; `done` once their read is shown or it has ended, so the reminder can go."""
    s = state()
    if not s.get('role'):
        return {'done': True, 'quiet': True}
    k, got, profiles, box = couple()
    if got.get('ended') or (got.get('error') and not profiles):
        return {'done': True, 'quiet': True}
    mine, theirs = mine_theirs(s, profiles)
    name = (theirs.get('psyche') or {}).get('name') or 'Your partner'
    if not s.get('questions'):
        return {'quiet': True} if not theirs.get('psyche') else {'say': '%s has joined Psyche Together. Your questions are ready.' % name,
                                                                 'buttons': ['Show my questions'], 'asButtons': True}
    if not s.get('sent'):
        return {'quiet': True}
    if box and s.get('forYou'):
        return {'done': True, 'quiet': True}
    if box or all('core' in (profiles.get(r) or {}) for r in ('a', 'b')):
        return {'say': '%s has finished. Your Psyche Together is ready.' % name, 'buttons': ['Show our Psyche Together'], 'asButtons': True}
    return {'quiet': True}


FORM_CSS = '''
:root{color-scheme:light;--ink:#241a2e;--soft:#5a4f66;--line:#ece4f1;--plum:#6e3796;--rose:#c2366d}
*{box-sizing:border-box}html,body{margin:0;background:#fbf8fc;color:var(--ink);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
.wrap{max-width:640px;margin:0 auto;padding:0 16px 120px}
header{margin:0 -16px 14px;padding:24px 20px 18px;color:#fff;background:linear-gradient(135deg,#5b2a86,#7b3fa0 45%,#c2366d)}
header small{font-size:11.5px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;opacity:.85}header h1{margin:6px 0 4px;font-size:25px;line-height:1.2}header p{margin:0;opacity:.9;font-size:14.5px}
.bar{position:sticky;top:0;z-index:5;background:#fbf8fcee;backdrop-filter:blur(6px);padding:10px 0 8px;margin-bottom:6px}
.bar div{height:6px;border-radius:9px;background:var(--line);overflow:hidden}.bar i{display:block;height:100%;width:0;background:linear-gradient(90deg,#7b3fa0,#c2366d);transition:width .3s}
.bar span{display:block;font-size:12.5px;color:var(--soft);margin-top:5px}
.q{background:#fff;border:1px solid var(--line);border-radius:18px;padding:16px 16px 12px;margin:0 0 12px;box-shadow:0 1px 2px rgba(60,20,80,.04)}
.q[hidden]{display:none}.q.done{border-color:#dcc6ea}
.chip{display:inline-block;font-size:11.5px;font-weight:700;letter-spacing:.05em;text-transform:uppercase;color:var(--plum);background:#f2e9f8;border-radius:999px;padding:3px 9px;margin-bottom:8px}
.lock{color:var(--rose);background:#fcebf2}
.opener{margin:0 0 6px;color:var(--soft);font-size:15px}.text{margin:0 0 10px;font-weight:650;font-size:16.5px}
.opts{display:flex;flex-direction:column;gap:7px}
.opts button{all:unset;cursor:pointer;padding:11px 14px;border-radius:12px;border:1.5px solid var(--line);font-size:15.5px;-webkit-tap-highlight-color:transparent}
.opts button:focus-visible{outline:2px solid var(--rose);outline-offset:2px}
.opts button[aria-pressed="true"]{border-color:var(--plum);background:#f6effb;font-weight:650}
.q.follow{margin-top:-6px;border-style:dashed;background:#fdfaff;border-top-left-radius:8px;border-top-right-radius:8px}
.end{background:#fff;border:1.5px solid #dcc6ea;border-radius:18px;padding:18px;text-align:center}
.end code{display:block;margin:12px 0;padding:12px;border-radius:12px;background:#f6effb;font:600 17px/1.3 ui-monospace,Menlo,monospace;letter-spacing:.04em;user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.end button{all:unset;cursor:pointer;display:inline-block;padding:13px 26px;border-radius:999px;color:#fff;font-weight:700;background:linear-gradient(135deg,#7b3fa0,#c2366d)}
.end p{margin:6px 0;color:var(--soft);font-size:14px}.end[hidden]{display:none}
'''

FORM_JS = r'''
(function(){
var D=JSON.parse(document.getElementById('data').textContent),ans={};
function score(id){var it=D.items.filter(function(x){return x.id===id})[0];if(!it||!it.scores||!(id in ans))return null;return it.scores[ans[id]];}
function shown(){var out=[],f=0;D.items.forEach(function(it){
 if(it.follows&&D.certain.indexOf(it.pillar)<0){if(ans[it.follows]===undefined||score(it.follows)!==0)return;}
 if(it.onlyIf){var fu=D.items.filter(function(x){return x.id==='core:future'})[0];if(fu&&ans['core:future']===0)return;}
 out.push(it.id);});return out;}
function render(){var ids=shown(),n=0;D.items.forEach(function(it){var el=document.getElementById('q-'+it.id.replace(':','-'));if(!el)return;
 var on=ids.indexOf(it.id)>=0;el.hidden=!on;if(on&&(it.id in ans))n++;el.classList.toggle('done',it.id in ans);});
 var total=ids.length;document.querySelector('.bar i').style.width=Math.round(100*n/Math.max(1,total))+'%';
 document.querySelector('.bar span').textContent=n+' of '+total+' answered';
 var end=document.querySelector('.end');end.hidden=n<total;
 if(n>=total){var code='PT-'+D.form+'-'+D.items.map(function(it){return ids.indexOf(it.id)>=0&&(it.id in ans)?String(ans[it.id]):'-'}).join('');
  end.querySelector('code').textContent=code;end.querySelector('button').setAttribute('data-code',code);}
 try{localStorage.setItem('pt-'+D.form,JSON.stringify(ans))}catch(e){}}
document.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('[data-q]'):null;
 if(b){var id=b.getAttribute('data-q');ans[id]=Number(b.getAttribute('data-i'));
  [].slice.call(b.parentNode.children).forEach(function(x){x.setAttribute('aria-pressed',x===b?'true':'false')});render();
  var ids=shown(),next=ids.filter(function(x){return !(x in ans)})[0];var el=next&&document.getElementById('q-'+next.replace(':','-'));
  if(el&&el.getBoundingClientRect().top>innerHeight*0.7)el.scrollIntoView({behavior:'smooth',block:'center'});return;}
 var c=e.target.closest?e.target.closest('[data-code]'):null;if(!c)return;var t=c.getAttribute('data-code'),code=document.querySelector('.end code');
 function done(ok){if(!ok){var r=document.createRange();r.selectNodeContents(code);var s=getSelection();s.removeAllRanges();s.addRange(r);}
  c.textContent=ok?'Copied: paste it in your PsycheAI chat':'Selected: copy it';setTimeout(function(){c.textContent='Copy my answer code'},3000);}
 function fallback(){try{var a=document.createElement('textarea');a.value=t;a.setAttribute('readonly','');a.style.position='fixed';a.style.opacity='0';document.body.appendChild(a);a.select();var ok=document.execCommand('copy');document.body.removeChild(a);done(ok)}catch(x){done(false)}}
 if(navigator.clipboard&&navigator.clipboard.writeText){navigator.clipboard.writeText(t).then(function(){done(true)},fallback)}else fallback();});
try{var kept=JSON.parse(localStorage.getItem('pt-'+D.form)||'{}');Object.keys(kept).forEach(function(id){ans[id]=kept[id];
 var el=document.getElementById('q-'+id.replace(':','-'));if(el){var bs=el.querySelectorAll('[data-q="'+id+'"]');[].slice.call(bs).forEach(function(x,i){x.setAttribute('aria-pressed',i===kept[id]?'true':'false')})}})}catch(e){}
render();})();
'''


def form_page(s):
    its = items(s)
    p = s.get('partner') or 'your partner'
    data = {'form': form_id(s), 'certain': certain(s),
            'items': [{'id': it['id'], 'pillar': it['pillar'], 'scores': it.get('scores'), 'follows': it.get('follows'), 'onlyIf': it.get('onlyIf')} for it in its]}
    cards, open_card = [], None

    def opts(it):
        return '<div class="opts">' + ''.join('<button type="button" aria-pressed="false" data-q="%s" data-i="%d">%s</button>' % (_e(it['id']), i, _e(o))
                                             for i, o in enumerate(it['options'])) + '</div>'
    for it in its:
        qid = it['id'].replace(':', '-')
        text = _e(it['text'].replace('{p}', p))
        if it['kind'] == 'deeper':
            cards.append('<div class="q follow" id="q-%s" hidden><p class="text">%s</p>%s</div>' % (qid, text, opts(it)))
            continue
        chip = ('<span class="chip lock">Private · never shared</span>' if it.get('private') else
                '<span class="chip">%s</span>' % _e(PILLARS.get(it['pillar'], 'The big decisions' if it['kind'] == 'decision' else '')) if (it['pillar'] or it['kind'] == 'decision') else '')
        cards.append('<div class="q" id="q-%s">%s%s<p class="text">%s</p>%s</div>' % (
            qid, chip, ('<p class="opener">%s</p>' % _e(it['opener'])) if it.get('opener') else '', text, opts(it)))
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Psyche Together · your questions</title><style>%s</style></head><body><div class="wrap">'
            '<header><small>Psyche Together</small><h1>You &amp; %s</h1><p>Your questions, from both your Psyches. Only you see your answers: the read shows the two of you together.</p></header>'
            '<div class="bar"><div><i></i></div><span></span></div>%s'
            '<div class="end" hidden><b>All done</b><p>Copy this code and paste it into your PsycheAI chat.</p><code></code>'
            '<button type="button" data-code="">Copy my answer code</button><p>The code holds only which button you tapped for each question.</p></div>'
            '</div><script type="application/json" id="data">%s</script><script>%s</script></body></html>'
            % (FORM_CSS, _e(p), ''.join(cards), json.dumps(data).replace('</', '<\\/'), FORM_JS))


# ---------------------------------------------------------------- the page

CSS = '''
:root{color-scheme:light;--ink:#241a2e;--soft:#5a4f66;--line:#ece4f1;--plum:#6e3796;--rose:#c2366d;--sage:#2f7d5b;--amber:#9a5b12}
*{box-sizing:border-box}html,body{margin:0;background:#fbf8fc;color:var(--ink);font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;-webkit-text-size-adjust:100%}
.wrap{max-width:760px;margin:0 auto;padding:0 14px 40px}
.banner{margin:0 -14px 16px;padding:26px 20px 22px;color:#fff;background:linear-gradient(135deg,#5b2a86,#7b3fa0 45%,#c2366d)}
.banner h1{margin:8px 0 4px;font-size:28px;line-height:1.15}.banner p{margin:0;opacity:.92}.banner small{opacity:.8;letter-spacing:.1em;text-transform:uppercase;font-weight:700;font-size:11.5px}
section{background:#fff;border:1px solid var(--line);border-radius:16px;padding:16px 18px;margin:0 0 14px}
h2{margin:0 0 10px;font-size:19px}h3{margin:14px 0 4px;font-size:15.5px}p{margin:0 0 10px}ul,ol{margin:0 0 10px;padding-left:20px}li{margin:3px 0}
.mine{border-color:#e4cff0;background:#fbf6fe}.mine h2:after{content:" · only on your copy";font-size:12px;font-weight:600;color:var(--soft)}
.support{border-color:#f0c9d8;background:#fdf1f5}
.chip{display:inline-block;padding:3px 9px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap}
.Strong,.Aligned{background:#e5f4ec;color:var(--sage)}.Steady,.Not-decided-yet{background:#fcf1e1;color:var(--amber)}.Worth-attention,.Talk-about{background:#f2e9f8;color:var(--plum)}
.row{display:flex;justify-content:space-between;gap:10px;align-items:baseline;border-top:1px solid var(--line);padding:9px 0}.row:first-of-type{border-top:0}
.row b{font-size:15px}.row p{margin:2px 0 0;color:var(--soft);font-size:14px}
.soft{color:var(--soft);font-size:13.5px}footer{color:var(--soft);font-size:12.5px;text-align:center;margin-top:18px}
'''


def page(box, s):
    r, view = box.get('read') or {}, box.get('view') or {}
    names = view.get('names') or ['', '']
    fy = s.get('forYou') if isinstance(s.get('forYou'), dict) else None
    gentle = ((s.get('answers') or {}).get('safety') or {}).get('label') in SAFETY_FLAGGED
    parts = []
    if gentle:
        parts.append('<section class="support mine"><h2>For you first</h2><p>' + _e(SUPPORT) + '</p></section>')
    if fy:
        items = ''.join('<h3>%s</h3><p>%s</p>%s' % (_e(x.get('title')), _e(x.get('detail')),
                        ('<p class="soft"><b>How to raise it:</b> %s</p>' % _e(x.get('howToRaise'))) if x.get('howToRaise') and not gentle else '')
                        for x in fy.get('focus') or [] if isinstance(x, dict))
        parts.append('<section class="mine"><h2>For you</h2>' + items + ('<p><b>This week:</b> %s</p>' % _e(fy.get('practice')))
                     + ('<p class="soft">%s</p>' % _e(fy.get('note')) if fy.get('note') else '') + '</section>')
    parts.append('<section><h2>You two</h2><p><b>%s &amp; %s</b> · %s</p><p>%s</p></section>' % (_e(names[0]), _e(names[1]), _e(view.get('stage')), _e(r.get('summary'))))
    parts.append('<section><h2>Your strengths</h2>' + ''.join('<h3>%s</h3><p>%s</p>' % (_e(x.get('title')), _e(x.get('detail'))) for x in r.get('strengths') or []) + '</section>')
    rows = ''.join('<div class="row"><div><b>%s</b><p>%s</p></div><span class="chip %s">%s</span></div>'
                   % (_e(PILLARS.get(p, p)), _e((r.get('pillars') or {}).get(p)), _e(lv.replace(' ', '-')), _e(lv))
                   for p, lv in sorted((view.get('pillars') or {}).items(), key=lambda kv: PILLAR_ORDER.index(kv[0])))
    parts.append('<section><h2>Your pillars, as a couple</h2><p class="soft">Strong when you both see it that way; worth attention when either of you does. Never how one of you answered.</p>' + rows + '</section>')
    pat = r.get('pattern') or {}
    parts.append('<section><h2>Your pattern together</h2><h3>%s</h3><p>%s</p><p><b>What breaks the loop:</b> %s</p></section>'
                 % (_e(pat.get('title')), _e(pat.get('detail')), _e(pat.get('breakTheLoop'))))
    if view.get('decisions'):
        lines = {d.get('topic'): d.get('line') for d in r.get('decisions') or [] if isinstance(d, dict)}
        rows = ''.join('<div class="row"><div><b>%s</b><p>%s: %s · %s: %s</p><p>%s</p></div><span class="chip %s">%s</span></div>'
                       % (_e(d['label']), _e(names[0]), _e(d.get('a') or '-'), _e(names[1]), _e(d.get('b') or '-'), _e(lines.get(d['topic'], '')),
                          _e(d['result'].replace(' ', '-')), _e(d['result']))
                       for d in view['decisions'])
        parts.append('<section><h2>The big decisions</h2><p class="soft">These you each stated, so they\'re shown side by side: they exist to be compared.</p>' + rows + '</section>')
    if r.get('conversations') and not gentle:
        parts.append('<section><h2>Conversations to have</h2>' + ''.join(
            '<h3>%s</h3><p>%s</p><ol>%s</ol>' % (_e(c.get('title')), _e(c.get('why')), ''.join('<li>%s</li>' % _e(x) for x in c.get('script') or []))
            for c in r['conversations']) + '<p class="soft">About ten minutes each, at a calm time. Worth doing with a counsellor if one keeps getting stuck.</p></section>')
    wk = r.get('weeks') or {}
    pr = wk.get('practice') or {}
    parts.append('<section><h2>Your four weeks</h2><h3>Week 1 · %s</h3><ol>%s</ol>%s<p class="soft">At four weeks, the nine questions again, to see what moved.</p></section>'
                 % (_e(pr.get('title')), ''.join('<li>%s</li>' % _e(x) for x in pr.get('days') or []),
                    ''.join('<h3>Week %d</h3><p>%s</p>' % (i + 2, _e(x)) for i, x in enumerate(wk.get('steps') or []))))
    parts.append('<section><h2>How this was read</h2><p>%s</p><p class="soft">From each of your Psyches, at card level, and the check-in you each did privately. '
                 'Each pillar\'s question asks how you see this relationship, which research on thousands of couples found matters more than personality. '
                 'This is coaching, not counselling: if something here feels heavy, a couples counsellor is worth seeing together.</p></section>' % _e(r.get('caveats')))
    when = datetime.fromtimestamp(box.get('at') or time.time()).strftime('%-d %B %Y')
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Psyche Together · %s &amp; %s</title><style>%s</style></head><body><div class="wrap"><header class="banner"><small>Psyche Together</small>'
            '<h1>%s &amp; %s</h1><p>%s</p></header>%s<footer>Psyche Together by PsycheAI · made in your own Muse workspace</footer></div></body></html>'
            % (_e(names[0]), _e(names[1]), CSS, _e(names[0]), _e(names[1]), _e(when), ''.join(parts)))


def show(box=None):
    s = state()
    if box is None:
        k, got, profiles, box = couple()
        if got.get('error'):
            return got
        if not box:
            return {'waiting': True, 'say': 'Your read isn\'t written yet.'}
    os.makedirs(OUT, exist_ok=True)
    names = (box.get('view') or {}).get('names') or ['', '']
    path = os.path.join(OUT, 'Psyche-Together-%s-%s.html' % tuple(re.sub(r'[^A-Za-z0-9]+', '', n) or 'Partner' for n in names))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page(box, s))
    os.chmod(path, 0o600)
    return {'file': path, 'say': 'Your Psyche Together is ready.', 'summary': (box.get('read') or {}).get('summary'),
            'buttons': ['End Psyche Together', 'Done'], 'asButtons': True}


def end():
    k = keys()
    if k.get('code'):
        tool('together_end', {})
    forget()
    return {'ended': True, 'say': 'Psyche Together has ended, for both of you. Your partner sees only that it ended. Your own copy of the page stays here until you delete it.'}


def forget():
    for path in (STATE, STATE_KEPT, KEYS, KEYS_KEPT):
        try:
            os.remove(path)
        except OSError:
            pass
    shutil.rmtree(WORK, ignore_errors=True)
    return {'ok': True}


# ---------------------------------------------------------------- signed updates (as the PsycheAI skill's)

PUBLIC_KEY = bytes.fromhex(os.environ.get('PSYCHEAI_SKILL_PUBLIC_KEY') or 'ff295f50202afe5313924d4ed60e397996164ad8db9aa8079d937c17d0bcbb8d')
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


def signed_text(version, hashes, release):
    return 'psyche-together\nrelease: %d\nversion: %s\n' % (release, version) + ''.join('%s %s\n' % (n, hashes[n]) for n in sorted(hashes))


def update():
    status, man = request('GET', '/together/files')
    if status != 200 or not isinstance(man, dict):
        return {'updated': False, 'error': 'Couldn\'t reach PsycheAI for an update.'}
    rel, hashes, sig = man.get('release'), man.get('hashes') or {}, man.get('signature') or ''
    try:
        good = isinstance(rel, int) and ed25519_verify(PUBLIC_KEY, signed_text(man.get('version'), hashes, rel).encode(),
                                                       base64.urlsafe_b64decode(sig + '=' * (-len(sig) % 4)))
    except (ValueError, binascii.Error):
        good = False
    if not good:
        return {'updated': False, 'error': 'The update isn\'t signed by PsycheAI, so it wasn\'t installed.'}
    if rel <= RELEASE:
        return {'updated': False, 'current': True, 'release': RELEASE}
    got = {}
    for name in FILES:
        st, raw = fetch('GET', BASE + '/together/' + name, {'User-Agent': agent()})
        if st != 200 or hashlib.sha256(raw).hexdigest() != hashes.get(name):
            return {'updated': False, 'error': 'An update file didn\'t match its signature, so nothing was installed.'}
        got[name] = raw
    for name, raw in got.items():
        path = os.path.join(HERE, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(raw)
    return {'updated': True, 'release': rel}


# ---------------------------------------------------------------- command line

def main(argv):
    if not argv:
        print(__doc__)
        return
    cmd, rest = argv[0], argv[1:]
    opt = lambda name: rest[rest.index(name) + 1] if name in rest and rest.index(name) + 1 < len(rest) else None
    if cmd == 'status':
        out = status()
    elif cmd == 'start':
        out = start()
    elif cmd == 'join':
        out = join(rest[0] if rest else '')
    elif cmd == 'next':
        out = next_step()
    elif cmd == 'answer':
        if not rest:
            out = {'error': 'answer <id> <label>, or answer <id> --text "<their words>" --nearest "<label>"'}
        else:
            label = rest[1] if len(rest) > 1 and not rest[1].startswith('--') else None
            out = answer(rest[0], label, opt('--text'), opt('--nearest'))
    elif cmd == 'link':
        out = invite()
    elif cmd == 'questions':
        out = questions_task()
    elif cmd == 'save-questions':
        out = save_questions(rest[0] if rest else '')
    elif cmd == 'form':
        out = form()
    elif cmd == 'answers':
        out = take_answers(' '.join(rest))
    elif cmd == 'widget':
        s = state()
        out = {'widget': widget_html(s), 'say': 'Your questions, written from both your Psyches.', 'buttons': ['Submit my answers'], 'asButtons': True}
    elif cmd == 'check':
        out = check()
    elif cmd == 'code':
        out = read_code(' '.join(rest))
    elif cmd == 'send':
        out = send()
    elif cmd == 'write':
        out = write_task()
    elif cmd == 'save':
        out = save_read(rest[0] if rest else '')
    elif cmd == 'foryou':
        out = foryou_task()
    elif cmd == 'save-foryou':
        out = save_foryou(rest[0] if rest else '')
    elif cmd == 'show':
        out = show()
    elif cmd == 'end':
        out = end()
    elif cmd == 'forget':
        out = forget()
    elif cmd == 'update':
        out = update()
    else:
        out = {'error': 'Unknown command: %s' % cmd}
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == '__main__':
    main(sys.argv[1:])
