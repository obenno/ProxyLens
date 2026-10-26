"""Recovery file boundary: private, checksummed, fresh destinations only."""

import importlib.util
import json
import stat
import tarfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "recovery", Path(__file__).resolve().parents[1] / "scripts" / "recovery.py"
)
recovery = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recovery)


def test_existing_destination_and_symlink_ancestors_are_never_reused(tmp_path):
    existing = tmp_path / "current"
    existing.mkdir()
    sentinel = existing / "keep"
    sentinel.write_text("untouched")
    with pytest.raises(recovery.RecoveryError):
        recovery.new_directory(existing)
    link = tmp_path / "link"
    link.symlink_to(existing, target_is_directory=True)
    with pytest.raises(recovery.RecoveryError):
        recovery.new_directory(link / "nested")
    assert sentinel.read_text() == "untouched"
    assert not (existing / "nested").exists()
    destination = recovery.new_directory(tmp_path / "new")
    assert stat.S_IMODE(destination.stat().st_mode) == 0o700


def test_manifest_rejects_tampered_or_public_archive_before_restore(tmp_path):
    directory = recovery.new_directory(tmp_path / "backup")
    archive = directory / "postgres.dump"
    recovery.private_write(archive, b"fixture")
    recovery.write_manifest(directory, {"kind": "postgres", "server_major": 17}, [archive])
    assert recovery.validate(directory)["kind"] == "postgres"
    assert all(stat.S_IMODE(p.stat().st_mode) == 0o600 for p in directory.iterdir())
    archive.chmod(0o644)
    with pytest.raises(recovery.RecoveryError):
        recovery.validate(directory)
    archive.chmod(0o600)
    archive.write_bytes(b"modified")
    with pytest.raises(recovery.RecoveryError):
        recovery.validate(directory)


def test_manifest_cannot_read_outside_recovery_set(tmp_path):
    directory = recovery.new_directory(tmp_path / "backup")
    recovery.private_write(
        directory / "manifest.json",
        json.dumps(
            {
                "format": 1,
                "files": {"../outside": "0" * 64},
                "kind": "postgres",
            }
        ).encode(),
    )
    with pytest.raises(recovery.RecoveryError):
        recovery.validate(directory)


def test_manifest_root_must_be_an_object(tmp_path):
    directory = recovery.new_directory(tmp_path / "backup")
    recovery.private_write(directory / "manifest.json", b"[]")
    with pytest.raises(recovery.RecoveryError):
        recovery.validate(directory)


def test_recovery_tar_rejects_path_traversal_and_escaping_links(tmp_path):
    for name, link in (("../escape", ""), ("./link", "../../escape"), ("/absolute", "")):
        archive = tmp_path / "bad.tar.gz"
        with tarfile.open(archive, "w:gz") as output:
            member = tarfile.TarInfo(name)
            if link:
                member.type = tarfile.SYMTYPE
                member.linkname = link
            output.addfile(member)
        with pytest.raises(recovery.RecoveryError):
            recovery.validate_tar(archive)
