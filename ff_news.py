"""News items detected from official data: injuries, injured reserve, depth chart changes, roster moves.
Every item is computed from nflverse feeds, so the list refreshes itself whenever the data updates."""
import io, urllib.request, datetime
import pandas as pd
B = 'https://github.com/nflverse/nflverse-data/releases/download/'
FPOS = {'QB': 'QB', 'RB': 'RB', 'HB': 'RB', 'FB': 'RB', 'WR': 'WR', 'LWR': 'WR', 'RWR': 'WR', 'SWR': 'WR', 'TE': 'TE'}

def _get(rel):
    with urllib.request.urlopen(B + rel, timeout=180) as r: return pd.read_parquet(io.BytesIO(r.read()))

def build_news(season, relevant_ids=None, max_items=220):
    """relevant_ids: player ids that matter for fantasy (gets a 'key' flag)."""
    rel = set(relevant_ids or [])
    out = []
    def add(kind, pid, name, pos, team, text, when, extra=None):
        if not name or not isinstance(name, str): return
        d = {'k': kind, 'id': pid if isinstance(pid, str) and pid else None, 'n': name, 'p': pos, 't': team, 'x': text, 'd': when, 'key': bool(pid in rel)}
        if extra: d.update(extra)
        out.append(d)
    # ---- injuries: latest report for each team
    try:
        inj = _get(f'injuries/injuries_{season}.parquet')
        inj = inj[inj.position.isin(['QB', 'RB', 'WR', 'TE', 'FB'])]
        inj = inj[inj.week == inj.groupby('team').week.transform('max')]
        for r in inj.itertuples():
            st = r.report_status if isinstance(r.report_status, str) and r.report_status.strip() else None
            pr = str(r.practice_status or '')
            prs = 'did not practice' if 'Did Not' in pr else 'limited in practice' if 'Limited' in pr else 'full practice' if 'Full' in pr else None
            if not st and prs in (None, 'full practice'): continue
            what = (r.report_primary_injury if isinstance(r.report_primary_injury, str) and r.report_primary_injury.strip() else '') or (r.practice_primary_injury if isinstance(r.practice_primary_injury, str) else '')
            txt = (f"{st} for week {int(r.week)}" if st else f"On the week {int(r.week)} injury report") + (f" ({what.lower()})" if what else '') + (f", {prs}" if prs else '')
            dm = getattr(r, 'date_modified', None); when = pd.to_datetime(dm, utc=True, errors='coerce') if dm is not None else pd.NaT
            add('inj', r.gsis_id, r.full_name, FPOS.get(r.position, r.position), r.team, txt, f'week {int(r.week)} injury report' if pd.isna(when) else when.isoformat(), {'st': st or prs})
    except Exception as e: print('injury news skipped:', e)
    # ---- roster: injured reserve and team changes between the last two roster weeks
    try:
        wr = _get(f'weekly_rosters/roster_weekly_{season}.parquet'); wr = wr[wr.position.isin(['QB', 'RB', 'WR', 'TE', 'FB'])].dropna(subset=['gsis_id'])
        wks = sorted(wr.week.unique())
        if len(wks) >= 2:
            a = wr[wr.week == wks[-2]].drop_duplicates('gsis_id').set_index('gsis_id'); b = wr[wr.week == wks[-1]].drop_duplicates('gsis_id').set_index('gsis_id')
            stamp = f"week {int(wks[-1])} roster"
            for pid in b.index:
                nb = b.loc[pid]; pos = FPOS.get(nb.position, nb.position)
                if pid in a.index:
                    na = a.loc[pid]
                    if na.team != nb.team: add('move', pid, nb.full_name, pos, nb.team, f"Joined {nb.team} from {na.team}", stamp, {'from': na.team})
                    elif na.status != 'RES' and nb.status == 'RES': add('ir', pid, nb.full_name, pos, nb.team, 'Placed on injured reserve', stamp)
                    elif na.status == 'RES' and nb.status == 'ACT': add('ir', pid, nb.full_name, pos, nb.team, 'Activated from injured reserve', stamp)
                    elif na.status in ('DEV', 'INA') and nb.status == 'ACT' and na.status == 'DEV': add('move', pid, nb.full_name, pos, nb.team, 'Promoted from the practice squad', stamp)
                elif nb.status == 'ACT': add('move', pid, nb.full_name, pos, nb.team, f"Added to the {nb.team} roster", stamp)
            for pid in a.index.difference(b.index):
                na = a.loc[pid]
                if na.status == 'ACT' and pid in rel: add('move', pid, na.full_name, FPOS.get(na.position, na.position), na.team, f"No longer on the {na.team} roster", stamp)
    except Exception as e: print('roster news skipped:', e)
    # ---- depth charts: latest chart vs the one about a week earlier
    try:
        dc = _get(f'depth_charts/depth_charts_{season}.parquet'); dc = dc[dc.pos_abb.isin(FPOS)].dropna(subset=['gsis_id'])
        dc['pg'] = dc.pos_abb.map(FPOS); dc['dt'] = pd.to_datetime(dc.dt, utc=True, errors='coerce'); dts = sorted(dc.dt.dropna().unique())
        if len(dts) >= 2:
            last = dts[-1]; older = [d for d in dts if d <= last - pd.Timedelta(days=6)]; base = older[-1] if older else dts[0]
            A = dc[dc.dt == base].sort_values('pos_rank').drop_duplicates(['gsis_id']).set_index('gsis_id'); Bd = dc[dc.dt == last].sort_values('pos_rank').drop_duplicates(['gsis_id']).set_index('gsis_id')
            for pid in Bd.index:
                nb = Bd.loc[pid]; nr = int(nb.pos_rank)
                if nr > 3: continue
                if pid in A.index and A.loc[pid].team == nb.team:
                    orr = int(A.loc[pid].pos_rank)
                    if orr != nr: add('depth', pid, nb.player_name, nb.pg, nb.team, f"{'Moved up' if nr < orr else 'Moved down'} the depth chart: {nb.pg}{orr} to {nb.pg}{nr}", pd.Timestamp(last).isoformat(), {'up': nr < orr})
                elif pid not in A.index and nr <= 2: add('depth', pid, nb.player_name, nb.pg, nb.team, f"New on the depth chart at {nb.pg}{nr}", pd.Timestamp(last).isoformat(), {'up': True})
    except Exception as e: print('depth chart news skipped:', e)
    # keep fantasy-relevant items first, then newest
    out.sort(key=lambda d: (not d['key'], str(d['d'] or '')), reverse=False)
    key = [d for d in out if d['key']]; other = [d for d in out if not d['key']]
    return (key + other)[:max_items]

if __name__ == '__main__':
    import json
    D = json.load(open('ff_data.json')); rel = {p['id'] for p in D['players'] if (p.get('prev') or 0) >= 6 or (p.get('fpg') or 0) >= 6 or (p.get('role') or 'X9')[-1] in '12'}
    N = build_news(2026, rel); from collections import Counter
    print('items:', len(N), Counter(d['k'] for d in N), '| fantasy-relevant:', sum(d['key'] for d in N))
    for k in ['inj', 'ir', 'depth', 'move']:
        for d in [x for x in N if x['k'] == k and x['key']][:3]: print(f"  [{k}] {d['n']} ({d['p']}, {d['t']}): {d['x']}  ·  {d['d']}")
