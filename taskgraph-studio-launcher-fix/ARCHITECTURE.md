# Architecture

## Components

The Orchestrator owns mutable state and scheduling. Planner/Atomizer proposes
local DAG fragments. General, Research, and Code/Data Workers share one execution
interface and route by registered capability. Critic returns an acceptance verdict
and actionable issues. Judge is an optional role of the model adapter, rather than
an always-running separate agent.

The Task Contract carries goal, success criteria, constraints, context, and limits.
Every worker receives the contract, task metadata, dependency outputs and available
capabilities. Outputs have an answer, claims, evidence, assumptions, and limitations.
Critic additionally receives the candidate; Judge receives both independent results.
These public artifacts express conclusions and their support, not private model
chain-of-thought.

## Loop and states

```text
intake -> scheduling -> planning -> scheduling
                   -> executing -> critic
                        |            | accepted -> done
                        |            | rejected -> repair task -> critic
                        |            | exhausted/error -> failed
                        +------------+---------------------> scheduling
root accepted -> complete; root failed/blocked -> failed
```

Run state is a coarse phase; per-task status is authoritative during concurrency.
Task statuses: pending, planning, queued, running, judging, reviewing, repair_wait, done, failed, blocked,
cancelled. Only tasks whose prerequisites are all done can start. An asyncio
FIRST_COMPLETED scheduler fills free task slots without waiting for an entire
wave. Planner calls are serialized by the scheduler; already-running workers can
continue while planning awaits I/O. The task parallelism limit does not count
planner calls. Each task runs candidates and review sequentially.

## Recursive graph mutation

A planner returns local IDs and dependencies. The host validates capabilities,
IDs, every dependency, acyclicity and task count before committing any mutation.
Children inherit the parent's existing prerequisites. The parent becomes a join
that waits for all its children and then synthesizes their outputs. Existing
downstream nodes still depend on the parent. Children may be atomized again until
the depth bound; an empty plan means atomic. Root depth is zero. Model prompts ask
for meaningful decomposition; depth/task limits enforce termination if the model
over-decomposes.

Rejected output is retained. A new repair node inherits the original prerequisites,
critic issues, prior candidate, capability, and incremented repair generation.
The original task waits on the repair. Accepted repair output propagates through
waiting ancestors before releasing downstream tasks. Repairs are not decomposed;
they may receive another targeted repair within the generation limit. Unrecoverable
failure blocks dependent tasks. Independent running work is allowed to finish.

## Two separate graphs and the artifact store

The task DAG contains execution prerequisites only. The reasoning graph has typed
claim, evidence, and assumption nodes, plus supports, assumes, and contradicts
edges. IDs are namespaced by artifact, task, revision, and candidate label. All
reasoning references are checked before ingestion. `supports` points from the
claim to its supporting evidence (a reference convention, not a causal arrow).
Contradictions are explicitly reported within an output; the judge can bring
cross-candidate disagreements into one result. V1 does not automatically discover
semantic contradictions across arbitrary stored claims or merge duplicate claims.

All candidate evidence is retained with source text, provenance and verified=false.
Accepted outputs are separate artifacts. The graph is an audit history, not a
single truth database: inspect accepted task outputs for the current conclusion.
The critic's task verdict is not proof that each claim is true. Dependency outputs
are the bounded shared context supplied to workers; the full historical store is
available to the host and inspection CLI, avoiding cross-candidate leakage.

## Routing and models

Registry selects the highest-priority worker supporting a requested capability;
unknown capabilities fail explicitly. The bundled adapter recognizes six roles,
while new role behavior belongs in a custom adapter. Worker definitions are data,
not separate hard-coded agent classes. ModelPolicy selects a default or stronger
model for judging, verification, and repairs; subclass it for richer policies.

Disagreement runs two calls with deep copies of the same pre-execution payload.
Neither sees the other's result. Both outputs are retained; a judge synthesizes,
then the normal critic reviews. Using the same model does not guarantee diversity.

## Persistence and failure semantics

The event log is append-only within a run. Inspection snapshots use atomic replace.
Each new run directory must not exist, preventing accidental overwrites. Filenames
are built from host-validated task IDs, never model-provided file paths. Artifacts
are written by the single asyncio event loop, with no concurrent filesystem writer.
Snapshots are inspectable checkpoints, not crash-resume journals. Provider errors,
invalid JSON/schema, invalid reasoning references, timeout, or limits fail visibly.
No silent mock fallback occurs for a live adapter failure.

## V2 opportunities

The desktop now has a reusable knowledge/MCP Library. See `LIBRARY.md` for the
transport, permission, credential and tool-call architecture and compatibility.

Add sandboxed code tools and retrieval with verifiable source excerpts; calibrated
verification; cross-artifact contradiction resolution; persisted resume; provider
backoff and idempotent retries; per-call token/cost accounting; semantic acceptance
evals; structured human-input pauses; and graphical inspection. These are extension
points, not claimed V1 capabilities.
# Resource blockers

Live entry points enable the general control layer (`control.py`). Before planning, `intake` returns a structured readiness contract. The host enforces missing-resource and search-policy decisions, lazily attaches native search under Auto, and performs a meaningful search as the access check. Readiness and actual resource-check outcomes are persisted independently from task artifacts and shown in the desktop. Other selected MCP tools are discovered but not automatically invoked for testing because arbitrary tool calls can have side effects. Their unverified execution status remains explicit.

Progress histories are keyed to the original task across repair descendants. They track new evidence sources or resolved issue strings; collection histories track distinct candidate URLs. First repetition requests a changed approach, second repetition stops as stalled. Model-call and repair-allowance exhaustion have a separate budget_exhausted outcome. These signals are heuristics; changed wording and irrelevant evidence can still mislead progress assessment. They supplement, not replace, critic review and domain-specific validators. Dependency state propagation iterates until stable, so nested repair stops reach the root without losing the original stop reason. Search cache hits preserve the original source artifact and avoid another provider request while still consuming a tool-attempt slot. Control does not increase budgets or resume old runs.

Counted job requests use `job_collection.py`: an extended worker schema, source-metadata URL matching, stable inventory merge, conservative deduplication, host-rendered final rows, and bounded collection continuation before critique. The host seeds independent source batches within task/depth limits, with no recursive batch decomposition. Batch quotas permit partial research; the root must reach its global target. Collection rounds share the configured call/tool budgets and are separate from critic revisions. They do not increase default limits. Listing nodes retain links to source artifacts, and snapshots expose current collection progress. Semantic relevance and open-status verification remain critic responsibilities; retrieved URLs alone are not verification.

`internet_search.py` wraps the existing MCP broker (or operates alone), exposing a structured `internet_search(query)` function to both adapters. It performs a separate provider-hosted search request without structured-output formatting, preserving source and citation blocks for the subsequent structured worker response. Native search is bounded to one invocation per request; partial Claude `pause_turn` responses are returned as incomplete tool results rather than automatically continued. The wrapper shares a combined tool-attempt budget and records extra model requests, source artifacts, timestamps and activity. Credentials stay in memory and are not included in query artifacts. Desktop `Internet Search` is opt-in and is captured in the run's resource manifest.

The structured critic response includes `blocked_reason` (empty when repairable or accepted). A nonempty reason takes precedence over acceptance, saves a `partial` artifact, blocks the task and its dependents, and ends the run as `needs_resources` if no other failure supersedes it. It does not consume repair attempts or publish an accepted answer. Ordinary quality failures still follow bounded targeted repairs. This is a model-assessed resource gap after candidate review, not an upfront connectivity or source-completeness guarantee. Local reasoning-reference integrity remains host-validated; assumptions need not repeat dependency wording.
