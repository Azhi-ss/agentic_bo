# Full competition campaigns

## Goal

Complete the competition matrix after the successful seed-100 pilots: run seeds 200–2000 for both `buchwald_sub4` and `suzuki`, package all 40 artifacts, validate the exact competition contract, and report dataset-level optimization metrics.

User value: produce a complete, resumable, contract-valid submission without repeating the two completed pilots or losing progress when a provider run is interrupted.

## Confirmed facts

- Checked-in configs already define both datasets, `autonomous_agent`, model `ai-modeling/gpt-5.6-sol`, thinking `xhigh`, budget 40, and seeds `[100, 200, ..., 2000]`.
- Seed 100 is complete for both datasets: each Frame has budget 40 and state revision 81; both provider processes have exited successfully.
- The existing `boagent experiment` command rejects the full configs because seed-100 campaign directories already exist. It also initializes every run before calling the Supervisor, so it is not a safe resume entry for a partially populated matrix.
- `boagent run` already resumes an individual non-terminal campaign from its Frame/session/receipts and skips a valid terminal campaign through `validateCampaignStatus`.
- `boagent package-competition` already enforces the full 20-seed × 40-step artifact contract against label-free `test_features.csv`.
- Prior provider evidence includes concurrency-limit failures. The safe default is one campaign at a time; completed work remains resumable.

## Requirements

### R1 — Safe matrix resume

Add the minimum explicit resume mode to `boagent experiment`.

- Default behavior remains fail-closed on any existing campaign directory.
- Resume mode processes authored runs in config order.
- Missing campaign: initialize with the existing config provenance and run it.
- Existing campaign: verify it belongs to the same dataset, seed, budget, objective, policy, and declared config hashes before running/resuming it.
- Valid terminal campaign: skip without a provider call.
- Partial valid campaign: invoke the existing Supervisor resume path.
- Mismatched, malformed, or untrusted existing campaign: fail before running that campaign; never overwrite it.

### R2 — Complete the matrix

Run the two checked-in configs in safe resume mode, one campaign at a time. This must preserve and skip the completed seed-100 pilots and complete seeds 200–2000 for both datasets: 38 remaining campaigns, 1,520 remaining decisions.

### R3 — Package and validate

Run `boagent package-competition` in full mode for each dataset. Each destination must contain exactly `seed_100.pt` through `seed_2000.pt`, with every artifact passing the existing 40-step, unique-index, exact-condition, modern-schema, and provenance checks.

### R4 — Metrics

Compute label-grounded metrics only after all campaigns are complete, using observed values already present in the packaged trajectories. Report per dataset:

- per-seed final best and best-found step;
- mean, median, standard deviation, minimum, and maximum final best;
- mean best-so-far/AUC across the 40 decisions;
- round-to-95%-of-dataset-global-best summary, clearly identified as post-run evaluator-only analysis.

No hidden/test label or global-best value may enter campaign prompts, surrogate fitting, candidate ranking, or decisions.

## Acceptance criteria

- [ ] AC1: `boagent experiment --resume` is additive; omitted `--resume` retains collision rejection.
- [ ] AC2: Resume mode skips a matching terminal campaign, resumes a matching partial campaign, initializes a missing campaign, and rejects mismatched existing state before provider work.
- [ ] AC3: Existing config, CLI, competition, and Supervisor tests remain green; focused resume tests cover AC2.
- [ ] AC4: Both competition trees contain 20 completed Frames with exactly 40 observed campaign trials and no pending trials.
- [ ] AC5: Full packaging reports `ok: true` for both datasets and writes exactly 20 validated `.pt` files per dataset.
- [ ] AC6: Final report accounts for all 40 seeds/artifacts and includes the metrics in R4, with evaluator-only hidden-label use explicitly separated from optimization.
- [ ] AC7: Interrupted execution can be restarted with the same commands without deleting valid work or repeating completed decisions.

## Out of scope

- Changing the autonomous decision policy, prompts, GP trust logic, acquisition defaults, Frame schema, oracle, or artifact schema.
- Parallel provider execution; single-campaign execution is chosen to avoid known concurrency-limit failures.
- Refactoring `benchmark/compare.py`; metrics may be computed by a narrow post-run command/script using existing evaluation definitions.
- Retrying deterministic integrity/provenance failures or silently repairing mismatched campaign directories.

## Risks and deferred items

- Provider availability can pause a run. Resume mode must preserve progress and make the same invocation safe to repeat.
- The 1,520 remaining decisions may take substantial wall-clock time; correctness and resumability take priority over concurrency.
- Any competition/leaderboard composite score not defined by the dataset contract remains unreported.
