# Taskgraph Studio

**Turn a complex objective into a visible, coordinated AI workflow.**

Taskgraph Studio is an experimental Python desktop application for multi-agent problem solving. Enter a task, provide relevant knowledge and tools, and inspect how the work is planned, executed, reviewed, and assembled into a result.

A live **task graph** shows dependencies and execution progress. A separate **reasoning graph** connects claims, evidence, assumptions, and contradictions so you can inspect the basis of the output.

Designed for exploring research, analysis, planning, and business problems. This is an early version, with bounded execution and explicit reporting of incomplete results.

## What you can do

- Define the objective, success criteria, constraints, and context in a Task Contract.
- Watch tasks move through planning, execution, review, and completion.
- Decompose work recursively and run independent tasks concurrently.
- Route tasks through a capability registry to General, Research, and Code/Data workers.
- Review claims and their associated sources in a separate reasoning graph.
- Use critic feedback to request targeted repairs within configured limits.
- Optionally compare two independently generated candidates with a judge.
- Connect OpenAI or Claude, with an optional stronger model for selected roles.
- Enable built-in Internet Search or connect selected MCP tools.
- Reuse knowledge from a local Library and inspect saved run artifacts.
- Adjust task, model-call, tool, repair, depth, parallelism, and timeout limits.

Dynamic routing selects among registered worker capabilities. V1 does not autonomously install tools or create new executable agent implementations.

## Quick start: Windows desktop

### Requirements

- Python 3.11 or newer, including Tkinter.
- No third-party Python packages are required.
- For live execution: an OpenAI or Anthropic API key and an accessible, compatible model ID.
- Internet access for live model calls and online tools.

### Open the app

1. Download the project ZIP and extract it completely.
2. Open the extracted folder containing `desktop.py`.
3. Double-click **Open Taskgraph.vbs**.
4. Leave **Demo** selected, click **Load example**, then **Start solving**.
5. Explore **Readiness**, **Task map**, **Reasoning**, **Answer**, and **Activity**.

The Windows launcher looks for a per-user Python installation or the bundled Codex Python runtime. It requires Windows Script Host. If it cannot find your Python installation, launch `desktop.py` with Python instead.

**Demo uses mock responses to demonstrate the workflow. It does not solve your task or search the internet.**

### Run a real task

1. Select **OpenAI** or **Claude**.
2. Enter your provider's API key and a model ID supported by your account and the adapter's structured-output requirements.
3. Write your task, including the intended outcome and important constraints.
4. Leave **Internet Search: Auto** selected when current information may be needed.
5. Optionally select relevant Library items or MCP connections.
6. Review **Run limits**, then click **Start solving**.

Live model and search requests incur provider charges. Each run uses one provider; mixed-provider teams are not supported in V1. Provider API keys entered in the desktop are held in memory.

## Example task

> Suggest five startup ideas that help US regional banks manage financial risk. Compare each idea by target buyer, risk problem, required data, implementation complexity, and an initial validation experiment. Use current sources for factual market claims, distinguish assumptions from evidence, and identify gaps that require further research.

For collection tasks, specify the requested count and inclusion criteria explicitly. For example:

> Find 20 AI engineering vacancies in the United States. Include employer, title, location, a direct vacancy URL, and a status note. Exclude general careers pages and duplicate listings. Clearly report any shortfall.

Counted job searches have specialized collection and review logic. Other domains use the general planning and critic workflow.

## Understanding the interface

| View | Purpose |
| --- | --- |
| Readiness | Inspect the interpreted deliverable, resource requirements, and remaining limits. |
| Task map | Follow tasks, dependencies, parallel work, and execution status. |
| Reasoning | Inspect claims, evidence, assumptions, contradictions, and artifact provenance. |
| Answer | Read and copy the accepted answer or a clearly labeled saved partial result. |
| Activity | Inspect transitions, tool activity, review feedback, and errors. |

The root task appears immediately. Subtasks appear after a plan is returned and validated. Click graph nodes to inspect details. **Copy error** copies the full error message.

**Open saved run** loads a previous `state.json` for inspection. It does not resume execution.

## Internet Search

- **Auto:** readiness assessment can attach native search when current external information is required.
- **On:** enable native search for the run.
- **Off:** disable the built-in search option. Separately selected MCP tools have their own permissions.

Built-in search uses your selected provider and API key; it does not require an MCP server. It requires a compatible model and provider access. Search activity and returned sources are retained as artifacts.

Retrieving a URL is not proof that its contents support a claim or that a vacancy remains open.

## Knowledge Library and MCP tools

### Add existing knowledge

Open **Library → Knowledge → New**, add notes or import a supported text file, and save it. Then choose **Use for this task** and select the relevant items.

Supported imports include UTF-8 TXT, Markdown, CSV, TSV, and JSON. Selected text is copied into the task context. A reference URL alone does not download the page. V1 does not include PDF/Word parsing or semantic retrieval over a vector database.

### Connect an MCP server

1. Open **Library → MCP connections → New**.
2. Enter a name, description, and compatible remote endpoint or local executable configuration.
3. Supply credentials if required and select **Test connection** to discover tools.
4. Set each tool to **Disable**, **Allow · ask each time**, or **Allow automatically**.
5. Select the connection under **Use for this task**.

Connections expose tools supplied by an existing MCP server. A description alone does not create a working integration. Local servers execute as your Windows user, without a sandbox.

See [LIBRARY.md](LIBRARY.md) for setup, credential handling, permissions, and protocol limitations.

## Execution limits

Use **Run limits** to change values before starting a run. Changes apply to future runs in the current app session; restarting restores defaults.

| Setting | Default |
| --- | ---: |
| Maximum tasks, including root and repairs | 80 |
| Model calls | 100 |
| Tool attempts | 24 |
| Tool / collection rounds | 8 |
| Parallel tasks | 3 |
| Decomposition depth | 3 |
| Repair generations per task | 2 |

Auto timeout is normally 90 seconds, or 300 seconds for live runs where internet or selected MCP tools may be used. Explicit timeout settings take precedence.

**The 80-task limit is not a requested result count.** A request for 20 jobs still targets 20 jobs. Planning, review, repair, search requests, and continuations consume their applicable budgets. Limits are not increased automatically.

## Completion and partial results

Runs can end as:

- **Complete:** the required work passed configured review.
- **Needs resources:** necessary inputs or capabilities were unavailable.
- **Stalled:** repeated attempts made no tracked progress after a change of approach.
- **Budget exhausted:** an execution limit was reached.
- **Failed:** a technical error prevented continuation.
- **Cancelled:** execution was stopped.

Partial work is retained where available and labeled incomplete. A stalled search does not establish that no additional results exist. The progress controller uses bounded heuristics, not an exhaustive assessment of the search space.

## Architecture

The orchestrator runs a state-machine loop that coordinates readiness, planning, worker execution, review, repair, and finalization.

| Component | Responsibility |
| --- | --- |
| Orchestrator | Maintain state, schedule ready tasks, enforce budgets, and save artifacts. |
| Planner / Atomizer | Decide whether to decompose a task and propose dependencies. |
| Capability registry | Route tasks to registered workers. |
| General Worker | Perform general analysis and synthesis. |
| Research Worker | Gather and organize evidence using available resources. |
| Code/Data Worker | Produce code or analysis; execution requires an appropriate connected tool. |
| Critic / Judge | Review candidates, request repairs, and compare optional independent outputs. |
| Artifact store | Retain tool results, candidate outputs, reviews, and provenance. |

The task DAG represents execution dependencies. The reasoning graph represents recorded claims and their relationships. They are separate structures; the reasoning graph is not a transcript of a model's internal reasoning.

See [ARCHITECTURE.md](ARCHITECTURE.md) for implementation details and extension points.

## Saved files

Each run has a directory under `runs/` containing:

- `state.json`: task and reasoning graph snapshot.
- `events.jsonl`: execution events and review feedback.
- `task-readiness.json`: live readiness assessment, when produced.
- `artifacts/`: worker outputs, tool results, reviews, and diagnostics.
- `answer.md`: accepted root answer, written on successful completion.

Run data is stored as local plaintext. Selected context and tool results are sent to the chosen model provider as part of execution.

## Current limitations

- Early-stage software; expect incomplete results and provider-dependent behavior.
- Confidence percentages are **model-reported and uncalibrated**, not measured probabilities of correctness.
- Critic acceptance and source linkage do not establish externally verified truth.
- Automatic reference normalization preserves supplied text; it does not validate the substance of an assumption.
- No automatic execution resume from saved snapshots.
- No hardened multi-user isolation or sandbox for local MCP servers.
- No monetary or token-budget enforcement; the app uses count and timeout limits.
- Selected transient OpenAI rate-limit errors have bounded retries; other errors may stop execution.
- Stopping a run may not cancel an HTTP request already sent to a provider.
- Automated validation uses mock and simulated provider responses, not a guarantee of live provider compatibility.

## Optional command-line use

The desktop is the primary interface. Developers can also run:

```sh
python desktop.py
python cli.py run --contract example.json --watch
python cli.py run --task "Help me plan a neighborhood event" --watch
python cli.py inspect runs/YOUR-RUN-FOLDER --watch
```

CLI runs default to mock mode. For live runs, set the provider API key in the appropriate environment variable and choose the adapter and model:

```sh
python cli.py run --task "Your task" --adapter openai --model YOUR_MODEL_ID --internet auto --watch
python cli.py run --task "Your task" --adapter claude --model YOUR_CLAUDE_MODEL_ID --internet auto --watch
```

Use `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`, respectively. Keep secrets out of committed files.

## Development and feedback

Run the automated checks with:

```sh
python -m unittest discover -v
```

To report a problem, include the task description, expected result, actual result, application version, provider/model, and relevant limits. Remove API keys, credentials, personal information, and sensitive source material from anything you share.

Provider adapters implement `Adapter.complete(role, payload, schema, model)`. Register workers to extend routing and customize `ModelPolicy.select(role, task)` to change model-selection policy.

## License

A license has not yet been selected. Public availability does not by itself grant permission to reuse or redistribute the software. Add a `LICENSE` file before distributing the project under open-source terms.
# TaskGraph-Studio
