"""Summarize a Codex JSONL rollout without loading transcript bodies into a model.

Counts canonical usage records once per response_id; mirrored token_count events
are a separate reconciliation source. Does not inspect encrypted reasoning.
"""
import argparse
import collections
import hashlib
import json
from pathlib import Path


def analyze(source, phase_spec=None):
    rows = []
    with source.open(encoding="utf-8") as stream:
        for line, value in enumerate(stream, 1):
            try:
                rows.append((line, json.loads(value)))
            except json.JSONDecodeError as error:
                raise ValueError("Invalid JSON at line %s: %s" % (line, error)) from error
    phases = phase_spec or [{"start": "", "name": "whole-session"}]
    if phases != sorted(phases, key=lambda p: p["start"]):
        raise ValueError("Phase starts must be sorted ISO UTC timestamps")
    def phase(timestamp):
        return next((p["name"] for p in reversed(phases) if timestamp >= p["start"]), "before-first-phase")
    totals = collections.Counter()
    grouped = collections.defaultdict(collections.Counter)
    seen_usage, seen_items, calls = {}, set(), {}
    usage_rows, commands, messages, compactions = [], [], [], []
    item_counts, tools = collections.Counter(), collections.Counter()
    output_sizes, last_mirror, last_thread = [], None, None
    duplicate_usage = 0
    for line, row in rows:
        payload = row.get("payload", {})
        timestamp = row.get("timestamp", "")
        bucket = phase(timestamp)
        if row["type"] == "token_usage_record":
            key = payload.get("response_id")
            if not key:
                raise ValueError("Usage record missing response_id at line %s" % line)
            if key in seen_usage:
                if seen_usage[key] != payload["usage"]:
                    raise ValueError("Conflicting usage for response_id %s" % key)
                duplicate_usage += 1
                continue
            seen_usage[key] = payload["usage"]
            usage = payload["usage"]
            totals.update(usage)
            grouped[bucket].update(usage)
            grouped[bucket]["responses"] += 1
            usage_rows.append(dict(line=line, timestamp=timestamp, phase=bucket, response_id=key, **usage))
            last_thread = payload.get("thread_token_usage")
        if row["type"] == "event_msg" and payload.get("type") == "token_count":
            info = payload.get("info") or {}
            if info.get("total_token_usage"):
                last_mirror = {"line": line, "usage": info["total_token_usage"]}
        if row["type"] == "compacted":
            info = {"line": line, "timestamp": timestamp}
            if usage_rows and usage_rows[-1]["line"] == line - 1:
                info["immediately_preceding_usage"] = usage_rows[-1]
            compactions.append(info)
        if row["type"] == "response_item":
            kind = payload.get("type")
            if kind in ("function_call", "custom_tool_call"):
                name = payload.get("name", "unknown")
                tools[name] += 1
                calls[payload.get("call_id")] = name
            if kind in ("function_call_output", "custom_tool_call_output"):
                output = payload.get("output", "")
                if isinstance(output, list):
                    output = "\n".join(c.get("text", "") for c in output if isinstance(c, dict))
                elif not isinstance(output, str):
                    output = json.dumps(output)
                output_sizes.append({"line": line, "timestamp": timestamp, "phase": bucket,
                                     "tool": calls.get(payload.get("call_id"), "unknown"),
                                     "text_chars": len(output), "truncated_marker": "truncat" in output.lower()})
        if row["type"] != "event_msg" or payload.get("type") != "item_completed":
            continue
        item = payload.get("item", {})
        key = item.get("id", "line-%s" % line)
        if key in seen_items:
            continue
        seen_items.add(key)
        kind = item.get("type", "unknown")
        item_counts[kind] += 1
        if kind == "CommandExecution":
            command = item.get("command", [])
            command = command[-1] if isinstance(command, list) and command else str(command)
            output = item.get("aggregated_output") or item.get("stdout", "")
            commands.append({"line": line, "timestamp": timestamp, "phase": bucket,
                             "command": command, "exit_code": item.get("exit_code"),
                             "output_chars": len(output), "output_sha256": hashlib.sha256(output.encode()).hexdigest()})
            grouped[bucket]["commands"] += 1
            if item.get("exit_code") not in (None, 0):
                grouped[bucket]["nonzero_commands"] += 1
        if kind in ("AgentMessage", "UserMessage"):
            text = "\n".join(c.get("text", "") for c in item.get("content", []))
            messages.append({"line": line, "timestamp": timestamp, "kind": kind, "text": text})
    if not usage_rows:
        raise ValueError("No token_usage_record entries; cannot establish canonical usage")
    totals["uncached_input_tokens"] = totals["input_tokens"] - totals["cached_input_tokens"]
    totals["non_reasoning_output_tokens"] = totals["output_tokens"] - totals["reasoning_output_tokens"]
    for value in grouped.values():
        value["uncached_input_tokens"] = value["input_tokens"] - value["cached_input_tokens"]
    fingerprints = collections.Counter(c["output_sha256"] for c in commands if c["output_chars"] > 100)
    summary = {
        "source": source.name, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_lines": len(rows), "start": rows[0][1]["timestamp"], "end": rows[-1][1]["timestamp"],
        "usage_responses": len(usage_rows), "duplicate_usage_records_skipped": duplicate_usage,
        "totals": dict(totals), "phases": dict(grouped), "phase_definitions": phases,
        "last_thread_usage": last_thread,
        "sum_matches_last_thread": bool(last_thread) and all(totals[k] == v for k, v in last_thread.items()),
        "last_token_count_event": last_mirror,
        "canonical_minus_event": {k: totals[k] - v for k, v in (last_mirror or {}).get("usage", {}).items()},
        "item_counts": dict(item_counts), "top_level_tool_calls": dict(tools), "compactions": compactions,
        "tool_output_text_chars": sum(o["text_chars"] for o in output_sizes),
        "tool_outputs_with_truncation_marker": sum(o["truncated_marker"] for o in output_sizes),
        "largest_tool_outputs": sorted(output_sizes, key=lambda o: o["text_chars"], reverse=True)[:12],
        "repeated_command_outputs_over_100_chars": sum(n - 1 for n in fingerprints.values() if n > 1),
        "nonzero_commands": sum(c["exit_code"] not in (None, 0) for c in commands),
        "method": "Usage assigned by timestamp to editorial phases, not exact causal tool attribution. Output sizes are characters, not token estimates. No encrypted content decoded."
    }
    return summary, usage_rows, commands, messages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("session", type=Path)
    parser.add_argument("--phases", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    phase_spec = json.loads(args.phases.read_text(encoding="utf-8")) if args.phases else None
    summary, usage, commands, messages = analyze(args.session, phase_spec)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    for name, values in [("usage", usage), ("commands", commands), ("messages", messages)]:
        (args.out / (name + ".jsonl")).write_text("".join(json.dumps(v, ensure_ascii=True) + "\n" for v in values), encoding="utf-8")
    print(json.dumps({"responses": summary["usage_responses"], "totals": summary["totals"], "reconciled": summary["sum_matches_last_thread"], "output": str(args.out)}, indent=2))


if __name__ == "__main__":
    main()
