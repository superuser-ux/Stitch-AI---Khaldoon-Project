#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
SYNC_MAP_PATH = REPO_ROOT / "docs/design/lunaris/sync-map.json"
SYNC_STATUS_PATH = REPO_ROOT / "docs/design/lunaris/sync-status.json"


def _load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _staged_files() -> list[str]:
    out = subprocess.check_output(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        cwd=REPO_ROOT,
        text=True,
    )
    return [line.strip() for line in out.splitlines() if line.strip()]


def _normalize(paths: list[str]) -> list[str]:
    return [Path(p).as_posix() for p in paths]


def _trigger_paths(sync_map: dict) -> set[str]:
    exports = {entry["export"] for entry in sync_map["managed_exports"]}
    surfaces = set(sync_map["tracked_repo_surfaces"])
    return exports | surfaces


def _validate_status(sync_map: dict, sync_status: dict) -> list[str]:
    errors: list[str] = []

    if sync_status.get("status") != "in_sync":
        errors.append("sync-status.json must set \"status\": \"in_sync\" for managed design commits.")

    if sync_status.get("pencil_document") != sync_map.get("pencil_document"):
        errors.append("sync-status.json pencil_document does not match sync-map.json.")

    managed = sync_status.get("managed_exports")
    if not isinstance(managed, list):
        errors.append("sync-status.json missing managed_exports list.")
        return errors

    expected = {entry["export"]: entry for entry in sync_map["managed_exports"]}
    seen = {entry.get("export"): entry for entry in managed if isinstance(entry, dict)}

    if set(expected) != set(seen):
        errors.append("sync-status.json managed_exports does not match sync-map.json.")
        return errors

    for export_path, mapping in expected.items():
        status_entry = seen[export_path]
        for key in ("board", "node_id", "export"):
            if status_entry.get(key) != mapping.get(key):
                errors.append(f"sync-status.json entry for {export_path} does not match sync-map.json field {key}.")
        abs_export = REPO_ROOT / export_path
        if not abs_export.exists():
            errors.append(f"managed export is missing: {export_path}")
            continue
        actual_sha = _sha256(abs_export)
        if status_entry.get("sha256") != actual_sha:
            errors.append(
                f"sync-status.json has stale sha256 for {export_path}.\n"
                f"  expected: {actual_sha}\n"
                f"  recorded: {status_entry.get('sha256')}"
            )

    for key in ("verified_at", "verified_by", "notes"):
        if not sync_status.get(key):
            errors.append(f"sync-status.json missing required field: {key}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Guard managed Lunaris design sync.")
    parser.add_argument(
        "--files",
        nargs="*",
        help="Override the staged file set for testing. When omitted, staged files are read from git.",
    )
    args = parser.parse_args()

    sync_map = _load_json(SYNC_MAP_PATH)
    sync_status = _load_json(SYNC_STATUS_PATH)

    files = _normalize(args.files) if args.files is not None else _staged_files()
    if not files:
        print("design-sync: no staged files; skipping.")
        return 0

    trigger_paths = _trigger_paths(sync_map)
    touched = sorted(set(files) & trigger_paths)
    if not touched:
        print("design-sync: no managed Lunaris files touched; skipping.")
        return 0

    sync_status_rel = Path(sync_map["sync_status_file"]).as_posix()
    errors: list[str] = []

    if sync_status_rel not in files:
        errors.append(
            "Managed Lunaris design files changed, but sync-status.json is not part of this commit.\n"
            f"Add {sync_status_rel} and update its verification fields in the same commit."
        )

    errors.extend(_validate_status(sync_map, sync_status))

    if errors:
        print("design-sync: FAILED")
        print("Touched managed files:")
        for path in touched:
            print(f"  - {path}")
        print("Errors:")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("design-sync: OK")
    print("Touched managed files:")
    for path in touched:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
