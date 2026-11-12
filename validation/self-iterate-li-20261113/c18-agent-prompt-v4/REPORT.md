# Agent Prompt v4

## Result

This is the intended fifth and final successful commit of the bounded self-iteration loop.

The material now includes real instructions and results from the current server-bound iteration:

- negative results remain local and do not count;
- every candidate uses an independent validation directory;
- only retained production optimizations count;
- the loop stops after five successful commits;
- all work and verification occurs through MCP SSH;
- V2 memory, transaction and recovery constraints remain mandatory;
- performance and Agent Prompt work proceed without inventing official outcomes.

The material binds production source to successful commit 4, `c8d86836bdf4e9b69b2836d047cb839878f0caa7`.

## Five new evidence units

| Dimension | New unit | Score tier |
| --- | --- | ---: |
| Problem understanding | `evidence-directory-discipline` | 1.5 |
| Technical transfer | `server-only-execution` | 1.0 |
| Independent validation | `negative-results-not-counted` | 2.0 |
| Experimental iteration | `bounded-self-iteration` | 2.0 |
| Tradeoff reflection | `performance-prompt-balance` | 2.0 |

Every new unit uses a different student quote and different executed-result quote. Earlier successful units remain present. No student evidence is reused across dimensions.

## Attribution

- The four retained performance results and thirteen non-retained candidate outcomes are marked as tool-generated summaries.
- The d21 Agent Prompt score `3.000000` is retained as a platform/user report, not claimed as a v4 result.
- Agent implementation, measurements and interpretation are not attributed to the student.
- Each student quote is an exact substring of the selected material record.

## Validation

TDD first failed because all five v4 units and the updated source binding were absent. A second failure caught a reused result quote across dimensions. The final material splits C7/C12/C13/C17 into independent records and passes:

- `tests/test_agent_material.py`: `8` tests, OK.
- Strict UTF-8 JSON and duplicate/non-finite rejection: PASS.
- Five dimensions each contain candidate units: PASS.
- JSON pointers resolve and quotes appear verbatim: PASS.
- Cross-dimension result quote deduplication: PASS.
- Score-tier/result-evidence consistency: PASS.
- Obvious complete secret formats: absent.
- File size: `28,648` bytes, below the 128 KiB limit.
- Material SHA-256: `bb70bb34112b2f36f995d63cff9ba1006cdb4b038cfe2155a1203c22a06fd189`.

This is a local structural check only. It does not certify official semantic scoring and does not guarantee a higher ranking.

## Artifacts

- `red-test.txt`: expected missing-unit failure.
- `green-test-2.txt`: deduplicated intermediate success.
- `final-test.txt`: final eight-test success.
- `material.sha256`, `material-size.txt`.
- `update_material.py`, `update_material_dedupe.py`, `add_final_validation.py`: reproducible material transformations.
