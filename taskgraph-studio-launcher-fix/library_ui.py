"""Library management dialog. Every saved connection remains task-opt-in."""
import copy
import json
import queue
import threading
import sys
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from pathlib import Path
from mcp_client import MCPClient, fingerprint


class LibraryWindow(tk.Toplevel):
    def __init__(self, studio):
        super().__init__(studio)
        self.studio, self.library = studio, studio.library
        self.title("Library · Taskgraph")
        self.geometry("1040x780")
        self.minsize(860, 660)
        self.configure(bg="#181d28")
        self.tasks = queue.Queue()
        self.current_k = self.current_c = None
        self.testing = False
        tabs = ttk.Notebook(self)
        tabs.pack(fill="both", expand=True, padx=16, pady=16)
        self.pages = {}
        for name in ("Knowledge", "MCP connections", "Use for this task"):
            frame = tk.Frame(tabs, bg="#181d28", padx=12, pady=12)
            tabs.add(frame, text=name)
            self.pages[name] = frame
        self._knowledge()
        self._connections()
        self._selection()
        tabs.bind("<<NotebookTabChanged>>", lambda e: self.refresh_selection())
        self.refresh_lists()
        self.after(100, self.poll)

    def label(self, parent, text):
        tk.Label(parent, text=text, bg="#181d28", fg="#edf2fc", anchor="w", justify="left", wraplength=650).pack(fill="x", pady=(7, 3))

    def entry(self, parent, label, secret=False):
        self.label(parent, label)
        variable = tk.StringVar()
        tk.Entry(parent, textvariable=variable, show="•" if secret else "", bg="#202735", fg="#edf2fc",
                 insertbackground="white", relief="flat").pack(fill="x", ipady=5)
        return variable

    def buttons(self, parent, actions):
        row = tk.Frame(parent, bg="#181d28")
        row.pack(fill="x", pady=8)
        for title, action in actions:
            self.studio.button(row, title, action).pack(side="left", padx=(0, 5))

    def split(self, parent, scroll=False):
        left = tk.Frame(parent, bg="#181d28", width=230)
        left.pack(side="left", fill="y", padx=(0, 16))
        listing = tk.Listbox(left, bg="#202735", fg="#edf2fc", selectbackground="#395775", exportselection=False, width=24)
        listing.pack(fill="both", expand=True)
        right = tk.Frame(parent, bg="#181d28")
        right.pack(side="left", fill="both", expand=True)
        if scroll:
            canvas = tk.Canvas(right, bg="#181d28", highlightthickness=0)
            bar = ttk.Scrollbar(right, orient="vertical", command=canvas.yview)
            bar.pack(side="right", fill="y")
            canvas.pack(fill="both", expand=True)
            canvas.configure(yscrollcommand=bar.set)
            content = tk.Frame(canvas, bg="#181d28")
            window = canvas.create_window((0, 0), window=content, anchor="nw")
            content.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.bind("<Configure>", lambda e: canvas.itemconfigure(window, width=e.width))
            right = content
        return listing, right

    def _knowledge(self):
        self.klist, panel = self.split(self.pages["Knowledge"])
        self.klist.bind("<<ListboxSelect>>", self.load_knowledge)
        self.kn = self.entry(panel, "Name")
        self.ks = self.entry(panel, "Source / reference URL (a citation; URLs are not fetched automatically)")
        self.label(panel, "Notes or source text — selected content is supplied to the model")
        self.kt = self.studio.editor(panel, 14)
        self.kt.pack(fill="both", expand=True)
        self.buttons(panel, [("New", self.new_knowledge), ("Import text file", self.import_text), ("Save", self.save_knowledge), ("Delete", lambda: self.delete("knowledge"))])

    def _connections(self):
        self.clist, panel = self.split(self.pages["MCP connections"], scroll=True)
        self.clist.bind("<<ListboxSelect>>", self.load_connection)
        self.cn = self.entry(panel, "Connection name")
        self.cd = self.entry(panel, "Brief description — when should workers use this connection?")
        self.transport = tk.StringVar(value="http")
        self.label(panel, "Transport · http = remote Streamable HTTP; stdio = local program")
        ttk.Combobox(panel, textvariable=self.transport, values=["http", "stdio"], state="readonly").pack(fill="x")
        self.endpoint = self.entry(panel, "HTTPS endpoint, or local executable path")
        self.arguments = self.entry(panel, 'Local arguments as JSON · example: ["server.py"]')
        self.cwd = self.entry(panel, "Local working directory · optional")
        self.credential = self.entry(panel, "Bearer token (remote) or secret environment JSON (local) · blank keeps saved value", True)
        self.remember = tk.BooleanVar(value=False)
        tk.Checkbutton(panel, text="Remember credential using Windows encryption", variable=self.remember,
                       bg="#181d28", fg="#edf2fc", selectcolor="#202735", activebackground="#181d28").pack(anchor="w")
        self.buttons(panel, [("Clear saved credential", self.clear_credential)])
        self.label(panel, "Local servers run as your Windows user. Use trusted programs. Credentials stay in this session unless Remember is checked. Testing discovers tools; it does not call them.")
        self.buttons(panel, [("New", self.new_connection), ("Save", self.save_connection), ("Test connection", self.test_connection), ("Sample", self.sample_connection), ("Delete", lambda: self.delete("connections"))])
        self.test_status = tk.StringVar(value="Save and test a connection to discover its tools.")
        tk.Label(panel, textvariable=self.test_status, bg="#181d28", fg="#a0f2cf", wraplength=640, justify="left", anchor="w").pack(fill="x")
        self.tools = tk.Listbox(panel, bg="#202735", fg="#edf2fc", selectbackground="#395775", exportselection=False, height=6)
        self.tools.pack(fill="both", expand=True, pady=8)
        self.tools.bind("<<ListboxSelect>>", self.tool_detail)
        self.tool_text = tk.StringVar(value="Select a tool to inspect its description.")
        tk.Label(panel, textvariable=self.tool_text, bg="#181d28", fg="#edf2fc", wraplength=640, justify="left", anchor="w").pack(fill="x")
        self.buttons(panel, [("Allow · ask each time", lambda: self.policy(True, False)),
                             ("Allow automatically", lambda: self.policy(True, True)), ("Disable", lambda: self.policy(False, False))])

    def _selection(self):
        panel = self.pages["Use for this task"]
        self.label(panel, "Select the knowledge and connections this task may use. Hold Ctrl to select multiple items. Nothing is selected automatically for a new app session.")
        self.label(panel, "Knowledge")
        self.selected_k = tk.Listbox(panel, selectmode="multiple", exportselection=False, bg="#202735", fg="#edf2fc", selectbackground="#395775", height=10)
        self.selected_k.pack(fill="both", expand=True)
        self.label(panel, "Connections · only tools you explicitly allowed can be called")
        self.selected_c = tk.Listbox(panel, selectmode="multiple", exportselection=False, bg="#202735", fg="#edf2fc", selectbackground="#395775", height=8)
        self.selected_c.pack(fill="both", expand=True)
        self.buttons(panel, [("Use selected items", self.apply_selection)])

    def refresh_lists(self):
        for widget, category in ((self.klist, "knowledge"), (self.clist, "connections")):
            widget.delete(0, "end")
            for row in self.library.data[category]:
                widget.insert("end", row["name"])
        self.refresh_selection()

    def refresh_selection(self):
        for widget, category, selected in ((self.selected_k, "knowledge", self.studio.selected_knowledge), (self.selected_c, "connections", self.studio.selected_connections)):
            widget.delete(0, "end")
            for i, row in enumerate(self.library.data[category]):
                widget.insert("end", row["name"])
                if row["id"] in selected:
                    widget.selection_set(i)

    def apply_selection(self):
        self.studio.selected_knowledge = {self.library.data["knowledge"][i]["id"] for i in self.selected_k.curselection()}
        self.studio.selected_connections = {self.library.data["connections"][i]["id"] for i in self.selected_c.curselection()}
        self.studio.library_status.set(f"{len(self.studio.selected_knowledge)} knowledge items · {len(self.studio.selected_connections)} connections selected")
        self.destroy()

    def new_knowledge(self):
        self.current_k = None
        self.kn.set(""); self.ks.set("")
        self.kt.delete("1.0", "end")

    def load_knowledge(self, event=None):
        if not self.klist.curselection(): return
        row = self.library.data["knowledge"][self.klist.curselection()[0]]
        self.current_k = row["id"]
        self.kn.set(row["name"]); self.ks.set(row.get("source", ""))
        self.kt.delete("1.0", "end"); self.kt.insert("1.0", row["text"])

    def save_knowledge(self):
        if not self.kn.get().strip() or not self.studio.value(self.kt):
            messagebox.showerror("Missing content", "Enter a name and some source text.", parent=self); return
        row = {"name": self.kn.get().strip(), "source": self.ks.get().strip(), "text": self.studio.value(self.kt)}
        if self.current_k: row["id"] = self.current_k
        self.current_k = self.library.put("knowledge", row)["id"]
        self.refresh_lists()

    def import_text(self):
        name = filedialog.askopenfilename(parent=self, filetypes=[("Text sources", "*.txt *.md *.csv *.json *.tsv")])
        if not name: return
        try:
            path = Path(name)
            if path.stat().st_size > 500000:
                raise ValueError("Choose a file smaller than 500 KB or paste an excerpt.")
            text = path.read_text(encoding="utf-8-sig")
            self.new_knowledge(); self.kn.set(path.stem); self.ks.set(str(path))
            self.kt.insert("1.0", text)
        except (OSError, ValueError) as exc:
            messagebox.showerror("Could not import", str(exc), parent=self)

    def connection(self):
        return next((r for r in self.library.data["connections"] if r["id"] == self.current_c), None)

    def new_connection(self):
        self.current_c = None
        for variable in (self.cn, self.cd, self.endpoint, self.credential, self.cwd): variable.set("")
        self.arguments.set("[]"); self.transport.set("http")
        self.tools.delete(0, "end")

    def sample_connection(self):
        self.new_connection()
        self.cn.set("Sample notes")
        self.cd.set("Search bundled demonstration notes to try an MCP connection.")
        self.transport.set("stdio")
        executable = Path(sys.executable)
        if executable.name.lower() == "pythonw.exe": executable = executable.with_name("python.exe")
        self.endpoint.set(str(executable))
        self.arguments.set(json.dumps([str(Path(__file__).with_name("example_mcp_server.py"))]))
        self.test_status.set("Click Test connection, then allow search_notes to try the sample.")

    def load_connection(self, event=None):
        if not self.clist.curselection(): return
        row = self.library.data["connections"][self.clist.curselection()[0]]
        self.current_c = row["id"]
        self.cn.set(row["name"]); self.cd.set(row["description"]); self.transport.set(row["transport"])
        self.endpoint.set(row.get("url") if row["transport"] == "http" else row.get("command"))
        self.arguments.set(json.dumps(row.get("args", []))); self.credential.set("")
        self.cwd.set(row.get("cwd", ""))
        self.show_tools()

    def save_connection(self):
        try:
            if not self.cn.get().strip() or not self.endpoint.get().strip():
                raise ValueError("Enter a name and endpoint or program path.")
            args = json.loads(self.arguments.get() or "[]")
            if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError("Arguments must be a JSON list of strings.")
            secret = self.credential.get()
            if secret and self.transport.get() == "stdio":
                env = json.loads(secret)
                if not isinstance(env, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in env.items()):
                    raise ValueError("Local credentials must be a JSON object of environment variable names and values.")
            old = self.connection() or {}
            row = {"name": self.cn.get().strip(), "description": self.cd.get().strip(), "transport": self.transport.get(),
                   "url": self.endpoint.get().strip() if self.transport.get() == "http" else "",
                   "command": self.endpoint.get().strip() if self.transport.get() == "stdio" else "", "args": args,
                   "cwd": self.cwd.get().strip()}
            if self.current_c: row["id"] = self.current_c
            if all(row[k] == old.get(k) for k in ("transport", "url", "command", "args", "cwd")) and not secret:
                row.update({"tools": old.get("tools", []), "policies": old.get("policies", {})})
            row = self.library.put("connections", row)
            self.current_c = row["id"]
            if old.get("transport") and old["transport"] != row["transport"]:
                self.library.clear_secret(self.current_c)
            if secret: self.library.secret(self.current_c, secret, persist=self.remember.get())
            self.credential.set("")
            self.refresh_lists(); self.show_tools()
            return row
        except (ValueError, OSError) as exc:
            messagebox.showerror("Could not save", str(exc), parent=self)

    def clear_credential(self):
        if self.current_c:
            self.library.clear_secret(self.current_c)
            self.credential.set("")
            self.test_status.set("Saved credential cleared.")

    def test_connection(self):
        if self.testing: return
        row = self.save_connection()
        if not row: return
        self.testing = True
        self.test_status.set("Connecting and discovering tools…")
        def work():
            client = None
            try:
                client = MCPClient(row, self.library.secret(row["id"]))
                client.connect()
                self.tasks.put((row, client.tools(), None))
            except Exception as exc:
                self.tasks.put((row, None, str(exc)))
            finally:
                if client: client.close()
        threading.Thread(target=work, daemon=True).start()

    def poll(self):
        try:
            row, tools, error = self.tasks.get_nowait()
            self.testing = False
            if error:
                self.test_status.set(error)
            else:
                # Ignore stale discovery if user edited/deleted the connection.
                existing = next((r for r in self.library.data["connections"] if r["id"] == row["id"]), None)
                if existing != row:
                    self.test_status.set("Connection changed during discovery. Test it again.")
                else:
                    row = copy.deepcopy(row)
                    policies = row.get("policies", {})
                    row["tools"] = tools
                    row["policies"] = {t["name"]: policies.get(t["name"], {}) if policies.get(t["name"], {}).get("fingerprint") == fingerprint(t)
                        else {"enabled": False, "automatic": False, "fingerprint": fingerprint(t)} for t in tools}
                    self.library.put("connections", row)
                    self.test_status.set(f"Connected. {len(tools)} tools discovered. Choose which tools to allow below.")
                    self.show_tools()
        except queue.Empty:
            pass
        self.after(100, self.poll)

    def show_tools(self):
        self.tools.delete(0, "end")
        row = self.connection() or {}
        for tool in row.get("tools", []):
            policy = row.get("policies", {}).get(tool["name"], {})
            mode = "AUTO" if policy.get("automatic") and policy.get("enabled") else "ASK" if policy.get("enabled") else "OFF"
            self.tools.insert("end", f"[{mode}] {tool['name']}")

    def tool_detail(self, event=None):
        row = self.connection()
        if row and self.tools.curselection():
            tool = row["tools"][self.tools.curselection()[0]]
            self.tool_text.set(tool.get("description", tool["name"])[:700])

    def policy(self, enabled, automatic):
        row = self.connection()
        if not row or not self.tools.curselection(): return
        tool = row["tools"][self.tools.curselection()[0]]
        if automatic and not messagebox.askyesno("Allow automatic calls?", f"Allow {tool['name']} without asking each time? Only choose this for operations you trust to run automatically. Server read-only hints are not guarantees.", parent=self): return
        row = copy.deepcopy(row)
        row.setdefault("policies", {})[tool["name"]] = {"enabled": enabled, "automatic": automatic, "fingerprint": fingerprint(tool)}
        self.library.put("connections", row); self.show_tools()

    def delete(self, category):
        cid = self.current_k if category == "knowledge" else self.current_c
        if cid and messagebox.askyesno("Delete library item?", "Remove this saved item? Existing run snapshots will be kept.", parent=self):
            self.library.remove(category, cid)
            self.new_knowledge() if category == "knowledge" else self.new_connection()
            self.refresh_lists()
