"""Optional: pull a Sleeper league (public API, no login needed) into ff_data.json.
Set the SLEEPER_LEAGUE_ID environment variable (a repository variable in GitHub) to turn it on."""
import json, os, sys, urllib.request, datetime

def build_league(league, rosters, users, players):
    sid = {p["sid"]: p["id"] for p in players if p.get("sid")}
    names = {u["user_id"]: (u.get("metadata") or {}).get("team_name") or u.get("display_name") for u in users}
    teams = []
    for r in rosters:
        ids = [sid[s] for s in (r.get("players") or []) if s in sid]
        st = r.get("settings") or {}
        teams.append({"id": r["roster_id"], "name": names.get(r.get("owner_id")) or f"Team {r['roster_id']}", "players": ids,
                      "rec": {"w": st.get("wins", 0), "l": st.get("losses", 0), "t": st.get("ties", 0),
                              "pf": (st.get("fpts") or 0) + (st.get("fpts_decimal") or 0) / 100}})
    slots = {"QB": 0, "RB": 0, "WR": 0, "TE": 0, "FLEX": 0, "SF": 0}
    for x in league.get("roster_positions") or []:
        if x in slots: slots[x] += 1
        elif x == "SUPER_FLEX": slots["SF"] += 1
        elif x in ("WRRB_FLEX", "REC_FLEX"): slots["FLEX"] += 1
    return {"src": "sleeper-sync", "name": league.get("name") or "Sleeper league", "teams": teams, "slots": slots,
            "when": datetime.date.today().isoformat()}

def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "gridiron-fantasy"})
    with urllib.request.urlopen(req, timeout=60) as r: return json.load(r)

if __name__ == "__main__":
    lid = os.environ.get("SLEEPER_LEAGUE_ID", "").strip()
    if not lid: print("SLEEPER_LEAGUE_ID not set; skipping league sync"); sys.exit(0)
    D = json.load(open("ff_data.json"))
    base = f"https://api.sleeper.app/v1/league/{lid}"
    try:
        D["league"] = build_league(get(base), get(base + "/rosters"), get(base + "/users"), D["players"])
        json.dump(D, open("ff_data.json", "w"), separators=(",", ":"), allow_nan=False)
        print("synced", D["league"]["name"], len(D["league"]["teams"]), "teams")
    except Exception as e:   # never break the site because Sleeper was unreachable
        print("Sleeper sync failed, keeping the page without a synced league:", e)
