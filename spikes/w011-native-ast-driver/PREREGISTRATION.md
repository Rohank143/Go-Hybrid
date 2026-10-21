# W-011 Spike Preregistration: Whole-Package Go AST Tier-0 Driver

- **Track & Slot:** Wildcard Track, Slot 11 (Issue #186, W-011)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 (Discussion #365)
- **Spike Submitter:** @Rohank143 (Architectural proposal: Rascoff / @CarlitoDon)
- **Status:** Preregistered prior to validation measurements

---

## 1. Stated Hypotheses

1. **H1 (Parity):** Tier-0 safety guarantees (use-after-move A1b, loop backedge move A1c, task sendability A2, map slot loan exclusivity A3) can be enforced directly over standard Go AST without an intermediate custom `.hy` syntax tree.
2. **H2 (Sibling Resolution):** Sibling types, methods, and channels declared in adjacent `.go` files within the same package resolve automatically without `foreign.rs` manual stubs or `HYB-E3005` fail-closed rejections.
3. **H3 (Complexity & Performance):** Erasing the `.hy` / `.go` barrier deletes >9,000 LoC of Rust compiler infrastructure and reduces per-function analysis overhead to <0.15ms.

---

## 2. Invariant Preconditions

1. **Directive Discipline:** Only functions with `//hy:check` undergo Tier-0 borrow/linearity analysis; un-annotated functions are treated as unmanaged boundary.
2. **Zero Runtime Overhead:** Intrinsics like `hy.Move(&x)` compile to simple assignments in Go and incur 0 nanoseconds of runtime penalty.
3. **Fail-Closed on Unknown Boundaries:** If a pointer with mutable capability crosses an unmanaged or unanalyzable boundary, the analyzer rejects the program deterministically.

---

## 3. Pre-Registered Test Matrix (10 Falsification Controls)

### Positive Controls (Accept 5/5)
- **C1 (Sendable Primitives):** Integer and string values passed to concurrent task.
- **C2 (Affine Move Transfer):** Variable moved once via `hy.Move(&x)` into task.
- **C3 (Sibling Type Resolution):** Sibling struct declared in adjacent file passed to task without `HYB-E3005`.
- **C4 (Scoped Slot Loan):** Map element borrowed, inspected, and released before container mutation.
- **C5 (Zero-Cost Intrinsic Invariance):** `hy.Move` compiles and evaluates identically to native variable transfer.

### Negative Controls (Reject 5/5)
- **M1 (Use-After-Move):** Accessing variable after `hy.Move(&x)` fails with `HYB-E1001`.
- **M2 (Loop Backedge Move):** Moving a variable inside a loop body fails with `HYB-E1002`.
- **M3 (Non-Sendable Pointer Share):** Passing mutable pointer across task boundary fails with `HYB-E3001`.
- **M4 (Slot Loan Mutation Race):** Mutating map while element slot loan is active fails with `HYB-E2001`.
- **M5 (Unmanaged Pointer Escape):** Leaking local pointer to un-annotated package function fails with `HYB-E3003`.
