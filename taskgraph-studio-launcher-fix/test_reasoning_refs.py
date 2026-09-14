import copy
import tempfile
import unittest
from pathlib import Path
from engine import Contract, MockAdapter, Orchestrator
from reasoning_refs import resolve_references


def result():
    return {"answer": "Draft", "claims": [{"id": "c1", "text": "Claim", "confidence": .5,
            "evidence": ["tool-artifact:one"], "contradicts": [], "assumptions": []}],
            "evidence": [{"id": "e1", "text": "Source", "source": "tool-artifact:one"}],
            "assumptions": [], "limitations": []}


class ReferenceTests(unittest.IsolatedAsyncioTestCase):
    def test_missing_literal_assumption_is_registered_verbatim(self):
        raw = result()
        statement = "I could not verify 20 distinct vacancies from the remaining retrieved evidence, so the batch is short by 2."
        raw["claims"][0]["assumptions"] = [statement]
        fixed = resolve_references(raw, {})
        self.assertEqual(fixed["assumptions"], [statement])
        self.assertEqual(fixed["claims"][0]["assumptions"], [statement])
        self.assertEqual(raw["assumptions"], [])
        self.assertIn("not verified facts", fixed["limitations"][-1])
        Orchestrator.check_result(None, fixed)

    def test_opaque_assumption_is_not_given_an_invented_meaning(self):
        raw = result()
        raw["claims"][0]["assumptions"] = ["A1"]
        fixed = resolve_references(raw, {})
        self.assertEqual(fixed["assumptions"], [])
        self.assertEqual(fixed["claims"][0]["assumptions"], [])
        self.assertEqual(fixed["unresolved_references"][0]["target"], "A1")
        Orchestrator.check_result(None, fixed)

    def test_unique_source_alias_resolves_without_changing_original(self):
        raw = result()
        fixed = resolve_references(raw, {"tool-artifact:one"})
        self.assertEqual(fixed["claims"][0]["evidence"], ["e1"])
        self.assertEqual(raw["claims"][0]["evidence"], ["tool-artifact:one"])
        self.assertEqual(fixed["claims"][0]["confidence"], .5)

    def test_many_local_items_use_an_explicit_existing_artifact_reference(self):
        raw = result()
        raw["evidence"].append({"id": "e2", "text": "Other fact", "source": "tool-artifact:one"})
        fixed = resolve_references(raw, {"tool-artifact:one"})
        linked = fixed["claims"][0]["evidence"]
        self.assertEqual(len(linked), 1)
        self.assertNotIn(linked[0], {"e1", "e2"})
        self.assertEqual(fixed["evidence"][-1]["source"], "tool-artifact:one")

    def test_unknown_targets_are_explicit_not_fabricated(self):
        raw = result()
        raw["claims"][0]["evidence"] = ["missing"]
        raw["claims"][0]["contradicts"] = ["missing_claim"]
        fixed = resolve_references(raw, {})
        self.assertEqual(fixed["claims"][0]["evidence"], [])
        self.assertEqual(fixed["claims"][0]["contradicts"], [])
        self.assertEqual(len(fixed["unresolved_references"]), 2)
        self.assertIn("missing_claim", fixed["limitations"][-1])
        self.assertEqual(fixed["claims"][0]["text"], "Claim")

    async def test_real_alias_does_not_consume_structural_repair_calls(self):
        class Alias(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "general": return result()
                return await super().complete(role, payload, schema, model)
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("Explain sources", max_depth=0), Alias(), Path(temp) / "run")
            self.assertEqual(await engine.run(), "complete")
            self.assertEqual(engine.calls, 2)
            self.assertTrue(list((engine.directory / "artifacts").glob("*.references-resolved-*.json")))

    async def test_unknown_links_cannot_be_accepted_by_a_lenient_critic(self):
        class Unknown(MockAdapter):
            async def complete(self, role, payload, schema, model):
                if role == "general":
                    raw = result()
                    raw["claims"][0]["evidence"] = ["nonexistent"]
                    return raw
                return await super().complete(role, payload, schema, model)
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("Explain sources", max_depth=0), Unknown(), Path(temp) / "run")
            self.assertEqual(await engine.run(), "needs_resources")
            self.assertEqual(engine.calls, 2)
            self.assertFalse((engine.directory / "answer.md").exists())
