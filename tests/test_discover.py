"""Selection policy: licences, the AI signal, exclusions and category overrides."""
import json

from whitescore import config, discover


def test_license_policy_accepts_osi_licences_only(monkeypatch):
    monkeypatch.setattr(config, "REQUIRE_RECOGNIZED_LICENSE", True)
    assert discover.license_allowed("MIT", "a/b")
    assert discover.license_allowed("GPL-3.0-or-later", "a/b")
    assert not discover.license_allowed("CC-BY-4.0", "a/b")        # not a software licence
    assert not discover.license_allowed("NOASSERTION", "a/b")
    assert not discover.license_allowed(None, "a/b")
    monkeypatch.setattr(config, "REQUIRE_RECOGNIZED_LICENSE", False)
    assert discover.license_allowed(None, "a/b")


def test_license_overrides_cover_misdetected_repositories(monkeypatch):
    monkeypatch.setattr(config, "LICENSE_OVERRIDES", {"acme/tool": "BSD-3-Clause", "acme/docs-first": "MIT"})
    assert discover.effective_license("NOASSERTION", "acme/tool") == "BSD-3-Clause"
    assert discover.license_allowed("NOASSERTION", "acme/tool")
    # GitHub read the CC-BY documentation licence; the override names the code licence
    assert discover.effective_license("CC-BY-4.0", "acme/docs-first") == "MIT"
    # a detected OSI licence is kept even when an override exists
    assert discover.effective_license("Apache-2.0", "acme/tool") == "Apache-2.0"
    assert discover.effective_license("NOASSERTION", "other/repo") == "NOASSERTION"


def test_weak_ai_words_count_half():
    # "no agents to install" alone is not enough; two weak words equal one strong word
    assert discover.ai_signal([], [], "IT automation with no agents to install") == 0
    assert discover.ai_signal([], [], "embedding web technologies, with agents") == 1
    assert discover.ai_signal([], [], "a large language model server") == 1
    assert discover.ai_signal([], [], "LLM inference engine with embedding support") == 2
    # keyword search hits still count as strong
    assert discover.ai_signal([], ["kw:llm"], "") == 2


def test_exclusion_file_allows_inline_comments(tmp_path):
    f = tmp_path / "excluded.txt"
    f.write_text("# comment\nansible/ansible   # IT automation\n\nservo/servo\n")
    assert discover.load_exclusions(f) == ["ansible/ansible", "servo/servo"]
    assert discover.load_exclusions(tmp_path / "missing.txt") == []


def test_select_repos_never_chooses_excluded_names_even_seeds():
    found = {"a/one": {"stars": 300}, "a/two": {"stars": 200}, "a/three": {"stars": 100}}
    chosen = discover.select_repos(found, seeds=["a/two", "x/seed"], max_repos=10, exclude=["A/Two", "a/three"])
    assert chosen == ["x/seed", "a/one"]


def test_category_overrides_drop_unknown_categories(tmp_path):
    f = tmp_path / "overrides.json"
    f.write_text(json.dumps({"overrides": {"Acme/Tool": "Computer Vision", "acme/other": "Not A Category"}}))
    assert discover.load_category_overrides(f) == {"acme/tool": "Computer Vision"}
    f.write_text("{not json")
    assert discover.load_category_overrides(f) == {}
    assert discover.load_category_overrides(tmp_path / "missing.json") == {}
