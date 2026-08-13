# Design — Competition submission pilot

## Scope of this design

This one task owns both planning and implementation. During the **current planning phase** no product code or YAML is edited and no provider runs. After explicit user approval + `task.py start`, **this same task** builds the design below (config, packager, contract test) and then runs the pilot. Evidence anchors are from `research/competition-runner-readiness.md` and `research/competition-readiness-research.md`.

## Architecture & boundaries

The pipeline is already layered; the fix adds one offline packaging/gate seam and one checked-in config, without touching the trusted-oracle or Frame identity core.

```
YAML experiment config  (R1: per-dataset, 20 seeds, budget 40)
   -> experiment_config.py  (strict list[int] seeds, cartesian runs)   [PASS today]
   -> boagent experiment -> initialize_campaign -> lenz create Frame     [PASS today]
        (35 Buchwald train rows as historical Trials; test_features.csv pool)
   -> boagent run -> Node Supervisor -> typed candidate tools           [PASS today]
        (autonomous_agent policy; early stop disabled)
   -> lenz submit/observe -> signed oracle receipts -> observed Frame    [PASS today]
   -> [NEW R2/R3/R4] offline PACKAGER  (per campaign Frame)
        * require budget==40, no pending trials, exactly 40 observed trials
        * exact seed membership, unique query_index, row equality vs test_features.csv
        * map verified export payload -> seed_<N>.pt   (modern dict schema)
        * per-seed state: complete | incomplete | invalid
        * directory manifest: exactly the required seed_<N>.pt filenames
   -> [R7] directory-level contract test
```

### Key boundary decisions

- **Packager is the competition gate, not `benchmark/compare.py`.** `benchmark/compare.py::_experiment_run` is hard-coded to exactly two trajectory entries and `EXPERIMENT_SEEDS=[300..304]` (runner audit P0 #4); it would mark valid 40-step campaigns failed. The packager owns certification. `benchmark/compare.py` is left untouched.
- **The packager is offline and deterministic.** It reads `frame/state.json` per campaign and the existing verified `boagent export` payload shape. No provider calls, no new campaign model (runner audit "Unknown P1" minimal-converter design).
- **40-step enforcement lives in the competition path, not the generic exporter.** `boagent export` and `validate_trajectory` accept verified non-empty early stops (`agent_cli.py:227-269`, `evaluation.py:17-20`); autonomous policy disables early stop (`supervisor.mjs:200-202`) but that is policy-level only. The packager hard-rejects trajectory length ≠ 40 regardless.

## Data flow & contracts

### Per-seed packaging contract (the gate)
For each campaign directory `<output>/autonomous_agent/seed-<N>`:
1. Load `frame/state.json`.
2. `study.budget == 40`; else `invalid`.
3. No pending (unobserved) trials; else `incomplete`.
4. Exactly 40 observed campaign trials; length ≠ 40 => `invalid` (R3). Fewer completed than 40 with none pending and no error => `incomplete`.
5. Seed membership: campaign seed ∈ required set `{100,200,...,2000}`; else `invalid`.
6. `query_index` unique across the 40 steps and in `test_features.csv` range; else `invalid`.
7. Each step `condition` == `test_features.csv.loc[query_index].to_dict()` (full row, candidate-column order; Buchwald includes `Product`); else `invalid`.
8. Emit modern dict PT: top-level `seed`, `dataset`, `target`, `direction`, `trajectory`; each row `step` (1..40), `query_index`, `condition`, `observed_value`, provenance ids. Write `<dataset>/seed_<N>.pt`.
9. State `complete` only when 1-8 pass and the file is written.

### Directory manifest contract
After per-seed packaging, assert the output dir contains exactly the required filenames: for full run `seed_100.pt..seed_2000.pt` (20 files); **for the pilot, exactly `seed_100.pt`** (subset mode). Extra or missing files => manifest failure surfaced per-seed, not a silent pass.

### Leakage contract (R6)
Hidden/test `Yield` is only ever touched by the trusted oracle (`src/boagent/oracle.py`) which returns a signed receipt; the agent, exporter, and packager operate on Frame `observed_value` (the oracle's returned value) and `test_features.csv` (label-free). The packager reads `test_features.csv` for row-equality only — never `test.csv`. No `Yield` enters optimization, training, tuning, prompting, ranking, or decisions. Buchwald: all 35 merged train rows remain historical Trials; only the single-product candidate pool is optimized; other products' **train** rows may assist modeling, their **test** `Yield` never does.

### Resume contract
Re-running a seed reconciles from Frame + signed receipts (Supervisor `reconcileTrajectory`). A seed whose Frame already satisfies the per-seed `complete` contract is **skipped** (idempotent packaging + no re-decision). Interrupted campaigns resume from the last observed receipt.

## Pilot procedure (R5) — executed only post-approval, within this task

Sequential, isolated, seed 100 only. Collision-free output roots (fixed, distinct from any future full-run tree):
- Buchwald: `runs/competition/autonomous_agent/buchwald_sub4/`
- Suzuki: `runs/competition/autonomous_agent/suzuki/`

1. buchwald_sub4 seed 100, policy autonomous_agent, model `ai-modeling/gpt-5.6-sol`/`xhigh`, budget 40, output root `runs/competition/autonomous_agent/buchwald_sub4/` -> 40 decisions.
2. suzuki seed 100, same settings, output root `runs/competition/autonomous_agent/suzuki/` -> 40 decisions.
3. Package + validate both campaigns -> expect `seed_100.pt` per dataset, 40 steps each, state `complete`.
4. **STOP** at the explicit human gate. Report per-seed state, artifact paths, and step counts. Do **not** launch the remaining 19 seeds.

Total cost ceiling: 80 provider decisions. No automatic escalation.

## Compatibility & migration

- Additive: new packager + config + one test. No change to Frame schema, oracle, `lenz` CLI, or Supervisor.
- `src/boagent/evaluation.py::SEEDS` (10-seed generic constant) is intentionally left as-is; the competition gate does not depend on it (runner audit P1 #5). Any later alignment is a separate task.
- Isolated pilot output prevents collision with a future full-run output tree.

## Risks & mitigations

- **R: exporter/validator early-stop acceptance leaks into competition path.** M: packager hard-enforces exactly 40 (R3); autonomous policy also disables early stop.
- **R: wrong candidate file mapping.** M: packager row-equality strictly against `test_features.csv` (783 Buchwald / 5731 Suzuki rows), never `searchspace.csv` (790/5760).
- **R: silent partial success on interrupted trees.** M: explicit per-seed `complete`/`incomplete`/`invalid` states; manifest check surfaces missing/extra files.
- **R: hidden-label leakage.** M: packager reads only `test_features.csv`; oracle is the sole `test.csv` reader and returns signed receipts.
- **R: full launch triggered prematurely.** M: no config authorizes 20-seed auto-launch; explicit human gate after pilot.
- **R: `benchmark.compare` mistaken for the gate.** M: design names the packager as sole gate; compare left untouched.

## Rollback

All pilot outputs are isolated; discarding the pilot = delete the isolated output tree. No product state mutated outside that tree (Frame receipts are per-campaign under the isolated root).
