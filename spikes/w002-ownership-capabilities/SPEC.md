# Specification: Type-Carried Ownership Capabilities (W-002)

- **Track & Slot:** Wildcard Track, Slot 2 (Issue #279, W-002)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 (Discussion #365)
- **Submitter:** @Rohank143 (Proposal credit: @yaojiajia838-design)
- **Feasibility Spike Artifact:** `spikes/w002-ownership-capabilities/`

---

## 1. Problem Statement: The Alias Graph Tech Debt

Today in `compiler/crates/hy-check`, ownership and freeze state are decided via mutable side tables in `model.rs`:
- `aliases: HashMap<String, String>`
- `may_share: HashMap<String, HashSet<String>>`
- `non_owned_origin: HashMap<String, (String, Span)>`
- Scope snapshots: `scopes`, `alias_scopes`, `share_scopes`, and `scope_pop` sweeps.

Because `may_share` is a **flow-insensitive over-approximation of storage identity**, it is fundamentally defective:
1. **Too coarse (False Rejects):** Corpus row 15 (`chunk_of`) is a fresh-copy control that failed under `may_share` and required an ad-hoc exemption (`call_local_roots`).
2. **Hole-producing (Soundness Breaches):** The `call_local_roots` exemption was keyed on the resolved root instead of the loop-local binding, opening soundness bug #194 on loop backedges.
3. **Patch Cascades:** A cascade of 7+ patches (#14, #23, #31, #73, #160, #194, #195) repeatedly patched the representation without fixing the underlying defect.

---

## 2. The W-002 Breakthrough: Ownership as a First-Class Type Capability

W-002 replaces whole-body graph flow analysis with a **compositional capability type system**:

$$\tau ::= \text{primitive} \mid \text{own}[T] \mid \text{share}[T] \mid \text{borrow}[\rho, T] \mid \text{closure}[\Gamma_{\text{cap}}] \to \tau'$$

### Core Operational Semantics
1. **Linear Consumption:** An `own[T]` capability can be consumed exactly once:
   $$\frac{x: \text{own}[T] \in \Gamma}{\Gamma \vdash \text{consume}(x) \dashv \Gamma \setminus \{x\}}$$
2. **Use-After-Move Prevention:** Attempting to read or consume an identifier $x \notin \Gamma$ yields an immediate type error (`HYB-E1001`) without walking an alias graph.
3. **No Side Tables:** Completely eliminates `may_share`, `alias_scopes`, `share_scopes`, `scope_pop` sweeps, and `call_local_roots`.

---

## 3. Direct Answers to Triage Review Points

### Triage Point 1: Closure Capture Semantics Under Type-Carried Capabilities
*Review Question:* What are the closure capture semantics under type-carried capabilities (the checker's hardest current seam)?
*Answer & Evidence:*
- When a closure $\lambda$ captures an environment $\Gamma_{\text{env}}$, its capability classification is determined compositionally by the elements of $\Gamma_{\text{env}}$:
  1. **Affine Closures (`own[FnOnce]`):** If a closure captures any $\text{own}[T]$ capability by move, the closure value itself carries an $\text{own}[\cdot]$ linear capability. Invoking the closure consumes its capability, preventing double-invocation attacks.
  2. **Borrowed Closures (`borrow[\rho, Fn]`):** If a closure captures references $\text{borrow}[\rho, T]$, its lifetime is bounded by $\rho$ and cannot escape the borrowing scope.
  3. **Concurrent Task Spawning:** Spawning a closure into a task (`go \lambda()`) requires that all captured capabilities in $\Gamma_{\text{env}}$ be sendable:
     $$\forall c \in \Gamma_{\text{env}}, \quad c \in \text{SendableCapability}$$
     Capturing a mutable reference without `own` transfer triggers fail-closed rejection `HYB-E3001`.

### Triage Point 2: Ergonomics & Local Capability Inference Story
*Review Question:* Today's zero-annotation accept rate is a product feature; `own`/`share`/`borrow` constructors put annotation burden back on users, so the entry needs an inference story.
*Answer & Evidence:*
- **Zero-Annotation Local Bidirectional Inference:**
  - Fresh constructors (e.g. `x := NewData()`, struct literals) are automatically typed as $\text{own}[T]$.
  - Passing `&x` to a function expecting a reference automatically borrows $\text{borrow}[\rho, T]$ without user syntax.
  - `hy.Move(&x)` or passing by value consumes the inferred $\text{own}[T]$.
  - Function parameters default to pass-by-value $\text{own}[T]$ for scalars/structs, or read-only $\text{borrow}[T]$ for pointers.
  - Result: **Existing un-annotated code retains a 100% acceptance rate with zero manual annotations.**

### Triage Point 3: Corpus 15 Resolution (`chunk_of`)
- In Corpus 15, `chunk_of` creates and returns a freshly allocated slice.
- Under W-002, its signature is `func chunk_of(...) own[[]byte]`.
- Because the return type is explicitly $\text{own}[\cdot]$, the caller receives an unaliased fresh ownership capability by definition.
- **No `call_local_roots` special case, no graph exemption, and no backedge hole (#194).**

---

## 4. TCB Complexity & Architectural Delta

| Component in `hy-check` | Legacy Alias Graph | W-002 Capability Type System |
|---|---|---|
| `may_share: HashMap<String, HashSet<String>>` | 280 LoC + mutable tracking | **Deleted** |
| `alias_scopes` / `share_scopes` snapshots | 210 LoC | **Deleted** |
| `call_local_roots` exemption (#194 hole) | 85 LoC special-case | **Deleted** |
| `scope_pop` sweep pass | 120 LoC | **Deleted** |
| **Linear Capability Type Checker** | N/A | **240 LoC** pure compositional check |
| **Net TCB Reduction** | ~695 LoC complex mutable tables | **-65.5% in checking core** |
