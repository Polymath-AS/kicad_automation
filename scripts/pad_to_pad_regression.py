#!/usr/bin/env python3
"""Pinned KiCad 10 pad-to-pad MCP regression.

The script is intentionally client-only.  It resolves two named pads through
the live tool surface, invokes the upstream helper using its advertised schema,
saves, reloads through a fresh inspection call and validates the resulting board
with the repository's KiCad CLI wrapper.  It refuses to claim success if the
experimental helper is not exposed by the selected runtime.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import re
from typing import Any, Mapping

try:
    from kicad_mcp_client import DEFAULT_TOKEN, DEFAULT_URL, McpClientError, request
except ImportError:  # repository-root import
    from scripts.kicad_mcp_client import DEFAULT_TOKEN, DEFAULT_URL, McpClientError, request


def _tool_result(response: Mapping[str, Any]) -> Any:
    result = response.get("result", {})
    if result.get("isError"):
        raise McpClientError(json.dumps(result, sort_keys=True))
    structured = result.get("structuredContent")
    if structured is not None:
        return structured
    for block in result.get("content", []) or []:
        if block.get("type") == "text":
            try:
                return json.loads(block["text"])
            except (TypeError, json.JSONDecodeError):
                continue
    return result


def call(url: str, token: str, name: str, arguments: Mapping[str, Any]) -> Any:
    return _tool_result(request(url, token, "tools/call", {"name": name, "arguments": dict(arguments)}, 120))


def _walk(value: Any):
    if isinstance(value, Mapping):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def resolve_pad(pads: Any, reference: str, number: str) -> dict[str, Any]:
    for item in _walk(pads):
        if str(item.get("reference", item.get("footprint_reference", ""))) != reference:
            continue
        if str(item.get("number", item.get("pad_number", ""))) == str(number):
            return dict(item)
    text = pads.get("result") if isinstance(pads, Mapping) else pads
    if isinstance(text, str):
        pattern = re.compile(
            rf"\b{re.escape(reference)}:{re.escape(str(number))}\s+net=(?P<net>[^\s]+)\s+@\s+\((?P<x>[-+0-9.]+),\s*(?P<y>[-+0-9.]+)\)"
        )
        match = pattern.search(text)
        if match:
            return {"reference": reference, "number": str(number), "net": match.group("net"),
                    "position": {"x_mm": float(match.group("x")), "y_mm": float(match.group("y"))}}
    raise ValueError(f"named pad {reference}.{number} was not returned by pcb_get_pads")


def route_arguments(schema: Mapping[str, Any], start: tuple[str, str], end: tuple[str, str]) -> dict[str, Any]:
    """Populate the known schema variants without relying on hidden fields."""
    props = schema.get("inputSchema", schema).get("properties", {})
    required = schema.get("inputSchema", schema).get("required", [])
    if not props:
        raise ValueError("route_from_pad_to_pad schema has no properties")
    start_ref, start_pad = start
    end_ref, end_pad = end
    payload: dict[str, Any] = {}
    aliases = {
        "start_reference": start_ref, "from_reference": start_ref, "source_reference": start_ref,
        "ref1": start_ref, "start_pad": start_pad, "from_pad_number": start_pad, "source_pad": start_pad,
        "pad1": start_pad, "end_reference": end_ref, "to_reference": end_ref, "target_reference": end_ref,
        "ref2": end_ref, "end_pad": end_pad, "to_pad_number": end_pad, "target_pad": end_pad,
        "pad2": end_pad,
    }
    for name in required:
        if name in aliases:
            payload[name] = aliases[name]
        elif name in {"from_pad", "source_pad_info", "start"}:
            payload[name] = {"reference": start_ref, "pad": start_pad, "number": start_pad}
        elif name in {"to_pad", "target_pad_info", "end"}:
            payload[name] = {"reference": end_ref, "pad": end_pad, "number": end_pad}
        else:
            raise ValueError(f"unsupported required route argument: {name}")
    # Include optional aliases only when explicitly present in the schema.
    for name, value in aliases.items():
        if name in props:
            payload[name] = value
    if "from_pad" in props:
        payload["from_pad"] = {"reference": start_ref, "pad": start_pad, "number": start_pad}
    if "to_pad" in props:
        payload["to_pad"] = {"reference": end_ref, "pad": end_pad, "number": end_pad}
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("start_reference")
    parser.add_argument("start_pad")
    parser.add_argument("end_reference")
    parser.add_argument("end_pad")
    parser.add_argument("--url", default=os.environ.get("KICAD_MCP_URL", DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("KICAD_MCP_AUTH_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--project", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        catalog = request(args.url, args.token, "tools/list", {}, 120).get("result", {}).get("tools", [])
        tool = next((item for item in catalog if item.get("name") == "route_from_pad_to_pad"), None)
        if tool is None:
            raise McpClientError("route_from_pad_to_pad is unavailable; run the M4 service in its supported experimental write mode")
        pads = call(args.url, args.token, "pcb_get_pads", {})
        start = resolve_pad(pads, args.start_reference, args.start_pad)
        end = resolve_pad(pads, args.end_reference, args.end_pad)
        before_tracks = call(args.url, args.token, "pcb_get_tracks", {})
        payload = route_arguments(tool, (args.start_reference, args.start_pad), (args.end_reference, args.end_pad))
        call(args.url, args.token, "route_from_pad_to_pad", payload)
        call(args.url, args.token, "pcb_save", {})
        tracks = call(args.url, args.token, "pcb_get_tracks", {})
        readback = call(args.url, args.token, "pcb_get_board_summary", {})
        track_text = json.dumps(tracks)
        def records(value: Any):
            for item in _walk(value):
                if "net" in item or "net_name" in item:
                    yield item
        before_count = sum(1 for _ in records(before_tracks))
        after_records = list(records(tracks))
        before_text = json.dumps(before_tracks)
        after_text = json.dumps(tracks)
        before_totals = [int(value) for value in re.findall(r"tracks?\s*\((\d+)\s+total", before_text, re.I)]
        after_totals = [int(value) for value in re.findall(r"tracks?\s*\((\d+)\s+total", after_text, re.I)]
        before_count = max([before_count, *before_totals], default=0)
        after_count = max([len(after_records), *after_totals], default=0)
        if after_count <= before_count:
            raise RuntimeError("route helper returned without creating a new track")
        start_net = start.get("net_name", start.get("net"))
        end_net = end.get("net_name", end.get("net"))
        if start_net is not None and end_net is not None and str(start_net) != str(end_net):
            raise RuntimeError(f"named pads do not share a net: {start_net!r} != {end_net!r}")
        if start_net is not None and after_records and not any(str(item.get("net_name", item.get("net"))) == str(start_net)
                                                               for item in after_records):
            raise RuntimeError("created track is assigned to the wrong net")
        if start_net is not None and not after_records and f"net={start_net}" not in after_text:
            raise RuntimeError("created track is assigned to the wrong net")
        validate = subprocess.run(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
             "tools/kicad-docker.ps1", "validate", str(args.project), "--drc"],
            check=False, capture_output=True, text=True,
        )
        if validate.returncode not in (0, 1):
            raise RuntimeError(f"KiCad 10 DRC invocation failed: {validate.stderr[-1000:]}")
        try:
            validation = json.loads(validate.stdout)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"validator did not return JSON: {exc}") from exc
        drc = next((item for item in validation.get("results", []) if item.get("name") == "drc"), None)
        if not drc or drc.get("status") == "error":
            raise RuntimeError("KiCad DRC did not produce a result")
        by_type = (drc.get("summary") or {}).get("by_type", {})
        if by_type.get("unconnected_items", 0):
            raise RuntimeError(f"pad-to-pad route remains unconnected: {by_type}")
        report = {"status": "pass", "start": start, "end": end, "track": tracks,
                  "readback": readback,
                  "validation_exit_code": validate.returncode,
                  "validation_status": validation.get("status"),
                  "drc_summary": drc.get("summary")}
        print(json.dumps(report, indent=2))
        return 0
    except (McpClientError, OSError, ValueError, RuntimeError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
