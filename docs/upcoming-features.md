# Lumos upcoming features and implementation roadmap

This document captures possible future capabilities for Lumos. It is intentionally more detailed than a wishlist: each idea records the problem, proposed behavior, implementation direction, and a practical definition of done. It should help maintainers turn an idea into a design document, GitHub epic, or implementation plan without having to reconstruct the original intent.

This is a planning document, not a promise of release dates or a stable public API. Designs may change as Lumos gains real-world usage.

## Product direction

Lumos should become a portable, spec-driven execution layer for AI-assisted software delivery. A user should be able to give Lumos a ticket, select a workflow, and let a combination of agents and skills plan, implement, test, review, fix, and publish the result with clear controls and evidence.

Future work should preserve these principles:

- **Runtime neutral:** workflows should not be tied to one AI product, model vendor, or agent framework.
- **Worker neutral:** an ordered step may invoke a skill, an autonomous agent, a script, or a future worker type through a shared contract.
- **Safe autonomy:** unattended execution needs explicit permissions, budgets, isolation, approval gates, and recovery behavior.
- **Spec driven:** ticket requirements and acceptance criteria should remain traceable through planning, code, tests, review, and delivery.
- **Inspectable:** users should be able to understand what ran, why a decision was made, what changed, and how much it cost.
- **Backward compatible:** configuration and state formats need versioning and documented migrations.

## Suggested delivery sequence

| Phase | Goal | Candidate features |
| --- | --- | --- |
| 1. Reliable execution | Make autonomous runs safe and genuinely portable | Runtime executor adapters, isolated worktrees, policy gates |
| 2. Scalable workflows | Support larger and more efficient delivery flows | Workflow DAGs, parallel workers, model routing and budgets |
| 3. Verifiable delivery | Prove that the result satisfies the source specification | Traceability, dry-run/explain mode, evaluation framework |
| 4. Ecosystem and operations | Make Lumos easy to extend, automate, and operate at scale | Worker marketplace, webhooks, dashboard/replay, multi-repository runs |

The phases express dependency order, not release commitments. Small independent slices can ship earlier when their contracts are stable.

## 1. Runtime executor adapters

### Problem

Lumos can describe skills and agents, but portable orchestration requires a real execution boundary between the workflow engine and the AI environment. Without that boundary, worker definitions may be portable on paper while invocation, continuation, tool permissions, and result collection remain tied to one host.

### Proposed capability

Introduce an executor interface responsible for running a normalized worker request. Initial adapters could support Codex, Claude Code, a local process, and a generic HTTP endpoint. Configuration selects a default executor and may override it per worker.

```yaml
runtime:
  default_executor: codex
  executors:
    codex:
      type: codex
    local:
      type: process
      command: ["python", "tools/run_worker.py"]

workflow:
  steps:
    - id: plan
      worker: planner
      executor: codex
```

The normalized request should include the worker definition, resolved prompt, ticket context, prior outputs, workspace information, permissions, timeout, and cancellation signal. The result should contain a status, structured report, artifacts, usage data, and diagnostics.

### Implementation direction

1. Define versioned `ExecutorRequest` and `ExecutorResult` schemas.
2. Add an executor registry and lifecycle methods such as `prepare`, `execute`, `cancel`, and `cleanup`.
3. Move host-specific behavior out of the core scheduler.
4. Implement one first-party adapter end to end before adding more.
5. Add capability discovery so Lumos can reject unsupported options before a run starts.
6. Document third-party adapter authoring and contract tests.

### Definition of done

- The same workflow can run through at least two executors without changing worker content.
- Timeouts, cancellation, streaming events, failures, and structured output behave consistently.
- Unsupported executor capabilities fail during validation rather than midway through a run.
- Secrets are referenced indirectly and are not written to reports or logs.
- Adapter contract tests can be reused by external implementations.

### Suggested issue breakdown

- Design the executor protocol and capability model.
- Build the executor registry and validation layer.
- Implement first-party Codex and local-process adapters.
- Publish an external executor authoring guide and conformance suite.

## 2. Workflow DAGs and parallel workers

### Problem

A strictly sequential list is simple, but it makes independent work wait unnecessarily. Testing, security analysis, documentation, and specialist reviews may run in parallel, while some steps need only a subset of earlier results.

### Proposed capability

Allow workflows to be directed acyclic graphs. Each step declares dependencies with `needs`; the scheduler runs ready steps concurrently within configured limits and joins their outputs for downstream workers.

```yaml
workflow:
  max_parallel: 3
  fail_fast: false
  steps:
    - id: plan
      worker: planner
    - id: implement
      worker: coder
      needs: [plan]
    - id: test
      worker: tester
      needs: [implement]
    - id: security_review
      worker: security-reviewer
      needs: [implement]
    - id: final_review
      worker: reviewer
      needs: [test, security_review]
```

### Implementation direction

- Validate unknown dependencies, cycles, duplicate identifiers, and unreachable nodes.
- Persist node state independently so an interrupted run resumes only incomplete work.
- Define deterministic input ordering when multiple upstream reports are merged.
- Add concurrency limits at global, workflow, executor, and repository levels.
- Specify `fail_fast`, partial failure, cancellation propagation, retry, and join semantics.
- Make logs and the CLI show which nodes are running, waiting, skipped, or blocked.

### Definition of done

- Independent steps demonstrably execute concurrently.
- Cyclic or ambiguous graphs fail before execution with useful errors.
- Resume does not repeat successfully completed nodes unless explicitly requested.
- A downstream step never starts until its dependency and success conditions are satisfied.
- Parallel output remains understandable and machine-readable.

## 3. End-to-end specification traceability

### Problem

A successful command or green test suite does not prove that every ticket requirement was understood and implemented. For spec-driven delivery, Lumos needs a durable chain from the source requirement to planning decisions, code changes, tests, review evidence, and final status.

### Proposed capability

Normalize acceptance criteria into stable requirement identifiers, then let workers attach evidence to those identifiers.

```yaml
requirements:
  - id: AC-1
    text: Users can configure the ticket prefix.
  - id: AC-2
    text: TC is used when no prefix is configured.
```

A run would produce a traceability matrix containing each requirement, its implementation references, test evidence, reviewer verdict, and unresolved gaps. The final delivery gate could require all mandatory requirements to be covered.

### Implementation direction

- Add schemas for requirements, evidence, confidence, and coverage status.
- Teach the planning stage to extract or confirm acceptance criteria.
- Extend worker reports with `requirements_addressed` and `evidence` fields.
- Add repository-aware evidence references for files, lines, commits, tests, and external links.
- Generate Markdown and JSON traceability reports.
- Define how changed or contradictory requirements invalidate earlier evidence.

### Definition of done

- Every mandatory acceptance criterion has a stable ID and final status.
- Evidence can be traced to concrete artifacts rather than narrative claims alone.
- Missing coverage can block completion under configurable policy.
- The report clearly distinguishes verified, partially verified, failed, and not-applicable criteria.

## 4. Sandboxed workers and Git worktree isolation

### Problem

Parallel or autonomous agents can overwrite one another, damage an existing checkout, or act on stale files. A safe orchestrator needs workspace isolation and controlled merge behavior.

### Proposed capability

Give each run—or selected worker—an isolated Git worktree and branch. Workers make changes only in their assigned workspace. Lumos validates and integrates results using a declared strategy.

```yaml
workspace:
  isolation: worktree
  branch_template: "lumos/{ticket}/{run_id}"
  cleanup: on_success
  integration:
    strategy: merge
    conflict_policy: ask
```

### Implementation direction

- Add a workspace manager with create, inspect, lock, integrate, and cleanup operations.
- Verify repository roots and branch targets before mutations.
- Record the base revision so stale runs can be detected.
- Support per-run isolation first; consider per-step isolation only after merge semantics are proven.
- Preserve failed workspaces by default for diagnosis.
- Add disk quotas, path allowlists, and orphan cleanup commands.

### Definition of done

- A run cannot modify the user's original checkout when isolation is enabled.
- Two isolated runs can operate on the same repository without corrupting each other.
- Conflicts stop safely and preserve both sides for inspection.
- Cleanup never deletes a workspace that Lumos cannot positively identify as its own.

## 5. Model routing and budget controls

### Problem

Not every step needs the most capable or expensive model. Conversely, complex planning or debugging may fail repeatedly on a model chosen only for speed. Teams also need predictable limits for unattended runs.

### Proposed capability

Select models by worker role, task complexity, executor availability, privacy policy, and remaining budget. Support hard limits and intentional escalation rules.

```yaml
models:
  defaults:
    model: fast-model
    reasoning: medium
  routes:
    planner:
      model: reasoning-model
      reasoning: high
    reviewer:
      model: reasoning-model
  escalation:
    after_failed_attempts: 2
    model: reasoning-model
  budgets:
    max_cost_usd: 8.00
    max_tokens: 500000
    max_duration_minutes: 90
```

### Implementation direction

- Normalize usage and cost reporting across executors while retaining raw provider data.
- Resolve a route before each attempt and record why it was selected.
- Separate hard limits from warning thresholds.
- Define behavior when pricing is unavailable or changes during a run.
- Make escalation bounded and prevent retry loops from silently exceeding budgets.
- Allow organizations to prohibit particular providers, regions, or model classes.

### Definition of done

- A dry run shows model choices and applicable limits before execution.
- Hard budgets stop safely and leave resumable state.
- Every model selection and escalation is visible in the audit trail.
- Missing price data is explicit and never treated as zero cost.

## 6. Policy as code and approval gates

### Problem

Autonomy must be constrained differently across repositories and organizations. A documentation change, database migration, production deployment, and dependency update should not share identical permissions or approval rules.

### Proposed capability

Evaluate versioned policies at meaningful lifecycle events: before a run, before a worker, before tool access, before integration, and before publishing a pull request.

```yaml
policies:
  - id: require-review-for-migrations
    when:
      changed_paths: ["migrations/**"]
    require:
      approval: human
      checks: [tests, database-review]
  - id: block-secret-files
    deny:
      changed_paths: ["**/.env", "**/*.pem"]
```

Policy decisions should be allow, deny, or require approval, accompanied by a clear explanation and matched rule IDs.

### Implementation direction

- Start with a small declarative schema instead of embedding arbitrary executable code.
- Define deterministic inputs such as ticket metadata, changed paths, commands, tool scopes, risk labels, and check results.
- Persist policy decisions and approvals in the run state.
- Add precedence rules for user, repository, and organization configuration.
- Protect policy files from being modified and then trusted within the same run.

### Definition of done

- Denied actions cannot be bypassed by retrying through another worker or executor.
- Approval requests explain exactly which policy matched and what action is pending.
- Policies can be validated and tested without executing a workflow.
- The audit log records policy versions and decisions.

## 7. Worker marketplace and installer

### Problem

Templates help authors begin, but reuse remains cumbersome if workers must be copied manually. Lumos needs a discoverable ecosystem for skills, agents, workflow packs, executors, and tracker adapters without sacrificing supply-chain safety.

### Proposed capability

Add package metadata and CLI commands to search, inspect, install, pin, update, and verify community extensions.

```text
lumos add acme/security-reviewer@1.4.0
lumos inspect acme/security-reviewer
lumos update --locked
```

A package manifest should declare its type, Lumos compatibility, entry points, required tools, permissions, configuration schema, license, provenance, and integrity digest. Installations should generate a lock file.

### Implementation direction

- Finalize extension manifests and semantic-version compatibility rules.
- Support a Git repository or local path source before building a hosted registry.
- Store exact versions, source revisions, and hashes in `lumos.lock`.
- Add signature or provenance verification and dependency scanning.
- Require users to review newly requested permissions during install or update.
- Define namespace ownership, deprecation, yanking, and trust indicators.

### Definition of done

- A clean environment can reproduce the same installed extension set from the lock file.
- Tampered package contents fail integrity checks.
- Updates cannot silently acquire broader permissions.
- Uninstall removes managed files without deleting user-authored configuration or data.

## 8. Workflow simulation, explanation, and dry run

### Problem

Users need to understand an autonomous run before it spends money, edits code, or contacts external systems. Configuration validation alone does not show the resolved workflow, inferred dependencies, permissions, or likely cost.

### Proposed capability

Provide `lumos plan`, `lumos explain`, and `lumos run --dry-run` modes that resolve configuration and display the intended execution without invoking workers or mutating external systems.

The output should include:

- Parsed ticket and selected tracker adapter.
- Workflow and worker resolution, including configuration sources.
- Dependency graph and expected concurrency.
- Executors and model routes.
- Required credentials, tools, and permissions.
- Policy gates and possible pause points.
- Estimated time, token use, and cost as ranges with assumptions.
- State, branch, worktree, and pull-request targets.

### Implementation direction

- Reuse the real resolver and scheduler planning code so simulation cannot drift from execution.
- Mark values as known, estimated, unavailable, or dependent on runtime output.
- Add human-readable, JSON, and optionally graph formats.
- Ensure dry runs never call mutating adapter methods.
- Provide actionable diagnostics with configuration source locations.

### Definition of done

- The plan explains why each worker, executor, and model was selected.
- CI can validate workflows in a non-interactive, machine-readable mode.
- Dry run performs no repository, tracker, or remote mutations.
- The eventual run records meaningful differences from the earlier plan.

## 9. Webhooks and autonomous ticket intake

### Problem

Manual `/lumos TC#123` invocation is useful for interactive work but does not support event-driven teams. Repositories may want Lumos to react to labels, assignments, comments, scheduled queues, or failed checks.

### Proposed capability

Add an intake service that receives tracker webhooks, normalizes them into Lumos events, evaluates routing and policy rules, and enqueues idempotent runs.

```yaml
automation:
  rules:
    - when:
        event: issue.labeled
        label: lumos-ready
      run:
        workflow: feature
    - when:
        event: pull_request.check_failed
      run:
        workflow: repair
```

### Implementation direction

- Verify webhook signatures before parsing or acknowledging events.
- Store provider delivery IDs and deduplicate retries.
- Separate intake, queueing, and execution so bursts do not overload workers.
- Add per-repository allowlists, concurrency limits, and kill switches.
- Prevent loops caused by Lumos reacting to its own comments, labels, or pull requests.
- Provide polling as a fallback for systems without reliable webhooks.

### Definition of done

- Duplicate event deliveries create at most one logical run.
- Unauthorized or invalid events are rejected and auditable.
- A repository owner can pause intake without losing queued work.
- Self-generated events cannot create infinite run loops.

## 10. Observability dashboard and deterministic replay

### Problem

Long autonomous workflows are difficult to operate from interleaved terminal logs. Maintainers need a coherent view of status, decisions, artifacts, costs, failures, and retries, plus a way to reproduce scheduler behavior without repeating expensive model calls.

### Proposed capability

Emit structured lifecycle events into a run event store and expose them through a local web dashboard or external telemetry exporter. Add replay modes that rebuild state and scheduling decisions from recorded inputs and outputs.

Useful views include:

- Run timeline and workflow graph.
- Worker attempts, retries, durations, and current status.
- Requirement coverage and policy decisions.
- Artifacts, diffs, reports, and pull-request links.
- Token, cost, and latency breakdowns.
- Failure clusters across repositories and worker versions.

### Implementation direction

- Define a versioned, append-only event envelope with run, step, attempt, and correlation IDs.
- Redact secrets at event creation rather than only in the UI.
- Keep large artifacts outside the event stream and reference them by digest.
- Distinguish state reconstruction replay from live re-execution.
- Add OpenTelemetry-compatible export after local event semantics stabilize.
- Define retention, deletion, and access-control behavior.

### Definition of done

- Run state can be reconstructed from persisted events and artifacts.
- A replay can reproduce scheduling and policy decisions without invoking models.
- Sensitive values are absent from stored events and exports.
- The CLI remains fully usable when the dashboard is not installed.

## 11. Agent evaluation and benchmarking

### Problem

Changes to prompts, models, workers, or orchestration logic can improve one example while silently degrading others. Lumos needs repeatable evidence for quality, reliability, speed, and cost.

### Proposed capability

Create evaluation suites containing fixture repositories, ticket specifications, expected constraints, and scoring rules. Compare worker or workflow variants under controlled conditions.

```yaml
suite: bug-fix-baseline
cases:
  - fixture: fixtures/python-null-crash
    ticket: tickets/null-crash.md
    assertions:
      - command_succeeds: "pytest -q"
      - forbidden_paths_unchanged: ["vendor/**"]
      - requirement_coverage_at_least: 1.0
```

Scores may cover task success, test results, requirement coverage, policy compliance, unnecessary diff size, retries, latency, tokens, and cost. Model-based judges should supplement—not replace—deterministic checks.

### Implementation direction

- Define immutable fixtures and hermetic setup/teardown.
- Record model, executor, prompt, worker, and Lumos versions for each result.
- Support repeated trials for nondeterministic systems.
- Separate deterministic assertions from rubric-based judgments.
- Add baseline comparison and regression thresholds for CI.
- Publish representative open benchmark suites without embedding secrets or proprietary code.

### Definition of done

- The same suite can compare two workflow or worker versions.
- Results show uncertainty and trial count, not only a single aggregate score.
- CI can fail on declared quality, cost, or reliability regressions.
- Evaluation artifacts are sufficient to investigate failed cases.

## 12. Multi-repository ticket orchestration

### Problem

Many features cross service, client, infrastructure, schema, and documentation repositories. Treating each repository as an unrelated ticket loses dependency ordering and makes coordinated delivery difficult.

### Proposed capability

Allow a parent run to coordinate child repository runs with explicit dependencies, revisions, integration policies, and delivery links.

```yaml
repositories:
  api:
    path: ../service-api
  web:
    path: ../web-client
  docs:
    path: ../product-docs

workflow:
  steps:
    - id: api-change
      repository: api
      worker: coder
    - id: web-change
      repository: web
      worker: coder
      needs: [api-change]
    - id: docs-change
      repository: docs
      worker: documenter
      needs: [api-change, web-change]
```

### Implementation direction

- Introduce parent and child run identifiers with cross-repository dependency state.
- Pin every repository to a base revision at planning time.
- Reuse workspace isolation and policy evaluation independently per repository.
- Define cross-repository artifacts such as generated API schemas or package versions.
- Support coordinated but separate pull requests, with links and dependency metadata.
- Design partial failure and rollback behavior before enabling automatic integration.

### Definition of done

- Each repository retains an independent audit trail, workspace, policy set, and pull request.
- Cross-repository dependencies are explicit and resumable.
- A failed child run cannot leave the parent falsely marked complete.
- Delivery output links all related changes and states their required merge order.

## Cross-cutting implementation requirements

The following requirements apply across the roadmap and should be considered when opening any feature epic.

### Security and privacy

- Use named secret references rather than embedding credentials in configuration.
- Redact sensitive values before logs, events, reports, and model context are persisted.
- Apply least-privilege scopes to executors, tracker adapters, and installed workers.
- Treat ticket content, repository files, worker packages, and model output as untrusted input.
- Document the trust boundary for local, hosted, and third-party components.

### Configuration and compatibility

- Version public configuration, run state, reports, events, and extension contracts.
- Reject unknown or invalid fields with precise source locations where practical.
- Publish migration notes and automated migrations for breaking schema changes.
- Define precedence among CLI arguments, project files, user settings, and environment values.
- Preserve sensible defaults, including the default `TC#` ticket reference convention.

### Idempotency and recovery

- Give runs, steps, attempts, external mutations, and webhook deliveries stable identifiers.
- Make resume behavior explicit and safe after process termination or network failure.
- Check external state before retrying issue comments, branches, commits, or pull requests.
- Retain enough evidence to distinguish completed, failed, cancelled, skipped, and uncertain work.

### Extensibility

- Keep core contracts small, typed, documented, and versioned.
- Publish capability discovery so extensions can declare optional features.
- Provide reusable conformance tests for executors, trackers, and workers.
- Keep provider-specific payloads available for diagnostics without leaking them into core logic.

### Testing

- Unit-test schema validation, graph scheduling, policy evaluation, and state transitions.
- Use contract tests for every adapter implementation.
- Add integration tests using local fakes before relying on live services.
- Maintain end-to-end fixtures for interruption, retry, conflict, cancellation, and resume paths.
- Add failure injection for network errors, malformed worker reports, and partial external mutations.

## Turning an idea into an implementation epic

Before starting one of these features, create a design issue or proposal that answers:

1. What user problem and concrete scenarios are in scope?
2. Which public contracts or configuration schemas change?
3. What are the security, permission, and data-retention implications?
4. How does interruption, retry, cancellation, and resume behave?
5. What must remain backward compatible?
6. Which telemetry proves that the feature works in production?
7. What is the smallest end-to-end slice that validates the design?
8. Which unit, contract, integration, and end-to-end tests are required?

Each epic should be split into contract/design work, one vertical implementation slice, hardening, documentation, and additional adapters or integrations. Avoid implementing several providers before the common contract has been proven by at least one complete workflow.

## Recommended next epics

If no user feedback changes the priority, the next major epics should be:

1. **Reliable autonomous execution:** executor protocol, capability discovery, cancellation, and normalized results.
2. **Isolated workspaces:** safe per-run worktrees, conflict handling, recovery, and cleanup.
3. **Workflow graph engine:** dependencies, concurrency controls, joins, and resumable node state.
4. **Specification traceability:** stable acceptance-criterion IDs, evidence, coverage reports, and completion gates.
5. **Model routing and governance:** budgets, escalation, policy evaluation, and approval gates.
6. **Developer ecosystem:** extension manifests, lock files, installer, conformance suites, and registry design.
7. **Operations platform:** event intake, observability, replay, evaluations, and multi-repository coordination.

The exact order should be revisited after each phase using adoption data, failure patterns, and feedback from extension authors.
