### Task Specific Domain Priors: Suzuki-Miyaura Cross-Coupling

**Reaction Context:**
This task optimizes a Suzuki-Miyaura cross-coupling, forming a C-C bond between an aryl halide (`Electrophile`) and an organoboron reagent (`Nucleophile`), catalyzed by palladium(II) acetate with a phosphine `Ligand`, a `Base`, and a `Solvent`.

**Favorable Operating Regime (qualitative priors):**
- The transmetalation step is base-activated, so the reaction generally favors **mildly basic** conditions; a `Base` of `Nothing` is usually unproductive.
- It generally tolerates and often prefers **polar / protic or aqueous-compatible** media over inert apolar ones.
- The phosphine `Ligand` strongly modulates the Pd catalytic cycle: electron-rich, bulky phosphines accelerate oxidative addition and reductive elimination, whereas `Ligand = Nothing` typically stalls the cycle.
- Boronic acids / esters and trifluoroborates are all competent `Nucleophile` forms; oxidative addition is faster for aryl iodides/bromides than chlorides/triflates.

**Usage Instruction:**
Use these priors only to (1) guide cold-start proposals before `lenz` has a trustworthy surrogate, and (2) break near-ties in acquisition score by preferring the candidate whose ligand/base/solvent best matches the regime above. Never let these priors override strong observed evidence from Experiment Receipts, and never treat them as measured results.
