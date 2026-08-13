# Implementation Plan

## Evaluation Script

- [ ] Work only in `/home/dministrator/project/boagent-bandit-b`.
- [ ] Generalize `trace2zh_offline_bandit.py` with Buchwald_sub4 and Suzuki dataset descriptors.
- [ ] Preserve the existing arm set, UCB1 selector, reward definition, floor `0.5`, seeds, and candidate-selection mechanism.
- [ ] Add per-dataset first-step, best-of-run, best-so-far, and t95 summaries.
- [ ] Add a cross-dataset classification that never hides a failing dataset through averaging.

## Offline Evaluation

- [ ] Run both datasets for seeds 100, 200, 300, 400, 500 and 15 steps.
- [ ] Save command output to an evaluation artifact under the worktree.
- [ ] Confirm only selected test labels enter observation history.

## Real Campaign Evaluation

- [ ] Summarize the completed Buchwald_sub4 v2 baseline and existing bandit trajectory.
- [ ] Summarize the completed Suzuki seed-100 autonomous baseline.
- [ ] Check for a compatible completed Suzuki bandit trajectory.
- [ ] If missing, write a new worktree config/output path and initialize/run Suzuki seed 100 with bandit enabled.
- [ ] Compare first step, best, and t95 independently for each dataset.

## Validation

- [ ] Run `node --test supervisor/campaign.test.mjs` in the worktree.
- [ ] Run `uv run python -m unittest discover tests` in the worktree.
- [ ] Verify `git diff` does not add changes to prohibited backend/CLI/runner files as part of this task.
- [ ] Record provider or policy failures verbatim if a real Suzuki campaign cannot finish.

## Review Gates

- Do not tune arms, rewards, floors, seeds, or budgets per dataset after seeing test yields.
- Do not claim generalization unless both datasets independently support it.
- Stop and report if the generalized script requires modifying GP/backend behavior.
