### Task Specific Domain Priors: Direct Arylation (BMS-911543)

**Reaction Context:**
This task optimizes a palladium-catalyzed direct arylation — a C-H activation / arylation step in the synthesis of BMS-911543 (a JAK2 inhibitor). The searchable knobs are the carboxylate `Base`, phosphine `Ligand`, `Solvent`, substrate `Concentration_M`, and reaction `Temp_C`; the aryl substrates and Pd catalyst are fixed.

**Favorable Operating Regime (qualitative priors):**
- Direct arylation proceeds by base-assisted concerted metalation-deprotonation (CMD); the carboxylate `Base` (acetate vs. bulkier pivalate) and its counter-cation (K vs. Cs) strongly influence the C-H activation step. Cs carboxylates are often more effective than K.
- The reaction generally requires **elevated temperature** within the searchable range to drive the catalytic cycle.
- The `Ligand` dominates catalyst activity: electron-rich, bulky biarylphosphines (e.g., the BrettPhos/JackiePhos/X-Phos family) accelerate the turnover; small or weakly donating phosphines are typically less effective.
- Polar aprotic `Solvent` choice and `Concentration_M` jointly modulate rate and selectivity.

**Usage Instruction:**
Use these priors only to (1) guide cold-start proposals before `lenz` has a trustworthy surrogate, and (2) break near-ties in acquisition score by preferring the candidate whose base/ligand/temperature best matches the regime above. Never let these priors override strong observed evidence from Experiment Receipts, and never treat them as measured results.
