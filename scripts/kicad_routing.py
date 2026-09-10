#!/usr/bin/env python3
"""KiCadRoutingTools candidate jobs: read-only input, validated staged output, CLI/MCP."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from typing import Literal, Mapping, NotRequired, TypedDict

try:
    from kicad_contracts import with_stable_uuid
except ImportError:  # direct image/script execution
    import sys
    sys.path.insert(0, "/usr/local/lib/kicad-automation")
    try:
        from kicad_contracts import with_stable_uuid
    except ImportError:  # repository-root test import
        from scripts.kicad_contracts import with_stable_uuid

try:
    from kicad_topology import GridRouter, RouteRequest
except ImportError:  # direct repository execution
    import sys
    sys.path.insert(0, "/usr/local/lib/kicad-automation")
    try:
        from kicad_topology import GridRouter, RouteRequest
    except ImportError:  # repository-root test import
        from scripts.kicad_topology import GridRouter, RouteRequest

REVISION = "529f873d4c4c20493b1fa786cc9b42ce6cce2945"
SCRIPTS = {"route": "route.py", "diff": "route_diff.py", "planes": "route_planes.py"}
NUMBERS = {"track_width": (0.05, 10), "clearance": (0.05, 10),
           "via_size": (0.1, 10), "via_drill": (0.05, 5), "grid_step": (0.025, 1),
           "diff_pair_gap": (0.05, 10), "impedance": (1, 1000),
           "coplanar_gap": (0.05, 10), "zone_clearance": (0.05, 10),
           "gnd_via_distance": (0.1, 100), "length_match_tolerance": (0.01, 100)}
POLICY_NUMBERS = {
    "max_iterations": (1, 10_000_000), "max_probe_iterations": (1, 10_000_000),
    "same_net_pad_clearance": (-1, 10), "routing_clearance_margin": (1, 3),
    "hole_to_hole_clearance": (0, 10), "board_edge_clearance": (0, 10),
}
POLICY_BOOLEANS = {"strict_sizes", "no_fix_drc_settings", "force_reroute",
                   "rip_existing_nets", "keep_input_copper"}
FAB_TIERS = {"standard", "advanced", "auto"}
ESCALATIONS = {"off", "board", "fab"}
DIFF_ONLY = {"diff_pair_gap", "impedance", "coplanar_gap", "diff_pair_intra_match", "length_match_tolerance"}
PLANE_ONLY = {"zone_clearance", "power_nets", "power_nets_widths", "stitch_vias",
              "add_gnd_vias", "gnd_via_net", "gnd_via_distance"}
BOOL_OPTIONS = {"diff_pair_intra_match", "stitch_vias", "add_gnd_vias"}


class RoutingStep(TypedDict):
    operation: Literal['route', 'diff', 'planes']
    nets: list[str]
    layers: list[str]
    track_width: NotRequired[float]
    clearance: NotRequired[float]
    via_size: NotRequired[float]
    via_drill: NotRequired[float]
    grid_step: NotRequired[float]
    diff_pair_gap: NotRequired[float]
    impedance: NotRequired[float]
    coplanar_gap: NotRequired[float]
    zone_clearance: NotRequired[float]
    power_nets: NotRequired[list[str]]
    power_nets_widths: NotRequired[list[float]]
    diff_pair_intra_match: NotRequired[bool]
    stitch_vias: NotRequired[bool]
    add_gnd_vias: NotRequired[bool]
    gnd_via_net: NotRequired[str]
    gnd_via_distance: NotRequired[float]
    length_match_tolerance: NotRequired[float]
    max_iterations: NotRequired[int]
    max_probe_iterations: NotRequired[int]
    fab_tier: NotRequired[Literal["standard", "advanced", "auto"]]
    escalation: NotRequired[Literal["off", "board", "fab"]]
    strict_sizes: NotRequired[bool]
    no_fix_drc_settings: NotRequired[bool]
    force_reroute: NotRequired[bool]
    rip_existing_nets: NotRequired[bool]
    keep_input_copper: NotRequired[bool]
    same_net_pad_clearance: NotRequired[float]
    routing_clearance_margin: NotRequired[float]
    hole_to_hole_clearance: NotRequired[float]
    board_edge_clearance: NotRequired[float]


class RoutingPlan(TypedDict):
    project: str
    steps: list[RoutingStep]
    timeout_seconds: NotRequired[int]
    schema_version: NotRequired[int]


# Preserve strict plan validation at the MCP/Pydantic boundary too.
RoutingStep.__pydantic_config__ = {"extra": "forbid"}
RoutingPlan.__pydantic_config__ = {"extra": "forbid"}


def contained(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative or Path(relative).is_absolute():
        raise ValueError("path must be a non-empty workspace-relative path")
    path = (root / relative).resolve()
    path.relative_to(root.resolve())
    return path


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize_layer(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("layer names must be strings")
    value = value.removeprefix("BL_").replace("_", ".")
    if not re.fullmatch(r"[FB]\.Cu|In([1-9]|[12][0-9]|30)\.Cu", value):
        raise ValueError(f"unsupported copper layer: {value}")
    return value


def validate_plan(plan: dict) -> dict:
    if not isinstance(plan, dict) or set(plan) - {"project", "steps", "timeout_seconds", "schema_version"}:
        raise ValueError("plan accepts project, steps, timeout_seconds, schema_version only")
    schema_version = plan.get("schema_version", 1)
    if type(schema_version) is not int or schema_version not in (1, 2):
        raise ValueError("schema_version must be 1 or 2")
    if not isinstance(plan.get("project"), str):
        raise ValueError("project must be a relative .kicad_pcb path")
    timeout = plan.get("timeout_seconds", 600)
    if type(timeout) is not int or not 10 <= timeout <= 3600:
        raise ValueError("timeout_seconds must be 10..3600 per routing step")
    steps = plan.get("steps")
    if not isinstance(steps, list) or not 1 <= len(steps) <= 8:
        raise ValueError("steps must contain 1..8 routing operations")
    normalized = []
    for step in steps:
        allowed = {"operation", "nets", "layers", *NUMBERS, *POLICY_NUMBERS,
                   "power_nets", "power_nets_widths", *BOOL_OPTIONS, *POLICY_BOOLEANS,
                   "gnd_via_net", "fab_tier", "escalation"}
        if not isinstance(step, dict) or set(step) - allowed:
            raise ValueError("unknown step option; arbitrary upstream arguments are not accepted")
        operation = step.get("operation")
        if operation not in SCRIPTS:
            raise ValueError("operation must be route, diff, or planes")
        if operation != "diff" and set(step) & DIFF_ONLY:
            raise ValueError("differential controls are only valid for diff steps")
        if operation != "planes" and set(step) & PLANE_ONLY:
            raise ValueError("plane controls are only valid for planes steps")
        nets = step.get("nets")
        if not isinstance(nets, list) or not 1 <= len(nets) <= 100 or any(
            not isinstance(n, str) or not n or n.startswith("-") or len(n) > 256
            or any(ord(c) < 32 for c in n) for n in nets
        ):
            raise ValueError("nets must be explicit nonempty patterns; leading '-' is unsupported")
        layers = step.get("layers")
        if not isinstance(layers, list) or not layers or len(layers) > 32:
            raise ValueError("layers must be an explicit list of copper layers")
        clean = {"operation": operation, "nets": nets,
                 "layers": [normalize_layer(layer) for layer in layers]}
        for name, (low, high) in NUMBERS.items():
            if name in step:
                value = step[name]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"{name} must be between {low} and {high} mm")
                clean[name] = value
        for name, (low, high) in POLICY_NUMBERS.items():
            if name in step:
                value = step[name]
                if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
                    raise ValueError(f"{name} must be between {low} and {high}")
                if name in {"max_iterations", "max_probe_iterations"} and type(value) is not int:
                    raise ValueError(f"{name} must be an integer")
                clean[name] = value
        if "max_probe_iterations" in clean and "max_iterations" in clean and clean["max_probe_iterations"] > clean["max_iterations"]:
            raise ValueError("max_probe_iterations cannot exceed max_iterations")
        if "fab_tier" in step:
            if step["fab_tier"] not in FAB_TIERS:
                raise ValueError("fab_tier must be standard, advanced, or auto")
            clean["fab_tier"] = step["fab_tier"]
        if "escalation" in step:
            if step["escalation"] not in ESCALATIONS:
                raise ValueError("escalation must be off, board, or fab")
            clean["escalation"] = step["escalation"]
        for name in POLICY_BOOLEANS:
            if name in step:
                if type(step[name]) is not bool:
                    raise ValueError(f"{name} must be boolean")
                clean[name] = step[name]
        if clean.get("force_reroute") and clean.get("keep_input_copper"):
            raise ValueError("force_reroute and keep_input_copper are conflicting policies")
        if "power_nets" in step:
            values = step["power_nets"]
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
                raise ValueError("power_nets must be a non-empty string list on plane steps")
            clean["power_nets"] = values
        if "power_nets_widths" in step:
            values = step["power_nets_widths"]
            if not isinstance(values, list) or any(type(v) not in (int, float) or not math.isfinite(v) or not 0.05 <= v <= 10 for v in values):
                raise ValueError("power_nets_widths must contain finite widths between 0.05 and 10 mm")
            if "power_nets" not in clean or len(values) != len(clean["power_nets"]):
                raise ValueError("power_nets_widths must match power_nets length")
            clean["power_nets_widths"] = values
        for name in BOOL_OPTIONS:
            if name in step:
                if not isinstance(step[name], bool):
                    raise ValueError(f"{name} must be boolean")
                clean[name] = step[name]
        if "gnd_via_net" in step:
            if not isinstance(step["gnd_via_net"], str) or not step["gnd_via_net"]:
                raise ValueError("gnd_via_net must be a non-empty net name")
            clean["gnd_via_net"] = step["gnd_via_net"]
        if clean.get("via_drill", 0) >= clean.get("via_size", 100):
            raise ValueError("via_drill must be smaller than via_size")
        if schema_version == 2:
            # Explicit safe defaults: a candidate may not silently relax the
            # project contract or shrink a requested feature to rescue a run.
            clean.setdefault("fab_tier", "standard")
            clean.setdefault("escalation", "off")
            clean.setdefault("strict_sizes", True)
            clean.setdefault("no_fix_drc_settings", True)
            clean.setdefault("max_iterations", 100_000)
            clean.setdefault("max_probe_iterations", 10_000)
        normalized.append(clean)
    result = {"project": plan["project"], "steps": normalized, "timeout_seconds": timeout,
              "schema_version": schema_version}
    if schema_version == 1:
        result["warnings"] = ["schema_version omitted or 1 uses legacy router defaults; use schema_version=2 for strict policy"]
    return result


def command(root: Path, step: dict, board: Path, output: Path) -> list[str]:
    args = [sys.executable, str(root / "py_router" / SCRIPTS[step["operation"]]),
            str(board), str(output), "--nets", *step["nets"],
            "--plane-layers" if step["operation"] == "planes" else "--layers", *step["layers"]]
    for name in NUMBERS:
        if name in step:
            args += ["--" + name.replace("_", "-"), str(step[name])]
    for name in ("max_iterations", "max_probe_iterations", "same_net_pad_clearance",
                 "routing_clearance_margin", "hole_to_hole_clearance", "board_edge_clearance"):
        if name in step:
            args += ["--" + name.replace("_", "-"), str(step[name])]
    for name in ("fab_tier", "escalation"):
        if name in step:
            args += ["--" + name.replace("_", "-"), str(step[name])]
    if "power_nets" in step:
        args += ["--power-nets", *step["power_nets"]]
    if "power_nets_widths" in step:
        args += ["--power-nets-widths", *(str(v) for v in step["power_nets_widths"])]
    if "gnd_via_net" in step:
        args += ["--gnd-via-net", step["gnd_via_net"]]
    for name in BOOL_OPTIONS:
        if step.get(name):
            args.append("--" + name.replace("_", "-"))
    for name in POLICY_BOOLEANS:
        if name in step:
            args.append("--" + name.replace("_", "-") if step[name] else
                        "--no-" + name.replace("_", "-"))
    return args


def run_process(args: list[str], log: Path, timeout: int, cwd: Path) -> int:
    """Kill the whole process group on timeout (the router may launch KiCad children)."""
    with log.open("w", encoding="utf-8") as stream:
        proc = subprocess.Popen(args, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT,
                                env={k: v for k, v in os.environ.items() if k in {
                                    "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT",
                                    "LANG", "LC_ALL", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
                                    "PYTHONDONTWRITEBYTECODE", "LD_LIBRARY_PATH"}},
                                start_new_session=os.name != "nt")
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name != "nt":
                os.killpg(proc.pid, signal.SIGKILL)
            else:
                proc.kill()
            proc.wait()
            raise TimeoutError(f"process timed out after {timeout}s; see {log}")


def router_help_options(root: Path, operation: str) -> set[str]:
    """Read the pinned parser's options in a credential-free environment."""
    script = root / "py_router" / SCRIPTS[operation]
    try:
        proc = subprocess.run(
            [sys.executable, str(script), "--help"], cwd=root,
            capture_output=True, text=True, timeout=30,
            env={k: v for k, v in os.environ.items() if k in {
                "PATH", "HOME", "TMPDIR", "TEMP", "TMP", "SYSTEMROOT", "LANG", "LC_ALL",
                "XDG_CACHE_HOME", "XDG_CONFIG_HOME", "PYTHONDONTWRITEBYTECODE", "LD_LIBRARY_PATH",
            }},
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"could not inspect pinned {operation} router capabilities: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"pinned {operation} router --help failed ({proc.returncode})")
    return set(re.findall(r"(?<![\w-])(--[a-z][a-z0-9-]*)", proc.stdout + proc.stderr))


def policy_options_for_step(step: Mapping[str, Any]) -> set[str]:
    names = {"max_iterations", "max_probe_iterations", "same_net_pad_clearance",
             "routing_clearance_margin", "hole_to_hole_clearance", "board_edge_clearance",
             "fab_tier", "escalation"}
    names.update(name for name in POLICY_BOOLEANS if name in step)
    return {"--" + name.replace("_", "-") for name in names if name in step}


def metrics_from_log(path: Path) -> dict[str, Any]:
    """Extract optional upstream metrics without turning missing values into zero."""
    if not path.is_file():
        return {"iterations": None, "probe_iterations": None, "relaxations": None, "scope": "unknown"}
    for line in reversed(path.read_text(encoding="utf-8", errors="replace").splitlines()):
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and any(key in value for key in ("iterations", "probe_iterations", "relaxations")):
            return {
                "iterations": value.get("iterations"),
                "probe_iterations": value.get("probe_iterations"),
                "relaxations": value.get("relaxations"),
                "scope": value.get("scope", "whole_job"),
            }
    return {"iterations": None, "probe_iterations": None, "relaxations": None, "scope": "unknown"}


def findings(report: dict) -> list[dict]:
    result = []
    for key in ("violations", "unconnected_items", "schematic_parity"):
        result.extend(with_stable_uuid("violation", v) for v in report.get(key, []))
    result.extend(with_stable_uuid("violation", v) for s in report.get("sheets", [])
                  for v in s.get("violations", []))
    return result


def validate(board: Path, reports: Path) -> dict:
    reports.mkdir()
    checks = {}
    for name, source, args in (
        ("erc", board.with_suffix(".kicad_sch"), ["sch", "erc"]),
        ("drc", board, ["pcb", "drc", "--schematic-parity"]),
    ):
        path = reports / f"{name}.json"
        code = run_process(["kicad-cli", *args, "--format", "json", "--severity-all",
                            "--exit-code-violations", "--output", str(path), str(source)],
                           reports / f"{name}.log", 120, board.parent)
        if code not in (0, 5) or not path.is_file():
            raise RuntimeError(f"{name} execution failed ({code}); see {reports}")
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict) or (name == "erc" and "sheets" not in raw) or (
            name == "drc" and not all(k in raw for k in ("violations", "unconnected_items", "schematic_parity"))
        ):
            raise RuntimeError(f"malformed {name} report")
        entries = findings(raw)
        checks[name] = {"exit_code": code, "count": len(entries),
                        "by_type": dict(Counter(v.get("type", "unknown") for v in entries)),
                        "report": str(path), "findings": entries}
    return checks


def regression(baseline: dict, candidate: dict) -> dict:
    def identities(check):
        return Counter(json.dumps(v, sort_keys=True) for v in check["findings"]
                       if v.get("type") != "unconnected_items")
    added = sum(sum((identities(candidate[k]) - identities(baseline[k])).values())
                for k in ("erc", "drc"))
    before = baseline["drc"]["by_type"].get("unconnected_items", 0)
    after = candidate["drc"]["by_type"].get("unconnected_items", 0)
    return {"new_nonconnectivity_findings": added, "unconnected_before": before,
            "unconnected_after": after, "regressed": added > 0 or after > before}


def copy_project(source: Path, dest: Path) -> None:
    """Copy project context, including hierarchical sheets and project-local libraries."""
    excluded = {".git", ".kicad-automation", ".history", "output", "node_modules"}
    def ignore(directory, names):
        for name in names:
            if (Path(directory) / name).is_symlink():
                raise ValueError(f"project symlink requires explicit packaging: {directory}/{name}")
        return [n for n in names if n in excluded or n.endswith((".lck", ".kicad_prl"))]
    shutil.copytree(source, dest, ignore=ignore)


def restore_contract(baseline: Path, candidate: Path) -> None:
    # Upstream may weaken .kicad_pro floors or edit schematics. Reapply the
    # original electrical/rule contract before every independent KiCad check.
    suffixes = {".kicad_pro", ".kicad_sch", ".kicad_dru"}
    for path in candidate.rglob("*"):
        if path.is_file() and path.suffix in suffixes and not (baseline / path.relative_to(candidate)).exists():
            path.unlink()
    for path in baseline.rglob("*"):
        if path.is_file() and path.suffix in suffixes:
            target = candidate / path.relative_to(baseline)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)


def doctor(root: Path) -> dict:
    actual = (root / "REVISION").read_text().strip()
    if actual != REVISION:
        raise ValueError(f"unsupported KRT revision: {actual}")
    for script in SCRIPTS.values():
        if not (root / "py_router" / script).is_file():
            raise ValueError(f"missing upstream script: {script}")
    return {"backend": "KiCadRoutingTools", "revision": actual,
            "operations": list(SCRIPTS), "source_access": "read_only",
            "applies_to_live_board": False,
            "capabilities": {
                "topology_preview": True,
                "dry_run": True,
                "blocking_object_reports": True,
                "live_ipc_promotion": False,
                "strict_policy_controls": False,
                "policy_capability_probe": True,
                "saved_source_rollback": False,
            }}


def plan_trace(board: dict, request: dict) -> dict:
    """Return a dry-run topology plan; no candidate/source file is changed."""
    return GridRouter(board).plan(RouteRequest.from_mapping(request)).as_dict()


def initialize_libraries() -> None:
    """Seed the disposable CLI configuration from this image's installed libraries."""
    config = Path(os.environ.get("XDG_CONFIG_HOME", str(Path.home() / ".config"))) / "kicad/10.0"
    config.mkdir(parents=True, exist_ok=True)
    for name in ("sym-lib-table", "fp-lib-table"):
        target = config / name
        if not target.exists():
            shutil.copy2(Path("/usr/share/kicad/template") / name, target)


def contract_hashes(directory: Path) -> dict:
    return {str(p.relative_to(directory)): digest(p) for p in sorted(directory.rglob("*"))
            if p.is_file() and p.suffix in {".kicad_pcb", ".kicad_sch", ".kicad_pro", ".kicad_dru"}}


def run_job(plan: dict, workspace: Path, jobs: Path, root: Path) -> dict:
    plan = validate_plan(plan)
    provenance = doctor(root)
    if plan.get("schema_version") == 2:
        for step in plan["steps"]:
            available = router_help_options(root, step["operation"])
            missing = sorted(policy_options_for_step(step) - available)
            if missing:
                raise ValueError(f"pinned {step['operation']} router does not advertise policy options: {missing}")
    board = contained(workspace, plan["project"])
    if board.suffix != ".kicad_pcb":
        raise ValueError("project must name a .kicad_pcb file")
    for suffix in (".kicad_pro", ".kicad_sch", ".kicad_pcb"):
        if not board.with_suffix(suffix).is_file():
            raise ValueError(f"missing project file: {board.with_suffix(suffix)}")
    if any(board.parent.glob("~*.lck")):
        raise ValueError("project is locked; save and close its editor before routing the saved snapshot")
    if jobs.resolve().is_relative_to(board.parent.resolve()):
        raise ValueError("job directory cannot be inside the source project directory")
    jobs.mkdir(parents=True, exist_ok=True)
    job = jobs / (time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:10])
    job.mkdir()
    result = {"job_id": job.name, "status": "running", "backend": provenance,
              "plan": plan, "source_board": str(board), "source_sha256": digest(board),
              "applied": False, "steps": []}
    result["source_contract_sha256"] = contract_hashes(board.parent)
    manifest = job / "result.json"
    def save():
        manifest.write_text(json.dumps(result, indent=2), encoding="utf-8")
    save()
    try:
        baseline_dir = job / "baseline"
        copy_project(board.parent, baseline_dir)
        current = baseline_dir / board.name
        baseline = validate(current, job / "baseline-checks")
        result["baseline"] = baseline
        for index, step in enumerate(plan["steps"], 1):
            input_dir = job / f"input-{index:02d}"
            copy_project(current.parent, input_dir)
            stage_dir = job / f"step-{index:02d}"
            copy_project(current.parent, stage_dir)
            output = stage_dir / board.name
            args = command(root, step, input_dir / board.name, output)
            entry = {"operation": step["operation"], "command": args,
                     "log": str(job / f"step-{index:02d}.log"),
                     "policy": {key: step[key] for key in step if key in POLICY_NUMBERS or
                                key in POLICY_BOOLEANS or key in {"fab_tier", "escalation"}}}
            result["steps"].append(entry)
            save()
            # Remove the copied board so a zero-exit/no-output tool cannot pass.
            output.unlink()
            entry["exit_code"] = run_process(args, Path(entry["log"]), plan["timeout_seconds"], stage_dir)
            entry["metrics"] = metrics_from_log(Path(entry["log"]))
            if entry["exit_code"] != 0 or not output.is_file():
                if entry["exit_code"] == 3:
                    raise RuntimeError(f"routing step {index} rejected by strict fabrication policy; see {entry['log']}")
                raise RuntimeError(f"routing step {index} failed or did not produce a board")
            restore_contract(baseline_dir, stage_dir)
            entry["validation"] = validate(output, job / f"step-{index:02d}-checks")
            entry["comparison"] = regression(baseline, entry["validation"])
            if entry["comparison"]["regressed"]:
                raise RuntimeError(f"routing step {index} introduced validation regressions")
            current = output
            save()
        final = result["steps"][-1]["validation"]
        result["comparison"] = regression(baseline, final)
        result["candidate"] = str(current)
        result["candidate_sha256"] = digest(current)
        result["status"] = "candidate_clean" if all(final[k]["count"] == 0 for k in final) else "needs_review"
        if result["comparison"]["regressed"]:
            result["status"] = "rejected"
    except Exception as exc:
        result.update(status="error", error=str(exc))
    finally:
        result["source_unchanged"] = contract_hashes(board.parent) == result["source_contract_sha256"]
        if not result["source_unchanged"]:
            result.update(status="rejected", error="source changed during routing; candidate is stale")
        save()
    return result


def serve(workspace: Path, jobs: Path, root: Path) -> None:
    from mcp.server.fastmcp import FastMCP
    server = FastMCP("kicad-routing-tools")

    @server.tool()
    def routing_tools_info() -> dict:
        """Inspect the pinned isolated routing backend; never changes the live board."""
        return doctor(root)

    @server.tool()
    def routing_run_candidate(plan: RoutingPlan) -> dict:
        """Run a route/diff/planes plan on a saved project copy and return ERC/DRC evidence.

        Plan: {project: relative .kicad_pcb path, timeout_seconds: 10..3600,
        steps: [{operation: route|diff|planes, nets: [patterns], layers: [F.Cu,...],
        optional track_width, clearance, via_size, via_drill, grid_step in mm}]}.
        Source must be saved and unlocked. Output stays in /jobs; never applied to live IPC.
        """
        return run_job(plan, workspace, jobs, root)

    @server.tool()
    def routing_plan_trace(board: dict, request: dict) -> dict:
        """Preview an obstacle-aware trace with blockers and no board mutation."""
        return plan_trace(board, request)

    @server.tool()
    def routing_job_result(job_id: str) -> dict:
        """Read a persisted routing job result after reconnecting."""
        if not re.fullmatch(r"[0-9]{8}-[0-9]{6}-[a-f0-9]{10}", job_id):
            raise ValueError("invalid job id")
        return json.loads((contained(jobs, job_id) / "result.json").read_text())
    server.run(transport="stdio")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("doctor", "run", "mcp"))
    parser.add_argument("plan", nargs="?")
    args = parser.parse_args()
    root = Path(os.environ.get("KRT_ROOT", "/opt/KiCadRoutingTools"))
    workspace = Path(os.environ.get("KRT_WORKSPACE", "/workspace"))
    jobs = Path(os.environ.get("KRT_JOBS", "/jobs"))
    try:
        initialize_libraries()
        if args.command == "mcp":
            serve(workspace, jobs, root)
            return 0
        result = doctor(root) if args.command == "doctor" else run_job(
            json.loads(contained(workspace, args.plan).read_text(encoding="utf-8-sig")), workspace, jobs, root)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status", "candidate_clean") == "candidate_clean" else 1
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
