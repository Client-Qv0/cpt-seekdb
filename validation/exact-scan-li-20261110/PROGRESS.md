# Durable execution ledger

- 2026-11-10: Read IMPLEMENTATION_BRIEF.md. Isolated branch perf/exact-scan-li-20261110 starts ef2cece289850201576c6dc7da1db58ef5a99bad; production baseline 9cea05e182875ae16f3f3c9c8e9cc688a65d653c.
- A/A batch 1 is running, PID 1627467, immutable baseline image under a1/a2 labels. Waiting for six complete pairs; no production modifications authorized before gate pass.
- Gate: median absolute paired query change <=3%, maximum <=10%; exactly one complete retry on failure. Do not discard rounds.
- TDD and independent spec/quality review required if implementation proceeds. No concurrent performance jobs, no changes to /opt/minivectordb-v2, shared branch, official assessment, or history rewriting.
- Recovery: inspect aa-*/adapter-manifest.json, result.json files, AA_GATE.json, and this ledger before restarting work.

- A/A batch 1 COMPLETE/PASS: six pairs, adapter exit 0, median abs query change 1.7864095989806983%, max 4.835422941605327%; AA_GATE_1.json preserves every round and resources. No retry needed. Proceed baseline diagnostic profiling -> C1 TDD -> C2 TDD -> validation/comparisons.

- C1 functional commit07b3a75ec2b0434105ccfa51a03a90d07c077ee3. Red/green scalar cache tests; native CTest7/7; distance858statement differentialPASS; stdio8cases eachPASS. C1_REPORT.md/C1_REVIEW.diff ready for independent review; parent arranging reviews because child tools omit collaboration. C1 Docker built. Full --stress and --large suites completed exit0, inspect c1-acceptance-full.log/c1-optimization-full.log for counts. No candidate measurements yet; waiting review before C2.

- Reporting correction from coordinator: preliminary optimization Ran12 plus setUpClass skip =12actual passing tests plus skippedclass, not11pass+1skip. Full flagged15/15 remains definitive. C1 reviewer dispatched by parent; await verdict. Baseline genuine agent material strict unittest audit executed separately; no invented user statements added.

- C1 independent review CLEAN per parent: SpecPASS (C1 scope), QualityPASS/no actionable defects at07b3a75. Parent verified full cache/fallback/typed predicates/invalidations/budget inspection. Functional approval only, performance acceptance pending. Proceed C2 TDD.

- 2026-11-11 finalization resumed by parent after child quota/interruption and NAT instability. Existing post-comparisons.exit and million-vector.exit read0; no measured probes restarted. MILLION_GATE.json independently verifies scalar anon40,132,608->40,128,512B and vector anon41,291,776->40,566,784B, all phasespass/zeroOOM. Added resource-final once: four frozen actual128MiB cases4/4,0skip/0OOM, explicitdev adapter separately fromdefaultJSONL20/recovery. FINAL_GATES.json all20checksPASS. Source remains3490b490; material genuinely extended to122791bytes andstrict5checksPASS. Final review agentreview_final_exact running; no publish before cleanverdict. Next: evidence binding/manifest, explicit staging, normalpersonalcommit/push andremoteSHAverification. Old/optworkspace untouched.

- 2026-11-11: Final independent broad SpecPASS/QualityPASS, no production defect. FINAL_REVIEW.md records49 recomputed metric statistics, rawmillion/resource/source/material checks; stale report sentence corrected. C1+C2 selected after all20gates. All implementation and validation tasks complete. Publication commit/remote SHA are delivery operations verified by coordinator; do not redo completed tasks. Preserved all three user options and15%/current-server choice; formalassessment notexecuted.
