"""#387 — manager-neutral reviewer-proxy secret resolver (Python gate API).

Resolves the shared HMAC secret (`REVIEWER_PROXY_SECRET`) from EXACTLY ONE authorized source, fail
closed. This module knows nothing about OpenBao or any secret manager: it reads a plain FILE path
(populated out-of-band by a host materializer) or the direct env var. It is a manager-neutral seam.

Precedence is NOT "file wins": if BOTH `REVIEWER_PROXY_SECRET_FILE` and `REVIEWER_PROXY_SECRET` are
non-empty the source is AMBIGUOUS and we FAIL CLOSED. The known public dev fixture is used ONLY under
an explicit `TANAGHOM_DEV_MODE` opt-in AND ONLY when neither FILE nor env is configured — never on an
accidental omission and never as a fallback for an invalid FILE.

FILE security (validated on EVERY resolve, so an atomic same-directory replacement is observed without a
restart): absolute path; not a symlink (`lstat` + `O_NOFOLLOW`); the OPENED descriptor is validated with
`fstat` before any byte is read (defeats TOCTOU / symlink swap); regular file; zero group/world
permission bits; owned by root or the process EUID; size <= 64 KiB; non-empty after trim; mtime not more
than 30 s in the future; age within a positive bounded `REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS`.

A single bounded retry is permitted ONLY for the transient atomic-replacement race (the leaf briefly
absent mid-rename). Every persistent invalid / missing / stale / insecure condition fails closed with NO
env or dev fallback. This module never logs, returns, or raises with secret content, hashes, or
fragments — only non-secret reason strings and boolean/source-kind metadata.
"""
import os
import stat
import time

DEV_REVIEWER_SECRET = "dev-internal-reviewer-proxy-secret"  # local/dev/test ONLY, gated below
MAX_FILE_BYTES = 64 * 1024
FUTURE_MTIME_SKEW_SECONDS = 30
_RENAME_RACE_RETRY_DELAY = 0.05  # one bounded retry for the transient rename window only

# source kinds
FILE = "file"
ENV = "env"
DEV = "dev"


class SecretError(Exception):
    """Fail-closed resolution error. The message is always non-secret (never the value)."""


def dev_mode():
    return (os.environ.get("TANAGHOM_DEV_MODE") or "").strip().lower() in ("1", "true", "yes", "on")


def _env_secret():
    return (os.environ.get("REVIEWER_PROXY_SECRET") or "").strip()


def _file_path():
    return (os.environ.get("REVIEWER_PROXY_SECRET_FILE") or "").strip()


def _max_age_seconds():
    raw = (os.environ.get("REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS") or "").strip()
    if not raw:
        raise SecretError("REVIEWER_PROXY_SECRET_FILE requires a positive "
                          "REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS")
    try:
        v = int(raw)
    except ValueError:
        raise SecretError("REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS must be a positive integer")
    if v <= 0:
        raise SecretError("REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS must be positive")
    return v


def _read_secure_file(path):
    """Read+validate the FILE. Raises FileNotFoundError ONLY for the transient rename window (caller may
    retry once); every other problem raises SecretError (persistent, fail-closed, no retry)."""
    if not os.path.isabs(path):
        raise SecretError("REVIEWER_PROXY_SECRET_FILE must be an absolute path")
    max_age = _max_age_seconds()
    lst = os.lstat(path)  # FileNotFoundError -> transient-retry candidate
    if stat.S_ISLNK(lst.st_mode):
        raise SecretError("REVIEWER_PROXY_SECRET_FILE must not be a symlink")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        fd = os.open(path, flags)
    except FileNotFoundError:
        raise
    except OSError as e:
        # ELOOP (symlink swapped in under O_NOFOLLOW), EACCES, etc. -> persistent, fail closed.
        raise SecretError("REVIEWER_PROXY_SECRET_FILE is unreadable or not a plain file (%s)" % e.errno)
    try:
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode):
            raise SecretError("REVIEWER_PROXY_SECRET_FILE must be a regular file")
        if st.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SecretError("REVIEWER_PROXY_SECRET_FILE must have zero group/world permission bits")
        if st.st_uid not in (0, os.geteuid()):
            raise SecretError("REVIEWER_PROXY_SECRET_FILE must be owned by root or the process user")
        if st.st_size > MAX_FILE_BYTES:
            raise SecretError("REVIEWER_PROXY_SECRET_FILE exceeds the 64 KiB size cap")
        now = time.time()
        if st.st_mtime > now + FUTURE_MTIME_SKEW_SECONDS:
            raise SecretError("REVIEWER_PROXY_SECRET_FILE mtime is in the future beyond skew")
        if now - st.st_mtime > max_age:
            raise SecretError("REVIEWER_PROXY_SECRET_FILE is stale beyond the configured max age")
        # read the COMPLETE bounded file — never assume one os.read returns every byte — and fail closed
        # the moment total exceeds the cap (defence in depth beyond the fstat size check).
        chunks = []
        total = 0
        while True:
            b = os.read(fd, 65536)
            if not b:
                break
            total += len(b)
            if total > MAX_FILE_BYTES:
                raise SecretError("REVIEWER_PROXY_SECRET_FILE exceeds the 64 KiB size cap")
            chunks.append(b)
        data = b"".join(chunks)
    finally:
        os.close(fd)
    try:
        value = data.decode("utf-8", "strict").strip()
    except UnicodeDecodeError:
        raise SecretError("REVIEWER_PROXY_SECRET_FILE is not valid UTF-8")
    if not value:
        raise SecretError("REVIEWER_PROXY_SECRET_FILE is empty after trim")
    return value


def resolve():
    """Return (value, source_kind). Raise SecretError (fail-closed) on any invalid configuration.
    source_kind is one of FILE/ENV/DEV. Never returns/raises with secret content."""
    fp = _file_path()
    ev = _env_secret()
    if fp and ev:
        raise SecretError("both REVIEWER_PROXY_SECRET_FILE and REVIEWER_PROXY_SECRET are set — "
                          "ambiguous secret source, refusing")
    if fp:
        try:
            return _read_secure_file(fp), FILE
        except FileNotFoundError:
            # transient atomic-replacement race ONLY: one bounded retry, then fail closed.
            time.sleep(_RENAME_RACE_RETRY_DELAY)
            try:
                return _read_secure_file(fp), FILE
            except FileNotFoundError:
                raise SecretError("REVIEWER_PROXY_SECRET_FILE is missing")
    if ev:
        return ev, ENV
    if dev_mode():
        return DEV_REVIEWER_SECRET, DEV
    raise SecretError("REVIEWER_PROXY_SECRET is not configured")


def status():
    """Non-secret health signal: (configured: bool, source: str|None). A resolvable FILE or env secret is
    'configured'; the dev fixture and any unresolved/invalid state are NOT. Never exposes the value."""
    try:
        _, src = resolve()
    except SecretError:
        return False, None
    return (src in (FILE, ENV)), src
