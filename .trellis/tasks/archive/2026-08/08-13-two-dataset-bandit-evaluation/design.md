# Technical Design

## Scope

Generalize the existing offline acquisition-bandit replay from Buchwald_sub4 to a dataset descriptor that also supports Suzuki. Reuse the worktree's existing bandit logic and GP backend without changing either algorithm.

## Dataset Contract

Each descriptor contains:

- dataset name and root path;
- optimized feature columns;
- target column (`Yield`);
- optional real baseline trajectory path and seed.

Descriptors:

- Buchwald_sub4: `Reactant2`, `Ligand`, `Additive`, `Base`;
- Suzuki: `Electrophile`, `Nucleophile`, `Ligand`, `Base`, `Solvent`.

`Product` is not an optimized Buchwald feature. It remains present in source rows but is excluded from the Study feature list, matching the prior replay.

## Offline Data Flow

1. Load `train.csv` and `test.csv` for the selected descriptor.
2. Build categories from feature values in train plus public test-feature values. Do not use `Yield` during category construction.
3. Initialize a Study from the descriptor's train rows only.
4. Select a candidate with the chosen acquisition strategy.
5. Read only the selected test row's `Yield` as oracle feedback.
6. Append that exact selected feature row and observed yield to history.
7. Repeat for 15 steps.
8. Aggregate five seeds independently per strategy and dataset.

## Comparison Contract

For each dataset and strategy report:

- first-step yield mean;
- mean run maximum;
- mean best-so-far by step;
- t95, defined against 95% of that dataset's public test maximum, if reached.

A cross-dataset result cannot pass by averaging datasets together. Report each dataset's deltas independently, then classify:

- effective on both;
- dataset-dependent;
- ineffective on both;
- environment-blocked for real campaigns.

## Real Campaign Evidence

- Reuse completed Buchwald_sub4 bandit and v2 baseline trajectories as read-only evidence.
- Reuse completed Suzuki autonomous baseline seed 100.
- If no compatible Suzuki bandit trajectory exists, create a new config/output path in the independent worktree and run seed 100 with `BOAGENT_BANDIT=1` and `BOAGENT_LENGTHSCALE_FLOOR=0.5`.
- Never overwrite the existing Suzuki baseline.

## Boundaries

- No changes to `src/boagent/backend.py`, `src/boagent/cli.py`, `src/boagent/runner.py`, datasets, or completed runs.
- The only required code change is the worktree-local evaluation script. Existing bandit implementation is reused unchanged.
- A new Suzuki experiment config and new output directory are allowed.

## Rollback

The evaluation adds only a generalized script/config/report in the independent worktree. Rollback is deletion of those new files. Existing bandit code and run artifacts remain untouched.
