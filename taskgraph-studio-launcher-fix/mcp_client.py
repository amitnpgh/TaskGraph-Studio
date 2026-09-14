"""Bounded MCP tools client: stdio and Streamable HTTP (2025-03/06/11)."""
import asyncio
import hashlib
import json
import os
import queue
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

MAX_BYTES = 2_000_000
VERSIONS = {"2025-03-26", "2025-06-18", "2025-11-25"}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("MCP endpoint redirected. Save the final trusted URL instead.")


def fingerprint(tool):
    return hashlib.sha256(json.dumps(tool, sort_keys=True).encode()).hexdigest()


class MCPClient:
    def __init__(self, config, token="", timeout=30):
        self.config, self.token, self.timeout = config, token, timeout
        self.process = None
        self.session = None
        self.version = "2025-11-25"
        self.seq = 0
        self.lock = threading.Lock()
        self.inbox = queue.Queue()

    def connect(self):
        if self.config["transport"] == "stdio":
            command = self.config.get("command", "")
            args = self.config.get("args", [])
            if not command or not isinstance(args, list) or not all(isinstance(a, str) for a in args):
                raise ValueError("Supply a program and a JSON array of arguments.")
            # A configured server is trusted local software, not a sandbox.
            # Avoid inheriting application API credentials into its environment.
            keep = {"PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE", "HOME", "APPDATA", "LOCALAPPDATA"}
            env = {k: v for k, v in os.environ.items() if k.upper() in keep}
            env.update(self.config.get("env", {}))
            if self.token:
                env.update(json.loads(self.token))
            self.process = subprocess.Popen([command, *args], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, env=env, shell=False, cwd=self.config.get("cwd") or None,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            def reader():
                try:
                    while True:
                        line = self.process.stdout.readline(MAX_BYTES + 1)
                        if not line or len(line) > MAX_BYTES:
                            self.inbox.put(ValueError("MCP process exited or returned an oversized message"))
                            return
                        self.inbox.put(json.loads(line))
                except Exception:
                    self.inbox.put(ValueError("MCP server returned invalid protocol data"))
            threading.Thread(target=reader, daemon=True).start()
        else:
            url = urllib.parse.urlsplit(self.config.get("url", ""))
            if url.username or url.password or url.fragment:
                raise ValueError("Keep credentials in the credential field, not in the URL.")
            if url.scheme != "https" and not (url.scheme == "http" and url.hostname in {"localhost", "127.0.0.1", "::1"}):
                raise ValueError("Remote MCP requires HTTPS. HTTP is supported for localhost only.")
        try:
            result = self.rpc("initialize", {"protocolVersion": self.version, "capabilities": {},
                "clientInfo": {"name": "Taskgraph Studio", "version": "1.1"}})
            if result.get("protocolVersion") not in VERSIONS:
                raise ValueError("This client supports MCP 2025-03-26, 2025-06-18 and 2025-11-25. Use a compatible endpoint.")
            self.version = result["protocolVersion"]
            self.rpc("notifications/initialized", {}, notify=True)
            return self
        except Exception:
            self.close()
            raise

    def _http(self, message):
        headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                   "MCP-Protocol-Version": self.version}
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        request = urllib.request.Request(self.config["url"], data=json.dumps(message).encode(), headers=headers)
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=self.timeout) as response:
                if response.headers.get("Mcp-Session-Id"):
                    self.session = response.headers["Mcp-Session-Id"]
                if "id" not in message:
                    return None
                if "text/event-stream" not in response.headers.get("Content-Type", ""):
                    raw = response.read(MAX_BYTES + 1)
                    if len(raw) > MAX_BYTES:
                        raise ValueError("MCP response exceeds 2 MB")
                    return json.loads(raw)
                data, total, deadline = [], 0, time.monotonic() + self.timeout
                while time.monotonic() < deadline:
                    raw = response.readline(MAX_BYTES + 1)
                    total += len(raw)
                    if total > MAX_BYTES:
                        raise ValueError("MCP stream exceeds 2 MB")
                    if not raw:
                        raise ValueError("MCP stream closed before returning a result; the tool is not retried automatically")
                    line = raw.decode("utf-8").rstrip("\r\n")
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip())
                    elif not line and data:
                        text = "\n".join(data)
                        data = []
                        if not text:
                            continue
                        event = json.loads(text)
                        if event.get("id") == message["id"] and "method" not in event:
                            return event
                        if "method" in event and "id" in event:
                            raise ValueError("This server requested a client capability that Taskgraph does not support")
                raise TimeoutError("MCP stream timed out")
        except urllib.error.HTTPError as exc:
            raise ValueError(f"MCP returned HTTP {exc.code}. Check the endpoint, authentication and server compatibility.") from None

    def rpc(self, method, params, notify=False):
        with self.lock:
            self.seq += 1
            message = {"jsonrpc": "2.0", "method": method, "params": params}
            if not notify:
                message["id"] = self.seq
            if self.process:
                self.process.stdin.write((json.dumps(message) + "\n").encode())
                self.process.stdin.flush()
                if notify:
                    return None
                deadline = time.monotonic() + self.timeout
                while True:
                    try:
                        result = self.inbox.get(timeout=max(.01, deadline - time.monotonic()))
                    except queue.Empty:
                        self.close()
                        raise TimeoutError("MCP server timed out; the tool is not retried automatically") from None
                    if isinstance(result, Exception):
                        raise result
                    if "method" in result and "id" in result:
                        rejection = {"jsonrpc": "2.0", "id": result["id"], "error": {"code": -32601, "message": "Client capability not supported"}}
                        self.process.stdin.write((json.dumps(rejection) + "\n").encode())
                        self.process.stdin.flush()
                    elif result.get("id") == message["id"]:
                        break
                    if time.monotonic() >= deadline:
                        raise TimeoutError("MCP response timed out")
            else:
                result = self._http(message)
                if notify:
                    return None
            if not isinstance(result, dict) or result.get("id") != message["id"]:
                raise ValueError("MCP response ID mismatch")
            if "error" in result:
                raise ValueError(f"MCP rejected {method} (RPC error {result['error'].get('code')})")
            if not isinstance(result.get("result"), dict):
                raise ValueError("Invalid MCP result")
            return result["result"]

    def tools(self):
        found, cursor, seen = [], None, set()
        for _ in range(20):
            result = self.rpc("tools/list", {"cursor": cursor} if cursor else {})
            for tool in result.get("tools", []):
                if not isinstance(tool.get("name"), str) or not tool["name"] or tool["name"] in seen or not isinstance(tool.get("inputSchema"), dict) or tool["inputSchema"].get("type") != "object":
                    raise ValueError("Invalid or duplicate tool definition")
                seen.add(tool["name"])
                found.append(tool)
            cursor = result.get("nextCursor")
            if not cursor:
                return found
        raise ValueError("Too many MCP discovery pages")

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.terminate()
                try:
                    self.process.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    self.process.kill()
                    self.process.wait(timeout=2)
            for stream in (self.process.stdin, self.process.stdout):
                if stream:
                    stream.close()


class ToolBroker:
    """Only explicitly selected connections and user-enabled tools are callable."""
    def __init__(self, library, selected, approve, audit, max_calls=24):
        self.library, self.selected = library, set(selected)
        self.approve, self.audit = approve, audit
        self.max_calls, self.calls = max_calls, 0
        self.clients, self.routes = [], {}
        self.secrets = []
        self.denied = set()

    async def connect(self):
        try:
            for connection in self.library.data["connections"]:
                if connection["id"] not in self.selected:
                    continue
                secret = self.library.secret(connection["id"])
                if secret:
                    self.secrets.extend(json.loads(secret).values() if connection["transport"] == "stdio" else [secret])
                client = MCPClient(connection, secret)
                self.clients.append(client)
                await asyncio.to_thread(client.connect)
                actual = await asyncio.to_thread(client.tools)
                missing = {name for name, policy in connection.get("policies", {}).items() if policy.get("enabled")} - {t["name"] for t in actual}
                if missing:
                    raise ValueError(f"An allowed tool disappeared from {connection['name']}. Test the connection and review it again.")
                for tool in actual:
                    policy = connection.get("policies", {}).get(tool["name"], {})
                    if not policy.get("enabled"):
                        continue
                    if policy.get("fingerprint") != fingerprint(tool):
                        raise ValueError(f"Tools changed on {connection['name']}. Test the connection and review permissions again.")
                    alias = "mcp_" + hashlib.sha256((connection["id"] + ":" + tool["name"]).encode()).hexdigest()[:24]
                    self.routes[alias] = (client, connection, tool, policy)
            if self.selected and not self.routes:
                raise ValueError("No allowed tools on the selected connections. Open Library, test the connections and allow at least one tool.")
        except BaseException:
            self.close()
            raise

    def definitions(self):
        return [{"type": "function", "name": alias, "description": f"{c['name']}: {c['description']}\n{t.get('description', t['name'])}"[:4000],
                 "parameters": t["inputSchema"], "strict": False} for alias, (_, c, t, _) in self.routes.items()]

    async def invoke(self, alias, arguments, task):
        if alias not in self.routes:
            raise ValueError("Tool is not enabled for this task")
        if not isinstance(arguments, dict):
            raise ValueError("Tool arguments must be an object")
        if self.calls >= self.max_calls:
            raise ValueError("Tool-call limit reached for this run")
        self.calls += 1
        client, connection, tool, policy = self.routes[alias]
        if not policy.get("enabled"):
            raise ValueError("Tool is disabled")
        request_key = (task, alias, json.dumps(arguments, sort_keys=True))
        if request_key in self.denied:
            return {"isError": True, "content": [{"type": "text", "text": "This call was denied earlier. It cannot be retried in this task."}]}
        def scrub(value):
            if isinstance(value, str):
                for secret in self.secrets:
                    if secret: value = value.replace(secret, "[credential redacted]")
                return value
            if isinstance(value, list): return [scrub(v) for v in value]
            if isinstance(value, dict): return {k: scrub(v) for k, v in value.items()}
            return value
        record = {"task": task, "connection": connection["name"], "tool": tool["name"], "arguments": scrub(arguments)}
        # Server annotations are descriptive only, never permission grants.
        if not policy.get("automatic", False):
            self.audit("tool_approval_requested", record)
            allowed = await self.approve(record)
            if not allowed:
                self.denied.add(request_key)
                self.audit("tool_denied", record)
                return {"isError": True, "content": [{"type": "text", "text": "User denied this call. Do not retry it."}]}
        self.audit("tool_started", record)
        try:
            result = await asyncio.to_thread(client.rpc, "tools/call", {"name": tool["name"], "arguments": arguments})
        except Exception:
            self.audit("tool_failed", {**record, "error": "MCP call failed; not retried automatically"})
            raise
        source = self.audit("tool_completed", {**record, "result": scrub(result)})
        return {"source": source, "result": scrub(result)}

    def close(self):
        for client in self.clients:
            client.close()
