"""Inspectable readiness contracts and evidence-based progress decisions."""
import re

STR = {"type": "string"}
STRINGS = {"type": "array", "items": STR}
FIELDS = {"deliverable": STR, "completion_checks": STRINGS,
          "requires_internet": {"type": "boolean"}, "initial_search_query": STR,
          "required_tools": STRINGS, "missing_inputs": STRINGS, "evidence_requirement": STR}
READINESS = {"type": "object", "properties": FIELDS, "required": list(FIELDS), "additionalProperties": False}


class BudgetExhausted(RuntimeError):
    pass


class ProgressController:
    def __init__(self):
        self.history = {}

    def observe(self, key, signals):
        signals = frozenset(signals)
        previous = self.history.get(key)
        gained = previous is None or bool(signals - previous[0])
        repeats = 0 if gained else previous[1] + 1
        self.history[key] = (signals | (previous[0] if previous else frozenset()), repeats)
        return {"decision": "stop_stalled" if repeats >= 2 else "change_approach" if repeats == 1 else "continue",
                "new_signals": len(signals - previous[0]) if previous else len(signals),
                "consecutive_no_progress": repeats,
                "directive": "Use a different source or method and resolve the recorded gap; do not merely reword the same answer." if repeats else "Continue toward the recorded completion checks within the remaining limits."}

    def review(self, task_id, issues, sources):
        # Repairs belong to the original task, not a new progress history.
        key = re.sub(r"\.repair\d+", "", task_id)
        normalized = {"issue:" + " ".join(i.lower().split()) for i in issues}
        previous = self.history.get("issues:" + key)
        self.history["issues:" + key] = (frozenset(normalized), 0)
        remaining = set(previous[0]) if previous else set()
        signals = {"source:" + s for s in sources}
        # Resolving a previously reported issue is observable progress too.
        signals.update("resolved:" + i for i in remaining - normalized)
        return self.observe("review:" + key, signals)


def demo_readiness(goal):
    return {"deliverable": goal, "completion_checks": ["Demonstrate orchestration; no substantive answer in Demo mode."],
            "requires_internet": False, "initial_search_query": "", "required_tools": [],
            "missing_inputs": [], "evidence_requirement": "Mock demonstration only."}
