# Taskgraph V1

## Incomplete collections

The Answer tab and Copy answer now expose saved root partial artifacts with an explicit incomplete/unaccepted label, including older runs opened in the updated app. They are never promoted to accepted answers. Collection-round exhaustion takes precedence over stagnation when both happen on the last allowed round, and the message reports the collected count plus remaining model/tool budgets. **Run limits → Tool / collection rounds** controls the existing shared round setting (default 8); other budgets remain separate. During a no-progress approach-change step, the host can make a bounded internet query excluding up to three previously used source domains, rather than relying only on a request to change approach. This still consumes existing search/model budgets and does not guarantee more qualifying results. Defaults are unchanged.

## Reasoning reference resolution

Workers sometimes cite saved source IDs directly where local evidence IDs were expected. `reasoning_refs.py` now resolves unambiguous declared source aliases and imports explicit references to existing tool artifacts. It does not guess which individual fact within a multi-item artifact supports a claim. Unknown evidence, contradiction or opaque assumption targets are preserved in `unresolved_references`, limitations and the original/resolved diagnostic artifact, while being excluded from graph edges. Missing assumption declarations containing statement text are copied verbatim from claims into the central assumptions list, with an audit note. They remain model-provided assumptions, not verified facts. Short or ID-like labels are not interpreted. A generic final candidate with unresolved references cannot be accepted merely because the critic overlooks them. Job-batch row review still independently checks each listing. Claim text and self-reported confidence are unchanged. Structural schema errors retain the existing bounded correction path.

## Temporary OpenAI rate limits

Confirmed `rate_limit_exceeded` responses now retry the rejected provider request up to three times with asynchronous exponential delays and jitter. Numeric/date Retry-After headers are honored; a delay over 60 seconds stops instead of retrying early. Activity shows each wait. Existing call budgets and overall operation timeouts still apply; retries count as additional model attempts. Completed tool actions are not replayed because retry occurs inside the transport request, not around the entire worker. Billing-quota errors, ambiguous 429 errors and other failures are not automatically retried. Both OpenAI model requests and built-in OpenAI search requests use this behavior. If limits persist, try Parallelism 1 and review API limits. No live rate-limit recovery has been tested. Guidance: [OpenAI rate limits](https://developers.openai.com/api/docs/guides/rate-limits).

## Readiness and progress control

Intake now receives a dedicated payload without planner or collection instructions. It sees the actual remaining tool budget separately from currently enabled tools and capabilities available on demand. If intake proposes missing inputs before Auto attaches search, the host attaches it and performs one bounded reassessment before stopping. Genuine missing user data still blocks the run, and Off remains respected. The readiness deliverable describes the user's requested result, not the intake document itself.

Live desktop runs and live CLI runs now begin with task readiness. Intake records the intended deliverable, observable completion checks, evidence requirements, missing essential inputs and internet/tool requirements. Inspect these in the **Readiness** tab or `task-readiness.json`. This interpretation is model-based; review it when the task is ambiguous.

**Internet Search** is now **Auto / On / Off**, with Auto as the initial preference. Auto enables native search when intake determines that current external information is needed; the first meaningful search tests provider access before planning, and its results are retained as evidence. It uses your existing provider key and incurs normal provider charges. Off is respected. The desktop saves the selection in `preferences.json` when starting a run. Demo performs no live readiness assessment or search. Selected MCP connections are initialized and discovered as before; readiness explicitly distinguishes connected MCP tools from verified tool execution.

The progress controller tracks new evidence sources, resolved reviewer issues and collection URL growth. A repeated lack of progress requests a different approach; another consecutive lack of progress stops as **stalled**, preserving partial artifacts. Exact repeat search queries reuse successful results rather than issuing another paid search request; attempted tool invocations still count against the tool limit. These are bounded heuristics, not proof of semantic progress or exhaustive research. Existing job-inventory validation remains a specialized completion check; other domains use the readiness checks plus critic review.

Terminal outcomes distinguish **complete**, **needs_resources**, **stalled**, **budget_exhausted**, technical **failed**, and **cancelled**. No limit is increased automatically. The default task/model/tool/repair limits are unchanged; intake, connection-check searches and model continuations use those same budgets. Auto timeout uses 300 seconds in live mode when internet might be needed, while explicit timeout settings are respected. Each new run starts fresh; partial runs are not resumed automatically.

For embedded Python callers, set `Contract(..., adaptive_control=True, internet_mode="auto")` and supply the orchestrator's async `internet_setup` callback to attach an authorized search broker. The embedded default remains False for compatibility with existing custom adapters; desktop and live CLI enable it. CLI search policy is `--internet auto|on|off`.

## Counted job searches

Batch review now reconciles returned verdicts against the supplied listing URLs. Unrelated rows are ignored; missing, conflicting or invalid verdicts become ambiguous and are not counted. Equivalent URLs differing only in tracking parameters match the original listing. Raw and reconciled reviews are saved for audit. If review formatting remains unusable, the batch retains no approved rows rather than treating the formatting failure as a fatal task error. The final target and evidence requirements are not relaxed. Reviewer input is restricted to the batch and its source records. Greenhouse `embed/job_app` URLs with a vacancy token are recognized as individual application links, while board indexes remain excluded.

Research-batch quotas are allocation targets, not acceptance requirements. A dedicated row reviewer classifies each candidate as supported, ambiguous or unsupported using saved retrieval records. Only supported candidates pass to the root; batch summaries show exclusions and shortfalls, without generic quota-repair loops. Recognizable Lever, Ashby and Greenhouse board indexes and generic career index URLs are excluded before counting, including records inherited from earlier tasks. These URL rules are a heuristic; row review is still model-based. Source-record excerpts are bounded and may omit information; neither mechanism proves a job is currently open. Once search calls are exhausted, workers can still extract unused listings from already retrieved records within the model/collection limits. The final root still owns the requested total and substantive review.

After readiness, counted-job runs also check for enabled tools or previously retrieved URL metadata. With neither, the run stops before collection workers start. Tool presence alone does not prove it can retrieve jobs. Empty batches are saved as incomplete and blocked rather than sent through critic repairs. The reviewer receives host-recorded enabled tools, tool-attempt counts and retrieved URL counts.

Requests such as "find me a list of 50 forward deployed engineer jobs" now use a counted job inventory. With decomposition enabled, the host creates up to four source batches instead of recursively rephrasing the same research task. Workers supply a URL and retrieved source reference for each listing. The host accumulates records, removes duplicate URLs (including tracking parameters) and conservative employer/title/location duplicates, preserves existing records, and requests additional collection when a batch or final list is short. Collection continuations use the existing model, tool and tool-round limits, separately from critic repair attempts. Defaults are unchanged.

The final list is rendered from the structured inventory so synthesis cannot replace its entries. Each listing also appears in the reasoning graph, and collection counts appear beside run counters. Intermediate batches may return supported partial results; only the root must reach the total. A short final collection stops as Needs resources and saves an explicitly incomplete partial artifact rather than treating fewer jobs as success. Review can still reject relevance or status problems. URL presence in retrieved metadata is not proof that a vacancy remains open, and duplicate detection may conservatively merge distinct vacancies with identical employer/title/location. This specialized path currently recognizes numeric job-list requests with phrases such as "list of 50" or "find me 50"; other tasks use the general orchestrator. Source matching uses tool-returned URL metadata; it does not certify user-supplied text.

A Python multi-agent orchestration tool for arbitrary user problems. The task DAG
controls execution; a separate reasoning graph records claims, evidence,
assumptions, contradictions, and reported confidence. No third-party dependencies.
Requires Python 3.11 or newer.

## Start here

### Desktop app — no terminal needed

Double-click **Open Taskgraph.vbs** in this folder. On the original computer,
the **Open Taskgraph** shortcut in the parent outputs folder launches it directly.
The launcher uses an installed Python runtime, including the bundled Codex runtime.

1. Click **Load example**, or write your own brief.
   **Approach: Multi-step** is the desktop default. It requires two or more analysis
   tasks before the root synthesizes their outputs. **Auto** lets the planner choose
   a direct answer with critic review for focused questions.
2. Leave **Demo** selected to try the workflow, then click **Start solving**.
3. Explore **Task map**, **Reasoning**, **Answer**, and **Activity**. Click a graph
   node for its full text and evidence. Scrollbars let you navigate large maps.
   Your goal appears immediately; a planning indicator and elapsed timer stay
   visible while the first plan is requested. Subtasks appear after each validated
   plan returns. Planning, execution, judging and review have distinct node statuses.
   Request failures appear above the graph, including API quota/rate-limit guidance.
   Click **Copy error** below the message to copy the complete error to your clipboard.
   Invalid worker references trigger up to two automatic correction calls before
   the task fails. The graph only receives validated results; original invalid
   outputs remain in `artifacts/*invalid-call-*.json`. Corrections use the normal
   call budget and incur API usage in live mode.
   Planner IDs containing punctuation, spaces or excessive length are renamed
   safely with all dependencies preserved. Duplicate IDs, cycles and other invalid
   plans receive up to two correction calls before failing. Ambiguous dependencies
   are never guessed, and invalid plans never partially enter the task graph.
4. For actual model answers, select **OpenAI** and enter your API key and model ID.
   The key is held in memory only. An existing OPENAI_API_KEY environment variable
   also works. Context is sent to OpenAI; normal API charges apply.
5. **Copy answer** copies the final result. **Open saved run** opens a `state.json`
   from an earlier run. Runs are saved automatically in this folder's `runs` folder.

The reasoning view defaults to each task's latest accepted result (or latest
candidate while waiting). **All versions** includes previous and rejected artifacts.
Confidence remains model-reported, and evidence remains unverified.
**Stop run** cancels orchestration; a request already sent to OpenAI may still finish.

The desktop uses Python's bundled Tkinter; it needs no web server, browser, or npm.
On another computer, install Python 3.11+ with Tkinter if it is not present. The
Windows launcher finds per-user Python installs or the Codex bundled runtime.

### Command-line alternative

Open a terminal in this folder:

```sh
python cli.py run --contract example.json --watch
python cli.py run --task "Help me plan a small neighborhood event" --watch
```

On this Windows computer, Python's default command currently points to an
unavailable Windows alias. Use the included launcher, which also finds the Codex
bundled Python runtime:

```powershell
./run.ps1 run --contract example.json --watch
```

Omit both task options to enter the problem interactively. The default mock mode
demonstrates recursive decomposition, concurrent workers, a rejected result,
targeted repair, and final synthesis. **Mock answers are templates, not solutions
to the submitted problem.** The example enables independent candidates and judging.

Every run gets a new folder under `runs/`. The CLI prints the location. To inspect
execution from a second terminal:

```sh
python cli.py inspect runs/YOUR-RUN-FOLDER --watch
```

`--watch` displays both graphs as text, including prerequisite arrows, node IDs,
claim confidence, and typed reasoning edges. No browser or server is needed.
For a less verbose run, omit `--watch`; transition events still print.

## Use a live model

PowerShell:

```powershell
$env:OPENAI_API_KEY = "your-api-key"
python cli.py run --task "Your problem" --adapter openai --model YOUR_MODEL_ID --watch
```

macOS/Linux:

```sh
export OPENAI_API_KEY="your-api-key"
python cli.py run --contract example.json --adapter openai --model YOUR_MODEL_ID
```

Choose a model available to your API account that supports Structured Outputs.
Optionally pass `--strong-model YOUR_STRONG_MODEL_ID` for critic, judge and repairs.
The adapter uses the [OpenAI Responses API Structured Outputs format](https://developers.openai.com/api/docs/guides/structured-outputs).
It sends contract/context/dependency artifacts to OpenAI, sets `store=false`, and
never stores the API key in run files. Live calls incur API charges. This delivery
was tested with mock and fake adapters, not a credentialed live API call.

## Use Claude

Reopen the desktop app and select **Claude** in the provider dropdown. Enter your
**Anthropic API key** and a Claude model ID available to your API account that
supports structured outputs. Choose an ID from the
[Claude model catalog](https://platform.claude.com/docs/en/models/overview).
The optional stronger model must also be a Claude model. Keys/model settings are
kept separately for OpenAI and Claude in memory; switching never reuses another
provider's key. No Claude app login, Bedrock or Vertex credentials are supported.

Claude works with the same task/reasoning graphs, Library knowledge, selected MCP
tools, approvals, critics, corrections, and configurable run limits. Each run uses
one provider; mixed-provider teams are not part of this update. Selected knowledge
and tool results are sent to the provider you choose. Live calls incur API usage.

CLI alternative: set `ANTHROPIC_API_KEY`, then use
`python cli.py run --task "Your problem" --adapter claude --model YOUR_CLAUDE_MODEL_ID`.
The adapter uses the
[Anthropic Messages API](https://platform.claude.com/docs/en/api/messages/create)
and [JSON structured outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs).
Tests simulate Anthropic responses, tool-use round trips, refusals, truncation and
authentication errors. A credentialed live Claude call has not been tested.

## Task Contract

The default task limit is **80**, including the root and repair tasks.
In the desktop, click **Run limits…** under Run settings to increase or decrease
the task limit, model-call limit, parallelism, depth, repairs, MCP attempts, tool
rounds, or timeout. **Restore defaults** resets the fields; **Save limits** applies
them to future runs in this app session. Restarting restores the defaults. The
active run is never changed. Its chosen limits are recorded in its Task Contract.
Timeout accepts `Auto` (90 seconds, or 300 with MCP) or a positive number of seconds.

Copy `example.json` and edit `goal`, `success_criteria`, `constraints`, and `context`.
Provide source material in context when factual evidence matters. Limits control
maximum task count (including root and repairs), decomposition depth, repair
generations per task, concurrent task executions, total adapter calls, and seconds
per call. `max_depth=0` makes the root atomic. `max_repairs=0` disables repairs.
`disagreement=true` produces two independent candidate calls and a judge for each
work item. Independence means isolated inputs, not guaranteed model diversity.

## Run outputs

The planner receives the remaining task capacity. If an expansion does not fit,
the worker solves the complete original task directly; its scope is preserved.
At full capacity, further planning is skipped and critic repairs revise existing
tasks in place, preserving prior artifacts. Repair and model-call limits still apply.
Nested plans may repeat exact inherited prerequisite IDs. These are preserved
automatically on every child and are not mistaken for missing local tasks.
In Multi-step mode, an unusable or oversized root plan falls back to a disclosed
two-part host plan: evidence/constraints analysis and candidate-solution comparison.
These are real worker tasks, followed by root synthesis and critic review. The
event log records this fallback and each planner's direct/decomposed decision.
The CLI contract uses `"strategy": "multi_step"` to enable it; its default is `auto`.

* `answer.md`: accepted root deliverable, only on success.
* `state.json`: atomically replaced inspection snapshot, including both graphs.
* `events.jsonl`: timestamped transitions, routes, model choices and critic issues.
* `artifacts/`: retained candidate, judge, accepted result and review JSON files.

`complete` means all required tasks passed the configured critic, **not** externally
verified truth. Confidence is model-reported and uncalibrated. Evidence is explicitly
marked unverified. Original candidates and rejected claims remain visible with
artifact provenance; accepted task outputs identify the current result.

## Tests

```sh
python -m unittest -v
```

Tests cover recursive decomposition, parallel execution, dependency ordering,
cycle rejection without partial mutations, provider failure propagation, timeout,
call budget, repair exhaustion, isolated duplicate workers, judge invocation,
reasoning references/contradictions, capability routing, and adaptive model hooks.

## Scope and extension points

This V1 handles arbitrary text problems with pluggable adapters. Workers can now
call user-selected MCP tools in OpenAI mode. Without connected tools, research uses
supplied context and code is produced as text. Connecting a tool grants only the
capabilities you explicitly allow; local servers run as your Windows user, without
a sandbox. See `LIBRARY.md` for setup and supported MCP features.

Implement `Adapter.complete(role, payload, schema, model)` to add a provider or
tools. Return schema-conforming dictionaries; host validation runs independently.
Register `Worker(name, capabilities, role, priority)` to alter dynamic routing.
Override `ModelPolicy.select(role, task)` for capability, risk, cost or uncertainty
policies. No API model names are hard-coded. See `ARCHITECTURE.md` for invariants.

V1 does not resume execution from snapshots, automatically retry provider errors,
verify remote citations, calibrate confidence, enforce monetary/token budgets, or
provide hardened multi-user isolation. Calls are bounded by count and timeout;
HTTP calls already in progress may finish after coroutine cancellation. Use normal
API-side spending controls. Run data is plain local JSON; treat it like your inputs.
# Missing resources and current information

A model connection alone does not provide web browsing. For tasks such as finding currently open jobs, enable **Internet Search** in Run Settings, or supply current source material or a relevant MCP retrieval tool. The sample MCP server only searches demonstration notes; it cannot search job listings.

## Internet Search — no MCP setup

1. Select OpenAI or Claude and enter your API key and a model ID supporting web search.
2. Select **Internet Search: Auto** (or On), then click **Start solving**. Demo mode cannot search.
3. Inspect Activity and tool evidence nodes for queries, returned sources and retrieval timestamps.

Search uses the selected provider's native web-search API with the existing key. Normal provider search and model charges apply. Auto is the initial preference. Workers choose focused queries as needed; the planner and critic see the tool's availability. Each search request counts toward the model-call budget; search and MCP invocations share the tool-call limit. Each request allows at most one native search invocation; workers can request further searches within the run limits. Auto timeout is 300 seconds when internet may be used. A search is not a guarantee of 50 valid results or proof a vacancy is still open. Unsupported models, failed searches and incomplete responses are reported as tool errors, never silently substituted with model memory. No live paid request was used in automated validation.

References: [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search), [Claude web search](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool).

The critic now distinguishes a repairable answer from an external resource blocker. A blocker stops the affected task with **Needs resources**, preserves its unaccepted candidate for inspection, and blocks dependent synthesis without spending repair attempts on templates. Add the missing resources and start a new run; failed runs are not resumed. This classification is model-based, not a guarantee that every missing resource will be detected. A partial template is never automatically counted as the requested completed list.
