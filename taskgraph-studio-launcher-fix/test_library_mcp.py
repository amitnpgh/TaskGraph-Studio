import asyncio
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock
from library import Library
from mcp_client import MCPClient, ToolBroker, fingerprint, NoRedirect
from engine import Contract, OpenAIAdapter, Orchestrator, MockAdapter, RESULT
from example_mcp_server import TOOL


class LibraryTests(unittest.TestCase):
    def test_selected_knowledge_only_and_no_automatic_url_fetch(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            a = library.put("knowledge", {"name": "A", "text": "First source", "source": "https://example.com"})
            library.put("knowledge", {"name": "B", "text": "Unselected source", "source": ""})
            reopened = Library(directory)
            self.assertIn("First source", reopened.context({a["id"]}))
            self.assertNotIn("Unselected", reopened.context({a["id"]}))
            self.assertEqual(reopened.context(set()), "")

    @unittest.skipUnless(os.name == "nt", "Windows credential protection")
    def test_credentials_are_encrypted_separate_and_clearable(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            row = library.put("connections", {"name": "Test"})
            try:
                library.secret(row["id"], "secret-example-token")
            except ValueError as exc:
                if "error 2" in str(exc):
                    self.skipTest("Restricted test account cannot access the Windows DPAPI profile")
                raise
            self.assertEqual(Library(directory).secret(row["id"]), "secret-example-token")
            for file in Path(directory).iterdir():
                self.assertNotIn("secret-example-token", file.read_text())
            library.clear_secret(row["id"])
            self.assertEqual(library.secret(row["id"]), "")

    def test_session_credentials_never_persist(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            row = library.put("connections", {"name": "Test"})
            library.secret(row["id"], "session-token", persist=False)
            self.assertEqual(library.secret(row["id"]), "session-token")
            self.assertEqual(Library(directory).secret(row["id"]), "")
            self.assertNotIn("session-token", library.path.read_text())


class MCPTests(unittest.TestCase):
    def test_real_stdio_discovery_and_call(self):
        client = MCPClient({"transport": "stdio", "command": sys.executable,
                            "args": [str(Path(__file__).with_name("example_mcp_server.py"))]})
        try:
            client.connect()
            self.assertEqual(client.tools()[0]["name"], "search_notes")
            result = client.rpc("tools/call", {"name": "search_notes", "arguments": {"query": "regional"}})
            self.assertIn("Regional-bank", json.dumps(result))
        finally:
            client.close()
        self.assertIsNotNone(client.process.poll())

    def test_http_session_headers_and_json(self):
        requests = []
        def open_fake(request, timeout):
            requests.append(request)
            body = json.loads(request.data)
            result = {"protocolVersion": "2025-11-25"} if body["method"] == "initialize" else {"tools": [TOOL]}
            response = io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": body.get("id"), "result": result}).encode())
            response.headers = {"Content-Type": "application/json", "Mcp-Session-Id": "session-test"}
            return response
        opener = MagicMock(); opener.open.side_effect = open_fake
        with patch("urllib.request.build_opener", return_value=opener):
            client = MCPClient({"transport": "http", "url": "https://example.com/mcp"}, "secret")
            client.connect(); self.assertEqual(len(client.tools()), 1)
        self.assertEqual(dict(requests[-1].header_items())["Mcp-session-id"], "session-test")
        self.assertEqual(dict(requests[-1].header_items())["Authorization"], "Bearer secret")

    def test_sse_parsing(self):
        response = io.BytesIO(b'event: message\ndata:\n\ndata: {"jsonrpc":"2.0","id":1,"result":{"tools":[]}}\n\n')
        response.headers = {"Content-Type": "text/event-stream"}
        opener = MagicMock(); opener.open.return_value = response
        with patch("urllib.request.build_opener", return_value=opener):
            client = MCPClient({"transport": "http", "url": "https://example.com/mcp"})
            self.assertEqual(client.rpc("tools/list", {}), {"tools": []})

    def test_insecure_endpoint_and_redirect_rejected(self):
        with self.assertRaises(ValueError):
            MCPClient({"transport": "http", "url": "http://example.com/mcp"}).connect()
        with self.assertRaises(ValueError):
            NoRedirect().redirect_request(None, None, None, None, None, None)


class BrokerTests(unittest.IsolatedAsyncioTestCase):
    def broker(self, enabled=True, automatic=False):
        client = MagicMock()
        client.rpc.return_value = {"content": [{"type": "text", "text": "source data"}]}
        audit = MagicMock(return_value="tool-artifact:tool_1")
        async def approve(record): return True
        broker = ToolBroker(None, [], approve, audit)
        broker.routes["allowed"] = (client, {"name": "Test", "description": "Test connection"}, TOOL, {"enabled": enabled, "automatic": automatic})
        return broker, client, audit

    async def test_approval_result_provenance_and_budget(self):
        broker, client, audit = self.broker()
        result = await broker.invoke("allowed", {"query": "test"}, "root")
        self.assertEqual(result["source"], "tool-artifact:tool_1")
        client.rpc.assert_called_once()
        broker.max_calls = 1
        with self.assertRaises(ValueError): await broker.invoke("allowed", {}, "root")

    async def test_denied_calls_never_execute_or_reprompt(self):
        broker, client, _ = self.broker()
        approvals = []
        async def deny(record): approvals.append(record); return False
        broker.approve = deny
        await broker.invoke("allowed", {}, "root")
        await broker.invoke("allowed", {}, "root")
        client.rpc.assert_not_called()
        self.assertEqual(len(approvals), 1)
        with self.assertRaises(ValueError): await broker.invoke("unselected", {}, "root")

    async def test_disabled_tool_and_cancelled_approval_never_execute(self):
        broker, client, _ = self.broker(enabled=False)
        with self.assertRaisesRegex(ValueError, "disabled"):
            await broker.invoke("allowed", {}, "root")
        client.rpc.assert_not_called()
        broker, client, _ = self.broker()
        entered = asyncio.Event()
        async def wait(record):
            entered.set()
            await asyncio.Future()
        broker.approve = wait
        pending = asyncio.create_task(broker.invoke("allowed", {}, "root"))
        await entered.wait()
        pending.cancel()
        with self.assertRaises(asyncio.CancelledError): await pending
        client.rpc.assert_not_called()

    async def test_credentials_redacted_from_audit_and_model_result(self):
        broker, client, audit = self.broker(automatic=True)
        broker.secrets = ["secret-test"]
        client.rpc.return_value = {"content": [{"type": "text", "text": "secret-test"}]}
        result = await broker.invoke("allowed", {}, "root")
        self.assertNotIn("secret-test", json.dumps(result))
        self.assertNotIn("secret-test", str(audit.call_args_list))

    async def test_discovery_enforces_selection_and_changed_schema(self):
        with tempfile.TemporaryDirectory() as directory:
            library = Library(directory)
            row = library.put("connections", {"name": "Test", "description": "Sample", "transport": "stdio",
                "policies": {"search_notes": {"enabled": True, "fingerprint": fingerprint(TOOL)}}})
            async def approve(record): return True
            fake = MagicMock(); fake.tools.return_value = [TOOL]
            with patch("mcp_client.MCPClient", return_value=fake):
                broker = ToolBroker(library, [], approve, MagicMock())
                await broker.connect()
                self.assertEqual(broker.routes, {})
                broker = ToolBroker(library, [row["id"]], approve, MagicMock())
                await broker.connect(); self.assertEqual(len(broker.routes), 1)
                fake.tools.return_value = [{**TOOL, "description": "Changed"}]
                with self.assertRaisesRegex(ValueError, "changed"):
                    await ToolBroker(library, [row["id"]], approve, MagicMock()).connect()

    async def test_openai_round_trip_executes_tool_then_structured_answer(self):
        payload = {"task": {"id": "root"}, "contract": {}}
        final = {"answer": "Used tool"}
        replies = [
            {"status": "completed", "output": [{"type": "function_call", "name": "allowed", "arguments": '{"query":"test"}', "call_id": "c1"}]},
            {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(final)}]}]}]
        bodies = []
        def request(req, timeout):
            bodies.append(json.loads(req.data))
            return io.BytesIO(json.dumps(replies.pop(0)).encode())
        adapter = OpenAIAdapter("fake-key")
        broker, client, _ = self.broker(automatic=True)
        adapter.tool_broker = broker
        adapter.on_extra_request = MagicMock()
        with patch("urllib.request.urlopen", side_effect=request):
            self.assertEqual(await adapter.complete("general", payload, RESULT, "test"), final)
        client.rpc.assert_called_once()
        self.assertEqual(bodies[1]["input"][-1]["type"], "function_call_output")
        self.assertIn("tool-artifact:tool_1", bodies[1]["input"][-1]["output"])
        adapter.on_extra_request.assert_called_once()


if __name__ == "__main__": unittest.main()
