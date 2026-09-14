import asyncio
import copy
import json
import tempfile
import unittest
import io
import urllib.error
from unittest.mock import patch
from pathlib import Path
from engine import Contract, MockAdapter, ModelPolicy, OpenAIAdapter, Orchestrator, Task, Worker, Registry, RESULT, validate


class EngineTests(unittest.IsolatedAsyncioTestCase):
    async def test_missing_sources_stops_without_repairs_or_final_answer(self):
        class MissingSources(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "critic":
                    return {"accepted": False, "issues": ["Only a template"],
                            "blocked_reason": "Supply current job listings or select a search MCP tool."}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(MissingSources(), max_depth=0)
        self.assertEqual(await engine.run(), "needs_resources")
        self.assertEqual(engine.calls, 2)
        self.assertEqual(engine.tasks["root"].status, "blocked")
        self.assertEqual(len(engine.tasks), 1)
        self.assertIsNone(engine.tasks["root"].output)
        self.assertFalse((engine.directory / "answer.md").exists())
        self.assertTrue((engine.directory / "artifacts/root.r0.partial.json").exists())
        self.assertIn("search MCP", engine.error)

    async def test_missing_resource_child_blocks_synthesis(self):
        class MissingSources(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "critic":
                    return {"accepted": False, "issues": [], "blocked_reason": "Current sources required."}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(MissingSources(), max_depth=1)
        self.assertEqual(await engine.run(), "needs_resources")
        self.assertEqual(engine.tasks["root"].status, "blocked")
        self.assertFalse(any("repair" in tid for tid in engine.tasks))
        self.assertFalse((engine.directory / "answer.md").exists())

    async def test_multistep_cannot_silently_become_one_worker(self):
        class Atomic(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "planner":
                    return {"tasks": []}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Atomic(), strategy="multi_step", max_depth=1)
        self.assertEqual(await engine.run(), "complete")
        self.assertEqual(len(engine.tasks["root"].deps), 2)
        self.assertEqual(len(engine.tasks), 3)
        self.assertTrue(all(engine.tasks[x].status == "done" for x in engine.tasks["root"].deps))
        self.assertIn("host_plan_used", (engine.directory / "events.jsonl").read_text())

    async def test_multistep_oversized_plan_keeps_two_children(self):
        class Large(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "planner":
                    return {"tasks": [{"id": f"t{i}", "title": "Work", "capability": "general", "deps": []} for i in range(4)]}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Large(), strategy="multi_step", max_tasks=3, max_depth=1)
        self.assertEqual(await engine.run(), "complete")
        self.assertEqual(len(engine.tasks), 3)

    def test_multistep_rejects_incompatible_limits(self):
        with self.assertRaises(ValueError):
            Contract("Goal", strategy="multi_step", max_tasks=1)
        with self.assertRaises(ValueError):
            Contract("Goal", strategy="multi_step", max_depth=0)

    def test_inherited_dependencies_are_valid_and_preserved(self):
        engine = self.engine()
        engine.tasks["root.t2"] = Task("root.t2", "Prior work", status="done")
        parent = Task("root.t3.t1", "Scope caveats", deps=["root.t2"])
        engine.tasks[parent.id] = parent
        specs = [
            {"id": "t1", "title": "Draft caveats", "capability": "general", "deps": ["root.t2"]},
            {"id": "t2", "title": "Review", "capability": "general", "deps": ["root.t2", "t1"]}]
        engine.add_plan(parent, specs)
        self.assertEqual(engine.tasks[parent.id + ".t1"].deps, ["root.t2"])
        self.assertEqual(engine.tasks[parent.id + ".t2"].deps, ["root.t2", parent.id + ".t1"])
        self.assertEqual(specs[0]["deps"], ["root.t2"])

    def test_unrelated_and_parent_dependencies_still_rejected_atomically(self):
        engine = self.engine()
        engine.tasks["unrelated"] = Task("unrelated", "Other")
        for dependency in ("missing", "root", "unrelated"):
            with self.assertRaisesRegex(ValueError, "unknown dependencies"):
                engine.add_plan(engine.tasks["root"], [{"id": "t1", "title": "A", "capability": "general", "deps": [dependency]}])
            self.assertEqual(set(engine.tasks), {"root", "unrelated"})

    async def test_oversized_plan_falls_back_to_complete_original_task(self):
        engine = self.engine(max_tasks=2)
        self.assertEqual(await engine.run(), "complete")
        self.assertEqual(len(engine.tasks), 1)
        self.assertEqual(engine.tasks["root"].title, "Compare options")
        self.assertIn("planning_budget_fallback", (engine.directory / "events.jsonl").read_text())

    async def test_full_graph_skips_planning_and_repairs_in_place(self):
        class RejectOnce(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "planner":
                    raise AssertionError("No task slots: planner must not be called")
                if role == "critic":
                    return {"accepted": payload["task"]["revision"] > 0, "issues": ["Improve the answer"], "blocked_reason": ""}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(RejectOnce(), max_tasks=1)
        self.assertEqual(await engine.run(), "complete")
        self.assertEqual(len(engine.tasks), 1)
        self.assertEqual(engine.tasks["root"].revision, 1)
        self.assertTrue((engine.directory / "artifacts/root.r0.candidate_a.json").exists())
        self.assertTrue((engine.directory / "artifacts/root.r1.accepted.json").exists())

    async def test_in_place_repairs_still_respect_repair_limit(self):
        class Reject(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "critic":
                    return {"accepted": False, "issues": ["Unsupported"], "blocked_reason": ""}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Reject(), max_tasks=1, max_repairs=1)
        self.assertEqual(await engine.run(), "failed")
        self.assertEqual(engine.calls, 4)
        self.assertEqual(len(engine.tasks), 1)
        self.assertIn("Repair limit", engine.error)

    def test_plan_renaming_preserves_dependencies_without_collisions(self):
        engine = self.engine()
        specs = [
            {"id": "a-b", "title": "A", "capability": "general", "deps": []},
            {"id": "a_b", "title": "B", "capability": "general", "deps": ["a-b"]},
            {"id": "../unsafe/path", "title": "C", "capability": "general", "deps": ["a_b"]}]
        engine.add_plan(engine.tasks["root"], specs)
        self.assertEqual(engine.tasks["root.t2"].deps, ["root.t1"])
        self.assertEqual(engine.tasks["root.t3"].deps, ["root.t2"])
        self.assertEqual(specs[0]["id"], "a-b")

    async def test_duplicate_plan_is_repaired_before_commit(self):
        class Duplicate(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "planner" and payload["task"]["id"] == "root":
                    if "output_repair" in payload:
                        return {"tasks": [{"id": "ok", "title": "Answer", "capability": "general", "deps": []}]}
                    return {"tasks": [{"id": "same", "title": "Answer", "capability": "general", "deps": []}] * 2}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Duplicate(), max_depth=1)
        self.assertEqual(await engine.run(), "complete")
        self.assertEqual(set(engine.tasks), {"root", "root.ok"})
        self.assertTrue(list((engine.directory / "artifacts").glob("*invalid-call-*.json")))

    async def test_duplicate_plan_correction_is_bounded_and_atomic(self):
        class Duplicate(MockAdapter):
            async def complete(self, *args):
                return {"tasks": [{"id": "same", "title": "Answer", "capability": "general", "deps": []}] * 2}
        engine = self.engine(Duplicate())
        self.assertEqual(await engine.run(), "failed")
        self.assertEqual(engine.calls, 3)
        self.assertEqual(set(engine.tasks), {"root"})
        self.assertIn("two attempts", engine.error)

    async def test_unknown_assumption_is_corrected_before_ingestion(self):
        class Mismatch(MockAdapter):
            async def complete(self, role, payload, schema, model):
                result = await super().complete(role, payload, schema, model)
                if schema == RESULT and "output_repair" not in payload:
                    result["claims"][0]["assumptions"] = ["A1"]
                return result
        engine = self.engine(Mismatch(), max_depth=0)
        self.assertEqual(await engine.run(), "needs_resources")
        self.assertEqual(engine.calls, 2)
        self.assertTrue(list((engine.directory / "artifacts").glob("*references-resolved-*.json")))
        self.assertFalse(any(n.get("text") == "A1" for n in engine.reasoning["nodes"].values()))
        self.assertIsNone(engine.tasks["root"].output)

    async def test_reference_correction_is_bounded(self):
        class Mismatch(MockAdapter):
            async def complete(self, role, payload, schema, model):
                result = await super().complete(role, payload, schema, model)
                if schema == RESULT:
                    result["claims"][0]["assumptions"] = ["A1"]
                return result
        engine = self.engine(Mismatch(), max_depth=0)
        self.assertEqual(await engine.run(), "needs_resources")
        self.assertEqual(engine.calls, 2)
        self.assertFalse(any(n.get("text") == "A1" for n in engine.reasoning["nodes"].values()))
        self.assertIn("references", engine.error)

    async def test_planning_visible_before_provider_returns(self):
        entered, release = asyncio.Event(), asyncio.Event()
        class Paused(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "planner" and payload["task"]["id"] == "root":
                    entered.set()
                    await release.wait()
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Paused())
        run = asyncio.create_task(engine.run())
        await asyncio.wait_for(entered.wait(), 1)
        state = json.loads((engine.directory / "state.json").read_text())
        self.assertEqual(state["tasks"]["root"]["status"], "planning")
        self.assertEqual(state["state"], "planning")
        release.set()
        self.assertEqual(await run, "complete")

    async def test_planner_failure_does_not_leave_pending_node(self):
        class Fail(MockAdapter):
            async def complete(self, *args):
                raise RuntimeError("Provider rejected the request")
        engine = self.engine(Fail())
        self.assertEqual(await engine.run(), "failed")
        self.assertEqual(engine.tasks["root"].status, "failed")
        state = json.loads((engine.directory / "state.json").read_text())
        self.assertEqual(state["error"], "Provider rejected the request")
        self.assertIn(state["error"], state["tasks"]["root"]["feedback"])

    async def test_429_classification(self):
        for code, expected in [("insufficient_quota", "billing"), ("rate_limit_exceeded", "rate limits"), ("", "may be")]:
            def reject(*args, **kwargs):
                raise urllib.error.HTTPError("https://api.openai.com", 429, "Too Many Requests", {},
                    io.BytesIO(json.dumps({"error": {"code": code, "message": "private content"}}).encode()))
            with patch("urllib.request.urlopen", side_effect=reject), patch("provider_retry.asyncio.sleep"):
                with self.assertRaisesRegex(RuntimeError, expected) as caught:
                    await OpenAIAdapter("fake-key").complete("planner", {}, {}, "test")
                self.assertNotIn("private content", str(caught.exception))

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def engine(self, adapter=None, **kwargs):
        return Orchestrator(Contract("Compare options", **kwargs), adapter or MockAdapter(), Path(self.temp.name) / "run")

    async def test_recursive_parallel_repair_and_store(self):
        engine = self.engine()
        self.assertEqual(await engine.run(), "complete")
        self.assertIn("root.research.facts", engine.tasks)
        self.assertIn("root.analysis.repair1", engine.tasks)
        self.assertGreaterEqual(engine.peak_active, 2)
        self.assertEqual(engine.tasks["root.analysis.repair1"].status, "done")
        self.assertTrue((engine.directory / "answer.md").exists())
        events = [json.loads(x) for x in (engine.directory / "events.jsonl").read_text().splitlines()]
        finished = {}
        for e in events:
            if e["event"] in {"completed", "repair_integrated"}:
                finished[e["task"]] = e["time"]
            if e["event"] == "started" and e["task"] == "root":
                self.assertIn("root.analysis", finished)
                self.assertIn("root.research", finished)
        for artifact in engine.artifacts.values():
            self.assertTrue((engine.directory / artifact["path"]).exists())
        for edge in engine.reasoning["edges"]:
            self.assertIn(edge["from"], engine.reasoning["nodes"])
            self.assertIn(edge["to"], engine.reasoning["nodes"])

    async def test_cycle_mutation_is_atomic(self):
        engine = self.engine()
        with self.assertRaisesRegex(ValueError, "Cyclic"):
            engine.add_plan(engine.tasks["root"], [
                {"id": "a", "title": "A", "capability": "general", "deps": ["b"]},
                {"id": "b", "title": "B", "capability": "general", "deps": ["a"]}])
        self.assertEqual(list(engine.tasks), ["root"])
        self.assertEqual(engine.tasks["root"].deps, [])

    async def test_failure_blocks_dependents(self):
        class Broken(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "code_data":
                    raise RuntimeError("Deliberate provider failure")
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Broken())
        self.assertEqual(await engine.run(), "failed")
        self.assertEqual(engine.tasks["root"].status, "blocked")

    async def test_call_limit(self):
        engine = self.engine(max_calls=1)
        self.assertEqual(await engine.run(), "failed")
        self.assertEqual(engine.calls, 1)

    async def test_disagreement_is_independent_and_judged(self):
        class Capture(MockAdapter):
            def __init__(self):
                self.inputs = []
            async def complete(self, role, payload, schema, model):
                self.inputs.append((role, copy.deepcopy(payload)))
                return await super().complete(role, payload, schema, model)
        adapter = Capture()
        engine = self.engine(adapter, disagreement=True, max_depth=0)
        self.assertEqual(await engine.run(), "complete")
        workers = [p for role, p in adapter.inputs if role == "general"]
        self.assertEqual(len(workers), 2)
        self.assertEqual(workers[0], workers[1])
        self.assertNotIn("candidates", workers[1])
        judge = [p for role, p in adapter.inputs if role == "judge"][0]
        self.assertEqual(len(judge["candidates"]), 2)

    async def test_repair_exhaustion(self):
        class Reject(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "critic":
                    return {"accepted": False, "issues": ["Missing support"], "blocked_reason": ""}
                return await super().complete(role, payload, schema, model)
        engine = self.engine(Reject(), max_depth=0, max_repairs=1)
        self.assertEqual(await engine.run(), "failed")
        self.assertEqual(len(engine.tasks), 2)
        self.assertEqual(engine.tasks["root.repair1"].status, "failed")

    async def test_timeout(self):
        class Slow(MockAdapter):
            async def complete(self, *args):
                await asyncio.sleep(1)
        engine = self.engine(Slow(), timeout=0.01)
        self.assertEqual(await engine.run(), "failed")

    async def test_openai_transport_contract(self):
        engine = self.engine()
        payload = engine.payload(engine.tasks["root"])
        result = await MockAdapter().complete("general", payload, RESULT, "mock")
        response = {"status": "completed", "output": [{"content": [{"type": "output_text", "text": json.dumps(result)}]}]}
        def fake_urlopen(request, timeout):
            body = json.loads(request.data)
            self.assertEqual(request.full_url, "https://api.openai.com/v1/responses")
            self.assertEqual(body["model"], "test-model")
            self.assertEqual(body["text"]["format"]["schema"], RESULT)
            self.assertFalse(body["store"])
            self.assertEqual(json.loads(body["input"]), payload)
            return io.BytesIO(json.dumps(response).encode())
        with patch.dict("os.environ", {"OPENAI_API_KEY": "fake-test-key"}), patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(await OpenAIAdapter().complete("general", payload, RESULT, "test-model"), result)
            response["status"] = "incomplete"
            with self.assertRaisesRegex(ValueError, "incomplete"):
                await OpenAIAdapter().complete("general", payload, RESULT, "test-model")

    async def test_reasoning_validation_and_contradictions(self):
        engine = self.engine()
        result = await MockAdapter().complete("general", engine.payload(engine.tasks["root"]), RESULT, "mock")
        result["claims"].append({"id": "c2", "text": "An opposing claim", "confidence": 0.2, "evidence": [], "assumptions": [], "contradicts": ["c1"]})
        engine.save_result(engine.tasks["root"], result, "test")
        self.assertTrue(any(e["relation"] == "contradicts" for e in engine.reasoning["edges"]))
        result["claims"][0]["confidence"] = 2
        with self.assertRaises(ValueError):
            engine.check_result(result)
        result["claims"][0]["confidence"] = 0.5
        result["claims"][0]["evidence"] = ["nonexistent"]
        with self.assertRaises(ValueError):
            engine.check_result(result)

    def test_routing_and_model_hooks(self):
        registry = Registry()
        registry.register(Worker("specialist", {"math", "code_data"}, "code_data"))
        self.assertEqual(registry.route("math").name, "specialist")
        with self.assertRaises(ValueError):
            registry.route("unknown")
        policy = ModelPolicy("small", "large")
        self.assertEqual(policy.select("general", Task("x", "x")), "small")
        self.assertEqual(policy.select("general", Task("x", "x", revision=1)), "large")

    def test_bad_contract_and_output(self):
        with self.assertRaises(ValueError):
            Contract(" ")
        with self.assertRaises(ValueError):
            Contract("goal", parallelism=0)
        with self.assertRaises(ValueError):
            Contract("goal", parallelism=1.5)
        with self.assertRaises(ValueError):
            Contract("goal", timeout=float("nan"))
        with self.assertRaises(ValueError):
            validate({"answer": 5}, RESULT)


if __name__ == "__main__":
    unittest.main()
