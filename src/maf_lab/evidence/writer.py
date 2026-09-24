"""The artifact writer: atomic, checksummed trial commit (spec section 9.2).

The commit order is strict and load-bearing:

1. Write every artifact file into `<trial_id>.partial/`.
2. Write `checksums.sha256` inside that same partial directory.
3. `fsync` every artifact file and the partial directory itself.
4. Atomically rename `<trial_id>.partial/` to `<trial_id>/`.
5. Write the `COMMITTED` marker inside the now-renamed directory.

Checksums are written before the rename and the marker only after it, so a
directory named like a completed trial and missing its integrity file is never
mistaken for one that committed successfully, and a directory that has
`COMMITTED` is guaranteed to have already passed step 2.

NFR-12's atomicity guarantee is asserted on Linux only (see
`docs/metric-card.md`): `os.replace` and `fsync` behave differently on Windows.
This module calls both unconditionally so behaviour is uniform across
platforms, but the crash-safety claim is not made outside Linux.
"""

from __future__ import annotations

import hashlib
import os
import shutil
from pathlib import Path


class CompletedTrialError(RuntimeError):
    """Raised when a commit is attempted for a trial that already committed.

    A completed trial directory is immutable (spec section 9.2, acceptance
    criterion 12): reaching this means a caller is retrying a trial identity
    that already produced evidence, which must be a new trial attempt with a
    new identity, not a silent overwrite.
    """


CHECKSUMS_FILENAME = "checksums.sha256"
COMMITTED_MARKER = "COMMITTED"


def _is_completed(trial_dir: Path) -> bool:
    """Whether `trial_dir` is a directory that previously committed successfully.

    Presence, not absence, of `COMMITTED` is what completion means: a directory
    that merely exists (created by an operator, or left by some other process)
    is not itself evidence of a prior commit.
    """
    return trial_dir.is_dir() and (trial_dir / COMMITTED_MARKER).exists()


class ArtifactWriter:
    """Commits one trial's artifacts under `root`, one directory per trial."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def commit_trial(self, *, trial_id: str, artifacts: dict[str, bytes]) -> Path:
        """Write `artifacts` and commit them atomically as `<root>/<trial_id>/`.

        Returns the committed directory. Raises `CompletedTrialError` without
        touching the filesystem if `trial_id` already has a committed directory.

        Not safe for two writers to race on the same `trial_id` concurrently:
        the completed-trial check and the write it guards are not atomic with
        each other. The B0 harness this ticket builds runs one trial at a time,
        so this does not arise yet; concurrent trial execution is a later
        ticket's problem to solve, likely with the durable store profile's
        real transaction rather than a filesystem check.
        """
        final_dir = self._root / trial_id
        if _is_completed(final_dir):
            raise CompletedTrialError(
                f"trial {trial_id} already has a committed directory at {final_dir}"
            )

        partial_dir = self._root / f"{trial_id}.partial"
        self._root.mkdir(parents=True, exist_ok=True)
        partial_dir.mkdir(parents=False, exist_ok=False)

        checksums = self._write_artifacts(partial_dir, artifacts)
        self._write_checksums(partial_dir, checksums)
        self._fsync_directory(partial_dir)

        # A non-completed directory may already occupy `final_dir` (a stray
        # directory, or a not-yet-classified partial from a future recovery
        # scenario). We have already established above that it is not a
        # committed trial, so clearing it is safe. POSIX `rename(2)` replaces a
        # directory atomically; Windows' `MoveFileEx` (which `os.replace` and
        # `Path.replace` call) refuses to replace a non-empty directory, so the
        # removal step is required there and a no-op elsewhere.
        if final_dir.exists():
            shutil.rmtree(final_dir)
        partial_dir.replace(final_dir)
        self._write_committed_marker(final_dir)
        return final_dir

    def _write_artifacts(self, partial_dir: Path, artifacts: dict[str, bytes]) -> dict[str, str]:
        checksums: dict[str, str] = {}
        for name in sorted(artifacts):
            content = artifacts[name]
            path = partial_dir / name
            with path.open("wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            checksums[name] = hashlib.sha256(content).hexdigest()
        return checksums

    def _write_checksums(self, partial_dir: Path, checksums: dict[str, str]) -> None:
        lines = [f"{digest}  {name}" for name, digest in sorted(checksums.items())]
        path = partial_dir / CHECKSUMS_FILENAME
        with path.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write("\n".join(lines) + "\n" if lines else "")
            handle.flush()
            os.fsync(handle.fileno())

    def _fsync_directory(self, directory: Path) -> None:
        # Opening a directory with O_RDONLY to fsync it is a POSIX pattern;
        # Windows raises PermissionError for it, and NFR-12's atomicity
        # guarantee is asserted on Linux only (see docs/metric-card.md), so this
        # step is skipped rather than faked on platforms where it cannot mean
        # what it means on Linux.
        if os.name != "posix":
            return
        fd = os.open(directory, os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_committed_marker(self, final_dir: Path) -> None:
        path = final_dir / COMMITTED_MARKER
        with path.open("w", encoding="utf-8") as handle:
            handle.write("")
            handle.flush()
            os.fsync(handle.fileno())


def verify_checksums(trial_dir: Path) -> bool:
    """Whether every artifact under `trial_dir` still matches `checksums.sha256`.

    Used by replay (spec section 9.2, acceptance criterion 11) to detect an
    artifact altered after commit, since a committed directory is meant to be
    immutable.
    """
    checksums_path = trial_dir / CHECKSUMS_FILENAME
    if not checksums_path.exists():
        return False
    for line in checksums_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, name = line.partition("  ")
        artifact_path = trial_dir / name
        if not artifact_path.exists():
            return False
        actual = hashlib.sha256(artifact_path.read_bytes()).hexdigest()
        if actual != digest:
            return False
    return True
