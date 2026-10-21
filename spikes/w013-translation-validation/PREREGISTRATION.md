# W-013 Spike Preregistration: Translation Validation of Lowered Go

- **Track & Slot:** Wildcard Track, Slot 13 (Issue #345, W-013)
- **Base Commit:** `ce53c67c51480026e6378c2eecbf3b2f5b6191c9` (`upstream/main`)
- **Review Window:** 2026-11-01 (Discussion #365)
- **Author/Spike Submitter:** @Rohank143 (Proposal credit: @MyTH-zyxeon)
- **Status:** Preregistered prior to validation measurements

---

## 1. Stated Hypothesis

`hy-emit` can be treated as an **untrusted producer**, shifting the safety argument from emitter correctness to translation validation. An independent validator operating over a small, checked-effect intermediate representation (IR) and the reconstructed Go Control Flow Graph (CFG) can verify effect simulation and loan store-back preservation without duplicating the emitter's lowering implementation.

## 2. Invariant Preconditions

1. **Certificate as Hint:** Correspondence certificates (`.cert.json`) emitted alongside Go code are hints to guide simulation verification; they are never accepted as proof by themselves.
2. **Fail-Closed Boundary:** Any unmodeled constructs (e.g. arbitrary unstructured gotos, un-summarized foreign calls) immediately fail closed with `CERT_UNSUPPORTED`.
3. **Observation-Order Equivalence:** Equivalence requires matching the observable trace order (including slot mutations, channel operations, and opaque external calls), not merely identical final heap states.

## 3. Pre-registered Test Cases & Falsifiers

### Positive Controls (Must Pass Validation)
1. **P1 (Straight-Line Slot Mutation):** Map slot borrow, in-place increment, and store-back before return.
2. **P2 (Early Return Store-Back):** Conditional early return where each exit path flushes slot-loan store-backs prior to return.
3. **P3 (Branch Join Preservation):** Branching computation with distinct loan updates that join into a unified post-commit block.
4. **P4 (Pure Stuttering Steps):** Introduced pure temporary variables in Go lowering that do not alter the observable effect trace.
5. **P5 (Multi-Slot Independent Loans):** Multiple non-aliasing map slot loans with distinct keys committing in source-declared order.

### Negative Controls / Mutation Falsifiers (Must Be Rejected)
1. **F1 (Delayed Store-Back Across Alias Read):** Delaying map-slot commit past an alias read (the MyTH-zyxeon witness).
2. **F2 (Dropped Store-Back on Early Exit):** An early return path that omits `m[k] = val` before returning.
3. **F3 (Reordered Observable External Call):** Reordering a side-effecting function call before a slot commit.
4. **F4 (Duplicated Effect):** Emitter inadvertently lowers an effectful call or write twice along a loop or branch edge.
5. **F5 (Stale / Corrupted Certificate Digest):** Tampered Go AST bytes or mismatched certificate digest rejected fail-closed.
