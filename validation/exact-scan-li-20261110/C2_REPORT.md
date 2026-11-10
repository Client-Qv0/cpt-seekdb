# C2 four-record AVX2 exact distance — review requested

Functional commit3490b490cfeb2b0ece00bb637f231e1b2f05ca80. BaseC1 commit07b3a75ec2b0434105ccfa51a03a90d07c077ee3. C2_REVIEW.diff covers full task. Requirements: IMPLEMENTATION_BRIEF.md, specifically C2 batch/kernel/semantics and existing cache budget constraints.

C2 keeps the C1 AoSoA view and gathers four records AFTER all scalar predicates. Consecutive aligned tiles use contiguous128bit FP32 loads, otherwise AVX2gather. Four independent double lanes iterate dimensions in original order, separate multiply/add, then actualsqrt; scalar tails. Runtime CPU dispatch and original nonAVX2 engine path remain. Kernel explicit target avx2,no-fma. Internal scalar reference remains callable. No new publicflags/types.

TDD c2-red.log: compilation fails for absent distances4 entry before kernel changes. c2-green.log thenPASS after minimal kernel. Tests compare every bit scalar/batch for contiguous and noncontiguous indices, dimensions1/3/5/31/128/129, 100iterations cycling10distinct querypatterns per dimension, finite FP32extremes/subnormals/negativezero/near ties. Existing tile/budget tests remain. c2-kernel-instructions.txt confirms vmulpd,vaddpd,vgatherdps,vsqrtpd and noFMA.

Fresh c2-ctest.log7/7PASS (existing6+new1); c2-acceptance-full.log21/21PASS --stress; c2-optimization-full.log15/15PASS --large; c2-distance whole-response differential858SQL and independentFP32oraclePASS; c2-stdio eight native protocol cases on baseline/candidatePASS. No timed comparisons or officialscores claimed. Native binarysha256 b2501504b9e0b13afe6dc35c4e24bf65efaf4351e98ae3d94fc6327f1bd9ee67.

Review spec compliance and code quality including SIMD gather bounds/order, filtering before batch, tails and dispatch; finalbranch review still required after all evidence.
