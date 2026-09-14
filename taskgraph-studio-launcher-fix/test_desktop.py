"""Headless checks for UI graph projection and the live desktop event bridge."""
import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from desktop import graph_subset, task_positions, initial_snapshot, read_run, Studio, parse_limits, DEFAULT_LIMITS
from unittest.mock import MagicMock
from engine import Contract, MockAdapter, Orchestrator, OpenAIAdapter


class DesktopTests(unittest.TestCase):
    def test_editable_limits_keep_defaults_and_accept_changes(self):
        self.assertEqual(parse_limits(DEFAULT_LIMITS)["max_tasks"], 80)
        self.assertEqual(parse_limits(DEFAULT_LIMITS)["max_calls"], 100)
        self.assertEqual(parse_limits(DEFAULT_LIMITS)["timeout"], 90)
        self.assertEqual(parse_limits(DEFAULT_LIMITS, connected=True)["timeout"], 300)
        limits = parse_limits({**DEFAULT_LIMITS, "max_tasks": "120", "max_calls": "250", "parallelism": "2", "timeout": "180"})
        self.assertEqual((limits["max_tasks"], limits["max_calls"], limits["parallelism"], limits["timeout"]), (120, 250, 2, 180))

    def test_invalid_limits_rejected(self):
        for key, value in [("max_tasks", "0"), ("max_calls", "1.5"), ("parallelism", "-1"), ("timeout", "nan")]:
            with self.assertRaises(ValueError): parse_limits({**DEFAULT_LIMITS, key: value})
        with self.assertRaises(ValueError): parse_limits({**DEFAULT_LIMITS, "max_depth": "0"}, strategy="multi_step")

    def test_copy_error_preserves_entire_message(self):
        ui = MagicMock()
        message = "Task 't1' has unknown dependencies.\nFull diagnostic — no truncation."
        ui.snapshot = {"error": message}
        Studio.copy_error(ui)
        ui.clipboard_clear.assert_called_once()
        ui.clipboard_append.assert_called_once_with(message)

    def test_graph_exists_before_any_model_call(self):
        state = initial_snapshot(Contract("Five company ideas"))
        self.assertEqual(state["calls"], 0)
        self.assertEqual(state["tasks"]["root"]["title"], "Five company ideas")
        surface = MagicMock()
        surface.snapshot = state
        surface.view = "Task map"
        surface.canvas.bbox.return_value = (0, 0, 590, 160)
        Studio.draw_graph(surface)
        surface.card.assert_called_once()
        self.assertTrue(any("BUILDING THE PLAN" == call.kwargs.get("text") for call in surface.canvas.create_text.call_args_list))

    def test_legacy_failure_is_visible_without_rewriting_file(self):
        with tempfile.TemporaryDirectory() as temp:
            filename = Path(temp) / "state.json"
            state = initial_snapshot(Contract("test"))
            state["state"] = "failed"
            state["tasks"]["root"]["status"] = "pending"
            filename.write_text(json.dumps(state))
            (Path(temp) / "events.jsonl").write_text(json.dumps({"error": "HTTP Error 429: Too Many Requests"}))
            loaded = read_run(filename)
            self.assertEqual(loaded["tasks"]["root"]["status"], "failed")
            self.assertIn("429", loaded["error"])
            self.assertEqual(json.loads(filename.read_text())["tasks"]["root"]["status"], "pending")

    def test_layout_follows_dependencies(self):
        tasks = {"root": {"deps": ["a", "b"]}, "a": {"deps": []}, "b": {"deps": ["c"]}, "c": {"deps": []}}
        positions = task_positions(tasks)
        self.assertEqual(len(set(positions.values())), len(tasks))
        for key, task in tasks.items():
            for dep in task["deps"]:
                self.assertGreater(positions[key][0], positions[dep][0])

    def test_latest_artifact_projection(self):
        state = {"artifacts": {
            "old": {"task": "x", "revision": 0, "label": "accepted"},
            "candidate": {"task": "x", "revision": 1, "label": "candidate_a"},
            "new": {"task": "x", "revision": 1, "label": "accepted"}},
            "reasoning": {"nodes": {
                "one": {"artifact": "old"}, "two": {"artifact": "candidate"}, "three": {"artifact": "new"}},
                "edges": [{"from": "one", "to": "two", "relation": "supports"}]}}
        self.assertEqual(set(graph_subset(state)["nodes"]), {"three"})
        self.assertEqual(graph_subset(state)["edges"], [])
        self.assertEqual(len(graph_subset(state, True)["nodes"]), 3)

    def test_desktop_event_snapshots(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp) / "run"
            snapshots = []
            def event(record):
                snapshots.append(json.loads((directory / "state.json").read_text()))
            engine = Orchestrator(Contract("Test", disagreement=True), MockAdapter(), directory, on_event=event)
            self.assertEqual(asyncio.run(engine.run()), "complete")
            for state in snapshots:
                task_positions(state["tasks"])
                graph_subset(state)
            self.assertEqual(snapshots[-1]["state"], "complete")
            self.assertGreater(len(snapshots), 10)

    def test_explicit_key_stays_on_adapter(self):
        adapter = OpenAIAdapter("desktop-test-key")
        self.assertEqual(adapter.key, "desktop-test-key")


if __name__ == "__main__":
    unittest.main()
