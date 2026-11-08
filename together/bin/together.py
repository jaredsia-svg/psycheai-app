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
  python3 bin/together.py again               four weeks on: the same questions again, to see what moved
  python3 bin/together.py later               not now: asks again in a few days
  python3 bin/together.py rewrite             write the read again, from what is already here
  python3 bin/together.py save-recheck @f     save what moved, as Muse wrote it
  python3 bin/together.py end                 end it, for both
  python3 bin/together.py forget              delete everything of it in this workspace
  python3 bin/together.py update              install the latest signed release
"""
import base64
import binascii
import glob
import io
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
RELEASE = 44
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
    ('future', 'Do you two want the same things, and picture the same life, 5, 10 and 15 years from now?',
     [('Yes, and we\'ve talked', 2), ('Probably, not talked', 1), ('Not sure', 0), ('No', 0)]),
    ('security', 'How sure are you that {p} is in this relationship for the long run?', [('Completely', 2), ('Mostly', 1), ('Not sure', 0)]),
    ('desire', 'Do you feel a real, particular physical attraction to {p}, and are you happy with the closeness between you? You can skip this one.',
     [('Yes, strongly', 2), ('Mostly', 1), ('Something to talk about', 0), ('Skip', None)]),
]
# Worded for working together when they've separated; desire and growth aren't asked then.
CORE_SEPARATED = {
    'security': 'How sure are you that {p} will keep showing up for the children?',
    'future': 'Do you two agree on what the children need over the next few years?',
    'life': 'How comfortable are you with how {p} handles time, money and energy around the children?',
}
SKIP_SEPARATED = {'desire', 'growth'}

# README "Psyche Together, release 17": two overall questions, the same for both. How satisfied someone believes
# their partner is was among the strongest predictors of relationship quality across 11,196 couples (Joel et al.,
# 2020), so the read compares each one's sense of the other with how the other feels, as a couple, never whose.
OVERALL = [('overall:you', 'Overall, how satisfied are you with your relationship with {p}?'),
           ('overall:them', 'And how satisfied do you think {p} is with it?')]
OVERALL_SEPARATED = {'overall:you': 'Overall, how satisfied are you with how you and {p} work together for the children?'}
OVERALL_OPTS = [('Very satisfied', 3), ('Satisfied', 2), ('Somewhat', 1), ('Not very', 0)]
READING = ('Happier than you each think', 'About right', 'Worth asking each other')

# README "Psyche Together, release 17": four weeks after the read, the same questions again (no openers, no
# follow-ups, no decisions), and what moved shown at the top of the page. Every four weeks after that.
RECHECK_DAYS = float(os.environ.get('PSYCHE_TOGETHER_RECHECK_DAYS') or 28)
NUDGE_DAYS = 3

SAFETY = ('safety', 'One private question, never shared with anyone: do you ever feel unsafe or afraid with {p}?',
          ['No', 'Sometimes', 'Yes', 'I\'d rather not say'])
SAFETY_FLAGGED = {'Sometimes', 'Yes'}
# README "Psyche Together, release 22": a deeper question, written for this person, can be answered in their own
# words. It stays in this workspace, as every deeper answer does, and only shapes their own For you.
OTHER = 'Something else'

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
        'letters': [{'letter': str(x.get('choice') or '')[:1].upper(), 'strength': str(x.get('strength') or '')[:12].lower()}
                    for x in ((r.get('mbti') or {}).get('letters') or [] if isinstance(r.get('mbti'), dict) else []) if isinstance(x, dict) and x.get('choice')][:4],
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
FOLLOW_MAX = 2      # follow-ups shown, in all (README "Psyche Together, release 41")


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


# README "Psyche Together, release 41": the questions follow the read's own order, chapter by chapter, so each one
# is asked where its answer lands: overall first (the glance), then 01 to 05, the private question last.
QUESTION_CHAPTERS = [('close', ['appreciation', 'know', 'connection', 'desire']), ('life', ['needs', 'life']),
                     ('future', ['future', 'decisions', 'growth']), ('secure', ['security']), ('disagree', ['disagreements'])]


def chapter_of(it):
    key = 'know' if it['kind'] == 'know' else 'decisions' if it['kind'] == 'decision' else it.get('pillar')
    return next((cid for cid, keys in QUESTION_CHAPTERS if key in keys), None)


def items(s):
    """Every question this person is asked once their questions are written, in order. Each is a dict:
    id, kind, pillar, opener, text, options, scores (core), follows (a follow-up's core id)."""
    stage, q, out = stage_of(s), s.get('questions') or {}, []
    core = {pid: (text, opts) for pid, text, opts in core_for(stage)}
    out += overall_items(stage)
    for cid, keys in QUESTION_CHAPTERS:
        for key in keys:
            if key == 'know':                   # how well you know your partner (README "Psyche Together, release 40")
                out += [{'id': k_['id'], 'kind': 'know', 'pillar': '', 'opener': '', 'text': k_['q'], 'options': list(k_['options'])} for k_ in q.get('know') or []]
            elif key == 'decisions':
                out += [{'id': 'decide:' + t, 'kind': 'decision', 'pillar': '', 'opener': '', 'text': DECISIONS[t][0], 'options': DECISIONS[t][1],
                         'onlyIf': 'hope' if t in ('hope', 'children') and stage == 'Dating' else None} for t in BY_STAGE.get(stage) or []]
            elif key in core:
                text, opts = core[key]
                out.append({'id': 'core:' + key, 'kind': 'core', 'pillar': key, 'opener': (q.get('openers') or {}).get(key, '') if key != 'desire' else '',
                            'text': text, 'options': [o for o, _ in opts], 'scores': [sc for _, sc in opts]})
                f = (q.get('followUps') or {}).get(key)
                if key != 'desire' and isinstance(f, dict) and f.get('q') and f.get('options'):
                    out.append({'id': 'deep:' + key, 'kind': 'deeper', 'pillar': key, 'opener': '', 'text': f['q'], 'follows': 'core:' + key,
                                'options': [o for o in f['options'] if o != OTHER] + [OTHER], 'own': True})
    out.append({'id': 'safety', 'kind': 'safety', 'pillar': '', 'opener': '', 'text': SAFETY[1], 'options': SAFETY[2], 'private': True})
    return out


def overall_items(stage):
    return [{'id': qid, 'kind': 'overall', 'pillar': '', 'opener': '', 'text': (OVERALL_SEPARATED.get(qid, text) if stage == SEPARATED else text),
             'options': [o for o, _ in OVERALL_OPTS], 'scores': [sc for _, sc in OVERALL_OPTS]} for qid, text in OVERALL]


def round_items(s):
    """The questions again, four weeks on: each pillar's own question, the two overall ones and the private one."""
    stage, out = stage_of(s), []
    core = {pid: (text, opts) for pid, text, opts in core_for(stage)}
    out += overall_items(stage)
    for cid, keys in QUESTION_CHAPTERS:
        for pid in keys:
            if pid in core:
                text, opts = core[pid]
                out.append({'id': 'core:' + pid, 'kind': 'core', 'pillar': pid, 'opener': '', 'text': text, 'options': [o for o, _ in opts], 'scores': [sc for _, sc in opts]})
    out.append({'id': 'safety', 'kind': 'safety', 'pillar': '', 'opener': '', 'text': SAFETY[1], 'options': SAFETY[2], 'private': True})
    return out


def live_round(s):
    r = s.get('round')
    return r if isinstance(r, dict) and not r.get('sent') else None


def its_for(s):
    return round_items(s) if live_round(s) else items(s)


def ans_for(s):
    r = live_round(s)
    return r.setdefault('answers', {}) if r else s.setdefault('answers', {})


def is_gentle(s):
    return ((s.get('answers') or {}).get('safety') or {}).get('label') in SAFETY_FLAGGED or bool(s.get('gentleLater'))


def levels_of(stage, answers):
    """The pillar answers as good / middling / low, and the overall two as 3 to 0: what is shared."""
    core = {}
    for pid, _, opts in core_for(stage):
        a = answers.get('core:' + pid)
        if a and pid != 'desire' and dict(opts).get(a.get('label')) is not None:
            core[pid] = dict(opts)[a['label']]
    ov = {k[8:]: dict(OVERALL_OPTS)[a['label']] for k, a in answers.items() if k.startswith('overall:') and a.get('label') in dict(OVERALL_OPTS)}
    return core, ov


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
    sure, out, deep = certain(s), [], 0
    scores = {it['id']: dict(zip(it['options'], it['scores'])) for it in its if it['kind'] == 'core'}
    for it in its:
        if it['kind'] == 'deeper':
            if it['pillar'] not in sure:
                core = answers.get(it['follows'])
                if core is None or scores.get(it['follows'], {}).get(core.get('label')) != 0:
                    continue
            if deep >= FOLLOW_MAX:
                continue
            deep += 1
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
    answers = ans_for(s)
    its = its_for(s)
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
    it = next((x for x in its_for(s) if x['id'] == qid), None) if s.get('questions') else None
    if not it:
        return {'error': 'There\'s no question %s right now.' % qid}
    if label not in it['options']:
        return {'error': '"%s" isn\'t one of the buttons: %s.' % (label, ', '.join(it['options']))}
    if label == OTHER and it.get('own'):
        words = clean_typed(text, [s.get('partner') or ''])
        if not words:
            return {'id': qid, 'needsText': True, 'say': 'In a few words, what is it for you?'}
        ans_for(s)[qid] = {'label': OTHER, 'text': words}
    else:
        ans_for(s)[qid] = {'label': label}
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
        out['chat'] = {k: v for k, v in s['chat'].items() if k != 'sample'}     # the sample goes in its own box
    know_ = (s.get('questions') or {}).get('know') or []
    if not answered:
        return out
    answers = s.get('answers') or {}
    if know_:       # the guesses go only when this person isn't on the gentle path, and are scored as a couple
        out['know'] = {'items': [{'id': k_['id'], 'q': k_['q'], 'options': k_['options'], 'answer': k_.get('answer')} for k_ in know_]}
        if not is_gentle(s):
            out['know']['guesses'] = {k_['id']: (answers.get(k_['id']) or {}).get('label') for k_ in know_ if answers.get(k_['id'])}
    core, ov = levels_of(stage_of(s), answers)
    out.update(core=core, overall=ov, rounds=s.get('rounds') or [], desireTalk=(answers.get('core:desire') or {}).get('label') == 'Something to talk about',
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
    out = {'stage': a.get('stage') or b.get('stage'), 'stages': [a.get('stage'), b.get('stage')], 'pillars': pillars,
            'desireTalk': bool(a.get('desireTalk') and b.get('desireTalk')), 'decisions': decisions,
            'names': [(a.get('psyche') or {}).get('name') or 'Partner A', (b.get('psyche') or {}).get('name') or 'Partner B']}
    ov = overall_view(a.get('overall'), b.get('overall'))
    if ov:
        out['overall'] = ov
    kv = know_view(a, b, out['names'])
    if kv:
        out['know'], out['knowBy'] = kv
    return out


def know_view(a, b, names):
    """How well you know each other (README "Psyche Together, releases 40 and 41"): each one's two guesses about the
    other, checked against what the partner's own report says. The couple total and the right answers are
    shared; each one's own count (knowBy) is shown only on their own copy, and never given to the writer."""
    items, by = [], {}
    for r, me, them, them_name in (('a', a, b, names[1]), ('b', b, a, names[0])):
        kn = me.get('know') or {}
        right = of = 0
        for it in kn.get('items') or []:
            key = it.get('answer')
            if not key or key not in (it.get('options') or []):
                continue
            items.append({'about': them_name, 'q': it.get('q'), 'answer': key})
            g = (kn.get('guesses') or {}).get(it.get('id'))
            if g is None:
                continue
            of += 1
            right += int(g == key)
        if of:
            by[r] = [right, of]
    if not items:
        return None
    return {'right': sum(x[0] for x in by.values()), 'of': sum(x[1] for x in by.values()), 'items': items}, by


def overall_view(x, y):
    """How satisfied they both are (as a pillar level) and how well each reads the other's, for the couple only:
    happier than they each think when both are more satisfied than the other guessed, about right when both
    guesses are within a step, otherwise worth asking each other. Never whose."""
    x, y = x if isinstance(x, dict) else {}, y if isinstance(y, dict) else {}
    if not all(isinstance(v.get(k), int) for v in (x, y) for k in ('you', 'them')):
        return None
    level = LEVELS[2 if x['you'] >= 2 and y['you'] >= 2 else 0 if 0 in (x['you'], y['you']) else 1]
    if x['you'] > y['them'] and y['you'] > x['them']:
        reading = READING[0]
    elif abs(x['you'] - y['them']) <= 1 and abs(y['you'] - x['them']) <= 1:
        reading = READING[1]
    else:
        reading = READING[2]
    return {'level': level, 'reading': reading}


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
.card{padding:16px 16px 14px;min-height:470px;display:flex;flex-direction:column}.card[hidden]{display:none}.card .nav{margin-top:auto;padding-top:14px}
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
.done .big{font-size:44px;line-height:1;margin:18px 0 6px;color:var(--plum)}
.go{margin:4px 0 12px;padding:12px 14px;border-radius:14px;background:linear-gradient(135deg,#7b3fa0,#c2366d);color:#fff;font-weight:750;font-size:16px;text-align:center}
.own{display:block;width:100%;margin-top:8px;padding:11px 12px;border:1.5px solid var(--plum);border-radius:14px;font:inherit;font-size:16px;color:var(--ink);background:#fff;resize:none;min-height:70px}.own[hidden]{display:none}
.intro .question{font-size:20px}.how{margin:0 0 8px;font-size:15px;line-height:1.5;color:var(--ink)}.intro p.small{margin:12px 0 0;font-size:13px;color:var(--soft)}
.start{all:unset;cursor:pointer;display:block;margin-top:16px;padding:13px 16px;border-radius:14px;background:var(--plum);color:#fff;font-weight:750;font-size:16px;text-align:center;-webkit-tap-highlight-color:transparent}
'''

W_JS = r'''
(function(){
var D=JSON.parse(document.getElementById('pt-data').textContent),ans={},at=-1,field=document.getElementById('pt-answers'),OTHER=D.other;
function done_(id){return (id in ans)&&ans[id]!==OTHER+': ';}
function score(id){var it=D.items.filter(function(x){return x.id===id})[0];return it&&it.scores&&(id in ans)?it.scores[it.options.indexOf(ans[id])]:null;}
function shown(){var deep=0;return D.items.filter(function(it){
 if(it.follows&&D.certain.indexOf(it.pillar)<0&&!(it.follows in ans&&score(it.follows)===0))return false;
 if(it.follows){if(deep>=D.followMax)return false;deep++;}
 if(it.onlyIf&&ans['core:future']===D.talked)return false;return true;}).map(function(it){return it.id});}
function card(id){return document.getElementById('c-'+id.replace(':','-'));}
function show(){var ids=shown(),n=ids.filter(done_).length;
 [].slice.call(document.querySelectorAll('.card')).forEach(function(c){c.hidden=true});
 document.querySelector('.prog i').style.width=Math.round(100*n/ids.length)+'%';
 field.value=JSON.stringify(ans);
 if(at<0){document.getElementById('c-intro').hidden=false;document.querySelector('.count').textContent=ids.length+' questions · about 3 minutes';return;}
 document.querySelector('.count').textContent=Math.min(at+1,ids.length)+' of '+ids.length;
 if(at>=ids.length){var d=document.getElementById('c-done');d.hidden=false;d.querySelector('h3').textContent='All '+ids.length+' answered';
  document.querySelector('.count').textContent='All '+ids.length+' answered';return;}
 var c=card(ids[at]);c.hidden=false;c.querySelector('.back').disabled=false;c.querySelector('.next').hidden=!done_(ids[at]);}
function own(name){return document.querySelector('textarea[data-for="'+name+'"]');}
document.addEventListener('change',function(e){var t=e.target;if(!t||t.type!=='radio')return;
 [].slice.call(document.querySelectorAll('input[name="'+t.name+'"]')).forEach(function(x){x.parentNode.classList.toggle('on',x.checked)});
 var box=own(t.name);
 if(t.value===OTHER&&box){box.hidden=false;ans[t.name]=OTHER+': '+box.value.trim();box.focus();show();return;}
 if(box)box.hidden=true;
 ans[t.name]=t.value;
 var ids=shown();Object.keys(ans).forEach(function(k){if(ids.indexOf(k)<0)delete ans[k];});
 setTimeout(function(){at=Math.min(shown().indexOf(t.name)+1,shown().length);show();},220);});
document.addEventListener('input',function(e){var t=e.target;if(!t||!t.getAttribute||!t.getAttribute('data-for'))return;
 ans[t.getAttribute('data-for')]=OTHER+': '+t.value.trim();field.value=JSON.stringify(ans);
 var c=t.closest('.card');if(c)c.querySelector('.next').hidden=!t.value.trim();});
document.addEventListener('click',function(e){var b=e.target.closest?e.target.closest('button'):null;if(!b)return;
 if(b.classList.contains('start')){at=0;show();}
 if(b.classList.contains('back')){at=at-1;show();}
 if(b.classList.contains('next')){at=Math.min(at+1,shown().length);show();}
 if(b.classList.contains('edit')){at=0;show();}});
// Muse keeps a widget's form state and puts it back when it draws the widget again (scrolling, reopening the chat):
// the answers are read back from the ticked radios and typed words, and it opens on the first one still to answer.
function restore(){if(Object.keys(ans).length)return;var got=false;
 [].slice.call(document.querySelectorAll('input[type=radio]:checked')).forEach(function(x){got=true;x.parentNode.classList.add('on');
  var box=own(x.name);if(x.value===OTHER&&box){box.hidden=false;ans[x.name]=OTHER+': '+box.value.trim();}else ans[x.name]=x.value;});
 if(!got)return;var ids=shown(),left=ids.filter(function(i){return !done_(i);});at=left.length?ids.indexOf(left[0]):ids.length;show();}
show();restore();setTimeout(restore,300);setTimeout(restore,1200);})();
'''


def widget_html(s):
    its = its_for(s)
    p = s.get('partner') or 'your partner'
    data = {'certain': certain(s), 'followMax': FOLLOW_MAX, 'talked': 'Yes, and we\'ve talked', 'other': OTHER,
            'items': [{'id': it['id'], 'pillar': it['pillar'], 'options': it['options'], 'scores': it.get('scores'), 'follows': it.get('follows'),
                       'onlyIf': it.get('onlyIf'), 'short': it['text'].replace('{p}', p)} for it in its]}
    cards = []
    for it in its:
        ch_ = next((c_ for c_ in CHAPTERS if c_[0] == chapter_of(it)), None)
        what_ = ('How well you know %s' % p if it['kind'] == 'know' else 'Going deeper' if it['kind'] == 'deeper' else 'The big decisions' if it['kind'] == 'decision'
                 else 'Overall' if it['kind'] == 'overall' else PILLARS.get(it['pillar'], ''))
        chip = ('<span class="chip lock">Private · never shared</span>' if it.get('private') else
                '<span class="chip">%s</span>' % _e(('%s %s · %s' % (ch_[1], ch_[2], what_)) if ch_ else what_))
        opts = ''.join('<label><input type="radio" name="%s" value="%s"><span>%s</span></label>' % (_e(it['id']), _e(o), _e(o)) for o in it['options'])
        if it.get('own'):
            opts += '<textarea class="own" data-for="%s" maxlength="200" rows="2" placeholder="In your own words" hidden></textarea>' % _e(it['id'])
        cards.append('<section class="card" id="c-%s" hidden>%s%s<p class="question">%s</p><div class="opts">%s</div>'
                     '<div class="nav"><button type="button" class="back">‹ Back</button><button type="button" class="next" hidden>Next ›</button></div></section>'
                     % (it['id'].replace(':', '-'), chip, ('<p class="opener">%s</p>' % _e(it['opener'])) if it.get('opener') else '',
                        _e(it['text'].replace('{p}', p)), opts))
    return ('<div class="pt"><style>%s</style><div class="top"><small>Psyche Together%s</small><b>You &amp; %s</b><div class="prog"><i></i></div>'
            '<div class="count"></div></div><form id="pt-form" onsubmit="return false">'
            '<section class="card intro" id="c-intro"><span class="chip">Your questions</span><p class="question">Written from both your Psyches, for the two of you.</p>'
            '<p class="how">Tap an answer and it moves on, with Back to change one. Some let you answer in your own words. At the end, tap <b>Submit my answers</b> just under this box.</p>'
            '<button type="button" class="start">Start ›</button><p class="small">Already tapped Submit my answers? Then yours are sent, and you can ignore this box.</p></section>%s'
            '<section class="card done" id="c-done" hidden><div class="big">✓</div><h3>All answered</h3><p>To check or change one, tap Change an answer and go through them again.</p><div class="go">Now tap Submit my answers, just below ↓</div>'
            '<div class="nav"><button type="button" class="edit">‹ Change an answer</button><span></span></div></section>'
            '<input type="hidden" id="pt-answers" name="psyche-together-answers" value="{}"></form>'
            '<script type="application/json" id="pt-data">%s</script><script>%s</script></div>'
            % (W_CSS, ' · %d weeks on' % weeks_on(live_round(s)['n']) if live_round(s) else '', _e(p), ''.join(cards), json.dumps(data).replace('</', '<\\/'), W_JS))


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
    its, bad = its_for(s), []
    byid = {it['id']: it for it in its}
    answers = dict(ans_for(s))
    for k, v in got.items():
        it = byid.get(k)
        if it and it.get('own') and isinstance(v, str) and v.startswith(OTHER + ':'):
            words = clean_typed(v[len(OTHER) + 1:], [s.get('partner') or ''])
            if words:
                answers[k] = {'label': OTHER, 'text': words}
            continue                     # "Something else" with no words: asked again in the chat
        if it and it.get('own') and v == OTHER:
            continue
        if not it:
            bad.append('%s isn\'t one of the questions' % k)
        elif v in it['options']:
            answers[k] = {'label': v}
        elif v not in (None, ''):
            bad.append('%s: "%s" isn\'t one of its options' % (k, v))
    ids = shown(s, its, answers)
    kept_ = {k: v for k, v in answers.items() if k in ids}
    if live_round(s):
        s['round']['answers'] = kept_
    else:
        s['answers'] = kept_
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
CHAT_MAX = 6000          # messages read from the Instagram thread, newest first (a WhatsApp export is read whole)
# README "Psyche Together, release 21": what the read sees of their conversation, at least what a Psyche Report
# reads of all of someone's messages (its 115,000 characters): spread over the whole span, a long message as its
# opening and its end, as the PsycheAI skill keeps one (TEXT_CHARS).
IG_SECONDS = 25          # reading the Instagram thread stops after this, newest first: a 1,123-message thread took 64 s in Muse
CHAT_BUDGET = 120000
CHAT_BYTES = 160000      # and at most this in UTF-8, so locked it fits one request (256 KB) whatever the script: Chinese or emoji take 3 or 4 bytes a character
TEXT_CHARS = 483
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
EMOJI = re.compile('[\U0001F300-\U0001FAFF\u2600-\u27BF\u2764]')
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
    """A message's time as a local datetime. Instagram now sends it as a bundle ({user_local, user_timezone, utc}):
    their own wall-clock time is used as it is, so the day's rhythm is theirs, else utc made local (README
    "Psyche Together, release 21")."""
    if isinstance(v, dict):
        local = v.get('user_local')
        if isinstance(local, str) and local.strip():
            try:
                return datetime.fromisoformat(local.strip().replace('Z', '+00:00')).replace(tzinfo=None)
            except ValueError:
                pass
        return _when(v.get('utc') or v.get('timestamp') or v.get('ms'))
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
    size, until = 100, time.time() + IG_SECONDS
    while len(out) < CHAT_MAX and pages < 80 and time.time() < until:
        page = _cli(IGM_CLI, 'thread', '--account-id', th['account'], '--thread-fbid', th['fbid'], '--first', size, *(('--after', after) if after else ()))
        if not page and size > 50:
            size = 50           # a page of 100 refused: 50 a page, as the PsycheAI skill does
            continue
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
        s['replyWithin5'] = round(100 * sum(1 for x in r if x <= 5) / len(r)) if r else None     # times are to the minute: a share reads better than a median of 0
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
    by_month, by_day, emoji = {}, {}, {'me': {}, 'them': {}}
    for t, who, text in msgs:
        by_month[t.strftime('%Y-%m')] = by_month.get(t.strftime('%Y-%m'), 0) + 1
        by_day[t.date()] = by_day.get(t.date(), 0) + 1
        for e in EMOJI.findall(text):
            emoji[who][e] = emoji[who].get(e, 0) + 1
    days = sorted(by_day)
    streak = best = 1 if days else 0
    for x, y in zip(days, days[1:]):
        streak = streak + 1 if (y - x).days == 1 else 1
        best = max(best, streak)
    busiest = max(by_day.items(), key=lambda kv: kv[1]) if by_day else None
    side['me']['emoji'] = [e for e, _ in sorted(emoji['me'].items(), key=lambda kv: -kv[1])[:3]]
    side['them']['emoji'] = [e for e, _ in sorted(emoji['them'].items(), key=lambda kv: -kv[1])[:3]]
    first, end = msgs[0][0], msgs[-1][0]
    months = max(1, (end.year - first.year) * 12 + end.month - first.month + 1)
    mid = first + (end - first) / 2
    a, b = sum(1 for m in msgs if m[0] < mid), sum(1 for m in msgs if m[0] >= mid)
    return {'from': first.strftime('%Y-%m-%d'), 'to': end.strftime('%Y-%m-%d'), 'messages': len(msgs), 'perMonth': round(len(msgs) / months, 1),
            'trend': 'rising' if b > a * 1.25 else 'falling' if a > b * 1.25 else 'steady', 'you': side['me'], 'partner': side['them'],
            'styleMatch': round(sum(lsm) / len(lsm), 2) if words['me'] and words['them'] else None,
            'months': [[k, by_month[k]] for k in sorted(by_month)],
            'fun': {'first': first.strftime('%-d %B %Y'), 'busiestDay': [busiest[0].strftime('%-d %B %Y'), busiest[1]] if busiest else None,
                    'streak': best, 'daysTalking': len(days)}}


# Common first names, as the PsycheAI skill keeps them (its COMMON_NAMES): taken out of the sample wherever they turn
# up, as [name], so someone else in the two of them's lives isn't named to the read. The two of them are kept.
COMMON_NAMES = frozenset("""
    aaron abby abigail adam adeline adrian agnes ahmad aidan aiden aisha alan albert alex alexa
    alexander alexandra alexis alfred ali alice alicia alison allison alyssa amanda amelia
    amir amy andre andrea andrew andy angela angelina angie anita ann anna annabelle anne annie
    anthony antonio arjun arnold arthur ashley audrey ava avery bailey barbara beatrice becky
    belinda ben benedict benjamin bernard beth bethany betty beverly bianca bobby bonnie brad
    bradley brandon brenda brendan brian bridget brittany bruce bryan bryce caleb calvin cameron
    camila candice carl carla carlos carmen caroline carolyn casey cassandra catherine cecilia
    celeste celine chad charlene charles charlie charlotte charmaine cheryl chloe chris christina
    christine christopher cindy claire clara clarence claudia clement colin connie connor conor
    constance corey craig cynthia daisuke damian damien dan daniel danielle danny darren darryl
    david debbie deborah declan denise dennis derek desiree desmond diana diane dominic donald donna
    doris dorothy douglas dylan edmund edward edwin eileen elaine eleanor elena eli elijah elisa
    elise eliza elizabeth ella ellen ellie eloise elsie emily emma eric erica erin esther ethan
    eugene evelyn fabian farah fatimah felicia felix fernando fiona francesca francis gabriel
    gabriella gareth gavin genevieve geoffrey george gerald geraldine germaine gillian gina gloria
    gordon graham greg gregory gwen gwendolyn hailey haley hannah harold harriet harrison harry
    heidi helen henry herbert howard hugo huimin ian ingrid irene isaac isabel isabella isabelle
    isaiah jacob jacqueline jake james jamie jane janet janice jared jason jasper jeff jeffrey jen
    jenna jennifer jenny jeremy jerome jess jesse jessica jessie jiahui jill jim joanna joanne
    jocelyn joe joel joey john johnny jolene jolin jon jonathan joseph josh joshua joyce juan judith
    judy julia julian juliana julie justin karen karthik kate katherine kathleen kathryn kathy katie
    kayla keith kelly ken kenneth kenny kevin kim kimberly kirsten kristen kyle lachlan laura lauren
    lawrence leah leon leonard leslie lewis liam lillian linda lindsay lionel lisa liz lizzie logan
    lorraine louis louisa louise lucas lucy luis luke lydia lynn madeleine maggie mandy marcus
    margaret maria marian marianne marie marilyn martha martin marvin mary matilda matt matthew
    maureen maxwell meg megan melanie melissa melvin michael michaela michelle mikayla mike mildred
    mohamed mohammad mohammed monica muhammad nadia naomi natalie natasha nate nathan nathaniel neil
    nicholas nicole nigel noah norman nurul oliver olivia oscar owen pamela patricia patrick paul
    paula pauline pete peter phil philip phoebe phyllis pooja preeti priscilla priya rachel rahul
    ralph randy raphael rebecca regina reuben rhys ricardo richard rick ricky rita robert roberto
    rodney roger ronald rosalind rosemary russell ruth ryan sabrina sally sam samantha samuel sandra
    sara sarah scott sean sebastian selina serena seth shane shannon sharon sheila shermaine shirley
    siti sophia sophie stanley stella stephanie stephen steve steven suresh susan sylvia tamara
    tanya terence teresa theodore theresa thomas tiffany tim timothy tina tobias todd tom tony tracy
    trevor tyler valerie vanessa veronica victor vincent vivian wallace walter weiming wendy wesley
    william winnie winston xavier xinyi yvonne zach zachary zack zoe
""".split())
NAME_RX = re.compile(r"\b[A-Za-z][a-z]{2,}\b")
# What the sample keeps (README "Psyche Together, release 23"), as the PsycheAI skill chooses a chat's lines
# (its choose_messages): a burst is one line, filler and link-only lines are out, a short one stays only if it
# opens a conversation, apologises, names a feeling or asks; ten equal stretches of time share the room by the
# square root of their size, so quiet years aren't starved; long, ordinary and short lines 50/40/10 within each.
BURST = 120
SHORT = 30
LONG = 120
FILLER = re.compile(r'^((ha)+h?|(he)+|lo+l+|lmao|ok|okay|okie|k|kk|omw|yes|yeah|ya|yup|no|nope|sure|hm+|cool|nice|thanks|thx|ty|icic|alr|wah|wahlau|walao|eh|wth|wtf+|omg+|link)$')
FEELING = re.compile(r'\b(love|loved|miss(?:ed)? you|hate|angry|mad at|upset|sad|hurt|worried|worry|anxious|scared|afraid|stressed|lonely|proud|grateful|thankful|disappoint\w*|frustrat\w*|annoy\w*|jealous|cry|crying|cried|happy|excited|feel|feeling|felt|sick of|tired of|overwhelm\w*|argu\w*|fight|fought|sian|emo)\b', re.I)
FORWARD = re.compile(r'^(?:forwarded(?: many times)?\b|fwd?:)', re.I)
LINKED = re.compile(r'\b(?:https?://|www\.)\S+', re.I)


def _share(weights, total, caps):
    """total places shared by weight, none over its cap; what a capped one can't take goes on to the rest."""
    out, left = [0] * len(weights), total
    live = [k for k, c in enumerate(caps) if c > 0 and weights[k] > 0]
    while left > 0 and live:
        w = sum(weights[k] for k in live)
        given = 0
        for k in live:
            take = min(int(left * weights[k] / w), caps[k] - out[k])
            out[k] += take
            given += take
        if given == 0:
            for k in sorted(live, key=lambda k: -weights[k]):
                if left - given <= 0:
                    break
                if out[k] < caps[k]:
                    out[k] += 1
                    given += 1
            if given == 0:
                break
        left -= given
        live = [k for k in live if out[k] < caps[k]]
    return out


def clean_line(text, keep=()):
    """One message for the sample: links, emails, handles and numbers out, other people's first names out; a long one
    as its opening and its end."""
    t = re.sub(r'\s+', ' ', str(text or '')).strip()
    for rx, sub in SCRUB:
        t = rx.sub(sub, t)
    keep = {k.lower() for k in keep if k}
    t = NAME_RX.sub(lambda m: '[name]' if m.group(0).lower() in COMMON_NAMES and m.group(0).lower() not in keep and m.group(0)[0].isupper() else m.group(0), t)
    return t if len(t) <= TEXT_CHARS else t[:330].rstrip() + ' … ' + t[-(TEXT_CHARS - 334):].lstrip()


def chat_sample(msgs, me_name, them_name, budget=None, keep=()):
    """What the read sees of their conversation, up to CHAT_BUDGET characters (and CHAT_BYTES), both voices, in time
    order: each line its date, time, who, and the message."""
    import zlib
    budget = budget or CHAT_BUDGET
    if not msgs:
        return []
    keep = set(keep) | {me_name, them_name}
    units, seen, prev = [], set(), None
    for t, who, text in msgs:             # a burst from one side, within two minutes, is one line
        raw = str(text or '').strip()
        if not raw:
            continue
        if units and prev and prev[1] == who and (t - prev[0]).total_seconds() <= BURST and len(units[-1]['raw']) + len(raw) + 3 <= TEXT_CHARS:
            units[-1]['raw'] += ' / ' + raw
        else:
            units.append({'t': t, 'who': who, 'raw': raw, 'opener': prev is None or (t - prev[0]).total_seconds() >= GAP})
        prev = (t, who)
    kept = []
    for u in units:
        raw = u['raw']
        if FORWARD.search(raw) or len(raw) > 1600:
            continue
        if LINKED.search(raw) and len(re.findall(r'\w{2,}', LINKED.sub(' ', raw))) < 4:
            continue                       # a link with hardly a word of their own says nothing about them
        key = re.sub(r'(.)\1+', r'\1', re.sub(r'[^\w]+', '', raw.lower()))
        if (key and (u['who'], key) in seen) or (not key and len(raw) < 3):
            continue
        short = len(raw) < SHORT
        if short and (FILLER.match(key or '') or not (u['opener'] or SORRY.search(raw) or FEELING.search(raw) or THANKS.search(raw) or WARM.search(raw) or '?' in raw)):
            continue
        seen.add((u['who'], key))
        line = '%s %s: %s' % (u['t'].strftime('%Y-%m-%d %H:%M'), me_name if u['who'] == 'me' else them_name, clean_line(raw, keep))
        kept.append(dict(u, line=line, cost=len(line) + 1, bytes=len(line.encode('utf-8')) + 1,
                         score=(2 if u['opener'] else 0) + (2 if SORRY.search(raw) else 0) + (2 if FEELING.search(raw) or WARM.search(raw) else 0)
                         + (1 if THANKS.search(raw) else 0) + (1 if '?' in raw else 0), hash=zlib.crc32(raw.encode())))
    if not kept:
        return []
    wide = sum(u['bytes'] for u in kept) / max(1, sum(u['cost'] for u in kept))
    budget = min(budget, int(CHAT_BYTES / max(1.0, wide)))
    if sum(u['cost'] for u in kept) <= budget:
        return [u['line'] for u in kept]
    avg = sum(u['cost'] for u in kept) / len(kept)
    want = min(len(kept), int(budget / avg * 1.1) + 1)
    first, span = kept[0]['t'], (kept[-1]['t'] - kept[0]['t']).total_seconds()
    n = 10 if span > 0 else 1
    periods = [[] for _ in range(n)]
    for u in kept:
        periods[min(n - 1, int((u['t'] - first).total_seconds() * n / (span + 1))) if span > 0 else 0].append(u)
    places = _share([round(len(p) ** 0.5 * 100) for p in periods], want, [len(p) for p in periods])
    chosen = []
    for period, room in zip(periods, places):
        bands = [[u for u in period if len(u['raw']) >= LONG], [u for u in period if SHORT <= len(u['raw']) < LONG], [u for u in period if len(u['raw']) < SHORT]]
        for band, k in zip(bands, _share([50, 40, 10], room, [len(b) for b in bands])):
            band.sort(key=lambda u: (-u['score'], u['hash']))
            chosen.extend(band[:k])
    chosen.sort(key=lambda u: u['t'])
    while len(chosen) > 1 and sum(u['cost'] for u in chosen) > budget:      # within the budget: thinned evenly through time
        over = sum(u['cost'] for u in chosen) - budget
        drop = max(1, min(len(chosen) - 1, int(over / (sum(u['cost'] for u in chosen) / len(chosen))) + 1))
        gone = {int(k * len(chosen) / drop) for k in range(drop)}
        chosen = [u for k, u in enumerate(chosen) if k not in gone]
    return [u['line'] for u in chosen]


def named_chat(chat, me_name, them_name):
    """The conversation with each line labelled as the two Psyches name them (the thread may name the partner differently from their Psyche)."""
    if not chat or not chat.get('sample'):
        return chat
    labels = chat.get('labels') or {}
    swap = {k: v for k, v in ((labels.get('me'), me_name), (labels.get('them'), them_name)) if k and v and k != v}
    if not swap:
        return chat
    def fix(line):
        head, rest = line[:17], line[17:]
        for old, new_ in swap.items():
            if rest.startswith(old + ': '):
                return head + new_ + rest[len(old):]
        return line
    return dict(chat, sample=[fix(x) for x in chat['sample']], labels={'me': me_name, 'them': them_name})


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
    s['pickedThread'], s['igCount'], s['igRetried'] = label, len(msgs), True
    save_state(s)
    return dict(chat_step(s), read='%d messages from your Instagram chat with %s' % (len(msgs), label))


def reread_instagram(s):
    """Once, before the read is written: the picked Instagram chat read again when it came back empty, or was read
    before release 21, when Instagram's new date format (a bundle: user_local, user_timezone, utc) made every
    message drop out. New messages are added to what's kept (none twice), counted, and the locked copy updated."""
    if s.get('role') != 'a' or s.get('readAt') or s.get('igRetried') or 'instagram' not in (s.get('chatDone') or []):
        return None
    old, sources, partner = kept_messages()
    label = s.get('pickedThread') or partner
    th = next((t for t in s.get('threads') or [] if t.get('label') == label), None)
    s['igRetried'] = True
    save_state(s)
    if not th:
        return None
    msgs = instagram_thread(th)
    seen = {(t.strftime('%Y-%m-%d %H:%M'), who, text) for t, who, text in old}
    new = [m for m in msgs if (m[0].strftime('%Y-%m-%d %H:%M'), m[1], m[2]) not in seen]
    s['pickedThread'], s['igCount'] = label, len(msgs)
    save_state(s)
    if not new:
        return None
    keep_messages(old + new, sources if 'instagram' in sources else sources + ['instagram'], partner or label)
    count_chat(s)
    if s.get('chatFinished') or s.get('questions'):
        put_profile(s, bool(s.get('sent')))
    return len(new)


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
    s['waCount'] = int(s.get('waCount') or 0) + len(msgs)
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
    counts = {k: s[c] for k, c in (('instagram', 'igCount'), ('whatsapp', 'waCount')) if s.get(c)}
    keep = [w for n in (str((psyche() or {}).get('name') or ''), str(partner or '')) for w in n.split()]
    s['chat'] = {'source': ' and '.join(sources), 'signals': chat_signals(msgs), 'sample': chat_sample(msgs, me_first, them_first, keep=keep), 'counts': counts,
                 'labels': {'me': me_first, 'them': them_first}} if msgs else None
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
    lb = chat.get('labels') or {}
    return {'source': chat.get('source'), 'signals': sig, 'sample': chat.get('sample'), 'labels': {'me': lb.get('them'), 'them': lb.get('me')}}


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
    'overall': 'How satisfied someone believes their partner is was among the five strongest predictors of relationship quality across 11,196 couples (Joel et al., PNAS 2020): reading each other well matters as much as how each one feels.',
    'values': 'Shared meaning, the values, rituals and goals a couple builds together, is the top floor of Gottman\'s Sound Relationship House; being alike matters less than what you make of it together (Joel et al., 2020).',
    'lovemaps': 'Knowing each other\'s inner world, worries, hopes and everyday life, is the foundation the rest of a relationship is built on (Gottman, love maps).',
}


# ---------------------------------------------------------------- the couple

PENDING = os.path.join(KEEP, 'together-pending.json')     # a partner's invite, kept while they make their Psyche


def needs_psyche(link=None):
    """No Psyche yet (README "Psyche Together, release 22"): Muse goes straight on to make theirs, in the same chat, with
    nothing more to paste or tap; a partner's invite is kept, and taken up by itself once their Psyche is ready."""
    link = link or (read_first([PENDING]) or {}).get('link')     # a kept invite always wins over a plain start
    if link:
        write_private([PENDING], {'link': link, 'at': int(time.time())})
        return {'needsPsyche': True, 'pending': True, 'startPsyche': True,
                'say': 'Psyche Together is built on both your Psyches, so first, yours: about 5 minutes, read from your own Instagram right here. '
                       'Your partner\'s invite is kept, and once your Psyche is ready you\'ll go straight on to your questions.'}
    write_private([PENDING], {'start': True, 'at': int(time.time())})     # they asked to start one: it starts once their Psyche is ready
    return {'needsPsyche': True, 'pending': True, 'startPsyche': True,
            'say': 'Psyche Together is built on both your Psyches, so first, yours: about 5 minutes, read from your own Instagram right here. '
                   'Once it\'s ready, we\'ll go straight on to start your Psyche Together.'}


CONSENT = ('Psyche Together: each of you answers privately, in your own Muse, and your partner never sees how you answered: the read shows '
           'the two of you together. For a read this deep, your full Psyche report and your Psyche Card picture go to your partner\'s Muse, locked. The one who starts it adds '
           'your conversation together (your Instagram chat, and your WhatsApp chat if they share it): what it shows, and a dated sample of it, go '
           'with it, locked, for your read. Nothing from chats with anyone else is read, and PsycheAI can\'t read any of it.')


def start():
    if not psyche() or not account():
        return needs_psyche()
    if (read_first([PENDING]) or {}).get('start'):
        try:
            os.remove(PENDING)
        except OSError:
            pass
    s = state()
    if s.get('role'):
        return {'error': 'There\'s a Psyche Together here already: "Continue Psyche Together", or "End Psyche Together" first.'}
    code = secrets.token_urlsafe(16)
    got = tool('together_link', {'e2e': {'id': couple_id(code)}})
    if got.get('access'):         # prepared for a paid Psyche Together (PLAN.md): the server says how to get it, on the website
        return {'needsAccess': True, 'say': got['access'].get('say') or '', 'url': got['access'].get('url')}
    if got.get('error'):
        return got
    save_keys({'code': code, 'role': 'a'})
    save_state({'role': 'a', 'v': 3, 'started': int(time.time()), 'answers': {}})
    return dict(next_step(), consent=CONSENT)


def card_pic():
    """Their own Psyche Card, as the PsycheAI skill saved it, made small for the page's header (README "Psyche
    Together, release 20"): a JPEG 360 wide at most, with Pillow; without it, the PNG only if it's small. Else None."""
    found = sorted(glob.glob(os.path.join(PSYCHE_DIR, 'out', 'Psyche-Card-*.png')) + glob.glob(os.path.join(KEEP, 'Psyche-Card-*.png')),
                   key=lambda f: os.path.getmtime(f))
    if not found:
        return None
    try:
        with open(found[-1], 'rb') as f:
            raw = f.read()
    except OSError:
        return None
    try:
        from PIL import Image
        im = Image.open(io.BytesIO(raw)).convert('RGBA')
        back = Image.new('RGB', im.size, (255, 255, 255))
        back.paste(im, mask=im.split()[-1])
        back.thumbnail((360, 640))
        buf = io.BytesIO()
        back.save(buf, 'JPEG', quality=80, optimize=True)
        return 'data:image/jpeg;base64,' + base64.b64encode(buf.getvalue()).decode()
    except Exception:
        return ('data:image/png;base64,' + base64.b64encode(raw).decode()) if len(raw) <= 90000 else None


PROFILE_V = 2      # what a profile carries changed (2: MBTI letters with their strength): each side sends theirs again once


def put_profile(s, answered):
    k = keys()
    e2e = {'profile': seal(shared_profile(s, answered), key_for('together-box', k['code']))}
    pic = None if s.get('picSent') else card_pic()
    if pic:
        e2e['pic'] = seal({'img': pic}, key_for('together-box', k['code']))
    got = tool('together_put', {'e2e': e2e})
    if not got.get('error') and answered:
        s['profileV'] = PROFILE_V
        save_state(s)
    if pic and not got.get('error'):
        s['picSent'] = True
        save_state(s)
    sample = (s.get('chat') or {}).get('sample')
    mark = hashlib.sha256(json.dumps(sample or [], ensure_ascii=False).encode()).hexdigest()[:16]
    if sample and not got.get('error') and s.get('chatSent') != mark:
        got = tool('together_put', {'e2e': {'chat': seal({'sample': sample}, key_for('together-box', k['code']))}})     # its own request: up to 120,000 characters
        if not got.get('error'):
            s['chatSent'] = mark
            save_state(s)
    return got


def after_stage(s):
    """The stage is in: their conversation next (README "Psyche Together, release 12"), then the invite."""
    return chat_step(s)


def join(link):
    m = LINK.search(str(link or ''))
    if not m:
        return {'error': 'That isn\'t a Psyche Together link: it looks like app.psycheai.io/together#… . Ask your partner to send it again.'}
    if not psyche() or not account():
        return needs_psyche(link)
    s = state()
    if s.get('role'):
        return {'error': 'There\'s a Psyche Together here already: "End Psyche Together" first to join a new one.'}
    try:
        os.remove(PENDING)
    except OSError:
        pass
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
    return {'url': link, 'invite': '%s invited you to Psyche Together, a private check-in for the two of you. Paste this into your Muse app: Install the Psyche Together skill from app.psycheai.io/together and join our Psyche Together: %s'
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
    for r in ('a', 'b'):
        talk = unseal((e.get('chats') or {}).get(r), key)
        if isinstance(talk, dict) and isinstance((profiles.get(r) or {}).get('chat'), dict):
            profiles[r]['chat']['sample'] = talk.get('sample') or []
    pics = {r: (unseal((e.get('pics') or {}).get(r), key) or {}).get('img') for r in ('a', 'b')}
    SEEN.update(pics={r: p for r, p in pics.items() if isinstance(p, str) and p.startswith('data:image/')},
                cards={r: (profiles.get(r) or {}).get('psyche') or {} for r in ('a', 'b')})
    return k, got, profiles, unseal(e.get('read'), key)


SEEN = {}       # the couple's card pictures and cards, as couple() last opened them, for the page's header


def mine_theirs(s, profiles):
    me, them = ('a', 'b') if s.get('role') == 'a' else ('b', 'a')
    return profiles.get(me) or {}, profiles.get(them) or {}


def task_file(d):
    """A writing job's data (both reports, the conversation: often 200 KB), saved where Muse reads it, so the command's
    own answer stays short enough to show whole (README "Psyche Together, release 22")."""
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, 'together-%s-task.json' % d['write'])
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False)
    os.chmod(path, 0o600)
    short = {k: v for k, v in d.items() if k in ('write', 'saveTo', 'stage', 'pillars', 'gentle')}
    if isinstance(d.get('partner'), dict):
        short['partnerName'] = d['partner'].get('name')
    return dict(short, task='work/together-%s-task.json' % d['write'])


def done_task(kind):
    try:
        os.remove(os.path.join(WORK, 'together-%s-task.json' % kind))
    except OSError:
        pass


def widget_out(s, say):
    """The questions widget, also saved as a file Muse can show as it is."""
    html_ = widget_html(s)
    os.makedirs(WORK, exist_ok=True)
    path = os.path.join(WORK, 'questions-widget.html')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(html_)
    return {'widget': html_, 'widgetFile': 'work/questions-widget.html', 'say': say, 'buttons': ['Submit my answers'], 'asButtons': True}


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
    return task_file({'write': 'questions', 'you': psyche_profile(psyche() or {}), 'partner': theirs.get('psyche'), 'stage': stage,
                      'yourReport': (psyche() or {}).get('report'), 'partnerReport': theirs.get('report'),
                      'yourChat': named_chat(s.get('chat') if s.get('role') == 'a' else flip_chat(theirs.get('chat')),
                                             (psyche_profile(psyche() or {}).get('name')), (theirs.get('psyche') or {}).get('name')),
                      'pillars': pillars, 'focus': focus, 'saveTo': 'work/together-questions.json'})


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
    kn = q.get('know')
    if not (isinstance(kn, list) and len(kn) == 2):
        problems.append('know: exactly two questions about %s, each q, 3 or 4 options, its answer and its basis in their report' % (partner or 'your partner'))
    else:
        for i, k_ in enumerate(kn):
            k_ = k_ if isinstance(k_, dict) else {}
            o_ = k_.get('options')
            ok = (isinstance(k_.get('q'), str) and 10 <= len(k_['q'].strip()) <= 180 and isinstance(o_, list) and 3 <= len(o_) <= 4
                  and all(isinstance(x, str) and 1 <= len(x.strip()) <= 40 for x in o_) and len(set(o_)) == len(o_))
            ok = ok and k_.get('answer') in (o_ or []) and isinstance(k_.get('basis'), str) and 10 <= len(k_['basis'].strip()) <= 200
            if not ok:
                problems.append('know[%d]: q (10 to 180 characters), 3 or 4 different options (each under 40 characters), answer (one of the options) and basis (where in their report it says so, 10 to 200 characters)' % i)
    named = sum(1 for p in pillars if partner and partner.lower() in str(op.get(p, '')).lower())
    if partner and named < (len(pillars) + 1) // 2:
        problems.append('openers: name %s in at least half of them, so each reads as about the two of you' % partner)
    _plain(problems, {'openers': op, 'followUps': fu, 'know': [{k: v for k, v in (x if isinstance(x, dict) else {}).items() if k != 'basis'} for x in (kn if isinstance(kn, list) else [])]}, 240)
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
    know_ = []
    for i, k_ in enumerate(q['know']):
        opts = [x.strip() for x in k_['options']]
        secrets.SystemRandom().shuffle(opts)        # the right one is never always first
        know_.append({'id': 'know:%d' % (i + 1), 'q': k_['q'].strip(), 'options': opts, 'answer': k_['answer'].strip()})
    s['questions'] = {'openers': {p: q['openers'][p].strip() for p in pillars}, 'followUps': {p: q['followUps'][p] for p in pillars}, 'know': know_}
    save_state(s)
    done_task('questions')
    try:
        os.remove(str(path).lstrip('@'))
    except OSError:
        pass
    return widget_out(s, 'Your questions, written from both your Psyches.')


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
    if live_round(s):
        return round_send(s)
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
        out = dict(foryou_task(), sent=True)
        k, got, profiles, box = couple()
        if not got.get('error') and not box and all('core' in (profiles.get(r) or {}) for r in ('a', 'b')):
            out['readTask'] = write_task(profiles).get('task')     # last one in: the read can be written beside For you
        return out
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
        other = profiles['b' if r == 'a' else 'a']
        people.append({'name': (pr.get('psyche') or {}).get('name'), 'card': pr.get('psyche') or {}, 'report': pr.get('report'),
                       'chat': named_chat(pr.get('chat'), (pr.get('psyche') or {}).get('name'), (other.get('psyche') or {}).get('name'))})
    return task_file({'write': 'read', 'coupleView': {k: v for k, v in view.items() if k != 'knowBy'}, 'people': people, 'research': RESEARCH, 'saveTo': 'work/together-read.json'})


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


# The read's five chapters, in order, numbered as the glance and the page show them (README "Psyche Together,
# release 16"): (id, number, title, its pillars, its research lines).
CHAPTERS = [('close', '01', 'Care & Connection', ['appreciation', 'connection', 'desire'], ['appreciation', 'connection']),
            ('life', '02', 'Living together', ['needs', 'life'], ['needs', 'life']),
            ('future', '03', 'Shared meaning', ['future', 'growth'], ['values', 'future', 'growth']),
            ('secure', '04', 'Attachment & Commitment', ['security'], ['security']),
            ('disagree', '05', 'Conflict & Repair', ['disagreements'], ['disagreements', 'perpetual', 'dreams'])]
# README "Psyche Together, release 18": a plain title, and under it the research it comes from.
# Release 38: one title per chapter, saying what it covers; no subtitle under a chapter.
SUBTITLES = {'plan': 'Small steps from every chapter'}
# Release 39: each chapter is made of named areas, the same names and order as its row in At a glance's Where you
# stand. A pillar area carries its check-in level; the others a count, a match or a short status.
AREAS = {'close': [('appreciation', 'Appreciation'), ('loves', 'Love languages'), ('know', 'Knowing each other'), ('connection', 'Connection'), ('desire', 'Closeness')],
         'life': [('needs', 'Fairness'), ('life', 'Rhythm'), ('interests', 'Interests')],
         'future': [('values', 'Values'), ('future', 'Shared future'), ('decisions', 'Big decisions'), ('growth', 'Growth')],
         'secure': [('security', 'Security'), ('attachment', 'Attachment')],
         'disagree': [('disagreements', 'Repair'), ('cycle', 'Your cycle')]}
PSY_AREAS = ['loves', 'connection', 'needs', 'life', 'values', 'growth', 'security', 'attachment', 'disagreements', 'cycle']
STATUS_AREAS = ['attachment', 'cycle']
EVIDENCE_KINDS = ['messages', 'psyches', 'report', 'moment']
VERDICTS = {'matches': 'Matches how you see it', 'better': 'Better than you think', 'closer': 'Worth a closer look'}


def areas_of(cid, view):
    """A chapter's areas that apply: a pillar area only when the couple view has it, big decisions only with decisions."""
    return [(a, n) for a, n in AREAS.get(cid, []) if (a not in PILLARS or a in (view.get('pillars') or {})) and (a != 'decisions' or view.get('decisions'))
            and (a != 'know' or (view.get('know') or {}).get('items'))]
PLAN_TITLE = 'Your 28-day practice'


TRUTH_HOME = {'strength': 'close', 'edge': 'disagree', 'surprise': 'secure'}     # where a truth sits when an older read named none
CHAPTER_IDS = [c[0] for c in CHAPTERS]
THEM_TWO = re.compile(r'\bthe two of them\b', re.I)
YOU_TWO = re.compile(r'\byou two\b', re.I)
THE_COUPLE = re.compile(r'\bthe couple\b', re.I)


def _sentences(r):
    out = {}
    for at, t in _texts(r):
        for x in re.split(r'(?<=[.!?])\s+', t):
            k = re.sub(r'[^a-z0-9 ]', '', x.lower()).strip()
            if len(k) >= 60:
                out.setdefault(k, []).append(at)
    return {k: v for k, v in out.items() if len(v) > 1}


def check_read(r, view, has_chat=False):
    """The read, lean (README "Psyche Together, release 24"): a glance, five chapters each with its takeaway, its truth
    when it holds one, its pillars, its story and its parts, said once; one plan; at least 11,000 characters; nothing
    that says who answered what, nothing said twice, and always to "you two"."""
    problems = []
    if not isinstance(r, dict):
        return ['The read is not a JSON object.']
    T = lambda x: x.strip() if isinstance(x, str) else ''
    D = lambda x: x if isinstance(x, dict) else {}
    L = lambda x: x if isinstance(x, list) else []
    ev = lambda xs: len(L(xs)) >= 1 and all(isinstance(e, dict) and DATED.search(T(e.get('when'))) and T(e.get('what')) for e in L(xs))
    need = lambda ok, msg: ok or problems.append(msg)
    need(T(r.get('summary')) and len(T(r.get('summary')).split()) <= 30, 'summary: one specific line, under 30 words')
    if view.get('overall'):
        ov = D(r.get('overall'))
        need(T(ov.get('title')) and 0 < len(T(ov.get('detail'))) <= 400, 'overall: a title and a detail of one or two sentences, at most 400 characters, for the couple, never whose')
    tr = L(r.get('truths'))
    need([D(x).get('kind') for x in tr] == ['strength', 'edge', 'surprise'] and all(T(D(x).get('title')) and 350 <= len(T(D(x).get('detail'))) <= 900
                                                                                  and D(x).get('chapter') in CHAPTER_IDS and ev(D(x).get('evidence')) for x in tr),
         'truths: exactly three, strength, edge and surprise in that order, each a title, a detail of 350 to 900 characters, its chapter (close, secure, disagree, life or future) and dated evidence')
    # Release 42: each area says how you see it, what the evidence shows (each piece tagged with where it comes from),
    # and what it means, ending in next steps that each say which evidence they come from.
    ch = D(r.get('chapters'))
    for cid in CHAPTER_IDS:
        c = D(ch.get(cid))
        need(0 < len(T(c.get('takeaway'))) <= 240, 'chapters.%s.takeaway: the one thing to take from it, at most 240 characters' % cid)
        ar = D(c.get('areas'))
        want = [a for a, _ in areas_of(cid, view)]
        stray = [a for a in ar if a not in want]
        need(not stray, 'chapters.%s.areas: %s isn\'t one of this chapter\'s areas (%s)' % (cid, ', '.join(stray), ', '.join(want)))
        for a in want:
            x = D(ar.get(a))
            at = 'chapters.%s.areas.%s' % (cid, a)
            evs = L(x.get('evidence'))
            kinds_ = [D(e).get('kind') for e in evs]
            ok_ev = (2 <= len(evs) <= 4 and all(D(e).get('kind') in EVIDENCE_KINDS and T(D(e).get('text')) and len(T(D(e).get('text'))) <= 200 for e in evs)
                     and all(DATED.search(T(D(e).get('when'))) for e in evs if D(e).get('kind') == 'moment'))
            need(ok_ev or (a == 'know' and not evs), '%s.evidence: two to four pieces (three is best), each {kind: messages, psyches, report or moment, text (at most 200 characters)}, a moment with its when (a month and year)' % at)
            if has_chat and a != 'know':
                need(any(k == 'messages' and re.search(r'\d', T(D(e).get('text'))) for k, e in zip(kinds_, evs)),
                     '%s.evidence: one messages piece with a real count from the conversation (a number, never "dozens" or "thousands")' % at)
            if a in PSY_AREAS:
                need('psyches' in kinds_, '%s.evidence: one psyches piece, the trait that bears on this, in words' % at)
            if a in PILLARS:
                need(0 < len(T(x.get('seen'))) <= 160 and x.get('verdict') in VERDICTS,
                     '%s: seen (how you both see it, one line, at most 160 characters, never whose) and verdict (matches, better or closer)' % at)
            nx = L(x.get('next'))
            need(0 < len(T(x.get('means'))) <= 320 and 1 <= len(nx) <= 3 and all(0 < len(T(D(y).get('do'))) <= 160 and 0 < len(T(D(y).get('because'))) <= 200 for y in nx),
                 '%s: means (one or two sentences, at most 320 characters) and next (one to three steps, each do, at most 160 characters, and because, at most 200: the evidence or trait it comes from)' % at)
            if a in STATUS_AREAS:
                need(0 < len(T(x.get('status'))) <= 32, '%s.status: a few words, at most 32 characters' % at)
        need(not c.get('detail') and not c.get('askEachOther') and not c.get('tryThis'),
             'chapters.%s: no detail, askEachOther or tryThis now: what it means and the next steps live in each area' % cid)
    A_ = lambda cid, a: D(D(D(ch.get(cid)).get('areas')).get(a))
    two_ = lambda x: T(D(x).get('a')) and T(D(x).get('b'))
    signs_ = lambda x: all(2 <= len(L(D(x).get(k))) <= 3 and all(T(y) and len(T(y)) <= 90 for y in L(D(x).get(k))) for k in ('a', 'b'))
    short_ = lambda xs, lo, hi: lo <= len(L(xs)) <= hi and all(T(x) and len(T(x)) <= 40 for x in L(xs))
    low_ = lambda xs: {T(x).lower() for x in L(xs) if T(x)}
    need(two_(A_('close', 'loves').get('care')), 'chapters.close.areas.loves.care: a and b, what makes each feel cared for')
    for a_, nm_, lo_ in (('interests', 'life', 1), ('values', 'future', 2)):
        grp = D(A_(nm_, a_).get('columns'))
        dup_ = sorted((low_(grp.get('a')) | low_(grp.get('b'))) & low_(grp.get('shared')))
        need(short_(grp.get('shared'), lo_, 5) and short_(grp.get('a'), 1, 3) and short_(grp.get('b'), 1, 3) and not dup_,
             'chapters.%s.areas.%s.columns: shared (%d to 5), a and b (1 to 3 each, more one\'s own, nothing also in shared), each under 40 characters' % (nm_, a_, lo_))
    topics = {x['topic'] for x in view['decisions']}
    if topics:
        dl = D(A_('future', 'decisions').get('lines'))
        need(all(T(dl.get(t)) for t in topics), 'chapters.future.areas.decisions.lines: a line per big decision (%s)' % ', '.join(sorted(topics)))
    need(signs_(A_('secure', 'security').get('signs')), 'chapters.secure.areas.security.signs: a and b, two or three early signs each that one of you feels unsure, under 90 characters')
    need(two_(A_('secure', 'attachment').get('reassure')), 'chapters.secure.areas.attachment.reassure: a and b, what reassures each')
    cy = A_('disagree', 'cycle')
    need(len(L(cy.get('steps'))) == 4 and all(T(x) and len(T(x)) <= 110 for x in L(cy.get('steps'))) and two_(cy.get('under')) and signs_(cy.get('signs'))
         and two_(cy.get('moves')) and T(cy.get('askYourself')),
         'chapters.disagree.areas.cycle: steps (four, naming who, at most 110 characters), under (a and b), signs (a and b, two or three each, under 90 characters), moves (a and b), askYourself')
    im = D(r.get('intermission'))
    need(T(im.get('title')) and 3 <= len(L(im.get('lines'))) <= 5 and all(T(x) and len(T(x)) <= 220 for x in L(im.get('lines'))), 'intermission: a title and three to five short, light lines')
    pn = D(r.get('plan'))
    w1 = D(pn.get('week1'))
    need(T(w1.get('title')) and len(L(w1.get('days'))) == 7 and len(L(pn.get('weeks'))) == 3
         and all(T(D(w).get('title')) and T(D(w).get('ask')) and T(D(w).get('doTogether')) and 3 <= len(L(D(D(w).get('conversation')).get('script'))) <= 5 for w in L(pn.get('weeks'))),
         'plan: week1 (title, seven days) and three weeks, each a title, a conversation (title, why, a script of 3 to 5 steps), ask and doTogether')
    need(T(r.get('caveats')), 'caveats: what this can\'t see, in a sentence or two')
    total = sum(len(t) for _, t in _texts(r))
    need(total >= 7000, 'the read is %d characters: at least 7,000 across its sections' % total)
    twice = _sentences(r)
    if twice:
        k, at = next(iter(twice.items()))
        problems.append('said twice (%s): "%s…" — say each thing once, in its one place' % (' and '.join(at[:2]), k[:60]))
    many = sum(len(YOU_TWO.findall(t)) for _, t in _texts(r))
    need(many <= 6, 'says "you two" %d times: say "you", your names, and "you both" for what you share; "you two" six times at most' % many)
    couple_ = [at for at, t in _texts(r) if THE_COUPLE.search(t)]
    need(not couple_, '%s says "the couple": say it to them, "you both" or by name' % ', '.join(couple_[:3]))
    them = [at for at, t in _texts(r) if THEM_TWO.search(t)]
    need(not them, '%s says "the two of them": say it to them, "you two" or by name' % ', '.join(them[:3]))
    _plain(problems, r, 2400)
    return [x for x in problems if x][:20]


LEVEL_OF = lambda n: 'high' if n >= 75 else 'moderate' if n >= 60 else 'low' if n >= 40 else 'very low'


def _conf(report):
    c = (report or {}).get('confidence') if isinstance((report or {}).get('confidence'), dict) else {}
    n = _score(c.get('score'))
    return n, [str(x) for x in (c.get('basedOn') or []) if isinstance(x, str)][:6]


def read_sources(profiles, view):
    """Exactly what the read was written from, and how far it can be trusted (README "Psyche Together, release 22"),
    worked out here rather than written: half the lower of the two Psyches' own confidence, as a Sync is held to the
    weaker card, and half the couple's own evidence, their conversation (up to 60: how much of it, and over how long)
    and their check-ins (40 when both answered every pillar question); at most 90, banded as the Psyche Report's."""
    people = []
    for r, nm in zip(('a', 'b'), view.get('names') or ['', '']):
        score, based = _conf((profiles.get(r) or {}).get('report'))
        people.append({'name': nm, 'confidence': score, 'level': LEVEL_OF(score) if score is not None else None, 'basedOn': based})
    chat = next((profiles[r]['chat'] for r in ('a', 'b') if (profiles.get(r) or {}).get('chat')), None) or {}
    sig = chat.get('signals') or {}
    sample = chat.get('sample') or []
    total = int(sig.get('messages') or 0)
    years = 0
    try:
        years = (datetime.strptime(sig['to'], '%Y-%m-%d') - datetime.strptime(sig['from'], '%Y-%m-%d')).days / 365.25
    except (KeyError, TypeError, ValueError):
        pass
    talk = 0 if not total else 25 if total < 500 else 40 if total < 5000 else 55
    talk += 5 if total and years >= 1 else 0
    asked = len([p for p in view.get('pillars') or {}])
    answered = {r: len((profiles.get(r) or {}).get('core') or {}) for r in ('a', 'b')}
    checkin = 40 if asked and all(answered[r] >= asked for r in ('a', 'b')) else 25
    own = talk + checkin
    weakest = min([p['confidence'] for p in people if p['confidence'] is not None] or [own])
    score = min(90, round((weakest + own) / 2))
    return {'people': people,
            'chat': {'messages': total, 'counts': chat.get('counts') or {}, 'source': chat.get('source'), 'from': sig.get('from'), 'to': sig.get('to'),
                     'sampleLines': len(sample), 'sampleChars': sum(len(x) for x in sample)} if total else None,
            'checkin': {'questions': asked, 'decisions': len(view.get('decisions') or [])},
            'confidence': {'score': score, 'level': LEVEL_OF(score), 'weakest': weakest, 'talk': talk, 'checkin': checkin}}


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
    box = {'read': r, 'view': view, 'at': int(time.time()), 'sources': read_sources(profiles, view),
           'psyches': {x: (profiles.get(x) or {}).get('psyche') or {} for x in ('a', 'b')}}
    if old:                   # written again (README "Psyche Together, release 22"): what moved since, and the four-week clock, stay
        box['at'] = max(box['at'], int(old.get('at') or 0) + 1)     # always later than the read it replaces, so each copy sees it's new
        box['firstAt'] = old.get('firstAt') or old.get('at')
        if old.get('rechecks'):
            box['rechecks'] = old['rechecks']
        box['rewrites'] = int(old.get('rewrites') or 0) + 1
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
    done_task('read')
    return dict(show(box) if s.get('forYou') else foryou_task(), saved=True)


def foryou_task(box=None):
    """This person's own For you, written right after they submit, from their answers, their full report and their
    partner's Psyche (README "Psyche Together, release 13"). Data only."""
    s = state()
    answers = s.get('answers') or {}
    mine = {}
    for it in items(s):
        a = answers.get(it['id'])
        if a and it['kind'] in ('core', 'deeper', 'overall'):
            mine[it['text'].replace('{p}', s.get('partner') or 'your partner')] = a.get('text') or a.get('label')
    k, got, profiles, _ = couple()
    _, theirs = mine_theirs(s, profiles) if not got.get('error') else ({}, {})
    flagged = is_gentle(s)
    return task_file({'write': 'foryou', 'yourAnswers': mine, 'yourPsyche': psyche_profile(psyche() or {}), 'yourReport': (psyche() or {}).get('report'),
                      'partner': theirs.get('psyche'), 'gentle': flagged, 'saveTo': 'work/together-foryou.json'})


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
    problems = check_foryou(fy, is_gentle(s))
    if problems:
        return {'saved': False, 'problems': problems}
    s['forYou'] = fy
    save_state(s)
    done_task('foryou')
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
    return {'waiting': True, 'setCheck': True, 'say': 'Your answers are in, and your own advice is ready for when your read arrives. I\'ll tell you here when %s has done theirs.' % (s.get('partner') or 'your partner'),
            'buttons': ['Is our read ready?'], 'asButtons': True}


# ---------------------------------------------------------------- four weeks on (README "Psyche Together, release 17")

def weeks_on(n):
    return int(round(RECHECK_DAYS * (n - 1) / 7)) or 4


def rounds_in(box):
    return [x for x in (box or {}).get('rechecks') or [] if isinstance(x, dict)]


def due_at(box):
    last = max([(box or {}).get('firstAt') or (box or {}).get('at') or 0] + [x.get('at') or 0 for x in rounds_in(box)])
    return last + RECHECK_DAYS * 86400


def next_round(box):
    return len(rounds_in(box)) + 2


def round_of(profile, n):
    return next((r for r in (profile or {}).get('rounds') or [] if isinstance(r, dict) and r.get('n') == n), None)


def again(box=None):
    """"Check in again": the same questions as before, in one widget, to see what moved."""
    s = state()
    if not s.get('role') or not s.get('sent'):
        return {'error': 'The check-in again comes once your Psyche Together has been read.'}
    if box is None:
        k, got, profiles, box = couple()
        if got.get('error'):
            return got
    if not box:
        return {'error': 'The check-in again comes once your Psyche Together has been read.'}
    n = next_round(box)
    r = s.get('round') if isinstance(s.get('round'), dict) else None
    if not r or r.get('n') != n:
        s['round'] = {'n': n, 'answers': {}, 'started': int(time.time())}
        save_state(s)
    elif r.get('sent'):
        return round_status(s, box)
    return widget_out(s, 'The same questions as last time, to see what has moved. About 2 minutes.')


def rewrite(note=None):
    """A fresh read from what is already here (README "Psyche Together, release 22"): both full reports, both people's
    answers and the conversation, with nothing deleted and nothing answered again. Their own profile goes again first,
    so a newer Psyche or a chat added since is in it; the partner's is as they sent it."""
    s = state()
    if not s.get('role') or not s.get('sent'):
        return {'error': 'Your read can be written again once you\'ve both answered and it\'s been written once.'}
    if s.get('role') == 'a' and kept_messages()[0]:
        count_chat(s)                     # the conversation chosen again, the latest way, from what's kept here
    got = put_profile(s, True)
    if got.get('error'):
        return got
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    if not box:
        return write_task(profiles) if all('core' in (profiles.get(r) or {}) for r in ('a', 'b')) else {'error': 'Your read hasn\'t been written yet.'}
    task = write_task(profiles)
    if note and task.get('task'):
        path = os.path.join(HERE, task['task'])
        try:
            d = json.load(open(path, encoding='utf-8'))
            d['feedback'] = [clean_typed(note)[:300]]
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(d, f, ensure_ascii=False)
            task['feedback'] = d['feedback']
        except (OSError, ValueError):
            pass
    return dict(task, rewrite=True, say='Writing your Psyche Together again, from both your Psyches and your conversation. About 4 minutes.')


def later():
    s = state()
    s['snoozeUntil'] = int(time.time() + NUDGE_DAYS * 86400)
    save_state(s)
    return {'say': 'I\'ll ask again in a few days.', 'buttons': ['Done'], 'asButtons': True}


def round_send(s):
    r = live_round(s)
    if not next_step(s).get('done'):
        return {'error': 'The check-in isn\'t finished yet.', 'next': next_step(s)}
    core, ov = levels_of(stage_of(s), r.get('answers') or {})
    if (r.get('answers') or {}).get('safety', {}).get('label') in SAFETY_FLAGGED:
        s['gentleLater'] = True
    s['rounds'] = [x for x in s.get('rounds') or [] if x.get('n') != r['n']] + [{'n': r['n'], 'at': int(time.time()), 'core': core, 'overall': ov}]
    got = put_profile(s, True)
    if got.get('error'):
        return got
    r['sent'] = int(time.time())
    save_state(s)
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    return dict(round_status(s, box, profiles), sent=True)


def round_status(s, box, profiles=None):
    """After this person's answers again are sent: what moved, once both are in."""
    n = (s.get('round') or {}).get('n')
    if any(x.get('n') == n for x in rounds_in(box)):
        return show(box)
    if profiles is None:
        k, got, profiles, _ = couple()
        if got.get('error'):
            return got
    if all(round_of(profiles.get(x), n) for x in ('a', 'b')):
        return recheck_task(profiles, box)
    return {'waiting': True, 'setCheck': True, 'buttons': ['Has my partner checked in?'], 'asButtons': True,
            'say': 'Your answers are in. When %s has done theirs too, you\'ll both see what has moved.' % (s.get('partner') or 'your partner')}


ORDER = {'Worth attention': 0, 'Steady': 1, 'Strong': 2}


def round_view(profiles, n):
    a, b = profiles['a'], profiles['b']
    ra, rb = round_of(a, n), round_of(b, n)
    return couple_view(dict(a, core=ra.get('core'), overall=ra.get('overall')), dict(b, core=rb.get('core'), overall=rb.get('overall')))


def moved(before, now):
    out = {}
    for pid, lv in (now.get('pillars') or {}).items():
        old = (before.get('pillars') or {}).get(pid)
        if old:
            out[pid] = 'up' if ORDER[lv] > ORDER[old] else 'down' if ORDER[lv] < ORDER[old] else 'same'
    return out


def recheck_task(profiles, box):
    """Data for Muse to write what moved: the couple view last time and now, the read's summary and plan. Data only."""
    n = next_round(box)
    before = (rounds_in(box)[-1].get('view') if rounds_in(box) else box.get('view')) or {}
    now = round_view(profiles, n)
    return {'write': 'recheck', 'round': n, 'weeks': weeks_on(n), 'names': now['names'], 'before': {'pillars': before.get('pillars'), 'overall': before.get('overall')},
            'now': {'pillars': now['pillars'], 'overall': now.get('overall')}, 'moved': moved(before, now), 'pillarNames': PILLARS,
            'summary': (box.get('read') or {}).get('summary'), 'plan': (box.get('read') or {}).get('plan'), 'saveTo': 'work/together-recheck.json'}    # small: no file needed


def check_recheck(x, mv):
    problems = []
    if not isinstance(x, dict):
        return ['What moved is not a JSON object.']
    T = lambda v: v.strip() if isinstance(v, str) else ''
    if not T(x.get('summary')) or len(T(x.get('summary')).split()) > 30:
        problems.append('summary: one line on the four weeks, under 30 words')
    want = sorted(p for p, d in mv.items() if d != 'same')
    ch = x.get('changes') if isinstance(x.get('changes'), list) else []
    got = sorted(c.get('pillar') for c in ch if isinstance(c, dict) and T(c.get('line')))
    if got != want:
        problems.append('changes: one line for each pillar that moved (%s), nothing else' % (', '.join(want) or 'none moved: leave it empty'))
    if not T(x.get('held')):
        problems.append('held: one or two sentences on what held steady')
    nx = x.get('next') if isinstance(x.get('next'), dict) else {}
    if not (T(nx.get('title')) and isinstance(nx.get('steps'), list) and len(nx['steps']) == 3 and all(T(v) for v in nx['steps'])):
        problems.append('next: a title and three small steps for the next four weeks')
    _plain(problems, x, 600)
    return problems[:10]


def save_recheck(path):
    try:
        with open(str(path).lstrip('@'), encoding='utf-8') as f:
            x = json.load(f)
    except (OSError, ValueError) as err:
        return {'saved': False, 'problems': ['Couldn\'t read %s: %s' % (path, err)]}
    x = x.get('answer', x) if isinstance(x, dict) else x
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    if not box:
        return {'saved': False, 'problems': ['There\'s no read to add to yet.']}
    n = next_round(box)
    if not all(round_of(profiles.get(r), n) for r in ('a', 'b')):
        return {'saved': False, 'problems': ['Both of you need to have checked in again first.']}
    task = recheck_task(profiles, box)
    problems = check_recheck(x, task['moved'])
    if problems:
        return {'saved': False, 'problems': problems}
    box['rechecks'] = rounds_in(box) + [{'n': n, 'at': int(time.time()), 'view': round_view(profiles, n), 'moved': task['moved'], 'note': x}]
    put = tool('together_put', {'e2e': {'read': seal(box, key_for('together-box', k['code']))}})
    if put.get('error'):
        return put
    try:
        os.remove(str(path).lstrip('@'))
    except OSError:
        pass
    return dict(show(box), saved=True, say='What has moved is at the top of your Psyche Together.')


def nudge(s, box, profiles, name):
    """The reminder's ask to check in again: when the partner already has, or four weeks are up; every few days at most."""
    now = time.time()
    n = next_round(box)
    theirs = round_of(mine_theirs(s, profiles)[1], n)
    if not theirs and now < due_at(box):
        return None
    if now < (s.get('snoozeUntil') or 0) or now - (s.get('nudgedAt') or 0) < NUDGE_DAYS * 86400:
        return None
    s['nudgedAt'] = int(now)
    save_state(s)
    say = ('%s has checked in again. Your turn: the same questions, about 2 minutes, to see what has moved.' % name if theirs else
           'It has been %d weeks since your Psyche Together. Time for the same questions again, to see what has moved? About 2 minutes.' % weeks_on(n))
    return {'say': say, 'buttons': ['Check in again', 'Not now'], 'asButtons': True}


def status():
    if not psyche() or not account():
        return needs_psyche()
    s = state()
    if s.get('role') and s.get('sent') and s.get('profileV') != PROFILE_V:
        try:
            put_profile(s, True)          # sent before this release: theirs again, with what a profile now carries
        except Exception:
            pass
    pending = read_first([PENDING]) or {}
    if not s.get('role') and pending.get('link'):
        return join(pending['link'])          # their Psyche is ready now: on to the invite that waited for it
    if not s.get('role') and pending.get('start'):
        try:
            os.remove(PENDING)
        except OSError:
            pass
        return start()                        # and for the one who asked to start one: the consent and the stage
    try:
        reread_instagram(s)
    except Exception:       # never in the way: the chat stays as it was
        pass
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
        return widget_out(s, 'Your questions, written from both your Psyches.')
    if not s.get('forYou'):
        return foryou_task()          # their own For you is written first, whatever the partner has done
    k, got, profiles, box = couple()
    if got.get('error'):
        return got
    if not box:
        return write_task(profiles) if all('core' in (profiles.get(r) or {}) for r in ('a', 'b')) else {
            'waiting': True, 'setCheck': True, 'say': '%s hasn\'t finished theirs yet.' % (s.get('partner') or 'Your partner'), 'buttons': ['Is our read ready?'], 'asButtons': True}
    if not s.get('forYou'):
        return foryou_task(box)
    if live_round(s):
        return widget_out(s, 'The same questions as last time, to see what has moved.')
    if (s.get('round') or {}).get('sent'):
        return round_status(s, box, profiles)
    return show(box)


def check():
    """For the "Psyche Together check" reminder (README "Psyche Together, release 13"): quiet until something is
    waiting, then the thing itself: the questions to write and show when the partner has joined, the read to
    write when both have answered, the page when it's ready; `done` once it has been shown."""
    s = state()
    if not s.get('role'):
        return {'done': True, 'quiet': True}
    try:
        reread_instagram(s)
        if s.get('sent') and s.get('profileV') != PROFILE_V:
            put_profile(s, True)
    except Exception:
        pass
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
        r = s.get('round') if isinstance(s.get('round'), dict) else None
        if r and r.get('sent'):
            if any(x.get('n') == r['n'] for x in rounds_in(box)):
                return dict(show(box), say='%s has checked in again too. Here\'s what has moved.' % name)
            if all(round_of(profiles.get(x), r['n']) for x in ('a', 'b')):
                return recheck_task(profiles, box)
            return {'quiet': True}
        if r:
            return {'quiet': True}
        if s.get('shown') != box.get('at'):
            again_ = bool(s.get('shown')) and box.get('rewrites')
            s['shown'] = box.get('at')
            save_state(s)
            return dict(show(box) if s.get('forYou') else foryou_task(),
                        say='Your Psyche Together has been written again, from the same answers and conversation. Here it is.' if again_ else '%s has finished. Here\'s your Psyche Together.' % name)
        return nudge(s, box, profiles, name) or {'quiet': True}
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

FONT = '-apple-system, BlinkMacSystemFont, "Segoe UI", Inter, Roboto, "Helvetica Neue", Arial, sans-serif'
# README "Psyche Together, release 19": the page in the Psyche Report's own design (its banner and mark, sticky
# nav, cards that open and close, gradient numbers), with one colour per chapter, used for its row on the map,
# its chip in the nav and its section, so it's always clear what belongs where.
COLOURS = {'support': '#c2366d', 'foryou': '#7b3fa0', 'since': '#2f7d5b', 'glance': '#7b3fa0', 'close': '#c2366d', 'secure': '#2f7d6b',
           'disagree': '#c2571a', 'moments': '#d1477a', 'life': '#2d5fa8', 'future': '#6a4bb5', 'plan': '#2f7d5b', 'how': '#5a4f66'}
LOGO = ('<svg class="mark" viewBox="0 0 140 140" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true" focusable="false">'
        '<path d="M12 70C12 56.745 37.967 46 70 46C102.033 46 128 56.745 128 70C128 83.255 102.033 94 70 94C37.967 94 12 83.255 12 70Z"/>'
        '<path d="M46 70C46 37.967 56.745 12 70 12C83.255 12 94 37.967 94 70C94 102.033 83.255 128 70 128C56.745 128 46 102.033 46 70Z"/>'
        '<path d="M41 19.771C52.479 13.143 74.768 30.259 90.785 58C106.801 85.741 110.479 113.602 99 120.229C87.521 126.857 65.232 109.741 49.215 82C33.199 54.259 29.521 26.398 41 19.771Z"/>'
        '<circle cx="70" cy="70" r="11" fill="currentColor" stroke="none"/></svg>')
CHEV = '<svg class="chev" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6"/></svg>'

CSS = '''
:root{color-scheme:light;--ink:#241a2e;--soft:#5a4f66;--mute:#6b6076;--line:#ece4f1;--sage:#2f7d5b;--amber:#9a5b12;--plum:#6e3796;--rose:#c2366d}
*{box-sizing:border-box;font-family:inherit}
html,body{margin:0;padding:0;background:#faf7fb}
body{font-family:__FONT__;color:var(--ink);font-size:15px;line-height:1.6;-webkit-text-size-adjust:100%;text-rendering:optimizeLegibility}
.wrap{max-width:760px;margin:0 auto;padding:0 14px 40px}
.banner{position:relative;overflow:hidden;margin:0 -14px;padding:26px 20px 26px;color:#fff;background:linear-gradient(135deg,#5b2a86 0%,#7b3fa0 45%,#c2366d 100%)}
.banner:before{content:"";position:absolute;right:-60px;top:-60px;width:220px;height:220px;border-radius:50%;background:radial-gradient(circle,rgba(255,230,190,.55),rgba(255,230,190,0) 70%)}
.banner .mark{position:absolute;top:-4.6rem;right:-3.8rem;width:240px;height:auto;color:#fff;opacity:.16;pointer-events:none}
.banner>*{position:relative}
.pair{display:flex;align-items:center;margin-bottom:12px}
.pair span{display:flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:50%;font-weight:800;font-size:18px;color:#fff;border:2.5px solid rgba(255,255,255,.9);box-shadow:0 6px 16px rgba(40,10,60,.3)}
.pair span:first-child{background:linear-gradient(135deg,#8f4fc0,#5b2a86)}.pair span:last-child{margin-left:-10px;background:linear-gradient(135deg,#e0558a,#a8295c)}
.facts{display:inline-block;padding:5px 12px;border-radius:999px;background:rgba(255,255,255,.18);border:1px solid rgba(255,255,255,.3);font-size:11.5px;font-weight:800;letter-spacing:.1em;text-transform:uppercase}
.banner h1{margin:10px 0 2px;font-size:30px;line-height:1.12;letter-spacing:-.02em}
.banner .lede{margin:8px 0 0;font-size:14.5px;line-height:1.5;opacity:.92;max-width:34em}
.banner .sub{margin-top:8px;font-size:12.5px;opacity:.75}
@media (max-width:480px){.banner .mark{top:-3.6rem;right:-3.4rem;width:165px;opacity:.14}.banner h1{font-size:26px}.facts{font-size:10px;letter-spacing:.06em}}
.banner.love{text-align:center;padding:24px 16px 26px;background:radial-gradient(90% 60% at 50% 38%,rgba(255,170,195,.55) 0%,rgba(255,170,195,0) 70%),linear-gradient(165deg,#2c0b33 0%,#6b1a55 40%,#b8305f 75%,#e0607a 100%)}
.banner.love:before{right:auto;left:50%;top:auto;bottom:-120px;margin-left:-160px;width:320px;height:240px;background:radial-gradient(circle,rgba(255,214,226,.35),rgba(255,214,226,0) 70%)}
.banner.love .mark{opacity:.1}
.fh{position:absolute;width:14px;height:14px;fill:#ffd1de;opacity:.0;animation:rise 9s ease-in infinite}
.fh.h1{left:8%;bottom:-10px;animation-delay:0s}.fh.h2{left:22%;bottom:-10px;width:10px;animation-delay:3s}.fh.h3{left:78%;bottom:-10px;animation-delay:1.5s}
.fh.h4{left:90%;bottom:-10px;width:11px;animation-delay:5s}.fh.h5{left:62%;bottom:-10px;width:9px;animation-delay:6.5s}.fh.h6{left:36%;bottom:-10px;width:12px;animation-delay:7.5s}
@keyframes rise{0%{transform:translateY(0) scale(.8);opacity:0}15%{opacity:.55}100%{transform:translateY(-330px) scale(1.1);opacity:0}}
.couple{position:relative;display:flex;justify-content:center;align-items:flex-start;gap:0;margin:18px 0 6px}
.lover{display:flex;flex-direction:column;align-items:center;width:150px}
.lover b{margin-top:12px;font-size:15px}.lover small{font-size:11.5px;opacity:.85}
.cardp{all:unset;cursor:zoom-in;display:block;width:124px;aspect-ratio:9/16;border-radius:14px;overflow:hidden;border:3px solid rgba(255,255,255,.95);box-shadow:0 16px 34px rgba(30,0,30,.45),0 0 0 6px rgba(255,190,210,.18);transition:transform .25s ease;-webkit-tap-highlight-color:transparent}
.cardp img{display:block;width:100%;height:100%;object-fit:cover}
.cardp.l{transform:rotate(-7deg) translateX(14px)}.cardp.r{transform:rotate(7deg) translateX(-14px)}
.cardp.l:hover{transform:rotate(-3deg) translateX(14px) scale(1.03)}.cardp.r:hover{transform:rotate(3deg) translateX(-14px) scale(1.03)}
.cardp.nopic{display:flex;align-items:center;justify-content:center;cursor:default;background:linear-gradient(160deg,#8f4fc0,#c2366d)}.cardp.nopic span{font-size:46px;font-weight:800;color:#fff}
.heart{position:absolute;left:50%;top:86px;z-index:2;width:58px;height:58px;margin-left:-29px;border-radius:50%;background:#fff;display:flex;align-items:center;justify-content:center;box-shadow:0 8px 24px rgba(120,10,60,.45),0 0 0 8px rgba(255,255,255,.22);animation:beat 1.8s ease-in-out infinite}
.heart svg{width:30px;height:30px}
@keyframes beat{0%,100%{transform:scale(1)}14%{transform:scale(1.14)}28%{transform:scale(1)}42%{transform:scale(1.1)}}
.banner.love h1{margin:16px 0 2px;font-size:32px}.banner.love h1 i{font-family:Georgia,"Times New Roman",serif;font-weight:400;color:#ffd1de;padding:0 2px}
.banner.love .lede{margin:8px auto 0}
@media (prefers-reduced-motion:reduce){.fh,.heart{animation:none}.fh{display:none}}
@media (min-width:640px){.lover{width:200px}.cardp{width:150px}.heart{top:104px}}
.viewer{position:fixed;inset:0;z-index:20;background:rgba(30,6,30,.9);display:flex;flex-direction:column;align-items:center;justify-content:center;padding:20px;cursor:zoom-out}
.viewer[hidden]{display:none}.viewer img{max-width:100%;max-height:calc(100% - 60px);border-radius:18px;box-shadow:0 20px 60px rgba(0,0,0,.5)}
.viewer span{margin-top:14px;padding:8px 16px;border-radius:999px;background:rgba(255,255,255,.14);color:#fff;font-size:14px;font-weight:600}
nav{position:sticky;top:0;z-index:5;margin:0 -14px 14px;padding:10px 14px;background:rgba(250,247,251,.94);-webkit-backdrop-filter:blur(8px);backdrop-filter:blur(8px);border-bottom:1px solid var(--line);display:flex;gap:6px;align-items:center;overflow-x:auto;scrollbar-width:none}
nav::-webkit-scrollbar{display:none}
nav a{flex:none;display:inline-flex;align-items:center;gap:6px;padding:6px 11px;border-radius:999px;border:1px solid #e2d8e9;background:#fff;color:var(--soft);font-size:13px;font-weight:650;text-decoration:none;white-space:nowrap}
nav a i{font-style:normal;font-weight:800;color:var(--c)}
nav a.on{background:var(--c);border-color:var(--c);color:#fff}nav a.on i{color:#fff}
nav button,.foldall{all:unset;box-sizing:border-box;cursor:pointer;-webkit-tap-highlight-color:transparent}
nav button{flex:none;margin-left:auto;padding:6px 12px;border-radius:999px;color:#7b3fa0;font-size:13px;font-weight:700;white-space:nowrap}
.part{background:#fff;border:1px solid #e6dcec;border-radius:20px;margin:0 0 14px;box-shadow:0 1px 2px rgba(36,26,46,.04),0 10px 30px rgba(36,26,46,.06);overflow:hidden;scroll-margin-top:var(--navh,62px)}
.part>.hd{all:unset;box-sizing:border-box;display:grid;grid-template-columns:auto 1fr auto;align-items:center;column-gap:14px;width:100%;padding:16px 18px;cursor:pointer;-webkit-tap-highlight-color:transparent}
.part>.hd:focus-visible{outline:2px solid var(--c);outline-offset:-2px;border-radius:18px}
.num{grid-row:1/span 2;min-width:34px;font-size:30px;font-weight:800;line-height:1;letter-spacing:-.03em;background:linear-gradient(135deg,var(--c),#d1477a);-webkit-background-clip:text;background-clip:text;color:transparent}
.ttl{font-size:19px;font-weight:750;letter-spacing:-.01em;line-height:1.25}
.tease{grid-column:2;font-size:11.5px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--c);opacity:.85}
.chev{grid-row:1/span 2;grid-column:3;width:24px;height:24px;color:var(--mute);transition:transform .2s}
.part.open .chev{transform:rotate(180deg)}.part.open{border-top:4px solid var(--c)}
.body{padding:2px 18px 18px;border-top:1px solid #f1eaf5}
.js .part:not(.open) .body{display:none}
h3{margin:24px 0 10px;font-size:12px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--c);display:flex;align-items:center;gap:8px}
h3:after{content:"";flex:1;height:1px;background:linear-gradient(90deg,#efe6f3,transparent)}
h4{margin:0 0 4px;font-size:16px;line-height:1.35}
p{margin:0 0 10px}
.soft{color:var(--soft);font-size:14px}
.lead{font-size:16.5px;font-weight:650;line-height:1.45}
.hero{margin:16px 0 4px;padding:18px;border-radius:18px;background:linear-gradient(135deg,#f3e9f8,#fdf0f6);border:1px solid #ead9f1}
.hero small,.lbl{display:block;font-size:11px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:var(--mute)}
.hero b{display:block;margin-top:4px;font-size:22px;line-height:1.3;letter-spacing:-.01em;background:linear-gradient(135deg,#7b3fa0,#d1477a);-webkit-background-clip:text;background-clip:text;color:transparent}
.lv{display:inline-flex;align-items:center;gap:5px;padding:3px 10px;border-radius:999px;font-size:12px;font-weight:750;white-space:nowrap}
.lv:before{content:"";flex:none;width:7px;height:7px;border-radius:50%;background:currentColor}
.tile .lv,.pv .lv{align-self:flex-start}
.tile:only-child{grid-column:1/-1}
.lv.Strong,.lv.Aligned,.lv.Happier-than-you-each-think,.lv.About-right{background:#e3f4ec;color:var(--sage)}
.lv.Steady,.lv.Not-decided-yet{background:#fdf1e2;color:var(--amber)}
.lv.Worth-attention,.lv.Worth-asking-each-other{background:#fbe7e5;color:#b3261e}.lv.Talk-about{background:#f2e9f8;color:var(--plum)}
.stats{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}
.stat{padding:14px;border-radius:16px;background:#fff;border:1px solid #ece2f2;box-shadow:0 4px 14px rgba(70,20,100,.06)}
.stat .lbl{margin-bottom:8px}
.sv{display:flex;align-items:flex-start;gap:7px;font-size:16.5px;font-weight:800;line-height:1.25}.sv:before{content:"";flex:none;width:10px;height:10px;margin-top:5px;border-radius:50%;background:currentColor}
.sv.Strong,.sv.Happier-than-you-each-think,.sv.About-right{color:var(--sage)}.sv.Steady{color:#2b5d8f}.sv.Worth-attention,.sv.Worth-asking-each-other{color:#b3261e}
.map{display:flex;flex-direction:column;gap:10px;margin:8px 0}
.mch{display:block;text-decoration:none;color:var(--ink);border:1px solid #ece2f2;border-left:5px solid var(--c);border-radius:16px;padding:12px 12px 12px 14px;background:linear-gradient(90deg,var(--t),#fff 60%)}
.mhd{display:flex;align-items:center;gap:10px;margin-bottom:10px}
.mhd .n{flex:none;display:flex;align-items:center;justify-content:center;width:30px;height:30px;border-radius:50%;background:var(--c);color:#fff;font-weight:800;font-size:13px}
.mhd b{display:block;font-size:15.5px;line-height:1.2}.mhd small{display:block;font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--c);opacity:.85}
.mhd em{margin-left:auto;font-style:normal;font-size:20px;color:var(--c);opacity:.6}
.tiles{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}
.tile{position:relative;display:flex;flex-direction:column;justify-content:space-between;gap:8px;padding:10px 11px;border-radius:12px;background:#fff;border:1px solid #efe6f4;min-height:74px}
.tile>b{font-size:13.5px;line-height:1.25;padding-right:22px}
.tile .sg{position:absolute;right:8px;top:8px;width:20px;height:20px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:800;background:#f4eff7;color:var(--soft)}
.key{display:flex;flex-wrap:wrap;gap:6px 14px;font-size:12px;color:var(--soft);margin:10px 0 0}
.key span{display:inline-flex;align-items:center;gap:5px}.key i{width:8px;height:8px;border-radius:50%;display:inline-block}
.truth{position:relative;padding:14px 16px;border-radius:16px;margin:10px 0;background:#fff;border:1px solid #ece2f2;border-left:5px solid var(--k)}
.truth .lbl{color:var(--k)}.truth h4{margin-top:4px}
.sci{margin:12px 0;padding:11px 14px;border-radius:14px;background:#f8f5fa;border:1px solid #eee5f3;font-size:13.5px;color:var(--soft)}
.sci .lbl{color:var(--c);margin-bottom:3px}.sci ul{margin:0;padding-left:18px}.sci li{margin:4px 0}
.pv{margin:14px 0;padding:14px;border-radius:16px;border:1px solid #efe6f4;background:#fdfbfe}
.pv .top{display:flex;align-items:center;justify-content:space-between;gap:8px;flex-wrap:wrap}
.pv .top b{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--c)}
.pv h4{margin:8px 0 10px;font-size:16.5px}
.sig{display:block;margin:-4px 0 8px;font-size:12.5px;font-weight:650;color:var(--soft)}
.three{display:grid;gap:8px}
.three div{display:grid;grid-template-columns:22px 1fr;gap:8px;font-size:14.5px}
.three i{width:22px;height:22px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-style:normal;font-size:11px;font-weight:800;color:#fff;background:var(--c);margin-top:1px}
.three small{display:block;font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}
.ev{list-style:none;margin:10px 0;padding:0;display:grid;gap:6px}
.ev li{padding:8px 12px;border-radius:12px;background:#f8f5fa;font-size:13.5px;color:var(--soft)}
.ev li b{display:inline-block;margin-right:6px;padding:1px 8px;border-radius:999px;background:#fff;border:1px solid #eadff0;color:var(--c);font-size:11.5px}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:12px 0}
@media (max-width:540px){.two{grid-template-columns:1fr}}
.two>div{padding:12px 14px;border-radius:14px;background:#faf6fc;border:1px solid #efe6f4}
.two>div>b{display:flex;align-items:center;gap:7px;font-size:13px;margin-bottom:4px}
.two>div>b span{flex:none;display:flex;align-items:center;justify-content:center;width:22px;height:22px;border-radius:50%;font-size:11px;color:#fff;background:#7b3fa0}
.two>div:last-child>b span{background:#c2366d}
.two p{margin:0;font-size:14.5px}
.callout{margin:12px 0;padding:12px 14px;border-radius:14px;font-size:14.5px}
.callout .lbl{margin-bottom:3px}
.callout.ask{background:#fdf6ee;border:1px solid #f4e3cc}.callout.ask .lbl{color:#9a5b12}
.callout.ask ul{margin:4px 0 0;padding-left:18px}.callout.ask li{margin:4px 0}
.callout.try{background:#eef8f2;border:1px solid #cfe9db}.callout.try .lbl{color:var(--sage)}
.callout.key2{background:#f5effa;border:1px solid #e7dbf0;font-weight:650}.callout.key2 ol{font-weight:400;margin:6px 0 0;padding-left:20px}.callout.key2 .lbl{color:var(--c)}
.cycle{display:grid;grid-template-columns:1fr 28px 1fr;grid-template-rows:auto 28px auto;gap:4px;align-items:center;margin:12px 0}
.cs{position:relative;padding:12px 10px 10px;border-radius:14px;background:#fff;border:1.5px solid #f1dccb;font-size:13.5px;min-height:70px;box-shadow:0 3px 10px rgba(194,87,26,.07)}
.cs i{position:absolute;top:-9px;left:10px;width:20px;height:20px;border-radius:50%;background:var(--c);color:#fff;font-style:normal;font-size:11px;font-weight:800;display:flex;align-items:center;justify-content:center}
.ca{text-align:center;color:var(--c);font-weight:800}.cc{grid-column:2;text-align:center;font-size:20px;color:var(--c)}
.item{padding:12px 0;border-top:1px solid #f2ecf5}
.big{display:flex;align-items:baseline;gap:10px;margin:10px 0}
.big b{font-size:44px;font-weight:800;line-height:1;letter-spacing:-.03em;background:linear-gradient(135deg,var(--c),#7b3fa0);-webkit-background-clip:text;background-clip:text;color:transparent}
.big span{color:var(--soft);font-size:14px}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:8px 0}td,th{text-align:left;padding:7px 4px;border-top:1px solid #f2ecf5}th{border-top:0;color:var(--c);font-size:12px;letter-spacing:.04em;text-transform:uppercase}td:not(:first-child),th:not(:first-child){text-align:right;font-variant-numeric:tabular-nums}
.chart{margin:10px 0}.chart svg{width:100%;height:auto;display:block}.chart figcaption{font-size:12px;color:var(--soft);margin-top:4px}
.rb{display:grid;grid-template-columns:76px 1fr 1fr;gap:6px;align-items:center;font-size:12.5px;margin:5px 0}
.rb div{position:relative;height:18px;background:#f1eef6;border-radius:9px;overflow:hidden}
.rb i{position:absolute;left:0;top:0;bottom:0;border-radius:9px}.rb i.a,.ka{background:#7b3fa0}.rb i.b,.kb{background:#c2366d}
.rb em{position:relative;font-style:normal;font-size:11px;font-weight:700;padding-left:6px;color:#fff;mix-blend-mode:difference}
.ka,.kb{display:inline-block;width:9px;height:9px;border-radius:3px}
.row{display:grid;grid-template-columns:1fr auto;gap:4px 10px;align-items:start;padding:11px 0;border-top:1px solid #f2ecf5}.row:first-of-type{border-top:0}
.row b{font-size:15px}.row p{grid-column:1/-1;margin:0;color:var(--soft);font-size:14px}
.part.mine{background:linear-gradient(180deg,#fbf6fe,#fff 40%)}
.private{display:inline-flex;align-items:center;gap:5px;margin-top:12px;padding:4px 10px;border-radius:999px;background:#f3e9f8;color:#6a3590;font-size:11.5px;font-weight:800;letter-spacing:.04em}
.fy{padding:12px 0;border-top:1px solid #f2ecf5}.fy:first-of-type{border-top:0}
.part.intermission{border-top:0;background:linear-gradient(135deg,#fff6ea 0%,#fdeef6 55%,#f4ecfd 100%);border-color:#f5d9e6}
.part.intermission .num{font-size:24px;background:none;-webkit-text-fill-color:initial;color:#d1477a}
.badge{display:inline-block;padding:3px 10px;border-radius:999px;background:#fff;color:#d1477a;font-size:10.5px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;box-shadow:0 2px 8px rgba(209,71,122,.15)}
.lines p{font-size:16px;font-weight:600;color:#3b2a49}
.funfacts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:14px 0}
.fact{padding:12px;border-radius:16px;background:rgba(255,255,255,.85);border:1px solid #f3dfe9;box-shadow:0 4px 14px rgba(209,71,122,.08)}
.fact em{display:block;font-style:normal;font-size:22px;line-height:1}.fact small{display:block;margin-top:6px;font-size:11.5px;font-weight:700;color:var(--soft)}.fact b{display:block;font-size:15.5px;line-height:1.25;margin-top:2px}
.timeline{list-style:none;padding:0;margin:8px 0 0 6px;border-left:2px solid #f0cfe0}
.timeline li{position:relative;padding:4px 0 12px 16px}
.timeline li:before{content:"";position:absolute;left:-7px;top:9px;width:12px;height:12px;border-radius:50%;background:linear-gradient(135deg,#7b3fa0,#d1477a);border:2px solid #fff}
.timeline b{display:block;font-size:12px;letter-spacing:.04em;text-transform:uppercase;color:#d1477a}.timeline em{display:block;font-size:11.5px;color:var(--soft);font-style:normal}
.weeks{position:relative;margin:12px 0 0;padding-left:44px}
.weeks:before{content:"";position:absolute;left:17px;top:8px;bottom:8px;width:2px;background:linear-gradient(#2f7d5b,#7b3fa0)}
.wk{position:relative;margin:0 0 14px;padding:14px;border-radius:16px;background:#fff;border:1px solid #e6efe9;box-shadow:0 4px 14px rgba(47,125,91,.06)}
.wk>i{position:absolute;left:-44px;top:12px;width:36px;height:36px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-style:normal;font-weight:800;font-size:12px;color:#fff;background:linear-gradient(135deg,#2f7d5b,#3f9a74);box-shadow:0 4px 10px rgba(47,125,91,.3)}
.wk small{font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:var(--sage)}
.wk h4{margin:2px 0 8px}
.wk ol.days{list-style:none;margin:0;padding:0;display:grid;gap:6px}
.days li{display:grid;grid-template-columns:24px 1fr;gap:8px;font-size:14px}
.days li b{width:24px;height:24px;border-radius:8px;display:flex;align-items:center;justify-content:center;background:#e3f4ec;color:var(--sage);font-size:12px}
.wk ol{margin:6px 0 10px;padding-left:20px;font-size:14px}
.mv{display:grid;grid-template-columns:1fr auto;gap:4px 10px;align-items:center;padding:10px 0;border-top:1px solid #e3efe8}
.mv b{font-size:14.5px}.mv span{font-size:12.5px;font-weight:750;white-space:nowrap}.mv span.up{color:var(--sage)}.mv span.down{color:var(--rose)}.mv span.same{color:var(--mute)}
.mv p{grid-column:1/-1;margin:0;font-size:14px;color:var(--soft)}
.support .body p{font-size:15px}
.glance-hero{margin:8px 0 6px;padding:10px 12px}.glance-hero small{font-size:10px}.glance-hero b{font-size:16.5px;margin-top:2px}
.ovl{display:flex;flex-direction:column;gap:4px;margin:8px 0 2px}.ovl>span{display:flex;align-items:center;justify-content:space-between;gap:8px}.ovl small{font-size:10.5px}.ovl .lv{font-size:12px;padding:2px 9px}.ovl>span{display:flex;align-items:center;gap:6px;flex-wrap:wrap}.ovl small{font-size:11px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--mute)}
.ovd{font-size:13px;line-height:1.45;color:var(--soft);margin:4px 0 2px}
.map{display:flex;flex-direction:column;gap:5px;margin:10px 0 6px}
.mr{display:grid;grid-template-columns:26px 1fr 12px;gap:9px;align-items:center;padding:6px 10px;border-radius:14px;background:#fff;border:1px solid #ece2f2;border-left:4px solid var(--c);text-decoration:none;color:var(--ink)}
.mr .n{width:26px;height:26px;border-radius:50%;background:var(--c);color:#fff;font-weight:800;font-size:12px;display:flex;align-items:center;justify-content:center}
.mr b{display:flex;align-items:center;gap:6px;flex-wrap:wrap;font-size:14.5px;line-height:1.2}.mr>i{font-style:normal;color:var(--c);font-size:18px}
.dots{display:flex;flex-wrap:wrap;gap:4px 10px;margin-top:4px}
.pd{display:inline-flex;align-items:center;gap:5px;font-size:12px;font-weight:650;color:var(--soft)}.pd:before{content:"";width:9px;height:9px;border-radius:50%;background:currentColor}
.pd em{font-style:normal;font-size:11px;color:var(--mute)}
.pd.Strong{color:var(--sage)}.pd.Steady{color:#2b5d8f}.pd.Worth-attention{color:#b3261e}
.tb{font-size:11px;font-weight:800;color:#fff;background:var(--k);border-radius:999px;padding:1px 7px}
.key{font-size:11.5px}.key .k{width:9px;height:9px;border-radius:50%}.k.Strong{background:var(--sage)}.k.Steady{background:#2b5d8f}.k.Worth-attention{background:#b3261e}
.take{margin:12px 0;padding:14px 16px;border-radius:16px;background:linear-gradient(135deg,#f3e9f8,#fdf0f6);border:1px solid #ead9f1}
.take .lbl{color:var(--c)}.take p{margin:4px 0 0;font-size:16.5px;font-weight:700;line-height:1.4}
.prow{margin:10px 0;padding:12px 14px;border-radius:14px;border:1px solid #efe6f4;background:#fdfbfe}
.prow .pt{display:flex;justify-content:space-between;align-items:center;gap:8px}.prow .pt b{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--c)}
.prow .phl{margin:6px 0;font-weight:700;font-size:15.5px}.prow p{margin:4px 0;font-size:14.5px}.prow p span{font-weight:700;color:var(--soft)}.prow .sig{font-size:12.5px;color:var(--mute)}
.evs{display:flex;flex-wrap:wrap;gap:6px;margin:8px 0 12px}.evp{display:inline-block;padding:5px 10px;border-radius:999px;background:#f6f1f9;border:1px solid #ece2f2;font-size:12.5px;color:var(--soft);line-height:1.35}
.evp b{color:var(--c);margin-right:6px;font-size:11.5px}
.minebox{margin:12px 0;padding:12px 14px;border-radius:14px;background:#fbf6fe;border:1.5px dashed #cdb6dd}.minebox .lbl{color:#6a3590}.minebox h4{margin:4px 0}.minebox .raise{font-size:14px;color:var(--soft)}
.diffs{padding-left:18px}.diffs li{margin:6px 0;font-size:14.5px}.diffs b{display:block}.solv{display:inline-block;font-size:11px;font-weight:800;color:#b57418;background:#fdf1e2;border-radius:999px;padding:0 7px;margin-right:4px}
details.sci{margin:14px 0 4px}details.sci summary{cursor:pointer;font-size:12px;font-weight:800;letter-spacing:.09em;text-transform:uppercase;color:var(--c)}details.sci ul{margin:6px 0 0}
.callout .q{margin:4px 0;font-weight:650}
.tts{display:flex;flex-direction:column;gap:3px;margin:8px 0 0}.ttl3{display:grid;grid-template-columns:104px 1fr;gap:6px;align-items:baseline;text-decoration:none;color:var(--ink);font-size:13.5px;font-weight:650;line-height:1.3}
.ttl3 span{font-size:10px;font-weight:800;letter-spacing:.04em;text-transform:uppercase;color:var(--k)}
.fchips{display:flex;flex-wrap:wrap;gap:6px;margin:4px 0 8px}.fchip{font-size:12.5px;font-weight:700;color:var(--c);background:#f5effa;border:1px solid #e7dbf0;border-radius:999px;padding:5px 11px;text-decoration:none}
.psy{margin:12px 0;padding:12px 14px;border-radius:16px;background:#fff;border:1px solid #ece2f2;box-shadow:0 3px 12px rgba(70,20,100,.05)}.psy .lbl{color:var(--c)}
.pkey{display:flex;gap:14px;flex-wrap:wrap;font-size:12.5px;font-weight:700;margin:6px 0 8px}.pkey i{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:5px}
.pkey i.a,.dr i.a{background:#7b3fa0}.pkey i.b,.dr i.b{background:#d1477a}
.dr{display:grid;grid-template-columns:118px 1fr 58px;gap:8px;align-items:center;font-size:13px;margin:6px 0}.dr>span{font-weight:650}.dr em{font-style:normal;text-align:right;font-size:12px}
b.a{color:#7b3fa0}b.b{color:#d1477a}
.tr{position:relative;height:20px}.tr:before{content:"";position:absolute;left:0;right:0;top:9px;height:2px;border-radius:2px;background:#eee6f2}
.tr .gap{position:absolute;top:8px;height:4px;border-radius:4px;background:#e2cfe9}.tr i{position:absolute;top:3px;width:14px;height:14px;margin-left:-7px;border-radius:50%;border:2px solid #fff;box-shadow:0 1px 3px rgba(0,0,0,.18)}
.mx{margin:8px 0}.mx .q{display:block;font-size:12.5px;font-weight:650;color:var(--soft);margin-bottom:2px}
.axis{display:grid;grid-template-columns:18px 1fr 18px;gap:8px;align-items:center}.axis>b{font-size:15px;font-weight:800;color:var(--ink);text-align:center}
.mx em{display:block;font-style:normal;font-size:11.5px;color:var(--mute);margin-top:1px}
.ml{display:grid;grid-template-columns:1fr auto auto 64px;gap:8px;align-items:center;font-size:13px;margin:6px 0}.ml>span{color:var(--soft);font-weight:650}.ml em{font-style:normal;font-size:11.5px;color:var(--mute);text-align:right}
.pair2{display:grid;grid-template-columns:1fr 1fr;gap:8px;margin:8px 0}.pair2>div{padding:9px 10px;border-radius:12px;background:#faf6fc;display:flex;flex-direction:column;gap:3px;font-size:13px}
@media(max-width:420px){.pair2{grid-template-columns:1fr}}
.radar{display:block;width:100%;max-width:360px;margin:0 auto}.radar text{font-size:8.5px;fill:#5a4f66}
.pline{margin:10px 0 0;font-size:14.5px;font-weight:600;color:#3b2a49}
.alike{display:grid;grid-template-columns:1fr 1.2fr 1fr;gap:6px;margin:8px 0 10px;align-items:stretch}
.alike>div{display:flex;flex-direction:column;gap:5px;padding:10px 8px;border-radius:14px;background:#faf6fc;border:1px solid #efe6f4}
.alike>div.both{background:linear-gradient(160deg,#f3e9f8,#fdf0f6);border-color:#e3cdee}
.alike small{font-size:10.5px;font-weight:800;letter-spacing:.06em;text-transform:uppercase;color:var(--c);text-align:center}
.alike span{font-size:12.5px;line-height:1.3;padding:5px 7px;border-radius:10px;background:#fff;border:1px solid #eee3f3;text-align:center}
.alike .both span{font-weight:700}
footer{margin-top:22px;text-align:center;color:var(--mute);font-size:12.5px;line-height:1.6}
.saycopy{margin-top:14px;padding:12px 14px;border-radius:14px;background:#f4edf8;border:1px solid var(--line)}.saycopy p{margin:0 0 8px;font-size:13.5px;color:var(--soft)}
.sayrow{display:flex;gap:8px;align-items:center;flex-wrap:wrap}.sayrow code{flex:1 1 12em;min-width:0;padding:8px 10px;border-radius:8px;background:#fff;border:1px solid var(--line);font:600 14px/1.35 inherit;color:var(--ink);user-select:all;-webkit-user-select:all}
.sayrow button{flex:none;padding:8px 14px;border-radius:999px;border:0;background:#7b3fa0;color:#fff;font:700 13.5px/1 inherit;cursor:pointer}
.conf2{margin:4px 0 14px}.conf2 .bar{height:10px;border-radius:6px;background:#f1eaf5;overflow:hidden;margin:2px 0 10px}.conf2 .bar i{display:block;height:100%;background:linear-gradient(90deg,#7b3fa0,#d1477a)}
.cb{display:grid;grid-template-columns:auto 1fr 44px;gap:7px 10px;align-items:center;font-size:13px}.cb>span{font-weight:650}.cb>div{height:8px;border-radius:5px;background:#f1eaf5;overflow:hidden}.cb>div i{display:block;height:100%}.cb>b{text-align:right;font-size:12.5px}
.srcs{padding-left:18px;font-size:14px}.srcs li{margin:6px 0}
.foldall{display:block;margin:6px auto 0;padding:8px 16px;border-radius:999px;color:#7b3fa0;font-size:13px;font-weight:700}
/* Calm, as the Psyche Report (README "Psyche Together, release 32"): one soft box style, colour only in small labels */
.lv{font-weight:650}.lv:before{display:none}
.lv.Strong,.lv.Aligned,.lv.Happier-than-you-each-think,.lv.About-right{background:#eef6f1;color:#2f6f53}
.lv.Steady{background:#eaf1f9;color:#2b5d8f}.lv.Not-decided-yet{background:#f3f0f5;color:#5a4f66}
.lv.Worth-attention,.lv.Worth-asking-each-other,.lv.Talk-about{background:#fbeeed;color:#a8322a}
.lw{font-weight:650}.lw.Strong,.lw.Happier-than-you-each-think,.lw.About-right{color:#2f6f53}.lw.Steady{color:#2b5d8f}.lw.Aligned{color:#2f6f53}.lw.Talk-about{color:#a8322a}.lw.Worth-attention,.lw.Worth-asking-each-other{color:#a8322a}
.callout,.callout.ask,.callout.try,.callout.key2,.truth,.take,.minebox,.psy,.two>div,.pair2>div{background:#faf7fb;border:1px solid #eee6f3;box-shadow:none}
.callout .lbl,.callout.ask .lbl,.callout.try .lbl,.callout.key2 .lbl,.truth .lbl,.take .lbl,.psy .lbl{color:var(--c)}
.callout.key2{font-weight:500}.minebox{border-style:dashed}
.truth{border-left:1px solid #eee6f3;background:linear-gradient(135deg,#f6f0fa,#fcf5f8)}.truth .th{display:flex;align-items:center;gap:8px}
.truth .th .n{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;color:#fff;background:linear-gradient(135deg,#7b3fa0,#d1477a)}
.truth .th .lbl{color:var(--mute)}
.take{background:linear-gradient(135deg,#f6f0fa,#fcf5f8)}.take p{font-size:16px;font-weight:650}
.prow{background:#fff;border:0;border-bottom:1px solid #f1ebf5;border-radius:0;padding:12px 0;margin:0}
.evp{background:#fff}.two>div>b span{background:#7b3fa0}.two>div:last-child>b span{background:#a3487a}
.pat{display:grid;grid-template-columns:34px 1fr;gap:12px;padding:12px 0;border-bottom:1px solid #f2ecf5;text-decoration:none;color:var(--ink)}
.pat .n{width:30px;height:30px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:13px;color:#fff;background:linear-gradient(135deg,#7b3fa0,#d1477a)}
.pat b{display:block;font-size:15.5px;line-height:1.3}.pat .soft{display:block;font-size:12.5px;margin-top:1px}.pat .pl{display:block;font-size:14px;color:var(--ink);margin-top:4px;line-height:1.45}
.it2{display:grid;grid-template-columns:28px 1fr 12px;gap:10px;align-items:start;padding:10px 0;border-bottom:1px solid #f2ecf5;text-decoration:none;color:var(--ink)}
.it2 .n2{font-weight:800;font-size:15px;line-height:1.3;background:linear-gradient(135deg,#7b3fa0,#d1477a);-webkit-background-clip:text;background-clip:text;color:transparent}
.it2 b{display:block;font-size:15px}.areas2{display:block;font-size:13.5px;color:var(--soft);margin-top:2px}.it2>i{font-style:normal;color:var(--mute);font-size:18px}
.sat{font-size:14px;color:var(--soft)}.foot2{margin:12px 0 2px;font-size:13px;color:var(--soft)}.foot2 a{color:#7b3fa0;text-decoration:none;font-weight:650}
.glance-hero b{font-size:19px}
.tz{grid-column:2;display:block;font-size:13px;line-height:1.4;color:var(--soft);margin-top:4px}.part.open .tz{display:none}
.signs ul{margin:4px 0 0;padding-left:18px;font-size:14px}.signs li{margin:3px 0}
.fb{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin:16px 0 0;font-size:13px;color:var(--mute)}.fb>button{all:unset;cursor:pointer;font-size:17px;padding:2px 6px;border-radius:8px}.fb>button.on{background:#f3e9f8}
.fbx{flex-basis:100%}.fbx textarea{width:100%;padding:9px 10px;border:1px solid var(--line);border-radius:10px;font:inherit;font-size:14px;resize:none;margin:6px 0}.fbok{flex-basis:100%;margin:2px 0 0}
@media print{nav,.foldall{display:none}.js .part:not(.open) .body{display:block}}
.area{margin:12px 0;padding:14px 16px;border-radius:16px;background:#fff;border:1px solid #eee6f3}
.area .at{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}.area .at b{font-size:12px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--c)}.area .at .lv{margin-left:auto}.area .at .lv+.lv{margin-left:6px}
.area .am{margin:8px 0 6px;font-weight:700;font-size:15.5px;line-height:1.4}.area>p{margin:4px 0;font-size:14.5px}.area>p span{font-weight:700;color:var(--soft)}.area .sig{font-size:12.5px;color:var(--mute)}
.area .psy{margin:10px 0}.area .ev{margin-top:10px}
.lv.Info{background:#f3ecf8;color:#7b3fa0}.lw.Info{color:#7b3fa0}
.tk2{display:block;font-size:13px;color:var(--soft);margin-top:4px;line-height:1.4}
.std{padding:14px 0;border-bottom:1px solid #f2ecf5}.std .th{display:flex;align-items:center;gap:8px}.std .th .n{width:24px;height:24px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-weight:800;font-size:12px;color:#fff;background:linear-gradient(135deg,#7b3fa0,#d1477a)}
.std .th .lbl{color:var(--mute)}.std h4{margin:6px 0 4px;font-size:16px}.std p{font-size:14.5px}.std .more{display:inline-block;margin-top:8px;font-size:13px;font-weight:650;color:#7b3fa0;text-decoration:none}
.st{margin:12px 0 0}.st .sl{display:block;font-size:11px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:var(--mute);margin-bottom:4px}.st>p{margin:4px 0;font-size:14.5px}
.evd{list-style:none;margin:4px 0;padding:0}.evd li{display:grid;grid-template-columns:24px 1fr;gap:6px;margin:6px 0;font-size:14.5px;line-height:1.45}.evd i{font-style:normal}
.st.means{border-top:1px solid #f1ebf5;padding-top:10px}.vd{display:inline-block;padding:2px 9px;border-radius:999px;font-size:12px;font-weight:700;background:#f3ecf8;color:#7b3fa0}
.vd.matches{background:#eaf1f9;color:#2b5d8f}.vd.better{background:#eef6f1;color:#2f6f53}.vd.closer{background:#fbeeed;color:#a8322a}
.nx{margin:4px 0;padding-left:18px}.nx li{margin:6px 0;font-size:14.5px}.nx li b{display:block}.nx li span{display:block;font-size:13px;color:var(--soft)}
.psyd{margin-top:16px;border-top:1px solid #f2ecf5;padding-top:10px}.psyd summary{cursor:pointer;font-weight:750;font-size:14px;color:#7b3fa0}.psyd summary .soft{font-weight:500;font-size:12.5px;margin-left:6px}
.map .ws{display:block;margin:10px 0;padding:14px;border:1px solid #eee6f3;border-radius:16px;background:#fff;text-decoration:none;color:var(--ink)}
.ws .wh{display:flex;align-items:center;gap:10px}.ws .wh b{flex:1;font-size:16px}.ws .wh i{font-style:normal;color:var(--mute);font-size:18px}.ws .n2{font-size:15px}
.tiles{display:grid;grid-template-columns:repeat(auto-fill,minmax(130px,1fr));gap:8px;margin:10px 0 6px}
.tl{display:flex;flex-direction:column;gap:2px;padding:9px 11px;border-radius:12px;background:#f6f2f9;border-left:0}.tl small{font-size:11px;font-weight:700;letter-spacing:.04em;text-transform:uppercase;color:var(--mute)}
.tl b{font-size:14.5px;font-weight:750;color:#5a4f66}.tl b:before{content:"";display:inline-block;width:7px;height:7px;border-radius:50%;background:currentColor;margin-right:6px;vertical-align:middle}
.tl.Strong,.tl.Aligned{background:#eef6f1}.tl.Strong b,.tl.Aligned b{color:#2f6f53}.tl.Steady{background:#eaf1f9}.tl.Steady b{color:#2b5d8f}
.tl.Worth-attention,.tl.Talk-about{background:#fbeeed}.tl.Worth-attention b,.tl.Talk-about b{color:#a8322a}.tl.Info{background:#f3ecf8}.tl.Info b{color:#7b3fa0}
.ws .tk2{margin:6px 0 0;font-size:13.5px;color:var(--soft)}
'''.replace('__FONT__', FONT)

JS = r'''
(function(){
document.documentElement.classList.add('js');
var parts=[].slice.call(document.querySelectorAll('.part')),chips=[].slice.call(document.querySelectorAll('nav a')),bar=document.querySelector('nav');
function navh(){if(bar)document.documentElement.style.setProperty('--navh',(bar.offsetHeight+10)+'px');}navh();window.addEventListener('resize',navh);
function mark(){chips.forEach(function(c){var p=document.querySelector(c.getAttribute('href'));c.classList.toggle('on',!!(p&&p.classList.contains('open')));});}
function set(p,open){p.classList.toggle('open',open);var b=p.querySelector('.hd');if(b)b.setAttribute('aria-expanded',open?'true':'false');mark();}
function go(el){requestAnimationFrame(function(){requestAnimationFrame(function(){try{el.scrollIntoView({block:'start',behavior:'instant'});}catch(e){el.scrollIntoView(true);}});});}
// One section open at a time, as the Psyche Report: opening one closes the rest, the intermission too.
function only(p){parts.forEach(function(q){if(q!==p)set(q,false);});set(p,true);go(p);}
parts.forEach(function(p){var b=p.querySelector('.hd');if(b)b.addEventListener('click',function(){if(p.classList.contains('open'))set(p,false);else only(p);});});
function open(id){var p=document.querySelector(id);if(p)only(p);}
chips.forEach(function(c){c.addEventListener('click',function(e){e.preventDefault();open(c.getAttribute('href'));});});
[].slice.call(document.querySelectorAll('.mr,.it2,a.pat,a.more,.foot2 a')).forEach(function(a){a.addEventListener('click',function(e){e.preventDefault();open(a.getAttribute('href'));});});
var fold=[].slice.call(document.querySelectorAll('[data-fold]'));
function label(){var any=parts.some(function(p){return p.classList.contains('open');});fold.forEach(function(b){b.hidden=!any;});}
fold.forEach(function(b){b.textContent='Close all ▲';b.addEventListener('click',function(){parts.forEach(function(p){set(p,false);});label();go(document.getElementById('top'));});});
[].slice.call(document.querySelectorAll('.mr')).forEach(function(a){a.addEventListener('click',label);});
chips.forEach(function(c){c.addEventListener('click',label);});
parts.forEach(function(p){var b=p.querySelector('.hd');if(b)b.addEventListener('click',label);});
mark();label();
[].slice.call(document.querySelectorAll('[data-copy]')).forEach(function(b){b.addEventListener('click',function(){var t=b.getAttribute('data-copy'),done=function(){b.textContent='Copied ✓';setTimeout(function(){b.textContent='Copy';},1800);};
 try{navigator.clipboard.writeText(t).then(done,function(){sel(b);});}catch(e){sel(b);}});});
function sel(b){var c=b.parentNode.querySelector('code');if(!c)return;var r=document.createRange();r.selectNodeContents(c);var s=window.getSelection();s.removeAllRanges();s.addRange(r);b.textContent='Selected: copy it';}
[].slice.call(document.querySelectorAll('.fb')).forEach(function(f){var x=f.querySelector('.fbx'),ok=f.querySelector('.fbok'),t=f.querySelector('textarea'),code=f.querySelector('code'),cp=f.querySelector('[data-copy]');
 function line(){var v=(t.value||'').trim();var s='Write our read again. In '+f.getAttribute('data-ch')+', this felt off'+(v?': '+v:'.');code.textContent=s;cp.setAttribute('data-copy',s);}
 [].slice.call(f.querySelectorAll('[data-fb]')).forEach(function(b){b.addEventListener('click',function(){[].slice.call(f.querySelectorAll('[data-fb]')).forEach(function(o){o.classList.toggle('on',o===b);});
  var up=b.getAttribute('data-fb')==='up';x.hidden=up;ok.hidden=!up;if(!up){line();t.focus();}});});
 t.addEventListener('input',line);});
var vw=document.getElementById('viewer');
[].slice.call(document.querySelectorAll('[data-view]')).forEach(function(b){b.addEventListener('click',function(){if(!vw)return;vw.querySelector('img').src=b.querySelector('img').src;vw.hidden=false;});});
if(vw){vw.addEventListener('click',function(){vw.hidden=true;});document.addEventListener('keydown',function(e){if(e.key==='Escape')vw.hidden=true;});}
})();
'''


def _paras(t):
    return ''.join('<p>%s</p>' % _e(x.strip()) for x in str(t or '').split('\n') if x.strip())


def _ev(xs):
    xs = [x for x in (xs or []) if isinstance(x, str) and x.strip()]
    return ('<ul class="ev">' + ''.join('<li>%s</li>' % _e(x) for x in xs) + '</ul>') if xs else ''


def _research(key):
    return ('<div class="sci"><span class="lbl">What the research says</span>%s</div>' % _e(RESEARCH[key])) if key in RESEARCH else ''


def _lv(level):
    return '<span class="lv %s">%s</span>' % (_e(str(level).replace(' ', '-')), _e(level)) if level else ''


def _sv(level):
    return '<span class="sv %s">%s</span>' % (_e(str(level).replace(' ', '-')), _e(level)) if level else ''


def _science(keys, folded=False):
    """A chapter's research lines in one box; folded at the end of a chapter, opened with a tap."""
    lines = [RESEARCH[k] for k in keys if k in RESEARCH]
    if folded and lines:
        return '<details class="sci"><summary>What the research says</summary><ul>%s</ul></details>' % ''.join('<li>%s</li>' % _e(x) for x in lines)
    if len(lines) < 2:
        return ''.join(_research(k) for k in keys)
    return '<div class="sci"><span class="lbl">What the research says</span><ul>%s</ul></div>' % ''.join('<li>%s</li>' % _e(x) for x in lines)


def _pills(xs):
    """Dated moments as small pills, where they belong (README "Psyche Together, release 24")."""
    xs = [x for x in (xs or []) if isinstance(x, dict) and x.get('what')]
    return ('<div class="evs">%s</div>' % ''.join('<span class="evp"><b>%s</b>%s</span>' % (_e(x.get('when')), _e(x.get('what'))) for x in xs)) if xs else ''


def _initial(name):
    return _e((str(name or '?').strip() or '?')[0].upper())


def _months_svg(months):
    """Messages by month, as a small bar chart drawn here (no library), newest on the right."""
    if not months:
        return ''
    unit = 'month'
    if len(months) > 36:                     # a long conversation: by year, so all of it fits
        years = {}
        for m, n in months:
            years[m[:4]] = years.get(m[:4], 0) + n
        months, unit = sorted(years.items()), 'year'
    top, w = max(n for _, n in months) or 1, 300
    bw = w / len(months)
    bars = ''.join('<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" fill="url(#mg)"><title>%s: %d</title></rect>'
                   % (i * bw + 1, 60 - 56 * n / top, max(1.5, bw - 2), 56 * n / top, _e(m), n) for i, (m, n) in enumerate(months))
    return ('<figure class="chart"><svg viewBox="0 0 %d 62" role="img" aria-label="Messages by month"><defs><linearGradient id="mg" x1="0" y1="0" x2="0" y2="1">'
            '<stop offset="0" stop-color="#d1477a"/><stop offset="1" stop-color="#7b3fa0"/></linearGradient></defs>%s</svg><figcaption>Messages by %s, %s to %s</figcaption></figure>'
            % (w, bars, unit, _e(months[0][0]), _e(months[-1][0])))


def _talk_panel(box, names):
    sig = (box.get('chat') or {}).get('signals') or {}
    if not (sig.get('you') and sig.get('partner')):
        return ''
    who = box.get('chatOf') or names
    you, them = sig['you'], sig['partner']
    v = lambda d, k, suf='': ('%s%s' % (d.get(k), suf)) if d.get(k) is not None else '–'
    pos = lambda d: '%s : %s' % (d.get('positive', 0), d.get('negative', 0))
    rep_ = lambda d: '–' if d.get('medianReplyMinutes') is None else 'under a minute' if d['medianReplyMinutes'] < 1 else '%s min' % d['medianReplyMinutes']
    rows = [('Messages', v(you, 'messages'), v(them, 'messages')), ('Conversations started', v(you, 'starts'), v(them, 'starts')),
            ('Typical reply', rep_(you), rep_(them)), ('Replies within 5 minutes', v(you, 'replyWithin5', '%'), v(them, 'replyWithin5', '%')), ('Questions asked', v(you, 'questions'), v(them, 'questions')),
            ('Thanks', v(you, 'thanks'), v(them, 'thanks')), ('Sorry and repair', v(you, 'sorry'), v(them, 'sorry')),
            ('Warm words : hard words', pos(you), pos(them)), ('"We" per 100 words', v(you, 'we'), v(them, 'we')), ('"I" and "you" per 100 words', v(you, 'iYou'), v(them, 'iYou'))]
    table = '<table><tr><th></th><th>%s</th><th>%s</th></tr>%s</table>' % (_e(who[0]), _e(who[1]), ''.join('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % tuple(_e(c) for c in r) for r in rows))
    match = ('<div class="big"><b>%d</b><span>out of 100: how closely your writing styles match</span></div>%s' % (round(100 * sig['styleMatch']), _research('styleMatch'))
             if sig.get('styleMatch') is not None else '')
    return ('<h3>You both, in numbers</h3>' + match + table
            + '<p class="soft">%s messages from %s to %s, about %s a month, %s.</p>' % (_e(sig.get('messages')), _e(sig.get('from')), _e(sig.get('to')), _e(sig.get('perMonth')), _e(sig.get('trend')))
            + _research('we'))


MONTHS = {m: i + 1 for i, m in enumerate(['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'])}


def _when_key(w):
    y = re.search(r'(19|20)\d{2}', str(w or ''))
    m = re.search(r'(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)', str(w or '').lower())
    mm = re.search(r'\b(19|20)\d{2}-(\d{2})', str(w or ''))
    return (int(y.group(0)) if y else 0, int(mm.group(2)) if mm else MONTHS.get(m.group(1), 0) if m else 0)


def _moments(xs, tag=''):
    xs = [x for x in (xs or []) if isinstance(x, dict) and x.get('what')]
    return ('<ul class="ev">' + ''.join('<li><b>%s</b>%s</li>' % (_e(x.get('when')), _e(x.get('what'))) for x in xs) + '</ul>') if xs else ''


SIGNAL = {'more': ('↑', 'Your messages show more than you see'), 'less': ('↓', 'Your messages show less than you see'),
          'same': ('=', 'Your messages match how you see it'), 'none': ('', '')}


def _views(r, view, pids):
    """A chapter's pillars, each as three views: how you see it, what your messages show, and why."""
    out = ''
    for pid in pids:
        if pid not in (view.get('pillars') or {}):
            continue
        lv, x = view['pillars'][pid], (r.get('pillars') or {}).get(pid) or {}
        arrow, said = SIGNAL.get(x.get('signal'), ('', ''))
        rows = [('1', 'How you see it', x.get('seeIt'))]
        if x.get('messages'):
            rows.append(('2', 'What your messages show', x.get('messages')))
        rows.append((str(len(rows) + 1), 'Why, through your Psyches', x.get('psyches')))
        out += ('<div class="pv"><div class="top"><b>%s</b>%s</div><h4>%s</h4>%s<div class="three">%s</div></div>'
                % (_e(PILLARS.get(pid, pid)), _lv(lv), _e(x.get('headline')), ('<span class="sig">%s %s</span>' % (arrow, _e(said))) if arrow else '',
                   ''.join('<div><i>%s</i><span><small>%s</small>%s</span></div>' % (n, _e(t), _e(v)) for n, t, v in rows)))
    return out


def _cycle(cy, names):
    st = [str(x) for x in (cy.get('steps') or [])][:4] + [''] * 4
    box = lambda i: '<div class="cs"><i>%d</i>%s</div>' % (i + 1, _e(st[i]))
    return ('<div class="cycle">%s<div class="ca">→</div>%s<div class="ca">↑</div><div class="cc">↻</div><div class="ca">↓</div>%s<div class="ca">←</div>%s</div>'
            % (box(0), box(1), box(3), box(2)))


def _rhythm(sig, who):
    you, them = sig.get('you') or {}, sig.get('partner') or {}
    if not (you.get('day') and them.get('day')):
        return ''
    rows = ''.join('<div class="rb"><span>%s</span><div><i class="a" style="width:%s%%"></i><em>%s%%</em></div><div><i class="b" style="width:%s%%"></i><em>%s%%</em></div></div>'
                   % (lbl, you['day'].get(k, 0), you['day'].get(k, 0), them['day'].get(k, 0), them['day'].get(k, 0))
                   for k, lbl in (('morning', 'Morning'), ('afternoon', 'Afternoon'), ('evening', 'Evening'), ('late', 'Late night')))
    return ('<h3>Your day, side by side</h3><div class="rhythm"><p class="soft">When each of you writes: <span class="ka"></span> %s · <span class="kb"></span> %s.</p>%s</div>'
            % (_e(who[0]), _e(who[1]), rows))


# Your two Psyches, woven into the chapters (README "Psyche Together, release 26"): what a Sync compares, each where it
# explains something, drawn here from both cards so no number drifts, with Muse's line on what it means for you two.
TRAIT_LABEL = {'openness': 'Openness', 'conscientiousness': 'Conscientiousness', 'extraversion': 'Extraversion', 'agreeableness': 'Agreeableness', 'neuroticism': 'Sensitivity'}
MOTIVE_LABEL = [('self-direction', 'Self-direction'), ('stimulation', 'Stimulation'), ('hedonism', 'Enjoyment'), ('achievement', 'Achievement'), ('power', 'Power'),
                ('security', 'Security'), ('conformity', 'Conformity'), ('tradition', 'Tradition'), ('benevolence', 'Care'), ('universalism', 'Universalism')]
PSYCHES_BY = {'close': (['extraversion'], [], 'loves'), 'secure': (['neuroticism'], [], 'attachment'), 'disagree': (['agreeableness'], [2, 3], 'conflict'),
              'life': (['conscientiousness'], [0, 1], None), 'future': (['openness'], [], 'motives')}
MBTI_PAIRS = [('E', 'I', 'Extraversion', 'Introversion'), ('S', 'N', 'Sensing', 'Intuition'), ('T', 'F', 'Thinking', 'Feeling'), ('J', 'P', 'Judging', 'Perceiving')]
MBTI_ASK = ['Where your energy comes from', 'What you notice first', 'How you decide', 'How you like plans']
# A letter's place on its axis by how clear it is (the Psyche Report's slight, moderate, clear): slight sits near the middle.
LEAN = {'slight': 14, 'moderate': 28, 'clear': 42, 'strong': 42}


def _axis(i, pa, pb, names):
    """One MBTI pair as an axis: each of you a dot, further out the clearer your letter."""
    hi, lo, nh, nl = MBTI_PAIRS[i]
    def place(p):
        lt = next((x for x in p.get('letters') or [] if x.get('letter') in (hi, lo)), None)
        ch = (lt or {}).get('letter') or (str(p.get('mbti') or '    ')[i:i + 1])
        if ch not in (hi, lo):
            return None, None, None
        st = (lt or {}).get('strength') or ''
        off = LEAN.get(st, 28)
        return ch, st, 50 - off if ch == hi else 50 + off
    ca, sa, xa = place(pa)
    cb, sb, xb = place(pb)
    if xa is None or xb is None:
        return ''
    lo_, hi_ = min(xa, xb), max(xa, xb)
    say = lambda nm, ch, st: '%s %s%s' % (_e(nm), ch, (', ' + _e(st)) if st else '')
    return ('<div class="mx"><span class="q">%s</span><div class="axis"><b title="%s">%s</b><div class="tr"><div class="gap" style="left:%d%%;width:%d%%"></div><i class="a" style="left:%d%%"></i><i class="b" style="left:%d%%"></i></div><b title="%s">%s</b></div>'
            '<em>%s · %s</em></div>' % (_e(MBTI_ASK[i]), _e(nh), hi, lo_, hi_ - lo_, xa, xb, _e(nl), lo, say(names[0], ca, sa), say(names[1], cb, sb)))


def _dual(label, x, y):
    lo, hi = min(x, y), max(x, y)
    return ('<div class="dr"><span>%s</span><div class="tr"><div class="gap" style="left:%d%%;width:%d%%"></div><i class="a" style="left:%d%%"></i><i class="b" style="left:%d%%"></i></div>'
            '<em><b class="a">%d</b> · <b class="b">%d</b></em></div>' % (_e(label), lo, hi - lo, x, y, x, y))


def _radar(ma, mb):
    import math
    pts = lambda m: ' '.join('%.1f,%.1f' % (110 + 80 * (m.get(k) or 0) / 100 * math.sin(2 * math.pi * i / 10), 100 - 80 * (m.get(k) or 0) / 100 * math.cos(2 * math.pi * i / 10))
                             for i, (k, _) in enumerate(MOTIVE_LABEL))
    rings = ''.join('<circle cx="110" cy="100" r="%d" fill="none" stroke="#ece4f1"/>' % r_ for r_ in (20, 40, 60, 80))
    labels = ''.join('<text x="%.1f" y="%.1f" text-anchor="middle">%s</text>' % (110 + 96 * math.sin(2 * math.pi * i / 10), 103 - 92 * math.cos(2 * math.pi * i / 10), _e(lb))
                     for i, (_, lb) in enumerate(MOTIVE_LABEL))
    return ('<svg class="radar" viewBox="-28 0 276 200" role="img" aria-label="Your ten motivations, both of you">%s'
            '<polygon points="%s" fill="#7b3fa0" fill-opacity=".22" stroke="#7b3fa0" stroke-width="1.6"/><polygon points="%s" fill="#d1477a" fill-opacity=".2" stroke="#d1477a" stroke-width="1.6"/>%s</svg>'
            % (rings, pts(ma), pts(mb), labels))


def _thumbs(cid, num, title):
    """👍 or 👎 on a chapter, as the Psyche Report's sections (README "Psyche Together, release 35"). The page can't send:
    a 👎 opens What's off? and makes the line to say in the chat, which writes the read again with it in mind."""
    return ('<div class="fb" data-ch="%s %s"><span>Did this ring true?</span><button type="button" data-fb="up">👍</button><button type="button" data-fb="down">👎</button>'
            '<div class="fbx" hidden><textarea maxlength="300" rows="2" placeholder="What\'s off? A few words"></textarea>'
            '<div class="sayrow"><code></code><button type="button" data-copy="">Copy</button></div><p class="soft">Say this in your Psyche Together chat, and your read is written again with it in mind.</p></div>'
            '<p class="fbok" hidden>Thanks: glad it landed.</p></div>' % (_e(num), _e(title)))


def _area_psy(aid, pa, pb, names, line):
    """What your two Psyches show for one area, beside Muse's line on what it means for it (README "Psyche Together,
    release 39"): each trait sits in the area it explains, never in a panel of its own."""
    fa, fb = pa.get('bigFive') or {}, pb.get('bigFive') or {}
    dual = lambda k: _dual(TRAIT_LABEL[k], fa[k], fb[k]) if isinstance(fa.get(k), int) and isinstance(fb.get(k), int) else ''
    pair = lambda x, y: '<div class="pair2"><div><b class="a">%s</b>%s</div><div><b class="b">%s</b>%s</div></div>' % (_e(names[0]), x, _e(names[1]), y)
    body = ''
    if aid == 'loves':
        g = lambda p_, k: _e(', '.join(p_.get(k) or []) or '–')
        if pa.get('caresBy') or pb.get('caresBy'):
            body = pair('<span>Shows care by: %s</span><span>Feels cared for by: %s</span>' % (g(pa, 'caresBy'), g(pa, 'feelsCaredForBy')),
                        '<span>Shows care by: %s</span><span>Feels cared for by: %s</span>' % (g(pb, 'caresBy'), g(pb, 'feelsCaredForBy')))
    elif aid == 'connection':
        body = dual('extraversion')
    elif aid == 'needs':
        body = dual('conscientiousness')
    elif aid == 'life':
        body = _axis(0, pa, pb, names) + _axis(1, pa, pb, names)
    elif aid == 'growth':
        body = dual('openness')
    elif aid == 'security':
        body = dual('neuroticism')
    elif aid == 'attachment':
        if pa.get('attachment') or pb.get('attachment'):
            body = pair('<span>%s</span>' % _e(pa.get('attachment') or '–'), '<span>%s</span>' % _e(pb.get('attachment') or '–'))
    elif aid == 'disagreements':
        body = dual('agreeableness')
    elif aid == 'cycle':
        def cut(t):         # whole sentences up to about 200 characters, never cut mid-sentence
            out_ = ''
            for sn in re.split(r'(?<=[.!?])\s+', str(t).strip()):
                if out_ and len(out_) + len(sn) > 200:
                    break
                out_ = (out_ + ' ' + sn).strip()
            return out_
        body = _axis(2, pa, pb, names) + _axis(3, pa, pb, names)
        if pa.get('conflict') or pb.get('conflict'):
            body += pair('<span>%s</span>' % _e(cut(pa.get('conflict') or '–')), '<span>%s</span>' % _e(cut(pb.get('conflict') or '–')))
    elif aid == 'values' and pa.get('motives') and pb.get('motives'):
        both = sorted(((min(pa['motives'].get(k, 0), pb['motives'].get(k, 0)), lb) for k, lb in MOTIVE_LABEL), reverse=True)[:3]
        apart = sorted(((abs((pa['motives'].get(k) or 0) - (pb['motives'].get(k) or 0)), k, lb) for k, lb in MOTIVE_LABEL), reverse=True)[:2]
        apart = [(d, k, lb) for d, k, lb in apart if d >= 10]
        body = ('<p class="lbl" style="margin-top:4px">Your ten motivations</p>' + _radar(pa['motives'], pb['motives'])
                + '<div class="pair2"><div><b>What drives you both</b><span>%s</span></div><div><b>Where you pull apart most</b><span>%s</span></div></div>'
                % (_e(', '.join(lb for _, lb in both)),
                   _e('; '.join('%s (%s %d · %s %d)' % (lb, names[0], pa['motives'].get(k) or 0, names[1], pb['motives'].get(k) or 0) for _, k, lb in apart) or 'Nowhere by much')))
    if not body and not line:
        return ''
    ta, tb = str(pa.get('mbti') or ''), str(pb.get('mbti') or '')
    key = ('<div class="pkey"><span><i class="a"></i>%s%s</span><span><i class="b"></i>%s%s</span></div>' % (
        _e(names[0]), (' · ' + _e(ta)) if ta else '', _e(names[1]), (' · ' + _e(tb)) if tb else '')) if body else ''
    return '<div class="psy"><span class="lbl">In your Psyches</span>%s%s%s</div>' % (key, body, ('<p class="pline">%s</p>' % _e(line)) if line else '')


def _psy_panel(pa, pb, names):
    """Your two Psyches side by side, once, at a glance (README "Psyche Together, release 42"): the four MBTI axes,
    the Big Five, love languages, attachment, conflict styles and the ten motivations. The areas cite a trait in words."""
    fa, fb = pa.get('bigFive') or {}, pb.get('bigFive') or {}
    if not (pa or pb):
        return ''
    body = ''.join(_axis(i, pa, pb, names) for i in range(4))
    body += ''.join(_dual(TRAIT_LABEL[k], fa[k], fb[k]) for k in ('openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism')
                    if isinstance(fa.get(k), int) and isinstance(fb.get(k), int))
    for aid, lbl in (('loves', 'Love languages'), ('attachment', 'Attachment'), ('cycle', 'In a disagreement'), ('values', '')):
        part_ = _area_psy(aid, pa, pb, names, '')
        if aid == 'cycle':          # the decide and plans axes are already above: only the two conflict styles
            part_ = re.sub(r'<div class="mx">.*?</em></div>', '', part_, flags=re.S)
        part_ = re.sub(r'<div class="pkey">.*?</div>', '', part_, count=1, flags=re.S).replace('<div class="psy"><span class="lbl">In your Psyches</span>', '', 1)
        part_ = part_[:-len('</div>')] if part_.endswith('</div>') else part_
        if part_.strip():
            body += ('<p class="lbl" style="margin-top:14px">%s</p>' % lbl if lbl else '') + part_
    body = '<p class="lbl" style="margin-top:4px">Personality</p>' + body
    ta, tb = str(pa.get('mbti') or ''), str(pb.get('mbti') or '')
    key = '<div class="pkey"><span><i class="a"></i>%s%s</span><span><i class="b"></i>%s%s</span></div>' % (
        _e(names[0]), (' · ' + _e(ta)) if ta else '', _e(names[1]), (' · ' + _e(tb)) if tb else '')
    return ('<details class="psyd"><summary>Your two Psyches, side by side <span class="soft">%s · %s</span></summary><div class="psy">%s%s</div></details>'
            % (_e(names[0] + (' · ' + ta if ta else '')), _e(names[1] + (' · ' + tb if tb else '')), key, body))


def _loves_match(pa, pb):
    """How many of you are cared for the way the other shows care: 2, 1, 0, or None without both cards' love languages."""
    if not (pa.get('caresBy') and pb.get('caresBy') and pa.get('feelsCaredForBy') and pb.get('feelsCaredForBy')):
        return None
    return int(bool(set(pb['caresBy']) & set(pa['feelsCaredForBy']))) + int(bool(set(pa['caresBy']) & set(pb['feelsCaredForBy'])))


def _tint(hexc):
    h = hexc.lstrip('#')
    r_, g_, b_ = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return '#%02x%02x%02x' % tuple(int(c + (255 - c) * 0.9) for c in (r_, g_, b_))


def _how(box):
    """The sources, each with its count, and the confidence score, worked out when the read was saved (read_sources)."""
    src = box.get('sources') if isinstance(box.get('sources'), dict) else None
    if not src:
        return ''
    c = src.get('confidence') or {}
    n = c.get('score')
    bar = lambda label, v, col: ('<span>%s</span><div><i style="width:%d%%;background:%s"></i></div><b>%d%%</b>' % (_e(label), v, col, v)) if v is not None else ''
    rows = ''.join(bar('%s\'s Psyche' % p['name'], p.get('confidence'), col) for p, col in zip(src.get('people') or [], ('#7b3fa0', '#c2366d')))
    rows += bar('Your conversation', round(100 * (c.get('talk') or 0) / 60), '#2d5fa8') + bar('Your check-ins', round(100 * (c.get('checkin') or 0) / 40), '#2f7d5b')
    out = ('<div class="conf2"><div class="big"><b>%d%%</b><span>confidence · %s</span></div><div class="bar"><i style="width:%d%%"></i></div>'
           '<p class="soft">Half is the lower of your two Psyches\' own confidence, as a Sync is held to the weaker card; half is what you two gave this read: '
           'your conversation together (how much of it, and over how long) and your check-ins. Never more than 90.</p><div class="cb">%s</div></div>'
           % (n, _e(c.get('level')), n, rows)) if n is not None else ''
    fmt = lambda d: datetime.strptime(d, '%Y-%m-%d').strftime('%-d %B %Y') if d else ''
    items = []
    for p in src.get('people') or []:
        items.append('<li><b>%s\'s Psyche Report</b>%s%s</li>' % (_e(p['name']), (': read from ' + _e(', '.join(p['basedOn']))) if p.get('basedOn') else '',
                     (' · confidence %d%% (%s)' % (p['confidence'], p['level'])) if p.get('confidence') is not None else ''))
    ch = src.get('chat')
    if ch:
        per = ' · '.join('%s %s' % (k.capitalize() if k != 'whatsapp' else 'WhatsApp', '{:,}'.format(v)) for k, v in sorted((ch.get('counts') or {}).items()))
        items.append('<li><b>Your conversation together</b>: {:,} messages{}{}, all counted on the device of the one who added it; {:,} of them, about {:,} characters, read in full for this read, spread over the whole time, links, emails, handles and numbers removed</li>'.format(
            ch['messages'], (' (%s)' % per) if per else '', (', %s to %s' % (fmt(ch.get('from')), fmt(ch.get('to')))) if ch.get('from') else '', ch.get('sampleLines') or 0, ch.get('sampleChars') or 0))
    ck = src.get('checkin') or {}
    if ck.get('questions'):
        items.append('<li><b>Your check-ins</b>: the same %d questions for each of you, answered privately%s, and how satisfied you each are and think the other is</li>'
                     % (ck['questions'], (', %d big decisions side by side' % ck['decisions']) if ck.get('decisions') else ''))
    return out + ('<h3>Read from</h3><ul class="srcs">%s</ul>' % ''.join(items) if items else '')


def page(box, s):
    """The read, integrated (README "Psyche Together", releases 14 to 19): For you first (this copy only); what moved
    since; at a glance (the overall pair, the relationship map by chapter, three truths); five chapters, each told
    once; a light intermission; one 28-day practice; and how it was read."""
    r, view = box.get('read') or {}, box.get('view') or {}
    names = view.get('names') or ['', '']
    fy = s.get('forYou') if isinstance(s.get('forYou'), dict) else None
    gentle = is_gentle(s)
    D = lambda x: x if isinstance(x, dict) else {}
    ch = D(r.get('chapters'))
    sig = (box.get('chat') or {}).get('signals') or {}
    who = box.get('chatOf') or names
    parts, nav, moments = [], [], []

    def part(pid, num, title, inner, cls='', sub='', opened=False, colour=None, teaser=''):
        c = colour or COLOURS.get(pid, '#7b3fa0')
        nav.append('<a href="#%s" style="--c:%s">%s%s</a>' % (pid, c, ('<i>%s</i>' % _e(num)) if num else '', _e(title)))
        parts.append('<section class="part %s%s" id="%s" style="--c:%s"><button type="button" class="hd" aria-expanded="%s"><span class="num">%s</span>'
                     '<span class="ttl">%s</span>%s%s</button><div class="body">%s</div></section>'
                     % (cls, ' open' if opened else '', pid, c, 'true' if opened else 'false', _e(num), _e(title),
                        (('<span class="tease">%s</span>' % _e(sub)) if sub else '') + (('<span class="tz">%s</span>' % _e(teaser)) if teaser else ''), CHEV, inner))

    def keep(xs, tag):
        for x in xs or []:
            if isinstance(x, dict) and x.get('what') and x.get('what') not in [m[1] for m in moments]:
                moments.append((x.get('when'), x.get('what'), tag))
        return _moments(xs)
    ask = lambda xs: ('<div class="callout ask"><span class="lbl">Ask each other</span><ul>%s</ul></div>' % ''.join('<li>%s</li>' % _e(x) for x in xs)) if xs else ''
    tryit = lambda t, label='Try this': ('<div class="callout try"><span class="lbl">%s</span>%s</div>' % (_e(label), _e(t))) if t else ''
    signs2 = lambda sg, la, lb: ('<div class="two signs">%s%s</div>' % (''.join('<div><b><span>%s</span>%s</b><ul>%s</ul></div>' % (_initial(n_), _e(l_), ''.join('<li>%s</li>' % _e(x) for x in D(sg).get(k) or []))
                                                                              for n_, l_, k in ((names[0], la, 'a'), (names[1], lb, 'b'))), '')) if D(sg).get('a') else ''
    two = lambda a, b, la, lb, na=names[0], nb=names[1]: ('<div class="two"><div><b><span>%s</span>%s</b>%s</div><div><b><span>%s</span>%s</b>%s</div></div>'
                                                         % (_initial(na), _e(la), _paras(a), _initial(nb), _e(lb), _paras(b)))
    if gentle:
        part('support', '♡', 'For you first', '<p>' + _e(SUPPORT) + '</p>', 'support mine', 'Only on your copy', True)
    # For you (README "Psyche Together, release 24"): each piece in the chapter it's about, as a small private box.
    other = names[1] if s.get('role') == 'a' else names[0]
    mine_by = {}
    for x in (fy or {}).get('focus') or []:
        if isinstance(x, dict):
            home = next((c[0] for c in CHAPTERS if x.get('pillar') in c[3]), 'close')
            mine_by.setdefault(home, []).append(x)
    private = lambda xs: ''.join('<div class="minebox"><span class="lbl">🔒 Just for you · %s never sees this</span><h4>%s</h4>%s%s</div>'
                                 % (_e(other), _e(x.get('title')), _paras(x.get('detail')),
                                    ('<p class="raise"><b>How to raise it:</b> %s</p>' % _e(x.get('howToRaise'))) if x.get('howToRaise') and not gentle else '') for x in xs)
    # What moved (README "Psyche Together, release 17"): each check-in again, newest first, above the read it updates.
    arrows = {'up': '↑ up', 'down': '↓ down', 'same': '= same'}
    for k_, rc in enumerate(reversed(rounds_in(box))):
        nt, rv = D(rc.get('note')), D(rc.get('view'))
        lines = {c.get('pillar'): c.get('line') for c in nt.get('changes') or [] if isinstance(c, dict)}
        rows = ''.join('<div class="mv"><b>%s</b><span class="%s">%s · %s</span>%s</div>' % (_e(PILLARS[pid]), d, _e(arrows[d]), _e((rv.get('pillars') or {}).get(pid, '')),
                                                                                       ('<p>%s</p>' % _e(lines[pid])) if lines.get(pid) else '')
                       for pid in PILLAR_ORDER for d in [(rc.get('moved') or {}).get(pid)] if d)
        ov2 = rv.get('overall') or {}
        nx = D(nt.get('next'))
        when_ = datetime.fromtimestamp(rc.get('at') or time.time()).strftime('%-d %B %Y')
        stats = ('<div class="stats"><div class="stat"><span class="lbl">How satisfied you both are</span>%s</div><div class="stat"><span class="lbl">How well you read each other</span>%s</div></div>'
                 % (_sv(ov2.get('level')), _sv(ov2.get('reading')))) if ov2 else ''
        part('since%d' % rc.get('n', 2), '↻', '%d weeks on' % weeks_on(rc.get('n', 2)),
             '<div class="hero"><small>These weeks, in one line</small><b>%s</b></div>%s<h3>What moved</h3>%s<div class="callout try"><span class="lbl">What held</span>%s</div>'
             '<div class="wk"><small>The next four weeks</small><h4>%s</h4><ol>%s</ol></div>'
             % (_e(nt.get('summary')), stats, rows, _e(nt.get('held')), _e(nx.get('title')), ''.join('<li>%s</li>' % _e(x) for x in nx.get('steps') or [])),
             'since', 'Checked in again · ' + when_, k_ == 0, COLOURS['since'])
    # At a glance (README "Psyche Together, release 39"): the line; an executive summary; three things that stand out
    # about you both, in full, each pointing to the chapter with its details; and where you stand, one row per chapter
    # listing its areas, in the same names and order as the chapter's own cards.
    kinds = {'strength': 'Your biggest strength as a couple', 'edge': 'Where you can grow together', 'surprise': 'What may surprise you both'}
    title_of = {c[0]: c[2] for c in CHAPTERS}
    pcards = box.get('psyches') or {'a': (SEEN.get('cards') or {}).get('a') or {}, 'b': (SEEN.get('cards') or {}).get('b') or {}}
    pa_, pb_ = pcards.get('a') or {}, pcards.get('b') or {}
    stands = ''
    for i, x in enumerate(x for x in r.get('truths') or [] if isinstance(x, dict) and x.get('kind') in kinds):
        home = x.get('chapter') if x.get('chapter') in CHAPTER_IDS else TRUTH_HOME.get(x.get('kind'), 'close')
        stands += ('<div class="std"><div class="th"><span class="n">%d</span><span class="lbl">%s</span></div><h4>%s</h4>%s%s<a class="more" href="#%s">More in %s ›</a></div>'
                   % (i + 1, _e(kinds[x['kind']]), _e(x.get('title')), _paras(x.get('detail')), _pills(x.get('evidence')), home, _e(title_of.get(home, ''))))
        keep(x.get('evidence'), kinds[x['kind']])
    word = lambda lv: '<span class="lw %s">%s</span>' % (_e(lv.replace(' ', '-')), _e(lv))
    dec = view.get('decisions') or []
    al_, tk_ = sum(1 for x in dec if x.get('result') == 'Aligned'), sum(1 for x in dec if x.get('result') != 'Aligned')

    def badge(cid, aid, pill=False):
        """An area's state in a few words: its check-in level, a count, a match, or the read's own short status."""
        c_ = D(ch.get(cid))
        if aid in (view.get('pillars') or {}):
            lv = view['pillars'][aid]
            return _lv(lv) if pill else word(lv)
        txt, cls = '', 'Info'
        if aid == 'loves':
            m_ = _loves_match(pa_, pb_)
            txt, cls = {2: ('both matched', 'Aligned'), 1: ('one matched', 'Steady'), 0: ('different', 'Talk-about')}.get(m_, ('', ''))
        elif aid == 'know' and D(view.get('know')).get('of'):
            kw = view['know']
            txt, cls = '%d of %d' % (kw['right'], kw['of']), ('Aligned' if kw['right'] == kw['of'] else 'Steady' if kw['right'] * 2 >= kw['of'] else 'Talk-about')
        elif aid in ('interests', 'values'):
            cl_ = D(D(D(c_.get('areas')).get(aid)).get('columns')) or D(c_.get('enjoy' if aid == 'interests' else 'alike'))
            txt = ('%d shared' % len(cl_['shared'])) if cl_.get('shared') else ''
        elif aid == 'decisions' and dec:
            if pill:
                return ''.join('<span class="lv %s">%s</span>' % (k_, t_) for k_, t_ in (('Aligned', '%d aligned' % al_ if al_ else ''), ('Talk-about', '%d to talk about' % tk_ if tk_ else '')) if t_)
            return ' · '.join(y for y in ['<span class="lw Aligned">%d aligned</span>' % al_ if al_ else '', '<span class="lw Talk-about">%d to talk about</span>' % tk_ if tk_ else ''] if y)
        elif aid in STATUS_AREAS:
            txt = D(D(c_.get('areas')).get(aid)).get('status') or ''
        if not txt:
            return ''
        return ('<span class="lv %s">%s</span>' if pill else '<span class="lw %s">%s</span>') % (cls, _e(txt))
    def tile(cid, aid, nm):
        """One area as a tile at a glance (README "Psyche Together, release 43"): its name, and its state in colour."""
        if aid in (view.get('pillars') or {}):
            txt, cls = view['pillars'][aid], view['pillars'][aid].replace(' ', '-')
        elif aid == 'decisions' and dec:
            txt, cls = '%d of %d aligned' % (al_, len(dec)), ('Aligned' if al_ == len(dec) else 'Steady')
        else:
            m_ = re.search(r'<span class="l[vw] ([\w-]+)">([^<]*)</span>', badge(cid, aid, True) or '')
            if not m_:
                return ''
            cls, txt = m_.group(1), html.unescape(m_.group(2))
            # Release 44: an area that isn't a check-in level is green when it's a great result, blue otherwise, never red.
            secure_ = lambda p_: bool(re.search(r'\bsecure', str(p_.get('attachment') or ''), re.I)) and not re.search(r'insecure', str(p_.get('attachment') or ''), re.I)
            great = {'loves': cls == 'Aligned', 'know': cls == 'Aligned',
                     'interests': len(D(D(D(D(ch.get(cid)).get('areas')).get(aid)).get('columns')).get('shared') or D(D(ch.get(cid)).get('enjoy')).get('shared') or []) >= 3,
                     'values': len(D(D(D(D(ch.get(cid)).get('areas')).get(aid)).get('columns')).get('shared') or D(D(ch.get(cid)).get('alike')).get('shared') or []) >= 3,
                     'attachment': secure_(pa_) and secure_(pb_)}.get(aid, False)
            cls = 'Aligned' if great else 'Steady'
        return '<span class="tl %s"><small>%s</small><b>%s</b></span>' % (_e(cls), _e(nm), _e(txt[:1].upper() + txt[1:]))
    rows = ''
    for cid, num, title, pids, refs in CHAPTERS:
        tiles_ = ''.join(tile(cid, aid, nm) for aid, nm in areas_of(cid, view))
        take_ = D(ch.get(cid)).get('takeaway')
        if tiles_:
            rows += ('<a class="it2 ws" href="#%s" style="--c:%s"><div class="wh"><span class="n2">%s</span><b>%s</b><i>›</i></div><div class="tiles">%s</div>%s</a>'
                     % (cid, COLOURS.get(cid, '#7b3fa0'), num, _e(title), tiles_, ('<p class="tk2">%s</p>' % _e(take_)) if take_ else ''))
    ovv, ovr = view.get('overall') or {}, D(r.get('overall'))
    summary_ = ''
    if ovv:
        summary_ = ('<p class="sat">How satisfied you both are: %s · How well you read each other: %s</p>%s'
                    % (word(ovv['level']), word(ovv['reading']), ('<p>%s</p>' % _e(ovr.get('detail'))) if ovr.get('detail') else ''))
    part('glance', '★', 'At a glance', '<div class="hero glance-hero"><small>You both, in one line</small><b>%s</b></div>%s%s%s'
         % (_e(r.get('summary')), ('<h3>Executive summary</h3>' + summary_) if summary_ else '',
            ('<h3>Where you stand</h3><div class="map">%s</div>' % rows) if rows else '',
            ('<h3>Three things that stand out about you both</h3>' + stands) if stands else '') + _psy_panel(pa_, pb_, names),
         '', 'The whole read on one screen', True)
    # Chapters (README "Psyche Together, release 39"): the takeaway; one card per area, as named on the glance, each
    # with what it means, what you said, what your messages show, what your Psyches show and the dated moments; then
    # why it happens, what to try, and the research folded.
    chips = lambda xs: ''.join('<span>%s</span>' % _e(x) for x in xs or [])
    own = lambda al, k: [x for x in al.get(k) or [] if str(x).strip().lower() not in {str(y).strip().lower() for y in al.get('shared') or []}]
    cols = lambda al: (('<div class="alike"><div><small>%s</small>%s</div><div class="both"><small>Both of you</small>%s</div><div><small>%s</small>%s</div></div>%s'
                        % (_e(names[0]), chips(own(al, 'a')), chips(al.get('shared')), _e(names[1]), chips(own(al, 'b')), ('<p>%s</p>' % _e(al.get('line'))) if al.get('line') else ''))
                       if al.get('shared') else '')
    ICON = {'messages': ('💬', 'Messages'), 'psyches': ('🧠', 'Psyches'), 'report': ('📄', 'Reports'), 'moment': ('📅', '')}
    for cid, num, title, pids, refs in CHAPTERS:
        c = D(ch.get(cid))
        ar = D(c.get('areas'))
        take = c.get('takeaway') or ' '.join(D(D(r.get('pillars')).get(p)).get('headline') or '' for p in pids if p in (view.get('pillars') or {}))
        inner = '<div class="take"><span class="lbl">The takeaway</span><p>%s</p></div>' % _e(take)
        got = lambda x, k: x.get(k) if x.get(k) else c.get(k)          # an older read kept these on the chapter
        for aid, nm in areas_of(cid, view):
            x = D(ar.get(aid))
            pv = D(D(r.get('pillars')).get(aid))
            # 1. How you see it
            seen = x.get('seen') or pv.get('seeIt')
            st1 = ('<div class="st"><span class="sl">How you see it</span><p>%s</p></div>' % _e(seen)) if seen else ''
            # 2. What the evidence shows: each piece tagged with its source, then the area's own data
            evs = [e for e in x.get('evidence') or [] if isinstance(e, dict)]
            if evs and not any(e.get('kind') for e in evs):        # an older read: its message line, Psyches line and moments
                evs = ([{'kind': 'messages', 'text': pv['messages']}] if pv.get('messages') else []) + ([{'kind': 'psyches', 'text': x['psyches']}] if x.get('psyches') else []) \
                      + [{'kind': 'moment', 'when': e.get('when'), 'text': e.get('what')} for e in evs]
            for e in evs:
                if e.get('kind') == 'moment':
                    keep([{'when': e.get('when'), 'what': e.get('text')}], '%s · %s' % (title, nm))
            lis = ''.join('<li><i title="%s">%s</i><span>%s%s</span></li>' % (_e(ICON.get(e.get('kind'), ('•', ''))[1]), ICON.get(e.get('kind'), ('•', ''))[0],
                                                                         ('<b>%s</b> · ' % _e(e.get('when'))) if e.get('kind') == 'moment' and e.get('when') else '', _e(e.get('text')))
                          for e in evs)
            data_ = ''
            if aid == 'life':
                data_ += _rhythm(sig, who).replace('<h3>Your day, side by side</h3>', '<p class="lbl" style="margin-top:10px">Your day, side by side</p>')
            elif aid == 'interests':
                data_ += cols(D(x.get('columns')) or D(c.get('enjoy')))
            elif aid == 'values':
                data_ += cols(D(x.get('columns')) or D(c.get('alike')))
            elif aid == 'decisions':
                lines = D(x.get('lines')) or {y.get('topic'): y.get('line') for y in c.get('decisions') or [] if isinstance(y, dict)}
                data_ += ''.join('<div class="row"><b>%s</b>%s<p>%s: %s · %s: %s</p>%s</div>'
                                 % (_e(y['label']), _lv(y['result']), _e(names[0]), _e(y.get('a') or '-'), _e(names[1]), _e(y.get('b') or '-'),
                                    ('<p>%s</p>' % _e(lines.get(y['topic']))) if lines.get(y['topic']) else '') for y in dec)
            elif aid == 'know':
                kw = D(view.get('know'))
                data_ += '<p class="lbl" style="margin-top:10px">Worth knowing about each other</p>' + ''.join('<div class="row"><b>About %s</b><p>%s</p><p><span>%s</span></p></div>' % (_e(y.get('about')), _e(y.get('q')), _e(y.get('answer'))) for y in kw.get('items') or [])
            elif aid == 'cycle':
                cy = D(c.get('cycle'))
                steps_ = x.get('steps') or cy.get('steps')
                data_ += _cycle({'steps': steps_}, names) if steps_ else ''
            st2 = ('<div class="st"><span class="sl">What the evidence shows</span>%s%s</div>' % (('<ul class="evd">%s</ul>' % lis) if lis else '', data_)) if (lis or data_) else ''
            # 3. What it means, and what to do about it
            means = x.get('means') or x.get('meaning') or pv.get('headline')
            vd = VERDICTS.get(x.get('verdict')) or ({'more': VERDICTS['better'], 'less': VERDICTS['closer'], 'same': VERDICTS['matches']}.get(pv.get('signal')) if not x.get('means') else None)
            extra = ''
            if aid == 'loves':
                care = D(got(x, 'care'))
                extra = two(care.get('a'), care.get('b'), 'What makes %s feel cared for' % names[0], 'What makes %s feel cared for' % names[1]) if care.get('a') else ''
            elif aid == 'security':
                extra = signs2(got(x, 'signs'), 'When %s is feeling unsure' % names[0], 'When %s is feeling unsure' % names[1])
            elif aid == 'attachment':
                rs = D(x.get('reassure')) or {'a': c.get('a'), 'b': c.get('b')}
                extra = two(rs.get('a'), rs.get('b'), 'What reassures %s' % names[0], 'What reassures %s' % names[1]) if rs.get('a') else ''
            elif aid == 'growth' and D(c.get('growth')).get('a') and not x.get('means'):
                extra = two(D(c.get('growth')).get('a'), D(c.get('growth')).get('b'), 'How %s helps %s grow' % (names[0], names[1]), 'How %s helps %s grow' % (names[1], names[0]))
            elif aid == 'cycle':
                cy = D(c.get('cycle'))
                extra = signs2(got(x, 'signs'), 'Early signs, for %s' % names[0], 'Early signs, for %s' % names[1])
                und = D(x.get('under')) or {'a': cy.get('a'), 'b': cy.get('b')}
                extra += two(und.get('a'), und.get('b'), 'Under it, for %s' % names[0], 'Under it, for %s' % names[1]) if und.get('a') else ''
                mv = D(got(x, 'moves'))
                extra += two(mv.get('a'), mv.get('b'), 'Your move, %s' % names[0], 'Your move, %s' % names[1]) if mv.get('a') else ''
                q_ = got(x, 'askYourself')
                extra += ('<div class="callout key2"><span class="lbl">A question to ask yourself</span>%s</div>' % _e(q_)) if q_ else ''
            elif aid == 'know':
                mine_k = D(view.get('knowBy')).get(s.get('role'))
                if mine_k and not gentle:
                    extra = ('<div class="minebox"><span class="lbl">🔒 Just for you · %s never sees this</span><p>You knew %d of %d about %s.%s</p></div>'
                             % (_e(other), mine_k[0], mine_k[1], _e(other), '' if mine_k[0] == mine_k[1] else ' The answers above are a good place to start asking.'))
            nx = ''.join('<li><b>%s</b><span>Because %s</span></li>' % (_e(D(y).get('do')), _e(re.sub(r'^(because|since)\s+', '', str(D(y).get('because') or ''), flags=re.I)))
                         for y in x.get('next') or [] if D(y).get('do'))
            st3 = ('<div class="st means"><span class="sl">What it means</span>%s%s%s%s</div>'
                   % (('<span class="vd %s">%s</span>' % (_e(x.get('verdict') or ''), _e(vd))) if vd else '', ('<p>%s</p>' % _e(means)) if means else '', extra,
                      ('<span class="sl" style="margin-top:12px">Next steps</span><ul class="nx">%s</ul>' % nx) if nx else '')) if (means or extra or nx) else ''
            if st1 or st2 or st3:
                inner += '<div class="area" id="%s-%s"><div class="at"><b>%s</b>%s</div>%s%s%s</div>' % (cid, aid, _e(nm), badge(cid, aid, True), st1, st2, st3)
        if not ar and (c.get('askEachOther') or c.get('tryThis')):          # an older read's chapter-wide steps
            inner += ('<div class="callout ask"><span class="lbl">Try together</span>%s%s</div>'
                      % (''.join('<p class="q">%s</p>' % _e(y) for y in c.get('askEachOther') or []), ('<p><b>This week:</b> %s</p>' % _e(c.get('tryThis'))) if c.get('tryThis') else ''))
        inner += private(mine_by.get(cid, []))
        inner += _science(refs, folded=True)
        part(cid, num, title, inner, 'chapter', SUBTITLES.get(cid, ''), teaser=take)
        if cid == 'future':             # the breather comes between the everyday and the deeper chapters
            parts.append('@@INTERMISSION@@')
    # The intermission (README "Psyche Together, release 16"): a light breather after the heaviest chapter.
    fun = sig.get('fun') or {}
    im = D(r.get('intermission'))
    facts = []
    if fun.get('first'):
        facts.append(('💬', 'Your first message here', fun['first']))
    if fun.get('busiestDay'):
        facts.append(('🔥', 'Your busiest day', '%s, %s messages' % (fun['busiestDay'][0], fun['busiestDay'][1])))
    if fun.get('streak'):
        facts.append(('📆', 'Your longest run of days in a row', '%s days' % fun['streak']))
    for side_, nm in (('you', who[0]), ('partner', who[1])):
        em = ((sig.get(side_) or {}).get('emoji') or [])
        if em:
            facts.append((em[0], '%s\'s favourite emoji' % nm, ' '.join(em)))
    facts_html = ''.join('<div class="fact"><em>%s</em><small>%s</small><b>%s</b></div>' % (_e(i_), _e(a_), _e(b_)) for i_, a_, b_ in facts)
    line = ''.join('<li><b>%s</b><span>%s</span><em>%s</em></li>' % (_e(w), _e(t), _e(tag)) for w, t, tag in sorted(moments, key=lambda m: _when_key(m[0])))
    inner = ('<span class="badge">Intermission</span><div class="lines" style="margin-top:12px">%s</div>%s%s%s%s'
             % (''.join('<p>%s</p>' % _e(x) for x in im.get('lines') or []), ('<div class="funfacts">%s</div>' % facts_html) if facts_html else '',
                _months_svg(sig.get('months') or []), _talk_panel(box, names), ('<h3>Your story in moments</h3><ol class="timeline">%s</ol>' % line) if line else ''))
    part('moments', '✦', im.get('title') or 'Your story in moments', inner, 'intermission', 'A light break', False, COLOURS['moments'])
    inter, inter_nav = parts.pop(), nav.pop()
    parts[parts.index('@@INTERMISSION@@')] = inter
    nav.insert(next((i for i, n in enumerate(nav) if '#secure' in n), len(nav)), inter_nav)
    # One practice.
    pn = D(r.get('plan'))
    w1 = D(pn.get('week1'))
    weeks = ''.join('<div class="wk"><i>W%d</i><small>Week %d</small><h4>%s</h4>%s<p><b>Ask each other:</b> %s</p><p style="margin:0"><b>Do together:</b> %s</p></div>'
                    % (i + 2, i + 2, _e(w.get('title')), ('' if gentle else '<div class="callout key2"><span class="lbl">A conversation: %s</span>%s<ol>%s</ol></div>' % (_e(D(w.get('conversation')).get('title')), _e(D(w.get('conversation')).get('why')),
                                                                                                         ''.join('<li>%s</li>' % _e(x) for x in D(w.get('conversation')).get('script') or []))),
                       _e(w.get('ask')), _e(w.get('doTogether'))) for i, w in enumerate(pn.get('weeks') or []) if isinstance(w, dict))
    part('plan', '06', PLAN_TITLE, '<div class="weeks"><div class="wk"><i>W1</i><small>Week 1 · a little every day</small><h4>%s</h4><ol class="days">%s</ol></div>%s</div>%s'
         '<p class="soft">In four weeks, Psyche Together asks you both the same questions again, here in Muse, and shows what has moved at the top of this page.</p>'
         % (_e(w1.get('title')), ''.join('<li><b>%d</b><span>%s</span></li>' % (i + 1, _e(x)) for i, x in enumerate(w1.get('days') or [])), weeks
            + (('<div class="minebox"><span class="lbl">🔒 Just for you · %s never sees this</span><p><b>This week, on your side:</b> %s</p>%s</div>'
                % (_e(other), _e(fy.get('practice')), ('<p class="soft">%s</p>' % _e(fy.get('note'))) if fy.get('note') else '')) if fy and fy.get('practice') else ''),
            _research('lovemaps')),
         'chapter', SUBTITLES['plan'])
    part('how', 'i', 'How this was read', _how(box) + '%s<p class="soft">From both your full Psyche reports, shared with your consent for this read; your conversation together, measured on the device of the one who added it; and the check-in you each did privately, the same core questions for both. '
         'The measures follow published research: how partners see the relationship (Joel et al., PNAS 2020), turning towards and repair (Gottman), responsiveness to good news (Gable et al., 2004), '
         'language style matching (Ireland et al., 2011), "we" language (Seider et al., 2009), demand and withdraw (Christensen & Heavey), dyadic coping (Bodenmann), self-expansion (Aron) and the Michelangelo phenomenon (Drigotas et al., 1999). '
         'They describe couples in general, never a verdict on either of you. This is coaching, not counselling: if something here feels heavy, a couples counsellor is worth seeing together.</p>'
         '<div class="saycopy"><p>To end Psyche Together and have PsycheAI delete everything it keeps for both of you, say this in your Psyche Together chat. Your own copy of this page stays on your device until you delete it.</p>'
         '<div class="sayrow"><code>End Psyche Together</code><button type="button" data-copy="End Psyche Together">Copy</button></div></div>' % _paras(r.get('caveats')),
         '', 'Sources, method and limits')
    when = datetime.fromtimestamp(box.get('at') or time.time()).strftime('%-d %B %Y')
    # The header (README "Psyche Together, release 20"): both Psyche Cards leaning in, a heart between them; whose copy
    # this is, since each holds that person's private advice (README "Psyche Together, release 29").
    mine_name = (names[0] if s.get('role') == 'a' else names[1] if s.get('role') == 'b' else '') or ''
    conf_h = ((box.get('sources') or {}).get('confidence') or {}).get('score')     # in the header, as the Psyche Report's signal strength
    pics, cards = SEEN.get('pics') or {}, SEEN.get('cards') or {}
    since = (sig.get('fun') or {}).get('first')

    def card(role, nm, side):
        ch_ = (cards.get(role) or {}).get('character') or ''
        img = (('<button type="button" class="cardp %s" data-view aria-label="Open %s\'s Psyche Card"><img alt="%s\'s Psyche Card" src="%s"></button>' % (side, _e(nm), _e(nm), pics[role]))
               if pics.get(role) else '<div class="cardp %s nopic"><span>%s</span></div>' % (side, _initial(nm)))
        ty = (cards.get(role) or {}).get('mbti') or ''
        return '<div class="lover">%s<b>%s</b>%s</div>' % (img, _e(nm), ('<small>most like %s%s</small>' % (_e(ch_), (' · ' + _e(ty)) if ty else '')) if ch_ else '')
    hearts = ''.join('<svg class="fh h%d" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.4 5c2 0 3.6 1.1 4.6 2.6l1 1.4 1-1.4C14 6.1 15.6 5 17.6 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21z"/></svg>' % i for i in range(1, 7))
    banner = ('<header class="banner love" id="top">%s%s<div class="facts">%s</div><div class="couple">%s<div class="heart"><svg viewBox="0 0 24 24" aria-hidden="true"><defs><linearGradient id="hg" x1="0" y1="0" x2="1" y2="1">'
              '<stop offset="0" stop-color="#ff7aa2"/><stop offset="1" stop-color="#c2366d"/></linearGradient></defs><path fill="url(#hg)" d="M12 21s-7.5-4.6-9.6-9.2C.9 8.4 3 5 6.4 5c2 0 3.6 1.1 4.6 2.6l1 1.4 1-1.4C14 6.1 15.6 5 17.6 5 21 5 23.1 8.4 21.6 11.8 19.5 16.4 12 21 12 21z"/></svg></div>%s</div>'
              '<h1>%s <i>&amp;</i> %s</h1><p class="lede">The two of you, read together: how you love, how you disagree and how you grow, from both your Psyches and your own words.</p><div class="sub">%s</div></header>'
              % (LOGO, hearts, _e(' · '.join(x for x in ['Psyche Together', view.get('stage') or '', ('%d%% confidence' % conf_h) if conf_h is not None else '', ('%s\'s copy' % mine_name) if mine_name else ''] if x)), card('a', names[0], 'l'), card('b', names[1], 'r'), _e(names[0]), _e(names[1]),
                 _e(' · '.join(x for x in [('Talking since ' + since) if since else '', when] if x))))
    viewer = '<div class="viewer" id="viewer" role="dialog" aria-label="Psyche Card" hidden><img alt=""><span>Tap to close</span></div>' if pics else ''
    bar = '<nav aria-label="Sections">%s<button type="button" data-fold>Close all ▲</button></nav>' % ''.join(nav)
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
            '<title>Psyche Together · %s &amp; %s%s</title><style>%s</style></head><body><div class="wrap">%s%s%s<button type="button" class="foldall" data-fold>Close all ▲</button>'
            '<footer><b>Psyche Together</b> by PsycheAI · psycheai.io<br>Made in your own Muse workspace. PsycheAI keeps no copy it can read.</footer></div>%s<script>%s</script></body></html>'
            % (_e(names[0]), _e(names[1]), (' · %s&#x27;s copy' % _e(mine_name)) if mine_name else '', CSS, banner, bar, ''.join(parts), viewer, JS))


def show(box=None):
    s = state()
    if s.get('role') and not s.get('picSent'):
        pic = card_pic()      # a Psyche Together from before release 20: their card goes now, for both headers
        if pic and not tool('together_put', {'e2e': {'pic': seal({'img': pic}, key_for('together-box', keys()['code']))}}).get('error'):
            s['picSent'] = True
            save_state(s)
            SEEN.clear()
    if box is None or 'pics' not in SEEN:
        k, got, profiles, box_ = couple()
        if got.get('error') and box is None:
            return got
        box = box if box is not None else box_
        if not box:
            return {'waiting': True, 'say': 'Your read isn\'t written yet.'}
    s['shown'] = box.get('at')
    done_ = [x.get('n') for x in rounds_in(box)]
    if isinstance(s.get('round'), dict) and s['round'].get('n') in done_:
        s['round'] = None
    save_state(s)
    os.makedirs(OUT, exist_ok=True)
    names = (box.get('view') or {}).get('names') or ['', '']
    clean = lambda n: re.sub(r'[^A-Za-z0-9]+', '', n or '') or 'Partner'
    mine_ = names[0] if s.get('role') == 'a' else names[1]
    path = os.path.join(OUT, 'Psyche-Together-%s-%s-%ss-copy.html' % (clean(names[0]), clean(names[1]), clean(mine_)))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(page(box, s))
    os.chmod(path, 0o600)
    for old in glob.glob(os.path.join(OUT, 'Psyche-Together-*.html')):
        if os.path.abspath(old) != os.path.abspath(path):
            try:
                os.remove(old)      # one page in out/, the newest: an older page never sits beside it
            except OSError:
                pass
    latest = (rounds_in(box)[-1].get('note') or {}) if rounds_in(box) else {}
    return {'file': path, 'say': 'Your Psyche Together is ready.', 'summary': latest.get('summary') or (box.get('read') or {}).get('summary'),
            'buttons': (['Check in again'] if time.time() >= due_at(box) else []) + ['Ask about our read', 'Our 28-day practice', 'Write our read again', 'Done'], 'asButtons': True}


def end():
    k = keys()
    if k.get('code'):
        tool('together_end', {})
    forget()
    return {'ended': True, 'say': 'Psyche Together has ended, for both of you. Your partner sees only that it ended. Your own copy of the page stays here until you delete it.'}


def forget():
    for path in (STATE, STATE_KEPT, KEYS, KEYS_KEPT, PENDING):
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
    if cmd in ('status', 'rewrite', 'check') and not os.environ.get('PSYCHE_TOGETHER_FRESH'):
        try:                # a newer signed release, if there is one, runs this same command (README release 37)
            if update().get('updated'):
                os.environ['PSYCHE_TOGETHER_FRESH'] = '1'
                os.execv(sys.executable, [sys.executable, os.path.abspath(__file__)] + list(argv))
        except Exception:   # never in the way of the person: the command answers either way
            pass
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
        out = widget_out(s, 'Your questions, written from both your Psyches.')
    elif cmd == 'check':
        out = check()
    elif cmd == 'again':
        out = again()
    elif cmd == 'later':
        out = later()
    elif cmd == 'rewrite':
        out = rewrite(opt('--note'))
    elif cmd == 'save-recheck':
        out = save_recheck(rest[0] if rest else '')
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
