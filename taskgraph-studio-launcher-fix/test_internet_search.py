import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from internet_search import InternetSearch
from engine import Contract, MockAdapter, Orchestrator


class SearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_repeat_query_reuses_source_without_another_paid_request(self):
        broker = self.broker()
        with patch.object(broker, "request", return_value={"isError": False, "response": []}) as request:
            first = await broker.invoke("internet_search", {"query": "AI jobs"}, "root")
            second = await broker.invoke("internet_search", {"query": "  ai   jobs "}, "root")
        self.assertEqual(request.call_count, 1)
        self.assertEqual(first["source"], second["source"])
        self.assertTrue(second["reused"])

    def broker(self, provider="OpenAI", **kw):
        return InternetSearch(provider, "test-secret", "test-model", lambda *x: "tool-artifact:tool_1", lambda *x: None, **kw)

    def test_provider_requests_and_citations(self):
        for provider in ("OpenAI", "Claude"):
            if provider == "OpenAI":
                data = {"status": "completed", "output": [{"type": "web_search_call", "status": "completed", "action": {"sources": [{"url": "https://example.org/jobs"}]}}]}
            else:
                data = {"stop_reason": "end_turn", "content": [{"type": "web_search_tool_result", "content": [{"url": "https://example.org/jobs"}]}]}
            with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(data).encode())) as request:
                result = self.broker(provider).request("open engineering jobs")
            self.assertFalse(result["isError"])
            self.assertIn("https://example.org/jobs", json.dumps(result))
            body = json.loads(request.call_args.args[0].data)
            self.assertEqual(body["model"], "test-model")
            self.assertNotIn("test-secret", json.dumps(body))
            self.assertEqual(body["tools"][0]["type"], "web_search" if provider == "OpenAI" else "web_search_20250305")
            self.assertNotIn("output_config", body)

    def test_no_search_and_partial_response_are_not_success(self):
        for provider, data in [("OpenAI", {"status": "completed", "output": []}),
                               ("Claude", {"stop_reason": "pause_turn", "content": []}),
                               ("Claude", {"stop_reason": "end_turn", "content": [{"type": "web_search_tool_result", "content": {"type": "web_search_tool_result_error"}}]})]:
            with patch("urllib.request.urlopen", return_value=io.BytesIO(json.dumps(data).encode())):
                self.assertTrue(self.broker(provider).request("jobs")["isError"])

    async def test_budget_validation_and_error_audit(self):
        broker = self.broker(max_calls=2)
        with patch.object(broker, "request", side_effect=RuntimeError("private error")) as request:
            self.assertTrue((await broker.invoke("internet_search", {"query": ""}, "root"))["isError"])
            result = await broker.invoke("internet_search", {"query": "jobs"}, "root")
            self.assertTrue(result["isError"])
            self.assertEqual(result["source"], "tool-artifact:tool_1")
            self.assertNotIn("private error", json.dumps(result))
            self.assertTrue((await broker.invoke("internet_search", {"query": "jobs"}, "root"))["isError"])
            self.assertEqual(request.call_count, 1)

    async def test_engine_exposes_tool_counts_call_and_saves_source(self):
        class Searching(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "general":
                    assert any(t["name"] == "internet_search" for t in payload["available_tools"])
                    result = await self.tool_broker.invoke("internet_search", {"query": "jobs"}, payload["task"]["id"])
                    answer = await super().complete(role, payload, schema, model)
                    answer["evidence"][0]["source"] = result["source"]
                    return answer
                return await super().complete(role, payload, schema, model)
        with tempfile.TemporaryDirectory() as temp:
            adapter = Searching()
            engine = Orchestrator(Contract("Find jobs", max_depth=0), adapter, Path(temp) / "run")
            broker = InternetSearch("OpenAI", "key", "model", engine.audit_tool, engine.extra_model_request)
            adapter.tool_broker = broker
            with patch.object(broker, "request", return_value={"isError": False, "sources": ["https://example.org"]}):
                self.assertEqual(await engine.run(), "complete")
            self.assertEqual(engine.calls, 3)
            self.assertTrue(any(a["label"] == "tool" for a in engine.artifacts.values()))
            self.assertTrue(any(e["relation"] == "retrieved_from" for e in engine.reasoning["edges"]))

    async def test_mcp_delegation_shares_outer_budget(self):
        class Delegate:
            routes = {"other": True}
            def definitions(self): return []
            async def invoke(self, *args): return {"ok": True}
            def close(self): self.closed = True
        delegate = Delegate()
        broker = self.broker(delegate=delegate, max_calls=1)
        self.assertTrue((await broker.invoke("other", {}, "root"))["ok"])
        self.assertTrue((await broker.invoke("internet_search", {"query": "jobs"}, "root"))["isError"])
        broker.close()
        self.assertTrue(delegate.closed)
