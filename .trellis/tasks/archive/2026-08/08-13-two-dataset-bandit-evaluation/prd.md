# Evaluate acquisition bandit on two datasets

## Goal

Evaluate the acquisition-function bandit on both public chemical-reaction datasets, Buchwald_sub4 and Suzuki, under matched, leakage-safe conditions. The result must state whether the bandit generalizes across datasets rather than relying on the earlier Buchwald-only result.

## Background

- The earlier evaluation covered only `datasets/chemical_reactions/buchwald_sub4`.
- Buchwald_sub4 has 35 initial labeled rows, 783 test candidates, and four optimized variables.
- Suzuki has 29 initial labeled rows, 5,731 test candidates, and five optimized variables.
- Existing complete autonomous baselines are available for Buchwald_sub4 seed 1600 (`runs/verification/buchwald-sub4-final-v2/...`) and Suzuki seed 100 (`runs/competition/autonomous_agent/suzuki/...`).
- The bandit arm set is `noisy_logei/2`, `logei/2`, `ucb/1`, `ucb/2`, and `ucb/4`.

## Requirements

1. Evaluate Buchwald_sub4 and Suzuki independently; do not pool observations or normalize one dataset using labels from the other.
2. Offline replay must use only each dataset's `train.csv` as initial labeled history. `test.csv` may supply oracle feedback only after a candidate is selected; it must not affect fitting, feature selection, acquisition ranking, arm selection, or prompts.
3. Use the same bandit state machine, arm set, reward definition, lengthscale-floor setting, seed set, and step budget for both datasets unless a dataset schema requires only feature-name adaptation.
4. Compare three strategies on each dataset: online bandit, fixed `ucb/beta1`, and fixed `noisy_logei/beta2`.
5. Use at least seeds `100, 200, 300, 400, 500` and 15 steps for offline replay.
6. Report per dataset: first-step mean, best-of-run mean, best-so-far curve or t95, and bandit deltas versus both fixed strategies. Also report the aggregate conclusion without allowing one dataset to hide failure on the other.
7. Real-campaign comparison must use the existing complete baseline for each dataset. Buchwald_sub4 may reuse the completed bandit evidence already collected. Suzuki requires a bandit campaign only if no compatible completed bandit trajectory exists.
8. Keep the evaluation in an independent worktree. Do not modify datasets or completed run artifacts.
9. Do not modify `src/boagent/backend.py`, `src/boagent/cli.py`, or `src/boagent/runner.py`. The evaluation script may parameterize dataset root and feature names only.

## Acceptance Criteria

- [ ] One offline script runs both `buchwald_sub4` and `suzuki` with the same five seeds and 15-step budget.
- [ ] The script prints a separate comparison table for each dataset and a cross-dataset pass/fail summary.
- [ ] For each dataset, the first-step bandit result is compared against fixed UCB/beta1 and noisy_logEI; no result is described as generalized unless both datasets support the claim.
- [ ] For each dataset, the multi-step best/t95 result is compared against both fixed baselines.
- [ ] Existing complete real baselines are summarized: Buchwald_sub4 seed 1600 and Suzuki seed 100.
- [ ] A Suzuki real bandit campaign is run with matched budget/config if provider availability permits; provider/policy failure is reported explicitly rather than replaced with offline evidence.
- [ ] `node --test supervisor/campaign.test.mjs` passes without reducing the existing test count.
- [ ] `uv run python -m unittest discover tests` passes.
- [ ] Final conclusion is one of: effective on both datasets, dataset-dependent, ineffective on both, or environment-blocked. It includes raw per-dataset evidence.

## Out of Scope

- Tuning a dataset-specific arm set or reward function.
- Changing GP fitting, kernel constraints, acquisition implementations, CLI behavior, or campaign runner behavior.
- Replacing the autonomous agent's candidate-decision policy.
- Rewriting or deleting existing campaign artifacts.

## Risks and Deferred Items

- The current real bandit wiring permits the autonomous agent to explicitly override the selected acquisition parameters, which weakens causal attribution. The report must separate offline direct-bandit evidence from real autonomous-campaign evidence.
- Provider instability may prevent a complete Suzuki real campaign. Offline two-dataset evaluation remains valid, but the real-campaign conclusion must be marked environment-blocked if this occurs.

## Floor Ablation Evidence (2026-08-13)

The categorical lengthscale floor (`_CATEGORICAL_LENGTHSCALE_FLOOR = 0.5`) guards against small-sample categorical degeneration: with few rows the GP drives categorical lengthscales toward 0, flattening those dimensions' posteriors and freezing exploration. This ablation isolates that guard's effect.

- Method: `boagent-bandit-b/floor_ablation.py`, offline replay via `trace2zh_offline_bandit`, buchwald_sub4, fixed strategy `noisy_logei/beta2`, 5 seeds x 15 steps, only `lengthscale_floor` varies (0.5 vs None = no guard). Same Study/candidates/features/train data.
- Result (public-test t95 threshold 82.27):

| floor | first mean | best-so-far AUC | best mean | t95 reached |
|---|---|---|---|---|
| 0.5 (guard) | 71.55 | 77.90 | 82.71 | 4/5 |
| None (no guard) | 66.11 | 77.34 | 81.23 | 0/5 |

- Delta: best mean +1.49, best-so-far AUC +0.56, t95 4/5 vs 0/5.
- Mechanism check (traced chosen pool indices): without the guard, seed-100 and seed-500 produce identical 15-step index sequences — lengthscale collapse makes the posterior undiscriminating so argmax is seed-independent and exploration freezes. With the guard, the two seeds diverge after step 9 — the model keeps seed-sensitive discrimination, so exploration stays active.
- Conclusion: the guard is effective — it restores t95 reachability (4/5 vs 0/5) and improves best mean +1.49 on this dataset under a fixed acquisition strategy.
