# Implementation plan — Full competition campaigns

## Ordered checklist

### Phase A — Safe resume entry

1. Add `--resume` to `boagent experiment`.
2. Reuse existing initialization and run functions; add one small validator for an existing campaign's authored config/provenance contract.
3. Keep omitted `--resume` collision behavior unchanged.
4. Add focused CLI tests for missing initialization, matching existing resume/skip dispatch, mismatched-state rejection, and default collision rejection.

### Phase B — Verification before provider work

5. Run focused Python tests:
   - `uv run python -m unittest tests.test_experiment_config`
   - `uv run python -m unittest tests.test_competition tests.test_cli_contract tests.test_evaluation`
6. Run Supervisor contract tests:
   - `node --test supervisor/campaign.test.mjs`
7. Dispatch mandatory code review/check and fix blocking findings.

### Phase C — Complete campaigns

8. Run sequentially:
   - `uv run boagent experiment --config experiment-configs/competition-buchwald-sub4.yaml --resume`
   - `uv run boagent experiment --config experiment-configs/competition-suzuki.yaml --resume`
9. On transient provider interruption, rerun the same command. Do not delete campaign directories or repeat completed candidates.
10. Verify each dataset has seeds 100–2000, each Frame budget 40, exactly 40 observed trials, and no pending trials.

### Phase D — Package and evaluate

11. Package full submissions using existing gate:
   - Buchwald destination: `runs/competition/submissions/buchwald_sub4`
   - Suzuki destination: `runs/competition/submissions/suzuki`
12. Require `ok: true`, exact 20-file manifests, and 40 valid steps in every artifact.
13. Compute per-seed and aggregate metrics from the validated artifacts with existing evaluation semantics; include best-found step as a direct trajectory calculation.
14. Report exact commands, artifact locations, completion counts, packaging results, and metrics. Mark all global-best/t95 analysis evaluator-only.

## Review and stop conditions

- Stop immediately on deterministic provenance, Frame, receipt, or artifact-integrity failure; do not auto-repair.
- Transient provider failures are resumable, not data failures.
- Do not introduce parallel campaign execution.
- Completion requires both datasets fully packaged and validated; partial completion is not reported as done.

## Risky files

- `src/boagent/agent_cli.py`: orchestration semantics. Minimal additive flag/helper only.
- `tests/test_experiment_config.py`: focused resume contract tests.
- Campaign and submission trees: generated evidence; never overwrite mismatched state.

## Validation proof

- Focused tests prove resume semantics and unchanged defaults.
- Supervisor tests prove terminal skip/reconciliation behavior remains valid.
- Frame inspection proves 40 observed decisions per seed.
- `package-competition` proves the submission contract.
- Metrics are calculated only from validated packaged artifacts.
