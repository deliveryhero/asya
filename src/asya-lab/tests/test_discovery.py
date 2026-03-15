"""Tests for config discovery utilities."""

from pathlib import Path

from asya_lab.config.discovery import collect_asya_dirs, find_asya_dir, find_git_root


class TestFindGitRoot:
    def test_finds_git_root(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        assert find_git_root(subdir) == tmp_path

    def test_returns_none_when_no_git(self, tmp_path: Path) -> None:
        subdir = tmp_path / "a" / "b"
        subdir.mkdir(parents=True)
        assert find_git_root(subdir) is None

    def test_finds_git_root_at_start_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert find_git_root(tmp_path) == tmp_path


class TestFindAsyaDir:
    def test_finds_asya_dir_in_current(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        assert find_asya_dir(tmp_path) == asya_dir

    def test_finds_asya_dir_in_parent(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        subdir = tmp_path / "src" / "pkg"
        subdir.mkdir(parents=True)
        assert find_asya_dir(subdir) == asya_dir

    def test_returns_none_when_no_asya(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert find_asya_dir(tmp_path) is None

    def test_stops_at_git_root(self, tmp_path: Path) -> None:
        parent = tmp_path / "parent"
        parent.mkdir()
        (parent / ".asya").mkdir()
        child = parent / "child"
        child.mkdir()
        (child / ".git").mkdir()
        assert find_asya_dir(child) is None

    def test_finds_nearest_asya_dir(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        root_asya = tmp_path / ".asya"
        root_asya.mkdir()
        sub = tmp_path / "team"
        sub.mkdir()
        sub_asya = sub / ".asya"
        sub_asya.mkdir()
        assert find_asya_dir(sub) == sub_asya


class TestCollectAsyaDirs:
    def test_collects_single(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        result = collect_asya_dirs(tmp_path)
        assert result == [asya_dir]

    def test_collects_multiple_root_first(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        root_asya = tmp_path / ".asya"
        root_asya.mkdir()
        team_dir = tmp_path / "src" / "team"
        team_dir.mkdir(parents=True)
        team_asya = team_dir / ".asya"
        team_asya.mkdir()
        result = collect_asya_dirs(team_dir)
        assert result == [root_asya, team_asya]

    def test_empty_when_no_asya(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        assert collect_asya_dirs(tmp_path) == []
