# Builds assets/together-sample.html, the sample Psyche Together report served at /together/sample
# (README "A sample Psyche Together report"): the real report page (together/bin/together.py page) for a
# made-up couple, Emily and Lucas, psycheai.io's own fictional sample readers (Mulan and Odysseus). Nothing here is anyone's
# real data. The read is checked by the same check_read every real read passes, so the sample can't show
# what a real read couldn't.
# Run after a change to the report's layout: python3 tools/together-sample.py
import importlib.util
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
APP = os.path.dirname(HERE)
spec = importlib.util.spec_from_file_location('t', os.path.join(APP, 'together', 'bin', 'together.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

AT = 1795000000          # a fixed date (November 2026), so the file only changes when the layout or the read does


def psyche(name, character, mbti, headline, big, motives, patterns, values, attachment, conflict, cares, feels, strengths, edges):
    return {'name': name, 'character': character, 'mbti': mbti, 'letters': [], 'headline': headline,
            'bigFive': dict(zip(['openness', 'conscientiousness', 'extraversion', 'agreeableness', 'neuroticism'], big)),
            'motives': motives, 'patterns': patterns, 'values': values, 'attachment': attachment, 'conflict': conflict,
            'caresBy': cares, 'feelsCaredForBy': feels, 'relationshipStrengths': strengths, 'relationshipEdges': edges}


# Their ten motivations, in together.py's order: Emily's from psycheai.io's docs/sample.json, Lucas's to fit his card's top three.
MOTIVES = [k for k, _ in m.MOTIVE_LABEL]
# Emily Carter and Lucas Moreau are psycheai.io's own sample readers (docs/sample.json and docs/sample-cards.json),
# so their Psyches here are the ones on their sample cards.
EMILY = psyche('Emily', 'Mulan', 'ENFJ', 'Organiser with a warm centre and a quiet battery', [61, 84, 55, 79, 44],
               dict(zip(MOTIVES, [55, 41, 34, 66, 18, 61, 52, 38, 84, 47])), ['The quiet organiser', 'Generous with attention', 'Bursts, then recovery'],
               ['Reliability', 'Craft', 'Belonging'], 'Leans secure, with a self-reliant streak', 'Smooths it over, raises it later',
               ['Acts of service'], ['Quality time', 'Words of affirmation'], ['Remembers the detail', 'Handles friction privately'], ['Never asks for anything', 'Tallies quietly'])
LUCAS = psyche('Lucas', 'Odysseus', 'ENTP', 'Resourceful planner with a way out of every corner', [84, 56, 72, 58, 40],
               dict(zip(MOTIVES, [74, 86, 62, 77, 41, 33, 24, 22, 58, 52])), ['A plan B for every plan', 'Talks a room round', 'Always heading home'],
               ['Ingenuity', 'Adventure', 'Loyalty'], 'Leans secure, restless when stuck', 'Argues it out, then moves on',
               ['Words of affirmation', 'Acts of service'], ['Words of affirmation', 'Quality time'], ['Says what he admires', 'Finds a way through'], ['Pushes to settle it now'])

SIGNALS = {
    'from': '2022-03-12', 'to': '2026-10-30', 'messages': 18420, 'perMonth': 330.0, 'trend': 'steady',
    'you': {'messages': 9810, 'starts': 1240, 'questions': 2210, 'thanks': 410, 'sorry': 96, 'warm': 1180, 'medianReplyMinutes': 9.0,
            'replyWithin5': 44, 'we': 31.2, 'iYou': 22.5, 'positive': 2140, 'negative': 610,
            'day': {'late': 9, 'morning': 31, 'afternoon': 24, 'evening': 36}, 'emoji': ['😂', '❤️', '🥹']},
    'partner': {'messages': 8610, 'starts': 860, 'questions': 1180, 'thanks': 520, 'sorry': 141, 'warm': 870, 'medianReplyMinutes': 14.0,
                'replyWithin5': 33, 'we': 27.8, 'iYou': 19.1, 'positive': 1690, 'negative': 520,
                'day': {'late': 22, 'morning': 14, 'afternoon': 27, 'evening': 37}, 'emoji': ['👍', '😂', '❤️']},
    'styleMatch': 0.81,
    'months': [['2022-%02d' % i, n] for i, n in zip(range(3, 13), [120, 410, 520, 560, 610, 590, 540, 500, 470, 480])]
              + [['2023-%02d' % i, n] for i, n in zip(range(1, 13), [450, 430, 420, 300, 210, 190, 200, 260, 330, 360, 380, 400])]
              + [['2024-%02d' % i, n] for i, n in zip(range(1, 13), [340, 330, 320, 300, 310, 290, 280, 300, 310, 290, 300, 320])]
              + [['2025-%02d' % i, n] for i, n in zip(range(1, 13), [280, 260, 250, 270, 240, 230, 220, 250, 260, 240, 230, 250])]
              + [['2026-%02d' % i, n] for i, n in zip(range(1, 11), [240, 230, 260, 250, 240, 230, 220, 240, 250, 260])],
    'fun': {'first': '12 March 2022', 'busiestDay': ['14 May 2022', 212], 'streak': 403, 'daysTalking': 1612},
    'years': [{'year': 2022, 'messages': 4400, 'positivePer100': 15.2, 'hardPer100': 1.1, 'warm': 690, 'sorry': 31, 'quickReplies': 48},
              {'year': 2023, 'messages': 3930, 'positivePer100': 11.8, 'hardPer100': 2.9, 'warm': 470, 'sorry': 74, 'quickReplies': 38},
              {'year': 2024, 'messages': 3690, 'positivePer100': 13.1, 'hardPer100': 1.9, 'warm': 420, 'sorry': 52, 'quickReplies': 37},
              {'year': 2025, 'messages': 2960, 'positivePer100': 13.6, 'hardPer100': 1.6, 'warm': 300, 'sorry': 44, 'quickReplies': 36},
              {'year': 2026, 'messages': 2420, 'positivePer100': 14.4, 'hardPer100': 1.3, 'warm': 170, 'sorry': 36, 'quickReplies': 37}],
    'repair': {'hard': 196, 'medianHoursBack': 3.5, 'backWithinDay': 0.86, 'ratioInside': 3.2,
               'byYear': {'2023': {'hard': 114, 'medianHoursBack': 6.0}, '2025': {'hard': 47, 'medianHoursBack': 2.5}}},
}


def profile(p, stage, core, overall, commit, mirror, topic, decisions, confidence, based, chat=None):
    out = {'v': 8, 'psyche': p, 'stage': stage, 'core': core, 'overall': dict(overall, scale=5), 'commit': commit, 'mirror': mirror,
           'topic': topic, 'decisions': decisions, 'desireTalk': False, 'rounds': [], 'sentAt': AT,
           'report': {'confidence': {'score': confidence, 'basedOn': based}}}
    if chat:
        out['chat'] = chat
    return out


# The chat as the one who added it shares it: its signals, its counts and how much of it was read in full (2,400 lines).
CHAT = {'signals': SIGNALS, 'counts': {'instagram': 6110, 'whatsapp': 12310}, 'source': 'instagram and whatsapp', 'sample': ['x' * 40] * 2400}


A = profile(EMILY, 'Living together', {'security': 2, 'appreciation': 1, 'connection': 1, 'needs': 1, 'disagreements': 1},
            {'you': 3, 'them': 2}, 2, {'appreciated': {'self': 'Time together', 'guess': 'Being told in words'}, 'repair': {'self': 'A little time first'}},
            'Chores and who does what', {'children': 'Yes', 'marriage': 'Yes', 'place': 'Where we are now'},
            86, ['1,204 of 1,204 captions', '318 of 2,940 own messages'], CHAT)
B = profile(LUCAS, None, {'security': 2, 'appreciation': 2, 'connection': 2, 'needs': 2, 'disagreements': 0},
            {'you': 3, 'them': 2}, 2, {'appreciated': {'self': 'Being told in words', 'guess': 'Something done for me'}, 'repair': {'self': 'To talk it through now'}},
            'Plans and timekeeping', {'children': 'Yes', 'marriage': 'Unsure', 'place': 'Another city or country'},
            83, ['268 posts and stories', '1,900 of his own messages'])
VIEW = m.couple_view(A, B)

READ = json.load(open(os.path.join(HERE, 'fixtures', 'together-sample-read.json')))
problems = m.check_read(READ, VIEW, True)
if problems:
    sys.exit('The sample read no longer passes check_read:\n- ' + '\n- '.join(problems))

BOX = {'v': 8, 'view': VIEW, 'read': READ, 'at': AT, 'firstAt': AT, 'rewrites': 0, 'chat': {'signals': SIGNALS}, 'chatOf': ['Emily', 'Lucas'],
       'psyches': {'a': EMILY, 'b': LUCAS},
       'sources': m.read_sources({'a': A, 'b': B}, VIEW)}
STATE = {'role': 'a', 'partner': 'Lucas', 'answers': {'safety': {'label': 'No'}}}

# Their Psyche Cards, as the page shows a couple's (tools/together-cards.mjs draws them from psycheai.io's own card).
import base64
pics = {}
for role, who in (('a', 'emily'), ('b', 'lucas')):
    f = os.path.join(APP, 'assets', 'together-card-%s.jpg' % who)
    if os.path.exists(f):
        pics[role] = 'data:image/jpeg;base64,' + base64.b64encode(open(f, 'rb').read()).decode()
m.SEEN.update(pics=pics, cards={'a': {'character': 'Mulan', 'mbti': 'ENFJ'}, 'b': {'character': 'Odysseus', 'mbti': 'ENTP'}})
html = m.page(BOX, STATE)
# A note at the top, so no one mistakes it for a real couple's read.
note = ('<div style="margin:0 auto;max-width:760px;padding:10px 16px;font:600 14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Inter,Roboto,Arial,sans-serif;'
        'color:#5b2a86;background:#f6effb;border-bottom:1px solid #ece4f1;text-align:center">A sample report for a made-up couple. Yours is written from your own Psyches, answers and messages.</div>')
html = html.replace('<body>', '<body>' + note, 1)
out = os.path.join(APP, 'assets', 'together-sample.html')
open(out, 'w', encoding='utf-8').write(html)
print(json.dumps({'ok': True, 'file': os.path.relpath(out, APP), 'bytes': len(html.encode('utf-8')), 'pillars': VIEW['pillars']}))
