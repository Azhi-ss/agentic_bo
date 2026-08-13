import test from "node:test";
import assert from "node:assert/strict";

import { acquisitionScore, autonomousSystemPrompt, campaignResult, createCampaignActionTools, createLenzTools, createRetryPrompt, createStepInstruction, crossContextCoverage, declaredRunProvenance, enforcePreferredSuggestion, gpDissentStreak, leakagePreflight, lowTrustAcquisition, nearBestCandidates, optimizationPolicy, preferredSuggestion, promptWithTransientRetries, reconcileTrajectory, replayOptimizationPolicy, requireCampaignAction, requireOk, requirePolicyAllowance, requireReceipt, resolveAutonomousPolicyAudit, sanitizeAutonomousContext, scopeOverreach, validateCampaignStatus, validateDecisionEvidence, verifyCommitment, verifiedTrialFacts, verifyOptimizationPolicy, verifyStop } from "./campaign.mjs";

const offered = [{
  candidate_id: "candidate-a",
  pool_index: 7,
  config: { ligand: "PPh3", base: "NaHCO3" },
}];

test("campaign step rejects a turn without an explicit action", () => {
  assert.throws(() => requireCampaignAction(undefined), /no explicit campaign action/i);
});

test("commitment identity requires the exact pool index and configuration", () => {
  assert.throws(
    () => verifyCommitment({ pool_index: 7, config: { ligand: "PPh3", base: "KOH" } }, offered),
    /does not match candidate identity/i,
  );
});

test("commitment identity ignores JSON object key order", () => {
  const decision = verifyCommitment({ pool_index: 7, config: { base: "NaHCO3", ligand: "PPh3" } }, offered);
  assert.equal(decision.candidate_id, "candidate-a");
});

test("commitment identity compares nested configuration values", () => {
  const nested = [{ candidate_id: "nested-a", pool_index: 8, config: { model: { depth: 2, width: 64 } } }];
  assert.throws(
    () => verifyCommitment({ pool_index: 8, config: { model: { depth: 8, width: 64 } } }, nested),
    /does not match candidate identity/i,
  );
});

test("a valid public candidate outside the initial proposal snapshot reaches lenz validation", () => {
  const decision = verifyCommitment({ pool_index: 99, config: { ligand: "SPhos", base: "KOH" } }, offered);
  assert.equal(decision.pool_index, 99);
});

test("an already observed pool index is rejected before submission", () => {
  assert.throws(
    () => verifyCommitment(
      { pool_index: 7, config: { ligand: "PPh3", base: "NaHCO3" } },
      offered,
      [{ candidate_id: "candidate-a", pool_index: 7 }],
    ),
    /already observed.*pool_index 7/i,
  );
});

test("an already observed candidate id is rejected before submission", () => {
  assert.throws(
    () => verifyCommitment(
      { pool_index: 7, config: { ligand: "PPh3", base: "NaHCO3" } },
      offered,
      [{ candidate_id: "candidate-a", pool_index: 99 }],
    ),
    /already observed.*candidate-a/i,
  );
});

test("enforced policy reports low trust without rejecting a supported commitment", () => {
  const context = {
    diagnostics: { train_r2: 0.99, cv_r2: -0.3, cv_r2_status: "ok", lengthscales: { ligand: 1 } },
    suggestions: [{ ...offered[0], acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 7, config: offered[0].config };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory: [], manifest: { target: "Yield", direction: "maximize" } });

  assert.equal(optimizationPolicy(context, [], {}).trust, "low");
  assert.equal(decision.pool_index, 7);
  assert.equal(decision.policy_audit.mode, "enforced");
  assert.equal(decision.policy_audit.would_reject, false);
});


test("preferred suggestion keeps the surrogate ordering", () => {
  const suggestions = [
    { pool_index: 7, acquisition_value: 0.9, posterior_mean: 80 },
    { pool_index: 2, acquisition_value: 0.9, posterior_mean: 90 },
  ];

  assert.equal(preferredSuggestion(suggestions).pool_index, 7);
});

test("non-terminal optimization permits an evidence-backed alternative", () => {
  const preferred = { pool_index: 7, config: { x: 1 } };
  assert.doesNotThrow(() => enforcePreferredSuggestion({ pool_index: 7, config: { x: 1 } }, preferred, 4));
  assert.doesNotThrow(() => enforcePreferredSuggestion({ pool_index: 2, config: { x: 2 }, evidence_sources: ["prior"] }, preferred, 4));
});

test("terminal optimization may choose a near-best alternative", () => {
  assert.doesNotThrow(() => enforcePreferredSuggestion({ pool_index: 2, config: { x: 2 } }, { pool_index: 7, config: { x: 1 } }, 1));
});

test("preferred suggestion is not rejected as a stalled policy", () => {
  const trajectory = [
    { decision: { intent: "optimize", config: { x: 1 } }, metrics: { Score: 80 } },
    { decision: { intent: "optimize", config: { x: 2 } }, metrics: { Score: 70 } },
    { decision: { intent: "optimize", config: { x: 3 } }, metrics: { Score: 60 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.99, cv_r2: -0.3, cv_r2_status: "ok", lengthscales: { x: 1 } },
    suggestions: [{ pool_index: 4, config: { x: 4 }, acquisition_value: 0.9 }],
    preferred_suggestion: { pool_index: 4, config: { x: 4 }, acquisition_value: 0.9 },
  };
  const decision = verifyOptimizationPolicy({
    commitment: { pool_index: 4, config: { x: 4 }, intent: "optimize", evidence_sources: ["acquisition"] },
    selectedScore: 0.9,
    context,
    trajectory,
    manifest: { target: "Score", direction: "maximize", budget: 10 },
  });

  assert.equal(decision.policy_audit.decision, "allow");
});
test("near-best candidates keep numerically tied terminal alternatives", () => {
  const candidates = [
    { pool_index: 1, acquisition_value: 0.5159254902 },
    { pool_index: 2, acquisition_value: 0.5159248897 },
    { pool_index: 3, acquisition_value: 0.50 },
  ];

  assert.deepEqual(nearBestCandidates(candidates).map((candidate) => candidate.pool_index), [1, 2]);
});

test("low-trust diagnostics select exploratory UCB with conservative beta", () => {
  assert.deepEqual(lowTrustAcquisition({ cv_r2: -0.1, cv_r2_status: "ok" }), { acqf: "ucb", beta: 1 });
  assert.deepEqual(lowTrustAcquisition({ cv_r2: 0.5, cv_r2_status: "ok" }), { acqf: "noisy_logei", beta: 2 });
});

test("supported offered alternatives are not hard-locked to preferred suggestion", () => {
  const commitment = {
    pool_index: 8,
    config: { ligand: "PPh3", base: "KOH" },
    intent: "explore",
    evidence_sources: ["information"],
    expected_learning: "separate two plausible regimes",
    result_use: "choose the next local region",
  };
  const preferred = { pool_index: 7, config: { ligand: "PPh3", base: "NaHCO3" } };

  assert.doesNotThrow(() => enforcePreferredSuggestion(commitment, preferred, 5));
});

test("autonomous profile has standalone non-GP-first instructions", () => {
  assert.match(autonomousSystemPrompt, /own the final optimization decision/i);
  assert.match(autonomousSystemPrompt, /non-binding advice/i);
  assert.match(autonomousSystemPrompt, /Surrogate Trust Assessment/);
  assert.match(autonomousSystemPrompt, /surrogate_trust_rationale/);
  for (const mode of ["exploit", "targeted_exploration", "global_exploration"]) assert.match(autonomousSystemPrompt, new RegExp(`"${mode}"`));
  assert.doesNotMatch(autonomousSystemPrompt, /preferred_suggestion|GP rank 1|beta=16/i);
});

test("retry prompt generator helper creates concise non-duplicative error messages", () => {
  const error = new Error("policy caution (stalled_policy): repeated signature");
  const autoRetry = createRetryPrompt(error, { autonomous: true });
  assert.match(autoRetry, /Your previous campaign action was rejected: policy caution/);
  assert.match(autoRetry, /commit_candidate/);
  assert.doesNotMatch(autoRetry, /Current verified campaign evidence/);
  assert.doesNotMatch(autoRetry, /JSON\.stringify|dataset_summary|historical_observed/);

  const defaultRetry = createRetryPrompt(error, { autonomous: false });
  assert.match(defaultRetry, /Your previous campaign action was rejected: policy caution/);
  assert.match(defaultRetry, /commit_candidate/);
  assert.match(defaultRetry, /stop_campaign/);
  assert.doesNotMatch(defaultRetry, /Current verified campaign evidence/);
});

test("system prompt and step prompt contracts clarify tool discipline and decision finalization", () => {
  const queryTools = ["lenz_diagnostics", "lenz_candidates", "lenz_suggest", "lenz_score", "lenz_predict", "lenz_trials"];
  for (const tool of queryTools) {
    assert.match(autonomousSystemPrompt, new RegExp(tool));
  }
  assert.match(autonomousSystemPrompt, /page.*lenz_trials.*historical separately/i);
  assert.match(autonomousSystemPrompt, /commit_candidate/);
  assert.match(autonomousSystemPrompt, /first step.*lenz_trials/i);
  assert.match(autonomousSystemPrompt, /global incumbent.*best finite target value/i);
  assert.match(autonomousSystemPrompt, /expected_objective_value.*strictly beats/i);
  assert.match(autonomousSystemPrompt, /transport or local-baseline.*decision_information/i);
  assert.match(autonomousSystemPrompt, /non-binding workflow.*lenz_suggest for a shortlist.*lenz_score and\/or lenz_predict/i);
  assert.match(autonomousSystemPrompt, /not a fixed order.*neither score nor predict is mandatory/i);
  assert.match(autonomousSystemPrompt, /interpret the verified Observation before requesting refreshed posterior advice/i);
  assert.match(autonomousSystemPrompt, /do not mechanically repeat.*without new observation or configuration evidence/i);
  assert.match(autonomousSystemPrompt, /repeated action patterns.*change strategy, hypothesis, or search region/i);

  const autoStep = createStepInstruction({ autonomous: true });
  for (const tool of queryTools) {
    assert.match(autoStep, new RegExp(tool));
  }
  assert.match(autoStep, /page.*lenz_trials.*historical separately/i);
  assert.match(autoStep, /commit_candidate/);
  assert.match(autoStep, /first step inspect verified observations/i);
  assert.match(autoStep, /global incumbent/i);
  assert.match(autoStep, /expected_objective_value.*strictly beats/i);
  assert.match(autoStep, /local-baseline or transport tests.*decision_information/i);
  assert.match(autoStep, /non-binding workflow.*lenz_suggest for a shortlist.*lenz_score and\/or lenz_predict/i);
  assert.match(autoStep, /not a fixed order.*neither score nor predict is mandatory/i);
  assert.match(autoStep, /interpret the verified Observation before requesting refreshed posterior advice/i);
  assert.match(autoStep, /do not mechanically repeat.*without new observation or configuration evidence/i);
  assert.match(autoStep, /repeated action patterns.*change strategy, hypothesis, or search region/i);

  const defaultStep = createStepInstruction({ autonomous: false });
  for (const tool of ["lenz_diagnostics", "lenz_suggest", "lenz_score", "lenz_predict", "lenz_trials"]) {
    assert.match(defaultStep, new RegExp(tool));
  }
  assert.doesNotMatch(defaultStep, /lenz_candidates/);
  assert.match(defaultStep, /commit_candidate/);
  assert.match(defaultStep, /stop_campaign/);
});

test("autonomous context allowlist excludes paths and ranked proposals", () => {
  const context = sanitizeAutonomousContext({
    state_revision: 2,
    status: { campaign_id: "c", target: "Yield", direction: "maximize", acqf: "noisy_logei", beta: 2, budget: 2, historical_observed: 3, observed: 0, pending: [], budget_remaining: 2, remaining: 10, public_root: "/secret" },
    dataset_summary: { rows: { candidate_pool: 10 } },
    verified_trials: [
      { source: "historical", metrics: { Yield: 90 } },
      { source: "campaign", metrics: { Yield: 80 } },
    ],
  });
  assert.equal(context.status.acqf, "noisy_logei");
  assert.equal(context.status.public_root, undefined);
  assert.equal(context.suggestions, undefined);
  assert.equal(context.preferred_suggestion, undefined);
  assert.equal(context.declared_provenance, undefined);
  assert.equal(Object.hasOwn(context, "verified_trials"), false);
});

test("shadow policy audits autonomous minimal context without ranked suggestions", () => {
  const context = sanitizeAutonomousContext({
    state_revision: 2,
    status: { campaign_id: "c", target: "Yield", direction: "maximize", acqf: "noisy_logei", beta: 2, budget: 2, historical_observed: 3, observed: 0, pending: [], budget_remaining: 2, remaining: 10 },
    dataset_summary: { rows: { candidate_pool: 10 } },
  });
  const commitment = { pool_index: 7, config: { ligand: "PPh3" }, intent: "explore", evidence_sources: ["prior"] };

  const decision = verifyOptimizationPolicy({ commitment, selectedScore: null, context, trajectory: [], manifest: { target: "Yield", direction: "maximize", budget: 2 } });

  assert.equal(Object.hasOwn(context, "suggestions"), false);
  assert.equal(decision.policy_audit.decision, "allow");
});

test("autonomous policy recognizes acquisition evidence from pulled proposals", () => {
  const context = {
    ...sanitizeAutonomousContext({
      state_revision: 2,
      status: { campaign_id: "c", target: "Yield", direction: "maximize", acqf: "noisy_logei", beta: 2, budget: 2, historical_observed: 3, observed: 0, pending: [], budget_remaining: 2, remaining: 10 },
      dataset_summary: { rows: { candidate_pool: 10 } },
    }),
    suggestions: [{ pool_index: 7, config: { ligand: "PPh3" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 7, config: { ligand: "PPh3" }, intent: "optimize", evidence_sources: ["acquisition"] };

  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory: [], manifest: { target: "Yield", direction: "maximize", budget: 2 } });

  assert.equal(decision.policy_audit.evidence.acquisition, true);
  assert.ok(!decision.policy_audit.flags.includes("unsupported_commitment"));
});

test("autonomous context allows only declared experiment provenance", () => {
  const context = sanitizeAutonomousContext({
    state_revision: 2,
    status: { campaign_id: "c", target: "Yield", direction: "maximize", acqf: "ucb", beta: 4, budget: 2, historical_observed: 3, observed: 0, pending: [], budget_remaining: 2, remaining: 10 },
    dataset_summary: { rows: { candidate_pool: 10 } },
    declared_provenance: { experiment_name: "public-name", experiment_policy: "autonomous_agent", declared_config_hash: "abc", source_config: "/tmp/secret.yaml", hidden_rank: 1 },
  });
  assert.deepEqual(context.declared_provenance, { experiment_name: "public-name", experiment_policy: "autonomous_agent", declared_config_hash: "abc" });
});

test("run audit provenance is additive, backward compatible, and policy-bound", () => {
  assert.deepEqual(declaredRunProvenance({}, "default"), { declared_config_hash: null, experiment_name: null, experiment_policy: "default" });
  assert.deepEqual(declaredRunProvenance({ normalized_config_hash: "hash", experiment_name: "experiment", experiment_policy: "autonomous_agent" }, "autonomous_agent"), { declared_config_hash: "hash", experiment_name: "experiment", experiment_policy: "autonomous_agent" });
  assert.throws(() => declaredRunProvenance({ experiment_policy: "autonomous_agent" }, "default"), /does not match runtime policy/);
});

test("autonomous tools omit permanent domain mutation and early stop", () => {
  const actionTools = createCampaignActionTools(() => {}, { autonomous: true });
  const commitCandidate = actionTools[0];
  const tools = createLenzTools(async () => ({ ok: true, result: [] }), "state", () => {}, () => {}, { autonomous: true }).map((tool) => tool.name);
  assert.deepEqual(actionTools.map((tool) => tool.name), ["commit_candidate"]);
  for (const field of ["surrogate_trust", "surrogate_trust_rationale", "search_mode", "decision_goal", "result_use"]) assert.ok(commitCandidate.parameters.required.includes(field));
  assert.deepEqual(commitCandidate.parameters.properties.surrogate_trust.anyOf.map((option) => option.const), ["low", "medium", "high"]);
  assert.deepEqual(commitCandidate.parameters.properties.search_mode.anyOf.map((option) => option.const), ["exploit", "targeted_exploration", "global_exploration"]);
  assert.deepEqual(commitCandidate.parameters.properties.decision_goal.anyOf.map((option) => option.const), ["incumbent_improvement", "decision_information"]);
  assert.equal(commitCandidate.parameters.properties.expected_objective_value.type, "number");
  assert.ok(!commitCandidate.parameters.required.includes("expected_objective_value"));
  assert.ok(tools.includes("lenz_candidates"));
  assert.ok(tools.includes("lenz_set_acqf"));
  assert.ok(!tools.some((name) => ["lenz_set_bounds", "lenz_set_objectives", "lenz_set_constraints"].includes(name)));
});
test("autonomous typed lenz descriptions preserve evidence semantics", () => {
  const tools = Object.fromEntries(createLenzTools(async () => ({ ok: true, result: [] }), "state", () => {}, () => {}, { autonomous: true }).map((tool) => [tool.name, tool]));

  assert.match(tools.lenz_suggest.description, /current posterior.*without committing or updating state/i);
  assert.match(tools.lenz_suggest.description, /repeating.*without a new observation or acquisition\/search change adds no evidence/i);
  assert.match(tools.lenz_score.description, /acquisition utility.*not a predicted outcome or observation/i);
  assert.match(tools.lenz_predict.description, /posterior mean and variance.*not acquisition utility or an observation/i);
  assert.match(tools.lenz_diagnostics.description, /fit and reliability evidence.*does not select candidates/i);
  assert.match(tools.lenz_trials.description, /verified trials.*Campaign evidence is the default.*historical separately/i);
  assert.match(tools.lenz_candidates.description, /label-free.*deterministic order.*not ranked evidence/i);
  assert.match(tools.lenz_set_acqf.description, /persistent|persist/i);
  assert.match(tools.lenz_set_acqf.description, /audited.*use only with evidence and rationale/i);
});

test("lenz_trials exposes bounded filters and forwards useful defaults", async () => {
  const calls = [];
  const evidence = [];
  const tools = createLenzTools(async (...args) => {
    calls.push(args);
    return { ok: true, result: { trials: [] } };
  }, "/campaign/frame/state.json", () => {}, (name) => evidence.push(name), { autonomous: true });
  const trials = tools.find((tool) => tool.name === "lenz_trials");

  assert.deepEqual(trials.parameters.properties.source.anyOf.map((option) => option.const), ["historical", "campaign", "all"]);
  assert.deepEqual(trials.parameters.properties.status.anyOf.map((option) => option.const), ["observed", "pending", "all"]);
  assert.equal(trials.parameters.properties.cursor.minimum, 0);
  assert.equal(trials.parameters.properties.limit.minimum, 1);
  assert.equal(trials.parameters.properties.limit.maximum, 100);
  assert.match(trials.description, /page/i);
  assert.match(trials.description, /historical separately/i);

  await trials.execute("call-1", {});
  assert.deepEqual(calls.at(-1), ["trials", "--state", "/campaign/frame/state.json", "--source", "campaign", "--status", "observed", "--cursor", "0", "--limit", "20"]);
  await trials.execute("call-2", { source: "historical", status: "pending", cursor: 5, limit: 100 });
  assert.deepEqual(calls.at(-1), ["trials", "--state", "/campaign/frame/state.json", "--source", "historical", "--status", "pending", "--cursor", "5", "--limit", "100"]);
  assert.deepEqual(evidence, ["lenz_trials", "lenz_trials"]);
});

test("Decision Evidence Record matches actual surrogate use", () => {
  const base = { pool_index: 7, config: offered[0].config, hypothesis: "plausible chemistry", evidence_sources: ["domain_prior"], expected_outcome: "higher yield", expected_learning: "updates next choice", rationale: "best current tradeoff", surrogate_trust: "medium", surrogate_trust_rationale: "cv_r2 0.5 moderate fit", search_mode: "targeted_exploration", decision_goal: "incumbent_improvement", expected_objective_value: 101, result_use: "Update the incumbent region ranking." };
  assert.equal(validateDecisionEvidence({ ...base, surrogate_relationship: "not_consulted" }, { calls: [] }).decision_evidence_complete, true);
  assert.equal(validateDecisionEvidence({ ...base, surrogate_relationship: "accept" }, { calls: ["lenz_suggest"], proposals: offered }).actual_tool_use.ranked_proposals_consulted, true);
  assert.throws(() => validateDecisionEvidence({ ...base, surrogate_relationship: "not_consulted" }, { calls: ["lenz_score"] }), /informed_without_proposal/);
  assert.throws(() => validateDecisionEvidence({ ...base, surrogate_trust: undefined, surrogate_relationship: "not_consulted" }, { calls: [] }), /surrogate_trust/);
  assert.throws(() => validateDecisionEvidence({ ...base, surrogate_trust: "very_low", surrogate_relationship: "not_consulted" }, { calls: [] }), /surrogate_trust/);
  assert.throws(() => validateDecisionEvidence({ ...base, search_mode: "local", surrogate_relationship: "not_consulted" }, { calls: [] }), /search_mode/);
  assert.throws(() => validateDecisionEvidence({ ...base, decision_goal: "learn", surrogate_relationship: "not_consulted" }, { calls: [] }), /decision_goal/);
  assert.throws(() => validateDecisionEvidence({ ...base, result_use: "", surrogate_relationship: "not_consulted" }, { calls: [] }), /result_use/);
  assert.throws(() => validateDecisionEvidence({ ...base, decision_goal: "decision_information", surrogate_relationship: "not_consulted" }, { calls: [] }), /follow_up_if_supported/);
  assert.equal(validateDecisionEvidence({ ...base, decision_goal: "decision_information", follow_up_if_supported: "Exploit the supported region.", follow_up_if_refuted: "Return to the incumbent shortlist.", surrogate_relationship: "not_consulted" }, { calls: [] }).decision_evidence_complete, true);
  assert.throws(() => validateDecisionEvidence({ ...base, surrogate_trust: "low", surrogate_trust_rationale: "gp is best", surrogate_relationship: "accept" }, { calls: ["lenz_suggest"], proposals: offered }), /non-surrogate evidence/);
  assert.throws(() => validateDecisionEvidence({ ...base, surrogate_trust: "low", surrogate_trust_rationale: "accept despite low trust because GP rank 1 is best", surrogate_relationship: "accept" }, { calls: ["lenz_suggest"], proposals: offered }), /non-surrogate evidence/);
  assert.equal(validateDecisionEvidence({ ...base, surrogate_trust: "low", surrogate_trust_rationale: "accept despite low trust because the verified receipt supports this region", surrogate_relationship: "accept" }, { calls: ["lenz_suggest"], proposals: offered }).decision_evidence_complete, true);
  assert.equal(validateDecisionEvidence({ ...base, search_mode: "exploit", surrogate_relationship: "not_consulted" }, { calls: [] }).decision_evidence_complete, true);
});

test("incumbent improvement expected value strictly beats the global verified maximum", () => {
  const base = { pool_index: 7, config: offered[0].config, hypothesis: "transport a promising local result", evidence_sources: ["observation"], expected_outcome: "higher yield", expected_learning: "tests transport", rationale: "bounded comparison", surrogate_trust: "medium", surrogate_trust_rationale: "verified observations define the region", search_mode: "targeted_exploration", decision_goal: "incumbent_improvement", result_use: "Update the global ranking.", surrogate_relationship: "not_consulted" };
  const boundary = { verifiedTrials: [{ source: "historical", metrics: { Yield: 90 } }, { source: "campaign", metrics: { Yield: 80 } }], target: "Yield", direction: "maximize" };

  assert.throws(() => validateDecisionEvidence(base, { calls: [] }, boundary), /finite expected_objective_value/);
  assert.throws(() => validateDecisionEvidence({ ...base, expected_objective_value: Number.NaN }, { calls: [] }, boundary), /finite expected_objective_value/);
  assert.throws(() => validateDecisionEvidence({ ...base, expected_objective_value: 85 }, { calls: [] }, boundary), /global verified incumbent 90/);
  assert.throws(() => validateDecisionEvidence({ ...base, expected_objective_value: 90 }, { calls: [] }, boundary), /strictly beat/);
  assert.equal(validateDecisionEvidence({ ...base, expected_objective_value: 90.1 }, { calls: [] }, boundary).decision_evidence_complete, true);
});

test("incumbent improvement expected value strictly beats the global verified minimum", () => {
  const commitment = { pool_index: 7, config: offered[0].config, hypothesis: "reduce loss", evidence_sources: ["observation"], expected_outcome: "lower loss", expected_learning: "updates next choice", rationale: "best current tradeoff", surrogate_trust: "medium", surrogate_trust_rationale: "verified observations define the region", search_mode: "exploit", decision_goal: "incumbent_improvement", result_use: "Update the global ranking.", surrogate_relationship: "not_consulted" };
  const boundary = { verifiedTrials: [{ source: "historical", metrics: { Loss: 4 } }, { source: "campaign", metrics: { Loss: 7 } }], target: "Loss", direction: "minimize" };

  assert.throws(() => validateDecisionEvidence({ ...commitment, expected_objective_value: 4 }, { calls: [] }, boundary), /strictly beat/);
  assert.throws(() => validateDecisionEvidence({ ...commitment, expected_objective_value: 5 }, { calls: [] }, boundary), /global verified incumbent 4/);
  assert.equal(validateDecisionEvidence({ ...commitment, expected_objective_value: 3.9 }, { calls: [] }, boundary).decision_evidence_complete, true);
});

test("local-baseline transport work falls back to valid decision information", () => {
  const commitment = { pool_index: 7, config: offered[0].config, hypothesis: "transport a local improvement", evidence_sources: ["observation"], expected_outcome: "beat the matched local baseline", expected_learning: "tests whether the effect transports", rationale: "resolves a bounded comparison", surrogate_trust: "medium", surrogate_trust_rationale: "verified observations define both contexts", search_mode: "targeted_exploration", result_use: "Rerank the transported region.", surrogate_relationship: "not_consulted" };
  const boundary = { verifiedTrials: [{ source: "historical", metrics: { Yield: 95 } }, { source: "campaign", metrics: { Yield: 60 } }], target: "Yield", direction: "maximize" };

  assert.throws(() => validateDecisionEvidence({ ...commitment, decision_goal: "incumbent_improvement", expected_objective_value: 70 }, { calls: [] }, boundary), /global verified incumbent 95/);
  assert.equal(validateDecisionEvidence({ ...commitment, decision_goal: "decision_information", follow_up_if_supported: "Test the best transported neighbor.", follow_up_if_refuted: "Return to the global incumbent region." }, { calls: [] }, boundary).decision_evidence_complete, true);
});

test("incumbent improvement is allowed when no finite global incumbent exists", () => {
  const commitment = { pool_index: 7, config: offered[0].config, hypothesis: "establish a finite baseline", evidence_sources: ["prior"], expected_outcome: "finite objective", expected_learning: "initializes ranking", rationale: "no finite observations exist", surrogate_trust: "low", surrogate_trust_rationale: "no verified finite observation exists", search_mode: "global_exploration", decision_goal: "incumbent_improvement", expected_objective_value: 1, result_use: "Establish the first incumbent.", surrogate_relationship: "not_consulted" };
  const boundary = { verifiedTrials: [{ metrics: { Score: null } }, { metrics: { Score: Number.NaN } }, { metrics: {} }], target: "Score", direction: "maximize" };

  assert.equal(validateDecisionEvidence(commitment, { calls: [] }, boundary).decision_evidence_complete, true);
});

test("candidate inspection enforces 500 returned rows per step", async () => {
  const response = { ok: true, result: { candidates: Array.from({ length: 100 }, (_, pool_index) => ({ pool_index })) } };
  const tools = createLenzTools(async () => response, "state", () => {}, () => {}, { autonomous: true });
  const candidates = tools.find((tool) => tool.name === "lenz_candidates");
  for (let call = 0; call < 5; call += 1) await candidates.execute("id", { limit: 100 });
  await assert.rejects(() => candidates.execute("id", { limit: 1 }), /500 returned rows/);
  tools.resetStep();
  await assert.doesNotReject(() => candidates.execute("id", { limit: 1 }));
});

test("tool evidence records only successful lenz results", async () => {
  const evidence = [];
  const tools = createLenzTools(async (command) => command === "predict" ? { ok: false, error: "invalid candidate" } : { ok: true, result: [] }, "state", () => {}, (name) => evidence.push(name), { autonomous: true });
  await tools.find((tool) => tool.name === "lenz_predict").execute("id", { configs: [{ ligand: "invalid" }] });
  await tools.find((tool) => tool.name === "lenz_suggest").execute("id", {});
  assert.deepEqual(evidence, ["lenz_suggest"]);
});

test("leakage preflight fails closed on forbidden context or enabled resources", () => {
  const good = { prompt: autonomousSystemPrompt, toolNames: ["lenz_candidates"], context: { status: {} }, runtime: { noTools: "builtin", noExtensions: true, noSkills: true, noPromptTemplates: true, noContextFiles: true }, prior: { prior_hash: "hash", prior_source: "PRIOR.md", prior_scan: "label_free", prior_provenance: "mechanism_or_pre_experiment_source" } };
  assert.equal(leakagePreflight(good).passed, true);
  assert.throws(() => leakagePreflight({ ...good, context: { dataset_root: "/tmp/data" } }), /leakage preflight failed/);
  assert.throws(() => leakagePreflight({ ...good, runtime: { ...good.runtime, noSkills: false } }), /runtime_resources_enabled/);
});

test("shadow policy challenges an unsupported stalled action signature", () => {
  const trajectory = [
    { decision: { intent: "discriminate", evidence_sources: ["information"], config: { catalyst: "A", temperature: 20 } }, metrics: { Score: 90 } },
    { decision: { intent: "discriminate", evidence_sources: ["information"], config: { catalyst: "B", temperature: 20 } }, metrics: { Score: 80 } },
    { decision: { intent: "discriminate", evidence_sources: ["information"], config: { catalyst: "C", temperature: 20 } }, metrics: { Score: 70 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.99, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { catalyst: 1 } },
    suggestions: [{ pool_index: 1, config: { catalyst: "E", temperature: 30 }, acquisition_value: 0.9 }],
  };
  const commitment = {
    pool_index: 99,
    config: { catalyst: "D", temperature: 20 },
    intent: "discriminate",
    evidence_sources: ["information"],
    expected_learning: "Rank another catalyst under the same background.",
    result_use: "Continue the same catalyst screen.",
  };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.1, context, trajectory, manifest: { target: "Score", direction: "maximize", budget: 10 } });

  assert.equal(decision.policy_audit.decision, "challenge");
  assert.ok(decision.policy_audit.flags.includes("stalled_policy"));
  assert.match(decision.policy_audit.required_justification.join(" "), /unresolved hypothesis/i);
});

test("autonomous advisory cautions retry twice then retain the final audited decision", () => {
  const decision = {
    pool_index: 99,
    config: { catalyst: "D", temperature: 20 },
    policy_audit: {
      decision: "challenge",
      flags: ["cross_context_uncovered", "stalled_policy", "scope_overreach", "gp_dissent"],
      required_justification: ["Explain why this commitment remains worthwhile."],
    },
  };

  assert.throws(() => resolveAutonomousPolicyAudit(decision, 1, 3), /policy caution/i);
  assert.throws(() => resolveAutonomousPolicyAudit(decision, 2, 3), /policy caution/i);
  const accepted = resolveAutonomousPolicyAudit(decision, 3, 3);

  assert.equal(accepted.pool_index, 99);
  assert.deepEqual(accepted.policy_audit.flags, decision.policy_audit.flags);
  assert.deepEqual(accepted.policy_audit.required_justification, decision.policy_audit.required_justification);
  assert.equal(accepted.policy_audit.advisory_outcome, "exhausted_accepted");
});

test("competition policy challenge retries twice then accepts the final validated action", () => {
  const decision = {
    pool_index: 99,
    policy_audit: {
      decision: "challenge",
      flags: ["middle_global_exploration"],
      required_justification: ["Use a shortlist candidate or name executable follow-ups."],
    },
  };

  assert.throws(() => resolveAutonomousPolicyAudit(decision, 1, 3), /policy caution/i);
  assert.throws(() => resolveAutonomousPolicyAudit(decision, 2, 3), /policy caution/i);
  assert.equal(resolveAutonomousPolicyAudit(decision, 3, 3).policy_audit.advisory_outcome, "exhausted_accepted");
});

test("autonomous policy exhaustion never accepts non-advisory challenges", () => {
  const decision = { policy_audit: { decision: "challenge", flags: ["unsupported_commitment"] } };
  assert.throws(() => resolveAutonomousPolicyAudit(decision, 3, 3), /policy challenge.*unsupported_commitment/i);
});

test("autonomous policy allows a healthy audited decision unchanged", () => {
  const decision = { policy_audit: { decision: "allow", flags: [] } };
  assert.equal(resolveAutonomousPolicyAudit(decision, 1, 3), decision);
});

test("shadow policy allows a productive repeated action signature", () => {
  const trajectory = [
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { architecture: "A", learning_rate: 0.1 } }, metrics: { Accuracy: 70 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { architecture: "B", learning_rate: 0.1 } }, metrics: { Accuracy: 80 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { architecture: "C", learning_rate: 0.1 } }, metrics: { Accuracy: 90 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { architecture: 1 } },
    suggestions: [{ pool_index: 99, config: { architecture: "D", learning_rate: 0.1 }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 99, config: { architecture: "D", learning_rate: 0.1 }, intent: "optimize", evidence_sources: ["acquisition"], expected_learning: "Test the best proposal.", result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Accuracy", direction: "maximize", budget: 10 } });

  assert.equal(decision.policy_audit.action_run.recent_improvements, 2);
  assert.equal(decision.policy_audit.decision, "allow");
});

test("high-trust shortlist override needs non-surrogate evidence", () => {
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { x: 1 } },
    suggestions: [{ pool_index: 1, config: { x: 1 }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 99, config: { x: 2 }, intent: "optimize", evidence_sources: ["acquisition"], expected_learning: "Try x=2.", result_use: "Use the result." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.1, context, trajectory: [], manifest: { target: "Score", direction: "maximize", budget: 10 } });

  assert.equal(decision.policy_audit.decision, "challenge");
  assert.ok(decision.policy_audit.flags.includes("unsupported_override"));
});

test("low-trust surrogate permits a domain-prior override", () => {
  const context = {
    diagnostics: { train_r2: 0.99, cv_r2: -0.2, cv_r2_status: "ok", lengthscales: { formulation: 1 } },
    suggestions: [{ pool_index: 1, config: { formulation: "A" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 99, config: { formulation: "B" }, intent: "explore", evidence_sources: ["prior"], expected_learning: "Test the documented formulation prior.", result_use: "Choose the next region." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.1, context, trajectory: [], manifest: { target: "Lifetime", direction: "maximize", budget: 10 } });

  assert.equal(decision.policy_audit.trust, "low");
  assert.equal(decision.policy_audit.decision, "allow");
});

test("late information probe must say how remaining actions can use it", () => {
  const trajectory = Array.from({ length: 8 }, (_, index) => ({
    decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { x: index } },
    metrics: { Score: index },
  }));
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { x: 1 } },
    suggestions: [{ pool_index: 99, config: { x: 9 }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 99, config: { x: 9 }, intent: "discriminate", evidence_sources: ["information"], expected_learning: "Separate two mechanisms." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Score", direction: "maximize", budget: 10 } });

  assert.equal(decision.policy_audit.budget.stage, "late");
  assert.ok(decision.policy_audit.flags.includes("terminal_information_waste"));
  assert.equal(decision.policy_audit.decision, "challenge");
});

test("unscored external commitment without evidence is challenged", () => {
  const context = { diagnostics: {}, suggestions: [] };
  const commitment = { pool_index: 99, config: { x: 2 }, rationale: "Try x=2." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: null, context, trajectory: [], manifest: { target: "Score", direction: "maximize", budget: 10 } });

  assert.equal(decision.policy_audit.evidence.acquisition, false);
  assert.ok(decision.policy_audit.flags.includes("unsupported_commitment"));
  assert.throws(() => requirePolicyAllowance(decision), /unsupported_commitment/i);
});

test("allowed policy decision reaches submission", () => {
  const decision = { pool_index: 7, policy_audit: { decision: "allow", flags: [] } };
  assert.equal(requirePolicyAllowance(decision), decision);
});

test("crossContextCoverage flags a frozen factor with inversion evidence", () => {
  // halide is frozen for 3 steps while additive is refined; the window shows
  // the frozen halide value I is strong with ligand L1 (85.9) but weak with
  // ligand L2 (57.9) — an inversion of the frozen factor across ligand.
  const trajectory = [
    { decision: { config: { product: "P", halide: "Br", ligand: "L1", additive: "a0" } }, metrics: { Yield: 55 } },
    { decision: { config: { product: "P", halide: "I", ligand: "L1", additive: "a1" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "I", ligand: "L1", additive: "a2" } }, metrics: { Yield: 85.9 } },
    { decision: { config: { product: "P", halide: "I", ligand: "L2", additive: "a2" } }, metrics: { Yield: 57.9 } },
    { decision: { config: { product: "P", halide: "I", ligand: "L1", additive: "a3" } }, metrics: { Yield: 84.9 } },
    { decision: { config: { product: "P", halide: "I", ligand: "L1", additive: "a4" } }, metrics: { Yield: 82 } },
  ];
  const next = { product: "P", halide: "I", ligand: "L1", additive: "a5" };
  const audit = crossContextCoverage(trajectory, next, "Yield", "maximize");

  assert.ok(audit, "detector should find the inversion");
  assert.equal(audit.frozen_factor, "halide");
  assert.equal(audit.value, "I");
  assert.equal(audit.other_dimension, "ligand");
  assert.equal(audit.strong_context, "L1");
  assert.equal(audit.weak_context, "L2");
  assert.ok(audit.strong_yield - audit.weak_yield >= 20);
});

test("crossContextCoverage returns null without a frozen factor", () => {
  // halide is varied in the most recent step, so it is not frozen.
  const trajectory = [
    { decision: { config: { product: "P", halide: "I", ligand: "L1", additive: "a1" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "Br", ligand: "L1", additive: "a1" } }, metrics: { Yield: 60 } },
    { decision: { config: { product: "P", halide: "Br", ligand: "L2", additive: "a1" } }, metrics: { Yield: 57.9 } },
  ];
  assert.equal(crossContextCoverage(trajectory, { product: "P", halide: "Br", ligand: "L2", additive: "a2" }, "Yield", "maximize"), null);
});

test("cross-context inversion remains telemetry for autonomous refinement", () => {
  const trajectory = [
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "Br", ligand: "L1", additive: "a0" } }, metrics: { Yield: 55 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", ligand: "L1", additive: "a1" } }, metrics: { Yield: 70 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", ligand: "L1", additive: "a2" } }, metrics: { Yield: 85.9 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", ligand: "L2", additive: "a2" } }, metrics: { Yield: 57.9 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", ligand: "L1", additive: "a3" } }, metrics: { Yield: 84.9 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", ligand: "L1", additive: "a4" } }, metrics: { Yield: 82 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [{ pool_index: 1, config: { product: "P", halide: "I", ligand: "L1", additive: "a5" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { product: "P", halide: "I", ligand: "L1", additive: "a5" }, decision_goal: "incumbent_improvement", search_mode: "exploit", evidence_sources: ["acquisition"], result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" } });

  assert.ok(decision.policy_audit.telemetry_flags.includes("cross_context_uncovered"));
  assert.ok(!decision.policy_audit.flags.includes("cross_context_uncovered"));
  assert.equal(decision.policy_audit.decision, "allow");
});

test("policy allows a refinement when the factor is not frozen", () => {
  const trajectory = [
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", ligand: "L1", additive: "a1" } }, metrics: { Yield: 70 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "Br", ligand: "L1", additive: "a1" } }, metrics: { Yield: 60 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "Br", ligand: "L2", additive: "a1" } }, metrics: { Yield: 57.9 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [{ pool_index: 1, config: { product: "P", halide: "Br", ligand: "L2", additive: "a2" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { product: "P", halide: "Br", ligand: "L2", additive: "a2" }, intent: "optimize", evidence_sources: ["acquisition"], expected_learning: "Refine additive under bromide/L2.", result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40 } });

  assert.ok(!decision.policy_audit.flags.includes("cross_context_uncovered"));
  assert.equal(decision.policy_audit.decision, "allow");
});

// halide stays I for the final 4 completed steps while additive is refined, and
// halide levels Cl/F were decided but never completed — untested counter-evidence
// the agent is not collecting. Shared by the scope-overreach tests.
const overreachTrajectory = () => ([
  { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
  { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
  { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
  { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
  { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
  { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 76 } },
  // Decided but never completed: these halide levels are untested counter-evidence.
  { decision: { intent: "optimize", evidence_sources: ["information"], config: { product: "P", halide: "Cl", additive: "z0" } } },
  { decision: { intent: "optimize", evidence_sources: ["information"], config: { product: "P", halide: "F", additive: "z0" } } },
]);

test("scopeOverreach returns null when the factor is not frozen", () => {
  const trajectory = [
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "Br", additive: "a5" } }, metrics: { Yield: 60 } },
  ];
  // halide changed in the most recent step, so it is not frozen.
  assert.equal(scopeOverreach(trajectory, { product: "P", halide: "I", additive: "a6" }, "Yield", "maximize"), null);
});

test("scopeOverreach flags a frozen factor with untested levels", () => {
  const audit = scopeOverreach(overreachTrajectory(), { product: "P", halide: "I", additive: "a6" }, "Yield", "maximize");

  assert.ok(audit, "detector should find the scope overreach");
  assert.equal(audit.frozen_factor, "halide");
  assert.equal(audit.frozen_value, "I");
  assert.ok(audit.untested_count >= 2, "untested halide levels should exist");
  assert.ok(audit.factor_levels > audit.untested_count);
});

test("scopeOverreach strict mode counts levels missing from completed observations against the searchspace", () => {
  // halide is frozen at I for the final 4 steps; the searchspace admits
  // halide levels {Br, I, Cl, F} but only Br and I were ever completed, so
  // Cl and F are untested even though neither was ever decided.
  const trajectory = [
    { decision: { config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
    { decision: { config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
    { decision: { config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 76 } },
  ];
  const searchspace = { halide: ["Br", "I", "Cl", "F"], additive: ["a0", "a1", "a2", "a3", "a4", "a5", "a6"] };

  const audit = scopeOverreach(trajectory, { product: "P", halide: "I", additive: "a6" }, "Yield", "maximize", { searchspace });

  assert.ok(audit, "detector should find the strict scope overreach");
  assert.equal(audit.frozen_factor, "halide");
  assert.equal(audit.frozen_value, "I");
  assert.equal(audit.factor_levels, 4, "factor_levels should be the full searchspace count");
  assert.equal(audit.untested_count, 2, "Cl and F are in the searchspace but never completed");
});

test("scopeOverreach strict mode counts levels against completed observations, not the recent window", () => {
  // halide levels Br and I are completed (Br outside the recent window) and
  // both are in the searchspace, so no halide level is untested in strict mode.
  const trajectory = [
    { decision: { config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
    { decision: { config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
    { decision: { config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 76 } },
  ];
  const searchspace = { halide: ["Br", "I"], additive: ["a0", "a1", "a2", "a3", "a4", "a5", "a6"] };

  const audit = scopeOverreach(trajectory, { product: "P", halide: "I", additive: "a6" }, "Yield", "maximize", { searchspace });

  // Br was completed at step 1 (outside the 8-entry window's recent tail);
  // strict mode uses ALL completed entries, so halide is fully covered.
  assert.ok(audit === null || audit.frozen_factor !== "halide", "fully covered halide must not be flagged for scope overreach");
});
test("scopeOverreach handles numeric candidate_values count in searchspace", () => {
  const trajectory = [
    { decision: { config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
    { decision: { config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
    { decision: { config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 76 } },
  ];
  const searchspace = { halide: 4, additive: 7 };

  const audit = scopeOverreach(trajectory, { product: "P", halide: "I", additive: "a6" }, "Yield", "maximize", { searchspace });

  assert.ok(audit, "detector should find the scope overreach with numeric searchspace");
  assert.equal(audit.frozen_factor, "halide");
  assert.equal(audit.frozen_value, "I");
  assert.equal(audit.factor_levels, 4, "factor_levels should match candidate_values count");
  assert.equal(audit.untested_count, 2, "4 - 2 observed halide levels (Br, I) = 2 untested");
});

test("scope overreach remains telemetry for autonomous refinement", () => {
  const trajectory = [
    { decision: { config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
    { decision: { config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
    { decision: { config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 76 } },
  ];
  const context = {
    dataset_summary: { features: { product: { role: "context", candidate_values: 1, values: ["P"] }, halide: { role: "decision", candidate_values: 4, values: ["Br", "I", "Cl", "F"] }, additive: { role: "decision", candidate_values: 7, values: ["a0", "a1", "a2", "a3", "a4", "a5", "a6"] } } },
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [{ pool_index: 1, config: { product: "P", halide: "I", additive: "a6" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { product: "P", halide: "I", additive: "a6" }, decision_goal: "incumbent_improvement", search_mode: "exploit", evidence_sources: ["acquisition"], result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" } });

  assert.ok(decision.policy_audit.telemetry_flags.includes("scope_overreach"));
  assert.ok(!decision.policy_audit.flags.includes("scope_overreach"));
  assert.equal(decision.policy_audit.scope_overreach.untested_count, 2);
  assert.equal(decision.policy_audit.decision, "allow");
});
test("stagnant scope overreach triggers challenge retry in autonomous mode", () => {
  const trajectory = [
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 64 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 63 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 64 } },
    { decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 62 } },
  ];
  const context = {
    dataset_summary: {
      features: {
        product: { role: "context", candidate_values: 1 },
        halide: { role: "decision", candidate_values: 4 },
        additive: { role: "decision", candidate_values: 7 },
      },
    },
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [
      { pool_index: 2, config: { product: "P", halide: "F", additive: "a0" }, acquisition_value: 0.95 },
      { pool_index: 1, config: { product: "P", halide: "I", additive: "a6" }, acquisition_value: 0.8 },
    ],
  };
  const commitment = {
    pool_index: 1,
    config: { product: "P", halide: "I", additive: "a6" },
    decision_goal: "incumbent_improvement",
    search_mode: "exploit",
    evidence_sources: ["acquisition"],
    result_use: "Update the incumbent.",
  };
  const decision = verifyOptimizationPolicy({
    commitment,
    selectedScore: 0.8,
    context,
    trajectory,
    manifest: { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" },
  });

  assert.ok(decision.policy_audit.flags.includes("scope_overreach"));
  assert.equal(decision.policy_audit.decision, "challenge");
  assert.equal(decision.policy_audit.scope_overreach.no_improvement, true);
  assert.match(decision.policy_audit.required_justification.join(" "), /halide=I has been frozen.*without improving the global incumbent/i);
});

test("scope overreach extracts candidate_values_list and candidate_values from dataset_summary features", () => {
  const trajectory = [
    { decision: { config: { product: "P", halide: "Br", additive: "a0" } }, metrics: { Yield: 60 } },
    { decision: { config: { product: "P", halide: "I", additive: "a1" } }, metrics: { Yield: 65 } },
    { decision: { config: { product: "P", halide: "I", additive: "a2" } }, metrics: { Yield: 70 } },
    { decision: { config: { product: "P", halide: "I", additive: "a3" } }, metrics: { Yield: 72 } },
    { decision: { config: { product: "P", halide: "I", additive: "a4" } }, metrics: { Yield: 74 } },
    { decision: { config: { product: "P", halide: "I", additive: "a5" } }, metrics: { Yield: 76 } },
  ];
  const context = {
    dataset_summary: {
      features: {
        product: { role: "context", candidate_values_list: ["P"] },
        halide: { role: "decision", candidate_values_list: ["Br", "I", "Cl", "F"] },
        additive: { role: "decision", candidate_values: 7 },
      },
    },
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [{ pool_index: 1, config: { product: "P", halide: "I", additive: "a6" }, acquisition_value: 0.9 }],
  };
  const commitment = {
    pool_index: 1,
    config: { product: "P", halide: "I", additive: "a6" },
    decision_goal: "incumbent_improvement",
    search_mode: "exploit",
    evidence_sources: ["acquisition"],
    result_use: "Update the incumbent.",
  };
  const decision = verifyOptimizationPolicy({
    commitment,
    selectedScore: 0.9,
    context,
    trajectory,
    manifest: { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" },
  });

  assert.ok(decision.policy_audit.telemetry_flags.includes("scope_overreach"));
  assert.ok(!decision.policy_audit.flags.includes("scope_overreach"));
  assert.equal(decision.policy_audit.scope_overreach.untested_count, 2);
  assert.equal(decision.policy_audit.decision, "allow");
});

test("gpDissentStreak counts consecutive override decisions", () => {
  const trajectory = [
    { step: 1, decision: { config: { x: 1 }, surrogate_relationship: "accept" }, metrics: { Yield: 60 } },
    { step: 2, decision: { config: { x: 2 }, surrogate_relationship: "override" }, metrics: { Yield: 65 } },
    { step: 3, decision: { config: { x: 3 }, surrogate_relationship: "override" }, metrics: { Yield: 70 } },
    { step: 4, decision: { config: { x: 4 }, surrogate_relationship: "accept" }, metrics: { Yield: 72 } },
    { step: 5, decision: { config: { x: 5 }, surrogate_relationship: "override" }, metrics: { Yield: 74 } },
    { step: 6, decision: { config: { x: 6 }, surrogate_relationship: "override" }, metrics: { Yield: 76 } },
  ];
  // The accept at step 4 breaks the earlier overrides; only the trailing run (steps 5-6) counts.
  assert.deepEqual(gpDissentStreak(trajectory, { config: { x: 7 } }), { streak: 2, last_step: 6 });
});

test("policy challenges a scope-overreach refinement", () => {
  const trajectory = overreachTrajectory();
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [{ pool_index: 1, config: { product: "P", halide: "I", additive: "a6" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { product: "P", halide: "I", additive: "a6" }, intent: "optimize", evidence_sources: ["acquisition"], expected_learning: "Refine additive under iodide.", result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40 } });

  assert.ok(decision.policy_audit.flags.includes("scope_overreach"));
  assert.equal(decision.policy_audit.decision, "challenge");
  assert.match(decision.policy_audit.required_justification.join(" "), /halide=.*untested level/i);
});

test("productive low-trust GP override streak remains telemetry", () => {
  const trajectory = [
    { step: 1, decision: { config: { x: 1 }, surrogate_relationship: "override" }, metrics: { Yield: 60 } },
    { step: 2, decision: { config: { x: 2 }, surrogate_relationship: "override" }, metrics: { Yield: 65 } },
    { step: 3, decision: { config: { x: 3 }, surrogate_relationship: "override" }, metrics: { Yield: 70 } },
    { step: 4, decision: { config: { x: 4 }, surrogate_relationship: "override" }, metrics: { Yield: 72 } },
    { step: 5, decision: { config: { x: 5 }, surrogate_relationship: "override" }, metrics: { Yield: 74 } },
    { step: 6, decision: { config: { x: 6 }, surrogate_relationship: "override" }, metrics: { Yield: 76 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.99, cv_r2: -0.2, cv_r2_status: "ok", lengthscales: { x: 1 } },
    suggestions: [{ pool_index: 1, config: { x: 7 }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { x: 7 }, decision_goal: "incumbent_improvement", search_mode: "exploit", surrogate_relationship: "override", evidence_sources: ["receipt"], result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" } });

  assert.equal(decision.policy_audit.gp_dissent.streak, 6);
  assert.ok(decision.policy_audit.telemetry_flags.includes("gp_dissent"));
  assert.ok(!decision.policy_audit.flags.includes("gp_dissent"));
  assert.equal(decision.policy_audit.decision, "allow");
});

test("low-trust acquisition-best refinement is not challenged as stalled", () => {
  const trajectory = Array.from({ length: 4 }, (_, index) => ({ decision: { config: { x: index, catalyst: "A" } }, metrics: { Yield: 10 - index } }));
  const context = {
    diagnostics: { cv_r2: -0.2, cv_r2_status: "ok" },
    suggestions: [{ pool_index: 1, config: { x: 4, catalyst: "A" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { x: 4, catalyst: "A" }, decision_goal: "incumbent_improvement", search_mode: "exploit", surrogate_trust: "low", result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" } });

  assert.ok(!decision.policy_audit.flags.includes("stalled_policy"));
  assert.equal(decision.policy_audit.decision, "allow");
});

test("trusted-surrogate dissent challenge requires declared medium or high trust", () => {
  const trajectory = Array.from({ length: 4 }, (_, index) => ({ decision: { config: { x: index }, surrogate_relationship: "override" }, metrics: { Yield: index } }));
  const context = { diagnostics: { cv_r2: 0.8, cv_r2_status: "ok" }, suggestions: [{ pool_index: 1, config: { x: 5 }, acquisition_value: 0.9 }] };
  const base = { pool_index: 99, config: { x: 99 }, decision_goal: "incumbent_improvement", search_mode: "exploit", surrogate_relationship: "override", result_use: "Update the incumbent." };
  const manifest = { target: "Yield", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" };

  const low = verifyOptimizationPolicy({ commitment: { ...base, surrogate_trust: "low" }, selectedScore: 0.1, context, trajectory, manifest });
  const high = verifyOptimizationPolicy({ commitment: { ...base, surrogate_trust: "high" }, selectedScore: 0.1, context, trajectory, manifest });

  assert.ok(!low.policy_audit.flags.includes("trusted_surrogate_dissent"));
  assert.ok(high.policy_audit.flags.includes("trusted_surrogate_dissent"));
});

test("healthy trajectory is allowed without scope or GP-dissent flags", () => {
  const trajectory = [
    { step: 1, decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { halide: "I", additive: "a0" }, surrogate_relationship: "accept" }, metrics: { Yield: 60 } },
    { step: 2, decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { halide: "Br", additive: "a1" }, surrogate_relationship: "accept" }, metrics: { Yield: 65 } },
    { step: 3, decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { halide: "I", additive: "a2" }, surrogate_relationship: "accept" }, metrics: { Yield: 70 } },
    { step: 4, decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { halide: "Br", additive: "a3" }, surrogate_relationship: "accept" }, metrics: { Yield: 72 } },
    { step: 5, decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { halide: "I", additive: "a4" }, surrogate_relationship: "accept" }, metrics: { Yield: 74 } },
    { step: 6, decision: { intent: "optimize", evidence_sources: ["acquisition"], config: { halide: "Br", additive: "a5" }, surrogate_relationship: "accept" }, metrics: { Yield: 76 } },
  ];
  const context = {
    diagnostics: { train_r2: 0.9, cv_r2: 0.8, cv_r2_status: "ok", lengthscales: { additive: 1 } },
    suggestions: [{ pool_index: 1, config: { halide: "I", additive: "a6" }, acquisition_value: 0.9 }],
  };
  const commitment = { pool_index: 1, config: { halide: "I", additive: "a6" }, intent: "optimize", evidence_sources: ["acquisition"], expected_learning: "Refine additive under iodide.", result_use: "Update the incumbent." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Yield", direction: "maximize", budget: 40 } });

  assert.equal(decision.policy_audit.decision, "allow");
  assert.ok(!decision.policy_audit.flags.includes("scope_overreach"));
  assert.ok(!decision.policy_audit.flags.includes("gp_dissent"));
});


test("middle global exploration is challenged for autonomous competition policy", () => {
  const trajectory = Array.from({ length: 12 }, (_, index) => ({ decision: { config: { x: index } }, metrics: { Score: index } }));
  const context = { diagnostics: {}, suggestions: [{ pool_index: 1, config: { x: 13 }, acquisition_value: 0.9 }] };
  const commitment = { pool_index: 99, config: { x: 99 }, decision_goal: "decision_information", search_mode: "global_exploration", follow_up_if_supported: "Exploit x=99 neighbors.", follow_up_if_refuted: "Return to the incumbent.", result_use: "Choose the next region." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.1, context, trajectory, manifest: { target: "Score", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" } });

  assert.ok(decision.policy_audit.flags.includes("middle_global_exploration"));
  assert.equal(decision.policy_audit.decision, "challenge");
});

test("shortlisted middle global exploration still requires executable follow-ups", () => {
  const trajectory = Array.from({ length: 12 }, (_, index) => ({ decision: { config: { x: index } }, metrics: { Score: index } }));
  const context = { diagnostics: {}, suggestions: [{ pool_index: 1, config: { x: 13 }, acquisition_value: 0.9 }] };
  const commitment = { pool_index: 1, config: { x: 13 }, decision_goal: "decision_information", search_mode: "global_exploration", result_use: "Choose the next region." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Score", direction: "maximize", budget: 40, experiment_policy: "autonomous_agent" } });

  assert.ok(decision.policy_audit.flags.includes("middle_global_exploration"));
  assert.equal(decision.policy_audit.decision, "challenge");
});

test("late information action requires a remaining follow-up slot", () => {
  const trajectory = Array.from({ length: 9 }, (_, index) => ({ decision: { config: { x: index } }, metrics: { Score: index } }));
  const context = { diagnostics: {}, suggestions: [{ pool_index: 1, config: { x: 10 }, acquisition_value: 0.9 }] };
  const commitment = { pool_index: 1, config: { x: 10 }, decision_goal: "decision_information", search_mode: "targeted_exploration", follow_up_if_supported: "Exploit x=10.", follow_up_if_refuted: "Return to x=8.", result_use: "Choose the final action." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.9, context, trajectory, manifest: { target: "Score", direction: "maximize", budget: 10, experiment_policy: "autonomous_agent" } });

  assert.ok(decision.policy_audit.flags.includes("terminal_information_waste"));
  assert.equal(decision.policy_audit.decision, "challenge");
});

test("late outside-shortlist exploration is challenged", () => {
  const trajectory = Array.from({ length: 8 }, (_, index) => ({ decision: { config: { x: index } }, metrics: { Score: index } }));
  const context = { diagnostics: {}, suggestions: [{ pool_index: 1, config: { x: 9 }, acquisition_value: 0.9 }] };
  const commitment = { pool_index: 99, config: { x: 99 }, decision_goal: "decision_information", search_mode: "targeted_exploration", follow_up_if_supported: "Exploit x=99.", follow_up_if_refuted: "Use x=9.", result_use: "Choose the next action." };
  const decision = verifyOptimizationPolicy({ commitment, selectedScore: 0.1, context, trajectory, manifest: { target: "Score", direction: "maximize", budget: 10, experiment_policy: "autonomous_agent" } });

  assert.ok(decision.policy_audit.flags.includes("late_weak_exploration"));
  assert.equal(decision.policy_audit.decision, "challenge");
});

test("acquisition score reuses offered values and scores menu-external candidates", async () => {
  let scored = 0;
  const context = { status: { acqf: "noisy_logei" }, suggestions: [{ pool_index: 7, acquisition_value: 0.9 }] };
  assert.equal(await acquisitionScore({ pool_index: 7 }, context, async () => { scored += 1; }), 0.9);
  assert.equal(await acquisitionScore({ pool_index: 99, config: { ligand: "SPhos" } }, context, async () => {
    scored += 1;
    return [{ noisy_logei: 0.4 }];
  }), 0.4);
  assert.equal(scored, 1);
});

test("unavailable acquisition audit never rejects a valid commitment", async () => {
  const context = { status: { acqf: "noisy_logei" }, diagnostics: {}, suggestions: [] };
  const selectedScore = await acquisitionScore({ pool_index: 99, config: { ligand: "SPhos" } }, context, async () => { throw new Error("diagnostics unavailable"); });
  const decision = verifyOptimizationPolicy({ commitment: { pool_index: 99, config: { ligand: "SPhos" } }, selectedScore, context, trajectory: [], manifest: { target: "Yield", direction: "maximize" } });

  assert.equal(decision.policy_audit.acquisition_score, null);
  assert.equal(decision.policy_audit.would_reject, false);
});

test("trajectory replay keeps unscored external decisions visible", () => {
  const trajectory = [{ step: 1, decision: { pool_index: 99, config: { ligand: "A" } }, metrics: { Yield: 80 } }];
  const contexts = [{ status: { acqf: "noisy_logei" }, diagnostics: {}, suggestions: [{ pool_index: 7, acquisition_value: 0.9 }] }];
  assert.deepEqual(replayOptimizationPolicy(trajectory, contexts, { target: "Yield", direction: "maximize" }), [
    { step: 1, status: "unscored", pool_index: 99 },
  ]);
});

test("stop_campaign returns an explicit terminating campaign action", async () => {
  let action;
  const stop = createCampaignActionTools((value) => { action = value; })
    .find((tool) => tool.name === "stop_campaign");

  const response = await stop.execute("call-stop", {
    condition: "target_reached",
    rationale: "The verified incumbent meets the requested target.",
  });

  assert.equal(response.terminate, true);
  assert.deepEqual(requireCampaignAction(action), {
    type: "stop_campaign",
    condition: "target_reached",
    rationale: "The verified incumbent meets the requested target.",
  });
});

test("campaign result distinguishes early stop from budget exhaustion", () => {
  const stop = { condition: "target_reached", rationale: "Verified target reached." };
  assert.deepEqual(campaignResult("/campaign", 2, stop), {
    ok: true,
    campaign: "/campaign",
    status: "stopped",
    evaluations: 2,
    stop,
  });
  assert.deepEqual(campaignResult("/campaign", 4), {
    ok: true,
    campaign: "/campaign",
    status: "budget_exhausted",
    evaluations: 4,
  });
});

test("failed lenz and malformed oracle responses stop with their real error", () => {
  assert.throws(() => requireOk({ ok: false, error: { message: "receipt rejected" } }, "observe"), /receipt rejected/);
  assert.throws(() => requireReceipt({ ok: true }), /no receipt/i);
});

test("verified trial facts never merge distinct candidates into replicates", () => {
  const facts = verifiedTrialFacts([
    { candidate_id: "a", query_index: 1, config: { ligand: "PPh3", base: "KOH" }, metrics: { Yield: 91 } },
    { candidate_id: "b", query_index: 2, config: { ligand: "PPh3", base: "NaHCO3" }, metrics: { Yield: 93 } },
  ]);

  assert.deepEqual(facts, [
    { candidate_id: "a", pool_index: 1, config: { ligand: "PPh3", base: "KOH" }, metrics: { Yield: 91 }, replicate_count: 1 },
    { candidate_id: "b", pool_index: 2, config: { ligand: "PPh3", base: "NaHCO3" }, metrics: { Yield: 93 }, replicate_count: 1 },
  ]);
});

test("Sara can inspect and reconfigure lenz through typed tools", async () => {
  const calls = [];
  const tools = createLenzTools(async (...args) => {
    calls.push(args);
    return { ok: true, result: { command: args[0] } };
  }, "/campaign/frame/state.json");

  assert.deepEqual(tools.map((tool) => tool.name), [
    "lenz_suggest", "lenz_predict", "lenz_score", "lenz_diagnostics", "lenz_trials", "lenz_set_acqf",
    "lenz_set_bounds", "lenz_set_objectives", "lenz_set_constraints", "lenz_pareto",
  ]);
  const setAcqf = tools.find((tool) => tool.name === "lenz_set_acqf");
  await setAcqf.execute("call-1", { acqf: "ucb", beta: 3, rationale: "Explore uncertainty." });
  assert.deepEqual(calls.at(-1), ["set-acqf", "--state", "/campaign/frame/state.json", "--acqf", "ucb", "--rationale", "Explore uncertainty.", "--beta", "3"]);
  await setAcqf.execute("call-2", { acqf: "logei", rationale: "Return to improvement." });
  assert.deepEqual(calls.at(-1), ["set-acqf", "--state", "/campaign/frame/state.json", "--acqf", "logei", "--rationale", "Return to improvement."]);
});

test("terminal status is authoritative only when fully bound to the current Frame", () => {
  const frame = { state_revision: 8, trials: [{ status: "observed" }] };
  const status = { status: "stopped", campaign_id: "campaign-a", state_revision: 8, observed: 1, budget: 4, budget_remaining: 3, condition: "target_reached", rationale: "verified", verified: true };
  assert.equal(validateCampaignStatus(status, { campaign_id: "campaign-a", budget: 4 }, frame), status);
  assert.throws(() => validateCampaignStatus({ ...status, observed: 0 }, { campaign_id: "campaign-a", budget: 4 }, frame), /observed count mismatch/);
  assert.throws(() => validateCampaignStatus({ ...status, verified: false }, { campaign_id: "campaign-a", budget: 4 }, frame), /verified stop/);
});

test("historical observations do not spend campaign stop budget", () => {
  const frame = {
    state_revision: 8,
    trials: [
      { trial_id: "historical-0", source: "historical", status: "observed" },
      { trial_id: "trial-a", source: "campaign", status: "observed" },
    ],
  };
  const status = { status: "stopped", campaign_id: "campaign-a", state_revision: 8, observed: 1, budget: 4, budget_remaining: 3, condition: "target_reached", rationale: "verified", verified: true };

  assert.equal(validateCampaignStatus(status, { campaign_id: "campaign-a", budget: 4 }, frame), status);
});

test("trajectory recovery excludes historical observations", () => {
  const frame = {
    trials: [
      { trial_id: "historical-0", source: "historical", query_index: null, candidate_id: "history", config: { x: 0 }, status: "observed", metrics: { Yield: 80 } },
      { trial_id: "trial-a", source: "campaign", query_index: 1, candidate_id: "candidate-a", config: { x: 1 }, status: "observed", metrics: { Yield: 90 } },
    ],
  };

  const trajectory = reconcileTrajectory(frame, []);

  assert.equal(trajectory.length, 1);
  assert.equal(trajectory[0].trial_id, "trial-a");
});

test("Supervisor rejects unsupported stop predicates", () => {
  const context = { status: { remaining: 2, pending: [] }, verified_trials: [] };
  assert.throws(() => verifyStop({ condition: "target_reached" }, { target: "Yield", direction: "maximize" }, context), /quantitative target/);
  assert.throws(() => verifyStop({ condition: "observed_candidates_exhausted" }, {}, context), /zero remaining/);
});

test("Supervisor accepts evidence-backed stop predicates", () => {
  const context = {
    status: { remaining: 0, pending: [] },
    verified_trials: [{ metrics: { Yield: 95 } }],
  };
  assert.doesNotThrow(() => verifyStop({ condition: "target_reached" }, { target: "Yield", direction: "maximize", target_value: 90 }, context));
  assert.doesNotThrow(() => verifyStop({ condition: "observed_candidates_exhausted" }, {}, context));
});

test("historical observations cannot satisfy campaign target stops", () => {
  const context = {
    status: { remaining: 1, pending: [] },
    verified_trials: [
      { source: "historical", metrics: { Yield: 99 } },
      { source: "campaign", metrics: { Yield: 80 } },
    ],
  };

  assert.throws(
    () => verifyStop({ condition: "target_reached" }, { target: "Yield", target_value: 90, direction: "maximize" }, context),
    /not supported by verified observations/,
  );
});

test("Frame reconciliation preserves rationale and recovers missing journal fields", () => {
  const trials = [
    { trial_id: "trial-a", request_id: "request-a", candidate_id: "candidate-a", query_index: 7, config: { x: 1 }, status: "observed", receipt_id: "receipt-a", metrics: { Yield: 80 } },
    { trial_id: "trial-b", request_id: "request-b", candidate_id: "candidate-b", query_index: 8, config: { x: 2 }, status: "pending" },
  ];
  const trajectory = reconcileTrajectory({ trials }, [{ trial_id: "trial-a", decision: { rationale: "kept" } }], (trial) => trial.receipt_id ? `/receipts/${trial.trial_id}.json` : undefined);
  assert.equal(trajectory[0].decision.rationale, "kept");
  assert.equal(trajectory[0].receipt, "/receipts/trial-a.json");
  assert.deepEqual(trajectory[1], {
    rationale: null,
    provenance: "recovered",
    request_id: "request-b",
    trial_id: "trial-b",
    decision: { pool_index: 8, config: { x: 2 }, candidate_id: "candidate-b", rationale: null },
    receipt: undefined,
  });
});

test("transient provider failures retry independently of campaign actions", async () => {
  let prompts = 0;
  let pauses = 0;
  let messages = [];
  await promptWithTransientRetries({
    prompt: async () => {
      prompts += 1;
      messages = prompts < 3
        ? [{ role: "assistant", stopReason: "error", errorMessage: "429 concurrency cooldown" }]
        : [{ role: "assistant", stopReason: "stop" }];
    },
    messages: () => messages,
    onPause: async () => { pauses += 1; },
    onError: async () => {},
    sleep: async () => {},
  });
  assert.equal(prompts, 3);
  assert.equal(pauses, 2);
});

test("interrupted upstream streams are retried", async () => {
  let prompts = 0;
  let messages = [];
  await promptWithTransientRetries({
    prompt: async () => {
      prompts += 1;
      messages = prompts === 1
        ? [{ role: "assistant", stopReason: "error", errorMessage: "Upstream response stream was interrupted" }]
        : [{ role: "assistant", stopReason: "stop" }];
    },
    messages: () => messages,
    onPause: async () => {},
    onError: async () => {},
    sleep: async () => {},
  });
  assert.equal(prompts, 2);
});

test("HTTP/2 stream failures are retried", async () => {
  let prompts = 0;
  let messages = [];
  await promptWithTransientRetries({
    prompt: async () => {
      prompts += 1;
      messages = prompts === 1
        ? [{ role: "assistant", stopReason: "error", errorMessage: "Upstream HTTP/2 stream failed" }]
        : [{ role: "assistant", stopReason: "stop" }];
    },
    messages: () => messages,
    onPause: async () => {},
    onError: async () => {},
    sleep: async () => {},
  });
  assert.equal(prompts, 2);
});

test("provider retries stop after a mutating tool succeeds", async () => {
  let prompts = 0;
  await assert.rejects(() => promptWithTransientRetries({
    prompt: async () => { prompts += 1; },
    messages: () => [{ role: "assistant", stopReason: "error", errorMessage: "Stream ended without finish_reason" }],
    onPause: async () => {},
    onError: async () => {},
    canRetry: () => false,
    sleep: async () => {},
  }), /finish_reason/);
  assert.equal(prompts, 1);
});

test("non-transient provider failures preserve the real error", async () => {
  let errorState;
  await assert.rejects(() => promptWithTransientRetries({
    prompt: async () => {},
    messages: () => [{ role: "assistant", stopReason: "error", errorMessage: "invalid API key" }],
    onPause: async () => {},
    onError: async (error) => { errorState = error; },
    sleep: async () => {},
  }), /invalid API key/);
  assert.equal(errorState, "invalid API key");
});

test("unsupported concurrent operations are not retried", async () => {
  let prompts = 0;
  await assert.rejects(() => promptWithTransientRetries({
    prompt: async () => { prompts += 1; },
    messages: () => [{ role: "assistant", stopReason: "error", errorMessage: "Concurrent tool calls are not supported" }],
    onPause: async () => {},
    onError: async () => {},
    sleep: async () => {},
  }), /not supported/);
  assert.equal(prompts, 1);
});
