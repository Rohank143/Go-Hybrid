# W-002 Spike Preregistration: Type-Carried Ownership Capabilities

- **Track & Slot:** Wildcard Track, Slot 2 (Issue #279, W-002)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 (Discussion #365)
- **Spike Submitter:** @Rohank143 (Architectural proposal: @yaojiajia838-design)
- **Status:** Preregistered prior to validation measurements

---

## 1. Stated Hypotheses

1. **H1 (Graph Deletion):** Deleting `may_share`, `aliases`, and scope snapshots in favor of a compositional capability typing rule $\Gamma \vdash e : \tau \dashv \Gamma'$ preserves 100% of Tier-0 safety guarantees.
2. **H2 (Closure Soundness):** Closures capturing `own[T]` capabilities behave as affine `FnOnce` values whose double-execution is blocked at type-check time.
3. **H3 (Corpus 15 Exemption Removal):** Fresh constructors (e.g. `chunk_of`) produce unaliased `own[T]` values compositionally without requiring ad-hoc `call_local_roots` graph exemptions.
4. **H4 (Zero Annotation Burden):** Bidirectional local inference permits un-annotated local expressions to be typed without explicit `own`/`borrow` constructors.

---

## 2. Pre-Registered Test Matrix (10 Falsification Controls)

### Positive Controls (Accept 5/5)
- **C1 (Fresh Allocation Inferred Own):** Fresh struct literal inferred as `own[T]`, consumed once without error.
- **C2 (Closure Invoked Once):** Affine closure capturing `own[T]` executed once successfully.
- **C3 (Corpus 15 Fresh Slice Chunk):** Function returning fresh `own[[]byte]` accepted without alias graph exemption.
- **C4 (Borrowed Reference Loan):** Borrowed capability `borrow[T]` read without consuming base ownership.
- **C5 (Zero-Annotation Local Inference):** Standard Go local variable sequence checked without explicit capability annotations.

### Negative Controls (Reject 5/5)
- **M1 (Double Consume / Use-After-Move):** Consuming `own[T]` twice fails with `HYB-E1001`.
- **M2 (Affine Closure Double-Execution):** Invoking an `own[FnOnce]` closure twice fails with `HYB-E1001`.
- **M3 (Loop Backedge Move):** Consuming an outer `own[T]` capability on a loop backedge fails with `HYB-E1002`.
- **M4 (Closure Leaks Mutable Borrow Across Task):** Spawning a closure capturing a non-sendable pointer fails with `HYB-E3001`.
- **M5 (Unconsumed Linear Capability Invalidation):** Attempting to store an `own[T]` capability into an unmanaged aliased container fails with `HYB-E3006`.
