#!/usr/bin/env python3
"""Retain only fixed-vocabulary startup diagnostics; never persist raw logs."""

from __future__ import annotations

import json
import os
import pathlib
import re
import stat
import subprocess
import sys


PROJECT = "tanaghom-zitadel-dev"
SERVICES = {"postgres", "zitadel-api", "zitadel-login", "caddy"}
SECRET_ROOT = pathlib.Path("/run/tanaghom-zitadel/current")
LOGIN_VOLUME = "tanaghom-zitadel-dev_login_bootstrap"
MAX_CAPTURE_BYTES = 1_000_000
CONTAINER_ID = re.compile(r"^[0-9a-f]{64}$")
LOG_PATTERNS = {
    "already_exists": re.compile(rb"already exists", re.IGNORECASE),
    "authentication_failed": re.compile(rb"authentication failed", re.IGNORECASE),
    "connection_refused": re.compile(rb"connection refused", re.IGNORECASE),
    "deadline_exceeded": re.compile(rb"deadline exceeded|timed? out", re.IGNORECASE),
    "database": re.compile(rb"database", re.IGNORECASE),
    "event": re.compile(rb"event", re.IGNORECASE),
    "initialization": re.compile(rb"initiali[sz]", re.IGNORECASE),
    "invalid_configuration": re.compile(rb"invalid (configuration|config)", re.IGNORECASE),
    "migration": re.compile(rb"migration", re.IGNORECASE),
    "no_space": re.compile(rb"no space left", re.IGNORECASE),
    "out_of_memory": re.compile(rb"out of memory|oom", re.IGNORECASE),
    "panic": re.compile(rb"panic", re.IGNORECASE),
    "permission_denied": re.compile(rb"permission denied", re.IGNORECASE),
    "projection": re.compile(rb"projection", re.IGNORECASE),
    "ready": re.compile(rb"ready", re.IGNORECASE),
    "setup": re.compile(rb"setup", re.IGNORECASE),
}


def run(args: list[str], *, required: bool = True) -> bytes:
    result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    if required and result.returncode != 0:
        raise RuntimeError(f"command failed without retained output: {args[0]}")
    return result.stdout[-MAX_CAPTURE_BYTES:]


def required_secrets() -> list[bytes]:
    secrets = [
        (SECRET_ROOT / "masterkey").read_bytes(),
        (SECRET_ROOT / "postgres_password").read_bytes(),
    ]
    steps = (SECRET_ROOT / "first-instance-steps.yaml").read_text(encoding="utf-8")
    password_lines = [line.split("Password:", 1)[1].strip() for line in steps.splitlines() if "Password:" in line]
    if len(password_lines) != 1:
        raise RuntimeError("bootstrap password source is ambiguous")
    secrets.append(json.loads(password_lines[0]).encode())

    volume = json.loads(run(["docker", "volume", "inspect", LOGIN_VOLUME]))
    if len(volume) != 1 or volume[0].get("Name") != LOGIN_VOLUME or volume[0].get("Driver") != "local":
        raise RuntimeError("Login PAT volume identity is unsafe")
    docker_root = pathlib.Path(run(["docker", "info", "--format", "{{.DockerRootDir}}"]).decode().strip()).resolve()
    expected_mount = docker_root / "volumes" / LOGIN_VOLUME / "_data"
    mountpoint = pathlib.Path(volume[0].get("Mountpoint", ""))
    if not mountpoint.is_absolute() or mountpoint.resolve() != expected_mount:
        raise RuntimeError("Login PAT volume mountpoint is unsafe")
    mount_stat = mountpoint.stat(follow_symlinks=False)
    if stat.S_ISLNK(mount_stat.st_mode) or mount_stat.st_uid != 0 or mount_stat.st_gid != 0:
        raise RuntimeError("Login PAT volume metadata is unsafe")
    pat = mountpoint / "login-client.pat"
    if pat.exists(follow_symlinks=False):
        pat_stat = pat.stat(follow_symlinks=False)
        if not stat.S_ISREG(pat_stat.st_mode) or pat_stat.st_uid != 0 or pat_stat.st_gid != 0:
            raise RuntimeError("Login PAT file metadata is unsafe")
        secrets.append(pat.read_bytes().strip())

    unique: list[bytes] = []
    for value in secrets:
        if len(value) < 12:
            raise RuntimeError("candidate secret is unexpectedly short")
        if value not in unique:
            unique.append(value)
    return unique


def candidate_ids() -> list[str]:
    output = run(
        ["docker", "ps", "-aq", "--no-trunc", "--filter", f"label=com.docker.compose.project={PROJECT}"]
    ).decode("ascii")
    ids = [line for line in output.splitlines() if line]
    if not ids or any(not CONTAINER_ID.fullmatch(container_id) for container_id in ids):
        raise RuntimeError("candidate container identity is unavailable or unsafe")
    return ids


def typed_state(inspected: dict[str, object], service: str) -> dict[str, object]:
    state = inspected.get("State")
    if not isinstance(state, dict):
        raise RuntimeError("candidate state is malformed")
    status_value = state.get("Status")
    if status_value not in {"created", "running", "paused", "restarting", "removing", "exited", "dead"}:
        raise RuntimeError("candidate state status is unknown")
    health = state.get("Health") or {}
    if not isinstance(health, dict):
        raise RuntimeError("candidate health is malformed")
    health_status = health.get("Status", "none")
    if health_status not in {"none", "starting", "healthy", "unhealthy"}:
        raise RuntimeError("candidate health status is unknown")
    summary = {
        "service": service,
        "status": status_value,
        "running": bool(state.get("Running", False)),
        "paused": bool(state.get("Paused", False)),
        "restarting": bool(state.get("Restarting", False)),
        "oom_killed": bool(state.get("OOMKilled", False)),
        "dead": bool(state.get("Dead", False)),
        "exit_code": int(state.get("ExitCode", 0)),
        "restart_count": int(inspected.get("RestartCount", 0)),
        "health_status": health_status,
        "health_failing_streak": int(health.get("FailingStreak", 0)),
    }
    return summary


def main() -> int:
    if len(sys.argv) != 3:
        print("FATAL: failure diagnostics require package and evidence paths", file=sys.stderr)
        return 2
    package = pathlib.Path(sys.argv[1]).resolve()
    evidence = pathlib.Path(sys.argv[2]).resolve()
    evidence_root = package / "evidence"
    if not evidence.is_relative_to(evidence_root):
        print("FATAL: failure evidence escaped package evidence root", file=sys.stderr)
        return 3

    try:
        secrets = required_secrets()
        summaries: list[dict[str, object]] = []
        for container_id in candidate_ids():
            raw_inspect = run(["docker", "inspect", container_id])
            inspected = json.loads(raw_inspect)[0]
            service = inspected.get("Config", {}).get("Labels", {}).get("com.docker.compose.service")
            if service not in SERVICES:
                raise RuntimeError("candidate service label is outside the allowlist")
            raw_logs = run(["docker", "logs", "--tail", "2000", container_id], required=False)
            if any(secret in payload for secret in secrets for payload in (raw_inspect, raw_logs)):
                raise RuntimeError("candidate secret occurred in transient startup diagnostics")
            summary = typed_state(inspected, service)
            summary["log_bytes_observed"] = len(raw_logs)
            summary["log_lines_observed"] = raw_logs.count(b"\n")
            summary["log_categories"] = {
                name: len(pattern.findall(raw_logs)) for name, pattern in sorted(LOG_PATTERNS.items())
            }
            summaries.append(summary)

        # Only typed values and fixed-vocabulary category names cross the retention boundary.
        payload = (json.dumps({"schema": 1, "services": sorted(summaries, key=lambda row: str(row["service"]))}, indent=2) + "\n").encode()
        if any(secret in payload for secret in secrets):
            raise RuntimeError("candidate secret occurred in fixed-vocabulary summary")
        evidence.mkdir(parents=True, exist_ok=True)
        temporary = evidence / ".failure-summary.json.new"
        temporary.write_bytes(payload)
        temporary.chmod(0o600)
        os.replace(temporary, evidence / "failure-summary.json")
    except (OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"FATAL: failure diagnostics could not prove safe retention: {exc}", file=sys.stderr)
        return 3

    print(f"FAILURE_DIAGNOSTICS_VERDICT=PASS path={evidence / 'failure-summary.json'} raw_logs_retained=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
