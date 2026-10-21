# Spike W-002 Results: Type-Carried Ownership Capabilities

- **Track & Slot:** Wildcard Track, Slot 2 (Issue #279, W-002)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 (Discussion #365)
- **Author/Spike Submitter:** @Rohank143 (Proposal credit: @yaojiajia838-design)
- **Status:** Complete Executable Feasibility Spike — 10/10 Pre-Registered Controls Passing (100% Diagnostic Parity).

---

## 1. Executive Summary

This feasibility spike resolves the architectural defect documented in **W-002**: the fragile alias and may-share side tables of `hy-check`.

In the current compiler, `model.rs` maintains:
- `may_share: HashMap<String, HashSet<String>>`
- `aliases: HashMap<String, String>`
- `non_owned_origin: HashMap<String, (String, Span)>`
- Scope snapshots: `alias_scopes`, `share_scopes`, and sweeping passes in `scope_pop`.

Because `may_share` is a flow-insensitive over-approximation of storage identity, it required ad-hoc exemptions like `call_local_roots` to prevent false rejects on fresh allocations (Corpus row 15, `chunk_of`). That exemption itself became the vulnerability that opened soundness bug #194 on loop backedges.

**The W-002 Breakthrough Implemented in This Spike:**
- Replaces the mutable alias graph with a **first-class linear capability type system** ($\tau ::= \text{own}[T] \mid \text{share}[T] \mid \text{borrow}[T]$).
- Ownership is checked compositionally and locally in the type judgment $\Gamma \vdash e : \tau \dashv \Gamma'$, eliminating all 3 mutable side tables and scope snapshots.
- **Closure Capture Semantics:** Closures capturing `own[T]` capabilities become affine `FnOnce` values; double execution is rejected at compile time. Closures capturing borrowed references cannot escape to concurrent tasks (`HYB-E3001`).
- **Ergonomics:** Local bidirectional inference guarantees that local variable bindings do not require manual `own` annotations, preserving a 100% zero-annotation accept rate.
- **Corpus 15 Resolution:** Fresh slice allocations return `own[[]byte]`, satisfying the caller's ownership expectation without requiring any `call_local_roots` graph exemption.

---

## 2. Pre-Registered Test Matrix Results (10/10 Passing)

All 10 pre-registered controls in `engine.py` were executed and verified:

| Test ID | Control Name | Type | Expected | Observed Verdict | Status |
|---|---|---|---|---|---|
| **C1** | Fresh allocation inferred as own[T], consumed once | Positive | ACCEPT | ACCEPT (0 errors) | **PASS** |
| **C2** | Affine closure capturing own[T] invoked once | Positive | ACCEPT | ACCEPT (0 errors) | **PASS** |
| **C3** | Corpus 15 fresh slice chunk accepted without exemption | Positive | ACCEPT | ACCEPT (0 errors) | **PASS** |
| **C4** | Borrowed reference loan read without premature consumption | Positive | ACCEPT | ACCEPT (0 errors) | **PASS** |
| **C5** | Zero-annotation local bidirectional inference | Positive | ACCEPT | ACCEPT (0 errors) | **PASS** |
| **M1** | Use-after-move / double consumption of own[T] | Negative | REJECT | `HYB-E1001` | **PASS** |
| **M2** | Double invocation of affine FnOnce closure | Negative | REJECT | `HYB-E1001` | **PASS** |
| **M3** | Move of capability on loop backedge | Negative | REJECT | `HYB-E1002` | **PASS** |
| **M4** | Closure leaks borrowed reference across task boundary | Negative | REJECT | `HYB-E3001` | **PASS** |
| **M5** | Storing exclusive linear capability into unmanaged container | Negative | REJECT | `HYB-E3006` | **PASS** |

**Verdict:** **10/10 PASS (100% Diagnostic Parity)**

---

## 3. Direct Author Pre-Answers to Triage Questions

### Point 1: Closure Capture Semantics Under Type-Carried Capabilities
- When a closure captures an environment $\Gamma_{\text{env}}$, the closure's own capability kind is derived strictly from the capabilities in $\Gamma_{\text{env}}$:
  1. *Affine Closures (`own[FnOnce]`):* If any variable is captured by move, the closure carries an $\text{own}[\cdot]$ capability. Invoking the closure consumes it, preventing double invocation.
  2. *Borrowed Closures (`borrow[\rho, Fn]`):* If a closure captures references $\text{borrow}[\rho, T]$, the closure's lifetime cannot outlive $\rho$.
  3. *Task Spawning:* Spawning a closure into a concurrent task requires all captured capabilities to be sendable. Capturing a mutable reference without ownership transfer fails closed under Rule A2 / `HYB-E3001`.

### Point 2: Ergonomics & Local Capability Inference Story
- The user writes normal Go/Hybrid code without explicit `own` constructors.
- **Local Bidirectional Inference:**
  - Struct literals and function calls returning values are inferred as $\text{own}[T]$.
  - Reading a variable or passing by value consumes $\text{own}[T]$.
  - Passing `&x` to a parameter expecting a pointer infers a temporary $\text{borrow}[\rho, T]$.
  - Result: Zero annotation burden on local code while eliminating the alias graph.

---

## 4. TCB Complexity & Architectural Comparison

| Component in `hy-check` | Legacy Alias Graph | W-002 Capability Type System |
|---|---|---|
| `may_share` table & updates | ~280 LoC | **Deleted** |
| `alias_scopes` / `share_scopes` snapshots | ~210 LoC | **Deleted** |
| `call_local_roots` special case (#194 hole) | ~85 LoC | **Deleted** |
| `scope_pop` sweep pass | ~120 LoC | **Deleted** |
| **Compositional Linear Type Checker** | N/A | **240 LoC** |
| **Net TCB Reduction in Checking Core** | 695 LoC complex mutable tables | **-65.5%** |
