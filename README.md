# OpenScores

A daily leaderboard of **open source AI projects on GitHub**, ranked by their
**White Scores**: five independent 0–100 measures of a project's maturity,
health, popularity, risk and sustainability.

Once a day a collector polls GitHub's API, discovers AI-related repositories
(by topic), pulls ~60 metrics per project, computes the scores, and publishes a
static site with the leaderboard, per-project breakdowns and score history.

## How it works

```
GitHub API ──► whitescore (Python) ──► site/data/*.json ──► static site (GitHub Pages)
   daily            discover            leaderboard.json      index.html / app.js
   cron             collect             history.json          methodology.html
                    score
```

| Piece | Where |
|---|---|
| Discovery (topic search, licensing/star filters, categories) | `whitescore/discover.py`, `whitescore/config.py` |
| Metric collection (GraphQL + REST) | `whitescore/collect.py`, `whitescore/queries.py` |
| Score formulas (pure functions, unit-tested) | `whitescore/scoring.py` |
| Orchestration, history, output files | `whitescore/pipeline.py` |
| Leaderboard site (no build step) | `site/` |
| Daily cron + Pages deploy | `.github/workflows/daily.yml` |

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
read access is enough. Fine-grained tokens cannot read GitHub Sponsors data,
so with one of those the sponsorship signal comes from funding links
(`FUNDING.yml`) only; the collector detects this and logs it once.

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
   `site/data/*.json` and redeploys the site.

## Configuration

Everything tunable lives in `whitescore/config.py` and can be overridden with
environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `MAX_REPOS` | 300 | Repositories tracked per run (top by stars, after seeds) |
| `MIN_STARS` | 500 | Discovery threshold |
| `PAGES_PER_TOPIC` | 2 | Search pages (100 results each) per topic |
| `REQUIRE_RECOGNIZED_LICENSE` | true | Drop repos whose license GitHub cannot identify |
| `MAX_COMMIT_PAGES` | 5 | Up to 500 recent commits sampled per repo |
| `WORKERS` | 3 | Concurrent repositories collected |
| `BENCH_STARS`, `BENCH_FORKS`, … | see config | Popularity saturation benchmarks |

Add repositories that topic search misses to `seed_repos.txt`.

### API budget

A full run of 300 repositories uses roughly 1,000–1,500 requests and
2,500–3,500 GraphQL points, well inside the 5,000/hour limits of a personal
token. The client backs off automatically on rate limits.

## Data files

* `site/data/leaderboard.json` – the latest run: every project with its five
  scores, the weighted components behind each score, raw metrics, category,
  7-day deltas, plus the weights and benchmarks used.
* `site/data/history.json` – per-project daily score series (up to 400 points)
  used for sparklines and deltas.
