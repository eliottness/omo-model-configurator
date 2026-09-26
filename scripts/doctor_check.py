#!/usr/bin/env python3
"""Run oh-my-openagent's own `doctor` and separate real findings from known noise.

Why this wrapper exists
-----------------------
`doctor` is the authoritative check on how your config actually resolves — it
reports effective model resolution per agent and category, deprecated config
keys, and capability-fallback warnings. Static linting cannot see any of that.

But its output is not all equally actionable. At least one check reports a
*working* provider as unavailable, because it consults OpenCode's model cache
rather than the provider itself. Reported verbatim, that warning sends people
chasing a non-problem — and worse, it trains them to ignore the whole report.

So this wrapper classifies:

  actionable            -> fix these
  known false positive  -> annotated with the command that proves it is noise

Version pinning
---------------
Pass `--version` so a report is reproducible. `doctor`'s checks and their
wording change between releases; an unpinned `bunx` invocation silently
upgrades underneath you and your findings move.

Offline use
-----------
`--from-file` reads a previously captured `doctor --json` payload instead of
shelling out, which is what the test suite uses.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Final

# `doctor` groups its checks under these names (see OMO docs/reference/cli.md).
# Listed for orientation only; unknown groups are passed through unchanged.
KNOWN_CHECK_GROUPS: Final[tuple[str, ...]] = (
    "System",
    "Configuration",
    "TUI Plugin",
    "Deprecated Reasoning Keys",
    "Tools",
    "Models",
    "Telemetry",
    "Team Mode",
)

_MODEL_CACHE_PROVIDERS_RE: Final[re.Pattern[str]] = re.compile(
    r"not found in OpenCode model cache:\s*(?P<providers>.+)", re.IGNORECASE
)


@dataclass(frozen=True)
class Finding:
    group: str
    title: str
    description: str
    severity: str
    affects: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "group": self.group,
            "title": self.title,
            "description": self.description,
            "severity": self.severity,
            "affects": list(self.affects),
        }


@dataclass(frozen=True)
class KnownFalsePositive:
    finding: Finding
    why: str
    how_to_verify: str
    status: str = "suspected"
    live_entitlement: str = "not-probed"

    def as_dict(self) -> dict[str, Any]:
        d = self.finding.as_dict()
        d["why_probably_noise"] = self.why
        d["how_to_verify"] = self.how_to_verify
        d["status"] = self.status
        d["live_entitlement"] = self.live_entitlement
        return d


@dataclass
class Report:
    pinned_version: str | None
    actionable: list[Finding] = field(default_factory=list)
    known_false_positives: list[KnownFalsePositive] = field(default_factory=list)
    groups_seen: list[str] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    confirmed_noise: list[KnownFalsePositive] = field(default_factory=list)
    command_evidence: dict[str, Any] = field(default_factory=dict)

    @property
    def actionable_errors(self) -> list[Finding]:
        return [f for f in self.actionable if f.severity.lower() == "error"]

    def as_dict(self) -> dict[str, Any]:
        return {
            "pinned_version": self.pinned_version,
            "groups_seen": self.groups_seen,
            "summary": self.summary,
            "actionable_count": len(self.actionable),
            "actionable_error_count": len(self.actionable_errors),
            "suspected_count": len(self.known_false_positives),
            "confirmed_noise_count": len(self.confirmed_noise),
            "actionable": [f.as_dict() for f in self.actionable],
            "suspected": [k.as_dict() for k in self.known_false_positives],
            "confirmed_noise": [k.as_dict() for k in self.confirmed_noise],
            "command_evidence": self.command_evidence,
        }


def classify(finding: Finding) -> KnownFalsePositive | None:
    """Return a KnownFalsePositive when this finding is a documented non-problem.

    Currently one rule: the model-cache provider warning. It fires whenever a
    provider is reachable but absent from OpenCode's cached model list, which is
    routine for gateway/proxy providers and for any provider added since the
    cache was last refreshed.
    """
    haystack = f"{finding.title} {finding.description}".lower()
    if "unavailable provider" not in haystack:
        return None
    match = _MODEL_CACHE_PROVIDERS_RE.search(finding.description)
    if match is None:
        return None
    providers = [p.strip() for p in match.group("providers").split(",") if p.strip()]
    if not providers:
        return None
    probe = providers[0]
    return KnownFalsePositive(
        finding=finding,
        why=(
            "This check reads OpenCode's cached model list, not the provider. A "
            "provider that works but is missing from the cache is reported here "
            "anyway."
        ),
        how_to_verify=(
            f'Verify by calling it directly: opencode run -m {probe}/<model> '
            f'--format json "reply with exactly: OK". If that returns text, '
            f"{probe} works and this warning is noise. "
            f"`bunx oh-my-openagent refresh-model-capabilities` may clear it."
        ),
    )


def build_report(
    payload: Any, pinned_version: str | None, probe: Any = None,
) -> Report:
    if not isinstance(payload, dict):
        raise ValueError("doctor payload must be a JSON object")
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("doctor payload has no 'results' array")

    report = Report(pinned_version=pinned_version)
    raw_summary = payload.get("summary")
    report.summary = raw_summary if isinstance(raw_summary, dict) else {}
    report.command_evidence = payload.get("command_evidence", {})

    for entry in results:
        if not isinstance(entry, dict):
            continue
        group = str(entry.get("name", "<unnamed>"))
        report.groups_seen.append(group)
        issues = entry.get("issues")
        if not isinstance(issues, list):
            continue
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            affects_raw = issue.get("affects")
            affects = tuple(
                str(a) for a in affects_raw if isinstance(a, (str, int, float))
            ) if isinstance(affects_raw, list) else ()
            finding = Finding(
                group=group,
                title=str(issue.get("title", "")),
                description=str(issue.get("description", "")),
                severity=str(issue.get("severity", "warning")),
                affects=affects,
            )
            known = classify(finding)
            if known is not None:
                match = _MODEL_CACHE_PROVIDERS_RE.search(finding.description)
                providers = {
                    name.strip() for name in match.group("providers").split(",")
                } if match else set()
                admitted = {
                    row["model"].split("/", 1)[0]
                    for row in (probe or {}).get("models", [])
                    if isinstance(row.get("model"), str)
                    and row.get("registry_admitted") is True
                }
                same_harness = (probe or {}).get("runtime", {}).get("surface") == payload.get("target", "opencode")
                if same_harness and providers and providers.issubset(admitted):
                    report.confirmed_noise.append(KnownFalsePositive(
                        known.finding, known.why, known.how_to_verify,
                        status="registry-confirmed",
                    ))
                else:
                    report.known_false_positives.append(known)
            else:
                report.actionable.append(finding)
    return report


def doctor_command(harness: str, version: str | None, platform: str) -> list[str]:
    if harness in {"native", "senpi"}:
        return ["omo", "doctor"]
    spec = "oh-my-openagent" if version is None else f"oh-my-openagent@{version}"
    return ["bunx", spec, "doctor", "--json", "--platform", platform]


def run_doctor(version: str | None, platform: str, harness: str = "opencode") -> Any:
    cmd = doctor_command(harness, version, platform)
    if shutil.which(cmd[0]) is None:
        raise RuntimeError(f"{cmd[0]} not on PATH; use --from-file for captured evidence")
    if harness in {"native", "senpi"} and version:
        from runtime_config import detect_runtime
        detected = detect_runtime("native")
        if detected.product_version != version:
            raise RuntimeError(
                f"installed native version {detected.product_version} differs from pin {version}"
            )
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    stdout = proc.stdout.strip()
    evidence = {
        "command": cmd, "exit_code": proc.returncode,
        "stdout": proc.stdout, "stderr": proc.stderr,
    }
    if harness in {"native", "senpi"}:
        issues = [{
            "title": line,
            "description": "",
            "severity": "warning" if line.startswith("WARN") else "error",
            "affects": ["native runtime"],
        } for line in stdout.splitlines() if line.startswith(("WARN", "FAIL", "ERROR"))]
        if proc.returncode and not any(i["severity"] == "error" for i in issues):
            issues.append({
                "title": f"Native doctor exited {proc.returncode}",
                "description": proc.stderr,
                "severity": "error", "affects": ["native runtime"],
            })
        return {"target": "native", "results": [{"name": "Native", "issues": issues}],
                "command_evidence": evidence}
    if not stdout:
        raise RuntimeError(
            f"`{' '.join(cmd)}` produced no stdout (exit {proc.returncode}): "
            f"{proc.stderr.strip()[:300]}"
        )
    # bunx may prepend install chatter before the JSON object.
    start = stdout.find("{")
    if start == -1:
        raise ValueError("no JSON object found in doctor output")
    payload = json.loads(stdout[start:])
    payload["command_evidence"] = evidence
    return payload


def render(report: Report) -> str:
    lines: list[str] = []
    lines.append(
        f"doctor: {len(report.actionable)} actionable, "
        f"{len(report.known_false_positives)} suspected cache finding(s), "
        f"{len(report.confirmed_noise)} registry-confirmed"
        + (f" [pinned {report.pinned_version}]" if report.pinned_version else
           " [UNPINNED - pass --version for a reproducible report]")
    )
    if report.actionable:
        lines.append("")
        lines.append("ACTIONABLE")
        for f in report.actionable:
            lines.append(f"  [{f.severity}] {f.group}: {f.title}")
            if f.description:
                lines.append(f"      {f.description}")
            if f.affects:
                lines.append(f"      affects: {', '.join(f.affects)}")
    if report.known_false_positives:
        lines.append("")
        lines.append("SUSPECTED CACHE FINDINGS (verification required)")
        for k in report.known_false_positives:
            lines.append(f"  [{k.finding.severity}] {k.finding.group}: {k.finding.title}")
            lines.append(f"      {k.finding.description}")
            lines.append(f"      why: {k.why}")
            lines.append(f"      {k.how_to_verify}")
    for finding in report.confirmed_noise:
        lines.append(f"REGISTRY-CONFIRMED: {finding.finding.title}; entitlement not probed")
    if not report.actionable and not report.known_false_positives and not report.confirmed_noise:
        lines.append("")
        lines.append("No issues reported.")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run oh-my-openagent doctor and split real findings from known noise.",
    )
    src = parser.add_mutually_exclusive_group()
    src.add_argument("--from-file", metavar="PATH",
                     help="read a captured `doctor --json` payload instead of running it")
    parser.add_argument("--version", metavar="VER",
                        help="pin the oh-my-openagent version (recommended; e.g. 4.19.4)")
    parser.add_argument("--platform", default="opencode", choices=("opencode", "codex"))
    parser.add_argument("--harness", choices=("auto", "native", "senpi", "opencode"), default="opencode")
    parser.add_argument("--probe-file", help="Captured registry evidence; never a live-entitlement assertion")
    parser.add_argument("--json", action="store_true", dest="as_json",
                        help="emit machine-readable output")
    parser.add_argument("--strict", action="store_true",
                        help="fail on any actionable finding, not only errors")
    args = parser.parse_args(argv)

    try:
        if args.from_file:
            payload = json.loads(open(args.from_file, encoding="utf-8").read())
        else:
            harness = args.harness
            if harness == "auto":
                from runtime_config import detect_runtime
                harness = detect_runtime().harness
            payload = run_doctor(args.version, args.platform, harness)
    except json.JSONDecodeError as exc:
        print(f"ERROR: could not parse doctor JSON output: {exc}", file=sys.stderr)
        return 2
    except (OSError, RuntimeError, ValueError, subprocess.TimeoutExpired) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    try:
        probe = None
        if args.probe_file:
            with open(args.probe_file, encoding="utf-8") as stream:
                probe = json.load(stream)
        report = build_report(payload, args.version, probe)
    except (OSError, ValueError) as exc:
        print(f"ERROR: unexpected doctor JSON shape: {exc}", file=sys.stderr)
        return 2

    print(json.dumps(report.as_dict(), indent=1) if args.as_json else render(report))

    if report.actionable_errors:
        return 1
    if args.strict and (report.actionable or report.known_false_positives):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
