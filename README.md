# Gridiron Fantasy: auto-updating version

This folder turns Gridiron Fantasy into a website that refreshes itself every 6 hours. GitHub
downloads the latest NFL data, rebuilds every projection, optionally syncs your Sleeper league,
and republishes the page for free.

## What updates automatically
- Weekly projections for every QB, RB, WR, and TE, with ranges, matchup grades, and Vegas totals
- Usage: snap share, target share, air-yards share, WOPR, carry share, red-zone chances
- Expected fantasy points from usage (the "luck check") and each player's game log
- Defense vs. position tables and strength of schedule
- Injury designations, depth-chart roles, and current teams after trades
- Rest-of-season and playoff-week projections
- Trends: buy-low, sell-high, risers, fallers, and playoff-schedule lists (the tested signal
  results are in `trends_val.json`, computed once from 2021-2025)
- Your Sleeper league (optional, see below): rosters, records, and lineup settings

## Built-in tools that update with the data
- **Cheat sheet:** must starts, don't starts, and sleepers for the week that matters. Once two or
  fewer games are left in a week, it moves on to next week automatically.
- **Boom and bust chances** for every player, from how real outcomes spread around similar
  projections (saved by the data update in the page's model data).
- **Matchup simulator** (My League): win chance against any opponent from thousands of simulated
  weeks, counting finished and in-progress games.
- **On pace for:** live projections during games.
- **Overall ranks** on every player card (rest of season and season so far).
- **Mock Draft:** draft against AI teams with different strategies using the site's rankings,
  with scarcity-aware recommendations, undo, and a graded result.

## News
- The **News** tab lists injury designations (with practice status), injured reserve moves,
  depth chart changes, and roster moves, detected from the official nflverse data every time
  the data update runs, plus the latest ESPN headlines (refreshed every few minutes), linked to
  the players they mention. Each player's card shows his own news.

## Projection accuracy
- Every player's projection is saved right before his game kicks off (`proj_history.json`) and
  compared with what he actually scored. The Learn tab shows the results week by week, and box
  scores show projected vs. actual points. This builds up automatically through the season.

## Live scores
- On your GitHub site, the **Live** tab and the score ticker load ESPN's public scoreboard and
  box scores directly every 30 seconds while games are on, with live fantasy points for every
  player and your own lineup (if ESPN allows browsers to load it directly; the Live tab shows
  which source it is using).
- Live games show down, distance, yard line, and a field graphic. Tapping a game drops its
  official box score, fantasy points, and team stats down right under it.
- As a backup, the `Live scores and news` workflow (`scores.yml`) saves copies to `live.json` and `news.json` about every
  10 minutes (GitHub Pages allows about 10 site updates per hour, and GitHub can delay scheduled jobs). The page falls back to it if your browser cannot reach ESPN. It only saves a new
  copy when a score or stat changed, so it does not flood your repository.
- Add `scores.yml` the same way as `update.yml` (step 4 below).

## One-time setup (about 10 minutes)
1. Create a free account at github.com and sign in.
2. Click **New repository**, name it `gridiron-fantasy`, choose **Public**, and create it.
3. Click **uploading an existing file** and drag in everything from this folder **except** the
   hidden `.github` folder and `.nojekyll` file. Click **Commit changes**. Then **Add file > Create
   new file**, name it `.nojekyll`, leave it empty, and commit (it tells GitHub to publish the files as-is).
4. Add the two schedule files: **Add file > Create new file**, name it
   `.github/workflows/update.yml`, paste in the contents of `update.yml` from this kit, and commit.
   Repeat for `.github/workflows/scores.yml`.
5. **Settings > Actions > General > Workflow permissions:** choose **Read and write
   permissions**, then **Save**.
6. **Settings > Pages:** set the branch to `main` and `/ (root)`, then **Save**. Your site will
   be at `https://YOUR-USERNAME.github.io/gridiron-fantasy/`.
7. Test it: **Actions** tab > **Update Gridiron Fantasy** > **Run workflow**. A run takes about
   5 to 10 minutes because it downloads several seasons of play-by-play data.

## Player photos and team logos
On your own site (and when you open the app file directly in a browser), real player headshots
and team logos load from ESPN's image servers. Player pages show the headshot in the animated
hero card, and anyone without a photo shows as a jersey in his team colors with his number. The
camera button at the top turns photos off. The claude.ai copy cannot load outside images, so it
always shows the jerseys and team-color tags. The photos and logos belong to the NFL, ESPN, and
the teams, so think about that before sharing a public site widely.

## Sync your Sleeper league automatically
1. Find your league ID: it is the long number in your league's web address on sleeper.com.
2. In your repository: **Settings > Secrets and variables > Actions > Variables tab >
   New repository variable**. Name it `SLEEPER_LEAGUE_ID` and paste the number.
3. Run the workflow again. Your league appears in the **My league** tab with every team's
   roster, record, and your league's lineup settings, and it stays in sync after trades and
   waiver moves.

Sleeper's league data is public and needs no password. ESPN and Yahoo require a login, so for
those leagues use the paste-in import on the page itself.

## Good to know
- The trained models (in `DTR.parquet`, `D25.parquet`, and the build scripts) are set up for
  the 2026 season. Before the 2027 season, ask Claude to retrain them with 2026 included.
- A free GitHub Pages site is public. If you sync a Sleeper league, team names and rosters
  will be visible to anyone with the link.
- Leagues you import by hand on the page are saved only in your own browser.
- GitHub can pause scheduled jobs on repositories with no activity for 60 days. If updates
  stop in the offseason, re-enable the workflow in the **Actions** tab.
- If a run fails, open it in the **Actions** tab to see the error. The usual cause is a data
  file that has not been published yet or was renamed.
- Data: nflverse (play-by-play, stats, snap counts, rosters, depth charts, injuries, schedule)
  and DynastyProcess (player ID crosswalk and dynasty values).
