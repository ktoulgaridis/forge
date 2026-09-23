#!/usr/bin/env python3
"""forge is org-generic: no tracked file names a specific org.

forge is a generator; an org's names (its own name, its repos, its products, its MCP
servers) reach an emitted package only through that org's `.forge.org.yaml`, never
through forge itself. This gate fails when a tracked file — path or content — carries a
forbidden name.

The forbidden-name list is NOT committed (committing it would itself name the org). It
comes from the FORGE_FORBIDDEN_NAMES environment variable: comma-separated,
case-insensitive substrings. Unset or empty, the gate skips. CI sets it from a repository
variable; a fork sets its own (CONTRIBUTING.md).

Run:  FORGE_FORBIDDEN_NAMES=name1,name2 uv run --with pytest pytest tests/test_forbidden_names.py -q
"""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
ENV = "FORGE_FORBIDDEN_NAMES"


def forbidden_names() -> list[str]:
    return [n.strip().lower() for n in os.environ.get(ENV, "").split(",") if n.strip()]


def tracked_files() -> list[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z"], check=True,
                         capture_output=True).stdout
    return [p for p in out.decode().split("\0") if p]


def hits(names: list[str]) -> list[str]:
    found = []
    for rel in tracked_files():
        path = ROOT / rel
        for name in names:
            if name in rel.lower():
                found.append(f"{rel}: path contains a forbidden name")
        if not path.is_file():
            continue
        text = path.read_bytes().decode("utf-8", errors="ignore").lower()
        for n, line in enumerate(text.splitlines(), 1):
            for name in names:
                if name in line:
                    found.append(f"{rel}:{n}: contains a forbidden name")
    return found


def test_no_tracked_file_names_a_forbidden_org_name():
    names = forbidden_names()
    if not names:
        pytest.skip(f"{ENV} is unset — the org-name gate runs only where it is configured")
    found = hits(names)
    # Report locations only: echoing the matched name would print it into CI logs.
    assert not found, "forge must stay org-generic:\n" + "\n".join(found)


def test_the_gate_sees_a_name_it_is_given():
    """The gate is not vacuous: a name that IS in the tree (this file's own env-var name)
    is found, so an empty result above means absence, not a scan that read nothing."""
    assert any("test_forbidden_names.py" in h for h in hits([ENV.lower()]))
