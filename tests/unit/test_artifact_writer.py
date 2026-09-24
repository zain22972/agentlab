"""Unit tests for the artifact writer's commit ordering (spec section 9.2).

The commit order is strict and load-bearing: write all artifacts, then write
`checksums.sha256` inside the partial directory, then fsync, then atomically
rename `<trial_id>.partial/` to `<trial_id>/`, then write the `COMMITTED`
marker. Checksums written after the rename would expose a committed-looking
directory whose integrity file is missing or incomplete.

Tests observe the ordering indirectly, through the filesystem state a writer
leaves behind if it stops at each step, rather than by mocking internal calls:
the guarantee that matters is what's on disk, not which method ran.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from maf_lab.evidence.writer import ArtifactWriter, CompletedTrialError


def test_writes_every_artifact_file_under_the_committed_directory(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    trial_dir = writer.commit_trial(
        trial_id="trial_0001",
        artifacts={"events.jsonl": b"line one\n", "audit.jsonl": b"line two\n"},
    )
    assert trial_dir == tmp_path / "trial_0001"
    assert (trial_dir / "events.jsonl").read_bytes() == b"line one\n"
    assert (trial_dir / "audit.jsonl").read_bytes() == b"line two\n"


def test_leaves_no_partial_directory_behind_after_a_successful_commit(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"x"})
    assert not (tmp_path / "trial_0001.partial").exists()


def test_writes_a_committed_marker_after_the_rename(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    trial_dir = writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"x"})
    assert (trial_dir / "COMMITTED").exists()


def test_writes_a_checksums_file_covering_every_artifact(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    trial_dir = writer.commit_trial(
        trial_id="trial_0001", artifacts={"a.txt": b"hello", "b.txt": b"world"}
    )
    checksums = (trial_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert hashlib.sha256(b"hello").hexdigest() in checksums
    assert hashlib.sha256(b"world").hexdigest() in checksums
    assert "a.txt" in checksums
    assert "b.txt" in checksums


def test_the_checksums_file_does_not_cover_itself_or_the_committed_marker(tmp_path: Path) -> None:
    writer = ArtifactWriter(root=tmp_path)
    trial_dir = writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"hello"})
    checksums = (trial_dir / "checksums.sha256").read_text(encoding="utf-8")
    assert "checksums.sha256" not in checksums
    assert "COMMITTED" not in checksums


class TestOrderingUpToTheRename:
    """The checksum file must exist inside the partial directory before the
    rename. We verify this by making the rename fail and inspecting what the
    writer had already written to the (still-present) partial directory."""

    def test_checksums_exist_in_the_partial_directory_before_the_rename_is_attempted(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        partial_dir = tmp_path / "trial_0001.partial"
        seen_before_rename: dict[str, bool] = {}

        real_replace = Path.replace

        def spying_replace(self: Path, target: str | Path) -> Path:
            # At the moment the rename is attempted, the checksum file must
            # already exist inside the (pre-rename) partial directory.
            seen_before_rename["checksums_present"] = (partial_dir / "checksums.sha256").exists()
            seen_before_rename["committed_marker_present"] = (
                partial_dir / "COMMITTED"
            ).exists()
            return real_replace(self, target)

        monkeypatch.setattr(Path, "replace", spying_replace)

        writer = ArtifactWriter(root=tmp_path)
        writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"hello"})

        assert seen_before_rename["checksums_present"] is True
        assert seen_before_rename["committed_marker_present"] is False


class TestOrderingAfterTheRename:
    def test_the_committed_marker_does_not_exist_before_the_rename(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        final_dir = tmp_path / "trial_0001"
        observations: dict[str, bool] = {}

        real_replace = Path.replace

        def spying_replace(self: Path, target: str | Path) -> Path:
            observations["committed_before_rename"] = (final_dir / "COMMITTED").exists()
            result = real_replace(self, target)
            observations["committed_immediately_after_rename"] = (
                final_dir / "COMMITTED"
            ).exists()
            return result

        monkeypatch.setattr(Path, "replace", spying_replace)

        writer = ArtifactWriter(root=tmp_path)
        writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"hello"})

        assert observations["committed_before_rename"] is False
        assert observations["committed_immediately_after_rename"] is False


class TestFailureBeforeRename:
    def test_a_failure_before_the_rename_leaves_the_partial_directory_and_no_committed_dir(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def failing_replace(self: Path, target: object) -> None:
            raise OSError("simulated crash before rename")

        monkeypatch.setattr(Path, "replace", failing_replace)

        writer = ArtifactWriter(root=tmp_path)
        with pytest.raises(OSError, match="simulated crash"):
            writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"hello"})

        assert (tmp_path / "trial_0001.partial").exists()
        assert (tmp_path / "trial_0001.partial" / "checksums.sha256").exists()
        assert not (tmp_path / "trial_0001.partial" / "COMMITTED").exists()
        assert not (tmp_path / "trial_0001").exists()


class TestNeverOverwriteACompletedTrial:
    def test_committing_the_same_trial_id_twice_is_refused(self, tmp_path: Path) -> None:
        writer = ArtifactWriter(root=tmp_path)
        writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"first"})

        with pytest.raises(CompletedTrialError, match="trial_0001"):
            writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"second"})

        assert (tmp_path / "trial_0001" / "a.txt").read_bytes() == b"first"

    def test_a_refused_second_attempt_does_not_leave_a_partial_directory_behind(
        self, tmp_path: Path
    ) -> None:
        writer = ArtifactWriter(root=tmp_path)
        writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"first"})

        with pytest.raises(CompletedTrialError):
            writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"second"})

        assert not (tmp_path / "trial_0001.partial").exists()

    def test_a_completed_directory_missing_its_committed_marker_is_not_treated_as_completed(
        self, tmp_path: Path
    ) -> None:
        """A directory named like a completed trial but without a COMMITTED
        marker is not evidence of a prior successful commit (e.g. a directory
        an operator created by hand, or a future recovery scenario's
        not-yet-classified partial). Overwriting it is allowed."""
        stray_dir = tmp_path / "trial_0001"
        stray_dir.mkdir()
        (stray_dir / "a.txt").write_bytes(b"stray")

        writer = ArtifactWriter(root=tmp_path)
        trial_dir = writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"real"})
        assert (trial_dir / "a.txt").read_bytes() == b"real"
        assert (trial_dir / "COMMITTED").exists()


class TestChecksumVerification:
    def test_verify_checksums_passes_for_an_untouched_committed_trial(self, tmp_path: Path) -> None:
        from maf_lab.evidence.writer import verify_checksums

        writer = ArtifactWriter(root=tmp_path)
        trial_dir = writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"hello"})
        assert verify_checksums(trial_dir) is True

    def test_verify_checksums_fails_if_an_artifact_is_altered_after_commit(
        self, tmp_path: Path
    ) -> None:
        from maf_lab.evidence.writer import verify_checksums

        writer = ArtifactWriter(root=tmp_path)
        trial_dir = writer.commit_trial(trial_id="trial_0001", artifacts={"a.txt": b"hello"})
        (trial_dir / "a.txt").write_bytes(b"tampered")
        assert verify_checksums(trial_dir) is False
