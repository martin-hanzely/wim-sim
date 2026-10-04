# Revision log

Phase 0 audit and the revision that follows it. Entries are append-only and in execution order.
Where an entry contradicts `export/`, it says so in its first line.

---

## Pre-specified seed protocol

**Declared 2026-10-04, before any run in Stages C–F. Not to be altered afterwards.**

> Every new comparison runs at ten seeds. A comparison whose per-seed differences are unanimous in
> sign is reported at ten seeds and not escalated. A comparison whose signs are not unanimous is
> escalated to thirty seeds, and both stages are reported.

The arithmetic that justifies it. Ten unanimous pairs give an exact two-sided sign/Wilcoxon p of
`2/2^10 = 0.00195`, which survives Holm correction across a family of fourteen:
`0.00195 x 14 = 0.027 < 0.05`. The `p = 2.6e-8` figures in the current export are the floor of an
exact Wilcoxon at `n = 30` (`min_attainable_p(30) = 2/2^30 = 1.9e-9`); those twenty extra seeds
measured the test's resolution limit, not the effect.

Two conditions make this honest rather than optional stopping, and both are binding:

1. the rule is declared in advance — this entry, committed before the first Stage C run;
2. **both stages are reported** — a comparison escalated to thirty seeds reports its ten-seed
   stage as well, with the same prominence.

Never decide seed counts after seeing results. Never escalate only the comparisons that failed to
separate.

### What would cost integrity — these stay off the table

- Cutting seeds after seeing results, or escalating only comparisons that failed to separate.
- Carrying any pre-fix controller result into a post-fix claim.
- Dropping the held-out set.
- Running some scenarios and quietly not reporting the rest.
- Switching on temperature compensation to make section III-B true retrospectively.

---
