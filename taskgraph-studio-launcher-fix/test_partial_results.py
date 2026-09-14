import json
import tempfile
import unittest
from pathlib import Path
from engine import Contract, Orchestrator, MockAdapter
from results import display_result
from test_job_collection import Collecting


class PartialTests(unittest.IsolatedAsyncioTestCase):
    def test_partial_visible_without_becoming_accepted(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            (base / "partial.json").write_text(json.dumps({"answer": "37 candidates", "limitations": []}))
            state = {"tasks": {"root": {"output": None}}, "artifacts": {"x": {"task": "root", "label": "partial", "revision": 0, "path": "partial.json"}}}
            shown = display_result(state, base)
            self.assertTrue(shown["is_partial"])
            self.assertIn("PARTIAL RESULT", shown["answer"])
            self.assertIsNone(state["tasks"]["root"]["output"])
            state["artifacts"]["x"]["path"] = "../outside.json"
            self.assertIsNone(display_result(state, base))

    async def test_collection_round_limit_is_not_mislabeled_as_stall(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("find me 3 AI jobs", adaptive_control=True, max_depth=0, max_tool_rounds=2), Collecting(fail=True), Path(temp) / "run")
            self.assertEqual(await engine.run(), "budget_exhausted", engine.error)
            self.assertIn("continuation rounds", engine.error)
            self.assertIn("tool calls", engine.error)

    async def test_change_approach_uses_a_different_source_within_budget(self):
        class Search:
            calls, max_calls = 0, 24
            def definitions(self): return [{"name": "internet_search", "description": "Search"}]
            async def invoke(self, name, arguments, task):
                self.calls += 1
                self.query = arguments["query"]
                return {"isError": False}
        with tempfile.TemporaryDirectory() as temp:
            adapter = MockAdapter()
            adapter.tool_broker = Search()
            engine = Orchestrator(Contract("find me 50 AI jobs"), adapter, Path(temp) / "run")
            engine.search_history = ['site:jobs.ashbyhq.com AI jobs']
            await engine.change_collection_source(engine.tasks["root"])
            self.assertIn("-site:jobs.ashbyhq.com", adapter.tool_broker.query)
            self.assertEqual(adapter.tool_broker.calls, 1)
            adapter.tool_broker.calls = 24
            await engine.change_collection_source(engine.tasks["root"])
            self.assertEqual(adapter.tool_broker.calls, 24)
