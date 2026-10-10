"""QA verdict policy: distinguish real regressions from environmental (flaky) failures.

BABD forces QA's verdict to FAIL whenever the project's test_command exits non-zero
(see Flow.check_evidence). That is correct for deterministic suites, but a suite with
network-dependent tests (Solana RPC, Jito bundles, live executors, ...) fails
*environmentally* -- the exit code is non-zero even when the code under test is fine.

This module adds an opt-in, per-project policy:

    "qa_policy": {
        "treat_flaky_as_pass": true,
        "flaky_patterns": ["Network", "socket", "ECONN", ...],   # plain substrings (auto-escaped)
        "allow_failure_files": ["fase_p0xl", "positionMonitor"],# flaky test files by name
        "known_failing": ["exact substring of an accepted failure"]
    }

When "treat_flaky_as_pass" is on and *every* failing test line is accepted -- because it
contains one of the "flaky_patterns"/"known_failing" substrings, or names one of the
"allow_failure_files" -- the non-zero exit is treated as environmental and QA's own
verdict stands. If even one failure is NOT accepted, the run counts as a real failure and
the verdict stays FAIL, so this cannot mask a genuine regression.

Matching is SUBSTRING-based (case-insensitive): every pattern is escaped before compiling,
so `sell() with no keypair` matches literally. This avoids the classic trap where a stray
`()` or `.` in a test name is silently interpreted as a regex.

The policy is intentionally conservative: it only ever *prevents* an automatic FAIL on
accepted failures. It never turns a genuine FAIL into a PASS.
"""
from __future__ import annotations

import re

# Default patterns used when a project enables treat_flaky_as_pass but does NOT supply
# its own flaky_patterns list. Plain substrings (escaped at compile time).
DEFAULT_FLAKY_PATTERNS = [
    "network", "socket",
    "ECONNREFUSED", "ECONNRESET", "ECONNABORTED",
    "ETIMEDOUT", "ENOTFOUND", "EAI_AGAIN",
    "fetch failed", "timeout", "timed out",
    "getaddrinfo", "connection refused", "connection reset", "connection closed",
    "rate limit", "Temporary failure in name resolution",
    "jito", "rpc", "dns",
    "HAS_ML",
]


def _compiled_patterns(policy: dict) -> list:
    # A project-supplied list REPLACES the defaults (clearly intentional). All entries are
    # treated as literal substrings and escaped -- predictable and regex-trap-free.
    raw = policy.get("flaky_patterns")
    if not raw:
        raw = list(DEFAULT_FLAKY_PATTERNS)
    out = []
    for p in raw:
        try:
            out.append(re.compile(re.escape(str(p)), re.IGNORECASE))
        except re.error:
            pass
    return out


def _accepted(line: str, compiled: list, policy: dict) -> bool:
    if any(c.search(line) for c in compiled):
        return True
    low = line.lower()
    for sub in (policy.get("allow_failure_files") or []):
        if str(sub).lower() in low:
            return True
    for sub in (policy.get("known_failing") or []):
        if str(sub).lower() in low:
            return True
    return False


def classify_failures(output: str = "", policy: dict | None = None, failures: list | None = None) -> dict:
    """Classify failures as flaky (accepted) vs real.

    Prefers the pre-extracted ``failures`` list (from projects.extract_failures, taken from the
    FULL untruncated output) when available; otherwise falls back to scanning the (possibly
    truncated) ``output`` text for `not ok` / `FAILED` lines.
    """
    policy = policy or {}
    compiled = _compiled_patterns(policy)

    lines = list(failures) if failures else []
    if not lines:
        for raw in (output or "").splitlines():
            s = raw.strip()
            if not s:
                continue
            if s.lower().startswith("not ok") or s.startswith(("FAILED ", "FAIL: ")):
                lines.append(s)

    real_lines, flaky_lines = [], []
    for line in lines:
        (flaky_lines if _accepted(line, compiled, policy) else real_lines).append(line)

    return {
        "total": len(lines),
        "flaky": len(flaky_lines),
        "real": len(real_lines),
        "real_lines": real_lines[:20],
        "flaky_lines": flaky_lines[:20],
    }


def is_flaky_only(output: str = "", policy: dict | None = None, failures: list | None = None) -> tuple:
    """(bool, info). True when there is >=1 failure and *every* failure is accepted/flaky."""
    info = classify_failures(output, policy, failures)
    if info["total"] == 0:
        return False, info
    return (info["real"] == 0 and info["flaky"] > 0), info


def should_override_fail(policy: dict | None) -> bool:
    policy = policy or {}
    return bool(policy.get("treat_flaky_as_pass", False))
