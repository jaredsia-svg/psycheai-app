# Builds assets/together-sample.html, the sample Psyche Together report served at /together/sample
# (README "A sample Psyche Together report"): the real report page (together/bin/together.py page) for a
# made-up couple, Emily and Daniel. Emily is psycheai.io's fictional sample reader. Nothing here is anyone's
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


EMILY = psyche('Emily', 'Mulan', 'ENFJ', 'Organiser with a warm centre and a quiet battery', [72, 81, 58, 77, 44],
               {'benevolence': 84, 'achievement': 71, 'stimulation': 52}, ['The quiet organiser', 'Generous with attention', 'Bursts, then recovery'],
               ['Loyalty', 'Kindness', 'Growth'], 'Leans secure, with a self-reliant streak', 'Smooths it over, raises it later',
               ['Acts of service', 'Quality time'], ['Quality time'], ['Shows up', 'Remembers the details'], ['Carries more than she says'])
DANIEL = psyche('Daniel', 'Odysseus', 'ISTP', 'Calm fixer who thinks with his hands', [66, 55, 38, 63, 36],
                {'self-direction': 82, 'stimulation': 68, 'security': 57}, ['Quiet problem-solver', 'Says it with a plan', 'Needs a reset after people'],
                ['Freedom', 'Honesty', 'Craft'], 'Leans secure, needs space first', 'Goes quiet, then comes back with a fix',
                ['Acts of service', 'Physical touch'], ['Words of affirmation'], ['Steady in a crisis', 'Keeps his word'], ['Slow to say how he feels'])

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
    'years': [{'year': 2022, 'messages': 4400, 'positivePer100': 15.2, 'hardPer100': 1.1, 'warm': 690, 'sorry': 31, 'quickReplies': 2100},
              {'year': 2023, 'messages': 3930, 'positivePer100': 11.8, 'hardPer100': 2.9, 'warm': 470, 'sorry': 74, 'quickReplies': 1500},
              {'year': 2024, 'messages': 3690, 'positivePer100': 13.1, 'hardPer100': 1.9, 'warm': 420, 'sorry': 52, 'quickReplies': 1350},
              {'year': 2025, 'messages': 2960, 'positivePer100': 13.6, 'hardPer100': 1.6, 'warm': 300, 'sorry': 44, 'quickReplies': 1080},
              {'year': 2026, 'messages': 2420, 'positivePer100': 14.4, 'hardPer100': 1.3, 'warm': 170, 'sorry': 36, 'quickReplies': 900}],
    'repair': {'hard': 196, 'medianHoursBack': 3.5, 'backWithinDay': 0.86, 'ratioInside': 3.2,
               'byYear': {'2023': {'hard': 114, 'medianHoursBack': 6.0}, '2025': {'hard': 47, 'medianHoursBack': 2.5}}},
}


def profile(p, stage, core, overall, commit, mirror, topic, decisions):
    return {'v': 8, 'psyche': p, 'stage': stage, 'core': core, 'overall': dict(overall, scale=5), 'commit': commit, 'mirror': mirror,
            'topic': topic, 'decisions': decisions, 'desireTalk': False, 'rounds': [], 'sentAt': AT, 'chat': {'signals': SIGNALS}}


A = profile(EMILY, 'Living together', {'security': 2, 'appreciation': 1, 'connection': 2, 'needs': 1, 'disagreements': 1},
            {'you': 3, 'them': 2}, 2, {'appreciated': {'self': 'Time together', 'guess': 'Something done for me'}, 'repair': {'self': 'To talk it through now'}},
            'Plans and timekeeping', {'children': 'Yes', 'marriage': 'Yes', 'place': 'Where we are now'})
B = profile(DANIEL, None, {'security': 2, 'appreciation': 2, 'connection': 1, 'needs': 2, 'disagreements': 0},
            {'you': 3, 'them': 2}, 2, {'appreciated': {'self': 'Being told in words', 'guess': 'Time together'}, 'repair': {'self': 'A little time first'}},
            'Chores and who does what', {'children': 'Yes', 'marriage': 'Unsure', 'place': 'Another city or country'})
VIEW = m.couple_view(A, B)

READ = json.load(open(os.path.join(HERE, 'fixtures', 'together-sample-read.json')))
problems = m.check_read(READ, VIEW, True)
if problems:
    sys.exit('The sample read no longer passes check_read:\n- ' + '\n- '.join(problems))

BOX = {'v': 8, 'view': VIEW, 'read': READ, 'at': AT, 'firstAt': AT, 'rewrites': 0, 'chat': {'signals': SIGNALS}, 'chatOf': ['Emily', 'Daniel'],
       'psyches': {'a': EMILY, 'b': DANIEL},
       'sources': {'people': [{'name': 'Emily', 'confidence': 78, 'level': 'high', 'basedOn': ['412 posts and stories', '2,300 of her own messages']},
                              {'name': 'Daniel', 'confidence': 71, 'level': 'moderate', 'basedOn': ['168 posts and stories', '1,900 of his own messages']}],
                   'chat': {'messages': 18420, 'counts': {'instagram': 6110, 'whatsapp': 12310}, 'source': 'instagram and whatsapp',
                            'from': '2022-03-12', 'to': '2026-10-30', 'sampleLines': 2400, 'sampleChars': 96000},
                   'checkin': {'questions': 8, 'decisions': 3, 'topics': True, 'commitment': True, 'know': 0, 'mirrors': 2, 'dreams': 0},
                   'confidence': {'score': 74, 'level': 'moderate', 'weakest': 71, 'talk': 80, 'checkin': 70}}}
STATE = {'role': 'a', 'partner': 'Daniel', 'answers': {'safety': {'label': 'No'}}}

html = m.page(BOX, STATE)
# A note at the top, so no one mistakes it for a real couple's read.
note = ('<div style="margin:0 auto;max-width:760px;padding:10px 16px;font:600 14px/1.4 -apple-system,BlinkMacSystemFont,Segoe UI,Inter,Roboto,Arial,sans-serif;'
        'color:#5b2a86;background:#f6effb;border-bottom:1px solid #ece4f1;text-align:center">A sample report for a made-up couple. Yours is written from your own Psyches, answers and messages.</div>')
html = html.replace('<body>', '<body>' + note, 1)
out = os.path.join(APP, 'assets', 'together-sample.html')
open(out, 'w', encoding='utf-8').write(html)
print(json.dumps({'ok': True, 'file': os.path.relpath(out, APP), 'bytes': len(html.encode('utf-8')), 'pillars': VIEW['pillars']}))
