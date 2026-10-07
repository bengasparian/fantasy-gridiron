#!/usr/bin/env python3
"""Predicted prop lines for BFF: what PrizePicks, Underdog and sportsbooks are expected to post this week.

Built the way books build lines, using only information from before the game:
  - this season's per-game numbers (quarterback games with fewer than 15 passes are left out as partial games),
    blended with last season's per-game numbers counted like 3 extra games,
  - scaled for the game: Vegas implied team total and the opposing defense,
  - set at the typical game (calibration factors below), ending in .5, only for players apps post lines for.
Tested on every 2025 game: overs hit 49-50% for every stat (a fair line splits 50/50).
Each line also gets our pick: our projection (injured teammates, role changes, matchup) against that line, blended
50/50 with the line itself. In 2025, picks shown at 54% or higher won 57.7%; passing-yard picks showed no edge, so the
page never picks passing yards. Results feed ff_data.json for the page and parlay_update.py.
"""
import json, math, os, datetime, pandas as pd

D = json.load(open('ff_data.json')); P = D['players']; NW = D['asof']['next_week']; SEASON = D['asof'].get('season') or datetime.date.today().year
SCHED = D.get('sched', {}); DVP = D.get('dvp', {}); QS = json.load(open('prop_qs.json'))
# tuned on every 2025 game (only pre-game information): prior-season weight W, Vegas a, defense b, context cap, calibration c
PAR = {'py': dict(W=5, a=.5, b=.5, cap=.15, c=.95), 'ptd': dict(W=3, a=.5, b=0, cap=.15, c=.95), 'ry': dict(W=3, a=.25, b=0, cap=.15, c=.86),
       'rec': dict(W=5, a=.25, b=.25, cap=.15, c=.85), 'ty': dict(W=5, a=.5, b=.25, cap=.30, c=.81)}
W = 3   # prior-season weight for usage (targets, carries) and fantasy baseline
BT = {'season': 2025, 'over': {'py': .49, 'ptd': .499, 'ry': .501, 'rec': .501, 'ty': .499}, 'mae': {'py': 62.0, 'ptd': 1.0, 'ry': 23.1, 'rec': 1.7, 'ty': 22.3},
      'picks': {'n': 1669, 'won': .577, 'by': {'ptd': .59, 'ry': .613, 'rec': .565, 'ty': .581}, 'py': .528}}
GLI = {'py': 3, 'ptd': 4, 'ry': 7, 'rec': 9, 'ty': 11}; STATS = {'QB': ['py', 'ptd', 'ry'], 'RB': ['ry', 'rec', 'ty'], 'WR': ['rec', 'ty'], 'TE': ['rec', 'ty']}
COL = {'py': 'passing_yards', 'ptd': 'passing_tds', 'ry': 'rushing_yards', 'rec': 'receptions', 'ty': 'receiving_yards'}

LEFT = {tm for tm, L in SCHED.items() for x in L if x[0] == NW and x[4] is None}
FW = NW + 1 if len(LEFT) / 2 <= 2 and NW < 18 else NW
# last season per game (books lean on it early in the year)
PRI = {}
f = f'stats_player_week_{SEASON - 1}.parquet'
if os.path.exists(f):
    s = pd.read_parquet(f); s = s[(s.season_type == 'REG') & s.position.isin(['QB', 'RB', 'WR', 'TE'])]
    s = s[(s.position != 'QB') | (s.attempts.fillna(0) >= 15)]
    g = s.groupby('player_id').agg(**{k: (c, 'mean') for k, c in COL.items()}, n=('week', 'size'), tg=('targets', 'mean'), car=('carries', 'mean'), fp=('fantasy_points_ppr', 'mean'))
    PRI = {pid: r.to_dict() for pid, r in g[g.n >= 4].iterrows()}
else: print(f'{f} not found: lines use this season only')

def cdf(q, x):
    if x < q[0]: return max(0, .05 * (1 - (q[0] - x) / (max(q[1] - q[0], .05) * 3)))
    if x >= q[18]: return min(1, .95 + .05 * (x - q[18]) / (max(q[18] - q[17], .05) * 3))
    for i in range(18):
        if x < q[i + 1]: d = q[i + 1] - q[i]; return (i + 1 + ((x - q[i]) / d if d > 0 else 0)) / 20
    return .95
QK = lambda pos, k: {'py': 'pass_yds', 'ptd': 'pass_td', 'ry': 'rush_yds_qb' if pos == 'QB' else 'rush_yds', 'ty': 'rec_yds_rb' if pos == 'RB' else 'rec_yds', 'rec': 'rec_rb' if pos == 'RB' else 'rec'}[k]
def wkproj(p):
    if p.get('inj') in ('Out', 'IR', 'Doubtful'): return 0.0
    if p['nw'] == FW: return float(p.get('proj') or 0)
    r = next((x for x in p.get('ros') or [] if x[0] == FW), None); return float(r[2]) if r else 0.0
def sch(tm): return next((x for x in SCHED.get(tm, []) if x[0] == FW), None)

# typical starting-QB numbers, used for quarterbacks without a usable last season (tested: fixes new starters' bias)
_qb = [[r for r in (p.get('gl') or []) if r[0] < FW and r[2] >= 15] for p in P if p['p'] == 'QB']
_qb = [g for g in _qb if len(g) >= 3]
QBTYP = {'py': sum(sum(r[3] for r in g) / len(g) for g in _qb) / len(_qb), 'ptd': sum(sum(r[4] for r in g) / len(g) for g in _qb) / len(_qb)} if len(_qb) >= 8 else {'py': 215.0, 'ptd': 1.4}
rows = []
for p in P:
    pos = p['p']; e = sch(p['t'])
    if not e or not e[1] or p['nw'] != FW or wkproj(p) < (10 if p['p'] == 'QB' else 4): continue   # apps post lines for expected starters and regular players
    G = [r for r in (p.get('gl') or []) if r[0] < FW]; full = [r for r in G if pos != 'QB' or r[2] >= 15]; n = len(full); pr = PRI.get(p['id'])
    if n == 0 and not pr: continue
    if pos == 'QB' and ((G and G[-1][2] < 15) or (not G and not pr)): continue          # only expected starters get QB lines
    # numbers are worked out right here for this player (no deferred lookups)
    def blend(a, b, n=n, w=W):
        if a is not None and b is not None: return (a * n + b * w) / (n + w)
        return a if a is not None else b
    this = {k: (sum(r[i] for r in full) / n if n else None) for k, i in list(GLI.items()) + [('tg', 10), ('car', 6)]}
    prior = {k: (pr[k] if pr else (QBTYP[k] if pos == 'QB' and k in QBTYP else None)) for k in GLI}
    base = {k: blend(this[k], prior[k], w=PAR[k]['W']) for k in GLI}
    tg = blend(this['tg'], pr['tg'] if pr else None) or 0; car = blend(this['car'], pr['car'] if pr else None) or 0
    fpb = blend(p.get('fpg') if n else None, pr['fp'] if pr else None)
    it = e[3] if e[3] is not None else 22.5; dv = ((DVP.get(e[1]) or {}).get(pos) or [None, None, 1.0])[2] or 1.0
    rows.append(dict(p=p, pos=pos, n=n, base=base, tg=tg, car=car, fpb=fpb, it=it, dv=dv, opp=e[1], kick=e[5] if len(e) > 5 else None))
# our projection relative to the book-style fantasy baseline, centered by position (removes any league-wide tilt)
S = {}
for r in rows:
    if r['fpb'] and r['fpb'] > 0: r['s'] = wkproj(r['p']) / r['fpb']; S.setdefault(r['pos'], []).append(r['s'])
MED = {q: sorted(v)[len(v) // 2] for q, v in S.items()}
lines = []
for r in rows:
    pos, p = r['pos'], r['p']
    sn = max(.8, min(1.25, r['s'] / MED[pos])) if r.get('s') and MED.get(pos) else 1.0
    for k in STATS[pos]:
        ok = {'py': True, 'ptd': True, 'ry': pos == 'RB' and r['car'] >= 8 or pos == 'QB' and (r['base']['ry'] or 0) >= 12,
              'rec': (pos == 'RB' and r['tg'] >= 2.5) or (pos in ('WR', 'TE') and r['tg'] >= 4), 'ty': (pos == 'RB' and r['tg'] >= 2.5) or (pos in ('WR', 'TE') and r['tg'] >= 4)}[k]
        if not ok: continue
        base = r['base'][k]
        if not base or base <= 0: continue
        pk = PAR[k]; ctx = max(1 - pk['cap'], min(1 + pk['cap'], (r['it'] / 22.5) ** pk['a'] * r['dv'] ** pk['b']))
        bm = base * ctx; raw = bm * pk['c']
        line = (.5 if raw < 1.15 else 1.5 if raw < 2.1 else 2.5) if k == 'ptd' else math.floor(raw) + .5
        if k == 'py' and line < 150.5: continue
        mm = bm * (sn if k == 'ptd' else 1 + (sn - 1) * .7)                                 # our projection for the stat
        if k == 'ptd': pm = 1 - sum(math.exp(-mm) * mm ** i / math.factorial(i) for i in range(int(line) + 1))   # touchdowns: count (Poisson) math
        else: pm = 1 - cdf(QS[QK(pos, k)], (line + 1e-4) / max(mm, .05))
        po = min(.62, max(.38, .5 * pm + .25))                                            # chance of the over, blended with the line; capped (tested)
        lines.append({'pid': p['id'], 't': p['t'], 'opp': r['opp'], 'k': k, 'line': line, 'mm': round(mm, 2), 'po': round(po, 4), 'kick': r['kick']})
D['lines'] = {'wk': FW, 'at': datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='minutes'), 'bt': BT, 'lines': lines}
json.dump(D, open('ff_data.json', 'w'), separators=(',', ':'))
print(f'predicted lines: {len(lines)} for week {FW} ({sum(1 for l in lines if l["k"] != "py" and max(l["po"], 1 - l["po"]) >= .54)} picks at 54%+)')
