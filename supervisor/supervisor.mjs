import { createHash, randomUUID } from "node:crypto";
import { spawn } from "node:child_process";
import { mkdir, readFile, rename, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { createAgentSession, DefaultResourceLoader, getAgentDir, ModelRuntime, SessionManager } from "@earendil-works/pi-coding-agent";
import { acquisitionScore, campaignResult, createCampaignActionTools, createLenzTools, enforcePreferredSuggestion, lowTrustAcquisition, nearBestCandidates, preferredSuggestion, promptWithTransientRetries, reconcileTrajectory, requireCampaignAction, requireOk, requirePolicyAllowance, requireReceipt, validateCampaignStatus, verifiedTrialFacts, verifyCommitment, verifyOptimizationPolicy, verifyStop } from "./campaign.mjs";
const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, "..");
const argv = process.argv.slice(2);
const args = Object.fromEntries(argv.flatMap((item, index) => item.startsWith("--") ? [[item.slice(2), argv[index + 1]]] : []));
const campaign = resolve(args.campaign ?? "runs/campaign");
const manifest = JSON.parse(await readFile(resolve(campaign, "manifest.json"), "utf8"));
const state = resolve(campaign, "frame", "state.json");
const frameAtStartup = JSON.parse(await readFile(state, "utf8"));
const statusPath = resolve(campaign, "campaign-status.json");
const priorStatus = await readFile(statusPath).then((text) => JSON.parse(text), () => undefined);
const terminalStatus = validateCampaignStatus(priorStatus, manifest, frameAtStartup);
if (terminalStatus) {
  console.log(JSON.stringify({ ok: true, campaign, ...terminalStatus }));
  process.exit(0);
}
const receipts = resolve(campaign, "receipts");
await mkdir(receipts, { recursive: true });

const run = (command, commandArgs) => new Promise((accept, reject) => {
  const child = spawn(command, commandArgs, { cwd: campaign, env: process.env, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  let stderr = "";
  child.stdout.on("data", (chunk) => { stdout += chunk; });
  child.stderr.on("data", (chunk) => { stderr += chunk; });
  child.on("close", (code) => code === 0 ? accept(stdout.trim()) : reject(new Error(`${command} failed (${code}): ${stderr || stdout}`)));
});
const lenz = async (...commandArgs) => JSON.parse(await run("lenz", commandArgs));
const writeJsonAtomic = async (path, value) => {
  const temporary = `${path}.${process.pid}.tmp`;
  await writeFile(temporary, JSON.stringify(value, null, 2));
  await rename(temporary, path);
};

const sessionFile = resolve(campaign, "pi-session.jsonl");
const priorSession = await readFile(sessionFile, "utf8").catch(() => "");
const priorModel = priorSession.match(/"type":"model_change"[^\n]*"provider":"([^"]+)"[^\n]*"modelId":"([^"]+)"/)?.slice(1);
const sessionManager = priorSession ? SessionManager.open(sessionFile) : (() => {
  const manager = SessionManager.create(campaign, campaign);
  manager.setSessionFile(sessionFile);
  return manager;
})();
const modelRuntime = await ModelRuntime.create({ modelsPath: resolve(root, ".pi/models.json") });
const provider = "ai-modeling";
const modelId = args.model ?? process.env.BOAGENT_MODEL ?? "gpt-5.6-sol";
const thinking = args.thinking ?? "xhigh";
const model = modelRuntime.getModel(provider, modelId);
if (!model) throw new Error(`model not found: ${provider}/${modelId}`);
const system = await readFile(resolve(root, "profiles/paper-reproduction/PAPER_SYSTEM.md"), "utf8");
const reference = await readFile(resolve(root, "profiles/paper-reproduction/PAPER_LENZ_REF.md"), "utf8");
const hash = (value) => createHash("sha256").update(value).digest("hex");
const auditPath = resolve(campaign, "campaign-run-config.json");
const audit = await readFile(auditPath).then((text) => JSON.parse(text), () => ({ revisions: [] }));
const runConfig = { campaign_id: manifest.campaign_id, provider, model: modelId, thinking, system_prompt_hash: hash(system), reference_hash: hash(reference) };
const previous = audit.revisions.at(-1);
if (!previous || Object.entries(runConfig).some(([key, value]) => previous[key] !== value)) {
  audit.revisions.push({ revision: audit.revisions.length + 1, at: new Date().toISOString(), ...runConfig, event: priorModel && (priorModel[0] !== provider || priorModel[1] !== modelId) ? "model_switched" : "run_configured", ...(priorModel ? { previous_provider: priorModel[0], previous_model: priorModel[1] } : {}) });
  await writeJsonAtomic(auditPath, audit);
}
let campaignAction;
let turnMutated = false;
const actionTools = createCampaignActionTools((action) => { campaignAction = action; });
const lenzTools = createLenzTools(lenz, state, () => { turnMutated = true; });
const loader = new DefaultResourceLoader({
  cwd: campaign,
  agentDir: getAgentDir(),
  systemPromptOverride: () => `${system}\n\n---\n\n${reference}`,
  noExtensions: true,
  noSkills: true,
  noPromptTemplates: true,
  noThemes: true,
  noContextFiles: true,
});
await loader.reload();
const { session } = await createAgentSession({
  cwd: campaign,
  model,
  modelRuntime,
  resourceLoader: loader,
  noTools: "builtin",
  customTools: [...lenzTools, ...actionTools],
  sessionManager,
  thinkingLevel: thinking,
});

const events = [];
session.subscribe((event) => {
  if (["tool_execution_start", "tool_execution_end", "turn_start", "turn_end", "agent_end"].includes(event.type)) {
    events.push({ at: new Date().toISOString(), ...event });
  }
});
const toolContext = async () => {
  const status = await lenz("status", "--state", state);
  const suggestions = await lenz("suggest", "--state", state, "--q", "20");
  const diagnostics = await lenz("diagnostics", "--state", state);
  const trials = await lenz("trials", "--state", state);
  const offered = requireOk(suggestions, "suggest");
  return {
    state_revision: status.state_revision,
    status: requireOk(status, "status"),
    suggestions: offered,
    near_best_suggestions: nearBestCandidates(offered),
    preferred_suggestion: preferredSuggestion(offered),
    diagnostics: requireOk(diagnostics, "diagnostics"),
    verified_trials: verifiedTrialFacts(requireOk(trials, "trials")),
  };
};

const trajectoryPath = resolve(campaign, "trajectory.json");
let trajectory = await readFile(trajectoryPath).then((text) => JSON.parse(text), () => []);
trajectory = reconcileTrajectory(frameAtStartup, trajectory, (trial) => trial.receipt_id ? resolve(receipts, `${trial.trial_id}.json`) : undefined);
await writeJsonAtomic(trajectoryPath, trajectory);
const persistStep = async (entry) => {
  const index = trajectory.findIndex((item) => (entry.trial_id && item.trial_id === entry.trial_id) || (entry.request_id && item.request_id === entry.request_id));
  if (index >= 0) trajectory[index] = { ...trajectory[index], ...entry };
  else trajectory.push(entry);
  await writeJsonAtomic(trajectoryPath, trajectory);
};
const submitDecision = async (entry) => {
  const submit = await lenz("submit", "--state", state, "--pool-index", String(entry.decision.pool_index), "--config", JSON.stringify(entry.decision.config), "--request-id", entry.request_id);
  const submitted = requireOk(submit, "submit");
  if (submitted.query_index !== Number(entry.decision.pool_index)) throw new Error("commitment pool_index/config mismatch");
  await persistStep({ ...entry, trial_id: submitted.trial_id });
  return submitted.trial_id;
};
for (const intent of trajectory.filter((entry) => entry.decision && entry.request_id && !entry.trial_id)) {
  await submitDecision(intent);
}
let context = await toolContext();
if (context.status.observed === 0) {
  const desired = lowTrustAcquisition(context.diagnostics);
  if (context.status.acqf !== desired.acqf || Number(context.status.beta) !== desired.beta) {
    requireOk(await lenz("set-acqf", "--state", state, "--acqf", desired.acqf, "--beta", String(desired.beta), "--rationale", "Supervisor diagnostic policy"), "set-acqf");
    context = await toolContext();
  }
}
const recovered = [];
if (context.status.pending.length) {
  for (const trialId of context.status.pending) {
    const current = JSON.parse(await readFile(state, "utf8"));
    const trial = current.trials.find((item) => item.trial_id === trialId);
    if (!trial) throw new Error(`pending trial missing from Frame: ${trialId}`);
    const oracle = JSON.parse(await run("boagent-oracle", ["--dataset-root", current.public_root, "--state", state, "--trial-id", trialId, "--request-id", trial.request_id, "--receipts", receipts]));
    const receipt = requireReceipt(oracle);
    const observation = requireOk(await lenz("observe", "--state", state, "--trial-id", trialId, "--receipt", receipt), "observe");
    await persistStep({ trial_id: trialId, request_id: trial.request_id, receipt, metrics: observation.metrics });
    recovered.push({ trial_id: trialId, metrics: observation.metrics });
  }
  context = await toolContext();
}
let prompt = [
  `Campaign ID: ${manifest.campaign_id}`,
  `The Frame already exists. Verified lenz evidence is supplied by the Supervisor.`,
  `The complete public task description is included below; do not try to read hidden outcomes.\n${await readFile(resolve(campaign, "TASK.md"), "utf8")}`,
  `Current verified campaign evidence: ${JSON.stringify(context)}`,
  recovered.length ? `Recovered verified observations: ${JSON.stringify(recovered)}.` : "",
  `Choose exactly one unobserved public candidate and finish by calling commit_candidate, or call stop_campaign with one verified paper-defined stopping condition. Candidate identity is the complete config plus pool_index. Only identical candidate_id values are replicates.`,
].join("\n");
const completedThisRun = [];
const maxActionAttempts = 3;
const maxProviderAttempts = 3;
const sleep = (milliseconds) => new Promise((accept) => setTimeout(accept, milliseconds));
let stopped;
for (let step = context.status.observed; step < manifest.budget; step += 1) {
  let decision;
  for (let attempt = 1; attempt <= maxActionAttempts; attempt += 1) {
    campaignAction = undefined;
    turnMutated = false;
    await promptWithTransientRetries({
      prompt: () => session.prompt(prompt),
      messages: () => session.messages,
      maxAttempts: maxProviderAttempts,
      sleep,
      canRetry: () => !turnMutated,
      onPause: (error, providerAttempt) => writeJsonAtomic(statusPath, { status: "paused", campaign_id: manifest.campaign_id, state_revision: context.state_revision, observed: context.status.observed, error, provider_attempt: providerAttempt }),
      onError: (error) => writeJsonAtomic(statusPath, { status: "error", campaign_id: manifest.campaign_id, state_revision: context.state_revision, observed: context.status.observed, error }),
    });
    try {
      const action = requireCampaignAction(campaignAction);
      if (action.type === "stop_campaign") {
        context = await toolContext();
        verifyStop(action, manifest, context);
        stopped = {
          status: "stopped",
          campaign_id: manifest.campaign_id,
          state_revision: context.state_revision,
          condition: action.condition,
          verified: true,
          rationale: action.rationale,
          observed: context.status.observed,
          budget: manifest.budget,
          budget_remaining: manifest.budget - context.status.observed,
        };
        await writeJsonAtomic(statusPath, stopped);
        break;
      }
      const commitment = verifyCommitment(action, context.suggestions, context.verified_trials);
      enforcePreferredSuggestion(commitment, context.preferred_suggestion, manifest.budget - context.status.observed);
      const selectedScore = await acquisitionScore(commitment, context, async (config) => requireOk(await lenz("score", "--state", state, "--configs", JSON.stringify([config])), "score"));
      decision = requirePolicyAllowance(verifyOptimizationPolicy({ commitment, selectedScore, context, trajectory, manifest }));
      break;
    } catch (error) {
      if (attempt === maxActionAttempts) throw error;
      prompt = [
        `Your previous campaign action was rejected: ${error.message}`,
        `Choose an unobserved candidate and call commit_candidate, or call stop_campaign with one verified paper-defined stopping condition.`,
        `Current verified campaign evidence: ${JSON.stringify(context)}.`,
      ].join("\n");
    }
  }
  if (stopped) break;
  const requestId = `${manifest.campaign_id}:${step}:${randomUUID()}`;
  const intent = { step: step + 1, request_id: requestId, decision, provenance: "journaled" };
  await persistStep(intent);
  const trialId = await submitDecision(intent);
  const current = JSON.parse(await readFile(state, "utf8"));
  const oracle = JSON.parse(await run("boagent-oracle", ["--dataset-root", current.public_root, "--state", state, "--trial-id", trialId, "--request-id", requestId, "--receipts", receipts]));
  const receipt = requireReceipt(oracle);
  const observation = requireOk(await lenz("observe", "--state", state, "--trial-id", trialId, "--receipt", receipt), "observe");
  await persistStep({ step: step + 1, request_id: requestId, decision, trial_id: trialId, receipt, metrics: observation.metrics });
  completedThisRun.push(trialId);
  if (step + 1 === manifest.budget) break;
  context = await toolContext();
  prompt = [
    `Verified observation for Trial ${trialId}: ${JSON.stringify(observation.metrics)}.`,
    `Budget remaining: ${manifest.budget - step - 1}.`,
    `Current verified campaign evidence: ${JSON.stringify(context)}.`,
    manifest.budget - step - 1 === 1
      ? `Terminal decision: compare every near_best_suggestions candidate before committing. With no later action, maximize the expected final best observed value; do not spend the last evaluation mainly on information or a matched comparison.`
      : `Interpret the result using exact candidate identities.`,
    `Finish by calling commit_candidate or stop_campaign exactly once.`,
  ].join("\n");
}
await writeJsonAtomic(trajectoryPath, trajectory);
const eventsPath = resolve(campaign, "supervisor-events.json");
const priorEvents = await readFile(eventsPath).then((text) => JSON.parse(text), () => []);
await writeJsonAtomic(eventsPath, [...priorEvents, ...events]);
console.log(JSON.stringify(campaignResult(campaign, completedThisRun.length, stopped)));
