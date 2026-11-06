# Experiment Audit Report

Date: 2026-10-30
Auditor: fresh inherited Codex reviewer, read-only. The exact runtime model identifier is not exposed to this reviewer; this is **not a GPT-5.6 review or cross-family acceptance**.
`review_independence: same-family`
`acceptance_status: provisional`

**Overall verdict: WARN**
**Integrity status: warn**

The saved results support a bounded, retrospective engineering demonstration. I found no fabricated ground truth, prediction-based performance normalization, nonexistent reported results, or substitution of replay for a new LLM discovery. The remaining warnings concern the strength of provenance and scientific generalization.

## A. Ground truth provenance — PASS

Market data are read directly from seven archive members, with matching axes and member fingerprints: `lesson-04/data.py:23–44`. Factor labels are future **dataset prices**, specifically next-open entry and horizon-adjusted exit, with maturity restricted to the evaluation endpoint: `lesson-05/factor.py:83–96,183–200`. They are not derived from candidate outputs.

The harness truncates each evaluation context at its endpoint and uses the reused evaluator: `lesson-06/harness.py:155–161,179–193`. Historical expressions enforce positive windows and exclude arbitrary Python: `lesson-04/formula.py:18–62`.

Qualification: these are empirical return labels under a stated adjusted-price interpretation, not an authoritative benchmark supplied with official ground truth. Adjustment interpretation and amount units remain vendor-unconfirmed: `lesson-04/results/data_audit.json:89–95`.

## B. Score normalization — PASS

The development objective is explicitly a composite decision score:

`min(annual_excess) − 0.25 × max(abs(drawdown)) − 0.0001 × AST_nodes`

See `lesson-06/harness.py:112–114`.

Annual excess is the mean of paired strategy-minus-benchmark daily returns, multiplied by 252; cumulative excess is separately reported in percentage points: `lesson-06/harness.py:211–221`. Portfolio metrics use initial capital rather than candidate maximum output: `lesson-04/engine.py:6–21`.

Rank features and correlation denominators are standard feature/statistical transformations, not normalization of achieved performance to manufacture near-perfect scores: `lesson-04/formula.py:118–119`; `lesson-05/factor.py:58–67`.

Raw scores and the distinction between objective, arithmetic excess, and realized cumulative return are preserved: `reports/lesson-06/README.md:29,41–62,89`.

## C. Result existence and provenance — WARN

**Numerical existence and consistency: PASS.** I independently checked:

- All 18 original history entries and 36 development metric files agree.
- All three original context/proposal/feedback digests agree; prior histories and parent references agree.
- The preserved original harness source matches its original manifest.
- Final replay history is **exactly equal** to original interactive history.
- All final source fingerprints, freeze-history digest, and selection-freeze digest agree.
- All 18 followup rows reproduce total return, drawdown, paired annual excess, and seeded bootstrap intervals from saved daily curves. Maximum selected-metric discrepancy: approximately `4.11e-15`.
- The final verifier contains 212 checks, all true: `lesson-06/results/verification.json:2–220`.

Original session evidence is retained under `lesson-06/provenance/interactive-session/`. Original proposal descriptions identify the current Codex session rather than a separate API: `round-00/proposal.json:2`, `round-01/proposal.json:2`, `round-02/proposal.json:2`. The final replay explicitly prefixes provenance with `replay of`: `lesson-06/harness.py:399–404`.

**Warning:** self-described agent names, local timestamps, and consistent hashes are not authenticated model-call receipts. They cannot independently establish the actual authoring model or information isolation. The report correctly discloses this and distinguishes the original interaction, numeric replay, and synthetic external-adapter test: `reports/lesson-06/README.md:11–15`.

## D. Dead code and generic interface — PASS, within tested scope

The measured path calls factor analysis, execution simulation, metrics, and paired bootstrap: `lesson-06/harness.py:179–235,310–349`. Their outputs appear in result artifacts; I found no phantom metric path.

The defects identified during review are repaired:

- Exact integer generation and string parent validation: `lesson-06/harness.py:73–103`.
- Reserved `equal_weight` and `baseline_` identifiers rejected: `lesson-06/harness.py:89–91`.
- Fixed controls no longer require the agent to choose hardcoded founder IDs: `lesson-06/harness.py:242–250,331–340`.
- Empty order and holding exports retain schemas: `lesson-06/harness.py:200–205`.
- A complete synthetic auto loop uses arbitrary identifiers and explicitly labels its adapter as a test stub, not an LLM: `lesson-06/tests/test_harness.py:189–218`.

External command execution uses an argv array without a shell and a bounded timeout: `lesson-06/harness.py:352–356,385–398`. This establishes implemented adapter support and synthetic integration coverage; **it does not establish a real external-model experiment**.

## E. Scope and financial claims — WARN

Actual scope is one adaptive retrospective search: three generations, six proposals each, two development folds, one selection quarter, and one 125-day followup window. Three execution scenarios are sensitivity checks, not independent research replications: `lesson-06/protocol.json:3–18`; `reports/lesson-06/README.md:19–29,93–112`.

There are no same-budget random/grid-search controls or repeated LLM discovery runs. Previously viewed history is explicitly disclosed. Therefore the experiment does not support LLM-search superiority, independent holdout performance, causal attribution to an individual mutation, or deployable alpha.

The report accurately preserves the negative outcome: selected followup return **−3.81%**, benchmark **−2.71%**, difference **−1.10 percentage points**; nominal annual arithmetic excess interval **[−30.29%, 27.32%]** contains zero: `reports/lesson-06/README.md:76–89`.

Residual positions and valuation-based terminal returns are disclosed: `reports/lesson-06/README.md:104–106`. The reused engine employs fractional adjusted units, daily-bar execution proxies, simplified costs, and incomplete corporate-action coverage: `lesson-04/assignment/protocol.json:22–25`; `lesson-04/course.py:29–120`.

## F. Evaluation type — PASS

The appropriate classification is mixed:

- **`real_gt` empirical-label diagnostics:** IC and quantile returns against dataset-derived future prices.
- **`simulation_only` execution evaluation:** simulated accounts, cash, fills, holdings, fees, and scenario returns using historical market observations.
- **Synthetic interface tests:** engineering validation only; exclude from financial or LLM-discovery evidence.

It is neither live trading nor human evaluation. No model-generated reference is used.

## State sealing and parent integrity

Current checks bind proposals to recorded candidates, validate earlier-generation parents, recompute development gates, verify frozen shortlist/champions, and check selection rules: `lesson-06/verify.py:15–57`. Followup cash, inventory, snapshots, chronology, fees, returns, and sampled labels are checked: `lesson-06/verify.py:61–118`.

The CSV inventory tolerance is tied to gross per-symbol quantity, with separate cash/equity checks: `lesson-06/verify.py:78–87`. Final maximum errors are **0.0068742 CNY cash**, **0.0078478 CNY equity**, and **4.773e-11 sampled Rank IC**: `lesson-06/results/verification.json:217–221`.

These are local consistency seals, not tamper-proof authentication or filesystem isolation. That limitation is accurately stated in `lesson-06/README.md:49`.

## Concrete actions and claim impact

Required claim boundaries are already present. Preserve them when delivering or summarizing:

- **Supported:** this run completed feedback-driven proposal changes, lineage, bounded evaluation, freezing, selection, and reproducible bookkeeping.
- **Supported with qualification:** development objective improved within this single retrospective search.
- **Unsupported:** independent discovery replication, authenticated external LLM API execution, search-method superiority, sustained alpha, or deployment readiness.
- **Optional wording correction:** replace “真实现金/份额账本” at `reports/lesson-06/README.md:9` and `lesson-06/report.py:139` with “显式现金/复权份额模拟账本” to describe the simulated accounts precisely.

No additional experiment is needed to support the report’s current engineering conclusion. Stronger scientific or financial claims require new evidence.

---

Executor note, 2026-10-30: the optional wording correction has been applied. Review text above is preserved as delivered. Trace and machine-readable verdict: [review trace](../../lesson-06/.aris/traces/experiment-audit/2026-10-30_run01/), [audit JSON](EXPERIMENT_AUDIT.json). The early verifier failure came from a Series-index alignment bug in the verifier, then an overly strict tolerance on CSV-rounded units; the final verifier reconstructs ledgers within the errors stated above. No strategy result was changed to address these verification issues.
