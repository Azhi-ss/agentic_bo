# Competition Runner Readiness Audit

## Verdict

**Not directly submittable.** Core candidate identity, non-repetition, row-order mapping, Frame/receipt provenance, and a modern `.pt` exporter exist, but the checked-in competition configuration and reporting path do not implement the required 20-seed/40-step submission contract. The existing exporter also permits verified early-stop artifacts shorter than 40 steps, while the competition requires exactly 40.

Blocking levels:

- **P0**: generated submission can violate a hard competition constraint or cannot be produced by the checked-in workflow.
- **P1**: required submission assurance is absent or an adjacent official path encodes a conflicting protocol.
- **P2**: evidence/coverage weakness that should be closed before trusting a full provider run.

## Pass

### P0-pass — `query_index` is defined by `test_features.csv` row order, not `searchspace.csv`

- `src/boagent/cli.py::load_candidates` reads only `test_features.csv`; `config_at`, `candidates`, `suggest`, `submit`, `predict`, and `score` all retain its pandas index as `pool_index`/`query_index` (`src/boagent/cli.py:30-45, 170-209, 215-268, 274-314, 462-507`).
- `src/boagent/oracle.py::run` resolves both public and private outcome rows with `trial.query_index` against `test_features.csv` and `test.csv` (`src/boagent/oracle.py:64-73`).
- `src/boagent/evaluation.py::validate_trajectory` validates `query_index` and `condition` against `test_features.csv` (`src/boagent/evaluation.py:21-34`).
- No runtime or test reference to `searchspace.csv` exists under `src/`, `benchmark/`, `supervisor/`, or `tests/`.
- Dataset evidence shows why this matters: Buchwald has 783 `test_features.csv` rows versus 790 `searchspace.csv` rows; only 187 same-index feature rows match. The current runtime correctly chooses `test_features.csv`.
- Test evidence: `tests/test_cli_contract.py::test_candidates_are_label_free_filtered_and_paginated` asserts pool indices 0 and 1; `tests/test_cli_contract.py::test_submit_rejects_mismatched_candidate_identity` asserts index/config binding.

### P0-pass — condition is bound exactly to the selected candidate row

- `src/boagent/cli.py::submit` computes `expected = config_at(candidates, pool_index, study.features)` and rejects unequal mappings (`src/boagent/cli.py:283-289`).
- Autonomous Supervisor performs a second exact-row fetch and Node deep equality check before submission (`supervisor/supervisor.mjs:243-248`).
- Oracle performs two further checks: trial config equals the public row, and the corresponding private row features equal the trial config (`src/boagent/oracle.py:64-73`).
- Export uses `condition: trial.config`, preserving the Frame-bound candidate (`src/boagent/agent_cli.py:253-269`).
- Final validation compares exported `condition` with `candidates.loc[index].to_dict()` (`src/boagent/evaluation.py:26-34`).
- Test evidence: `tests/test_cli_contract.py::test_submit_rejects_mismatched_candidate_identity`; `supervisor/campaign.test.mjs` tests exact index/config identity, key-order tolerance, nested-value comparison, and autonomous exact-candidate behavior.

### P0-pass — duplicate `query_index` values are rejected within a run

- `Study.submitted` is the set of campaign `query_index` values (`src/boagent/state.py:125-127`).
- Suggestion paths remove submitted indices (`src/boagent/cli.py:248-257`).
- `src/boagent/cli.py::submit` rejects an index already in `Study.submitted` (`src/boagent/cli.py:296-301`).
- Supervisor additionally checks already verified `pool_index`/`candidate_id` before submission (`supervisor/campaign.mjs:236-249`).
- Export validation has an independent `seen` set and rejects duplicates (`src/boagent/evaluation.py:22-34`).
- Test evidence: `supervisor/campaign.test.mjs` tests rejection of an already observed pool index and candidate id; Python contract suite tests submit identity and budget behavior.

### P1-pass — the YAML schema accepts an explicit 20-seed list

- `Experiment.seeds` is an arbitrary non-empty strict `list[int]`; only duplicates are forbidden (`src/boagent/experiment_config.py:23-37`).
- `LoadedExperiment.runs` expands every authored seed (`src/boagent/experiment_config.py:78-101`).
- Audit-only validation of `[100, 200, ..., 2000]` succeeded: 20 seeds, first 100, last 2000, budget 40.
- Existing tests prove explicit list expansion and duplicate rejection, though only with five seeds (`tests/test_experiment_config.py::test_loads_strict_yaml_and_expands_authored_matrix`, `::test_rejects_invalid_duplicates_missing_dataset_and_output_collisions`).

### P1-pass — Buchwald training data is not collapsed to one product

- Dataset evidence: `datasets/chemical_reactions/buchwald_sub4/train.csv` has exactly 35 rows and 5 products, seven rows each.
- `src/boagent/cli.py::create` converts every training row into a historical Trial and derives categories from all train and candidate rows (`src/boagent/cli.py:126-164`).
- `src/boagent/agent_cli.py::summarize_dataset` summarizes every feature and does not filter to one product (`src/boagent/agent_cli.py:34-54`).
- The only context-role heuristic marks a feature as context only when the candidate pool has one value and training has multiple (`src/boagent/agent_cli.py:40-42`). Buchwald's competition candidate pool has one product, but all 35 training observations remain available to the model; no single-product training assumption was found.
- Test evidence: `tests/test_cli_contract.py::test_init_gives_agent_a_leak_free_dataset_summary` covers differing train products and a single candidate-pool product without dropping training rows.

### P1-pass — Frame, trajectory, and receipt identity are traceable end to end

- Frame schema records `query_index`, exact config, candidate id, request id, receipt id, metrics, seed, budget, features, and provenance (`src/boagent/state.py::Trial`, `::Study`).
- Supervisor journals intent before submission, reconciles interrupted runs from Frame, invokes the oracle, observes the signed receipt, and persists metrics (`supervisor/supervisor.mjs:112-153, 267-296`; `supervisor/campaign.mjs::reconcileTrajectory`).
- Oracle receipts are HMAC-signed and bind campaign, trial, candidate, request, status, and metrics (`src/boagent/oracle.py:18-25, 47-92`).
- `lenz observe` verifies signature and all receipt identity fields before changing Frame (`src/boagent/cli.py:320-359`).
- `benchmark/compare.py::_experiment_run` cross-checks trajectory, Frame, receipt filenames/signatures/identity, session trace, and Supervisor event trace (`benchmark/compare.py:106-172`).
- Test evidence: `tests/test_benchmark_compare.py::test_experiment_report_aggregates_action_and_two_step_metrics`, `::test_experiment_report_rejects_missing_receipt_or_session_trace`, plus Supervisor reconciliation and receipt tests.

### P1-pass — a modern `.pt` exporter already exists

- `boagent export` loads the Frame and writes a Torch artifact with top-level `seed`, `dataset`, `target`, `direction`, and `trajectory`; each row contains `step`, `query_index`, `condition`, `observed_value`, `candidate_id`, `trial_id`, and `receipt_id` (`src/boagent/agent_cli.py:223-270`).
- `src/boagent/evaluation.py::validate_trajectory` recognizes this modern schema when `target` is present and reads `observed_value` (`src/boagent/evaluation.py:13-62`).
- Test evidence: `tests/test_cli_contract.py::test_export_writes_target_direction_and_observed_value` loads the `.pt` and checks the modern fields.

## Gap

### P0 — no checked-in competition config defines the required seeds and budget together

- Required seeds: `[100, 200, ..., 2000]`, budget 40.
- Checked configs are:
  - `experiment-configs/suzuki-autonomous-agent.yaml`: seeds 300-304, budget 2.
  - `experiment-configs/suzuki-autonomous-agent-budget40-seed300.yaml`: seed 300 only, budget 40.
- Neither is a competition matrix, and no per-dataset competition YAMLs were found.
- Result: `boagent experiment --config ...` cannot currently produce the mandated 20 campaigns per dataset from a checked-in submission config.

### P0 — experiment execution does not produce the required `seed_<N>.pt` files

- `LoadedExperiment.runs` creates campaign directories named `<output>/<policy>/seed-<N>` (`src/boagent/experiment_config.py:78-101`).
- `boagent experiment` initializes and runs each campaign but never calls `boagent export` (`src/boagent/agent_cli.py:189-220`).
- `.pt` production is a separate manual command requiring both campaign and output path (`src/boagent/agent_cli.py:223-270`).
- Therefore the matrix runner does not yield 20 `seed_<N>.pt` artifacts per dataset, and there is no batch exporter/packager enforcing their names or count.
- `src/boagent/runner.py` and `benchmark/run_gp.py` do write `seed_<N>.pt`, but they are separate legacy/baseline paths, not the current `boagent init/run` Supervisor campaign path. `src/boagent/runner.py` is also incompatible with the current `lenz submit/observe` CLI signatures (`--query-index`/raw metrics versus required `--pool-index`, config, request id, and signed receipt), so it is not a viable submission runner.

### P0 — exporter allows fewer than exactly 40 steps

- Competition requires every PT to contain exactly 40 steps.
- `boagent export` explicitly accepts a verified non-empty early stop when observed trials are below budget (`src/boagent/agent_cli.py:227-269`).
- `validate_trajectory` also accepts verified non-empty early-stop artifacts shorter than the requested budget (`src/boagent/evaluation.py:17-20`).
- Test evidence explicitly locks this behavior: `tests/test_evaluation.py::test_accepts_verified_non_empty_early_stop`; `tests/test_cli_contract.py::test_export_rejects_zero_observation_early_stop` implies positive early stop is allowed.
- The autonomous profile disables early stop (`supervisor/supervisor.mjs:200-202`; `supervisor/campaign.test.mjs::autonomous tools omit permanent domain mutation and early stop`), which reduces operational risk only for that policy. The exporter/validator still do not enforce the competition artifact contract.

### P0 — existing benchmark report hard-codes a two-step, five-seed protocol

- `benchmark/compare.py::_experiment_run` requires exactly two trajectory entries and two matching receipts (`benchmark/compare.py:106-128`).
- `EXPERIMENT_SEEDS` is `[300, 301, 302, 303, 304]`; report text says “Descriptive five-seed comparison” (`benchmark/compare.py:75-77, 175-191`).
- Tests lock two-step/five-seed assumptions (`tests/test_benchmark_compare.py::test_experiment_plan_comes_from_checked_in_config_and_refuses_existing_directories`, `::test_experiment_report_aggregates_action_and_two_step_metrics`).
- This report cannot certify 20 files × 40 steps and would mark valid competition campaigns failed.

### P1 — the general evaluation protocol still encodes ten seeds, not twenty

- `src/boagent/evaluation.py::SEEDS` is `range(100, 1001, 100)`, only 10 seeds (`src/boagent/evaluation.py:10`).
- `tests/test_evaluation.py::test_paper_protocol_uses_ten_seeds_and_median_iqr` explicitly asserts length 10.
- The validator can be called on arbitrary files, but the official constant/test conflicts with the competition seed contract and cannot serve as submission assurance.

### P1 — no test proves the exact competition seed set, 20 output filenames, or 40-row modern exports

- Config tests cover five seeds and budget 2.
- Export test covers one observation.
- Validation tests cover one/two steps and early-stop behavior.
- No test scans a dataset output directory for exactly `seed_100.pt` through `seed_2000.pt`, rejects extra/missing seeds, or validates every file at budget 40.

### P1 — no checked-in Buchwald competition config or end-to-end dry plan

- The loader is dataset-generic and current code does not collapse Buchwald training products, but all checked experiment YAMLs point to Suzuki.
- There is no plan-mode evidence for Buchwald showing 20 runs, budget 40, and collision-free output paths.
- This is a release packaging gap rather than a discovered multi-product runtime bug.

### P2 — output naming conventions are inconsistent across paths

- Campaign directories use `seed-<N>`.
- Required PT files use `seed_<N>.pt`.
- Legacy agent runner and GP baseline use `seed_<N>.pt` automatically (`src/boagent/runner.py:142-143`; `benchmark/run_gp.py:78-79`).
- Modern `boagent export` accepts any caller-supplied filename and does not enforce the required name (`src/boagent/agent_cli.py:223-270`).

## Unknown

### P1 — exact external competition PT schema beyond the stated fields

- The repository has two PT schemas:
  - Legacy: rows use `observed_yield` (`src/boagent/runner.py`, `tests/test_evaluation.py`).
  - Modern exporter: rows use `observed_value` and include target/direction and provenance ids (`src/boagent/agent_cli.py::export`).
- Internal `validate_trajectory` accepts both, but no external competition schema/specification or sample artifact is present in the audited repository.
- Unknown: whether the judge expects `observed_yield`, `observed_value`, only `{query_index, condition}`, a list rather than a dict, or additional dataset/method metadata.
- **Minimal converter design if external schema differs (do not implement until the judge schema is known):** a single offline command that reads each campaign's `frame/state.json`, requires `study.budget == 40`, no pending trials, exactly 40 observed campaign trials, exact seed membership, unique indices, and row equality against `test_features.csv`; then maps the already verified `boagent export` payload to the judge's exact key names and writes `<dataset>/seed_<N>.pt`. It should finish with a directory-level manifest check for exactly the 20 required filenames. No provider calls and no new campaign model are needed.

### P2 — full 40-step behavior on all competition datasets

- No real provider experiment was run, per audit constraint.
- Unit/contract evidence establishes identity and budget guards, but does not prove that every dataset has at least 40 valid unobserved candidates after initialization, that the provider completes 40 autonomous decisions, or that runtime/resource limits are acceptable.
- Buchwald has 783 public candidates, so candidate exhaustion before 40 is not suggested by row count; this remains runtime evidence, not a code-contract blocker.

### P2 — all competition dataset names and expected directory layout

- The repository contains multiple datasets, but the request does not include the authoritative competition dataset list or required archive layout. Readiness can be judged for the stated per-dataset contract, not completeness of a final submission bundle.

## End-to-end data-flow trace

1. YAML `experiment.seeds`/`budget` → strict Pydantic config → Cartesian run list (`src/boagent/experiment_config.py`).
2. `boagent experiment` → `initialize_campaign` → manifest/TASK/CAMPAIGN → `lenz create` Frame with all train rows as historical Trials and `test_features.csv` as the candidate pool (`src/boagent/agent_cli.py`, `src/boagent/cli.py::create`).
3. `boagent run` → Node Supervisor → typed candidate tools over the Frame (`src/boagent/agent_cli.py::run_campaign`, `supervisor/supervisor.mjs`).
4. Candidate decision `(pool_index, config)` → exact public-row checks → `lenz submit` → pending Frame Trial (`supervisor/supervisor.mjs`, `src/boagent/cli.py::submit`).
5. Trusted oracle uses the same index in `test_features.csv` and `test.csv` → signed receipt (`src/boagent/oracle.py::run`).
6. `lenz observe` verifies receipt identity/signature → observed Frame Trial; Supervisor updates `trajectory.json` (`src/boagent/cli.py::observe`, `supervisor/supervisor.mjs`).
7. `boagent export` derives a modern PT trajectory from observed Frame Trials (`src/boagent/agent_cli.py::export`).
8. `validate_trajectory` rechecks step ordering, uniqueness, row mapping, and metrics summary, but currently accepts early stops (`src/boagent/evaluation.py`).
9. `benchmark/compare.py::experiment_report` audits Frame/trajectory/receipts/session/events, but is specialized to two-step five-seed experiments and is not the competition report.

## Verification performed

- `uv run python -m unittest tests.test_experiment_config tests.test_cli_contract tests.test_evaluation tests.test_benchmark_compare` — **41 passed**.
- `node --test supervisor/campaign.test.mjs` — **52 passed**.
- Audit-only config model validation of the explicit 20-seed list — **accepted**.
- Static/dataset checks — Buchwald training: **35 rows, 5 products**; candidate files: **783 test-feature rows vs 790 searchspace rows**.
- No provider experiment was started and no source code was modified.

## Submission blockers in priority order

1. **P0:** add checked-in per-dataset configs with exact seeds `[100,200,...,2000]`, budget 40, and the intended single competition policy.
2. **P0:** add an offline batch export/package step that creates exactly 20 `seed_<N>.pt` files per dataset from completed campaign Frames.
3. **P0:** make the competition packaging/validation path reject every artifact whose trajectory length is not exactly 40, regardless of generic campaign early-stop support.
4. **P0:** do not use `benchmark.compare experiment_report` as the competition gate; it is hard-coded to two steps and five seeds.
5. **P1:** lock the exact external PT schema, then add one directory-level contract test covering seed set, filenames, 40 steps, unique indices, exact conditions, and `test_features.csv` row-order mapping.
