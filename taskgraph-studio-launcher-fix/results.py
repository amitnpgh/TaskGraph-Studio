"""Display accepted answers or clearly marked, unaccepted root partial results."""
import json
from pathlib import Path


def display_result(state, directory=None):
    if not state:
        return None
    accepted = state.get("tasks", {}).get("root", {}).get("output")
    if accepted:
        return accepted
    if not directory:
        return None
    base = Path(directory).resolve()
    candidates = [a for a in state.get("artifacts", {}).values() if a.get("task") == "root" and a.get("label") == "partial"]
    for artifact in sorted(candidates, key=lambda a: a.get("revision", 0), reverse=True):
        try:
            path = (base / artifact["path"]).resolve()
            if not path.is_relative_to(base):
                continue
            result = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(result.get("answer"), str):
                continue
            return {**result, "answer": "PARTIAL RESULT — not accepted as complete; listings have not passed final review.\n\n" + result["answer"], "is_partial": True}
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    return None
