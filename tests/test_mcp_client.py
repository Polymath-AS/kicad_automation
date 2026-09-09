import importlib.util
import json
import sys
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


mcp = load_module("kicad_mcp_client", "scripts/kicad_mcp_client.py")


class TestHandler(BaseHTTPRequestHandler):
    response_type = "application/json"
    response_body = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
    received = None

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        type(self).received = {
            "path": self.path,
            "authorization": self.headers.get("Authorization"),
            "accept": self.headers.get("Accept"),
            "body": json.loads(self.rfile.read(length)),
        }
        encoded = json.dumps(type(self).response_body).encode("utf-8")
        if self.response_type == "text/event-stream":
            encoded = b"event: message\n" + b"data: " + encoded + b"\n\n"
        self.send_response(200)
        self.send_header("Content-Type", self.response_type)
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, _format, *_args):
        pass


class McpClientTests(unittest.TestCase):
    def setUp(self):
        TestHandler.response_type = "application/json"
        TestHandler.response_body = {"jsonrpc": "2.0", "id": 1, "result": {"ok": True}}
        TestHandler.received = None
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), TestHandler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/mcp"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def test_tool_call_uses_mcp_headers_and_shape(self):
        response = mcp.request(
            self.url,
            "test-token",
            "tools/call",
            {"name": "pcb_save", "arguments": {}},
            2,
        )
        self.assertTrue(response["result"]["ok"])
        self.assertEqual(TestHandler.received["path"], "/mcp")
        self.assertEqual(TestHandler.received["authorization"], "Bearer test-token")
        self.assertIn("text/event-stream", TestHandler.received["accept"])
        self.assertEqual(TestHandler.received["body"]["method"], "tools/call")
        self.assertEqual(TestHandler.received["body"]["params"]["name"], "pcb_save")

    def test_streamable_http_event_is_decoded(self):
        TestHandler.response_type = "text/event-stream"
        response = mcp.request(self.url, "", "tools/list", {}, 2)
        self.assertTrue(response["result"]["ok"])
        self.assertIsNone(TestHandler.received["authorization"])

    def test_json_rpc_error_is_a_client_error(self):
        TestHandler.response_body = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32601, "message": "missing"},
        }
        with self.assertRaisesRegex(mcp.McpClientError, "JSON-RPC error"):
            mcp.request(self.url, "test-token", "missing", {}, 2)

    def test_bare_socket_error_is_normalized_for_wait_retries(self):
        with mock.patch.object(mcp.urllib.request, "urlopen", side_effect=ConnectionResetError("reset")):
            with self.assertRaisesRegex(mcp.McpClientError, "MCP connection failed"):
                mcp.request(self.url, "test-token", "initialize", {}, 2)

    def test_schema_fails_clearly_when_profile_hides_tool(self):
        TestHandler.response_body = {"jsonrpc": "2.0", "id": 1, "result": {"tools": []}}
        args = mcp.build_parser().parse_args(
            ["--url", self.url, "--token", "test-token", "schema", "sch_build_circuit"]
        )
        with self.assertRaisesRegex(mcp.McpClientError, "active profile"):
            mcp.invoke(args)

    def test_parse_json_argument_rejects_invalid_json(self):
        with self.assertRaisesRegex(mcp.McpClientError, "invalid JSON"):
            mcp.parse_json_argument("not-json")


if __name__ == "__main__":
    unittest.main()
