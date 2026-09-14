# Knowledge and MCP Library

Close and reopen Taskgraph to load the new **Library** button. No terminal is needed.

## Add knowledge

1. Open **Library → Knowledge → New**.
2. Enter a name, optional source URL/path, and the actual notes or source text.
3. Or choose **Import text file** for UTF-8 TXT, Markdown, CSV, TSV or JSON.
4. Click **Save**. Then open **Use for this task**, select the items and click
   **Use selected items**.

Selected text is copied into the task context with its title, source and saved date.
The run retains that snapshot even if you later edit the library. References are
citations, not automatic downloads: a URL alone does not fetch a page. PDF/Word
parsing, embeddings and semantic search are not included. Imports are limited to
500 KB and selected context to 120,000 characters; use excerpts for larger sources.

## Add an MCP connection

1. Open **Library → MCP connections → New**.
2. Enter a name and brief description of when the connection is useful.
3. Choose **http** for a remote Streamable HTTP endpoint, or **stdio** for a local
   executable. For remote connections enter the full HTTPS MCP endpoint, not a
   website homepage. Localhost may use HTTP.
4. For a local server, enter the executable path and arguments as a JSON list,
   such as `["C:\\tools\\my_server.py"]`. Supply a program, not a shell command.
   Set the optional working directory if the server needs relative files.
5. Enter a bearer token for a remote server, if needed. For a local server, the
   credential field accepts secret environment variables as a JSON object, e.g.
   `{"SERVICE_API_KEY":"your-token"}`. Keep secrets out of URLs and arguments.
6. Credentials stay in memory by default. Select **Remember credential using
   Windows encryption** to protect them with DPAPI for the current Windows user.
   Blank credential fields preserve the current credential. **Clear saved
   credential** removes it. There is no plaintext fallback if Windows protection
   is unavailable. Credentials cannot be moved to another user/computer by copying
   the encrypted file; enter them again there.
7. Click **Test connection**. This starts a local server or contacts the remote
   endpoint, performs the MCP handshake and discovers its actual tools. It does
   not invoke those tools. Local server startup itself runs the configured program.
8. Select each tool and choose **Allow · ask each time**, **Allow automatically**,
   or **Disable**. New or changed tools default to disabled. Do not treat a server's
   read-only annotation as proof that it cannot change data.
9. Open **Use for this task**, select the connection and click **Use selected items**.
10. Choose **OpenAI** or **Claude** in the main window and start the task. Demo mode uses selected
    knowledge but deliberately does not connect to or invoke external tools.

For a no-account discovery test, click **Sample**, then **Test connection**. This
starts the bundled `example_mcp_server.py` with one harmless `search_notes` tool.
Allow it and select that connection for a live run to ask the model to search
the sample notes. The sample is not current or verified banking research.

## During a run

Only selected connections are opened. Each selected server's current definitions
are compared with the tested definitions; changed tools require renewed review.
Planner inputs describe the available tools. General, Research and Code/Data roles
can invoke them; the planner, judge and critic do not execute tools themselves.
The model chooses relevant tools from this allowed set. Availability does not
guarantee that the model will call a tool: ask for the desired source explicitly.

Tools marked **ask each time** show the connection, tool, task and exact arguments.
**Allow once** authorizes that call; **Deny**, closing the dialog, or its 120-second
timeout denies it. A denied call cannot be retried with the same arguments within
that task. Automatic tools run without a prompt only after your explicit setting.

Activity records tool starts, approvals and results. Completed calls are retained
under `artifacts/tool_*.json`, with tool name, arguments and returned content.
They also appear as evidence nodes; select a node to read its full artifact.
Returned data is supplied to the model with its artifact source ID. Credential
values configured for the connection are redacted from logs and model-bound
results. Other data returned by a server may be sensitive: run files are local
plaintext. Confidence behavior is unchanged; tool retrieval is not truth verification.

## Limits and compatibility

* Implements tools/list and tools/call over MCP **2025-03-26, 2025-06-18 and
  2025-11-25** stdio/Streamable HTTP. Remote responses may use JSON or SSE.
* Requires a compatible endpoint; the newer stateless MCP 2026 protocol,
  legacy two-endpoint HTTP+SSE, OAuth sign-in, MCP resource browsing, prompts,
  sampling, elicitation and durable task extensions are not implemented.
* Bearer-token or unauthenticated remote access is supported. Redirects are
  rejected to avoid forwarding credentials; save the final trusted URL instead.
* Remote requests are not retried or resumed automatically. An interrupted call
  may have already changed external state. Verify that state before rerunning.
* There are at most 24 tool attempts per run and eight model/tool rounds per
  worker call. Additional model requests count toward the existing model-call
  limit. Runs with selected connections use a 300-second worker-call timeout.
* Tool results are capped at 2 MB. Model-bound results above 60,000 characters
  are explicitly truncated while the full result remains in the local artifact.
* Connection calls are serialized per server. New connections are not enabled
  automatically. Selections are explicit and held for this app session; inspect
  them before starting another task. Library editing is locked out during runs.

## Files and extension points

`library/catalog.json` stores knowledge, connection descriptions, tested tool
definitions and permissions. Credentials are separate `library/<id>.secret`
DPAPI blobs when remembering is selected. Session credentials never enter files.
`library-selection.json` in each run identifies its selected resources without
credentials or connection addresses. The distribution ZIP excludes your library
and personal runs.

`MCPClient` owns transport; `ToolBroker` owns selection, policy and audit;
`Library` owns persistence; `LibraryWindow` owns setup. The OpenAI adapter bridges
MCP definitions to Responses function calls; the Claude adapter bridges them to
Messages tool-use blocks. Both use the same broker and final-output validation.
The [MCP transport specification](https://modelcontextprotocol.io/specification/2025-11-25/basic/transports)
and [OpenAI function-calling guide](https://developers.openai.com/api/docs/guides/function-calling)
are the protocol references.

Validation includes a real local stdio server, simulated HTTP/SSE, encrypted-secret
handling, selection isolation, denied calls, definition changes, result provenance,
and a simulated OpenAI function-call round trip. The DPAPI integration test cannot
run under this restricted test account (Windows error 2) and is explicitly skipped;
session-only storage is tested. No credentialed third-party server or live OpenAI
call was used for these tests. The desktop dialog has not been visually verified.
