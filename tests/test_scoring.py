import math

from whitescore import config, scoring


def strong_metrics():
    return {
        "age_months": 72, "releases_12m": 14, "days_since_release": 10,
        "has_readme": True, "has_install_docs": True, "has_examples": True,
        "has_api_docs": True, "has_troubleshooting": True,
        "has_license": True, "has_contributing": True, "has_code_of_conduct": True,
        "has_security_policy": True, "has_issue_templates": True,
        "has_ci": True, "has_tests": True, "ci_success_rate": 0.95,
        "active_maintainers_180d": 12, "uses_semver": True, "has_changelog": True,
        "release_cadence_consistency": 0.9, "breaking_changes_12m": 0,
        "commits_90d": 400, "days_since_commit": 0.5,
        "median_issue_response_hours": 6, "median_pr_response_hours": 10,
        "issues_opened_90d": 200, "issues_closed_90d": 220, "prs_opened_90d": 300,
        "prs_closed_90d": 280, "prs_merged_90d": 250, "open_issues": 100,
        "active_contributors_90d": 60,
        "stars": 80_000, "stars_90d": 9_000, "forks": 15_000, "forks_90d": 1_500,
        "watchers": 1_500, "contributors_total": 900, "external_engagement_90d": 1_500,
        "bus_factor": 8, "top_contributor_share": 0.12, "stale_open_issues": 5,
        "owner_is_org": True, "is_archived": False, "has_sponsorship": True,
        "contributor_retention": 0.7,
    }


def test_weights_sum_to_one():
    for weights in (config.MATURITY_WEIGHTS, config.HEALTH_WEIGHTS, config.POPULARITY_WEIGHTS,
                    config.RISK_WEIGHTS, config.SUSTAINABILITY_WEIGHTS, config.OVERALL_WEIGHTS):
        assert math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9)


def test_normalisers():
    assert scoring.n_log(0, 100) == 0
    assert scoring.n_log(100, 100) == 100
    assert scoring.n_log(10_000, 100) == 100
    assert 0 < scoring.n_log(10, 100) < 100
    assert scoring.n_ratio(1.5) == 100
    assert scoring.n_ratio(-1) == 0
    assert scoring.n_recency(0, 30) == 100
    assert math.isclose(scoring.n_recency(30, 30), 100 * math.exp(-1))
    assert scoring.n_recency(None, 30) == 0


def test_strong_project_scores_high_everywhere():
    s = scoring.score_all(strong_metrics())
    assert s["maturity"] >= 90
    assert s["health"] >= 85
    assert s["popularity"] >= 90
    assert s["sustainability"] >= 80
    assert s["risk"] <= 15
    assert s["overall"] >= 88
    for group in s["components"].values():
        for value in group.values():
            assert 0 <= value <= 100


def test_empty_metrics_are_safe_and_low():
    s = scoring.score_all({})
    assert 0 <= s["maturity"] <= 100
    assert s["popularity"] == 0
    assert s["risk"] >= 60            # unknown everything is risky
    assert s["sustainability"] <= 30


def test_archived_projects_are_critical_risk():
    m = strong_metrics()
    m["is_archived"] = True
    assert scoring.score_all(m)["risk"] >= 90


def test_scores_are_independent_dimensions():
    """Popularity must not move maturity or health."""
    base = strong_metrics()
    poor_pop = dict(base, stars=10, stars_90d=0, forks=1, forks_90d=0, watchers=1,
                    contributors_total=3, external_engagement_90d=0)
    a, b = scoring.score_all(base), scoring.score_all(poor_pop)
    assert a["maturity"] == b["maturity"]
    assert a["health"] == b["health"]
    assert b["popularity"] < a["popularity"]


def test_interpretation_bands():
    assert scoring.interpret("risk", 10) == "Low risk"
    assert scoring.interpret("risk", 80) == "Critical risk"
    assert scoring.interpret("maturity", 90) == "Highly mature"
    assert scoring.interpret("health", 0) == "Unhealthy"
