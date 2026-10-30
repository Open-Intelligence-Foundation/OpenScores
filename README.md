# OpenScores

A daily leaderboard of **open source AI projects on GitHub**, ranked by their
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
   daily            select from catalog leaderboard.json      index.html / app.js
   cron             collect (incremental) history.json        methodology.html
                    score
```

Two scheduled workflows share the work. The **weekly catalog sweep** finds
every AI-related repository above the star threshold (about an hour of search
requests). The **daily refresh** takes the top `MAX_REPOS` of them, fully
collects the ones that are new or have not been fully collected for
`FULL_REFRESH_DAYS` days (at most `MAX_FULL_COLLECT` per run), brings the rest
up to date from a metrics cache with one light query per fifty repositories,
rescores everything and redeploys the site.

| Piece | Where |
|---|---|
| Discovery (topic search, licensing/star filters, categories) | `whitescore/discover.py`, `whitescore/config.py` |
| Metric collection (GraphQL + REST) | `whitescore/collect.py`, `whitescore/queries.py` |
| Score formulas (pure functions, unit-tested) | `whitescore/scoring.py` |
| Orchestration, history, output files | `whitescore/pipeline.py` |
| Incremental collection and metrics cache | `whitescore/incremental.py` |
| Leaderboard site (no build step) | `site/` |
| Daily cron + Pages deploy | `.github/workflows/daily.yml` |
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
anonymously). A fine-grained personal access token with public repository
read access is enough, with two caveats the collector handles on its own and
logs once per run: fine-grained tokens are refused GitHub Sponsors data (the
sponsorship signal then comes from funding links only) and the stargazer
timeline in GraphQL (recent stars are then read over REST instead). A classic
personal access token with no scopes has neither restriction.

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

Full daily run (discovery + up to `MAX_REPOS` projects):

```bash
.venv/bin/python -m whitescore
```

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
   personal access token with public repo read access. Without it the workflow
   falls back to the built-in `GITHUB_TOKEN`, which is capped at 1,000 API
   requests per hour, so set `MAX_REPOS` to roughly 150 or lower.
   If a run logs `not found or inaccessible` for every repository, the message
   now includes GitHub's own error; it almost always means the token lacks
   read access to public repositories.
4. Run the **Daily White Score refresh** workflow once manually from the Actions
   tab. It then runs every day at 06:17 UTC, commits the refreshed
   `site/data/*.json` plus `data/metrics-cache.json` and redeploys the site.
   With the default cap of 500 full collections per run, the first run scores
   500 projects and the second completes the 1,000; after that each run fully
   recollects about a third of them and refreshes the rest from cache.
5. The **Weekly catalog sweep** workflow runs on Sundays and can also be run
   manually. It rebuilds `site/data/catalog.json` and `CATALOG.md`; the daily
   refresh reads the committed catalog, so the sweep never delays scoring.

## Configuration

Everything tunable lives in `whitescore/config.py` and can be overridden with
environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MAX_REPOS` | 1000 | Repositories tracked per run (top by stars, after seeds) |
| `MAX_FULL_COLLECT` | 500 | Full collections per run; the rest are refreshed from cache (-1 = unlimited) |
| `FULL_REFRESH_DAYS` | 3 | A repository is fully recollected once it is this many days old in the cache |
| `LIGHT_BATCH` | 50 | Repositories per light-refresh GraphQL request |
| `MIN_STARS` | 500 | Discovery threshold |
| `PAGES_PER_TOPIC` | 2 | Search pages (100 results each) per topic |
| `REQUIRE_RECOGNIZED_LICENSE` | true | Drop repos whose license GitHub cannot identify |
| `MAX_COMMIT_PAGES` | 5 | Up to 500 recent commits sampled per repo |
| `WORKERS` | 3 | Concurrent repositories collected |
| `HISTORY_MAX_POINTS` | 120 | Daily score points kept per project |
| `BENCH_STARS`, `BENCH_FORKS`, … | see config | Popularity saturation benchmarks |

Add repositories that topic search misses to `seed_repos.txt`.

### API budget

A full collection costs about 10 requests and 7 GraphQL points per repository
(measured: 25 repositories took 262 requests and 185 points), so 500 full
collections use roughly 5,000 requests and 3,700 points, and the light refresh
of the other 500 adds 10 GraphQL requests. That fits a personal token's
5,000/hour limits for REST and GraphQL separately; when a limit is hit the
client sleeps until it resets, so a run may take up to about two hours. Raise
`MAX_FULL_COLLECT` only with a bigger budget (a GitHub App token), never by
pooling several personal tokens, which GitHub's terms forbid.

## Data files

* `site/data/leaderboard.json` – the latest run: every project with its five
  scores, the weighted components behind each score, raw metrics, category,
  7-day deltas, plus the weights and benchmarks used.
* `site/data/history.json` – per-project daily score series (up to 120 points)
  used for sparklines and deltas.
* `data/metrics-cache.json` – the last full collection of every tracked
  repository, used by the incremental daily refresh. Committed but not served.
