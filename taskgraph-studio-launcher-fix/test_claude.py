import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock
from claude_adapter import ClaudeAdapter
from engine import Contract, MockAdapter, Orchestrator, RESULT
from desktop import Studio


class ClaudeTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_format_and_authentication(self):
        captured = []
        def request(req, timeout):
            captured.append(req)
            return io.BytesIO(json.dumps({"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"answer":"test"}'}]}).encode())
        with patch("urllib.request.urlopen", side_effect=request):
            result = await ClaudeAdapter("anthropic-test-key").complete("planner", {"task": {"id": "root"}}, RESULT, "claude-test")
        self.assertEqual(result, {"answer": "test"})
        req = captured[0]
        self.assertEqual(req.full_url, "https://api.anthropic.com/v1/messages")
        self.assertEqual(req.get_header("X-api-key"), "anthropic-test-key")
        body = json.loads(req.data)
        self.assertEqual(body["model"], "claude-test")
        self.assertEqual(body["output_config"]["format"]["schema"], RESULT)
        self.assertNotIn("anthropic-test-key", req.data.decode())
        self.assertNotIn("tools", body)

    async def test_mcp_round_trip_and_denial(self):
        adapter = ClaudeAdapter("test-key")
        broker = MagicMock()
        broker.routes = {"search": True}
        broker.definitions.return_value = [{"name": "search", "description": "Search", "parameters": {"type": "object"}}]
        broker.invoke = AsyncMock(return_value={"isError": True, "content": [{"type": "text", "text": "User denied this call"}]})
        adapter.tool_broker = broker
        adapter.on_extra_request = MagicMock()
        bodies = []
        replies = [
            {"stop_reason": "tool_use", "content": [{"type": "tool_use", "id": "tool1", "name": "search", "input": {"query": "bank"}}]},
            {"stop_reason": "end_turn", "content": [{"type": "text", "text": '{"answer":"Could not retrieve data"}'}]}]
        def request(body):
            bodies.append(json.loads(json.dumps(body)))
            return replies.pop(0)
        adapter.request = request
        result = await adapter.complete("research", {"task": {"id": "root"}}, RESULT, "claude-test")
        self.assertIn("Could not", result["answer"])
        broker.invoke.assert_awaited_once_with("search", {"query": "bank"}, "root")
        tool_result = bodies[1]["messages"][-1]["content"][0]
        self.assertEqual(tool_result["tool_use_id"], "tool1")
        self.assertTrue(tool_result["is_error"])
        adapter.on_extra_request.assert_called_once()

    async def test_truncation_refusal_and_auth_errors(self):
        adapter = ClaudeAdapter("test-key")
        for reason in ("max_tokens", "refusal", "pause_turn"):
            adapter.request = lambda body, reason=reason: {"stop_reason": reason, "content": []}
            with self.assertRaises(ValueError):
                await adapter.complete("general", {"task": {"id": "root"}}, RESULT, "claude-test")
        adapter = ClaudeAdapter("test-key")
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError("https://api.anthropic.com", 401, "bad", {}, None)):
            with self.assertRaisesRegex(RuntimeError, "API key"):
                await adapter.complete("general", {}, RESULT, "claude-test")

    async def test_complete_orchestration_with_claude_transport(self):
        adapter = ClaudeAdapter("test-key")
        from engine import PROMPTS
        async def fake_complete(role, payload, schema, model):
            value = await MockAdapter().complete(role, payload, schema, model)
            with patch.object(adapter, "request", return_value={"stop_reason": "end_turn", "content": [{"type": "text", "text": json.dumps(value)}]}):
                return await ClaudeAdapter.complete(adapter, role, payload, schema, model)
        with tempfile.TemporaryDirectory() as directory:
            engine = Orchestrator(Contract("test", max_depth=0, max_tool_rounds=2), adapter, Path(directory) / "run")
            self.assertEqual(adapter.max_tool_rounds, 2)
            with patch.object(adapter, "complete", side_effect=fake_complete):
                self.assertEqual(await engine.run(), "complete")

    def test_provider_switch_keeps_keys_separate(self):
        class Variable:
            def __init__(self, value=""): self.value = value
            def get(self): return self.value
            def set(self, value): self.value = value
        ui = MagicMock()
        ui.active_provider = "OpenAI"
        ui.provider_settings = {}
        ui.key, ui.model, ui.strong = Variable("openai-key"), Variable("openai-model"), Variable("")
        ui.mode = Variable("Claude")
        Studio.mode_changed(ui)
        self.assertEqual(ui.key.get(), "")
        ui.key.set("claude-key"); ui.model.set("claude-model")
        ui.mode.set("OpenAI")
        Studio.mode_changed(ui)
        self.assertEqual(ui.key.get(), "openai-key")
        self.assertEqual(ui.model.get(), "openai-model")
        ui.mode.set("Claude")
        Studio.mode_changed(ui)
        self.assertEqual(ui.key.get(), "claude-key")


if __name__ == "__main__": unittest.main()
