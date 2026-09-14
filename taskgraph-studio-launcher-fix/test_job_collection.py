import copy
import tempfile
import unittest
from pathlib import Path
from engine import Contract, Orchestrator, MockAdapter, Task
from job_collection import requested_jobs, merge_items, canonical, render, vacancy_url, reconcile_review


def listing(n, source="tool-artifact:seed"):
    return {"title": "Forward Deployed Engineer", "organization": f"Employer {n}",
            "location": "Remote", "url": f"https://example.org/jobs/{n}", "source": source,
            "status_note": "Retrieved posting; open status not independently verified."}


class Collecting(MockAdapter):
    def __init__(self, fail=False):
        self.fail = fail
        self.continuations = []
        self.n = 0
        self.tool_broker = self
        self.routes = {"internet_search": True}
        self.calls, self.max_calls = 0, 24

    def definitions(self):
        return [{"name": "internet_search", "description": "Search"}]

    async def complete(self, role, payload, schema, model):
        result = await super().complete(role, payload, schema, model)
        if "job_items" not in schema.get("properties", {}):
            return result
        if "collection_continuation" in payload:
            self.continuations.append(copy.deepcopy(payload["collection_continuation"]))
        old = payload.get("collection_continuation", {}).get("preserve_items", [])
        if self.fail:
            result["job_items"] = [listing(99, "fake")]
        else:
            self.n += 1
            result["job_items"] = old + [listing(self.n)]
        return result


class CollectionTests(unittest.IsolatedAsyncioTestCase):
    def test_review_reconciliation_never_approves_missing_or_conflicting_rows(self):
        rows = [{"url": listing(1)["url"] + "?utm_source=openai", "classification": "supported", "reason": "Source supports it"},
                {"url": listing(2)["url"], "classification": "supported", "reason": "A"},
                {"url": listing(2)["url"], "classification": "unsupported", "reason": "B"},
                {"url": listing(99)["url"], "classification": "supported", "reason": "Unrequested"}]
        result, ignored = reconcile_review(rows, [listing(1), listing(2), listing(3)])
        self.assertEqual([r["classification"] for r in result["rows"]], ["supported", "ambiguous", "ambiguous"])
        self.assertEqual(result["rows"][0]["url"], listing(1)["url"])
        self.assertEqual(ignored, [listing(99)["url"]])

    def test_greenhouse_application_token_is_a_vacancy_not_a_board(self):
        self.assertTrue(vacancy_url("https://boards.greenhouse.io/embed/job_app?token=5414236&utm_source=openai"))
        self.assertFalse(vacancy_url("https://boards.greenhouse.io/embed/job_app?for=company"))
        self.assertFalse(vacancy_url("https://boards.greenhouse.io/embed/job_board?for=company"))

    async def test_incomplete_reviewer_response_keeps_supported_rows_without_retries(self):
        class Incomplete(MockAdapter):
            async def complete(self, role, payload, schema, model):
                assert "collection" not in payload
                return {"rows": [{"url": listing(1)["url"], "classification": "supported", "reason": "Source supports it"},
                                 {"url": listing(99)["url"], "classification": "supported", "reason": "Wrong extra row"}]}
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("find me 3 AI jobs"), Incomplete(), Path(temp) / "run")
            task = Task("root.jobs_batch1", "Batch", parent="root")
            engine.tasks[task.id] = task
            candidate = {"answer": "", "claims": [], "evidence": [], "assumptions": [], "limitations": [], "job_items": [listing(1), listing(2), listing(3)]}
            result = await engine.review_job_batch(task, candidate)
            self.assertEqual(engine.calls, 1)
            self.assertEqual(result["job_items"], [listing(1)])
            self.assertIn("2 ambiguous", result["answer"])
            self.assertTrue(list((engine.directory / "artifacts").glob("*.review-reconciled-*.json")))

    def test_board_homepages_are_not_vacancies_even_when_retrieved(self):
        for url in ["https://jobs.lever.co/AIFund", "https://jobs.lever.co/arsiem/", "https://jobs.ashbyhq.com/example", "https://job-boards.greenhouse.io/example", "https://example.org/careers"]:
            self.assertFalse(vacancy_url(url))
            item = {**listing(1), "url": url}
            items, issues = merge_items([item], [], {item["source"]: {canonical(url)}})
            self.assertEqual(items, [])
            self.assertTrue(issues)
        self.assertTrue(vacancy_url("https://jobs.lever.co/arsiem/vacancy-id"))
        self.assertTrue(vacancy_url("https://job-boards.greenhouse.io/example/jobs/123"))

    async def test_twelve_of_thirteen_batch_is_row_reviewed_without_count_repairs(self):
        class BatchAdapter(Collecting):
            async def complete(self, role, payload, schema, model):
                if role == "critic":
                    raise AssertionError("Batch must not reach generic count critic")
                if role == "batch_verifier":
                    return {"rows": [{"url": item["url"], "classification": "ambiguous" if i == 0 else "unsupported" if i == 1 else "supported", "reason": "Test verdict"} for i, item in enumerate(payload["candidate"]["job_items"])]}
                result = await super().complete(role, payload, schema, model)
                result["job_items"] = [listing(n) for n in range(1, 13)]
                return result
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("find me 50 AI jobs", max_tool_rounds=1), BatchAdapter(), Path(temp) / "run")
            for i in range(1, 5):
                task = Task(f"root.jobs_batch{i}", "Source batch", "research", depth=1, parent="root", planned=True)
                engine.tasks[task.id] = task
            engine.retrieved_sources["tool-artifact:seed"] = {canonical(listing(n)["url"]) for n in range(1, 13)}
            task = engine.tasks["root.jobs_batch1"]
            await engine.execute(task)
            self.assertEqual(task.status, "done")
            self.assertEqual(len(task.output["job_items"]), 10)
            self.assertIn("1 ambiguous and 1 unsupported", task.output["answer"])
            self.assertIn("Search allocation: 13; shortfall: 3", task.output["answer"])
            self.assertFalse(any("repair" in key for key in engine.tasks))

    async def test_exhausted_search_budget_still_allows_extracting_retrieved_records(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = Collecting()
            adapter.calls = adapter.max_calls
            engine = Orchestrator(Contract("find me 3 AI jobs", max_depth=0), adapter, Path(temp) / "run")
            engine.retrieved_sources["tool-artifact:seed"] = {canonical(listing(n)["url"]) for n in range(1, 4)}
            self.assertEqual(await engine.run(), "complete")
            self.assertEqual(len(adapter.continuations), 2)

    async def test_no_search_tools_stops_before_any_model_call(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("find me 50 AI jobs"), MockAdapter(), Path(temp) / "run")
            self.assertEqual(await engine.run(), "needs_resources")
            self.assertEqual(engine.calls, 0)
            self.assertEqual(len(engine.tasks), 1)
            self.assertIn("Internet Search Auto or On", engine.error)
            self.assertEqual(engine.tasks["root"].status, "blocked")
            self.assertFalse((engine.directory / "answer.md").exists())

    async def test_empty_batches_do_not_create_critic_repairs(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("find me 50 AI jobs", max_tool_rounds=1), Collecting(fail=True), Path(temp) / "run")
            self.assertEqual(await engine.run(), "needs_resources")
            self.assertFalse(any("repair" in key for key in engine.tasks))
            self.assertTrue(any(a["label"] == "partial" for a in engine.artifacts.values()))

    def test_empty_inventory_does_not_claim_linked_entries(self):
        answer = render([], 50)
        self.assertIn("No source-linked", answer)
        self.assertNotIn("Each entry links", answer)

    def test_goal_detection_and_deduplication(self):
        self.assertEqual(requested_jobs("find me a list of 50 forward deployed engineer jobs"), 50)
        self.assertIsNone(requested_jobs("Write 50 lines of code"))
        sources = {"tool-artifact:seed": {canonical(listing(1)["url"]), canonical(listing(2)["url"])}}
        duplicate = {**listing(1), "url": listing(1)["url"] + "?utm_source=example"}
        cross_post = {**listing(1), "url": listing(2)["url"]}
        items, _ = merge_items([], [listing(1), duplicate, cross_post], sources)
        self.assertEqual(len(items), 1)

    def test_replacement_and_unobserved_url_rejected(self):
        sources = {"tool-artifact:seed": {canonical(listing(1)["url"])}}
        items, issues = merge_items([listing(1)], [{**listing(1), "organization": "Invented"}, listing(2)], sources)
        self.assertEqual(items, [listing(1)])
        self.assertEqual(len(issues), 2)

    async def test_shortfall_collects_more_preserves_items_and_renders_inventory(self):
        with tempfile.TemporaryDirectory() as temp:
            adapter = Collecting()
            engine = Orchestrator(Contract("find me a list of 3 engineer jobs", max_depth=0), adapter, Path(temp) / "run")
            engine.retrieved_sources["tool-artifact:seed"] = {canonical(listing(n)["url"]) for n in range(1, 8)}
            self.assertEqual(await engine.run(), "complete")
            output = engine.tasks["root"].output
            self.assertEqual(len(output["job_items"]), 3)
            self.assertEqual(len(adapter.continuations), 2)
            self.assertEqual(adapter.continuations[0]["preserve_items"], [listing(1)])
            self.assertIn("3 of 3", output["answer"])
            self.assertEqual(engine.tasks["root"].revision, 0)

    async def test_unsupported_inventory_blocks_without_critic_repairs(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("list of 50 engineer jobs", max_depth=0, max_tool_rounds=2), Collecting(fail=True), Path(temp) / "run")
            self.assertEqual(await engine.run(), "needs_resources")
            self.assertEqual(len(engine.tasks), 1)
            self.assertEqual(engine.calls, 3)
            self.assertFalse((engine.directory / "answer.md").exists())
            self.assertTrue((engine.directory / "artifacts/root.r0.partial.json").exists())

    async def test_parallel_batches_do_not_recursively_repeat_goal(self):
        with tempfile.TemporaryDirectory() as temp:
            engine = Orchestrator(Contract("list of 4 engineer jobs", max_tasks=5), Collecting(), Path(temp) / "run")
            engine.retrieved_sources["tool-artifact:seed"] = {canonical(listing(n)["url"]) for n in range(1, 30)}
            self.assertEqual(await engine.run(), "complete")
            self.assertEqual(len(engine.tasks), 5)
            self.assertEqual(len(engine.tasks["root"].output["job_items"]), 4)
            self.assertTrue(all(t.depth == 1 for t in engine.tasks.values() if t.id != "root"))
