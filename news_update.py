"""ESPN NFL headlines -> news.json (headline, link, time, related player ids). Run every few minutes by the scores workflow."""
import json, os, urllib.request, datetime
URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/news?limit=50"

def fetch_headlines():
    req = urllib.request.Request(URL, headers={"User-Agent": "gridiron-fantasy"})
    with urllib.request.urlopen(req, timeout=15) as r: j = json.load(r)
    out = []
    for a in j.get("articles") or []:
        h = a.get("headline")
        if not h: continue
        link = (((a.get("links") or {}).get("web") or {}).get("href"))
        ath = []
        for c in a.get("categories") or []:
            if c.get("type") == "athlete":
                aid = c.get("athleteId") or (c.get("athlete") or {}).get("id")
                if aid: ath.append(str(aid))
        out.append({"h": h, "u": link, "d": a.get("published") or a.get("lastModified"), "a": ath, "prem": bool(a.get("premium"))})
    return out

if __name__ == "__main__":
    old = json.load(open("news.json")) if os.path.exists("news.json") else {}
    try:
        items = fetch_headlines()
        if items and items != old.get("items"):
            json.dump({"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "items": items}, open("news.json", "w"), separators=(",", ":"))
            print("news.json updated:", len(items), "headlines")
        else: print("no change")
    except Exception as e:
        print("ESPN news unavailable, keeping the previous news.json:", e)
