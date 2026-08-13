# Competition submission pilot

## Goal

Make the checked-in autonomous-agent workflow able to produce a **contract-valid competition submission**, then de-risk it with a single real pilot run (seed 100 per dataset) before any full launch. "Option B": fix the competition P0 blockers, run one 40-step real pilot at seed 100 per dataset, then **stop at an explicit human gate** — no automatic 20-seed launch.

User value: a submission we can trust. Today the runtime enforces candidate identity, non-repetition, row-order mapping, and Frame/receipt provenance, but the checked-in config + packaging path do **not** implement the required 20-seed / exactly-40-step submission contract, and the exporter accepts short (early-stop) artifacts. The pilot proves the fixed pipeline end-to-end on real provider decisions at minimum cost before committing to the full 800-decision run.

## Background (confirmed evidence)

Source audits (copied into `research/`):
- `research/competition-readiness-research.md` — read-only contract audit of the two datasets.
- `research/competition-runner-readiness.md` — runner/packaging readiness audit with P0/P1/P2 blockers.

Contract facts (both datasets, from the dataset READMEs):
- **Datasets in scope:** `buchwald_sub4` + `suzuki` (required contract pair).
- **Seeds:** exactly `[100, 200, 300, ..., 2000]` (20 seeds) per dataset.
- **Budget:** 40 — each run is exactly 40 queried points, **exactly 40 steps** (`step` = 1..40).
- **Files:** exactly 20 files per dataset named `seed_<N>.pt` (`seed_100.pt` .. `seed_2000.pt`); no extra/missing seeds, no alternate prefix/suffix.
- **`query_index`:** zero-based row index of `test_features.csv` (which preserves `test.csv` row order after `Yield` removal). Valid ranges: Buchwald `0..782` (783 rows), Suzuki `0..5730` (5731 rows). Must be **unique within a run**.
- **`condition`:** full feature dict equal to `test_features.csv.loc[query_index]`, in candidate-column order; strict full-dict equality is enforced.
- **Buchwald training:** merged `5 products × 7 rows = 35` rows must all remain available for modeling; candidate pool is single-product; **no hidden/test `Yield` leakage** into optimization, training, tuning, prompting, ranking, or decisions.
- **PT payload:** modern dict payload with top-level `seed`, `dataset`, `target`, `direction`, `trajectory`; each row `step`, `query_index`, `condition`, `observed_value`, plus provenance ids. Buchwald `condition` must include the full row **including `Product`** (validator requires full-row equality; README example is short).

Runtime facts already passing (from runner audit, P0/P1-pass): `query_index` bound to `test_features.csv`; exact condition binding; duplicate-index rejection; YAML schema accepts an explicit 20-seed list; Buchwald 35-row training preserved; Frame/trajectory/receipt provenance end-to-end; a modern `.pt` exporter exists.

## Settled decisions

- **Policy:** `autonomous_agent`.
- **Model:** `ai-modeling/gpt-5.6-sol` at reasoning `xhigh`.
- **Pilot:** seed 100 per dataset, run **sequentially** (buchwald_sub4 then suzuki), 40 decisions each = **80 decisions total**.
- **No automatic full launch:** the pilot ends at an **explicit post-pilot human gate**; the 20-seed run is a separate later decision.
- **Isolated outputs:** pilot writes to an isolated output tree, never colliding with a future full run.
- **Resume:** Frame/receipt-based resume; a valid already-completed seed is **skipped** on re-run.
- **Packager states:** `complete` / `incomplete` / `invalid` per seed; partial trees report per-seed state rather than silently passing.
- **No hidden-label leakage** anywhere in the pilot or packaging path.
- **Exactly 40 steps** enforced by the competition packaging/validation path, independent of generic campaign early-stop support.

## Requirements

> Scope note: this **single task** owns both planning and, after explicit user approval of the final planning summary + `task.py start`, the implementation. The **current planning phase** performs no product/YAML edits and no provider runs. After approval, this same task implements the competition YAMLs, the packager, and the contract test (R1-R4, R7), then runs the pilot (R5). The **full 20-seed / 800-decision launch stays out of scope** (separate post-gate authorization).

### R1 — Checked-in per-dataset competition config (fixes runner P0 #1)
This task authors per-dataset config(s) (after approval) declaring seeds `[100,200,...,2000]`, budget 40, policy `autonomous_agent`, model `ai-modeling/gpt-5.6-sol`/`xhigh`, and an explicit isolated output root per dataset. Output roots are collision-free and fixed:
- Buchwald: `runs/competition/autonomous_agent/buchwald_sub4/`
- Suzuki: `runs/competition/autonomous_agent/suzuki/`
The pilot (R5) consumes only the seed-100 slice of these configs; the remaining seeds are not launched until the post-pilot human gate.

### R2 — Batch export/packager producing `seed_<N>.pt` (fixes runner P0 #2, P2 naming)
This task builds an offline packager that reads each completed campaign Frame and writes exactly the required `<dataset>/seed_<N>.pt` files, enforcing filename + count. Reports per-seed state `complete`/`incomplete`/`invalid`. Does **not** call the provider.

### R3 — Enforce exactly 40 steps in the competition path (fixes runner P0 #3)
The packaging/validation path rejects any artifact whose trajectory length ≠ 40, regardless of the generic exporter's early-stop acceptance. Autonomous policy already disables early stop; the packager must still hard-enforce 40.

### R4 — Competition gate independent of `benchmark.compare` (fixes runner P0 #4)
Do not use `benchmark/compare.py::experiment_report` (hard-coded 2-step / 5-seed) as the competition gate. The packager/validator this task builds is the gate; it must certify 20 files × 40 steps, unique indices, exact conditions, and `test_features.csv` row-order mapping.

### R5 — Pilot run (seed 100 per dataset)
After R1-R4/R7 land, run the autonomous_agent policy at seed 100 for buchwald_sub4 then suzuki, budget 40, into the isolated output roots above. 80 real provider decisions total. Then package + validate those two seeds and **stop** at the human gate. Execution happens only after `task.py start` and approval — never during the current planning phase.

### R6 — Leakage safety + resume + partial-state reporting
No hidden `Yield` read into optimization/training/tuning/prompting/ranking/decisions. Re-running a valid completed seed skips it (Frame/receipt resume). Packager reports `complete`/`incomplete`/`invalid` per seed on partial trees.

### R7 — Contract test (addresses runner P1 #6)
This task adds one directory-level contract test that, given a dataset output tree, asserts: exact seed set present, filenames `seed_100.pt..seed_2000.pt` (pilot subset asserts exactly `seed_100.pt`), each file exactly 40 steps, unique `query_index`, exact `condition` vs `test_features.csv`, modern PT schema. Parametrized so the pilot subset (seed 100) validates without demanding all 20 files yet.

## Out of scope

- Any product/YAML edit or provider run **during the current planning phase** (edits happen only after approval + `task.py start`, within this same task).
- The **full** 20-seed / 800-decision launch (separate post-gate authorization).
- Changing `src/boagent/evaluation.py::SEEDS` (10-seed generic constant) — tracked as P1 but not required for the pilot; the competition gate is the packager, not the generic evaluator.
- Defining the external competition composite scoring/leaderboard formula (unknown; not specified by organizers).
- Fixing README typos / options.json `Catalyst` omission (documentation drift, not submission blockers).
- `benchmark/compare.py` refactor (explicitly avoided as the gate; left as-is).

## Acceptance criteria

- [ ] AC1: Task exists at `.trellis/tasks/08-10-competition-submission-pilot` with status `planning`; it flips to `in_progress` only on explicit human approval + `task.py start`, after which this same task implements R1-R7.
- [ ] AC2: Both source audits are copied into `research/` and referenced by `implement.jsonl` / `check.jsonl`, alongside the relevant backend spec(s).
- [ ] AC3: `prd.md`, `design.md`, `implement.md` are written and converged (complex task).
- [ ] AC4: `implement.jsonl` and `check.jsonl` each contain real research **and** backend-spec entries (seed `_example` removed); `task.py validate` passes.
- [ ] AC5: Design specifies: per-dataset config shape with collision-free output roots (R1), offline packager producing exactly `seed_<N>.pt` with per-seed `complete`/`incomplete`/`invalid` state (R2), hard 40-step enforcement in the competition path (R3), packager-as-gate independent of `benchmark.compare` (R4), Frame/receipt resume with completed-seed skip and no-leakage guarantees (R6), and the pilot procedure seed 100 buchwald then suzuki sequentially (R5).
- [ ] AC6: A post-pilot **human gate** is explicitly documented; no config authorizes automatic full-seed launch.
- [ ] AC7: Implementation plan defines, in order, config authoring, packager + contract test, the exact pilot commands, the packager/validator invocation, expected artifacts (`seed_100.pt` per dataset, 40 steps each), and the stop point.
- [ ] AC8: During the **current planning phase** no provider call, no `task.py start`, no YAML/product edit, and no commit are performed. (Implementation of R1-R7 is authorized only by a later approval within this same task.)
