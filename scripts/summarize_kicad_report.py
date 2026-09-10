#!/usr/bin/env python3
"""Produce a compact, stable summary of a KiCad ERC or DRC JSON report."""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

try:
    from kicad_contracts import stable_uuid
except ImportError:  # direct repository test import
    from scripts.kicad_contracts import stable_uuid


REFERENCE_PATTERNS = (
    re.compile(r"\bSymbol\s+(?P<ref>[A-Za-z][A-Za-z0-9_-]*\d+)\b"),
    re.compile(r"\bof\s+(?P<ref>[A-Za-z][A-Za-z0-9_-]*\d+)\b"),
)


def collect_findings(report: dict[str, Any]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for category in ("violations", "unconnected_items", "schematic_parity"):
        for finding in report.get(category, []) or []:
            item = {**finding, "category": category}
            item.setdefault(
                "uuid",
                stable_uuid("violation", {"category": category, **finding}),
            )
            findings.append(item)
    for sheet in report.get("sheets", []) or []:
        for finding in sheet.get("violations", []) or []:
            findings.append(
                {
                    **finding,
                    "category": "erc",
                    "sheet": sheet.get("path", ""),
                    "uuid": finding.get(
                        "uuid",
                        stable_uuid(
                            "violation",
                            {"sheet": sheet.get("path", ""), **finding},
                        ),
                    ),
                }
            )
    return findings


def references_for(finding: dict[str, Any]) -> set[str]:
    references: set[str] = set()
    for item in finding.get("items", []) or []:
        description = str(item.get("description", ""))
        for pattern in REFERENCE_PATTERNS:
            match = pattern.search(description)
            if match:
                references.add(match.group("ref"))
    return references


def summarize(report: dict[str, Any], limit: int = 10) -> dict[str, Any]:
    findings = collect_findings(report)
    by_severity = Counter(str(item.get("severity") or "unknown") for item in findings)
    by_type = Counter(str(item.get("type") or item["category"]) for item in findings)
    references = sorted({ref for finding in findings for ref in references_for(finding)})
    top_findings = []
    for finding in findings[:limit]:
        top_findings.append(
            {
                "category": finding["category"],
                "uuid": finding["uuid"],
                "type": finding.get("type"),
                "severity": finding.get("severity"),
                "description": finding.get("description"),
                "sheet": finding.get("sheet"),
                "references": sorted(references_for(finding)),
                "items": [
                    {
                        "description": item.get("description"),
                        "uuid": item.get("uuid") or stable_uuid("violation-item", item),
                        "pos": item.get("pos"),
                    }
                    for item in finding.get("items", []) or []
                ],
            }
        )
    return {
        "total": len(findings),
        "by_severity": dict(sorted(by_severity.items())),
        "by_type": dict(sorted(by_type.items())),
        "references": references,
        "top_findings": top_findings,
        "truncated": len(findings) > limit,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    print(json.dumps(summarize(report, max(0, args.limit)), separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
