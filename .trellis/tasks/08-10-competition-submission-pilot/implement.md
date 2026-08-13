# Implementation plan — Competition submission pilot

> This single task owns implementation. Nothing below runs during the current planning phase. After explicit human approval of the final planning summary and `task.py start` (status -> in_progress), **this same task** executes Phases A-D in order.

## Ordered checklist

### Phase A — Competition config (R1)
1. Author per-dataset competition YAML(s): `buchwald_sub4` and `suzuki`, each with `seeds: [100,200,...,2000]`, `budget: 40`, `policy: autonomous_agent`, model `ai-modeling/gpt-5.6-sol`/`xhigh`, and an explicit collision-free `output` root: Buchwald `runs/competition/autonomous_agent/buchwald_sub4/`, Suzuki `runs/competition/autonomous_agent/suzuki/` (distinct from any existing run). Verify with `experiment_config.py` load (audit-only) that 20 seeds expand, first=100/last=2000, budget=40.
   - Risky file: new YAML(s) under `experiment-configs/`. No auto-launch: the pilot invokes only seed 100.

### Phase B — Offline packager / competition gate (R2, R3, R4, R6)
2. Add an offline packager command (no provider calls) that, per campaign Frame under `<output>/autonomous_agent/seed-<N>`:
   - loads `frame/state.json`; requires `budget==40`, no pending trials, exactly 40 observed trials (length ≠ 40 => `invalid`; R3);
   - checks seed membership, unique `query_index`, and full-row `condition` equality vs `test_features.csv` (never `searchspace.csv`, never `test.csv`);
   - maps the verified `boagent export` payload to modern dict `seed_<N>.pt` under `<dataset>/`;
   - returns per-seed state `complete` | `incomplete` | `invalid`;
   - ends with a directory manifest check: full mode expects `seed_100.pt..seed_2000.pt`; **pilot subset mode expects exactly `seed_100.pt`**.
   - Idempotent: a seed whose Frame already satisfies `complete` is skipped (resume).
   - Explicitly does NOT use `benchmark/compare.py::experiment_report` (R4); that file is untouched.
   - Risky files: new packager module + its CLI wiring. Rollback: delete the module; no other path depends on it.

### Phase C — Contract test (R7)
3. Add one directory-level contract test: given a dataset output tree, assert exact seed set, filenames, exactly-40 steps per file, unique `query_index`, exact `condition` vs `test_features.csv`, modern PT schema. Parametrize so pilot subset (only `seed_100.pt`) passes without demanding all 20 files.

### Phase D — Pilot run (R5) — sequential, isolated, 80 decisions
4. Run buchwald_sub4 seed 100: `boagent experiment` (or per-seed run) with the competition config restricted to seed 100, output root `runs/competition/autonomous_agent/buchwald_sub4/`. Confirm 40 autonomous decisions complete.
5. Run suzuki seed 100 the same way into `runs/competition/autonomous_agent/suzuki/`. Confirm 40 decisions.
6. Package + validate both: run the packager in pilot-subset mode per dataset. Expect state `complete` and one `seed_100.pt` (40 steps) per dataset.
7. **STOP at the human gate.** Report per-seed state, `seed_100.pt` paths, and step counts. Do not launch seeds 200..2000.

## Validation commands

- Config sanity (audit-only, no run):
  `uv run python -c "from src.boagent.experiment_config import ..."` load of the 20-seed list (mirror the audit already done in the runner report).
- Existing suites must stay green after Phases B/C:
  `uv run python -m unittest tests.test_experiment_config tests.test_cli_contract tests.test_evaluation tests.test_benchmark_compare`
  `node --test supervisor/campaign.test.mjs`
- New contract test (Phase C):
  `uv run python -m unittest tests.test_<packager_contract>`
- Pilot proof (Phase D): packager output shows `seed_100.pt` per dataset at exactly 40 steps, state `complete`.

## Review gates

- Gate 1 (post-Phase C): code review + `trellis-check` before any provider run. No leakage regressions; packager rejects length ≠ 40; manifest correct.
- Gate 2 (post-Phase D pilot): **explicit human gate.** Present per-seed state + artifact paths + step counts. Full 20-seed launch is a separate authorization; it is NOT implied by pilot success.

## Rollback points

- Phase A: remove the new YAML(s).
- Phase B/C: remove the packager module + test; no other code depends on them.
- Phase D: delete the isolated pilot output tree; no shared state mutated outside it.

## Pre-start checks

- [ ] `prd.md`, `design.md`, `implement.md` converged.
- [ ] `implement.jsonl` / `check.jsonl` carry real research entries; `task.py validate` passes.
- [ ] Final planning summary approved by the user in a subsequent message.
- [ ] Confirm no provider call / no YAML-or-product edit / no commit happened during the current planning phase (implementation is authorized only after approval, within this task).
