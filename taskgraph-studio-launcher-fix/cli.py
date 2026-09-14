"""Run: python cli.py run --task 'Your problem' --watch"""
import argparse
import asyncio
import json
import sys
import time
from datetime import datetime
from pathlib import Path
from engine import Contract, MockAdapter, ModelPolicy, OpenAIAdapter, Orchestrator
from claude_adapter import ClaudeAdapter


def inspect(directory, reasoning=True):
    state = json.loads((Path(directory) / "state.json").read_text(encoding="utf-8"))
    print(f"\nSTATE: {state['state']} | model calls: {state['calls']}")
    print("TASK DAG (task <- prerequisites)")
    for tid, task in state["tasks"].items():
        print(f"  [{task['status']:11}] {tid} <- {', '.join(task['deps']) or '(none)'}")
        print(f"                  {task['title']}")
    if reasoning:
        print("REASONING GRAPH")
        for key, node in state["reasoning"]["nodes"].items():
            extra = f" confidence={node['confidence']}" if "confidence" in node else ""
            print(f"  {key} [{node['kind']}{extra}] {node['text']}")
        for edge in state["reasoning"]["edges"]:
            print(f"  {edge['from']} --{edge['relation']}--> {edge['to']}")
    return state["state"]


def main(argv=None):
    parser = argparse.ArgumentParser(description="Task DAG + reasoning graph orchestrator")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Enter an arbitrary problem or load a task contract")
    source = run.add_mutually_exclusive_group()
    source.add_argument("--task")
    source.add_argument("--contract", type=Path)
    run.add_argument("--adapter", choices=["mock", "openai", "claude"], default="mock")
    run.add_argument("--model", help="Required for live providers; choose a structured-output compatible model")
    run.add_argument("--strong-model", help="Optional model for critic, judge and repair")
    run.add_argument("--out", type=Path)
    run.add_argument("--watch", action="store_true", help="Print task DAG and reasoning graph at each transition")
    run.add_argument("--disagreement", action="store_true")
    run.add_argument("--internet", choices=["auto", "on", "off"], default="auto")
    show = sub.add_parser("inspect", help="Read a running or completed run")
    show.add_argument("directory", type=Path)
    show.add_argument("--watch", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "inspect":
            while True:
                status = inspect(args.directory)
                if not args.watch or status in {"complete", "failed", "needs_resources", "stalled", "budget_exhausted", "cancelled"}:
                    return 0
                time.sleep(1)
        data = json.loads(args.contract.read_text(encoding="utf-8")) if args.contract else {"goal": args.task or input("What problem should we solve? ")}
        if args.disagreement:
            data["disagreement"] = True
        data.setdefault("adaptive_control", args.adapter != "mock")
        data["internet_mode"] = args.internet
        contract = Contract(**data)
        if args.adapter != "mock" and not args.model:
            parser.error("--model is required with a live adapter")
        adapter = {"mock": MockAdapter, "openai": OpenAIAdapter, "claude": ClaudeAdapter}[args.adapter]()
        directory = args.out or Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        def event(record):
            print(f"{record['event']:20} {record.get('task', '')}", flush=True)
            if args.watch and record["event"] in {"decomposed", "artifact_saved", "repair_created", "finished"}:
                inspect(directory)
        engine = Orchestrator(contract, adapter, directory, ModelPolicy(args.model or "mock", args.strong_model), on_event=event)
        async def run_engine():
            async def enable_search():
                if adapter.tool_broker:
                    return
                from internet_search import InternetSearch
                adapter.tool_broker = InternetSearch("Claude" if args.adapter == "claude" else "OpenAI", adapter.key, args.model, engine.audit_tool, engine.extra_model_request, contract.max_tool_calls)
                adapter.on_extra_request = engine.extra_model_request
            if args.adapter != "mock":
                engine.internet_setup = enable_search
                if args.internet == "on":
                    await enable_search()
            try:
                return await engine.run()
            finally:
                if getattr(adapter, "tool_broker", None):
                    adapter.tool_broker.close()
        status = asyncio.run(run_engine())
        print(f"\nRun {status}. Inspect results in {directory.resolve()}")
        answer = directory / "answer.md"
        if answer.exists():
            print(answer.read_text(encoding="utf-8"))
        return 0 if status == "complete" else 1
    except (ValueError, OSError, TypeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted. The last snapshot remains available.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
