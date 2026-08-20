"""#387 — focused unit test for the manager-neutral reviewer-proxy secret resolver.

Pure-function; no DB, no HTTP, no network. Run:  python -m gates.reviewer_secret_selftest
Covers: secure file, env compatibility, explicit dev fallback, source ambiguity fail-closed,
missing/unreadable/insecure/symlink/oversize/empty/stale/future FILE, no invalid-FILE fallback,
atomic replacement, and that a resolved value never leaks into an error message.
"""
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(__file__))
import reviewer_secret as rs  # noqa: E402

_FAIL = 0


def check(name, cond):
    global _FAIL
    if cond:
        print("  [PASS] " + name)
    else:
        _FAIL += 1
        print("  [FAIL] " + name)


ENV_KEYS = ("REVIEWER_PROXY_SECRET", "REVIEWER_PROXY_SECRET_FILE",
            "REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS", "TANAGHOM_DEV_MODE")


def clear_env():
    for k in ENV_KEYS:
        os.environ.pop(k, None)


def write_secret_file(dirpath, value=b"file-backed-secret-XYZ", mode=0o400, age=0.0, name="reviewer_proxy_secret"):
    p = os.path.join(dirpath, name)
    with open(p, "wb") as f:
        f.write(value)
    os.chmod(p, mode)
    if age:
        t = time.time() - age
        os.utime(p, (t, t))
    return p


def expect_secreterror(fn):
    try:
        fn()
        return False, "no-raise"
    except rs.SecretError as e:
        return True, str(e)
    except Exception as e:  # wrong exception type
        return False, type(e).__name__ + ":" + str(e)


def main():
    d = tempfile.mkdtemp(prefix="revsec-")
    secret_value = "file-backed-secret-XYZ"

    # 1) env compatibility
    clear_env(); os.environ["REVIEWER_PROXY_SECRET"] = "  env-secret-123  "
    v, src = rs.resolve()
    check("env source resolves (trimmed) and is 'env'", v == "env-secret-123" and src == rs.ENV)
    check("env source reports configured=True, source=env", rs.status() == (True, rs.ENV))

    # 2) explicit dev fallback only under dev-mode, and NOT reported configured
    clear_env(); os.environ["TANAGHOM_DEV_MODE"] = "1"
    v, src = rs.resolve()
    check("dev-mode + nothing configured uses dev fixture", v == rs.DEV_REVIEWER_SECRET and src == rs.DEV)
    check("dev fixture is NOT reported configured", rs.status() == (False, rs.DEV))

    # 3) missing everything + no dev-mode -> fail closed
    clear_env()
    ok, msg = expect_secreterror(rs.resolve)
    check("nothing configured, no dev-mode -> SecretError", ok and "not configured" in msg)
    check("unconfigured status is (False, None)", rs.status() == (False, None))

    # 4) empty-string env is treated as unset
    clear_env(); os.environ["REVIEWER_PROXY_SECRET"] = "   "
    check("whitespace-only env is not configured", rs.status()[0] is False)

    # 5) secure FILE happy path
    clear_env()
    p = write_secret_file(d, mode=0o400)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p
    os.environ["REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS"] = "900"
    v, src = rs.resolve()
    check("valid FILE resolves and is 'file'", v == secret_value and src == rs.FILE)
    check("valid FILE reports configured=True, source=file", rs.status() == (True, rs.FILE))

    # 6) FILE wins even under dev-mode (dev fixture only when NEITHER configured)
    os.environ["TANAGHOM_DEV_MODE"] = "1"
    v, src = rs.resolve()
    check("FILE authoritative even under dev-mode", v == secret_value and src == rs.FILE)
    os.environ.pop("TANAGHOM_DEV_MODE", None)

    # 7) source ambiguity -> fail closed (both FILE and env)
    os.environ["REVIEWER_PROXY_SECRET"] = "env-and-file"
    ok, msg = expect_secreterror(rs.resolve)
    check("both FILE and env set -> ambiguous SecretError", ok and "ambiguous" in msg)
    os.environ.pop("REVIEWER_PROXY_SECRET", None)

    # 8) FILE missing max-age -> fail closed
    os.environ.pop("REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS", None)
    ok, msg = expect_secreterror(rs.resolve)
    check("FILE without positive max-age -> SecretError", ok and "MAX_AGE" in msg)
    os.environ["REVIEWER_PROXY_SECRET_FILE_MAX_AGE_SECONDS"] = "900"

    # 9) relative path -> fail closed
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = "relative/secret"
    ok, msg = expect_secreterror(rs.resolve)
    check("relative FILE path -> SecretError", ok and "absolute" in msg)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 10) group/world permission bits -> fail closed (no dev/env fallback)
    os.chmod(p, 0o444)
    ok, msg = expect_secreterror(rs.resolve)
    check("world-readable FILE -> SecretError (no fallback)", ok and "permission" in msg)
    os.chmod(p, 0o400)

    # 11) symlink -> fail closed
    link = os.path.join(d, "link_secret")
    try:
        os.symlink(p, link)
        os.environ["REVIEWER_PROXY_SECRET_FILE"] = link
        ok, msg = expect_secreterror(rs.resolve)
        check("symlink FILE -> SecretError", ok and "symlink" in msg)
    finally:
        os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 12) oversize -> fail closed
    big = write_secret_file(d, value=b"x" * (rs.MAX_FILE_BYTES + 1), mode=0o400, name="big")
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = big
    ok, msg = expect_secreterror(rs.resolve)
    check("oversize FILE -> SecretError", ok and "size cap" in msg)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 13) empty-after-trim -> fail closed
    empty = write_secret_file(d, value=b"   \n", mode=0o400, name="empty")
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = empty
    ok, msg = expect_secreterror(rs.resolve)
    check("empty-after-trim FILE -> SecretError", ok and "empty" in msg)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 14) stale -> fail closed
    stale = write_secret_file(d, mode=0o400, age=1000.0, name="stale")
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = stale
    ok, msg = expect_secreterror(rs.resolve)
    check("stale FILE (age>max) -> SecretError", ok and "stale" in msg)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 15) future mtime beyond skew -> fail closed
    future = write_secret_file(d, mode=0o400, age=-120.0, name="future")  # negative age => future
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = future
    ok, msg = expect_secreterror(rs.resolve)
    check("future-mtime FILE -> SecretError", ok and "future" in msg)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 16) missing FILE -> fail closed (after bounded retry), never env/dev fallback
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = os.path.join(d, "does-not-exist")
    os.environ["TANAGHOM_DEV_MODE"] = "1"  # prove NO dev fallback for an invalid FILE
    ok, msg = expect_secreterror(rs.resolve)
    check("missing FILE -> SecretError even with dev-mode on (no fallback)", ok and "missing" in msg)
    os.environ.pop("TANAGHOM_DEV_MODE", None)
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = p

    # 17) atomic same-directory replacement is observed without restart (new value on next resolve)
    p2tmp = os.path.join(d, ".reviewer_proxy_secret.tmp")
    with open(p2tmp, "wb") as f:
        f.write(b"rotated-secret-2")
    os.chmod(p2tmp, 0o400)
    os.replace(p2tmp, p)  # atomic rename over the leaf
    v, src = rs.resolve()
    check("atomic replacement observed without restart", v == "rotated-secret-2" and src == rs.FILE)

    # 18) no secret value ever appears in an error message (scan every SecretError raised above)
    #     re-trigger a representative failure and assert the value is absent
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = stale
    ok, msg = expect_secreterror(rs.resolve)
    check("error messages never contain the secret value",
          ok and "rotated-secret-2" not in msg and "file-backed-secret" not in msg)

    # 19) PARITY: the COMPLETE bounded file is read (value at the exact size cap resolves in full)
    capval = "A" * rs.MAX_FILE_BYTES
    capf = write_secret_file(d, value=capval.encode(), mode=0o400, name="capfull")
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = capf
    v, src = rs.resolve()
    check("complete bounded read: full-size (64 KiB) file read in its entirety",
          src == rs.FILE and v == capval and len(v) == rs.MAX_FILE_BYTES)

    # 20) PARITY: invalid UTF-8 is rejected (strict), matching the TS TextDecoder(fatal) mirror
    badf = write_secret_file(d, value=b"\xff\xfe\x00not-utf8", mode=0o400, name="badutf8")
    os.environ["REVIEWER_PROXY_SECRET_FILE"] = badf
    ok, msg = expect_secreterror(rs.resolve)
    check("invalid UTF-8 FILE -> SecretError (not valid UTF-8)", ok and "UTF-8" in msg)

    clear_env()
    print("\n" + ("ALL REVIEWER-SECRET RESOLVER CHECKS PASSED" if _FAIL == 0 else "FAILURES: %d" % _FAIL))
    return 0 if _FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
