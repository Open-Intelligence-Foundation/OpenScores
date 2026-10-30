"""Pure scoring functions for the White Score suite.

All functions take a flat ``metrics`` dict (see ``collect.py`` for the keys)
and return 0-100 component scores plus a weighted total. Nothing here touches
the network, which keeps the formulas unit-testable.
"""
from __future__ import annotations

import math
from typing import Dict, Optional

from . import config

Metrics = Dict[str, object]


# ---------------------------------------------------------------------------
# Normalisation helpers
# ---------------------------------------------------------------------------
def n_log(x: Optional[float], benchmark: float) -> float:
    """Log-normalised count: 100 * min(1, ln(1+x) / ln(1+b))."""
    if x is None or x <= 0:
        return 0.0
    return 100.0 * min(1.0, math.log1p(x) / math.log1p(benchmark))


def n_ratio(x: Optional[float]) -> float:
    """Ratio already in [0, 1] -> 0-100, clamped."""
    if x is None:
        return 0.0
    return 100.0 * min(1.0, max(0.0, x))


def n_recency(days: Optional[float], tau: float) -> float:
    """Exponential decay: 100 * e^(-d / tau). ``None`` (never happened) -> 0."""
    if days is None:
        return 0.0
    return 100.0 * math.exp(-max(0.0, days) / tau)


def _flag(metrics: Metrics, key: str) -> int:
    return 1 if metrics.get(key) else 0


def _num(metrics: Metrics, key: str, default: float = 0.0) -> float:
    value = metrics.get(key)
    return float(value) if value is not None else default


def _opt(metrics: Metrics, key: str) -> Optional[float]:
    value = metrics.get(key)
    return None if value is None else float(value)


def weighted_total(components: Dict[str, float], weights: Dict[str, float]) -> float:
    total = sum(components[k] * w for k, w in weights.items())
    return round(min(100.0, max(0.0, total)), 1)


def _round(components: Dict[str, float]) -> Dict[str, float]:
    return {k: round(v, 1) for k, v in components.items()}


# ---------------------------------------------------------------------------
# White Maturity Score (WMS)
# ---------------------------------------------------------------------------
def maturity_components(m: Metrics) -> Dict[str, float]:
    age = n_log(_num(m, "age_months"), 60)
    releases = (0.7 * n_log(_num(m, "releases_12m"), 12)
                + 0.3 * n_recency(_opt(m, "days_since_release"), 90))
    documentation = 20.0 * (_flag(m, "has_readme") + _flag(m, "has_install_docs")
                            + _flag(m, "has_examples") + _flag(m, "has_api_docs")
                            + _flag(m, "has_troubleshooting"))
    governance = governance_score(m)
    ci_pass = _opt(m, "ci_success_rate")
    ci_tests = (40.0 * _flag(m, "has_ci") + 30.0 * _flag(m, "has_tests")
                + 30.0 * (ci_pass if ci_pass is not None else 0.0))
    maintainers = n_log(_num(m, "active_maintainers_180d"), 8)
    versioning = (40.0 * _flag(m, "uses_semver") + 30.0 * _flag(m, "has_changelog")
                  + 30.0 * _num(m, "release_cadence_consistency"))
    compatibility = 100.0 - n_log(_num(m, "breaking_changes_12m"), 10)
    return {
        "age": age, "releases": releases, "documentation": documentation,
        "governance": governance, "ci_tests": ci_tests, "maintainers": maintainers,
        "versioning": versioning, "compatibility": compatibility,
    }


def governance_score(m: Metrics) -> float:
    return 20.0 * (_flag(m, "has_license") + _flag(m, "has_contributing")
                   + _flag(m, "has_code_of_conduct") + _flag(m, "has_security_policy")
                   + _flag(m, "has_issue_templates"))


# ---------------------------------------------------------------------------
# White Health Score (WHS)
# ---------------------------------------------------------------------------
def _response_score(median_hours: Optional[float]) -> float:
    """100 * e^(-hours/72). No observations -> neutral 50."""
    if median_hours is None:
        return 50.0
    return 100.0 * math.exp(-max(0.0, median_hours) / 72.0)


def health_components(m: Metrics) -> Dict[str, float]:
    commit_activity = (0.7 * n_log(_num(m, "commits_90d"), 100)
                       + 0.3 * n_recency(_opt(m, "days_since_commit"), 30))
    issue_response = _response_score(_opt(m, "median_issue_response_hours"))
    pr_response = _response_score(_opt(m, "median_pr_response_hours"))

    opened = _num(m, "issues_opened_90d")
    closed = _num(m, "issues_closed_90d")
    issue_closure = n_ratio(closed / opened) if opened > 0 else 100.0

    prs_closed = _num(m, "prs_closed_90d")
    prs_merged = _num(m, "prs_merged_90d")
    pr_merge = n_ratio(prs_merged / prs_closed) if prs_closed > 0 else 50.0

    open_issues = _num(m, "open_issues")
    backlog = 100.0 * math.exp(-open_issues / (max(1.0, closed) * 2.0))

    contributor_diversity = n_log(_num(m, "active_contributors_90d"), 20)
    release_freshness = n_recency(_opt(m, "days_since_release"), 90)
    ci_rate = _opt(m, "ci_success_rate")
    ci_reliability = 100.0 * ci_rate if ci_rate is not None else 50.0
    return {
        "commit_activity": commit_activity, "issue_response": issue_response,
        "pr_response": pr_response, "issue_closure": issue_closure, "pr_merge": pr_merge,
        "backlog": backlog, "contributor_diversity": contributor_diversity,
        "release_freshness": release_freshness, "ci_reliability": ci_reliability,
    }


# ---------------------------------------------------------------------------
# White Popularity Score (WPS)
# ---------------------------------------------------------------------------
def popularity_components(m: Metrics, benchmarks: Optional[Dict[str, int]] = None) -> Dict[str, float]:
    b = benchmarks or config.POPULARITY_BENCHMARKS
    return {
        "stars": n_log(_num(m, "stars"), b["stars"]),
        "star_growth": n_log(_num(m, "stars_90d"), b["star_growth"]),
        "forks": n_log(_num(m, "forks"), b["forks"]),
        "fork_growth": n_log(_num(m, "forks_90d"), b["fork_growth"]),
        "watchers": n_log(_num(m, "watchers"), b["watchers"]),
        "contributors": n_log(_num(m, "contributors_total"), b["contributors"]),
        "external_engagement": n_log(_num(m, "external_engagement_90d"), b["external_engagement"]),
    }


# ---------------------------------------------------------------------------
# White Risk Score (WRS) - higher is worse
# ---------------------------------------------------------------------------
def risk_components(m: Metrics) -> Dict[str, float]:
    bus = _num(m, "bus_factor")
    bus_factor = 100.0 * math.exp(-(max(1.0, bus) - 1.0) / 1.5)
    concentration = 100.0 * min(1.0, _num(m, "top_contributor_share"))
    commit_staleness = 100.0 - n_recency(_opt(m, "days_since_commit"), 90)
    release_staleness = 100.0 - n_recency(_opt(m, "days_since_release"), 180)
    security = 0.0 if m.get("has_security_policy") else 100.0
    open_issues = _num(m, "open_issues")
    stale = _num(m, "stale_open_issues")
    stale_issues = 100.0 * min(1.0, stale / open_issues) if open_issues > 0 else 0.0
    ownership = 0.0 if m.get("owner_is_org") else 100.0
    archived = 100.0 if m.get("is_archived") else 0.0
    return {
        "bus_factor": bus_factor, "concentration": concentration,
        "commit_staleness": commit_staleness, "release_staleness": release_staleness,
        "security": security, "stale_issues": stale_issues, "ownership": ownership,
        "archived": archived,
    }


# ---------------------------------------------------------------------------
# White Sustainability Score (WSS)
# ---------------------------------------------------------------------------
def sustainability_components(m: Metrics) -> Dict[str, float]:
    active_maintainers = _num(m, "active_maintainers_180d")
    maintainers = n_log(active_maintainers, 8)
    maintainer_diversity = 100.0 * (1.0 - min(1.0, _num(m, "top_contributor_share")))
    retention = n_ratio(_opt(m, "contributor_retention"))
    sponsorship = 100.0 if m.get("has_sponsorship") else 0.0
    org_backing = 100.0 if m.get("owner_is_org") else 0.0
    governance = governance_score(m)
    release_consistency = (0.5 * n_log(_num(m, "releases_12m"), 12)
                           + 50.0 * _num(m, "release_cadence_consistency"))
    load = _num(m, "issues_opened_90d") + _num(m, "prs_opened_90d")
    workload = 100.0 * math.exp(-load / (max(1.0, active_maintainers) * 60.0))
    return {
        "maintainers": maintainers, "maintainer_diversity": maintainer_diversity,
        "retention": retention, "sponsorship": sponsorship, "org_backing": org_backing,
        "governance": governance, "release_consistency": release_consistency,
        "workload": workload,
    }


# ---------------------------------------------------------------------------
# Overall White Score
# ---------------------------------------------------------------------------
def overall_score(scores: Dict[str, float]) -> float:
    """Weighted blend of the five dimensions; risk enters inverted (100 - risk)."""
    total = 0.0
    for key, weight in config.OVERALL_WEIGHTS.items():
        value = float(scores.get(key) or 0.0)
        total += weight * (100.0 - value if key == "risk" else value)
    return round(max(0.0, min(100.0, total)), 1)


# ---------------------------------------------------------------------------
# Suite
# ---------------------------------------------------------------------------
def score_all(m: Metrics) -> Dict[str, object]:
    mat = maturity_components(m)
    hea = health_components(m)
    pop = popularity_components(m)
    ris = risk_components(m)
    sus = sustainability_components(m)

    maturity = weighted_total(mat, config.MATURITY_WEIGHTS)
    health = weighted_total(hea, config.HEALTH_WEIGHTS)
    popularity = weighted_total(pop, config.POPULARITY_WEIGHTS)
    risk = weighted_total(ris, config.RISK_WEIGHTS)
    if m.get("is_archived"):
        risk = max(risk, 90.0)
    sustainability = weighted_total(sus, config.SUSTAINABILITY_WEIGHTS)
    overall = overall_score({"maturity": maturity, "health": health, "popularity": popularity,
                             "sustainability": sustainability, "risk": risk})

    return {
        "overall": overall,
        "maturity": maturity, "health": health, "popularity": popularity,
        "risk": risk, "sustainability": sustainability,
        "components": {
            "maturity": _round(mat), "health": _round(hea), "popularity": _round(pop),
            "risk": _round(ris), "sustainability": _round(sus),
        },
    }


def interpret(score_name: str, value: float) -> str:
    """Human-readable band for a score, mirroring the White Score tables."""
    if score_name == "risk":
        bands = [(25, "Low risk"), (50, "Moderate risk"), (75, "High risk"), (101, "Critical risk")]
    elif score_name == "maturity":
        bands = [(25, "Experimental"), (50, "Early-stage"), (70, "Usable"), (85, "Mature"), (101, "Highly mature")]
    elif score_name == "health":
        bands = [(25, "Unhealthy"), (50, "Weak"), (70, "Moderate"), (85, "Healthy"), (101, "Very healthy")]
    elif score_name == "popularity":
        bands = [(25, "Low visibility"), (50, "Niche"), (70, "Notable"), (85, "Popular"), (101, "Widely recognized")]
    else:
        bands = [(25, "Fragile"), (50, "At risk"), (70, "Moderate"), (85, "Sustainable"), (101, "Highly sustainable")]
    for limit, label in bands:
        if value < limit:
            return label
    return bands[-1][1]
