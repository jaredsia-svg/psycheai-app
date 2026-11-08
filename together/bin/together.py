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
RELEASE = 13
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
FOLLOW_MAX = 3


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
    out = {'v': 8, 'psyche': psyche_profile(kept) if kept else {}, 'stage': stage_of(s) if s.get('role') == 'a' else None,
           'report': (kept or {}).get('report'), 'fullName': str((kept or {}).get('name') or '')[:60]}
    if s.get('chat'):
        out['chat'] = s['chat']
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


# ---------------------------------------------------------------- your conversation together
# README "Psyche Together, release 8": each side reads its own copy of the couple's conversation (their Instagram
# thread with the partner, or their WhatsApp chat together), works out the signals here, and keeps a dated sample
# spread over time. The thread holds only the two of them, so sharing it between them reveals nothing either
# can't already see; nothing from anyone else's conversations is read.

IG_CLI = os.environ.get('PSYCHEAI_IG_CLI') or '/opt/hatch/bin/instagram-cli'
IGM_CLI = os.environ.get('PSYCHEAI_IGM_CLI') or '/opt/hatch/bin/instagram-messages-cli'
CHAT_FILE = os.path.join(HERE, 'chat.json')
CHAT_MAX = 2000          # messages read from the thread, newest first
SAMPLE = 180             # messages the read sees, spread over the whole span
GAP = 6 * 3600           # a new conversation after six quiet hours
THANKS = re.compile(r'\b(thanks|thank you|thx|ty|appreciate|grateful|proud of you|you\'re the best)\b', re.I)
SORRY = re.compile(r'\b(sorry|my bad|i was wrong|apologi[sz]e|forgive me|let\'s talk|can we talk|i understand)\b', re.I)
# Language measures from the research (README "Psyche Together, release 9"): function-word categories for
# language style matching (Ireland et al., Psychological Science 2011), "we" against "I" and "you" (Seider et al.
# 2009), and a small list of positive and negative words for the balance of the two.
LSM_CATS = {
    'personal': 'i me my mine myself you your yours yourself he him his she her hers we us our ours they them their',
    'impersonal': 'it its this that these those something anything everything nothing',
    'articles': 'a an the',
    'prepositions': 'in on at to from with about for of by over under into after before',
    'auxiliary': 'am is are was were be been being have has had do does did will would can could should shall may might must',
    'adverbs': 'very really just so too also even only still quite already almost',
    'conjunctions': 'and but or so because if though although while',
    'negations': 'no not never none nobody nothing nope dont cant wont isnt arent didnt doesnt',
    'quantifiers': 'all some any many much more most few lots every each',
}
LSM_SETS = {k: set(v.split()) for k, v in LSM_CATS.items()}
WE = set('we us our ours ourselves'.split())
I_YOU = set('i me my mine myself you your yours yourself'.split())
POS = set('love glad happy great good nice thanks thank appreciate excited fun proud lovely sweet amazing awesome yay haha lol miss cute beautiful care hug'.split())
NEG = set('sorry sad angry upset annoyed hate tired stressed worried hurt bad awful terrible ugh frustrated mad disappointed annoying'.split())
BANDS = [('late', 0, 5), ('morning', 5, 12), ('afternoon', 12, 18), ('evening', 18, 24)]
WARM = re.compile(r'\b(love you|miss you|luv u|love u|<3)\b|❤|🥰|😘|💕', re.I)


def _cli(cli, *args):
    try:
        done = subprocess.run([cli] + [str(a) for a in args], capture_output=True, timeout=120)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    try:
        return json.loads((done.stdout or b'{}').decode('utf-8', 'replace') or '{}')
    except ValueError:
        return None


def _accounts(data):
    found = []

    def walk(v):
        if isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, dict):
            name = v.get('username') or v.get('user_name')
            fbid = next((str(v[k]) for k in ('user_fbid', 'fbid', 'account_id', 'id') if v.get(k) not in (None, '')), None)
            if isinstance(name, str) and name and fbid:
                found.append({'username': name.lstrip('@'), 'id': fbid})
                return
            for k, x in v.items():
                if k != '_meta':
                    walk(x)
    walk(data)
    return found


def _when(v):
    try:
        n = float(v)
        return datetime.fromtimestamp(n / 1000 if n > 1e11 else n)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(str(v).replace('Z', '+00:00')).astimezone().replace(tzinfo=None)
        except ValueError:
            return None


def instagram_threads():
    """The initiator's one-to-one Instagram chats, busiest first: [{label, account, fbid, them}], or []."""
    if not os.path.exists(IGM_CLI):
        return []
    out = []
    for acct in _accounts(_cli(IGM_CLI, 'accounts') or {}):
        got = _cli(IGM_CLI, 'top-recipients', '--account-id', acct['id'], '--count', 12) or {}
        for th in (got.get('entities') or {}).get('thread') or []:
            others = [u for u in th.get('users') or [] if str(u.get('id')) != acct['id']]
            if len(others) != 1 or not th.get('thread_fbid'):
                continue
            u = others[0]
            label = str(u.get('full_name') or u.get('username') or '').strip()[:40]
            if label and label not in [x['label'] for x in out]:
                out.append({'label': label, 'account': acct['id'], 'fbid': th['thread_fbid'],
                            'them': sorted({str(v) for v in (u.get('id'), u.get('interop_messaging_user_fbid')) if v})})
    return out[:8]


def instagram_thread(th):
    """One Instagram thread, read from this account: [(datetime, 'me'|'them', text)], oldest first."""
    out, after, pages, them = [], None, 0, set(th.get('them') or [])
    while len(out) < CHAT_MAX and pages < 40:
        page = _cli(IGM_CLI, 'thread', '--account-id', th['account'], '--thread-fbid', th['fbid'], '--first', 50, *(('--after', after) if after else ()))
        if not page:
            break
        pages += 1
        for m in page.get('messages') or []:
            text = str(((m.get('content') or {}).get('text_body')) or '').strip()
            t = _when(m.get('message_sent_at') or m.get('timestamp'))
            if text and t:
                out.append((t, 'them' if str(m.get('sender_fbid') or '') in them else 'me', text))
        info = page.get('messages_page_info') or {}
        after = info.get('end_cursor') if info.get('has_next_page') else None
        if not after:
            break
    return sorted(out, key=lambda x: x[0])


WA_LINE = re.compile(r'^‎?\[?(\d{1,2})[/.](\d{1,2})[/.](\d{2,4}),?\s+(\d{1,2}):(\d{2})(?::\d{2})?\s*([AaPp][Mm])?\]?\s*(?:-\s*)?([^:]{1,60}):\s(.*)$')


def whatsapp_file(paths, partner_names, my_names):
    """Their WhatsApp chat together, from an export they shared (.txt or .zip): [(datetime, 'me'|'them', text)]."""
    import zipfile
    lines = []
    for p in paths:
        try:
            if zipfile.is_zipfile(p):
                with zipfile.ZipFile(p) as z:
                    for n in z.namelist():
                        if n.endswith('.txt'):
                            lines += z.read(n).decode('utf-8', 'replace').splitlines()
            else:
                with open(p, encoding='utf-8', errors='replace') as f:
                    lines += f.read().splitlines()
        except (OSError, ValueError):
            continue
    rows, senders = [], {}
    for ln in lines:
        m = WA_LINE.match(ln.strip())
        if not m:
            if rows:
                rows[-1][2] += '\n' + ln
            continue
        d, mo, y, h, mi, ap, who, text = m.groups()
        y = int(y) + (2000 if len(y) == 2 else 0)
        h = int(h) % 12 + (12 if ap and ap.lower() == 'pm' else 0) if ap else int(h)
        try:
            t = datetime(y, int(mo), int(d), h, int(mi))
        except ValueError:
            try:
                t = datetime(y, int(d), int(mo), h, int(mi))
            except ValueError:
                continue
        rows.append([t, who.strip(), text])
        senders[who.strip()] = senders.get(who.strip(), 0) + 1
    if len(senders) < 2:
        return None
    low = lambda s: s.lower()
    them = next((s for s in senders if any(n and n.lower() in low(s) for n in partner_names)), None)
    me = next((s for s in senders if s != them and any(n and n.lower() in low(s) for n in my_names)), None)
    if not them and me:
        them = next((s for s in senders if s != me), None)
    if not them:
        return None
    skip = re.compile(r'omitted|<Media omitted>|This message was deleted|Messages and calls are end-to-end', re.I)
    return [(t, 'them' if who == them else 'me', text) for t, who, text in rows if not skip.search(text) and who in (them, me or who)]


def chat_signals(msgs):
    """What the conversation shows, counted here: per side, how much each writes, who starts a conversation,
    how fast each replies, questions, thanks, sorry, warm words; and whether it's rising or falling."""
    if not msgs:
        return None
    side = {'me': {}, 'them': {}}
    for k in side:
        side[k] = {'messages': 0, 'starts': 0, 'questions': 0, 'thanks': 0, 'sorry': 0, 'warm': 0, 'replyMinutes': []}
    last = None
    for t, who, text in msgs:
        s = side[who]
        s['messages'] += 1
        if last is None or (t - last[0]).total_seconds() >= GAP:
            s['starts'] += 1
        elif last[1] != who and (t - last[0]).total_seconds() <= 86400:
            s['replyMinutes'].append((t - last[0]).total_seconds() / 60)
        s['questions'] += '?' in text
        s['thanks'] += bool(THANKS.search(text))
        s['sorry'] += bool(SORRY.search(text))
        s['warm'] += bool(WARM.search(text))
        last = (t, who)
    for s in side.values():
        r = sorted(s.pop('replyMinutes'))
        s['medianReplyMinutes'] = round(r[len(r) // 2], 1) if r else None
    words = {'me': [], 'them': []}
    hours = {'me': [0, 0, 0, 0], 'them': [0, 0, 0, 0]}
    for t, who, text in msgs:
        words[who] += re.findall(r"[a-z']+", text.lower().replace("'", ''))
        hours[who][next(i for i, (_, lo, hi) in enumerate(BANDS) if lo <= t.hour < hi)] += 1
    for who, key in (('me', 'me'), ('them', 'them')):
        w, s_ = words[who], side[key]
        n = max(1, len(w))
        s_['we'] = round(100 * sum(1 for x in w if x in WE) / n, 2)
        s_['iYou'] = round(100 * sum(1 for x in w if x in I_YOU) / n, 2)
        pos, neg = sum(1 for x in w if x in POS), sum(1 for x in w if x in NEG)
        s_['positive'], s_['negative'] = pos, neg
        tot = max(1, sum(hours[who]))
        s_['day'] = {b[0]: round(100 * h / tot) for b, h in zip(BANDS, hours[who])}
    rates = {who: {k: sum(1 for x in words[who] if x in v) / max(1, len(words[who])) for k, v in LSM_SETS.items()} for who in words}
    lsm = [1 - abs(rates['me'][k] - rates['them'][k]) / (rates['me'][k] + rates['them'][k] + 0.0001) for k in LSM_SETS]
    by_month = {}
    for t, _, _ in msgs:
        by_month[t.strftime('%Y-%m')] = by_month.get(t.strftime('%Y-%m'), 0) + 1
    first, end = msgs[0][0], msgs[-1][0]
    months = max(1, (end.year - first.year) * 12 + end.month - first.month + 1)
    mid = first + (end - first) / 2
    a, b = sum(1 for m in msgs if m[0] < mid), sum(1 for m in msgs if m[0] >= mid)
    return {'from': first.strftime('%Y-%m-%d'), 'to': end.strftime('%Y-%m-%d'), 'messages': len(msgs), 'perMonth': round(len(msgs) / months, 1),
            'trend': 'rising' if b > a * 1.25 else 'falling' if a > b * 1.25 else 'steady', 'you': side['me'], 'partner': side['them'],
            'styleMatch': round(sum(lsm) / len(lsm), 2) if words['me'] and words['them'] else None,
            'months': [[k, by_month[k]] for k in sorted(by_month)][-24:]}


def chat_sample(msgs, me_name, them_name):
    """A sample the read sees: spread over the whole span, favouring what matters (questions, thanks, sorry,
    longer messages), each line its date, time, who, and the message with links, emails, handles and numbers out."""
    if not msgs:
        return []
    keep = set()
    step = max(1, len(msgs) // (SAMPLE // 2))
    keep.update(range(0, len(msgs), step))
    ranked = sorted(range(len(msgs)), key=lambda i: -(('?' in msgs[i][2]) + bool(THANKS.search(msgs[i][2])) * 2 + bool(SORRY.search(msgs[i][2])) * 2 + min(len(msgs[i][2]), 300) / 150))
    for i in ranked:
        if len(keep) >= SAMPLE:
            break
        keep.add(i)
    out = []
    for i in sorted(keep)[:SAMPLE]:
        t, who, text = msgs[i]
        out.append('%s %s: %s' % (t.strftime('%Y-%m-%d %H:%M'), me_name if who == 'me' else them_name, clean_typed(text.replace('\n', ' '))[:300] if len(text) < 300 else clean_typed(text.replace('\n', ' '))[:300] + '…'))
    return out


def kept_messages():
    got = read_first([CHAT_FILE]) or {}
    return [(datetime.strptime(m[0], '%Y-%m-%d %H:%M'), m[1], m[2]) for m in got.get('messages') or []], got.get('sources') or [], got.get('partner') or ''


def keep_messages(msgs, sources, partner):
    write_private([CHAT_FILE], {'messages': [(t.strftime('%Y-%m-%d %H:%M'), who, text) for t, who, text in sorted(msgs, key=lambda x: x[0])],
                                'sources': sources, 'partner': partner})


def chat_step(s):
    """The initiator's Instagram chat with their partner, picked from a list, after the stage; then the invite at
    once. WhatsApp is added while they wait (README "Psyche Together, release 13")."""
    if not s.get('chatFinished') and 'instagram' not in s.get('chatDone', []) and 'instagram' not in s.get('chatSkipped', []):
        ths = instagram_threads()
        s['threads'] = ths
        save_state(s)
        if ths:
            return {'pickThread': True, 'say': 'Which of your Instagram chats is with your partner? Only that one chat is read.',
                    'buttons': [t['label'] for t in ths] + ['Not on Instagram'], 'asButtons': True}
    return finish_chat(s)


def pick_thread(label):
    s = state()
    if label == 'Not on Instagram':
        s.setdefault('chatSkipped', []).append('instagram')
        save_state(s)
        return chat_step(s)
    th = next((t for t in s.get('threads') or [] if t['label'] == label), None)
    if not th:
        return {'error': '"%s" isn\'t one of the chats listed.' % label}
    msgs = instagram_thread(th)
    old, sources, partner = kept_messages()
    keep_messages(old + msgs, sources + ['instagram'], partner or label)
    s.setdefault('chatDone', []).append('instagram')
    save_state(s)
    return dict(chat_step(s), read='%d messages from your Instagram chat with %s' % (len(msgs), label))


WHATSAPP_HOW = 'in WhatsApp, open your chat with your partner, tap ⋮ or their name, then More, Export chat, Without media, and share the .zip here'


def add_chat_file(paths):
    """Their WhatsApp chat together, any time before the read is written: added to the conversation, and the
    locked card sent again with it."""
    s = state()
    if s.get('readAt'):
        return {'error': 'Your read is already written, so the WhatsApp chat can\'t be added to it now.'}
    old, sources, partner = kept_messages()
    me = psyche() or {}
    msgs = whatsapp_file(paths, [partner, _first(partner)], [str(me.get('name') or ''), _first(me.get('name'))])
    if not msgs:
        return {'error': 'I couldn\'t find a one-to-one chat in that file: share the export of your chat together (%s).' % WHATSAPP_HOW}
    keep_messages(old + msgs, sources + ['whatsapp'], partner)
    s.setdefault('chatDone', []).append('whatsapp')
    save_state(s)
    count_chat(s)
    got = put_profile(s, bool(s.get('sent')))
    if got.get('error'):
        return got
    return {'say': 'Added: %d messages from your WhatsApp chat, %s to %s. Your read will use it.' % (len(msgs), msgs[0][0].strftime('%b %Y'), msgs[-1][0].strftime('%b %Y')),
            'buttons': ['Has my partner joined?'] if not s.get('questions') else ['Is our read ready?'], 'asButtons': True}


def count_chat(s):
    msgs, sources, partner = kept_messages()
    me_first = _first((psyche() or {}).get('name')) or 'You'
    them_first = _first(partner) or 'Partner'
    s['chat'] = {'source': ' and '.join(sources), 'signals': chat_signals(msgs), 'sample': chat_sample(msgs, me_first, them_first)} if msgs else None
    save_state(s)
    return msgs


def finish_chat(s):
    """The conversation so far, counted and sampled here, goes in their locked card with the stage; then the invite,
    the reminder, and WhatsApp offered while they wait."""
    msgs = count_chat(s)
    s['chatFinished'] = True
    save_state(s)
    got = put_profile(s, False)
    if got.get('error'):
        return got
    return {'invite': invite(), 'setCheck': True,
            'say': 'All set. I\'ll tell you here when your partner joins, with your questions ready.',
            'whatsapp': ('Highly recommended while you wait: your WhatsApp chat together makes the read far more specific to the two of you. '
                         'To add it, %s.' % WHATSAPP_HOW),
            'buttons': ['Add our WhatsApp chat', 'Has my partner joined?'], 'asButtons': True}


def flip_chat(chat):
    """The initiator's conversation, seen from the partner's side: "you" and "partner" swapped."""
    if not chat:
        return None
    sig = dict(chat.get('signals') or {})
    if sig.get('you') is not None:
        sig['you'], sig['partner'] = sig.get('partner'), sig.get('you')
    return {'source': chat.get('source'), 'signals': sig, 'sample': chat.get('sample')}


# What the research says, per pillar and per measure: fixed here, cited, and laid out by the page as written,
# so a study is never paraphrased into something it didn't find (README "Psyche Together, release 9").
RESEARCH = {
    'security': 'How committed you believe your partner is was the single strongest predictor of relationship quality among 11,196 couples (Joel et al., PNAS 2020). Attachment shapes how each partner reads distance and closeness (Mikulincer & Shaver).',
    'appreciation': 'Feeling appreciated was one of the five strongest predictors of relationship quality in the same pooled study (Joel et al., 2020). How a partner responds to good news, with active, warm interest, builds trust and closeness (Gable et al., 2004).',
    'connection': 'In Gottman\'s newlywed study, couples still together six years later had turned towards each other\'s small bids for attention about 86% of the time; couples who later split, about 33%.',
    'desire': 'Sexual satisfaction was one of the five strongest predictors of relationship quality (Joel et al., 2020).',
    'disagreements': 'About two-thirds of couples\' recurring disagreements are never solved, only handled well (Gottman). How a disagreement starts and whether repair attempts land matter more than how often couples disagree; one partner pushing to talk while the other withdraws is a common, breakable cycle (Christensen & Heavey).',
    'needs': 'Couples who see the division of practical and emotional work as fair report more satisfaction, whatever the exact split. How partners cope with stress together, not just each on their own, predicts how well the relationship does (Bodenmann, dyadic coping).',
    'life': 'Similar personalities predict surprisingly little about relationship quality; how partners see the relationship predicts far more (Joel et al., 2020). Doing new and engaging things together keeps satisfaction up over time (Aron et al., self-expansion).',
    'future': 'Couples who decide their big transitions together, rather than sliding into them, report more commitment later on (Stanley & Rhoades, sliding versus deciding).',
    'growth': 'Partners who see each other as the person they want to become, and help them get there, both grow and stay more satisfied (the Michelangelo phenomenon, Drigotas et al., 1999).',
    'styleMatch': 'Couples whose everyday writing styles matched more closely were more likely to still be together three months later (language style matching, Ireland et al., Psychological Science 2011).',
    'we': 'Couples who say "we" more often show more positive behaviour when they disagree (Seider et al., 2009).',
    'perpetual': 'Most recurring disagreements come from lasting differences in personality and needs: the goal is a way of living with them, not a winner (Gottman).',
    'dreams': 'Behind a disagreement that keeps coming back there is often a hope or need that hasn\'t been said; naming it is what loosens it (Gottman, dreams within conflict).',
    'lovemaps': 'Knowing each other\'s inner world, worries, hopes and everyday life, is the foundation the rest of a relationship is built on (Gottman, love maps).',
}


# ---------------------------------------------------------------- the couple

def needs_psyche():
    return {'needsPsyche': True, 'say': 'Psyche Together builds on your Psyche, so make yours first. Say "Install psycheai.io/skill and generate my Psyche", then come back here.'}


CONSENT = ('Psyche Together: each of you answers privately, in your own Muse, and your partner never sees how you answered: the read shows '
           'the two of you together. For a read this deep, your full Psyche report goes to your partner\'s Muse, locked. The one who starts it adds '
           'your conversation together (your Instagram chat, and your WhatsApp chat if they share it): what it shows, and a dated sample of it, go '
           'with it, locked, for your read. Nothing from chats with anyone else is read, and PsycheAI can\'t read any of it.')


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
    """The stage is in: their conversation next (README "Psyche Together, release 12"), then the invite."""
    return chat_step(s)


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
            'yourReport': (psyche() or {}).get('report'), 'partnerReport': theirs.get('report'),
            'yourChat': s.get('chat') if s.get('role') == 'a' else flip_chat(theirs.get('chat')),
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


def send(no_chat=False):
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
    if not s.get('forYou'):
        return dict(foryou_task(), sent=True)
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
    people = []
    for r in ('a', 'b'):
        pr = profiles[r]
        people.append({'name': (pr.get('psyche') or {}).get('name'), 'card': pr.get('psyche') or {}, 'report': pr.get('report'), 'chat': pr.get('chat')})
    return {'write': 'read', 'coupleView': view, 'people': people, 'research': RESEARCH, 'saveTo': 'work/together-read.json'}


BANNED = re.compile(r'\b(score[sd]?|percent\w*|compatib\w*|incompatib\w*|divorc\w*|predict\w*|toxic|contempt\w*|stonewall\w*|narcissis\w*|'
                    r'diagnos\w*|therap\w*|treatment|disorder\w*|abus\w*|red flags?|verdict)\b|%', re.I)
WHO_ANSWERED = re.compile(r'\b(rated|answered|ticked)\b|\bin (the|your|their|his|her) check-?in\b', re.I)
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


DATED = re.compile(r'\b(19|20)\d{2}\b|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b', re.I)


def check_read(r, view, has_chat=False):
    """The read at more than a Psyche Report's depth (README "Psyche Together, release 9"): every section there,
    each long enough to say something specific, with dated evidence, and nothing that says who answered what."""
    problems = []
    if not isinstance(r, dict):
        return ['The read is not a JSON object.']
    strong = {p for p, lv in view['pillars'].items() if lv != 'Worth attention'}
    worth = {p for p, lv in view['pillars'].items() if lv == 'Worth attention'}
    T = lambda x: x.strip() if isinstance(x, str) else ''
    D = lambda x: x if isinstance(x, dict) else {}
    L = lambda x: x if isinstance(x, list) else []
    dated = lambda xs: any(isinstance(e, str) and DATED.search(e) for e in L(xs))
    need = lambda ok, msg: ok or problems.append(msg)
    need(T(r.get('summary')) and len(T(r.get('summary')).split()) <= 30, 'summary: one specific line, under 30 words')
    ov = D(r.get('overview'))
    need(len(T(ov.get('lede'))) >= 800, 'overview.lede: three or four paragraphs, at least 800 characters')
    st = L(ov.get('strengths'))
    need(2 <= len(st) <= 4 and all(isinstance(x, dict) and x.get('pillar') in strong and T(x.get('title')) and len(T(x.get('detail'))) >= 250 and dated(x.get('evidence')) for x in st),
         'overview.strengths: two to four Strong or Steady pillars (%s), each a title, a detail of four or five sentences, and dated evidence' % (', '.join(sorted(strong)) or 'none'))
    pl = D(r.get('pillars'))
    for p in view['pillars']:
        x = D(pl.get(p))
        if len(T(x.get('detail'))) < 600 or not all(T(x.get(k)) for k in ('headline', 'insight', 'tryThis')):
            problems.append('pillars.%s: headline, a detail of three or four paragraphs (at least 600 characters), insight and tryThis' % p)
        elif len(L(x.get('evidence'))) < 2 or not dated(x.get('evidence')):
            problems.append('pillars.%s.evidence: two or three dated moments' % p)
    extra = [p for p in pl if p not in view['pillars']]
    need(not extra, 'pillars: %s aren\'t in the couple view; leave them out' % ', '.join(extra))
    cy = D(r.get('cycle'))
    need(len(T(cy.get('loop'))) >= 500 and all(T(cy.get(k)) for k in ('title', 'a', 'b', 'exit')) and dated(cy.get('evidence')),
         'cycle: title, loop (at least 500 characters), a and b (each side, with the need underneath), exit, and dated evidence')
    if has_chat:
        tk = D(r.get('talk'))
        need(len(T(tk.get('summary'))) >= 400 and T(tk.get('bids')) and 4 <= len(L(tk.get('lines'))) <= 8,
             'talk: their conversation is here, so a summary (at least 400 characters), bids, and four to eight lines')
    care = D(r.get('care'))
    need(len(T(care.get('detail'))) >= 400 and T(care.get('a')) and T(care.get('b')), 'care: detail (at least 400 characters), a and b')
    pe = D(r.get('perpetual'))
    need(2 <= len(L(pe.get('lasting'))) <= 3 and all(isinstance(x, dict) and T(x.get('title')) and T(x.get('detail')) and T(x.get('howToLiveWithIt')) for x in L(pe.get('lasting'))),
         'perpetual.lasting: two or three lasting differences, each title, detail and howToLiveWithIt')
    need(1 <= len(L(pe.get('solvable'))) <= 2 and all(isinstance(x, dict) and T(x.get('title')) and T(x.get('detail')) and T(x.get('firstStep')) for x in L(pe.get('solvable'))),
         'perpetual.solvable: one or two solvable ones, each title, detail and firstStep')
    dr = D(r.get('dreams'))
    need(all(T(dr.get(k)) for k in ('tension', 'a', 'b', 'question')), 'dreams: tension, a, b and question')
    gr = D(r.get('growth'))
    need(len(T(gr.get('detail'))) >= 200 and len(L(gr.get('together'))) == 3, 'growth: detail (at least 200 characters) and three together ideas')
    need(len(L(r.get('lovemap'))) == 6 and all(T(x) for x in L(r.get('lovemap'))), 'lovemap: six questions')
    conv = L(r.get('conversations'))
    need(len(conv) <= 5 and all(isinstance(c, dict) and c.get('pillar') in worth and c.get('title') and c.get('why') and 3 <= len(L(c.get('script'))) <= 5 for c in conv),
         'conversations: up to five, each from a pillar Worth attention (%s), with title, why and a script of 3 to 5 steps' % (', '.join(sorted(worth)) or 'none, so leave it empty'))
    need(not worth or conv, 'conversations: at least one, for a pillar Worth attention')
    wk = D(r.get('weeks'))
    pr = D(wk.get('practice'))
    need(pr.get('pillar') in view['pillars'] and pr.get('title') and len(L(pr.get('days'))) == 7 and len(L(wk.get('steps'))) == 3,
         'weeks: practice (a pillar from the couple view, a title, and seven days) and three steps for weeks 2 to 4')
    topics = {d['topic'] for d in view['decisions']}
    need(not topics or all(isinstance(d, dict) and d.get('topic') in topics and d.get('line') for d in L(r.get('decisions'))),
         'decisions: a line for each big decision, by topic (%s)' % ', '.join(sorted(topics)))
    need(T(r.get('caveats')), 'caveats: what this can\'t see, in a sentence or two')
    total = sum(len(t) for _, t in _texts(r))
    need(total >= 16000, 'the read is %d characters: write it deeper than a Psyche Report, at least 16,000 characters across its sections' % total)
    _plain(problems, r, 2400)
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
    problems = check_read(r, view, bool(profiles['a'].get('chat') or profiles['b'].get('chat')))
    if problems:
        return {'saved': False, 'problems': problems}
    chat_of = next((r_ for r_ in ('a', 'b') if profiles[r_].get('chat')), None)
    box = {'read': r, 'view': view, 'at': int(time.time())}
    if chat_of:
        box['chat'] = {'signals': (profiles[chat_of]['chat'] or {}).get('signals')}
        box['chatOf'] = [view['names'][0], view['names'][1]] if chat_of == 'a' else [view['names'][1], view['names'][0]]
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
    return dict(show(box) if s.get('forYou') else foryou_task(), saved=True)


def foryou_task(box=None):
    """This person's own For you, written right after they submit, from their answers, their full report and their
    partner's Psyche (README "Psyche Together, release 13"). Data only."""
    s = state()
    answers = s.get('answers') or {}
    mine = {}
    for it in items(s):
        a = answers.get(it['id'])
        if a and it['kind'] in ('core', 'deeper'):
            mine[it['text'].replace('{p}', s.get('partner') or 'your partner')] = a.get('text') or a.get('label')
    k, got, profiles, _ = couple()
    _, theirs = mine_theirs(s, profiles) if not got.get('error') else ({}, {})
    flagged = (answers.get('safety') or {}).get('label') in SAFETY_FLAGGED
    return {'write': 'foryou', 'yourAnswers': mine, 'yourPsyche': psyche_profile(psyche() or {}), 'yourReport': (psyche() or {}).get('report'),
            'partner': theirs.get('psyche'), 'gentle': flagged, 'saveTo': 'work/together-foryou.json'}


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
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    if box:
        return show(box)
    if all('core' in (profiles.get(r) or {}) for r in ('a', 'b')):
        return write_task(profiles)
    return {'waiting': True, 'say': 'Your answers are in, and your own advice is ready for when your read arrives. I\'ll tell you here when %s has done theirs.' % (s.get('partner') or 'your partner'),
            'buttons': ['Is our read ready?'], 'asButtons': True}


def status():
    try:
        update()            # a newer signed release, if there is one: the next command runs it
    except Exception:       # never in the way of the person: status answers either way
        pass
    if not psyche() or not account():
        return needs_psyche()
    s = state()
    if not s.get('role'):
        return {'none': True, 'say': 'Psyche Together is a private check-in for you and your partner, built on both your Psyches.', 'buttons': ['Start Psyche Together'], 'asButtons': True}
    if s.get('role') == 'a' and not stage_of(s):
        return next_step(s)
    if s.get('role') == 'a' and not s.get('chatFinished') and not s.get('questions'):
        return chat_step(s)
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
    """For the "Psyche Together check" reminder (README "Psyche Together, release 13"): quiet until something is
    waiting, then the thing itself: the questions to write and show when the partner has joined, the read to
    write when both have answered, the page when it's ready; `done` once it has been shown."""
    s = state()
    if not s.get('role'):
        return {'done': True, 'quiet': True}
    k, got, profiles, box = couple()
    if got.get('ended') or (got.get('error') and not profiles):
        return {'done': True, 'quiet': True}
    mine, theirs = mine_theirs(s, profiles)
    name = (theirs.get('psyche') or {}).get('name') or 'Your partner'
    if not s.get('questions'):
        if not theirs.get('psyche'):
            return {'quiet': True}
        return dict(questions_task(), say='%s has joined Psyche Together. Here are your questions.' % name)
    if not s.get('sent'):
        return {'quiet': True}
    if box:
        if s.get('shown') == box.get('at'):
            return {'done': True, 'quiet': True}
        s['shown'] = box.get('at')
        save_state(s)
        return dict(show(box) if s.get('forYou') else foryou_task(), say='%s has finished. Here\'s your Psyche Together.' % name)
    if all('core' in (profiles.get(r) or {}) for r in ('a', 'b')):
        return write_task(profiles)
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
.soft{color:var(--soft);font-size:13.5px}nav{position:sticky;top:0;z-index:3;display:flex;gap:6px;overflow-x:auto;padding:8px 0 10px;background:#fbf8fc;scrollbar-width:none}nav a{flex:none;font-size:12.5px;font-weight:700;color:var(--plum);background:#f2e9f8;border-radius:999px;padding:6px 11px;text-decoration:none}.lede{font-size:17px;font-weight:650}.sub{margin-top:18px}.item{border-top:1px solid var(--line);padding-top:10px;margin-top:10px}.pillar{border-top:1px solid var(--line);padding:12px 0 4px}.ph{display:flex;justify-content:space-between;align-items:center;gap:8px}.ph b{font-size:13px;letter-spacing:.06em;text-transform:uppercase;color:var(--plum)}.ev{margin:6px 0 10px;padding-left:18px;color:var(--soft);font-size:14px}.try{background:#f6effb;border-radius:12px;padding:9px 12px}.two{display:grid;grid-template-columns:1fr 1fr;gap:12px;margin:10px 0}@media(max-width:520px){.two{grid-template-columns:1fr}}.two>div{background:#faf6fc;border-radius:12px;padding:10px 12px}.sci{font-size:13px;color:var(--soft);border-left:3px solid #cdb6dd;padding:2px 0 2px 10px;margin:10px 0}.insight{font-weight:650}.chips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 12px}.gauge{display:flex;align-items:baseline;gap:8px;margin:8px 0}.gauge b{font-size:34px;color:var(--plum)}.gauge span{color:var(--soft);font-size:14px}.chart{margin:8px 0}.chart svg{width:100%;height:auto}.chart figcaption{font-size:12px;color:var(--soft)}table{width:100%;border-collapse:collapse;font-size:14px;margin:6px 0}td,th{text-align:left;padding:6px 4px;border-top:1px solid var(--line)}th{border-top:0;color:var(--soft);font-size:12.5px}footer{color:var(--soft);font-size:12.5px;text-align:center;margin-top:18px}
'''


def _paras(t):
    return ''.join('<p>%s</p>' % _e(x.strip()) for x in str(t or '').split('\n') if x.strip())


def _ev(xs):
    xs = [x for x in (xs or []) if isinstance(x, str) and x.strip()]
    return ('<ul class="ev">' + ''.join('<li>%s</li>' % _e(x) for x in xs) + '</ul>') if xs else ''


def _research(key):
    return ('<p class="sci"><b>What the research says.</b> %s</p>' % _e(RESEARCH[key])) if key in RESEARCH else ''


def _months_svg(months):
    """Messages by month, as a small bar chart drawn here (no library), newest on the right."""
    if not months:
        return ''
    top, w = max(n for _, n in months) or 1, 300
    bw = w / len(months)
    bars = ''.join('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" fill="#7b3fa0"><title>%s: %d</title></rect>'
                   % (i * bw + 1, 60 - 56 * n / top, max(1.5, bw - 2), 56 * n / top, _e(m), n) for i, (m, n) in enumerate(months))
    return ('<figure class="chart"><svg viewBox="0 0 %d 62" role="img" aria-label="Messages by month">%s</svg><figcaption>Messages by month, %s to %s</figcaption></figure>'
            % (w, bars, _e(months[0][0]), _e(months[-1][0])))


def _talk_panel(box, names):
    sig = (box.get('chat') or {}).get('signals') or {}
    if not (sig.get('you') and sig.get('partner')):
        return ''
    who = box.get('chatOf') or names
    you, them = sig['you'], sig['partner']
    v = lambda d, k, suf='': ('%s%s' % (d.get(k), suf)) if d.get(k) is not None else '–'
    pos = lambda d: '%s : %s' % (d.get('positive', 0), d.get('negative', 0))
    rows = [('Messages', v(you, 'messages'), v(them, 'messages')), ('Conversations started', v(you, 'starts'), v(them, 'starts')),
            ('Typical reply', v(you, 'medianReplyMinutes', ' min'), v(them, 'medianReplyMinutes', ' min')), ('Questions asked', v(you, 'questions'), v(them, 'questions')),
            ('Thanks', v(you, 'thanks'), v(them, 'thanks')), ('Sorry and repair', v(you, 'sorry'), v(them, 'sorry')),
            ('Warm words : hard words', pos(you), pos(them)), ('"We" per 100 words', v(you, 'we'), v(them, 'we')), ('"I" and "you" per 100 words', v(you, 'iYou'), v(them, 'iYou')),
            ] + [('Writing in the ' + lbl, '%s%%' % ((you.get('day') or {}).get(k, 0)), '%s%%' % ((them.get('day') or {}).get(k, 0)))
                 for k, lbl in (('morning', 'morning'), ('afternoon', 'afternoon'), ('evening', 'evening'), ('late', 'late night'))]
    table = '<table><tr><th></th><th>%s</th><th>%s</th></tr>%s</table>' % (_e(who[0]), _e(who[1]), ''.join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % tuple(_e(c) for c in r) for r in rows))
    match = ('<div class="gauge"><b>%d</b><span>out of 100: how closely your writing styles match</span></div>%s' % (round(100 * sig['styleMatch']), _research('styleMatch'))
             if sig.get('styleMatch') is not None else '')
    return (match + table + '<p class="soft">%s messages from %s to %s, about %s a month, %s.</p>' % (_e(sig.get('messages')), _e(sig.get('from')), _e(sig.get('to')), _e(sig.get('perMonth')), _e(sig.get('trend')))
            + _months_svg(sig.get('months') or []) + _research('we'))


def page(box, s):
    """The read as a page in parts, deeper than a Psyche Report (README "Psyche Together, release 9"): For you
    first (this copy only), then who they are together, the nine pillars three ways with what the research says,
    their cycle, how they talk (measured), care, the differences to live with and to solve, the dream under their
    tension, growth, the love map, the decisions, conversations, four weeks and the science."""
    r, view = box.get('read') or {}, box.get('view') or {}
    names = view.get('names') or ['', '']
    fy = s.get('forYou') if isinstance(s.get('forYou'), dict) else None
    gentle = ((s.get('answers') or {}).get('safety') or {}).get('label') in SAFETY_FLAGGED
    D = lambda x: x if isinstance(x, dict) else {}
    parts, nav = [], []

    def part(pid, title, inner, cls=''):
        nav.append('<a href="#%s">%s</a>' % (pid, _e(title)))
        parts.append('<section id="%s" class="%s"><h2>%s</h2>%s</section>' % (pid, cls, _e(title), inner))
    if gentle:
        part('support', 'For you first', '<p>' + _e(SUPPORT) + '</p>', 'support mine')
    if fy:
        items_ = ''.join('<h3>%s</h3>%s%s' % (_e(x.get('title')), _paras(x.get('detail')),
                         ('<p class="soft"><b>How to raise it:</b> %s</p>' % _e(x.get('howToRaise'))) if x.get('howToRaise') and not gentle else '')
                         for x in fy.get('focus') or [] if isinstance(x, dict))
        part('foryou', 'For you', items_ + ('<p><b>This week:</b> %s</p>' % _e(fy.get('practice'))) + ('<p class="soft">%s</p>' % _e(fy.get('note')) if fy.get('note') else ''), 'mine')
    ov = D(r.get('overview'))
    strengths = ''.join('<div class="item"><h3>%s</h3>%s%s</div>' % (_e(x.get('title')), _paras(x.get('detail')), _ev(x.get('evidence')))
                        for x in ov.get('strengths') or [] if isinstance(x, dict))
    levels = ''.join('<span class="chip %s">%s</span>' % (_e(lv.replace(' ', '-')), _e(PILLARS.get(p, p))) for p, lv in sorted((view.get('pillars') or {}).items(), key=lambda kv: PILLAR_ORDER.index(kv[0])))
    part('overview', 'You two', '<p class="lede">%s</p><div class="chips">%s</div>%s<h3 class="sub">Your strengths</h3>%s' % (_e(r.get('summary')), levels, _paras(ov.get('lede')), strengths))
    pl = D(r.get('pillars'))
    rows = ''
    for pid in [p for p in PILLAR_ORDER if p in (view.get('pillars') or {})]:
        lv, x = view['pillars'][pid], D(pl.get(pid))
        rows += ('<div class="pillar" id="p-%s"><div class="ph"><b>%s</b><span class="chip %s">%s</span></div><h3>%s</h3>%s%s%s%s%s</div>'
                 % (pid, _e(PILLARS.get(pid, pid)), _e(lv.replace(' ', '-')), _e(lv), _e(x.get('headline')), _paras(x.get('detail')),
                    ('<p class="insight">%s</p>' % _e(x.get('insight'))) if x.get('insight') else '', _ev(x.get('evidence')),
                    ('<p class="try"><b>Try this:</b> %s</p>' % _e(x.get('tryThis'))) if x.get('tryThis') else '', _research(pid)))
    part('pillars', 'Your nine pillars', '<p class="soft">Each pillar three ways: how you both see it (Strong when you both do, worth attention when either of you doesn\'t, never saying whose), what your conversation shows, and why, through your two Psyches.</p>' + rows)
    cy = D(r.get('cycle'))
    part('cycle', 'Your cycle', '<h3>%s</h3>%s<div class="two"><div><b>%s</b>%s</div><div><b>%s</b>%s</div></div><p class="try"><b>The way out:</b> %s</p>%s%s'
         % (_e(cy.get('title')), _paras(cy.get('loop')), _e(names[0]), _paras(cy.get('a')), _e(names[1]), _paras(cy.get('b')), _e(cy.get('exit')), _ev(cy.get('evidence')), _research('disagreements')))
    tk = r.get('talk') if isinstance(r.get('talk'), dict) else None
    if tk:
        part('talk', 'How you two talk', _paras(tk.get('summary')) + ('<p class="insight"><b>Reaching for each other.</b> %s</p>' % _e(tk.get('bids')) if tk.get('bids') else '')
             + _research('connection') + _talk_panel(box, names) + _ev(tk.get('lines')))
    care = D(r.get('care'))
    part('care', 'How you each care', '%s<div class="two"><div><b>What makes %s feel cared for</b>%s</div><div><b>What makes %s feel cared for</b>%s</div></div>%s'
         % (_paras(care.get('detail')), _e(names[0]), _paras(care.get('a')), _e(names[1]), _paras(care.get('b')), _research('appreciation')))
    pe = D(r.get('perpetual'))
    part('lasting', 'Differences to live with, and ones to solve', '<h3 class="sub">To live with</h3>' + ''.join(
        '<div class="item"><h3>%s</h3>%s<p class="try"><b>Living with it:</b> %s</p></div>' % (_e(x.get('title')), _paras(x.get('detail')), _e(x.get('howToLiveWithIt'))) for x in pe.get('lasting') or [] if isinstance(x, dict))
        + '<h3 class="sub">To solve</h3>' + ''.join('<div class="item"><h3>%s</h3>%s<p class="try"><b>First step:</b> %s</p></div>' % (_e(x.get('title')), _paras(x.get('detail')), _e(x.get('firstStep')))
                                                    for x in pe.get('solvable') or [] if isinstance(x, dict)) + _research('perpetual'))
    dr = D(r.get('dreams'))
    part('dreams', 'The dream under your tension', '<p>%s</p><div class="two"><div><b>%s</b>%s</div><div><b>%s</b>%s</div></div><p class="insight"><b>The question that opens it:</b> %s</p>%s'
         % (_e(dr.get('tension')), _e(names[0]), _paras(dr.get('a')), _e(names[1]), _paras(dr.get('b')), _e(dr.get('question')), _research('dreams')))
    gr = D(r.get('growth'))
    part('growth', 'Growing through each other', _paras(gr.get('detail')) + '<h3 class="sub">New things to try together</h3><ul>%s</ul>' % ''.join('<li>%s</li>' % _e(x) for x in gr.get('together') or []) + _research('growth'))
    if r.get('lovemap'):
        part('lovemap', 'Your love map', '<p class="soft">Ask each other these, one at a time, over a meal or a walk. Not knowing an answer isn\'t a failing; finding out is the point.</p><ol>%s</ol>%s'
             % (''.join('<li>%s</li>' % _e(x) for x in r['lovemap']), _research('lovemaps')))
    if view.get('decisions'):
        lines = {d.get('topic'): d.get('line') for d in r.get('decisions') or [] if isinstance(d, dict)}
        rows = ''.join('<div class="row"><div><b>%s</b><p>%s: %s · %s: %s</p><p>%s</p></div><span class="chip %s">%s</span></div>'
                       % (_e(d['label']), _e(names[0]), _e(d.get('a') or '-'), _e(names[1]), _e(d.get('b') or '-'), _e(lines.get(d['topic'], '')),
                          _e(d['result'].replace(' ', '-')), _e(d['result'])) for d in view['decisions'])
        part('decisions', 'The big decisions', '<p class="soft">These you each stated, so they\'re shown side by side: they exist to be compared.</p>' + rows + _research('future'))
    if r.get('conversations') and not gentle:
        part('talks', 'Conversations to have', ''.join('<div class="item"><h3>%s</h3><p>%s</p><ol>%s</ol></div>' % (_e(c.get('title')), _e(c.get('why')), ''.join('<li>%s</li>' % _e(x) for x in c.get('script') or []))
             for c in r['conversations']) + '<p class="soft">About ten minutes each, at a calm time. Worth doing with a counsellor if one keeps getting stuck.</p>')
    wk = r.get('weeks') or {}
    pr = wk.get('practice') or {}
    part('weeks', 'Your four weeks', '<h3>Week 1 · %s</h3><ol>%s</ol>%s<p class="soft">At four weeks, the questions again, to see what moved.</p>'
         % (_e(pr.get('title')), ''.join('<li>%s</li>' % _e(x) for x in pr.get('days') or []), ''.join('<h3>Week %d</h3><p>%s</p>' % (i + 2, _e(x)) for i, x in enumerate(wk.get('steps') or []))))
    part('how', 'How this was read', '%s<p class="soft">From both your full Psyche reports, shared with your consent for this read; your conversation together, measured on your own devices; and the check-in you each did privately, the same core questions for both. '
         'The measures follow published research: how partners see the relationship (Joel et al., PNAS 2020), turning towards and repair (Gottman), responsiveness to good news (Gable et al., 2004), '
         'language style matching (Ireland et al., 2011), "we" language (Seider et al., 2009), demand and withdraw (Christensen & Heavey), dyadic coping (Bodenmann), self-expansion (Aron) and the Michelangelo phenomenon (Drigotas et al., 1999). '
         'They describe couples in general, never a verdict on you two. This is coaching, not counselling: if something here feels heavy, a couples counsellor is worth seeing together.</p>' % _paras(r.get('caveats')))
    when = datetime.fromtimestamp(box.get('at') or time.time()).strftime('%-d %B %Y')
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>Psyche Together · %s &amp; %s</title><style>%s</style></head><body><div class="wrap"><header class="banner"><small>Psyche Together</small>'
            '<h1>%s &amp; %s</h1><p>%s</p></header><nav>%s</nav>%s<footer>Psyche Together by PsycheAI · made in your own Muse workspace</footer></div></body></html>'
            % (_e(names[0]), _e(names[1]), CSS, _e(names[0]), _e(names[1]), _e(when), ''.join(nav), ''.join(parts)))


def show(box=None):
    s = state()
    if box is None:
        k, got, profiles, box = couple()
        if got.get('error'):
            return got
        if not box:
            return {'waiting': True, 'say': 'Your read isn\'t written yet.'}
    if s.get('shown') != box.get('at'):
        s['shown'] = box.get('at')
        save_state(s)
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
        out = send('--no-chat' in rest)
    elif cmd == 'chat-file':
        out = add_chat_file(rest)
    elif cmd == 'pick-thread':
        out = pick_thread(' '.join(rest))
    elif cmd == 'skip-chat':
        s = state()
        s.setdefault('chatSkipped', []).append('whatsapp')
        save_state(s)
        out = chat_step(s)
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
