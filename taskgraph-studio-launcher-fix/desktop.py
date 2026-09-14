"""Taskgraph Studio: native desktop UI, no web server or additional dependencies."""
from __future__ import annotations
import asyncio
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from datetime import datetime
from dataclasses import asdict
from pathlib import Path
from engine import Contract, Task, MockAdapter, ModelPolicy, OpenAIAdapter, Orchestrator
from library import Library
from library_ui import LibraryWindow
from mcp_client import ToolBroker
from claude_adapter import ClaudeAdapter
from results import display_result

BASE = Path(__file__).resolve().parent
BG, PANEL, CARD, LINE = "#10131b", "#181d28", "#202735", "#30394b"
TEXT, MUTED, ACCENT = "#edf2fc", "#9eaec6", "#a0f2cf"
BLUE, GOLD, RED = "#84b9ff", "#f7c575", "#ff929f"
COLORS = {"done": ACCENT, "running": BLUE, "queued": BLUE, "pending": MUTED,
          "planning": BLUE, "reviewing": GOLD, "judging": GOLD, "correcting": GOLD,
          "failed": RED, "blocked": RED, "cancelled": GOLD, "repair_wait": GOLD}

DEFAULT_LIMITS = {"max_tasks": 80, "max_calls": 100, "parallelism": 3,
                  "max_depth": 3, "max_repairs": 2, "max_tool_calls": 24,
                  "max_tool_rounds": 8, "timeout": "Auto"}


def parse_limits(values, connected=False, strategy="auto"):
    limits = {}
    for key in DEFAULT_LIMITS:
        try:
            limits[key] = (300 if connected else 90) if key == "timeout" and str(values[key]).strip().lower() == "auto" else float(values[key]) if key == "timeout" else int(str(values[key]).strip())
        except (ValueError, TypeError):
            raise ValueError(f"Enter a valid {'number or Auto' if key == 'timeout' else 'whole number'} for {key.replace('_', ' ')}.") from None
    Contract("Validate limits", strategy=strategy, **limits)
    return limits


def initial_snapshot(contract):
    return {"state": "intake", "error": None, "contract": asdict(contract), "calls": 0,
            "tasks": {"root": asdict(Task("root", contract.goal, status="queued"))},
            "reasoning": {"nodes": {}, "edges": []}, "artifacts": {}}


def read_run(filename):
    """Read old snapshots without altering their saved audit history."""
    state = json.loads(Path(filename).read_text(encoding="utf-8"))
    if state.get("state") == "failed" and not state.get("error"):
        events = Path(filename).parent / "events.jsonl"
        if events.exists():
            for raw in events.read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(raw)
                except ValueError:
                    continue
                if event.get("error"):
                    state["error"] = event["error"]
        for task in state.get("tasks", {}).values():
            if task["status"] == "pending":
                task["status"] = "failed" if task["id"] == "root" else "blocked"
                task["feedback"].append(state.get("error") or "The run stopped before this task could execute.")
    return state


def task_positions(tasks):
    """Topological left-to-right layout, resilient when viewing incomplete data."""
    levels = {}
    remaining = set(tasks)
    while remaining:
        ready = [k for k in tasks if k in remaining and all(d in levels for d in tasks[k]["deps"])]
        if not ready:
            ready = list(remaining)
        for key in ready:
            levels[key] = max((levels.get(d, -1) + 1 for d in tasks[key]["deps"]), default=0)
            remaining.remove(key)
    rows, positions = {}, {}
    for key in tasks:
        level = levels[key]
        row = rows.get(level, 0)
        rows[level] = row + 1
        positions[key] = (36 + level * 292, 40 + row * 156)
    return positions


def graph_subset(state, history=False):
    graph = state.get("reasoning", {"nodes": {}, "edges": []})
    if history:
        return graph
    # Prefer the latest accepted artifact; otherwise display the latest candidate.
    chosen = {}
    for aid, artifact in state.get("artifacts", {}).items():
        task = artifact["task"]
        previous = chosen.get(task)
        score = (artifact["revision"], artifact["label"] == "accepted", artifact["label"] == "judge")
        if previous is None or score >= previous[0]:
            chosen[task] = (score, aid)
    ids = {v[1] for v in chosen.values()}
    ids.update(aid for aid, artifact in state.get("artifacts", {}).items() if artifact["label"] == "tool")
    nodes = {k: v for k, v in graph["nodes"].items() if v["artifact"] in ids}
    return {"nodes": nodes, "edges": [e for e in graph["edges"] if e["from"] in nodes and e["to"] in nodes]}


class DemoAdapter(MockAdapter):
    async def complete(self, *args):
        await asyncio.sleep(0.3)  # Make the mechanics visible in the live graph.
        return await super().complete(*args)


class Studio(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Taskgraph Studio · 1.2 OpenAI + Claude")
        self.geometry("1440x940")
        self.minsize(1000, 720)
        self.configure(bg=BG)
        self.option_add("*Font", ("Segoe UI", 11))
        self.messages = queue.Queue()
        self.library = Library(BASE / "library")
        self.selected_knowledge, self.selected_connections = set(), set()
        self.library_status = tk.StringVar(value="No library items selected")
        self.limit_values = dict(DEFAULT_LIMITS)
        self.limit_summary = tk.StringVar(value="80 tasks · 100 model calls")
        self.snapshot = None
        self.run_dir = None
        self.busy = False
        self.started_at = None
        self.selected = None
        self.view = "Task map"
        self.loop = self.run_future = None
        self.cancel_requested = False
        self.mode = tk.StringVar(value="Demo")
        self.strategy = tk.StringVar(value="Multi-step")
        self.model = tk.StringVar()
        self.strong = tk.StringVar()
        self.key = tk.StringVar()
        self.provider_settings = {}
        self.active_provider = "Demo"
        self.disagreement = tk.BooleanVar(value=False)
        try:
            preference = json.loads((BASE / "preferences.json").read_text(encoding="utf-8")).get("internet_search", "Auto")
        except (OSError, ValueError):
            preference = "Auto"
        self.internet_search = tk.StringVar(value=preference if preference in {"Auto", "On", "Off"} else "Auto")
        self.history = tk.BooleanVar(value=False)
        self.status = tk.StringVar(value="Ready when you are")
        self.counter = tk.StringVar(value="0 tasks     /     0 claims     /     0 calls")
        self._theme()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.after(100, self.poll)

    def _theme(self):
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TCombobox", fieldbackground=CARD, background=CARD, foreground=TEXT, arrowcolor=MUTED)
        style.map("TCombobox", fieldbackground=[("readonly", CARD)], foreground=[("readonly", TEXT)])
        style.configure("Vertical.TScrollbar", background=LINE, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)
        style.configure("Horizontal.TScrollbar", background=LINE, troughcolor=BG, bordercolor=BG, arrowcolor=MUTED)

    def label(self, parent, text=None, **kw):
        return tk.Label(parent, text=text, bg=parent.cget("bg"), fg=TEXT, anchor="w", **kw)

    def button(self, parent, text, command, primary=False):
        return tk.Button(parent, text=text, command=command, bg=ACCENT if primary else CARD,
                         fg=BG if primary else TEXT, activebackground=BLUE, activeforeground=BG,
                         relief="flat", bd=0, padx=16, pady=10, cursor="hand2",
                         disabledforeground=MUTED, font=("Segoe UI", 11, "bold" if primary else "normal"))

    def editor(self, parent, height=3):
        return tk.Text(parent, height=height, wrap="word", bg=CARD, fg=TEXT, insertbackground=ACCENT,
                       selectbackground="#395775", relief="flat", padx=12, pady=10, undo=True,
                       font=("Segoe UI", 11), highlightthickness=1, highlightbackground=LINE,
                       highlightcolor=ACCENT)

    def _build(self):
        top = tk.Frame(self, bg=BG, padx=24, pady=18)
        top.pack(fill="x")
        tk.Label(top, text="◈", bg=BG, fg=ACCENT, font=("Segoe UI", 28)).pack(side="left", padx=(0, 12))
        self.label(top, "Taskgraph", font=("Segoe UI", 22, "bold")).pack(side="left")
        tk.Label(top, text="STUDIO", bg=BG, fg=MUTED, font=("Segoe UI", 10, "bold")).pack(side="left", padx=12, pady=(8, 0))
        self.button(top, "Open saved run", self.open_run).pack(side="right")
        self.button(top, "Library", self.open_library).pack(side="right", padx=8)
        self.button(top, "Load example", self.load_example).pack(side="right", padx=8)
        main = tk.PanedWindow(self, orient="horizontal", bg=BG, sashwidth=8, bd=0)
        main.pack(fill="both", expand=True, padx=20, pady=(0, 16))

        # Scrollable intake remains usable on smaller displays.
        left = tk.Frame(main, bg=PANEL)
        main.add(left, minsize=300, width=344)
        form_canvas = tk.Canvas(left, bg=PANEL, highlightthickness=0)
        form_scroll = ttk.Scrollbar(left, orient="vertical", command=form_canvas.yview)
        form_canvas.configure(yscrollcommand=form_scroll.set)
        form_scroll.pack(side="right", fill="y")
        form_canvas.pack(side="left", fill="both", expand=True)
        form = tk.Frame(form_canvas, bg=PANEL, padx=18, pady=18)
        wid = form_canvas.create_window((0, 0), window=form, anchor="nw")
        form.bind("<Configure>", lambda e: form_canvas.configure(scrollregion=form_canvas.bbox("all")))
        form_canvas.bind("<Configure>", lambda e: form_canvas.itemconfigure(wid, width=e.width))
        self.label(form, "01  /  THE BRIEF", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(0, 18))
        self.label(form, "What are we solving?", font=("Segoe UI", 15, "bold")).pack(anchor="w", pady=(0, 8))
        self.goal = self.editor(form, 4)
        self.goal.pack(fill="x")
        self.label(form, "A good result should…").pack(anchor="w", pady=(16, 5))
        self.criteria = self.editor(form, 2)
        self.criteria.insert("1.0", "Answer the goal with explicit limitations")
        self.criteria.pack(fill="x")
        self.label(form, "Context & source material").pack(anchor="w", pady=(16, 5))
        self.context = self.editor(form, 3)
        self.context.pack(fill="x")
        self.label(form, "Constraints · one per line").pack(anchor="w", pady=(16, 5))
        self.constraints = self.editor(form, 2)
        self.constraints.pack(fill="x")
        self.label(form, "RUN SETTINGS", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(22, 10))
        self.button(form, "Run limits…", self.edit_limits).pack(fill="x", pady=(0, 6))
        tk.Label(form, textvariable=self.limit_summary, bg=PANEL, fg=MUTED, anchor="w").pack(fill="x", pady=(0, 10))
        self.button(form, "Choose knowledge & tools", self.open_library).pack(fill="x", pady=(0, 6))
        tk.Label(form, textvariable=self.library_status, bg=PANEL, fg=MUTED, anchor="w", wraplength=270).pack(fill="x", pady=(0, 10))
        self.label(form, "Approach").pack(anchor="w", pady=(0, 4))
        ttk.Combobox(form, textvariable=self.strategy, values=["Multi-step", "Auto"], state="readonly").pack(fill="x", pady=(0, 8))
        modes = ttk.Combobox(form, textvariable=self.mode, values=["Demo", "OpenAI", "Claude"], state="readonly")
        modes.pack(fill="x")
        modes.bind("<<ComboboxSelected>>", lambda e: self.mode_changed())
        self.connection = tk.Frame(form, bg=PANEL)
        for title, variable, secret in [("API key", self.key, True), ("Model ID", self.model, False), ("Stronger model · optional", self.strong, False)]:
            self.label(self.connection, title).pack(anchor="w", pady=(10, 4))
            tk.Entry(self.connection, textvariable=variable, show="•" if secret else "", bg=CARD, fg=TEXT,
                     insertbackground=TEXT, relief="flat").pack(fill="x", ipady=7)
        self.notice = tk.Label(form, text="Demo shows the workflow. It does not solve your problem.",
                               bg=PANEL, fg=GOLD, wraplength=270, justify="left", anchor="w", font=("Segoe UI", 10))
        self.notice.pack(fill="x", pady=12)
        self.label(form, "Internet Search").pack(anchor="w")
        ttk.Combobox(form, textvariable=self.internet_search, values=("Auto", "On", "Off"), state="readonly").pack(fill="x", pady=5)
        self.label(form, "Auto enables search when the task needs it.\nUses your provider key · search charges apply", font=("Segoe UI", 9)).pack(anchor="w", pady=(0, 10))
        self.toggle = tk.Checkbutton(form, text="Compare independent answers", variable=self.disagreement,
            bg=PANEL, fg=TEXT, selectcolor=CARD, activebackground=PANEL, activeforeground=TEXT,
            anchor="w", relief="flat", highlightthickness=0)
        self.toggle.pack(fill="x", pady=(0, 12))
        self.start_btn = self.button(form, "Start solving  →", self.start, primary=True)
        self.start_btn.pack(fill="x")
        self.stop_btn = self.button(form, "Stop run", self.stop)
        self.stop_btn.pack(fill="x", pady=(8, 0))
        self.stop_btn.configure(state="disabled")

        right = tk.Frame(main, bg=BG)
        main.add(right, minsize=640)
        head = tk.Frame(right, bg=BG, padx=12, pady=14)
        head.pack(fill="x")
        self.label(head, "02  /  WORKSPACE", font=("Segoe UI", 10, "bold")).pack(anchor="w")
        tk.Label(head, textvariable=self.status, bg=BG, fg=TEXT, font=("Segoe UI", 19, "bold"), anchor="w").pack(fill="x", pady=(10, 7))
        tk.Label(head, textvariable=self.counter, bg=BG, fg=MUTED, anchor="w").pack(fill="x")
        self.progress = ttk.Progressbar(head, mode="indeterminate")
        self.progress.pack(fill="x", pady=(12, 6))
        self.run_message = tk.Label(head, text="Your task map appears as soon as you start.", bg=BG, fg=MUTED,
                                    anchor="w", justify="left", wraplength=640, font=("Segoe UI", 11))
        self.run_message.pack(fill="x", pady=(4, 0))
        self.copy_error_btn = self.button(head, "Copy error", self.copy_error)
        self.copy_error_btn.pack(anchor="w", pady=(6, 0))
        self.copy_error_btn.configure(state="disabled")
        tabs = tk.Frame(right, bg=BG)
        tabs.pack(fill="x", padx=12, pady=(8, 12))
        self.tabs = {}
        for name in ("Task map", "Readiness", "Reasoning", "Answer", "Activity"):
            b = self.button(tabs, name, lambda name=name: self.change_view(name))
            b.pack(side="left", padx=(0, 4))
            self.tabs[name] = b
        self.history_toggle = tk.Checkbutton(tabs, text="All versions", variable=self.history,
            command=self.render, bg=BG, fg=MUTED, selectcolor=CARD, activebackground=BG, activeforeground=TEXT)
        self.surface = tk.Frame(right, bg=PANEL, highlightthickness=1, highlightbackground=LINE)
        self.surface.pack(fill="both", expand=True, padx=12)
        self.graph_frame = tk.Frame(self.surface, bg=PANEL)
        self.canvas = tk.Canvas(self.graph_frame, bg=PANEL, highlightthickness=0)
        hs = ttk.Scrollbar(self.graph_frame, orient="horizontal", command=self.canvas.xview)
        vs = ttk.Scrollbar(self.graph_frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(xscrollcommand=hs.set, yscrollcommand=vs.set)
        hs.pack(side="bottom", fill="x")
        vs.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<ButtonPress-2>", lambda e: self.canvas.scan_mark(e.x, e.y))
        self.canvas.bind("<B2-Motion>", lambda e: self.canvas.scan_dragto(e.x, e.y, gain=1))
        self.canvas.bind("<MouseWheel>", lambda e: self.canvas.yview_scroll(-int(e.delta / 120), "units"))
        self.document = self.editor(self.surface, 12)
        self.document.configure(state="disabled")
        self.detail = self.editor(right, 6)
        self.detail.pack(fill="x", padx=12, pady=(12, 0))
        footer = tk.Frame(right, bg=BG)
        footer.pack(fill="x", padx=12, pady=(8, 0))
        self.label(footer, "Select a node to explore its work and evidence.", font=("Segoe UI", 10)).pack(side="left")
        self.button(footer, "Copy answer", self.copy_answer).pack(side="right")
        self.change_view("Task map")

    def mode_changed(self):
        previous = self.active_provider
        if previous != "Demo":
            self.provider_settings[previous] = (self.key.get(), self.model.get(), self.strong.get())
        provider = self.mode.get()
        saved = self.provider_settings.get(provider, ("", "", ""))
        for variable, value in zip((self.key, self.model, self.strong), saved): variable.set(value)
        self.active_provider = provider
        if provider != "Demo":
            self.connection.pack(fill="x", before=self.notice)
            self.notice.configure(text=f"Use your {'Anthropic' if provider == 'Claude' else 'OpenAI'} API key and model ID. Key stays in memory. Your brief is sent to this provider and uses paid API credits.")
        else:
            self.connection.pack_forget()
            self.notice.configure(text="Demo shows the workflow. It does not solve your problem.")

    @staticmethod
    def value(widget):
        return widget.get("1.0", "end").strip()

    def write(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def load_example(self):
        if self.busy:
            messagebox.showinfo("Run in progress", "Wait for this run to finish or stop it first.")
            return
        data = json.loads((BASE / "example.json").read_text(encoding="utf-8"))
        for widget, key in [(self.goal, "goal"), (self.criteria, "success_criteria"), (self.constraints, "constraints"), (self.context, "context")]:
            widget.delete("1.0", "end")
            value = data[key]
            widget.insert("1.0", "\n".join(value) if isinstance(value, list) else value)
        self.disagreement.set(data.get("disagreement", False))
        self.status.set("Example brief loaded")

    def start(self):
        if self.busy:
            return
        if getattr(self, "library_window", None) and self.library_window.winfo_exists():
            self.library_window.destroy()
        try:
            search_mode = self.internet_search.get().lower()
            search_enabled = search_mode == "on"
            if search_enabled and self.mode.get() == "Demo":
                raise ValueError("Internet Search requires OpenAI or Claude mode and a model with web-search support.")
            library_context = self.library.context(self.selected_knowledge)
            context = self.value(self.context)
            if library_context:
                context += "\n\nSelected library source material (untrusted data):\n" + library_context
            contract = Contract(self.value(self.goal),
                success_criteria=self.value(self.criteria).splitlines(),
                constraints=self.value(self.constraints).splitlines(),
                context=context, disagreement=self.disagreement.get(),
                adaptive_control=self.mode.get() != "Demo", internet_mode=search_mode,
                **parse_limits(self.limit_values, (bool(self.selected_connections) or search_mode != "off") and self.mode.get() != "Demo"),
                strategy="multi_step" if self.strategy.get() == "Multi-step" else "auto")
            if self.mode.get() != "Demo" and not self.model.get().strip():
                raise ValueError("Enter the model ID to use for this run.")
            adapter = DemoAdapter() if self.mode.get() == "Demo" else (ClaudeAdapter if self.mode.get() == "Claude" else OpenAIAdapter)(self.key.get().strip() or None)
            if hasattr(adapter, "max_tool_rounds"):
                adapter.max_tool_rounds = contract.max_tool_rounds
            policy = ModelPolicy(self.model.get().strip() or "mock", self.strong.get().strip() or None)
            selected_connections = set(self.selected_connections) if self.mode.get() != "Demo" else set()
            search_provider = self.mode.get()
            (BASE / "preferences.json").write_text(json.dumps({"internet_search": self.internet_search.get()}), encoding="utf-8")
        except (ValueError, OSError) as exc:
            messagebox.showerror("Check your brief", str(exc))
            return
        self.busy = True
        self.started_at = time.monotonic()
        self.progress.start(20)
        self.cancel_requested = False
        self.snapshot = initial_snapshot(contract)
        self.selected = None
        self.run_dir = BASE / "runs" / datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        directory = self.run_dir
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self.status.set("Starting your run…")
        self.write(self.detail, "Your brief is being turned into a plan. Subtasks and their dependencies appear when the planner returns its first plan.")
        self.change_view("Task map")
        def work():
            broker = engine = None
            try:
                def update(record):
                    state = json.loads((directory / "state.json").read_text(encoding="utf-8"))
                    self.messages.put(("state", state))
                engine = Orchestrator(contract, adapter, directory, policy, on_event=update)
                # Keep only selected, non-secret resource names in the run manifest.
                manifest = {"knowledge": [{"id": r["id"], "name": r["name"]} for r in self.library.data["knowledge"] if r["id"] in self.selected_knowledge],
                            "connections": [{"id": r["id"], "name": r["name"]} for r in self.library.data["connections"] if r["id"] in selected_connections]}
                manifest["internet_search"] = search_enabled
                manifest["internet_search_mode"] = search_mode
                (directory / "library-selection.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                async def run():
                    nonlocal broker
                    self.loop = asyncio.get_running_loop()
                    self.run_future = asyncio.current_task()
                    if self.cancel_requested:
                        raise asyncio.CancelledError()
                    if selected_connections:
                        engine.state = "connecting"
                        engine.emit("connecting_tools")
                        broker = ToolBroker(self.library, selected_connections, self.ask_tool_approval, engine.audit_tool, max_calls=contract.max_tool_calls)
                        await broker.connect()
                        adapter.tool_broker = broker
                        adapter.on_extra_request = engine.extra_model_request
                        engine.emit("tools_connected", count=len(broker.routes))
                    async def enable_search():
                        nonlocal broker
                        from internet_search import InternetSearch
                        if isinstance(broker, InternetSearch):
                            return
                        broker = InternetSearch(search_provider, adapter.key, policy.default, engine.audit_tool,
                            engine.extra_model_request, contract.max_tool_calls, delegate=broker)
                        adapter.tool_broker = broker
                        adapter.on_extra_request = engine.extra_model_request
                        engine.emit("internet_search_enabled")
                        manifest["internet_search"] = True
                        (directory / "library-selection.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
                    if search_provider != "Demo":
                        engine.internet_setup = enable_search
                    if search_enabled:
                        await enable_search()
                    return await engine.run()
                try:
                    outcome = asyncio.run(run())
                except asyncio.CancelledError:
                    engine.state = "cancelled"
                    engine.emit("cancelled")
                    outcome = "cancelled"
                self.messages.put(("finished", outcome))
            except Exception as exc:
                if engine:
                    engine.state = "failed"
                    engine.error = str(exc)
                    engine.tasks["root"].status = "failed"
                    engine.emit("run_failed", error=str(exc))
                self.messages.put(("error", str(exc)))
            finally:
                if broker:
                    broker.close()
                self.loop = self.run_future = None
        threading.Thread(target=work, daemon=True).start()

    def stop(self):
        if not self.busy:
            return
        self.cancel_requested = True
        loop, future = self.loop, self.run_future
        if loop and future and not loop.is_closed():
            try:
                loop.call_soon_threadsafe(future.cancel)
            except RuntimeError:
                pass
        self.status.set("Stopping… an in-flight request may still finish")
        self.stop_btn.configure(state="disabled")

    def poll(self):
        changed = False
        while True:
            try:
                kind, data = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "state":
                self.snapshot = data
                changed = True
            elif kind == "approval":
                self.show_tool_approval(*data)
            elif kind in {"finished", "error"}:
                self.busy = False
                self.start_btn.configure(state="normal")
                self.stop_btn.configure(state="disabled")
                if kind == "error":
                    if self.snapshot:
                        self.snapshot["state"] = "failed"
                        self.snapshot["error"] = data
                        self.snapshot["tasks"]["root"]["status"] = "failed"
                    self.status.set("The run could not start")
                    messagebox.showerror("Run error", data)
                elif data == "complete":
                    self.change_view("Answer")
                self.progress.stop()
                changed = True
        if changed:
            self.render()
        self.update_run_message()
        self.after(100, self.poll)

    def update_run_message(self):
        state = self.snapshot
        self.copy_error_btn.configure(state="normal" if state and state.get("error") else "disabled")
        if not state:
            return
        if state["state"] in {"needs_resources", "stalled", "budget_exhausted"}:
            self.run_message.configure(text=state.get("error", "This run needs attention.") + " Open Readiness for the task contract and latest control decision.", fg=GOLD)
            return
        if state["state"] == "checking_readiness":
            self.run_message.configure(text="Understanding the deliverable and checking required resources before planning…", fg=BLUE)
            return
        if state["state"] == "failed":
            error = state.get("error") or "The run stopped. Open Activity for details."
            if error == "HTTP Error 429: Too Many Requests":
                error = "OpenAI rejected the first request (429). Check API billing and request limits, then start again."
            self.run_message.configure(text=error, fg=RED)
            return
        if state["state"] == "cancelled":
            self.run_message.configure(text="Stopped. Your existing work is saved.", fg=GOLD)
            return
        if state["state"] == "connecting":
            self.run_message.configure(text="Connecting selected MCP servers and checking tool permissions…", fg=BLUE)
            return
        if state["state"] == "complete":
            count = len(state["tasks"])
            text = ("Direct answer + critic review. No subtasks were created. Choose Multi-step for separate analysis tasks."
                    if count == 1 else f"{count} tasks completed their required work and review. Explore the map or read your answer.")
            self.run_message.configure(text=text, fg=ACCENT)
            return
        elapsed = int(time.monotonic() - self.started_at) if self.busy and self.started_at else 0
        planning = sum(t["status"] == "planning" for t in state["tasks"].values())
        if any(t["status"] == "correcting" for t in state["tasks"].values()):
            text = "Correcting the task plan or links between claims and evidence."
        elif planning or state["state"] == "intake":
            text = "Planner is building the task map. Subtasks appear when each plan is ready."
        else:
            text = "The map updates as workers execute, compare and review results."
        if self.busy:
            text += f"   •   {elapsed}s elapsed"
        self.run_message.configure(text=text, fg=BLUE)

    def change_view(self, name):
        self.view = name
        for title, button in self.tabs.items():
            button.configure(bg=ACCENT if title == name else CARD, fg=BG if title == name else MUTED)
        if name == "Reasoning":
            self.history_toggle.pack(side="right")
        else:
            self.history_toggle.pack_forget()
        self.render()

    def render(self):
        state = self.snapshot
        if state:
            tasks = state["tasks"]
            done = sum(t["status"] == "done" for t in tasks.values())
            claims = sum(n["kind"] == "claim" for n in graph_subset(state)["nodes"].values())
            self.counter.set(f"{done}/{len(tasks)} tasks complete     /     {claims} claims     /     {state['calls']} model calls")
            progress = state.get("collection_progress")
            if progress:
                self.counter.set(self.counter.get() + f"     /     {progress['collected']}/{progress['target']} listings ({progress['task']})")
            labels = {"complete": "Your result is ready", "needs_resources": "Needs resources", "stalled": "Progress stalled", "budget_exhausted": "Configured limit reached", "checking_readiness": "Checking task readiness", "failed": "This run needs attention", "cancelled": "Run stopped",
                      "planning": "Breaking the problem down", "executing": "Workers are on it", "scheduling": "Connecting the next steps", "intake": "Reading your brief"}
            self.status.set(labels.get(state["state"], state["state"].capitalize()))
        if self.view in {"Task map", "Reasoning"}:
            self.document.pack_forget()
            self.graph_frame.pack(fill="both", expand=True)
            self.draw_graph()
        else:
            self.graph_frame.pack_forget()
            self.document.pack(fill="both", expand=True)
            if self.view == "Answer":
                result = display_result(state, self.run_dir)
                if result:
                    text = result["answer"]
                    if result.get("limitations"):
                        text += "\n\nLIMITATIONS\n" + "\n".join("• " + x for x in result["limitations"])
                else:
                    text = "Your answer will appear here after the required work passes review."
                    if state and state["state"] in {"failed", "cancelled"}:
                        text = "No final answer was accepted. Open Activity or select a failed task to see what happened."
                    if state and state["state"] in {"needs_resources", "stalled", "budget_exhausted"}:
                        text = state.get("error", "This run needs attention.") + "\n\nThe requested deliverable is not complete. Open Readiness for the task contract and control decision. Saved candidates remain available in the run artifacts."
                self.write(self.document, text)
            elif self.view == "Readiness":
                readiness = (state or {}).get("readiness")
                if readiness:
                    text = "DELIVERABLE\n" + readiness["deliverable"] + "\n\nCOMPLETION CHECKS\n" + "\n".join("• " + x for x in readiness["completion_checks"])
                    text += "\n\nEVIDENCE REQUIRED\n" + readiness["evidence_requirement"]
                    text += "\n\nRESOURCE STATUS\n" + readiness.get("resource_check", "Checking")
                    text += "\nInternet required: " + str(readiness["requires_internet"])
                    text += "\nMissing inputs: " + ("; ".join(readiness["missing_inputs"]) or "None identified")
                    text += "\n\nLATEST CONTROL DECISION\n" + json.dumps(state.get("control_decision"), indent=2)
                    text += "\n\nREMAINING LIMITS\nModel calls: " + str(max(0, state["contract"]["max_calls"] - state["calls"]))
                    text += "\nTool calls: " + str(state.get("resource_status", {}).get("remaining_tool_calls", "Not recorded in this older run"))
                    text += "\nCollection continuation limit per task: " + str(state["contract"]["max_tool_rounds"])
                    if state.get("error"):
                        text += "\n\nSTOP REASON\n" + state["error"]
                else:
                    text = "Readiness appears at the start of a live run. Demo illustrates orchestration without live task assessment."
                self.write(self.document, text)
            else:
                text = "Run activity will appear here."
                if self.run_dir and (self.run_dir / "events.jsonl").exists():
                    lines = []
                    for raw in (self.run_dir / "events.jsonl").read_text(encoding="utf-8").splitlines():
                        try:
                            e = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        when = datetime.fromtimestamp(e["time"]).strftime("%H:%M:%S")
                        lines.append(f"{when}   {e['event'].replace('_', ' ').capitalize()}   {e.get('task', '')}")
                        if e.get("error"):
                            lines.append("    " + e["error"])
                        if e["event"] == "provider_rate_wait":
                            lines.append(f"    Provider rate limit: waiting {e['delay_seconds']} seconds before retry {e['retry']} of 3.")
                        if e.get("review", {}).get("issues"):
                            lines.extend("    • " + issue for issue in e["review"]["issues"])
                    text = "\n".join(lines)
                self.write(self.document, text)
        if self.selected:
            self.select_node(*self.selected)
        self.update_run_message()

    def draw_graph(self):
        c = self.canvas
        c.delete("all")
        if not self.snapshot:
            c.create_text(36, 48, text="Make room for a good idea.", fill=TEXT, anchor="nw", font=("Segoe UI", 23, "bold"))
            c.create_text(36, 102, text="Write your brief on the left, or load the example.\nYour task map will take shape here as the work unfolds.",
                          fill=MUTED, anchor="nw", font=("Segoe UI", 12), width=540)
            for i, (title, sub) in enumerate([("Plan", "Break the problem down"), ("Explore", "Work in parallel"), ("Review", "Check and improve")]):
                x = 36 + i * 185
                c.create_rectangle(x, 195, x + 164, 310, fill=CARD, outline=LINE)
                c.create_text(x + 16, 214, text=f"0{i + 1}", fill=ACCENT, anchor="nw", font=("Segoe UI", 10))
                c.create_text(x + 16, 240, text=title, fill=TEXT, anchor="nw", font=("Segoe UI", 16, "bold"))
                c.create_text(x + 16, 279, text=sub, fill=MUTED, anchor="nw", font=("Segoe UI", 9))
            c.configure(scrollregion=(0, 0, 610, 370))
            return
        if self.view == "Task map":
            nodes = self.snapshot["tasks"]
            positions = task_positions(nodes)
            for key, task in nodes.items():
                x, y = positions[key]
                for dep in task["deps"]:
                    dx, dy = positions[dep]
                    c.create_line(dx + 242, dy + 55, dx + 264, dy + 55, x - 22, y + 55, x, y + 55,
                                  fill=LINE, width=2, arrow="last", smooth=True)
            for key, task in nodes.items():
                self.card(key, positions[key], task["title"], task["status"].replace("_", " "),
                          COLORS.get(task["status"], MUTED), task["capability"].replace("_", " / "), "task")
            if len(nodes) == 1 and self.snapshot["state"] not in {"failed", "complete", "cancelled", "needs_resources", "stalled", "budget_exhausted"}:
                c.create_rectangle(330, 40, 590, 160, fill=PANEL, outline=BLUE, dash=(5, 4))
                c.create_text(348, 57, text="BUILDING THE PLAN", fill=BLUE, anchor="nw", font=("Segoe UI", 10, "bold"))
                c.create_text(348, 88, text="Identifying subtasks and dependencies…\nThis is a planning indicator, not a scheduled task.",
                              fill=MUTED, anchor="nw", width=220, font=("Segoe UI", 10))
        else:
            graph = graph_subset(self.snapshot, self.history.get())
            nodes = graph["nodes"]
            rows = {"evidence": 0, "claim": 0, "assumption": 0, "listing": 0}
            columns = {"evidence": 0, "claim": 1, "assumption": 2, "listing": 3}
            positions = {}
            for key, node in nodes.items():
                kind = node["kind"]
                positions[key] = (36 + columns[kind] * 292, 44 + rows[kind] * 156)
                rows[kind] += 1
            for e in graph["edges"]:
                x, y = positions[e["from"]]
                dx, dy = positions[e["to"]]
                c.create_line(x + 121, y + 55, dx + 121, dy + 55,
                              fill=RED if e["relation"] == "contradicts" else LINE, width=2, arrow="last")
            for key, node in nodes.items():
                kind = node["kind"]
                detail = f"{node['confidence']:.0%} reported confidence" if kind == "claim" else "Unverified source" if kind in {"evidence", "listing"} else "Explicit assumption"
                self.card(key, positions[key], node["text"], kind, {"claim": ACCENT, "evidence": BLUE, "assumption": GOLD, "listing": BLUE}[kind], detail, "reason")
            if not nodes:
                c.create_text(36, 48, text="Claims and evidence will appear as workers return results.", fill=MUTED, anchor="nw", font=("Segoe UI", 13))
        bounds = c.bbox("all")
        if bounds:
            c.configure(scrollregion=(0, 0, bounds[2] + 40, bounds[3] + 40))

    def card(self, key, position, title, status, color, detail, kind):
        x, y = position
        tag = "node_" + str(len(self.canvas.find_all()))
        self.canvas.create_rectangle(x, y, x + 242, y + 120, fill=CARD, outline=LINE, width=1, tags=tag)
        self.canvas.create_rectangle(x, y, x + 3, y + 120, fill=color, outline="", tags=tag)
        self.canvas.create_text(x + 16, y + 14, text="●  " + status.upper(), fill=color, anchor="nw", font=("Segoe UI", 9, "bold"), tags=tag)
        title = title if len(title) < 76 else title[:73] + "…"
        self.canvas.create_text(x + 16, y + 39, text=title, width=210, fill=TEXT, anchor="nw", font=("Segoe UI", 11, "bold"), tags=tag)
        self.canvas.create_text(x + 16, y + 99, text=detail, fill=MUTED, anchor="nw", font=("Segoe UI", 9), tags=tag)
        self.canvas.tag_bind(tag, "<Button-1>", lambda e: self.select_node(kind, key))
        self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.configure(cursor="hand2"))
        self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.configure(cursor=""))

    def select_node(self, kind, key):
        self.selected = (kind, key)
        if not self.snapshot:
            return
        if kind == "task":
            t = self.snapshot["tasks"].get(key)
            if not t:
                return
            text = f"{t['title']}\n{t['status'].upper()}  ·  {t['capability']}  ·  {key}\n"
            text += "Prerequisites: " + (", ".join(t["deps"]) or "None") + "\n"
            if t["output"]:
                text += "\n" + t["output"]["answer"]
            elif t["feedback"]:
                text += "\n" + "\n".join(t["feedback"])
        else:
            n = self.snapshot["reasoning"]["nodes"].get(key)
            if not n:
                return
            text = n["text"] + "\n\n" + f"{n['kind'].upper()} · task {n['task']}\n"
            if "source" in n:
                text += "Source: " + n["source"] + " (unverified)\n"
            if "confidence" in n:
                text += f"Reported confidence: {n['confidence']:.0%} · not calibrated\n"
            text += "Artifact: " + n["artifact"]
            if self.run_dir and n["artifact"].startswith("tool_"):
                # Only host-generated tool artifact names can be opened here.
                aid = n["artifact"]
                if aid[5:].isdigit():
                    path = self.run_dir / "artifacts" / (aid + ".json")
                    if path.exists():
                        text += "\n\nTool response:\n" + path.read_text(encoding="utf-8")
            for e in self.snapshot["reasoning"]["edges"]:
                if e["from"] == key:
                    target = self.snapshot["reasoning"]["nodes"][e["to"]]
                    text += "\n" + e["relation"].capitalize() + ": " + target["text"]
        self.write(self.detail, text)

    def open_run(self):
        if self.busy:
            messagebox.showinfo("Run in progress", "Wait for this run to finish or stop it first.")
            return
        filename = filedialog.askopenfilename(title="Open a run's state.json", initialdir=BASE, filetypes=[("Run snapshot", "*.json")])
        if not filename:
            return
        try:
            state = read_run(filename)
            if not {"tasks", "reasoning", "state", "calls"} <= state.keys() or "root" not in state["tasks"]:
                raise ValueError("Choose a state.json file from a Taskgraph run.")
            task_positions(state["tasks"])
            graph_subset(state)
            self.snapshot = state
            self.run_dir = Path(filename).parent
            self.selected = None
            self.change_view("Task map")
        except (OSError, ValueError, KeyError, TypeError) as exc:
            messagebox.showerror("Could not open run", str(exc))

    def copy_answer(self):
        result = display_result(self.snapshot, self.run_dir)
        if not result:
            messagebox.showinfo("No answer yet", "The final answer will be available after a successful run.")
            return
        self.clipboard_clear()
        self.clipboard_append(result["answer"])
        self.status.set("Partial result copied — incomplete" if result.get("is_partial") else "Answer copied")

    def copy_error(self):
        error = self.snapshot.get("error") if self.snapshot else None
        if not error:
            return
        self.clipboard_clear()
        self.clipboard_append(error)
        self.status.set("Error copied — paste it into your message")

    def open_library(self):
        if self.busy:
            messagebox.showinfo("Run in progress", "Library selections are fixed for this run. Edit them after the run finishes.")
            return
        if getattr(self, "library_window", None) and self.library_window.winfo_exists():
            self.library_window.lift()
        else:
            self.library_window = LibraryWindow(self)

    def edit_limits(self):
        if self.busy:
            messagebox.showinfo("Run in progress", "Limits are fixed for the current run. Edit them before starting the next run.")
            return
        dialog = tk.Toplevel(self)
        dialog.title("Run limits")
        dialog.configure(bg=PANEL)
        dialog.transient(self)
        dialog.grab_set()
        fields = [("max_tasks", "Total task nodes", "Includes the original task and repair tasks"),
                  ("max_calls", "Model calls", "Includes planning, reviews and tool follow-ups"),
                  ("parallelism", "Parallel workers", "Maximum tasks executing together"),
                  ("max_depth", "Decomposition depth", "0 makes the original task atomic"),
                  ("max_repairs", "Repair attempts", "0 disables critic-driven repairs"),
                  ("max_tool_calls", "MCP tool attempts", "Total attempts across the run"),
                  ("max_tool_rounds", "Tool / collection rounds", "Per-call tool exchanges and per-task collection continuations"),
                  ("timeout", "Worker-call timeout (seconds)", "Auto = 90 seconds, or 300 with MCP connections")]
        variables = {}
        for index, (key, title, help_text) in enumerate(fields):
            tk.Label(dialog, text=title, bg=PANEL, fg=TEXT, anchor="w").grid(row=index*2, column=0, sticky="w", padx=20, pady=(10, 0))
            tk.Label(dialog, text=help_text, bg=PANEL, fg=MUTED, anchor="w", font=("Segoe UI", 10)).grid(row=index*2+1, column=0, sticky="w", padx=20)
            variable = tk.StringVar(value=str(self.limit_values[key]))
            variables[key] = variable
            tk.Entry(dialog, textvariable=variable, bg=CARD, fg=TEXT, insertbackground=TEXT, width=12).grid(row=index*2, column=1, rowspan=2, padx=20)
        actions = tk.Frame(dialog, bg=PANEL)
        actions.grid(row=len(fields)*2, column=0, columnspan=2, sticky="ew", padx=20, pady=18)
        def reset():
            for key, variable in variables.items(): variable.set(str(DEFAULT_LIMITS[key]))
        def save():
            values = {k: v.get() for k, v in variables.items()}
            try:
                parse_limits(values, strategy="multi_step" if self.strategy.get() == "Multi-step" else "auto")
            except ValueError as exc:
                messagebox.showerror("Check limits", str(exc), parent=dialog)
                return
            self.limit_values = values
            self.limit_summary.set(f"{values['max_tasks']} tasks · {values['max_calls']} model calls")
            dialog.destroy()
        self.button(actions, "Restore defaults", reset).pack(side="left")
        self.button(actions, "Save limits", save, primary=True).pack(side="right")

    async def ask_tool_approval(self, record):
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self.messages.put(("approval", (record, loop, future)))
        try:
            return await asyncio.wait_for(future, 120)
        except asyncio.TimeoutError:
            return False

    def show_tool_approval(self, record, loop, future):
        if future.done(): return
        dialog = tk.Toplevel(self)
        dialog.title("Approve MCP tool call")
        dialog.geometry("700x470")
        dialog.configure(bg=PANEL)
        self.label(dialog, f"{record['connection']}  /  {record['tool']}", font=("Segoe UI", 15, "bold")).pack(fill="x", padx=20, pady=16)
        self.label(dialog, "This tool will receive the arguments below. Allow this one call?").pack(fill="x", padx=20)
        content = self.editor(dialog, 12)
        content.pack(fill="both", expand=True, padx=20, pady=12)
        self.write(content, "Task: " + record["task"] + "\n\n" + json.dumps(record["arguments"], indent=2))
        def decide(allowed):
            def resolve():
                if not future.done(): future.set_result(allowed)
            if not loop.is_closed(): loop.call_soon_threadsafe(resolve)
            dialog.destroy()
        row = tk.Frame(dialog, bg=PANEL)
        row.pack(fill="x", padx=20, pady=12)
        self.button(row, "Deny", lambda: decide(False)).pack(side="right")
        self.button(row, "Allow once", lambda: decide(True), primary=True).pack(side="right", padx=8)
        dialog.protocol("WM_DELETE_WINDOW", lambda: decide(False))
        def expired():
            if not dialog.winfo_exists(): return
            if future.done(): dialog.destroy()
            else: dialog.after(250, expired)
        dialog.after(250, expired)

    def close(self):
        if self.busy and not messagebox.askyesno("Close Taskgraph?", "A run is in progress. Stop it and close? An API request already sent may still be charged."):
            return
        if self.busy:
            self.stop()
        self.destroy()


if __name__ == "__main__":
    Studio().mainloop()
