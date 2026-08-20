"""Manager-neutral runtime secret resolver for provider credentials.

For a requested environment key such as ``OPENROUTER_API_KEY``, exactly one of
``OPENROUTER_API_KEY`` or ``OPENROUTER_API_KEY_FILE`` may be configured. FILE
values are validated on every read so host-side atomic rotation is observed
without restarting the application. This module has no OpenBao dependency and
never includes secret content in errors.
"""

import os
import re
import stat
import time


MAX_FILE_BYTES = 64 * 1024
FUTURE_MTIME_SKEW_SECONDS = 30
_RENAME_RACE_RETRY_DELAY = 0.05
_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")

FILE = "file"
ENV = "env"


class SecretError(RuntimeError):
    """Fail-closed resolution error containing only non-secret metadata."""


def _validate_name(name):
    if not isinstance(name, str) or not _NAME_RE.fullmatch(name):
        raise SecretError("runtime secret name must be an uppercase environment key")
    return name


def _file_var(name):
    return f"{name}_FILE"


def _max_age_var(name):
    return f"{name}_FILE_MAX_AGE_SECONDS"


def _max_age_seconds(name):
    age_var = _max_age_var(name)
    raw = (os.environ.get(age_var) or "").strip()
    if not raw:
        raise SecretError(f"{_file_var(name)} requires a positive {age_var}")
    try:
        value = int(raw)
    except ValueError as exc:
        raise SecretError(f"{age_var} must be a positive integer") from exc
    if value <= 0:
        raise SecretError(f"{age_var} must be positive")
    return value


def _read_secure_file(name, path):
    file_var = _file_var(name)
    if not os.path.isabs(path):
        raise SecretError(f"{file_var} must be an absolute path")
    max_age = _max_age_seconds(name)
    try:
        lst = os.lstat(path)
    except FileNotFoundError:
        raise
    except OSError as exc:
        # Do not let an OS exception surface the configured secret path to API/log callers.
        raise SecretError(f"{file_var} is unreadable or not a plain file ({exc.errno})") from exc
    if stat.S_ISLNK(lst.st_mode):
        raise SecretError(f"{file_var} must not be a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as exc:
        raise SecretError(f"{file_var} is unreadable or not a plain file ({exc.errno})") from exc
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode):
            raise SecretError(f"{file_var} must be a regular file")
        if opened.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SecretError(f"{file_var} must have zero group/world permission bits")
        if opened.st_uid not in (0, os.geteuid()):
            raise SecretError(f"{file_var} must be owned by root or the process user")
        if opened.st_size > MAX_FILE_BYTES:
            raise SecretError(f"{file_var} exceeds the 64 KiB size cap")
        now = time.time()
        if opened.st_mtime > now + FUTURE_MTIME_SKEW_SECONDS:
            raise SecretError(f"{file_var} mtime is in the future beyond skew")
        if now - opened.st_mtime > max_age:
            raise SecretError(f"{file_var} is stale beyond the configured max age")
        chunks = []
        total = 0
        while True:
            chunk = os.read(fd, 65536)
            if not chunk:
                break
            total += len(chunk)
            if total > MAX_FILE_BYTES:
                raise SecretError(f"{file_var} exceeds the 64 KiB size cap")
            chunks.append(chunk)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        value = data.decode("utf-8", "strict").strip()
    except UnicodeDecodeError as exc:
        raise SecretError(f"{file_var} is not valid UTF-8") from exc
    if not value:
        raise SecretError(f"{file_var} is empty after trim")
    return value


def resolve(name):
    """Return ``(value, source_kind)`` or fail closed on missing/invalid input."""
    name = _validate_name(name)
    file_var = _file_var(name)
    path = (os.environ.get(file_var) or "").strip()
    env_value = (os.environ.get(name) or "").strip()
    if path and env_value:
        raise SecretError(f"both {file_var} and {name} are set; ambiguous secret source")
    if path:
        try:
            return _read_secure_file(name, path), FILE
        except FileNotFoundError:
            time.sleep(_RENAME_RACE_RETRY_DELAY)
            try:
                return _read_secure_file(name, path), FILE
            except FileNotFoundError as exc:
                raise SecretError(f"{file_var} is missing") from exc
    if env_value:
        return env_value, ENV
    raise SecretError(f"{name} is not configured")


def status(name):
    """Return non-secret ``(configured, source_kind)`` metadata."""
    try:
        _, source = resolve(name)
    except SecretError:
        return False, None
    return True, source
