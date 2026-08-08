# Implementation Plan

1. Load project backend guidelines and current Supervisor/lenz contracts before editing.
2. Add a backward-compatible policy selector for `default`, `lm_compare`, and contingency `lm_forced_first`; record it in run configuration evidence.
3. Extend the exact-config scoring response with finite-pool identity plus posterior/acquisition fields, reusing existing candidate lookup and surrogate helpers.
4. Add experiment-scoped opening-turn enforcement:
   - `lm_compare`: require one scored chemistry candidate distinct from GP rank 1, then permit either candidate.
   - `lm_forced_first`: require and commit that distinct candidate on step 1.
5. Add focused Node and Python contract tests for default compatibility, score identity fields, and both policy gates.
6. Add the minimal five-seed budget-2 experiment runner/reporting path. Fix seeds to `300–304`; output arms to distinct directories and never overwrite existing runs.
7. Run focused tests first, then smoke one budget-2 campaign per arm to confirm traces and receipts.
8. Run five matched seeds for Arm A and Arm B. Retry provider-transient failures from campaign state without changing model or prompt.
9. If all five Arm B first choices remain GP rank 1, run the predeclared Arm C for seeds `300–304`.
10. Produce a per-seed and aggregate report covering action compliance, candidate-source behavior, tool use, and two-step outcomes. Do not claim statistical significance.
11. Run final focused verification and confirm source changes are limited to experiment support, tests, and generated run artifacts.

## Validation Commands

- `uv run python -m unittest tests.test_cli_contract tests.test_prompt_policy`
- `cd supervisor && node --test campaign.test.mjs`
- One budget-2 smoke per selected arm through `boagent init` + `boagent run`.
- Experiment report integrity check: five matched seeds per mandatory arm, exactly two trajectory entries and two receipts per completed run.

## Risk / Rollback Points

- After score-contract changes: stop if existing callers require the legacy payload and compatibility cannot be additive.
- After policy enforcement: verify omitted policy still reproduces current default behavior before launching live runs.
- Never delete failed campaign directories; resume them or use a new clearly identified output path.
- Provider errors are operational retries, not reasons to change the experiment arm, model, seed, or prompt.
