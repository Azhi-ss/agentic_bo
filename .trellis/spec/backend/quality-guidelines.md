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
- Autonomous typed-tool descriptions own stable local semantics: `suggest` reads the current posterior without committing or updating state; `score` returns acquisition utility; `predict` returns posterior mean/variance; diagnostics assess reliability rather than select Candidates; trials are verified observed evidence; deterministic Candidate pool order is not ranking evidence.
- The autonomous system and per-Step prompts own cross-tool workflow guidance. They include every autonomous query tool, keep tool order and `score`/`predict` use non-binding, require interpreting a verified Observation before refreshed posterior advice, and challenge mechanical query repetition through strategy/hypothesis/region changes rather than fixed tool-call gates.

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
- Node prompt/tool tests assert autonomous query-tool availability, semantic separation of `suggest`/`score`/`predict`, observation-before-refresh guidance, and advisory anti-inertia language without imposing a fixed call order.
- Smoke: run/export a budget-2 autonomous campaign only after preflight, then validate the exported trajectory against the public dataset.

#### Surrogate Trust Assessment

- Every autonomous `commit_candidate` requires:
  - `surrogate_trust`: `low | medium | high`;
  - `surrogate_trust_rationale`: non-empty current-step diagnostic evidence or an explicit reason re-diagnosis is unnecessary;
  - `search_mode`: `exploit | targeted_exploration | global_exploration`;
  - `decision_goal`: `incumbent_improvement | decision_information`;
  - `result_use`: the concrete next action or candidate-ranking change caused by the result.
- `decision_information` additionally requires non-empty `follow_up_if_supported` and `follow_up_if_refuted`; missing branches fail deterministic Decision Evidence validation before budget spend.
- `incumbent_improvement` additionally requires finite `expected_objective_value`. Validation computes the direction-aware global incumbent from every verified observed historical and Campaign trial and rejects values that do not strictly improve it. If no finite target observation exists, the finite declaration is accepted without an incumbent comparison.
- Local matched-context or transport improvement is `decision_information` unless its expected objective strictly beats that global incumbent.
- `low` trust does not forbid GP use. If `surrogate_relationship=accept`, the rationale must name independent support: a prior, verified Receipt/Observation, bounded region, or equivalent independent evidence. GP rank or posterior mean alone is insufficient.
- Search-mode meanings are fixed:
  - `exploit`: refine a region supported by a verified Campaign Observation;
  - `targeted_exploration`: observations or domain prior define a plausible region and GP may assist inside it;
  - `global_exploration`: neither observations nor prior justify a region, so coverage or uncertainty dominates.
- For autonomous competition runs, `cross_context_uncovered`, `scope_overreach`, and a low-trust GP override streak remain persisted telemetry; none independently triggers a correction retry.
- Middle-stage global exploration is challenged when it is outside the acquisition shortlist or lacks executable supported/refuted follow-ups. Terminal information work is challenged when no later budget slot can use it. Late non-exploit candidates outside the shortlist are challenged.
- Competition challenges use the existing bounded autonomous advisory retry path: two correction attempts, then persist the final otherwise-valid commitment with `advisory_outcome=exhausted_accepted`. Deterministic validation remains hard.
- `surrogate_trust` and `search_mode` are audit fields, not numeric universal gates. Do not derive a universal trust threshold from one dataset.
- Deterministic validation rejects missing/invalid enums, missing decision-use fields, and low-trust GP acceptance without named independent evidence. Behavioral consistency remains a trajectory/session review concern.
- Direct Supervisor `lenz trials --state <path>` calls intentionally omit filters and pagination to receive the CLI's complete historical + Campaign observed set; the paginated autonomous `lenz_trials` tool is only the model-facing inspection surface.
- Node tests must inspect the autonomous `commit_candidate` TypeBox schema, prompt calibration clauses, invalid enums, direction-aware global-incumbent boundaries, local-baseline classification, no-finite-incumbent behavior, decision-information branches, telemetry/challenge separation, bounded retry behavior, and justified low-trust acceptance.

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
- The runtime policy mode (`autonomous`) must be passed explicitly from the CLI/supervisor boundaries down through to `verifyOptimizationPolicy` to decouple live direct-runs from offline manifest declarations. Manifest-based inference for `experiment_policy` is reserved strictly for offline trajectory replay and artifact validation.
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

## Scenario: Matrix Experiment Configuration, Resume, and Competition Packaging

### 1. Scope / Trigger

- Trigger: an authored YAML matrix is planned or executed, an existing Campaign directory is resumed, or competition `.pt` artifacts are produced from Campaign Frames.
- This cross-layer contract spans strict YAML, Python CLI orchestration, manifest/Frame/run-audit provenance, the Node Supervisor's Frame/session/receipt reconciliation, and offline artifact validation.
- Schema version 1 is exactly `policies × seeds` with shared settings; per-run overrides are forbidden.

### 2. Signatures

- `boagent experiment --config <yaml> [--plan] [--resume]`
- `load_experiment_config(path: Path, *, check_output_collisions: bool = True) -> LoadedExperiment`
- `validate_experiment_campaign(campaign: Path, loaded: LoadedExperiment, item: dict[str, object]) -> None`
- `boagent package-competition --config <yaml> --destination <dir> [--seed <int> ...]`
- `package_competition(loaded: LoadedExperiment, destination: Path, seeds: tuple[int, ...]) -> dict[str, object]`
- `validate_artifact(path: Path, dataset_root: Path, seed: int) -> SeedResult`
- `SeedResult(seed: int, state: Literal["complete", "incomplete", "invalid"], detail: str, artifact: str | None = None, steps: int = 0)`

### 3. Contracts

- Paths resolve relative to the YAML file, while canonical hash material preserves authored POSIX paths and excludes machine-specific absolute paths.
- `--plan` validates and expands policies/seeds in authored order without creating directories or starting a provider.
- Execute mode records source and normalized hashes and passes provider/model/thinking/policy explicitly. Declared config hash is immutable provenance; effective acquisition changes remain separate runtime revisions.
- Omitted `--resume` keeps fail-closed collision checks. `--plan` and `--resume` disable loader collision preflight, but execute mode still rejects a post-preflight collision unless resume was explicitly requested.
- Resume processes `LoadedExperiment.runs()` sequentially in authored policy × seed order. A missing directory is initialized through `initialize_campaign`; an existing directory must pass `validate_experiment_campaign`; both then dispatch through `run_campaign`.
- Every existing Campaign considered for resume, including an audited legacy Campaign, requires `manifest.json`, `frame/state.json`, and `.receipt-key`, plus matching Campaign id and exact dataset path, seed, budget, target, and direction. Current-format Campaigns additionally require exact experiment name/policy, source filename/hash, normalized/declared hash, and initial acquisition.
- Legacy mode is selected only when manifest fields `experiment_name`, `experiment_policy`, `source_config`, `source_config_hash`, and `normalized_config_hash`, plus Frame fields `experiment_name`, `experiment_policy`, `source_config`, `source_config_hash`, and `declared_config_hash`, are all absent. Manifest `initial_runtime` and Frame `initial_acquisition` must also be absent; configuration revision, acquisition name, and beta must match the authored initial configuration. The latest `campaign-run-config.json` revision must match Campaign id, provider, model, thinking, policy, and unavailable provider-generation seed; its `declared_config_hash` and `experiment_name` must be null, while `experiment_policy` must equal the authored policy. Mixed or unaudited legacy state is rejected.
- Python calls `run_campaign` for both partial and terminal valid Campaigns. The existing Supervisor owns receipt/session reconciliation and terminal-status skip before provider startup; Python does not duplicate that validator.
- Packaging is offline: it reads `frame/state.json` and public `test_features.csv`, never starts a provider and never reads `test.csv`.
- The loaded config must declare exactly seeds `100..2000` by 100 and budget 40 even for subset packaging. Requested seeds must be unique members of that set; omission means all 20.
- Each complete artifact is `seed_<N>.pt` with top-level `seed`, `dataset`, `target`, `direction`, and `trajectory`. The trajectory has exactly 40 ordered rows with `step=1..40`, unique in-range integer `query_index`, exact full-row `condition`, numeric non-boolean `observed_value`, and non-empty `candidate_id`, `trial_id`, and `receipt_id`.
- Report `ok` is true only when every requested seed is `complete`, no expected artifact is missing, and the destination `.pt` filename snapshot taken when packaging begins contains no extra name.

### 4. Validation & Error Matrix

- Unknown YAML field, unsupported schema/enums, duplicate policy/seed, invalid positive budget/beta, missing dataset/public input, or secret/hidden key -> fail before mutation; validation identifies field paths without echoing secret values or full YAML.
- Omitted `--resume` plus any existing output -> collision error; no Campaign is initialized or run.
- Existing directory without required manifest/Frame/key -> CLI parameter error before initialization or Supervisor dispatch.
- Malformed metadata, manifest/Frame identity mismatch, current provenance mismatch, or legacy audit mismatch -> field-specific CLI parameter error; existing files remain untouched and no provider starts.
- Config seed list/budget differs from competition constants, or requested seeds are duplicate/out of range -> packaging `ValueError`.
- Missing Frame, pending trials, or fewer than 40 observed trials at budget 40 -> seed `incomplete`.
- Frame load failures caught by `package_competition` (`OSError`, `ValueError`, `TypeError`, or `json.JSONDecodeError`), wrong Campaign seed/dataset, wrong budget, more than 40 observations, duplicate/out-of-range index, condition mismatch, missing provenance, or invalid observed value -> seed `invalid`. Other exceptions escaping `Study.load`, including an uncaught missing-field `KeyError`, are not assigned a per-seed state by the current implementation.
- Artifact load/schema/seed/dataset/40-step/index/condition/modern-field failure -> `validate_artifact` returns `invalid`.
- Missing expected artifacts, or extra `.pt` filenames present when packaging begins, make the manifest invalid, report `ok=false`, and CLI exit 1.

### 5. Good/Base/Bad Cases

- Good: one checked-in YAML plans deterministically; rerunning `experiment --resume` lets matching terminal Campaigns reach Supervisor skip, matching partial Campaigns reconcile, and missing Campaigns initialize in order; packaging then yields an exact valid manifest.
- Base: direct `boagent init`/`run` remains compatible, and a fresh `experiment` without `--resume` retains strict collision rejection. Repeated `--seed` may package an explicit pilot subset while YAML still declares the full competition matrix.
- Bad: silently override authored model/policy, start one run before detecting a planned collision, overwrite mismatched Campaign state, duplicate terminal validation in Python, package a verified early stop, map against `searchspace.csv`, accept shortened conditions, or ignore stale extra `.pt` files.

### 6. Tests Required

- Config: strict schema, CWD-independent paths/hash, authored-order expansion, whole-plan collision preflight, side-effect-free plan, direct CLI compatibility, and secret-safe errors.
- Resume: missing initialization; matching dispatch without reinitialization; audited-legacy acceptance; legacy audit mismatch rejection; current manifest/Frame mismatch rejection without mutation; unchanged default and post-preflight collision rejection.
- For every resume rejection, assert `initialize_campaign` and `run_campaign` were not called; for mismatch, assert manifest and Frame bytes are unchanged.
- Packaging: subset schema and 40 steps; full-mode missing 19 seeds; short Frame=`incomplete`; wrong budget=`invalid`; pending/duplicate/condition/range/provenance failures; non-numeric observation rejection; stale extra manifest rejection; JSON report and CLI exit 1.
- Supervisor tests must retain terminal skip and Frame/session/signed-receipt reconciliation because Python resume delegates those decisions.
- Full-package smoke assertions: `ok is True`, exactly `seed_100.pt` through `seed_2000.pt`, and every `validate_artifact` result is `complete` with 40 steps.

### 7. Wrong vs Correct

#### Wrong

```python
if campaign.exists():
    shutil.rmtree(campaign)
initialize_campaign(...)
```

#### Correct

```python
if campaign.exists():
    validate_experiment_campaign(campaign, loaded, item)
else:
    initialize_campaign(...)
run_campaign(campaign, model=item["model"], thinking=item["thinking"], policy=item["policy"])
```