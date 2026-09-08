"""Compact native KiCad DRC/ERC JSON with a multiset delta. Read-only."""
import argparse
import collections
import json
from pathlib import Path


def entries(report):
    if "sheets" in report:
        if not isinstance(report["sheets"], list):
            raise ValueError("Invalid ERC sheets")
        for sheet in report["sheets"]:
            if not isinstance(sheet.get("violations"), list):
                raise ValueError("ERC sheet missing violations list")
            for item in sheet["violations"]:
                yield "erc", item, sheet.get("path", "")
    else:
        for category in ("violations", "unconnected_items", "schematic_parity"):
            if not isinstance(report.get(category), list):
                raise ValueError("DRC report missing list: " + category)
            for item in report[category]:
                yield category, item, ""


def fingerprint(category, item, sheet):
    # Include stable UUID/position identities and descriptions. Do not use report dates.
    identities = sorted(json.dumps({k: obj[k] for k in ("uuid", "pos", "description") if k in obj}, sort_keys=True)
                        for obj in item.get("items", []))
    return json.dumps([category, sheet, item.get("type"), item.get("severity"),
                       item.get("description"), identities], sort_keys=True)


def summarize(report, baseline=None, limit=5):
    current = list(entries(report))
    counts = collections.Counter(c for c, _, _ in current)
    kinds = collections.Counter("%s/%s/%s" % (c, v.get("type", "unknown"), v.get("severity", "unknown"))
                                for c, v, _ in current)
    fps = collections.Counter(fingerprint(c, v, s) for c, v, s in current)
    result = {"source": report.get("source"), "report_date": report.get("date"),
              "kicad_version": report.get("kicad_version"), "total_items": len(current),
              "by_category": dict(counts), "by_type_severity": dict(kinds),
              "examples": [{"category": c, "sheet": s, **v} for c, v, s in current[:limit]],
              "freshness": "NOT_VERIFIED; this summarizes an existing report"}
    if baseline is not None:
        if ("sheets" in report) != ("sheets" in baseline) or report.get("source") != baseline.get("source"):
            raise ValueError("Baseline must have the same report kind and source")
        old = collections.Counter(fingerprint(c, v, s) for c, v, s in entries(baseline))
        added, removed = fps - old, old - fps
        result["delta"] = {"added": sum(added.values()), "resolved": sum(removed.values()),
                           "unchanged": sum((fps & old).values()),
                           "added_examples": [json.loads(f) for f in list(added)[:limit]]}
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("report", type=Path)
    ap.add_argument("--baseline", type=Path)
    ap.add_argument("--limit", type=int, default=5)
    args = ap.parse_args()
    if args.limit < 0:
        ap.error("--limit must be nonnegative")
    read = lambda path: json.loads(path.read_text(encoding="utf-8-sig"))
    try:
        result = summarize(read(args.report), read(args.baseline) if args.baseline else None, args.limit)
    except (ValueError, KeyError, TypeError) as error:
        ap.error(str(error))
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
