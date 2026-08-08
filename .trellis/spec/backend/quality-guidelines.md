# Quality Guidelines

> Code quality standards for backend development.

---

## Overview

<!--
Document your project's quality standards here.

Questions to answer:
- What patterns are forbidden?
- What linting rules do you enforce?
- What are your testing requirements?
- What code review standards apply?
-->

(To be filled by the team)

---

## Forbidden Patterns

<!-- Patterns that should never be used and why -->

(To be filled by the team)

---

## Required Patterns

<!-- Patterns that must always be used -->

(To be filled by the team)

---

## Testing Requirements

<!-- What level of testing is expected -->

(To be filled by the team)

---

## Code Review Checklist

<!-- What reviewers should check -->

(To be filled by the team)


## Scenario: Autonomous Campaign Profiles

### 1. Scope / Trigger

- Trigger: a campaign adds a selectable Supervisor profile or exposes new label-free candidate/evidence fields across Python, Node, and reporting.
- Keep omitted `--policy` behavior identical to `default`; experimental profiles must be explicit.

### 2. Signatures

- `boagent run --campaign <path> [--model <id>] [--thinking <level>] [--policy default|autonomous_agent]`
- `lenz candidates --state <path> [--filters <json>] [--cursor <int>] [--limit <1..100>]`
- `lenz score --state <path> --configs <json> [--acqf <name>] [--beta <number>]`

### 3. Contracts

- `candidates` reads only `test_features.csv`, preserves original pool order, accepts exact legal scalar/list filters, and returns only pagination plus `pool_index`, exact `candidate_id`, and `config`.
- Autonomous Candidate Inspection returns at most 100 rows per call and 500 rows per Campaign Step; failed calls do not count as successful evidence.
- Autonomous prompts and initial context use explicit allowlists: no persisted manifest spreading, dataset paths, labels, ranked initial proposals, or full historical rows.
- The leakage preflight runs before model runtime creation and verifies prompt/context/tool surfaces, runtime isolation, and prior audit metadata.
- Autonomous tools omit stop, permanent bounds, objectives, and constraints; acquisition/beta remain mutable.
- Decision Evidence Record classification derives from successful tool results accumulated across every corrective action attempt in the current Step.
- A transient provider retry is allowed only before any successful mutation or campaign action in that turn.
- `campaign-run-config.json` records policy, prompt/config/code/prior hashes, prior scan/provenance, provider-generation-seed limitation, and leakage result.
- A completed budget-2 run has two exact public Candidate decisions, two valid matching signed Receipts, a complete session/events trace, and explicit transient retry evidence when retries occurred.

### 4. Validation & Error Matrix

- Unknown `--policy` -> CLI/Supervisor error.
- Unknown feature/value, invalid cursor/limit, or more than 500 returned rows in a Step -> Candidate Inspection error.
- Candidate `pool_index`/`config` mismatch or already-observed Candidate -> rejection before submit/Oracle and no budget spend.
- Decision Evidence Record relationship inconsistent with successful tool use -> correction retry with prior Step evidence retained.
- Forbidden prompt/tool/context field or enabled resource surface -> fail before model runtime/provider startup.
- Missing/mismatched/invalidly signed Receipts, incomplete trace, or trajectory length other than two -> report integrity failure.

### 5. Good/Base/Bad Cases

- Good: Sara inspects any public evidence she chooses, commits an exact unobserved Candidate with truthful evidence classification, incorporates Receipt 1, then completes Step 2.
- Base: omit `--policy`; the existing Paper Prompt, automatic low-trust acquisition switch, and stop semantics remain active.
- Bad: reset evidence after a rejected action, count a failed tool result as consulted evidence, infer a Candidate identity, silently fall back to a GP proposal, or report unsigned/incomplete evidence as successful.

### 6. Tests Required

- Python: exact Candidate filtering/identity, omitted/default policy, prior metadata, report trace/retry/integrity extraction, and incomplete evidence rejection.
- Node: standalone prompt/context allowlist, autonomous tool surface, 500-row reset, successful evidence tracking across correction attempts, retry mutation barrier, and leakage fail-closed behavior.
- Smoke: run/export a budget-2 autonomous campaign only after preflight, then validate the exported trajectory against the public dataset.

#### Surrogate Trust Assessment

- Every autonomous `commit_candidate` requires:
  - `surrogate_trust`: `low | medium | high`;
  - `surrogate_trust_rationale`: non-empty current-step diagnostic evidence or an explicit reason re-diagnosis is unnecessary;
  - `search_mode`: `exploit | targeted_exploration | global_exploration`.
- `low` trust does not forbid GP use. If `surrogate_relationship=accept`, the rationale must name independent support: a prior, verified Receipt/Observation, bounded region, or equivalent independent evidence. GP rank or posterior mean alone is insufficient.
- Search-mode meanings are fixed:
  - `exploit`: refine a region supported by a verified Campaign Observation;
  - `targeted_exploration`: observations or domain prior define a plausible region and GP may assist inside it;
  - `global_exploration`: neither observations nor prior justify a region, so coverage or uncertainty dominates.
- `surrogate_trust` and `search_mode` are audit fields, not numeric hard gates. Do not derive a universal trust threshold from one dataset.
- Deterministic validation rejects missing/invalid enums and low-trust GP acceptance without named independent evidence. Behavioral consistency between declared `search_mode` and actual Candidate inspection remains a trajectory/session review concern.
- Node tests must inspect the autonomous `commit_candidate` TypeBox schema, prompt calibration clauses, invalid enums, thin low-trust acceptance, and justified low-trust acceptance.

##### Wrong

```text
cv_r2 is negative; GP rank 1 is best, so accept it.
```

##### Correct

```text
surrogate_trust=low; search_mode=targeted_exploration. The verified/high-yield local region and domain prior independently support this Candidate; GP rank is advisory within that region.
```

#### Campaign Provider Environment

- `boagent init` and `boagent run` build subprocess environments through `src/boagent/agent_cli.py::project_env()`.
- `project_env()` loads the repository-root `.env` with `load_dotenv(..., override=False)` before copying `os.environ`; an explicitly exported environment variable always wins over `.env`.
- Project `.pi/models.json` resolves the `ai-modeling` credential from `$OPENAI_API_KEY`. OMP provider configuration under `~/.omp/agent/models.yml` is a separate store and is not automatically visible to the embedded Pi `ModelRuntime`.
- Tests must prove both `.env` fallback and exported-variable precedence using synthetic values only. Never print or snapshot a real credential.

##### Wrong

```text
Assume OMP's configured ai-modeling key is automatically inherited by boagent's embedded Pi runtime.
```

##### Correct

```text
Load repo .env without override, copy the resulting environment, and pass it explicitly to the Supervisor subprocess.
```

### 7. Wrong vs Correct

#### Wrong

```text
The model used score in an earlier rejected attempt, but the final trajectory says not_consulted because per-attempt evidence was reset.
```

#### Correct

```text
Successful Step evidence accumulates until a valid Commitment, and reporting cross-checks the complete session trace and signed Receipts.
```