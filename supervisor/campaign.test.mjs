import test from "node:test";
import assert from "node:assert/strict";

import { acquisitionScore, campaignResult, createCampaignActionTools, createLenzTools, enforcePreferredSuggestion, lowTrustAcquisition, nearBestCandidates, optimizationPolicy, preferredSuggestion, promptWithTransientRetries, reconcileTrajectory, replayOptimizationPolicy, requireCampaignAction, requireOk, requirePolicyAllowance, requireReceipt, validateCampaignStatus, verifyCommitment, verifiedTrialFacts, verifyOptimizationPolicy, verifyStop } from "./campaign.mjs";

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

test("low-trust diagnostics select exploratory UCB", () => {
  assert.deepEqual(lowTrustAcquisition({ cv_r2: -0.1, cv_r2_status: "ok" }), { acqf: "ucb", beta: 16 });
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
