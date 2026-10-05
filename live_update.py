"""Refresh live.json with ESPN's public scoreboard and box scores (run every few minutes on game days).
The page loads ESPN directly every 30 seconds when it can; live.json is the backup copy it falls back to."""
import json, os, time, urllib.request, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
EMAP = {"WSH": "WAS", "LAR": "LA"}
BASE = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/"

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-fantasy"})
    with urllib.request.urlopen(req, timeout=12) as r: return json.load(r)

def ab(c): k = ((c.get("team") or {}).get("abbreviation")) or "?"; return EMAP.get(k, k)

def games(sb):
    out = []
    for e in sb.get("events") or []:
        c = (e.get("competitions") or [{}])[0]; C = c.get("competitors") or []
        h = next((x for x in C if x.get("homeAway") == "home"), {}); a = next((x for x in C if x.get("homeAway") == "away"), {})
        s = e.get("status") or c.get("status") or {}; t = s.get("type") or {}; sit = c.get("situation") or {}; o = (c.get("odds") or [{}])[0]
        pp = any(k in (t.get("name") or "") for k in ("POSTPONED", "CANCELED", "SUSPENDED"))
        pre = pp or t.get("state") == "pre"; poss = None if pp else sit.get("possession")
        if len(C) < 2: continue
        out.append({"id": e.get("id"), "home": ab(h), "away": ab(a), "hs": None if pre else int(h.get("score") or 0), "as": None if pre else int(a.get("score") or 0),
                    "state": "pre" if pp else (t.get("state") or "pre"), "detail": (t.get("description") or "Postponed") if pp else (t.get("shortDetail") or t.get("detail") or ""), "clock": s.get("displayClock"), "q": s.get("period"),
                    "poss": (ab(h) if poss == h.get("id") else ab(a)) if poss else None, "dd": sit.get("shortDownDistanceText") or sit.get("downDistanceText"),
                    "ddl": sit.get("downDistanceText"), "down": sit.get("down"), "dist": sit.get("distance"), "yl": sit.get("yardLine"), "ptxt": sit.get("possessionText"),
                    "rz": bool(sit.get("isRedZone")), "kick": e.get("date"), "venue": (c.get("venue") or {}).get("fullName"),
                    "tv": (((c.get("broadcasts") or [{}])[0]).get("names") or [None])[0], "odds": o.get("details"), "ou": o.get("overUnder"),
                    "last": (sit.get("lastPlay") or {}).get("text")})
    return out

def box(sm):
    """Official box score: every stat category per team (as ESPN lists it), team stats, plus normalized lines for fantasy points."""
    players, cats, ts = {}, {}, {}
    for tp in ((sm.get("boxscore") or {}).get("players") or []):
        tm = EMAP.get((tp.get("team") or {}).get("abbreviation"), (tp.get("team") or {}).get("abbreviation"))
        for cat in tp.get("statistics") or []:
            keys = cat.get("keys") or []; lab = [str(x).upper() for x in (cat.get("labels") or [])]; n = cat.get("name")
            rows = []
            for at in cat.get("athletes") or []:
                nm = (at.get("athlete") or {}).get("displayName"); st = at.get("stats") or []
                if not nm: continue
                rows.append([nm] + [str(x) for x in st])
                r = players.setdefault((nm, tm), {"n": nm, "t": tm})
                def gv(k, l):
                    i = keys.index(k) if k in keys else (lab.index(l) if l in lab else -1)
                    return st[i] if 0 <= i < len(st) else None
                num = lambda v: float(v) if v not in (None, "", "--") and str(v).replace(".", "", 1).replace("-", "", 1).isdigit() else 0.0
                if n == "passing":
                    ca = str(gv("completions/passingAttempts", "C/ATT") or "0/0").split("/")
                    r.update(pc=int(num(ca[0])), pa=int(num(ca[1]) if len(ca) > 1 else 0), py=num(gv("passingYards", "YDS")), ptd=num(gv("passingTouchdowns", "TD")), int=num(gv("interceptions", "INT")))
                elif n == "rushing": r.update(ra=num(gv("rushingAttempts", "CAR")), ry=num(gv("rushingYards", "YDS")), rtd=num(gv("rushingTouchdowns", "TD")))
                elif n == "receiving": r.update(rec=num(gv("receptions", "REC")), ty=num(gv("receivingYards", "YDS")), rectd=num(gv("receivingTouchdowns", "TD")), tg=num(gv("receivingTargets", "TGTS")))
                elif n == "fumbles": r.update(fl=num(gv("fumblesLost", "LOST")))
            if rows: cats.setdefault(tm, []).append({"n": n, "t": cat.get("text") or (n or "").title(), "l": cat.get("labels") or [], "r": rows, "tot": [str(x) for x in (cat.get("totals") or [])]})
    for tt in ((sm.get("boxscore") or {}).get("teams") or []):
        tm = EMAP.get((tt.get("team") or {}).get("abbreviation"), (tt.get("team") or {}).get("abbreviation"))
        ts[tm] = [[s.get("label") or s.get("name"), s.get("displayValue")] for s in (tt.get("statistics") or []) if s.get("displayValue") is not None]
    return {"players": list(players.values()), "cats": cats, "ts": ts}

if __name__ == "__main__":
    old = json.load(open("live.json")) if os.path.exists("live.json") else {}
    try:
        sb = get(BASE + "scoreboard"); G = games(sb); B = {k: v for k, v in (old.get("box") or {}).items() if isinstance(v, dict)}
        need = [g for g in G if g["state"] == "in" or (g["state"] == "post" and not B.get(g["id"]))]
        t0 = time.time()
        with ThreadPoolExecutor(max_workers=4) as ex:   # box scores 4 at a time, and never more than ~2 minutes in total
            futs = {ex.submit(get, BASE + "summary?event=" + str(g["id"])): g["id"] for g in need}
            for f in as_completed(futs, timeout=150):
                try: B[futs[f]] = box(f.result())
                except Exception as e: print("box score unavailable for", futs[f], e)
                if time.time() - t0 > 140: print("time budget reached; keeping earlier box scores for the rest"); break
        new = {"src": "ESPN, refreshed every few minutes", "week": (sb.get("week") or {}).get("number"), "games": G, "box": {k: v for k, v in B.items() if any(str(x["id"]) == str(k) for x in G)}}
        if {k: old.get(k) for k in ("games", "box")} != {k: new[k] for k in ("games", "box")}:
            new["at"] = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")
            json.dump(new, open("live.json", "w"), separators=(",", ":")); print("live.json updated:", sum(g["state"] == "in" for g in G), "games live")
        else: print("no change")
    except Exception as e:
        print("ESPN unavailable, keeping the previous live.json:", e)
