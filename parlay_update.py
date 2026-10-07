#!/usr/bin/env python3
"""Parlay tracker for BFF, built only from real posted lines (props.json from props_update.py).

Each run:
  1. Reads player projections (ff_data.json in the data job, bet_inputs.json in the score job) and the latest real lines.
  2. Picks this week's best 2-pick, 3-pick and 5-pick from posted lines (PrizePicks first, then Underdog, then sportsbooks),
     over or under, one leg per player and per game. Picks can change as lines move until the week's first kickoff,
     then they lock. No real lines = no suggestions.
  3. Grades every locked parlay from official box scores (hit, miss, or void if the player did not play).
  4. Writes parlay_history.json (the record) and parlays.json (what the page shows).
For entertainment only (21+ where legal). Chances blend our projection with what the line itself implies.
"""
import json, math, os, datetime

SRC = 'ff_data.json' if os.path.exists('ff_data.json') else 'bet_inputs.json'
D = json.load(open(SRC)); P = D['players']; PI = {p['id']: p for p in P}; NW = D['asof']['next_week']; SCHED = D.get('sched', {})
if SRC == 'ff_data.json':   # hand the score job a compact copy of what it needs
    keep = ('id', 'n', 'p', 't', 'opp', 'nw', 'proj', 'ros', 'inj', 'fpg', 'rpg', 'gl', 'wk')
    json.dump({'asof': D['asof'], 'sched': SCHED, 'players': [{k: p.get(k) for k in keep} for p in P]}, open('bet_inputs.json', 'w'), separators=(',', ':'))
QS = json.load(open('prop_qs.json'))
PROPS = json.load(open('props.json')) if os.path.exists('props.json') else {}
HIST_FILE = 'parlay_history.json'
H = json.load(open(HIST_FILE)) if os.path.exists(HIST_FILE) else {}
NOW = datetime.datetime.fromisoformat(os.environ['BFF_NOW']) if os.environ.get('BFF_NOW') else datetime.datetime.now(datetime.timezone.utc)
POS = ['QB', 'RB', 'WR', 'TE']; GLI = {'py': 3, 'ptd': 4, 'ry': 7, 'ty': 11, 'rec': 9}
BOOK_ORDER = ['prizepicks', 'underdog', 'draftkings', 'fanduel']

out = lambda p: p.get('inj') in ('Out', 'IR', 'Doubtful')
def wkproj(p, w):
    if w == p['nw']: return 0.0 if p.get('inj') in ('Out', 'IR') else float(p.get('proj') or 0)
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
def model_means(p):
    G = p.get('gl') or []
    if len(G) < 2 or not wkproj(p, FW) > 0: return None
    n = len(G); pr = PRIOR[p['p']]; sh = lambda v, pv: (v * n + pv * 3) / (n + 3)
    base = {k: sh(pg(p, i), pr[k]) for k, i in GLI.items()}
    s = max(.8, min(1.2, (wkproj(p, FW) / max(4, fpb(p))) / (CTX.get(p['p']) or 1)))
    return {k: v * (s if k == 'ptd' else 1 + (s - 1) * .7) for k, v in base.items()}
def cdf(q, x):
    if x < q[0]: w = max(q[1] - q[0], .05) * 3; return max(0, .05 * (1 - (q[0] - x) / w))
    if x >= q[18]: w = max(q[18] - q[17], .05) * 3; return min(1, .95 + .05 * (x - q[18]) / w)
    for i in range(18):
        if x < q[i + 1]: d = q[i + 1] - q[i]; return (i + 1 + ((x - q[i]) / d if d > 0 else 0)) / 20
    return .95
def qkey(p, k):
    return {'py': 'pass_yds', 'ptd': 'pass_td', 'ry': 'rush_yds_qb' if p['p'] == 'QB' else 'rush_yds',
            'ty': 'rec_yds_rb' if p['p'] == 'RB' else 'rec_yds', 'rec': 'rec_rb' if p['p'] == 'RB' else 'rec'}[k]
def dec(a): return 1 + (a / 100 if a > 0 else 100 / -a) if a else None
def mkt_over(op, up):
    """The market's chance of the over at this line, with the bookmaker's margin removed. Pick'em standard lines are built to be 50/50."""
    o, u = dec(op), dec(up)
    if not o or not u or op == up: return .5
    return (1 / o) / (1 / o + 1 / u)
def p_over(p, k, line, M, op=None, up=None):
    """Chance he goes over a posted line: our model's chance at that exact line, blended 50/50 with the market's chance."""
    q = QS[qkey(p, k)]; m = max(M[k], .05)
    return .5 * (1 - cdf(q, (line + 1e-4) / m)) + .5 * mkt_over(op, up)

def suggest():
    L = PROPS.get('lines') or []
    if not L: return []
    best = {}
    for x in L:   # one posted line per player and stat, from the preferred app/book
        key = (x['pid'], x['k']); r = BOOK_ORDER.index(x['book']) if x['book'] in BOOK_ORDER else 9
        if key not in best or r < best[key][0]: best[key] = (r, x)
    legs = []
    for _, x in best.values():
        p = PI.get(x['pid'])
        if not p or out(p) or p['nw'] != FW: continue
        if datetime.datetime.fromisoformat(x['kick'].replace('Z', '+00:00')) <= NOW: continue
        M = model_means(p)
        if not M: continue
        po = p_over(p, x['k'], x['line'], M, x.get('op'), x.get('up')); lean = 'Over' if po >= .5 else 'Under'; ch = max(po, 1 - po)
        if ch >= .54: legs.append({**x, 'lean': lean, 'pr': round(ch, 4)})
    legs.sort(key=lambda l: -l['pr'])
    def pick(n):
        o, games, people = [], set(), set()
        for l in legs:
            g = ''.join(sorted([l['t'], l['opp']]))
            if g in games or l['pid'] in people: continue
            games.add(g); people.add(l['pid']); o.append(l)
            if len(o) == n: return o
        return None
    res = []
    for typ, n in (('safe', 2), ('bal', 3), ('long', 5)):
        sel = pick(n)
        if sel: res.append({'type': typ, 'prob': round(math.prod(l['pr'] for l in sel), 4),
                            'legs': [{**{k: l.get(k) for k in ('pid', 't', 'opp', 'k', 'line', 'lean', 'pr', 'book', 'op', 'up')}, 'n': PI[l['pid']]['n'], 'pos': PI[l['pid']]['p']} for l in sel]})
    return res

kicks = [datetime.datetime.fromisoformat(x[5]) for L in SCHED.values() for x in L if x[0] == FW and len(x) > 5 and x[5]]
first = min(kicks) if kicks else None; key = str(FW)
if first and NOW < first:
    sug = suggest()
    old = H.get(key, {}).get('parlays')
    if sug != old or key not in H:
        H[key] = {'wk': FW, 'made': NOW.isoformat(timespec='minutes'), 'locks': first.isoformat(), 'lines_at': PROPS.get('at'), 'src': PROPS.get('src'), 'parlays': sug}
    print(f'week {FW}: {len(sug)} suggestion(s) from {len(PROPS.get("lines") or [])} real lines; they lock at {first.isoformat()}' if sug else f'week {FW}: no real lines yet, so no suggestions')
elif key in H: print(f'week {FW}: locked since {H[key]["locks"]}')
else: print(f'week {FW}: first kickoff passed before any suggestion was recorded')

STAT = {'py': lambda r: r[3], 'ptd': lambda r: r[4], 'ry': lambda r: r[7], 'ty': lambda r: r[11], 'rec': lambda r: r[9], 'td': lambda r: r[8] + r[12]}
def final(team, w):
    e = next((x for x in SCHED.get(team, []) if x[0] == w), None); return bool(e and e[4] is not None)
for wk, W in H.items():
    w = int(wk)
    for par in W['parlays']:
        for lg in par['legs']:
            if lg.get('res') in ('hit', 'miss', 'void'): continue
            if not final(lg['t'], w): lg['res'] = 'pending'; continue
            p = PI.get(lg['pid']); row = next((r for r in (p or {}).get('gl') or [] if r[0] == w), None)
            played = row is not None or any(x[0] == w and (x[3] or 0) > 0 for x in (p or {}).get('wk') or [])
            if not played: lg['res'] = 'void'; lg['act'] = None; continue
            a = STAT[lg['k']](row) if row else 0; lg['act'] = a
            lg['res'] = 'hit' if (a > lg['line'] if lg['lean'] == 'Over' else a < lg['line']) else 'miss'
        R = [l['res'] for l in par['legs']]
        par['status'] = 'lost' if 'miss' in R else 'pending' if 'pending' in R else 'won' if 'hit' in R else 'void'
json.dump(H, open(HIST_FILE, 'w'), indent=1)
page = {'fw': FW, 'start': min((int(k) for k in H), default=FW), 'weeks': [H[k] for k in sorted(H, key=int, reverse=True)]}
new = json.dumps({'parl': page, 'props': PROPS}, separators=(',', ':'))
if not os.path.exists('parlays.json') or open('parlays.json').read() != new: open('parlays.json', 'w').write(new)
if SRC == 'ff_data.json':
    D['parl'] = page; D['props'] = PROPS; json.dump(D, open('ff_data.json', 'w'), separators=(',', ':'))
done = [p for W in H.values() for p in W['parlays'] if p['status'] in ('won', 'lost')]
print(f'parlay tracker: {len(H)} week(s) recorded, {sum(p["status"] == "won" for p in done)} won of {len(done)} graded')
