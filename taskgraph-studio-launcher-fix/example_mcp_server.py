"""A harmless local MCP server for testing Taskgraph's tool connection."""
import json
import sys

TOOL = {"name": "search_notes", "description": "Search the bundled Taskgraph sample notes. This is a demonstration, not current banking research.",
        "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"], "additionalProperties": False}}
NOTES = ["Taskgraph supports reusable knowledge and per-task MCP tools.",
         "Regional-bank company ideas need customer interviews, source evidence and feasibility checks. This is a sample note, not verified research."]

def respond(request):
    method = request["method"]
    if method == "initialize":
        return {"protocolVersion": "2025-11-25", "capabilities": {"tools": {}}, "serverInfo": {"name": "Taskgraph sample notes", "version": "1.0"}}
    if method == "tools/list": return {"tools": [TOOL]}
    if method == "tools/call":
        if request["params"]["name"] != "search_notes": raise ValueError("Unknown tool")
        query = request["params"]["arguments"]["query"].lower()
        matches = [n for n in NOTES if any(word in n.lower() for word in query.split())]
        return {"content": [{"type": "text", "text": json.dumps({"source": "bundled demo notes", "matches": matches})}], "isError": False}
    raise ValueError("Unsupported method")

if __name__ == "__main__":
    for line in sys.stdin:
        request = json.loads(line)
        if "id" not in request: continue
        try:
            response = {"jsonrpc": "2.0", "id": request["id"], "result": respond(request)}
        except Exception:
            response = {"jsonrpc": "2.0", "id": request["id"], "error": {"code": -32602, "message": "Invalid sample request"}}
        print(json.dumps(response), flush=True)
