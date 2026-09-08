"""Read-only tool probes. No installation, GUI launch, or design modification."""
import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def probe(command):
    try:
        result = subprocess.run(command, capture_output=True, text=True, errors="replace", timeout=20)
        return {"command": command, "exit_code": result.returncode,
                "output": (result.stdout + result.stderr).strip()[:1600]}
    except (OSError, subprocess.TimeoutExpired) as error:
        return {"command": command, "error": str(error)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--cli", default=shutil.which("kicad-cli"))
    ap.add_argument("--pcb-python", help="Python executable bundled with KiCad for legacy pcbnew")
    ap.add_argument("--java", default=shutil.which("java"))
    ap.add_argument("--router-jar", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    result = {"cli": probe([args.cli, "version"]) if args.cli else {"missing": True},
              "java": probe([args.java, "-version"]) if args.java else {"missing": True}}
    if args.cli:
        for name, command, flags in [
            ("drc", ["pcb", "drc"], ["--format", "--schematic-parity", "--exit-code-violations"]),
            ("erc", ["sch", "erc"], ["--format", "--exit-code-violations"]),
        ]:
            p = probe([args.cli] + command + ["--help"])
            result[name] = {"exit_code": p.get("exit_code"), "error": p.get("error"),
                            "supported_flags": {flag: flag in p.get("output", "") for flag in flags}}
    if args.pcb_python:
        code = ("import json,pcbnew as p; print(json.dumps({'version':p.GetBuildVersion(),"
                "'symbols':{n:hasattr(p,n) for n in ['LoadBoard','GetSettingsManager',"
                "'ZONE_FILLER','ExportSpecctraDSN','ImportSpecctraSES']}}))")
        result["pcbnew"] = probe([args.pcb_python, "-c", code])
    if args.router_jar:
        result["router_jar"] = {"path": str(args.router_jar.resolve()), "exists": args.router_jar.is_file(),
                                "runtime_compatibility": "NOT_TESTED"}
        if args.router_jar.is_file():
            result["router_jar"]["sha256"] = hashlib.sha256(args.router_jar.read_bytes()).hexdigest()
    result["scope"] = "Executable probes only; library paths, saved rules and router round-trip need separate checks."
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
