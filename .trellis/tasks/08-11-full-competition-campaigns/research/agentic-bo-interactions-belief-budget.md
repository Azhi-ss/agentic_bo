# Paper evidence note: interaction effects, belief revision, and budget allocation

## Scope

Primary sources only:

- Original paper text: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md`
- Bundled reproduction system prompt: `profiles/paper-reproduction/PAPER_SYSTEM.md`
- Bundled lenz reference: `profiles/paper-reproduction/PAPER_LENZ_REF.md`

The classifications below mean:

- **Explicit**: the source directly prescribes or states the mitigation.
- **Adjacent principle**: the source gives relevant guidance, but not the exact proposed mechanism.
- **Absent**: no prescription for the exact mechanism appears in the reviewed sources.

## Bottom line

The paper **does discuss adjacent failure modes**: coupled parameter interactions defeat coordinate-wise/local strategies; stochastic early choices create path-dependent trajectories; early tool-use patterns can persist; additional reasoning can second-guess a good domain prior; and agents can discard or over-trust beliefs improperly. It **does not explicitly formulate the exact failure** as “a prior learned under one interaction context is transferred to another context where its effect reverses,” nor does it prescribe mandatory one-factor revalidation after such transfer.

The source-authored response is adaptive and evidence-conditioned rather than a fixed revalidation tax: retain exact trial data, inspect surrogate diagnostics, compare candidates/regions, use exploratory acquisition when the model is weak, interpret every observation before the next trial, avoid abandoning a prior after one contradiction, and periodically escape repeated local moves. Mandatory revalidation would consume the same scarce black-box evaluation budget as optimization trials; the paper treats diagnostic, prediction, scoring, proposal, and reconfiguration calls as computational actions that do **not** consume that evaluation budget, while acknowledging their token/backend cost.

## Evidence matrix

| Question / failure | Is the exact failure discussed? | Source-authored mitigation | Classification |
| --- | --- | --- | --- |
| Interaction-dependent prior transfer / domain-prior overgeneralization | **No, not exactly.** The paper shows that coupled dimensions require joint modeling and that priors can help or be second-guessed, but does not analyze a prior whose validity changes specifically because another factor or interaction context changed. | Use a calibrated joint surrogate on coupled landscapes; score or predict prior-driven alternatives; state falsification evidence; do not treat plausibility as observed performance. | **Adjacent principle**; exact mitigation **absent**. |
| Local-search path dependence | **Yes, at the behavioral level.** Repeated runs follow different trajectories; an early tool-calling pattern tends to persist (“tool-use inertia”). Local and coordinate-wise strategies fail on jointly coupled landscapes. | Maintain tool-call diversity; compare an under-explored region after consecutive local moves unless acquisition and uncertainty rule it out; use a calibrated surrogate for joint structure. | Failure **explicit**; diversity intervention partly future work in the paper, concrete escape rule **explicit in bundled prompt/reference**. |
| Belief-update / belief-revision failure | **Partly.** Sources explicitly warn against discarding a prior after one contradictory trial, trusting a weak posterior, skipping reflection between trials, and letting extra reasoning override a strong context signal. They do not provide a formal belief-update algorithm. | Interpret each verified observation before the next trial; inspect `cv_r2`; use exploratory acquisition under weak diagnostics; require matched comparison or repetition for causal/SAR claims; identify what would falsify a prior. | **Explicit behavioral mitigations**, but a formal revision rule is **absent**. |
| Mandatory one-factor revalidation | **No.** Neither the paper nor bundled prompt requires revalidating every transferred prior or every changed factor one at a time. | The bundled prompt permits matched comparisons/repeated experiments for stronger causal claims, but says benchmark improvement is primary and explicitly forbids replacing a better acquisition-ranked candidate with a lower-value matched comparison merely to isolate a factor. | Mandatory policy **absent**; selective validation is an **adjacent principle**. |
| Exploration/exploitation under unreliable beliefs | **Yes.** The paper frames acquisition as balancing exploration and exploitation and identifies failures from weak surrogate trust and path-dependent ad hoc strategies. | Diagnose surrogate trust; switch to exploratory UCB/Sobol when unreliable; probe under-explored regions; avoid aggressive exploitation or bound narrowing on weak `cv_r2`. | **Explicit**. |
| Evaluation-budget distortion from required revalidation | **Not named as a failure.** The formalism does distinguish costly evaluations from computational deliberation, so the distortion follows directly if revalidation requires new oracle calls. | Prefer free-with-respect-to-evaluation-budget probes, predictions, scores, proposal comparisons, and temporary bounds before committing another real evaluation; spend information-gathering evaluations only when remaining actions can exploit the result. | Distortion is **inference**; budget distinction and last-step rule are **explicit**. |

## 1. Interaction effects and transfer of domain priors

### Paper text

- Classical BO uses an acquisition function to balance exploration and exploitation, while agentic BO makes strategy choice responsive to priors, observations, and backend diagnostics: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:100-104` (Section 3.1).
- The chemistry experiments report that a language-model prior directs early evaluations to a productive region and the GP posterior then refines within that region: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:374-379` (Section 6.3).
- The clearest interaction claim is in the bash-only analysis: on Hartmann/Ackley, “interactions between dimensions cannot be resolved easily by optimizing each coordinate independently,” so a surrogate modeling the joint response surface has an advantage; chemistry objectives are described as approximately separable and dominated by a few main effects: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:896-945` (Section D.1, paragraphs beginning “Second, the value of the surrogate…” and “2. Coordinate descent”).
- Random GP sample paths couple all input dimensions through the kernel covariance; coordinate-wise strategies cannot exploit separability, and the calibrated surrogate is beneficial: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:932-945` (Section D.1, “Optimization of GP sample paths”).
- Additional reasoning sometimes harms the warm start by overriding or second-guessing a strong context-derived prior: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:832-861` (Figure 17 discussion and Section C.1); the main ablation also says additional reasoning can produce a worse warm start: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:390-493` (Section 6.5, “Effect of reasoning level”).

### Bundled prompt/reference text

- A prior must be converted to a concrete value; priors formed from trial history should be tested like any other: `profiles/paper-reproduction/PAPER_SYSTEM.md:29-31`.
- Chemical plausibility is not measured evidence. A prior-driven override should name exact candidates, use prediction/scoring, and state what observation would falsify the prior: `profiles/paper-reproduction/PAPER_SYSTEM.md:33-37`.
- Exact candidate identity must not be collapsed into informal families when counting evidence: `profiles/paper-reproduction/PAPER_SYSTEM.md:33-37`.
- Persistent narrowing is allowed only after evidence and/or a strong prior; one-off probes should use temporary bounds: `profiles/paper-reproduction/PAPER_LENZ_REF.md:186-196`.
- A prior-driven candidate can be compared against surrogate suggestions with `score`: `profiles/paper-reproduction/PAPER_LENZ_REF.md:286-296`.

### Classification

- **Exact interaction-dependent transfer failure: absent.** The sources do not state that a main-effect prior established under context $z_1$ must be invalidated or re-estimated under context $z_2$, nor do they give a transfer criterion.
- **Adjacent explicit principles:** model coupled dimensions jointly; keep candidate identity exact; treat priors as falsifiable rather than as observations; use surrogate scoring/prediction before overriding acquisition evidence.

## 2. Local-search path dependence and interaction history

### Paper text

- The formal state retains data, mutable configuration, exogenous context, and deliberation history. Later instructions can semantically supersede earlier ones; tool calls, proposals, and interventions remain in history: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:120-137` (Section 4, “State”).
- Each computational response updates the state conditioning the next action, and the final configuration carries into the next campaign step: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:152-178` (Section 4, “Metalevel policy and deliberation,” equations 4.3–4.4).
- With domain context, Sara increasingly uses local `suggest --around`; without context, generic proposals remain prominent: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:380-389` (Section 6.4, “Adaptive tool use”).
- Repeated identical problems follow different trajectories. The paper explicitly reports “tool-use inertia”: a calling pattern adopted early tends to persist, reducing strategy diversity. It proposes maintaining tool-call diversity through prompting or architecture as future work: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:494-521` (Section 7, “Non-determinism”).
- Tool-use order varies across tasks, prior conditions, and seeds, but timelines do not establish why commands were selected or that more calls improve performance: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:946-953` (Section D.2).

### Bundled prompt/reference text

- Search sequencing—global exploration, local refinement, tightening, or widening—must be chosen from current evidence: `profiles/paper-reproduction/PAPER_SYSTEM.md:70-72`.
- After consecutive local moves along the same dimension, actively compare an under-explored region unless acquisition and posterior uncertainty quantitatively rule it out: `profiles/paper-reproduction/PAPER_SYSTEM.md:72-74`; repeated in `profiles/paper-reproduction/PAPER_LENZ_REF.md:159-171`.
- Temporary `suggest --around` pins omitted dimensions at the incumbent, making its local and potentially path-dependent nature explicit: `profiles/paper-reproduction/PAPER_LENZ_REF.md:159-185`.

### Classification

- **Explicit failure:** stochastic trajectory dependence and early-pattern tool-use inertia.
- **Explicit mitigation in bundled materials:** force an under-explored-region comparison after repeated same-dimension local moves, unless quantitative evidence justifies staying local.
- **Paper-level mitigation status:** maintaining tool-call diversity is identified as an important future direction, not demonstrated as a solved mechanism.

## 3. Belief revision and posterior-update failures

### Paper text

- Sequential reflection is a core directive: each suggest–evaluate–observe cycle is a new reasoning step, and the result must be interpreted before the next candidate. The stated motivation is preventing a full loop with no intermediate reasoning: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:264-290` (Table 2).
- The paper cautions that prompting mitigates but does not eliminate batching/looping; coding-agent turn economy can trade surrogate-update frequency for fewer turns, and full enforcement would require harness constraints: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:281-290` (Table 2 footnote 1).
- The original paper prompt says only `observe` moves the posterior and requires observing before another suggestion when information is available: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:1048-1054` (Appendix F, “The trial loop”).
- Original anti-patterns include blindly trusting an untrustworthy posterior, talking oneself out of explicit context, discarding a prior on one contradicting trial, and treating predictions as observations: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:1062-1076` (Appendix F).
- Diagnostics expose cross-validated $R^2$ and sensitivities to help assess surrogate trust: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:200-255` (Section 5.1, “probe”).

### Bundled prompt/reference text

- One verified observation must be interpreted before the next commitment; `observe` is the operation that moves the posterior: `profiles/paper-reproduction/PAPER_SYSTEM.md:51-58`.
- When `cv_r2 < 0.2`, missing, or non-OK, the reproduction prompt explicitly switches to exploratory UCB with `beta=16` until diagnostics become trustworthy: `profiles/paper-reproduction/PAPER_SYSTEM.md:54-58`.
- One observation can support or weaken a mechanism hypothesis but cannot confirm SAR/causality; stronger claims require a matched comparison or repetition: `profiles/paper-reproduction/PAPER_SYSTEM.md:35-37`; `profiles/paper-reproduction/PAPER_LENZ_REF.md:260-269`.
- The reference says low or negative cross-validated $R^2$ makes the surrogate untrustworthy and should be checked before aggressive exploitation, narrowing, or sensitivity claims: `profiles/paper-reproduction/PAPER_LENZ_REF.md:250-269`.
- Exploratory UCB or Sobol is prescribed when diagnostics indicate model unreliability: `profiles/paper-reproduction/PAPER_LENZ_REF.md:198-217`.

### Classification

- **Explicit mitigations:** sequential observation/reflection, posterior-trust diagnostics, exploratory acquisition under weak fit, falsifiable priors, and caution against revising a prior from one contradictory point.
- **Absent:** a quantitative Bayesian update rule for the LLM's semantic/domain beliefs. The GP posterior updates formally through observed data, but semantic belief revision remains prompt-governed.

## 4. Is mandatory one-factor revalidation prescribed?

**No.** No reviewed source requires one-factor-at-a-time revalidation whenever a prior is transferred, an incumbent changes, or an interacting factor moves.

Relevant nearby guidance is narrower:

- The bundled prompt requires matched comparison or repetition only before making stronger SAR/causality claims, not before using every prior: `profiles/paper-reproduction/PAPER_SYSTEM.md:35-37`; `profiles/paper-reproduction/PAPER_LENZ_REF.md:260-269`.
- For benchmark optimization, improvement is primary. Information has value only if a remaining action can exploit it, and the agent must not replace a better acquisition-ranked candidate with a lower-value matched comparison merely to isolate a factor: `profiles/paper-reproduction/PAPER_SYSTEM.md:52-56`.
- With one evaluation left, the prompt explicitly says not to spend it mainly on a matched comparison or information whose benefit cannot be used later: `profiles/paper-reproduction/PAPER_SYSTEM.md:62-68`.
- Per-dimension local refinement is available as an optional search move, not a universal validation requirement: `profiles/paper-reproduction/PAPER_LENZ_REF.md:159-185`.

**Classification:** mandatory one-factor revalidation is **absent** and, as a blanket benchmark policy, is in tension with the bundled prompt's explicit value-of-information and final-evaluation rules.

## 5. Computational budget versus evaluation budget

### Paper text

- A real oracle evaluation is the **only** action that advances campaign counter $t$ and consumes black-box evaluation budget: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:138-142` (Section 4, action space).
- Probe, propose, and reconfigure calls do not consume black-box evaluation budget or advance $t$, but incur tokens, context, and backend-compute overhead: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:142-152`.
- The experimental protocol compares methods under the same evaluation budget and reports performance against number of evaluations: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:690-692` (Appendix A).
- Token use scales roughly with evaluation budget. GPT 5.5 uses roughly $1.5$–$2\times$ more tokens and more tool calls; higher token expenditure correlates with stronger prior-informed performance, but the paper explicitly rejects a clear causal conclusion: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:850-861` (Sections C.1–C.2).
- The meta-MDP assigns separate costs $c_{\mathrm{eval}}$ and $c_{\mathrm{comp}}$, separate weights $\lambda_{\mathrm{eval}}$ and $\lambda_{\mathrm{comp}}$, and permits hard evaluation/time/resource budgets. The evaluated Sara policy is not claimed optimal for this objective, and learning a cost-aware policy is future work: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:954-991` (Appendix E, equation E.1 and following paragraphs).

### Bundled prompt/reference text

- The campaign should spend the whole evaluation budget by default; early stopping requires target attainment, infeasibility, exhausted distinct candidates, or quantified convergence: `profiles/paper-reproduction/PAPER_SYSTEM.md:62-66`.
- Scoring, prediction, diagnostics, and suggestions are read-only/computational comparisons; a real evaluation reaches state only when observed: `profiles/paper-reproduction/PAPER_LENZ_REF.md:51-63,102-123,250-300`.

### Inference

- **[INFERENCE]** Mandatory one-factor revalidation is not computational deliberation if it calls the real oracle; each such check consumes one of the same evaluations used for leaderboard optimization. Thus it changes the effective allocation from “maximize best observed value” toward “purchase confirmatory information.” This is especially costly late in a fixed 40-evaluation campaign because the result has fewer remaining steps in which to improve selection.
- **[INFERENCE]** Prediction, acquisition scoring, diagnostics, exact-candidate comparisons, and temporary regional proposals are the paper-aligned first line for challenging a transferred prior because they preserve evaluation budget, though they cannot replace a real experiment when causal confirmation is itself the objective.

## 6. Implications for the proposed design

1. **Do not encode universal one-factor revalidation as a mandatory campaign step.** It is not source-prescribed and can distort a fixed evaluation budget. Use it selectively when the expected information can change later candidate selection or when the campaign's objective includes causal/SAR confidence. Evidence: `profiles/paper-reproduction/PAPER_SYSTEM.md:52-56,62-68`; budget formalism at `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:138-152,954-991`.
2. **Represent prior applicability as conditional and falsifiable.** Store the exact candidate/context supporting a belief, the competing exact candidates, and the observation that would weaken it. Do not generalize family-level evidence across distinct candidates. Evidence: `profiles/paper-reproduction/PAPER_SYSTEM.md:29-37`. **[INFERENCE]** This is the minimum design response to interaction-dependent transfer because the paper does not supply a formal transfer rule.
3. **Use joint surrogate evidence to guard against interaction mistakes.** Before coordinate-wise/local exploitation or persistent narrowing, inspect cross-validated fit and compare acquisition/prediction over exact alternatives and under-explored regions. Evidence: `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:896-945`; `profiles/paper-reproduction/PAPER_LENZ_REF.md:186-217,250-296`.
4. **Add a local-path escape condition, not a fixed periodic tax.** After consecutive same-dimension local moves, require an under-explored-region comparison unless quantified acquisition and uncertainty support remaining local. Evidence: `profiles/paper-reproduction/PAPER_SYSTEM.md:70-74`; `profiles/paper-reproduction/PAPER_LENZ_REF.md:159-171`.
5. **Keep belief revision sequential and evidence-graded.** One observation may weaken/support a hypothesis; matched comparisons or repeats justify stronger causal claims; no single contradiction should automatically erase a prior. Evidence: `profiles/paper-reproduction/PAPER_SYSTEM.md:35-37,51-58,76-85`.
6. **Separate accounting.** Track real evaluations independently from tokens/tool/backend compute, and record whether an evaluation's intent is optimization, exploration, or discrimination. Evidence: distinct action costs in `references/2608.00316_agentic_bayesian_optimization/2608.00316.md:138-152,954-991`; intent/audit fields in `profiles/paper-reproduction/PAPER_SYSTEM.md:92-93`. **[INFERENCE]** This makes any revalidation cost visible rather than silently reducing the optimization budget.

## Answer to the exact assignment

1. **Exact failure discussed?** No for interaction-dependent prior transfer; yes for adjacent interaction, path-dependence, weak-posterior, and belief-revision failures.
2. **Explicit mitigation?** Yes for sequential reflection, diagnostics, exploratory acquisition, exact comparisons, falsifiable priors, and escaping repeated local moves; no formal semantic-belief update or transfer-validity rule.
3. **Mandatory one-factor revalidation?** No; only selective matched comparisons/repeats for stronger claims, with explicit warnings not to sacrifice better optimization candidates merely to isolate a factor.
4. **Computational vs evaluation budget?** Explicitly separate. Only real oracle calls consume evaluation budget; tool deliberation consumes tokens/backend compute. Appendix E models both costs but leaves the optimal trade-off unresolved.
5. **Design implication?** Prefer conditional, evidence-triggered validation and joint-surrogate/global comparisons. If a real one-factor revalidation is chosen, charge it explicitly to the evaluation budget and require a plausible downstream decision it can change.
