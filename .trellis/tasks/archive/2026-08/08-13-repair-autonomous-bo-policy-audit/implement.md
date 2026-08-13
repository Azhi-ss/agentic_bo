# Implementation plan

## Branch

- Implementation branch: `experiment/competition-score-policy`
- Base branch: `main`
- Existing unrelated working-tree changes must not be staged or committed with this task.

## Ordered changes

1. **Update autonomous commitment schema**
   - Add `decision_goal` and `result_use` to autonomous `commit_candidate`.
   - Require `follow_up_if_supported` and `follow_up_if_refuted` for decision-information actions through deterministic validation.
   - Preserve default/non-autonomous schema.

2. **Separate telemetry from correction flags**
   - Keep computing cross-context, scope-overreach, and GP-dissent observations.
   - Record them under audit telemetry.
   - Remove them as independent autonomous retry triggers.

3. **Implement competition-score challenge rules**
   - Reuse existing policy stage, shortlist, score, action-run, factor-run, and surrogate trust information.
   - Add middle/late global-exploration checks.
   - Add terminal information-waste checks using explicit follow-up fields and remaining budget.
   - Add late outside-shortlist exploration challenge.
   - Limit trusted-surrogate dissent to medium/high trust plus an unresolved concrete disagreement.
   - Keep implementation domain-neutral and direction-aware.

4. **Update retry prompts and autonomous instructions**
   - Explain score-oriented stage behavior without exposing labels/global optimum.
   - State that telemetry is advisory.
   - Require corrected actions to resolve the named competition challenge rather than merely change candidate.

5. **Add unit and replay tests**
   - Productive override streak remains allowed.
   - Low-trust override remains allowed.
   - Middle/late global exploration challenge behavior.
   - Terminal information action requires usable follow-up budget.
   - Late shortlist-adjacent exploit remains allowed.
   - Cross-context/scope detection remains recorded as telemetry.
   - Existing hard validation and default-policy behavior remain unchanged.
   - Replay representative seed-1600 prefixes around steps 5, 23-37, and 38.

6. **Run static and unit verification**
   - `node --check supervisor/campaign.mjs`
   - `node --check supervisor/supervisor.mjs`
   - `node --test supervisor/campaign.test.mjs`

7. **Run offline replay report**
   - Compare old detector flags and competition correction flags on historical Buchwald trajectories.
   - Report per-seed correction counts and known seed-1600 interval outcomes.
   - Assert telemetry is not lost.

8. **Run controlled A/B**
   - First run paired seed-1600 control/treatment from clean isolated worktrees/configs.
   - If completion and action audit are sound, run at least five paired seeds.
   - Calculate Best, AUC, T95, regret, longest stagnation interval, and intervention outcomes.

9. **Review gate**
   - Do not merge if treatment worsens median AUC or median T95 without a compensating, pre-agreed final-best improvement.
   - Do not claim improvement from seed-1600 alone.
   - Keep changes on the experiment branch if evidence is mixed.

## Risk points

- Current worktree contains unrelated modifications. Stage only explicitly reviewed task files.
- Existing campaign trajectories predate the new fields; replay must tolerate missing fields.
- Provider nondeterminism means same-seed A/B is paired but not perfectly deterministic. Use multiple seeds and report provider failures separately.
- Hidden labels are permitted only in offline evaluation, never policy execution.

## Rollback

- Before implementation, record the branch HEAD and task artifacts.
- Keep commits narrow: schema/validation, policy, tests/replay, then experiment config/results if requested.
- Roll back an individual policy commit rather than resetting the mixed working tree.
