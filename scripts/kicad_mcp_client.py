#!/usr/bin/env python3
"""Small, dependency-free client for the repository's KiCad MCP endpoint."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_URL = "http://127.0.0.1:3334/mcp"
DEFAULT_TOKEN = "kicad-automation-local-dev-token-change-me-2026"
PROTOCOL_VERSION = "2025-11-25"


class McpClientError(RuntimeError):
    """A transport, protocol, or MCP tool failure."""


def parse_json_argument(value: str) -> Any:
    """Parse inline JSON or JSON loaded from an @-prefixed file path."""
    if value.startswith("@"):
        value = Path(value[1:]).read_text(encoding="utf-8")
    try:
        return json.loads(value)
    except json.JSONDecodeError as exc:
        raise McpClientError(f"invalid JSON: {exc}") from exc


def decode_response(body: bytes, content_type: str) -> dict[str, Any]:
    """Decode an MCP JSON or Streamable HTTP event-stream response."""
    text = body.decode("utf-8")
    if "text/event-stream" not in content_type.lower():
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise McpClientError(f"server returned invalid JSON: {exc}") from exc
        if not isinstance(value, dict):
            raise McpClientError("server returned a non-object JSON-RPC response")
        return value

    events: list[str] = []
    current: list[str] = []
    for line in text.splitlines():
        if not line:
            if current:
                events.append("\n".join(current))
                current = []
            continue
        if line.startswith("data:"):
            current.append(line[5:].lstrip())
    if current:
        events.append("\n".join(current))

    for event in reversed(events):
        try:
            value = json.loads(event)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            return value
    raise McpClientError("server returned an event stream without a JSON-RPC object")


def request(
    url: str,
    token: str,
    method: str,
    params: dict[str, Any] | None,
    timeout: float,
    request_id: int = 1,
) -> dict[str, Any]:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        payload["params"] = params
    encoded = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    headers = {
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    http_request = urllib.request.Request(url, data=encoded, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(http_request, timeout=timeout) as response:
            result = decode_response(response.read(), response.headers.get("Content-Type", ""))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise McpClientError(f"HTTP {exc.code} from MCP endpoint: {detail}") from exc
    except urllib.error.URLError as exc:
        raise McpClientError(f"cannot reach MCP endpoint {url}: {exc.reason}") from exc

    if "error" in result:
        raise McpClientError(f"JSON-RPC error: {json.dumps(result['error'], sort_keys=True)}")
    return result


def initialize_params() -> dict[str, Any]:
    return {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "kicad-automation-cli", "version": "1.0.0"},
    }


def result_is_error(response: dict[str, Any]) -> bool:
    result = response.get("result")
    return isinstance(result, dict) and result.get("isError") is True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=os.environ.get("KICAD_MCP_URL", DEFAULT_URL))
    parser.add_argument("--token", default=os.environ.get("KICAD_MCP_AUTH_TOKEN", DEFAULT_TOKEN))
    parser.add_argument("--timeout", type=float, default=120.0, help="request timeout in seconds")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("initialize", help="negotiate MCP protocol capabilities")
    commands.add_parser("list", help="list tools exposed by the active server profile")

    schema = commands.add_parser("schema", help="show one tool's discovered schema")
    schema.add_argument("tool")

    call = commands.add_parser("call", help="call an MCP tool")
    call.add_argument("tool")
    call.add_argument("--arguments", default="{}", help="inline JSON or @path/to/arguments.json")

    raw = commands.add_parser("raw", help="send an arbitrary JSON-RPC method")
    raw.add_argument("method")
    raw.add_argument("--params", default="{}", help="inline JSON or @path/to/params.json")

    wait = commands.add_parser("wait", help="wait until the MCP endpoint initializes")
    wait.add_argument("--wait-timeout", type=float, default=120.0)
    wait.add_argument("--interval", type=float, default=1.0)
    return parser


def invoke(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "initialize":
        return request(args.url, args.token, "initialize", initialize_params(), args.timeout)
    if args.command == "list":
        return request(args.url, args.token, "tools/list", {}, args.timeout)
    if args.command == "schema":
        response = request(args.url, args.token, "tools/list", {}, args.timeout)
        tools = response.get("result", {}).get("tools", [])
        match = next((tool for tool in tools if tool.get("name") == args.tool), None)
        if match is None:
            raise McpClientError(f"tool is not exposed by the active profile: {args.tool}")
        return {"jsonrpc": "2.0", "id": response.get("id"), "result": match}
    if args.command == "call":
        arguments = parse_json_argument(args.arguments)
        if not isinstance(arguments, dict):
            raise McpClientError("tool arguments must be a JSON object")
        return request(
            args.url,
            args.token,
            "tools/call",
            {"name": args.tool, "arguments": arguments},
            args.timeout,
        )
    if args.command == "raw":
        params = parse_json_argument(args.params)
        if not isinstance(params, dict):
            raise McpClientError("method params must be a JSON object")
        return request(args.url, args.token, args.method, params, args.timeout)
    if args.command == "wait":
        deadline = time.monotonic() + args.wait_timeout
        last_error = "endpoint did not respond"
        while time.monotonic() < deadline:
            try:
                return request(args.url, args.token, "initialize", initialize_params(), args.timeout)
            except McpClientError as exc:
                last_error = str(exc)
                time.sleep(args.interval)
        raise McpClientError(f"MCP endpoint was not ready after {args.wait_timeout:g}s: {last_error}")
    raise McpClientError(f"unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    try:
        response = invoke(build_parser().parse_args(argv))
        print(json.dumps(response, indent=2, sort_keys=True))
        return 1 if result_is_error(response) else 0
    except (McpClientError, OSError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
