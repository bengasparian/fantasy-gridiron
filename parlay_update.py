#!/usr/bin/env python3
"""Parlay tracker for BFF.

Each run:
  1. Builds this week's suggested parlays with the same rules the page uses (Fantasy Help > Betting help).
  2. Saves them to parlay_history.json. They can refresh until the week's first kickoff, then they are locked.
  3. Grades every locked parlay from the official box scores: a leg is a hit, a miss, or void (player did not play).
     A parlay is won when no leg misses and at least one leg hits (voided legs drop out, as at sportsbooks).
  4. Adds the results to ff_data.json so the page can show "This week", "Past wins", and "Full record".
For entertainment only (21+ where legal).
"""
import json, math, os, datetime

D = json.load(open('ff_data.json'))
P = D['players']; PI = {p['id']: p for p in P}; NW = D['asof']['next_week']; SCHED = D.get('sched', {})
QS = json.load(open('prop_qs.json'))
HIST_FILE = 'parlay_history.json'
H = json.load(open(HIST_FILE)) if os.path.exists(HIST_FILE) else {}
NOW = datetime.datetime.fromisoformat(os.environ['BFF_NOW']) if os.environ.get('BFF_NOW') else datetime.datetime.now(datetime.timezone.utc)
POS = ['QB', 'RB', 'WR', 'TE']; GLI = {'py': 3, 'ptd': 4, 'ry': 7, 'ty': 11, 'rec': 9}

out = lambda p: p.get('inj') in ('Out', 'IR')
def wkproj(p, w):  # PPR projection for week w (same as the page in PPR)
    if w == p['nw']: return 0.0 if out(p) else float(p.get('proj') or 0)
    r = next((x for x in p.get('ros') or [] if x[0] == w), None); return float(r[2]) if r else 0.0

LEFT = {tm for tm, L in SCHED.items() for x in L if x[0] == NW and x[4] is None}
FW = NW + 1 if len(LEFT) / 2 <= 2 and NW < 18 else NW

def pg(p, i): return sum(r[i] or 0 for r in p['gl']) / len(p['gl'])
PRIOR = {}
for q in POS:
    L = [p for p in P if p['p'] == q and len(p.get('gl') or []) >= 3 and (p.get('fpg') or 0) >= (12 if q == 'QB' else 5 if q == 'TE' else 7)]
    mean = lambda f: sum(f(p) for p in L) / len(L) if L else 0.0
    PRIOR[q] = {'fp': mean(lambda p: p.get('fpg') or 0), 'td': mean(lambda p: pg(p, 8) + pg(p, 12)), **{k: mean(lambda p, i=i: pg(p, i)) for k, i in GLI.items()}}
def fpb(p): n = len(p['gl']); return ((p.get('fpg') or 0) * n + PRIOR[p['p']]['fp'] * 3) / (n + 3)
CTX = {}
for q in POS:
    v = sorted(wkproj(p, FW) / max(4, fpb(p)) for p in P if p['p'] == q and len(p.get('gl') or []) >= 2 and p['nw'] == FW and wkproj(p, FW) >= 6)
    CTX[q] = v[len(v) // 2] if v else 1.0

def prop_stats(p):
    G = p.get('gl') or []
    if len(G) < 2 or not wkproj(p, FW) > 0: return None
    n = len(G); pr = PRIOR[p['p']]; sh = lambda v, pv: (v * n + pv * 3) / (n + 3)
    raw = {'py': pg(p, 3), 'ptd': pg(p, 4), 'ry': pg(p, 7), 'ty': pg(p, 11), 'rec': pg(p, 9), 'td': pg(p, 8) + pg(p, 12)}
    base = {k: sh(v, pr['td'] if k == 'td' else pr[k]) for k, v in raw.items()}
    s = max(.8, min(1.2, (wkproj(p, FW) / max(4, fpb(p))) / (CTX.get(p['p']) or 1)))
    return {k: v * (s if k in ('td', 'ptd') else 1 + (s - 1) * .7) for k, v in base.items()}

def cdf(q, x):
    if x < q[0]: w = max(q[1] - q[0], .05) * 3; return max(0, .05 * (1 - (q[0] - x) / w))
    if x >= q[18]: w = max(q[18] - q[17], .05) * 3; return min(1, .95 + .05 * (x - q[18]) / w)
    for i in range(18):
        if x < q[i + 1]: d = q[i + 1] - q[i]; return (i + 1 + ((x - q[i]) / d if d > 0 else 0)) / 20
    return .95
def qkey(p, k):
    return {'py': 'pass_yds', 'ptd': 'pass_td', 'ry': 'rush_yds_qb' if p['p'] == 'QB' else 'rush_yds',
            'ty': 'rec_yds_rb' if p['p'] == 'RB' else 'rec_yds', 'rec': 'rec_rb' if p['p'] == 'RB' else 'rec'}.get(k)
def p_over(p, k, line, M):
    m = M[k]
    if not m > 0: return 0.0
    if k == 'td': return 1 - math.exp(-m)
    q = QS.get(qkey(p, k)); return 1 - cdf(q, (line + 1e-4) / m) if q else .5
stats_for = lambda p: ['py', 'ptd', 'ry'] if p['p'] == 'QB' else ['ry', 'rec', 'ty', 'td'] if p['p'] == 'RB' else ['rec', 'ty', 'td']

def suggest():
    C = [(p, prop_stats(p)) for p in P if not out(p) and p['nw'] == FW and wkproj(p, FW) >= 8]
    C = sorted([c for c in C if c[1]], key=lambda c: -wkproj(c[0], FW))[:60]
    legs = []
    for p, M in C:
        for k in stats_for(p):
            m = M[k]
            if not m > 0 or k == 'ptd': continue
            if k == 'td': legs.append(dict(p=p, k='td', line=.5, pr=p_over(p, 'td', .5, M))); continue
            lo = max(.5, math.floor(m * .55) + .5); mid = math.floor(m * .9) + .5
            legs.append(dict(p=p, k=k, line=lo, pr=p_over(p, k, lo, M))); legs.append(dict(p=p, k=k, line=mid, pr=p_over(p, k, mid, M)))
    def pick(L, n):
        o, games = [], set()
        for x in L:
            key = ''.join(sorted([x['p']['t'], x['p']['opp'] or '']))
            if key in games or any(y['p'] is x['p'] for y in o): continue
            games.add(key); o.append(x)
            if len(o) >= n: break
        return o
    by = lambda f, n: pick(sorted([x for x in legs if f(x)], key=lambda x: -x['pr']), n)
    sets = [('safe', by(lambda x: x['pr'] >= .8 and x['k'] != 'td', 3), 3), ('bal', by(lambda x: .55 <= x['pr'] <= .72 and x['k'] != 'td', 4), 4), ('long', by(lambda x: x['k'] == 'td' and .3 <= x['pr'] <= .55, 3), 3)]
    res = []
    for typ, L, n in sets:
        if len(L) != n: continue
        res.append({'type': typ, 'prob': round(math.prod(x['pr'] for x in L), 4),
                    'legs': [{'pid': x['p']['id'], 'n': x['p']['n'], 'pos': x['p']['p'], 't': x['p']['t'], 'opp': x['p']['opp'], 'k': x['k'], 'line': x['line'], 'lean': 'Over', 'pr': round(x['pr'], 4)} for x in L]})
    return res

# ---- record this week's suggestions until the first kickoff, then lock them
kicks = [datetime.datetime.fromisoformat(x[5]) for L in SCHED.values() for x in L if x[0] == FW and len(x) > 5 and x[5]]
first = min(kicks) if kicks else None
key = str(FW)
if first and NOW < first:
    H[key] = {'wk': FW, 'made': NOW.isoformat(timespec='minutes'), 'locks': first.isoformat(), 'parlays': suggest()}
    print(f'week {FW}: suggestions saved (they lock at the first kickoff, {first.isoformat()})')
elif key in H: print(f'week {FW}: locked since {H[key]["locks"]}')
else: print(f'week {FW}: first kickoff already passed before any suggestion was recorded; nothing to track this week')

# ---- grade every recorded week from official box scores
STAT = {'py': lambda r: r[3], 'ptd': lambda r: r[4], 'ry': lambda r: r[7], 'ty': lambda r: r[11], 'rec': lambda r: r[9], 'td': lambda r: r[8] + r[12]}
def final(team, w):
    e = next((x for x in SCHED.get(team, []) if x[0] == w), None); return bool(e and e[4] is not None)
for wk, W in H.items():
    w = int(wk)
    for par in W['parlays']:
        for lg in par['legs']:
            if lg.get('res') in ('hit', 'miss', 'void'): continue        # already graded: keep it fixed
            if not final(lg['t'], w): lg['res'] = 'pending'; continue
            p = PI.get(lg['pid']); row = next((r for r in (p or {}).get('gl') or [] if r[0] == w), None)
            played = row is not None or any(x[0] == w and (x[3] or 0) > 0 for x in (p or {}).get('wk') or [])
            if not played: lg['res'] = 'void'; lg['act'] = None; continue
            a = STAT[lg['k']](row) if row else 0; lg['act'] = a
            lg['res'] = 'hit' if (a > lg['line'] if lg['lean'] == 'Over' else a < lg['line']) else 'miss'
        R = [l['res'] for l in par['legs']]
        par['status'] = 'lost' if 'miss' in R else 'pending' if 'pending' in R else 'won' if 'hit' in R else 'void'
json.dump(H, open(HIST_FILE, 'w'), indent=1)
D['parl'] = {'fw': FW, 'start': min((int(k) for k in H), default=FW), 'weeks': [H[k] for k in sorted(H, key=int, reverse=True)]}
json.dump(D, open('ff_data.json', 'w'), separators=(',', ':'))
done = [p for W in H.values() for p in W['parlays'] if p['status'] in ('won', 'lost')]
print(f'parlay tracker: {len(H)} week(s) recorded, {sum(p["status"]=="won" for p in done)} won of {len(done)} graded')
