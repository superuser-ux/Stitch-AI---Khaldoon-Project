#!/usr/bin/env python3
"""Fail closed if an exact candidate secret occurs in retained/runtime evidence."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys


PROJECT = "tanaghom-zitadel-dev"
SERVICES = ("postgres", "zitadel-api", "zitadel-login", "caddy")
SECRET_ROOT = pathlib.Path("/run/tanaghom-zitadel/current")


def run_capture(args: list[str]) -> tuple[bytes, bytes]:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed without retained output: {args[0]}")
    return result.stdout, result.stderr


def run_bytes(args: list[str]) -> bytes:
    return run_capture(args)[0]


def compose_args(package: pathlib.Path, *args: str) -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        PROJECT,
        "-f",
        str(package / "docker-compose.yml"),
        *args,
    ]


def service_id(package: pathlib.Path, service: str) -> str:
    value = run_bytes(compose_args(package, "ps", "-q", service)).decode("ascii").strip()
    if not value:
        raise RuntimeError(f"candidate service is absent: {service}")
    return value


def load_secrets(package: pathlib.Path, *, include_pat: bool) -> list[bytes]:
    secrets = [
        (SECRET_ROOT / "masterkey").read_bytes(),
        (SECRET_ROOT / "postgres_password").read_bytes(),
    ]
    steps = (SECRET_ROOT / "first-instance-steps.yaml").read_text(encoding="utf-8")
    password_lines = [line.split("Password:", 1)[1].strip() for line in steps.splitlines() if "Password:" in line]
    if len(password_lines) != 1:
        raise RuntimeError("bootstrap password source is ambiguous")
    secrets.append(json.loads(password_lines[0]).encode())

    if include_pat:
        login_id = service_id(package, "zitadel-login")
        secrets.append(run_bytes(["docker", "exec", login_id, "cat", "/zitadel/bootstrap/login-client.pat"]).strip())
    unique = []
    for value in secrets:
        if len(value) < 12:
            raise RuntimeError("candidate secret is unexpectedly short")
        if value not in unique:
            unique.append(value)
    return unique


def candidate_artifacts(
    package: pathlib.Path, evidence: pathlib.Path, *, runtime: bool
) -> list[tuple[str, bytes, pathlib.Path | None, bytes | None]]:
    compose_stdout, compose_stderr = run_capture(compose_args(package, "config"))
    artifacts: list[tuple[str, bytes, pathlib.Path | None, bytes | None]] = [
        (
            "rendered-compose-memory",
            compose_stdout + compose_stderr,
            None if runtime else evidence / "compose.rendered.yaml",
            None if runtime else compose_stdout,
        ),
    ]
    if runtime:
        for service in SERVICES:
            container_id = service_id(package, service)
            inspect_stdout, inspect_stderr = run_capture(["docker", "inspect", container_id])
            artifacts.append(
                (
                    f"inspect:{service}",
                    inspect_stdout + inspect_stderr,
                    evidence / f"{service}.inspect.json",
                    inspect_stdout,
                )
            )
            logs_stdout, logs_stderr = run_capture(["docker", "logs", container_id])
            artifacts.append(
                (f"logs:{service}", logs_stdout + logs_stderr, None, None)
            )

    evidence_root = package / "evidence"
    if evidence_root.exists():
        for path in sorted(evidence_root.rglob("*")):
            if path.is_file() and not path.is_symlink():
                artifacts.append((f"evidence:{path.relative_to(package)}", path.read_bytes(), None, None))
    if not evidence.is_relative_to(evidence_root):
        raise RuntimeError("evidence directory escaped package evidence root")
    return artifacts


def main() -> int:
    if len(sys.argv) != 4 or sys.argv[3] not in {"predeploy", "runtime"}:
        print("FATAL: secret_scan.py requires package, evidence, and predeploy|runtime", file=sys.stderr)
        return 2
    package = pathlib.Path(sys.argv[1]).resolve()
    evidence = pathlib.Path(sys.argv[2]).resolve()
    runtime = sys.argv[3] == "runtime"
    try:
        secrets = load_secrets(package, include_pat=runtime)
        artifacts = candidate_artifacts(package, evidence, runtime=runtime)
        findings = []
        for name, payload, _retain_path, _retain_payload in artifacts:
            if any(secret in payload for secret in secrets):
                findings.append(name)
        if findings:
            for name in findings:
                print(f"FATAL: candidate secret found in {name}", file=sys.stderr)
            return 3
        evidence.mkdir(parents=True, exist_ok=True)
        for _name, _payload, retain_path, retain_payload in artifacts:
            if retain_path is None:
                continue
            temporary = retain_path.with_name(f".{retain_path.name}.new")
            if retain_payload is None:
                raise RuntimeError("retained artifact payload is unavailable")
            temporary.write_bytes(retain_payload)
            temporary.chmod(0o600)
            temporary.replace(retain_path)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FATAL: secret scan could not prove absence: {exc}", file=sys.stderr)
        return 3
    print("SECRET_SCAN_VERDICT=PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
