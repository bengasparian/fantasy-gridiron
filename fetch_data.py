"""Download the public data the pipeline needs (nflverse + DynastyProcess) into this folder."""
import sys, urllib.request
SEASON = int(sys.argv[1]) if len(sys.argv) > 1 else 2026
B = "https://github.com/nflverse/nflverse-data/releases/download/"
files = {}
for y in range(2021, SEASON + 1):
    files[f"pbp_{y}.parquet"] = B + f"pbp/play_by_play_{y}.parquet"
    files[f"stats_player_week_{y}.parquet"] = B + f"stats_player/stats_player_week_{y}.parquet"
    files[f"snap_counts_{y}.parquet"] = B + f"snap_counts/snap_counts_{y}.parquet"
files["db_playerids.csv"] = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/db_playerids.csv"
files["values.csv"] = "https://raw.githubusercontent.com/dynastyprocess/data/master/files/values-players.csv"
for name, url in files.items():
    with urllib.request.urlopen(url, timeout=300) as r, open(name, "wb") as f:
        f.write(r.read())
    print("downloaded", name)
