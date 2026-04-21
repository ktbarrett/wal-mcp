from pathlib import Path

import pytest

from wal_mcp import install_skills


def test_install_skills_copies_skill_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Each subdir under the bundled skills/ should land under dest/."""
    fake_pkg = tmp_path / "pkg"
    skills_src = fake_pkg / "skills"
    (skills_src / "alpha").mkdir(parents=True)
    (skills_src / "alpha" / "SKILL.md").write_text("alpha skill")
    (skills_src / "beta").mkdir()
    (skills_src / "beta" / "SKILL.md").write_text("beta skill")
    # Loose file at the skills root should be ignored (only directories install).
    (skills_src / "README.md").write_text("ignore me")

    monkeypatch.setattr(install_skills, "files", lambda _pkg: fake_pkg)

    dest = tmp_path / "out"
    monkeypatch.setattr("sys.argv", ["wal-mcp-install-skills", str(dest)])
    install_skills.main()

    assert (dest / "alpha" / "SKILL.md").read_text() == "alpha skill"
    assert (dest / "beta" / "SKILL.md").read_text() == "beta skill"
    assert not (dest / "README.md").exists()


def test_install_skills_overwrites_existing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A re-install replaces an existing skill directory atomically."""
    fake_pkg = tmp_path / "pkg"
    skills_src = fake_pkg / "skills"
    (skills_src / "alpha").mkdir(parents=True)
    (skills_src / "alpha" / "SKILL.md").write_text("new content")

    dest = tmp_path / "out"
    (dest / "alpha").mkdir(parents=True)
    (dest / "alpha" / "stale.txt").write_text("should be gone")

    monkeypatch.setattr(install_skills, "files", lambda _pkg: fake_pkg)
    monkeypatch.setattr("sys.argv", ["wal-mcp-install-skills", str(dest)])
    install_skills.main()

    assert (dest / "alpha" / "SKILL.md").read_text() == "new content"
    assert not (dest / "alpha" / "stale.txt").exists()
