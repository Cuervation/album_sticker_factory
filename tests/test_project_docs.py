from pathlib import Path


def test_core_docs_exist() -> None:
    assert Path("SPEC.md").exists()
    assert Path("AGENTS.md").exists()


def test_skills_exist() -> None:
    expected = [
        "skills/sticker-planning/SKILL.md",
        "skills/image-search-policy/SKILL.md",
        "skills/image-quality-review/SKILL.md",
        "skills/sticker-cropping/SKILL.md",
        "skills/source-rights/SKILL.md",
        "skills/local-review-export/SKILL.md",
    ]
    for item in expected:
        assert Path(item).exists()


def test_curation_seed_exists() -> None:
    assert Path("data/curation_seed.json").exists()
