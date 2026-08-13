# Competition readiness evidence audit

## Scope and safety

Read-only audit of the local competition contract; no provider experiment was run. `test.csv` was used only for header and row-count streaming checks. No test/hidden `Yield` value was read into this report or exposed to an optimization model.

Files read:

- `AGENTS.md`
- `.trellis/workflow.md`
- `datasets/chemical_reactions/buchwald_sub4/README.md`
- `datasets/chemical_reactions/suzuki/README.md`
- CSV headers/counts for both datasets: `train.csv`, `test_features.csv`, `searchspace.csv`; `test.csv` header/count only
- `datasets/chemical_reactions/buchwald_sub4/options.json` and `datasets/chemical_reactions/suzuki/options.json`
- Submission writer/validator evidence: `src/boagent/cli.py`, `src/boagent/runner.py`, `src/boagent/agent_cli.py`, `src/boagent/evaluation.py`, `benchmark/run_gp.py`, `tests/test_evaluation.py`

The two dataset READMEs contain their submission-format sections directly; they do not link to a separate local submission-format document.

## Conclusions

### 1. Fixed seeds

**Competition README contract: yes, exactly** `[100, 200, ..., 2000]` (20 seeds), for both datasets:

- Buchwald: `datasets/chemical_reactions/buchwald_sub4/README.md:147-159`, especially `:154-159`.
- Suzuki: `datasets/chemical_reactions/suzuki/README.md:112-124`, especially `:119-124`.

Submission names must match those seeds: Buchwald `README.md:169-178,213-220`; Suzuki `README.md:134-143,180-187`.

**Readiness mismatch:** the repository evaluator currently declares only ten seeds, `100..1000`, at `src/boagent/evaluation.py:10`. That constant does not implement the 20-seed README contract.

### 2. File count and trajectory length

**Yes:** each dataset requires exactly 20 files named `seed_<N>.pt`; each file must contain exactly 40 queried points.

- Buchwald: `README.md:171-180,213-220`.
- Suzuki: `README.md:136-145,180-187`.
- Each run has 40 iterations, one point per iteration, total 40 queries/run and 800 across 20 runs: Buchwald `:151-159`; Suzuki `:116-124`.

**Readiness mismatch:** `src/boagent/evaluation.py:17-20` accepts a verified non-empty early stop shorter than 40, while the competition READMEs say “恰好 40”. For competition packaging, do not rely on early-stop acceptance.

### 3. `.pt` object, field types/shapes, row identity, and order

The READMEs document either a length-40 record list or a dictionary containing `trajectory`, with the recommended dictionary also carrying `seed` and `dataset` (Buchwald `README.md:180-211`; Suzuki `README.md:145-178`). **However, the current local validator is only safe with a dictionary:** it initially extracts a bare list at `src/boagent/evaluation.py:13-16`, but later calls `payload.get(...)` at `:36`, which a list does not support.

Per-step contract and effective local types:

- `step`: integer sequence exactly `1..40`; README: Buchwald `:182-188`, Suzuki `:147-153`; enforced in order by `src/boagent/evaluation.py:26-29`.
- `query_index`: candidate-row index, effectively integer/int-convertible (`int(...)` in validator), unique and in range; `src/boagent/evaluation.py:27,30-31`.
- `condition`: Python dictionary mapping feature column names to exact CSV row values; strict full-dict equality is enforced at `src/boagent/evaluation.py:32-33`.
- observation: legacy dictionary artifacts use `observed_yield`, float-convertible; modern artifacts carrying top-level `target` use `observed_value`; `src/boagent/evaluation.py:23-25,35-43`. Although the READMEs mention `actual_yield`, the local validator does not accept that key.
- `predicted_yield`: optional in the README and not checked by `validate_trajectory`.

The repository’s standard agent writer creates a dict with `seed`, `dataset`, and a list of step dictionaries, then saves with `torch.save`: `src/boagent/runner.py:141-143`. Thus the practical trajectory shape is `list[dict]` of length 40, not a tensor shape.

`condition` is generated from the exact public candidate row in candidate-column order: `src/boagent/runner.py:141`. The validator independently reconstructs the row with `candidates.loc[index].to_dict()` and requires equality: `src/boagent/evaluation.py:21,32-33`.

`query_index` means the **zero-based pandas/default row index** of `test_features.csv`, and the README states that `test_features.csv` preserves the row order of `test.csv` after removing `Yield`:

- Buchwald `README.md:74-78,185-186,216-220`.
- Suzuki `README.md:70-74,150-151,183-187`.
- Writer evidence uses `candidates.index` and `.loc[index]`: `src/boagent/runner.py:101-103,128-141`; the shared lookup does the same at `src/boagent/cli.py:30-45`.

Safe metadata inspection found these valid zero-based ranges:

- Buchwald: `0..782` (783 candidate rows).
- Suzuki: `0..5730` (5731 candidate rows).

### 4. Duplicate `query_index`

Within each seed/run, indices must not repeat:

- Buchwald `README.md:215-220`.
- Suzuki `README.md:182-187`.
- Enforced with a per-trajectory `seen` set at `src/boagent/evaluation.py:22,30-34`.

This prohibition is per run; the documents do not prohibit different seeds from querying the same index.

### 5. Buchwald merged training set and permitted modeling

**Confirmed:** `buchwald_sub4/train.csv` has 35 rows and five `Product` values, each with exactly 7 rows. The README explicitly defines the merge as `5 × 7`: `datasets/chemical_reactions/buchwald_sub4/README.md:80-96`; the five products/counts are listed at `:86-92`.

Allowed modeling treatment:

- use `Product` to distinguish tasks/products;
- use cross-product training relationships, including multitask learning or meta-learning (`README.md:94`);
- use other products’ merged **training** rows to assist modeling (`:145`);
- never use other products’ test `Yield` for this product’s optimization (`:145`), and never use this test `Yield` for training, feature engineering, tuning, prompting, ranking, or decisions (`:137-145`).

Only the train file is merged. Searchspace/test/test_features remain sub4-only with fixed Product: `README.md:96`.

### 6. CSV metadata, naming, directories, packaging, and scoring

Safe CSV metadata check:

| Dataset/file | Header | Rows |
| --- | --- | ---: |
| Buchwald `train.csv` | `Product, Reactant2, Ligand, Additive, Base, Yield` | 35 |
| Buchwald `test_features.csv` | `Product, Reactant2, Ligand, Additive, Base` | 783 |
| Buchwald `searchspace.csv` | same features + `Yield` | 790 |
| Suzuki `train.csv` | `Electrophile, Nucleophile, Ligand, Base, Solvent, Yield` | 29 |
| Suzuki `test_features.csv` | same five feature columns, no `Yield` | 5731 |
| Suzuki `searchspace.csv` | same features + `Yield` | 5760 |

For both datasets, a header/count-only check confirmed `test.csv` has the same row count as `test_features.csv`, with identical feature columns and trailing `Yield`. No label values were inspected.

Naming/data constraints:

- Public reagent/component values use IUPAC names; absent reagent is `Nothing`: Buchwald `README.md:16`, Suzuki `README.md:16`.
- Exact submitted filenames: `seed_100.pt` through `seed_2000.pt`; no alternate suffix/prefix is documented.
- Dataset directory layouts are documented at Buchwald `README.md:231-240` and Suzuki `README.md:198-207`. The README names files with dataset prefixes, while this repository’s actual directories use generic names (`train.csv`, `test.csv`, `test_features.csv`, `searchspace.csv`). Repository writers/validators use the generic names: `benchmark/run_gp.py:26-28`, `src/boagent/evaluation.py:21,40`.
- No archive type, enclosing submission directory name, compression rule, maximum size, or upload manifest is specified in either README. Only the exact 20 `.pt` files and their contents are specified.
- `options.json` is optional input. Suzuki includes all five optimization variables plus fixed `Product` and `Catalyst`; Buchwald includes its four optimization variables plus fixed `Reactant1`, `Product`, and `Solvent`, but omits the README-documented fixed `Catalyst` (`buchwald_sub4/README.md:43-47,70` versus `buchwald_sub4/options.json:42-50`).

Scoring references (not a fully specified leaderboard formula):

- metrics are initial-round best, final best, `t95`, and best-so-far AUC: Buchwald `README.md:222-229`; Suzuki `README.md:189-196`;
- README recommendation is to compute per seed and report mean, standard deviation, and 95% CI;
- internal hidden evaluation may contribute to final rank and is used for leakage/leaderboard-overfit detection: Buchwald `README.md:142-144`; Suzuki `README.md:108-110`.

The local `validate_trajectory` computes initial best, final best, t95, mean best-so-far AUC, and simple regret at `src/boagent/evaluation.py:44-62`; local `summarize` instead reports median/Q25/Q75 (`:65-72`), which differs from the README reporting recommendation.

## Reproducible safe checks

These commands avoid reading test labels:

```bash
python3 - <<'PY'
import csv
from collections import Counter
from pathlib import Path
for name in ('buchwald_sub4', 'suzuki'):
    root = Path('datasets/chemical_reactions') / name
    for filename in ('train.csv', 'test_features.csv', 'searchspace.csv'):
        with (root / filename).open(newline='', encoding='utf-8-sig') as f:
            rows = list(csv.DictReader(f))
            print(name, filename, f.fieldnames, len(rows))
            if name == 'buchwald_sub4' and filename == 'train.csv':
                print(Counter(row['Product'] for row in rows))
PY
```

Header/count-only hidden-file alignment check:

```bash
python3 - <<'PY'
import csv
from pathlib import Path
for name in ('buchwald_sub4', 'suzuki'):
    root = Path('datasets/chemical_reactions') / name
    with (root/'test_features.csv').open(newline='', encoding='utf-8-sig') as f:
        features = csv.reader(f); fh = next(features); fn = sum(1 for _ in features)
    with (root/'test.csv').open(newline='', encoding='utf-8-sig') as f:
        test = csv.reader(f); th = next(test); tn = sum(1 for _ in test)
    print(name, fh == th[:-1], th[-1] == 'Yield', fn, tn)
PY
```

## Unresolved ambiguities / readiness risks

1. **Buchwald `condition` inconsistency:** its README example lists only `Reactant2/Ligand/Additive/Base` (`README.md:200-205`), but `test_features.csv` also contains `Product`, and the local validator requires equality with the complete row dict (`src/boagent/evaluation.py:32-33`). The repository writer includes all candidate columns (`runner.py:141`). Safest local submission is therefore to include `Product` in Buchwald `condition`, despite the shortened README example.
2. **Required vs recommended fields:** the READMEs call the per-step fields “建议包含” but later strictly require trajectory length, index validity/uniqueness, filename, and exact condition. They do not formally specify Python scalar classes/dtypes, serialization protocol version, or whether top-level `seed`/`dataset` are mandatory. The local validator effectively requires a dictionary containing `trajectory`; every step needs `step`, `query_index`, `condition`, and either legacy `observed_yield` or modern `observed_value`. README-listed `actual_yield` is unsupported locally.
3. **Bare-list contradiction:** the READMEs permit a top-level list, and `evaluation.py:13-16` initially handles one, but `evaluation.py:36` later calls `payload.get`, so a bare list fails. Use the recommended dictionary shape.
4. **Filename layout:** exact filenames are specified, but whether all 20 files must be at archive root, in a dataset folder, or submitted separately is not stated.
5. **Scoring:** metric definitions are given, but no authoritative composite weighting/tie-break/failure penalty is specified. `benchmark/compare.py:28-33` contains a local composite score, but the dataset READMEs do not declare that formula as the competition leaderboard rule.
6. **README typo:** Buchwald’s input section incorrectly names Suzuki files at `datasets/chemical_reactions/buchwald_sub4/README.md:161-167`; surrounding Buchwald sections and actual repository paths clearly indicate Buchwald files should be used.
7. **Protocol drift:** the local evaluator’s 10-seed constant, early-stop allowance, and median/IQR summary conflict with or differ from the README’s 20 seeds, exactly 40 steps, and mean/std/95% CI recommendation. Competition packaging should follow the dataset READMEs unless organizers publish a newer authoritative format.
8. **Writer incompatibility:** `benchmark/run_gp.py:65-79` writes `pool_index`/`config`, not validator-required `query_index`/`condition`; those `.pt` artifacts are not directly competition-validator compatible.
9. **Options mismatch:** Buchwald README documents fixed `Catalyst` and says fixed values may be found in `options.json`, but `buchwald_sub4/options.json` has no `Catalyst` key.
10. **Illustrative syntax error:** Suzuki’s README object example lacks a comma after `observed_yield` at `README.md:173-174`; it is not valid copy-paste Python.
