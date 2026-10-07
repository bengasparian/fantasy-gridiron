#!/usr/bin/env python3
"""Real player-prop lines for BFF (PrizePicks, Underdog, DraftKings, FanDuel) from The Odds API (the-odds-api.com).

Needs a free or paid API key saved in GitHub as the secret ODDS_API_KEY. Without one, nothing is fetched and the site shows
no parlay suggestions (it never invents lines).

Credits: each game costs (markets returned) x 1 credit (4 bookmakers count as 1 region); the list of games is free.
The script spreads your remaining monthly credits over the rest of the month: it refreshes only when a refresh is due,
so the free plan (500 credits) refreshes a few times a month and a paid plan refreshes every few hours.
"""
import json, os, re, sys, datetime, urllib.request, urllib.parse, calendar

KEY = os.environ.get('ODDS_API_KEY', '').strip()
BASE = os.environ.get('ODDS_API_BASE', 'https://api.the-odds-api.com').rstrip('/')
NOW = datetime.datetime.fromisoformat(os.environ['BFF_NOW']) if os.environ.get('BFF_NOW') else datetime.datetime.now(datetime.timezone.utc)
MIN_HOURS = float(os.environ.get('PROPS_MIN_HOURS', '2'))      # never refresh more often than this
RESERVE = int(os.environ.get('PROPS_RESERVE', '20'))           # credits kept back for safety
BOOKS = ['prizepicks', 'underdog', 'draftkings', 'fanduel']      # standard (non-alternate) lines only
MARKETS = {'player_pass_yds': 'py', 'player_pass_tds': 'ptd', 'player_rush_yds': 'ry', 'player_receptions': 'rec', 'player_reception_yds': 'ty'}
TEAMS = {'Arizona Cardinals': 'ARI', 'Atlanta Falcons': 'ATL', 'Baltimore Ravens': 'BAL', 'Buffalo Bills': 'BUF', 'Carolina Panthers': 'CAR',
 'Chicago Bears': 'CHI', 'Cincinnati Bengals': 'CIN', 'Cleveland Browns': 'CLE', 'Dallas Cowboys': 'DAL', 'Denver Broncos': 'DEN', 'Detroit Lions': 'DET',
 'Green Bay Packers': 'GB', 'Houston Texans': 'HOU', 'Indianapolis Colts': 'IND', 'Jacksonville Jaguars': 'JAX', 'Kansas City Chiefs': 'KC',
 'Las Vegas Raiders': 'LV', 'Los Angeles Chargers': 'LAC', 'Los Angeles Rams': 'LA', 'Miami Dolphins': 'MIA', 'Minnesota Vikings': 'MIN',
 'New England Patriots': 'NE', 'New Orleans Saints': 'NO', 'New York Giants': 'NYG', 'New York Jets': 'NYJ', 'Philadelphia Eagles': 'PHI',
 'Pittsburgh Steelers': 'PIT', 'San Francisco 49ers': 'SF', 'Seattle Seahawks': 'SEA', 'Tampa Bay Buccaneers': 'TB', 'Tennessee Titans': 'TEN',
 'Washington Commanders': 'WAS'}
OUT = 'props.json'
prev = json.load(open(OUT)) if os.path.exists(OUT) else {}

def norm(n):
    n = re.sub(r"[.'’]", '', (n or '').lower()).replace('-', ' ')
    return ' '.join(w for w in n.split() if w not in ('jr', 'sr', 'ii', 'iii', 'iv', 'v'))
def get(path, **q):
    q['apiKey'] = KEY
    req = urllib.request.Request(f"{BASE}{path}?{urllib.parse.urlencode(q)}", headers={'User-Agent': 'BFF-fantasy-site'})
    with urllib.request.urlopen(req, timeout=20) as r:
        h = {k.lower(): v for k, v in r.headers.items()}
        return json.load(r), int(h.get('x-requests-remaining', '-1') or -1), int(h.get('x-requests-last', '0') or 0)

if not KEY:
    print('ODDS_API_KEY not set: no real prop lines fetched (the site will not suggest parlays without real lines)'); sys.exit(0)
if not os.path.exists('bet_inputs.json'):
    print('bet_inputs.json missing (run the data update first); skipping'); sys.exit(0)
INP = json.load(open('bet_inputs.json')); ROSTER = {}
for p in INP['players']: ROSTER.setdefault(p['t'], []).append(p)

# ---- is a refresh due? spread the remaining credits over the rest of the month
last = datetime.datetime.fromisoformat(prev['at']) if prev.get('at') else None
remaining = prev.get('remaining')
cost = prev.get('cost') or 75
month_end = datetime.datetime(NOW.year + (NOW.month == 12), NOW.month % 12 + 1, 1, tzinfo=datetime.timezone.utc)
if remaining is not None and last and (last.year, last.month) != (NOW.year, NOW.month): remaining = None   # credits reset monthly
hours_left = max(1.0, (month_end - NOW).total_seconds() / 3600)
if remaining is not None:
    refreshes = max(0, (remaining - RESERVE) // max(1, cost))
    if refreshes < 1: print(f'only {remaining} credits left this month; keeping the current lines'); sys.exit(0)
    interval = min(72.0, max(MIN_HOURS, hours_left / refreshes))
else: interval = MIN_HOURS
if last and (NOW - last).total_seconds() / 3600 < interval:
    print(f'lines are {(NOW - last).total_seconds() / 3600:.1f}h old; next refresh after {interval:.1f}h'); sys.exit(0)

# ---- this week's games that have not started (the events list is free)
try: events, rem, _ = get('/v4/sports/americanfootball_nfl/events')
except Exception as ex:   # unreachable, bad key (401), out of credits (429)...: keep the previous lines, never fail the job
    print(f'The Odds API not reachable ({str(ex)[:120]}); keeping the previous lines'); sys.exit(0)
if rem >= 0: remaining = rem
up = [e for e in events if NOW < datetime.datetime.fromisoformat(e['commence_time'].replace('Z', '+00:00')) < NOW + datetime.timedelta(days=7)]
if not up: print('no NFL games in the next 7 days; nothing to fetch'); sys.exit(0)
lines, unmatched, spent = [], set(), 0
for e in up:
    if remaining is not None and 0 <= remaining < len(MARKETS) + RESERVE: print('credit floor reached; stopping early'); break
    try: data, rem, last_cost = get(f"/v4/sports/americanfootball_nfl/events/{e['id']}/odds", bookmakers=','.join(BOOKS), markets=','.join(MARKETS), oddsFormat='american')
    except Exception as ex: print(f"skipped one game ({str(ex)[:80]})"); continue
    spent += last_cost; remaining = rem if rem >= 0 else remaining
    home, away = TEAMS.get(e['home_team']), TEAMS.get(e['away_team'])
    if not home or not away: continue
    cand = {}
    for p in ROSTER.get(home, []) + ROSTER.get(away, []): cand.setdefault(norm(p['n']), p)
    for bk in data.get('bookmakers', []):
        if bk['key'] not in BOOKS: continue
        for mk in bk.get('markets', []):
            k = MARKETS.get(mk['key'])
            if not k: continue
            sides = {}
            for o in mk.get('outcomes', []):
                if o.get('point') is None or o.get('name') not in ('Over', 'Under'): continue
                sides.setdefault((o.get('description'), o['point']), {})[o['name']] = o.get('price')
            for (name, point), pr in sides.items():
                p = cand.get(norm(name))
                if not p:
                    toks = norm(name).split()
                    hits = [q for nn, q in cand.items() if toks and nn.split()[-1:] == toks[-1:] and nn[:1] == toks[0][:1]]
                    p = hits[0] if len(hits) == 1 else None
                if not p: unmatched.add(name); continue
                lines.append({'pid': p['id'], 't': p['t'], 'opp': away if p['t'] == home else home, 'k': k, 'line': float(point),
                              'book': bk['key'], 'op': pr.get('Over'), 'up': pr.get('Under'), 'kick': e['commence_time']})
refreshes_left = max(0, ((remaining or 0) - RESERVE) // max(1, spent or cost)) if remaining is not None else 0
interval = min(72.0, max(MIN_HOURS, hours_left / refreshes_left)) if refreshes_left else 72.0
if not lines and prev.get('lines'): print('no lines came back this time; keeping the previous lines'); sys.exit(0)
out = {'at': NOW.isoformat(timespec='minutes'), 'src': 'The Odds API', 'books': BOOKS, 'remaining': remaining, 'cost': spent or cost,
       'interval_h': round(interval, 1), 'games': len(up), 'lines': lines, 'unmatched': len(unmatched)}
json.dump(out, open(OUT, 'w'), separators=(',', ':'))
print(f'props: {len(lines)} real lines for {len(up)} games ({len(unmatched)} names not matched), {spent} credits used, {remaining} left this month')
