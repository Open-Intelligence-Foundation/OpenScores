# OpenScores

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
4. Run the **White Score refresh** workflow once manually from the Actions
   tab. It then runs every six hours (00:17, 06:17, 12:17 and 18:17 UTC),
   commits the refreshed `site/data/*.json` plus `data/metrics-cache.json` and
   `data/token-preferences.json`, and redeploys the site. With the default cap
   of 300 full collections per run, the first four runs build up the 1,000
   projects over a day; after that each run fully recollects the ~250 whose
   cached metrics are a day old and refreshes the rest from cache.
5. The **Weekly catalog sweep** workflow runs on Sundays and can also be run
   manually. It rebuilds `site/data/catalog.json` and `CATALOG.md`; the
   refresh reads the committed catalog, so the sweep never delays scoring.

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
lag on the light fields at the cost of another commit, Pages deploy and
Actions minutes per run. Four runs are about 80 Actions minutes a day
(2,400 a month, plus about 240 for the weekly sweep). Public repositories get
unlimited Actions minutes; a private repository on the Pro or Team plan has
3,000 a month, on the Free plan 2,000, so on the Free plan drop to three runs
a day (`cron: "17 */8 * * *"` with `MAX_FULL_COLLECT=400`).

Raise `MAX_FULL_COLLECT` only with a bigger budget (a GitHub App token), never
by pooling several personal tokens, which GitHub's terms forbid. The fallback
token is not pooling: a repository is read with one token per run.

## Data files

* `site/data/leaderboard.json` – the latest run: every project with its five
  scores, the weighted components behind each score, raw metrics, category,
  7-day deltas, plus the weights and benchmarks used.
* `site/data/history.json` – per-project daily score series (up to 120 points)
  used for sparklines and deltas. Several runs on one day update that day's
  point rather than adding more.
* `data/metrics-cache.json` – the last full collection of every tracked
  repository, used by the incremental refresh. Committed but not served.
* `data/token-preferences.json` – repositories that the primary token was
  refused and the fallback token could read. Committed but not served.
