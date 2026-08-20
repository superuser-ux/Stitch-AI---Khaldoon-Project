"""Focused offline checks for the manager-neutral provider secret resolver."""

import os
import tempfile
import time
from pathlib import Path

from agents import runtime_secret as secret


NAME = "TEST_PROVIDER_API_KEY"
KEYS = (NAME, f"{NAME}_FILE", f"{NAME}_FILE_MAX_AGE_SECONDS")


def clear():
    for key in KEYS:
        os.environ.pop(key, None)


def expect_error(fragment):
    try:
        secret.resolve(NAME)
    except secret.SecretError as exc:
        assert fragment in str(exc)
        assert "super-secret-value" not in str(exc)
        return
    raise AssertionError(f"expected SecretError containing {fragment!r}")


def write(path, value="super-secret-value", mode=0o400, age=0):
    if path.exists():
        path.chmod(0o600)
    path.write_text(value, encoding="utf-8")
    path.chmod(mode)
    timestamp = time.time() - age
    os.utime(path, (timestamp, timestamp))


def main():
    clear()
    expect_error("not configured")

    os.environ[NAME] = "  super-secret-value  "
    assert secret.resolve(NAME) == ("super-secret-value", secret.ENV)
    assert secret.status(NAME) == (True, secret.ENV)

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "credential"
        write(path)
        os.environ[f"{NAME}_FILE"] = str(path)
        expect_error("ambiguous")

        os.environ.pop(NAME)
        os.environ[f"{NAME}_FILE_MAX_AGE_SECONDS"] = "900"
        assert secret.resolve(NAME) == ("super-secret-value", secret.FILE)

        path.chmod(0o440)
        expect_error("group/world")
        write(path, age=901)
        expect_error("stale")

        write(path)
        link = Path(directory) / "link"
        link.symlink_to(path)
        os.environ[f"{NAME}_FILE"] = str(link)
        expect_error("symlink")

        os.environ[f"{NAME}_FILE"] = str(Path(directory) / "missing")
        expect_error("missing")

        os.environ[f"{NAME}_FILE"] = str(path)
        original_lstat = secret.os.lstat
        try:
            secret.os.lstat = lambda attempted: (_ for _ in ()).throw(
                PermissionError(13, "denied", attempted)
            )
            expect_error("unreadable or not a plain file")
        finally:
            secret.os.lstat = original_lstat

        replacement = Path(directory) / "replacement"
        write(replacement, "rotated-value")
        replacement.replace(path)
        assert secret.resolve(NAME) == ("rotated-value", secret.FILE)

    clear()
    assert secret.status(NAME) == (False, None)
    print("runtime_secret_selftest: PASS")


if __name__ == "__main__":
    main()
