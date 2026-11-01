# OpenScores

OpenScores is run by the [Open Intelligence Foundation](https://openintelligence.foundation).

A continuously refreshed leaderboard of **open source AI projects on GitHub**, ranked by their
**White Scores**: five independent 0–100 measures of a project's maturity,
health, popularity, risk and sustainability. The default ranking is the Overall
White Score, a weighted blend of all five (maturity, health and popularity 0.25
each, sustainability 0.15, inverted risk 0.10).

Once a day a collector polls GitHub's API, discovers AI-related repositories
(by topic), pulls ~60 metrics per project, computes the scores, and publishes a
static site with the leaderboard, per-project breakdowns and score history.

## How it works

```
GitHub API ──► whitescore (Python) ──► site/data/*.json ──► static site (GitHub Pages)
   weekly           catalog sweep       catalog.json          catalog.html
   6-hourly         select from catalog leaderboard.json      index.html / app.js
   cron             collect (incremental) history.json        methodology.html
                    score
```

Two scheduled workflows share the work. The **weekly catalog sweep** finds
every AI-related repository above the star threshold (about an hour of search
requests). The **refresh**, four times a day, takes the top `MAX_REPOS` of
them, fully collects the ones that are new or have not been fully collected
for `FULL_REFRESH_DAYS` days (at most `MAX_FULL_COLLECT` per run), brings the
rest up to date from a metrics cache with one light query per fifty
repositories, rescores everything and redeploys the site. With the defaults
every project is fully recollected once a day and its stars, forks, open
issues, pull requests and last-commit date are never more than six hours old.

| Piece | Where |
|---|---|
| Discovery (topic search, licensing/star filters, categories) | `whitescore/discover.py`, `whitescore/config.py` |
| Metric collection (GraphQL + REST) | `whitescore/collect.py`, `whitescore/queries.py` |
| Score formulas (pure functions, unit-tested) | `whitescore/scoring.py` |
| Orchestration, history, output files | `whitescore/pipeline.py` |
| Incremental collection and metrics cache | `whitescore/incremental.py` |
| Leaderboard site (no build step) | `site/` |
| Six-hourly refresh + Pages deploy | `.github/workflows/daily.yml` |
| Weekly catalog sweep | `.github/workflows/catalog.yml` |

The scoring methodology, including every formula and benchmark, is on the
site's Methodology page (`site/methodology.html`).

## The catalog

`python -m whitescore.catalog` sweeps GitHub for every AI-related repository:
170 topics (star-banded to get past the 1,000-results-per-query cap), then a
name/description keyword pass for well-known repos that carry no topics, then
a seed list fetched directly. It writes two files:

* `site/data/catalog.json` – the full catalog (stars, forks, language, license,
  topics, category, AI-signal score, curated-list flag), used by the collector.
* `site/data/catalog-web.json` – a slim copy with short keys that the site's
  **Catalog** page loads (GitHub Pages serves it gzipped).

Neither file is committed (together they are about 28 MB and change weekly);
see *Data files* below for where they live and how to fetch the latest ones.

Each repository gets an **AI signal** so that projects merely tagged `ai` or
`chat` (databases, UI kits, chat servers) are marked *AI-adjacent* and kept out
of the leaderboard. Awesome-lists, courses and paper collections are kept in a
"Courses, Papers & Curated Lists" category. See the Methodology page for the
scoring. The sweep works without a token (10 search requests/minute, about two
hours for everything) and three times faster with one. Useful flags:

```bash
.venv/bin/python -m whitescore.catalog --resume --skip-topics   # only the keyword + seed passes
```

```bash
.venv/bin/python -m whitescore.catalog --recategorize           # no network: re-apply category rules
```

## Run it locally

Requires Python 3.8+ and a GitHub token (the GraphQL API cannot be used
anonymously). A **classic** personal access token with the `public_repo` scope
is the best primary token: it reads everything the collector asks for. A
fine-grained token also works, with two caveats the collector handles on its
own and logs once per run: fine-grained tokens are refused GitHub Sponsors
data (the sponsorship signal then comes from funding links only) and the
stargazer timeline in GraphQL (recent stars are then read over REST instead).

Some organizations refuse one kind of token outright (SAML single sign-on, or
an organization policy against classic tokens); GitHub then answers every
request for their repositories with FORBIDDEN. Set `GITHUB_TOKEN_FALLBACK` to
a token of the other kind and the collector retries a refused repository with
it, remembers the repositories that needed it in
`data/token-preferences.json`, and starts with the fallback for them (and for
other repositories of the same owner) on later runs. This is an access
fallback only: each repository is read with one token per run, never both.

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

```bash
export GITHUB_TOKEN=ghp_yourtoken
```

Score a handful of repos without discovery (fast, good for a first run):

```bash
.venv/bin/python -m whitescore --repos huggingface/transformers vllm-project/vllm ollama/ollama
```

Full run (catalog selection + up to `MAX_REPOS` projects):

```bash
.venv/bin/python -m whitescore
```

A fresh clone has no data files: the leaderboard, catalog and metrics cache
are not committed (see *Data files*). To start from the live site's latest
data instead of collecting everything yourself, download them first (replace
the host with your own Pages URL if you run a fork):

```bash
site=https://openscores.io
for f in leaderboard history catalog catalog-web; do curl -fsSL "$site/data/$f.json" -o "site/data/$f.json"; done
for f in metrics-cache token-preferences; do curl -fsSL "$site/data/$f.json" -o "data/$f.json"; done
```

With the catalog and metrics cache in place, `python -m whitescore` behaves
exactly as a workflow run does: it skips live discovery and only fully
recollects the repositories whose cached metrics are stale.

Serve the site:

```bash
.venv/bin/python -m http.server 8791 --directory site
```

Then open http://localhost:8791.

Without a token you can still preview the site using synthetic data (it is
clearly labelled as a sample on the page):

```bash
.venv/bin/python scripts/make_sample_data.py
```

Tests:

```bash
.venv/bin/python -m pytest -q
```

## Deploy with GitHub Actions + Pages

1. Push this repository to GitHub.
2. In **Settings → Pages**, set the source to **GitHub Actions**.
3. (Recommended) add a repository secret `WHITESCORE_GITHUB_TOKEN` containing a
   classic personal access token with the `public_repo` scope. Without it the
   workflow falls back to the built-in `GITHUB_TOKEN`, which is capped at 1,000
   API requests per hour, so set `MAX_FULL_COLLECT` to roughly 80 or lower.
   If a run logs `not found or inaccessible` for every repository, the message
   includes GitHub's own error; it almost always means the token lacks read
   access to public repositories.
   Optionally add `WHITESCORE_GITHUB_TOKEN_FALLBACK` with a fine-grained token
   (public repositories, read-only) for organizations that refuse classic
   tokens; see *Run it locally* above.
4. Run the **Weekly catalog sweep** workflow once manually from the Actions
   tab, so the first refresh has a candidate pool (without one it falls back
   to live topic discovery). It then runs on Sundays, rebuilds
   `site/data/catalog.json` and `catalog-web.json`, hands them to the refresh
   through the Actions cache, and commits only `CATALOG.md`. The catalog page
   on the site picks up a new sweep at the next refresh, within six hours.
5. Run the **White Score refresh** workflow once manually. It then runs every
   six hours (00:17, 06:17, 12:17 and 18:17 UTC): it restores the previous
   run's `data/metrics-cache.json`, `data/token-preferences.json` and
   `site/data/history.json` from the Actions cache, collects and scores,
   saves the new state to the cache, and deploys `site/` to Pages straight
   from the run, with copies of the two state files alongside the leaderboard.
   Nothing is committed except `site/data/history.json`, once a day. With the
   default cap of 300 full collections per run, the first four runs build up
   the 1,000 projects over a day; after that each run fully recollects the
   ~250 whose cached metrics are a day old and refreshes the rest from cache.

The cache is a convenience, not the source of truth. GitHub drops cache
entries that have not been used for a week, so if the workflow is paused for
longer (or runs for the first time in a fork) the refresh fetches the state
files from the live site instead, which always has the last deployment. Only
a repository that has never deployed starts from nothing: that first run
scores as many repositories as its full-collection cap allows and the board
fills up over the following runs. The one daily commit is a durable record
of the score series and also counts as repository activity, so GitHub does
not disable the schedule after 60 days without commits.

## Configuration

Everything tunable lives in `whitescore/config.py` and can be overridden with
environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MAX_REPOS` | 1000 | Repositories tracked per run (top by stars, after seeds) |
| `MAX_FULL_COLLECT` | 300 | Full collections per run; the rest are refreshed from cache (-1 = unlimited) |
| `FULL_REFRESH_DAYS` | 1 | A repository is fully recollected once it is this many days old in the cache |
| `GITHUB_TOKEN_FALLBACK` | unset | Second token, of the other kind, for repositories whose organization refuses the primary |
| `LIGHT_BATCH` | 50 | Repositories per light-refresh GraphQL request |
| `MIN_STARS` | 500 | Discovery threshold |
| `PAGES_PER_TOPIC` | 2 | Search pages (100 results each) per topic |
| `REQUIRE_RECOGNIZED_LICENSE` | true | Drop repos whose license GitHub cannot identify |
| `MAX_COMMIT_PAGES` | 5 | Up to 500 recent commits sampled per repo |
| `WORKERS` | 6 | Concurrent repositories collected |
| `HISTORY_MAX_POINTS` | 120 | Daily score points kept per project |
| `BENCH_STARS`, `BENCH_FORKS`, … | see config | Popularity saturation benchmarks |

Add repositories that topic search misses to `seed_repos.txt`.

### API budget

A full collection costs about 10 requests and 7 GraphQL points per repository
(measured: 25 repositories took 262 requests and 185 points). A personal token
has 5,000 requests per hour for REST and 5,000 points per hour for GraphQL,
counted separately, so one hour buys at most about 475 full collections even
if every request landed in the same bucket. The light refresh is almost free:
1,000 repositories cost 20 GraphQL requests.

The schedule follows from that. Four runs a day with `FULL_REFRESH_DAYS=1`
means each run fully recollects about 250 repositories (~2,600 requests and
~1,850 points, roughly half of one hour's budget, leaving room for retries)
and light-refreshes the other 750, in 15 to 20 minutes with six workers.
Running more often would not make the full metrics fresher, since the daily
budget only covers each repository once; it would only shorten the six-hour
lag on the light fields at the cost of another Pages deploy and more
Actions minutes per run. Four runs are about 80 Actions minutes a day
(2,400 a month, plus about 240 for the weekly sweep). Public repositories get
unlimited Actions minutes; a private repository on the Pro or Team plan has
3,000 a month, on the Free plan 2,000, so on the Free plan drop to three runs
a day (`cron: "17 */8 * * *"` with `MAX_FULL_COLLECT=400`).

Raise `MAX_FULL_COLLECT` only with a bigger budget (a GitHub App token), never
by pooling several personal tokens, which GitHub's terms forbid. The fallback
token is not pooling: a repository is read with one token per run.

## Data files

The collector reads and writes plain JSON files on disk, the same ones
whether it runs locally or in Actions:

* `site/data/leaderboard.json` – the latest run: every project with its five
  scores, the weighted components behind each score, raw metrics, category,
  7-day deltas, plus the weights and benchmarks used.
* `site/data/history.json` – per-project daily score series (up to 120 points)
  used for sparklines and deltas. Several runs on one day update that day's
  point rather than adding more.
* `site/data/catalog.json` and `catalog-web.json` – the weekly catalog sweep
  (see *The catalog*).
* `data/metrics-cache.json` – the last full collection of every tracked
  repository, used by the incremental refresh.
* `data/token-preferences.json` – repositories that the primary token was
  refused and the fallback token could read.

Where each file lives:

| File | In git (`main`) | Actions cache | Live site (`/data/…`) |
| --- | --- | --- | --- |
| `leaderboard.json` | no | no (rebuilt every run) | yes |
| `history.json` | yes, one commit a day | yes | yes |
| `catalog.json`, `catalog-web.json` | no | yes, from the weekly sweep | yes |
| `metrics-cache.json`, `token-preferences.json` | no | yes | yes, as a fallback copy |
| `CATALOG.md` | yes, weekly | no | no |

To inspect the latest data, open `https://<your-pages-host>/data/<file>`
(for this deployment,
https://openscores.io/data/leaderboard.json
and so on), or download all of them with the loop in *Run it locally*. The
leaderboard and catalog carry a `generated_at` timestamp, history points are
dated, and each metrics-cache entry records its `collected_at`. The cached
copies can also be downloaded from the **Caches** page of the Actions tab.
Run output is git-ignored, so a local run never dirties the working tree
beyond `site/data/history.json`.
