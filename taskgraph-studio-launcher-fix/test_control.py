import tempfile
import unittest
from pathlib import Path
from control import ProgressController
from engine import Contract, MockAdapter, Orchestrator


class IntakeAdapter(MockAdapter):
    def __init__(self, needs_web=False, missing=None):
        self.needs_web, self.missing = needs_web, missing or []
        self.roles = []

    async def complete(self, role, payload, schema, model):
        self.roles.append(role)
        if role == "intake":
            return {"deliverable": "A sourced comparison", "completion_checks": ["Compare the alternatives using supplied evidence"],
                    "requires_internet": self.needs_web, "initial_search_query": "current alternatives" if self.needs_web else "",
                    "required_tools": [], "missing_inputs": self.missing, "evidence_requirement": "Cite supporting sources"}
        return await super().complete(role, payload, schema, model)


class Broker:
    calls, max_calls = 0, 24
    def __init__(self, failed=False): self.failed = failed
    def definitions(self): return [{"name": "internet_search", "description": "Search"}]
    async def invoke(self, name, args, task):
        self.calls += 1
        return {"isError": self.failed, "result": {"isError": self.failed, "text": "Source result"}}


class ControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_unattached_auto_search_is_not_zero_budget_or_missing_input(self):
        class InitiallyBlocked(IntakeAdapter):
            async def complete(self, role, payload, schema, model):
                result = await super().complete(role, payload, schema, model)
                if role == "intake":
                    self.assert_payload = payload
                    if not payload["host_resource_status"]["enabled_tool_names"]:
                        result["missing_inputs"] = ["No enabled tools yet"]
                return result
        with tempfile.TemporaryDirectory() as temp:
            adapter = InitiallyBlocked(needs_web=True)
            engine = Orchestrator(Contract("Compare current alternatives", adaptive_control=True, max_depth=0), adapter, Path(temp) / "run")
            async def setup(): adapter.tool_broker = Broker()
            engine.internet_setup = setup
            intake = engine.intake_payload()
            self.assertEqual(intake["host_resource_status"]["remaining_tool_calls"], 24)
            self.assertEqual(intake["host_resource_status"]["available_on_demand"], ["internet_search"])
            self.assertNotIn("planning_requirement", intake)
            self.assertNotIn("collection", intake)
            self.assertEqual(await engine.run(), "complete")
            self.assertEqual(adapter.roles.count("intake"), 2)
            self.assertEqual(engine.readiness["resource_check"], "search_succeeded")

    async def test_reassessment_does_not_discard_genuinely_missing_data(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = IntakeAdapter(needs_web=True, missing=["Supply the private dataset"])
            engine = Orchestrator(Contract("Compare current data", adaptive_control=True), adapter, Path(temp) / "run")
            async def setup(): adapter.tool_broker = Broker()
            engine.internet_setup = setup
            self.assertEqual(await engine.run(), "needs_resources")
            self.assertIn("private dataset", engine.error)
            self.assertEqual(adapter.tool_broker.calls, 0)
            self.assertEqual(adapter.roles, ["intake", "intake"])

    def test_progress_resets_on_new_evidence(self):
        controller = ProgressController()
        self.assertEqual(controller.observe("task", {"a"})["decision"], "continue")
        self.assertEqual(controller.observe("task", {"a"})["decision"], "change_approach")
        self.assertEqual(controller.observe("task", {"a", "b"})["decision"], "continue")
        controller.observe("task", {"a", "b"})
        self.assertEqual(controller.observe("task", {"a", "b"})["decision"], "stop_stalled")

    async def test_auto_search_activates_and_checks_before_workers(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = IntakeAdapter(needs_web=True)
            engine = Orchestrator(Contract("Compare alternatives", adaptive_control=True, max_depth=0), adapter, Path(temp) / "run")
            async def setup(): adapter.tool_broker = Broker()
            engine.internet_setup = setup
            self.assertEqual(await engine.run(), "complete")
            self.assertEqual(adapter.roles[0], "intake")
            self.assertEqual(adapter.tool_broker.calls, 1)
            self.assertEqual(engine.readiness["resource_check"], "search_succeeded")
            self.assertTrue((engine.directory / "task-readiness.json").exists())

    async def test_off_and_failed_search_stop_before_worker(self):
        for mode, failed in [("off", False), ("auto", True)]:
            with tempfile.TemporaryDirectory() as temp:
                adapter = IntakeAdapter(needs_web=True)
                engine = Orchestrator(Contract("Compare alternatives", adaptive_control=True, internet_mode=mode), adapter, Path(temp) / "run")
                async def setup(): adapter.tool_broker = Broker(failed)
                engine.internet_setup = setup
                self.assertEqual(await engine.run(), "needs_resources")
                self.assertEqual(adapter.roles, ["intake"])
                self.assertEqual(len(engine.tasks), 1)

    async def test_writing_does_not_enable_search_and_missing_data_blocks(self):
        for missing in [[], ["Supply the dataset to analyze"]]:
            with tempfile.TemporaryDirectory() as temp:
                adapter = IntakeAdapter(missing=missing)
                engine = Orchestrator(Contract("Write a paragraph", adaptive_control=True, max_depth=0), adapter, Path(temp) / "run")
                async def setup(): raise AssertionError("Search not needed")
                engine.internet_setup = setup
                self.assertEqual(await engine.run(), "needs_resources" if missing else "complete")

    async def test_repeated_unresolved_review_stalls_instead_of_repair_error(self):
        class Stuck(IntakeAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "critic":
                    return {"accepted": False, "issues": ["Missing evidence"], "blocked_reason": ""}
                return await super().complete(role, payload, schema, model)
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("Compare alternatives", adaptive_control=True, max_depth=0), Stuck(), Path(temp) / "run")
            self.assertEqual(await engine.run(), "stalled", engine.error)
            self.assertNotIn("Repair limit exhausted", engine.error)
            self.assertFalse((engine.directory / "answer.md").exists())

    async def test_model_budget_is_distinct_terminal_outcome(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("Compare alternatives", adaptive_control=True, max_calls=1, max_depth=0), IntakeAdapter(), Path(temp) / "run")
            self.assertEqual(await engine.run(), "budget_exhausted")
            self.assertEqual(engine.calls, 1)
