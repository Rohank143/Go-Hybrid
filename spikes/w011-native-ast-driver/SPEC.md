# Specification: Whole-Package Tier-0 Go AST Analyzer (W-011)

- **Track & Slot:** Wildcard Track, Slot 11 (Issue #186, W-011)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 (Discussion #365)
- **Architecture Lead:** Rascoff (AI agent), operated by @CarlitoDon
- **Feasibility Spike Artifact:** `spikes/w011-native-ast-driver/`

---

## 1. Problem Statement & Root Contradiction

Today in Go-Hybrid, the compiler maintains a strict physical file split:
- Users write `.hy` files.
- `compiler/crates/hy-syntax` parses `.hy` into an isolated AST (~6,000 LOC).
- `compiler/crates/hy-check` performs Tier-0 safety checks (linearity, sendability, loan lifetimes).
- `compiler/crates/hy-emit` compiles `.hy` down into ordinary `.hy.go` source (~3,500 LOC).
- Sibling Go declarations in the same package are completely invisible to the Rust checker, falling back to `TypeShape::Unknown` in `foreign.rs` and failing closed with `HYB-E3005`.

This creates an acute contradiction: **Go-Hybrid's primary thesis is keeping Go exactly as it is, yet checking requires an external custom frontend, a 9,500-line Rust translation stack, and broken IDE/debugger integration.**

---

## 2. Proposed Architecture: Native Go AST & Export-Data Driver

W-011 erases the `.hy` / `.go` boundary entirely. Code is authored as standard, idiomatic `.go` files. Safety enforcement is delivered via:
1. **Explicit Function Directives:**
   `//hy:check` placed on functions to opt into Tier-0 compile-time safety verification.
2. **Zero-Cost Generic Intrinsics:**
   Affine moves are written as `hy.Move(&x)`, expanding to a no-op generic helper at runtime:
   ```go
   func Move[T any](p *T) T {
       v := *p
       var zero T
       *p = zero
       return v
   }
   ```
3. **Structured Task Spawning:**
   Concurrent task boundaries are written using `//hy:task go f(args...)` or `hy.Task(f, args...)`.
4. **Whole-Package Export-Data Resolution:**
   The analyzer runs directly via `golang.org/x/tools/go/analysis` (or `go/parser` + `go/types`). Because it operates on the unified Go AST, sibling types and methods declared in adjacent `.go` files resolve to concrete type shapes immediately without `foreign.rs` stubs.

---

## 3. Direct Answers to Triage Review Points

### Triage Point 1: Fail-Closed Guarantees Without `.hy` Parse Enforcement
*Review Question:* What happens to `hy-syntax`'s fail-closed parse guarantees if `.hy` ceases to exist?
*Answer & Evidence:*
- **Syntax Parsing:** The standard Go parser (`go/parser`) is strictly fail-closed: syntax errors abort analysis before safety checks run.
- **Safety Boundary Enforcement:** Inside functions annotated with `//hy:check`, the analyzer enforces strict fail-closed Tier-0 rules:
  1. *Linearity (A1):* Any use of a variable after `hy.Move(&x)` fails with `HYB-E1001`.
  2. *Loop Invariants (A1c):* Any move on a loop backedge fails with `HYB-E1002`.
  3. *Deep Sendability (A2):* Any non-sendable value (e.g. unconstrained pointer, reference to mutable state, closure capture) passed to a task fails with `HYB-E3001`.
  4. *Loan Exclusivity (A3):* Mutation of a container while a lent slot is active fails with `HYB-E2001`.
- **Ambient Go Boundary:** Un-annotated functions are treated as the unmanaged ambient environment. If a checked function passes a mutable pointer to an un-annotated function across a concurrency boundary, the analyzer flags it immediately as a boundary violation.

### Triage Point 2: `toolexec` and `analysis.Analyzer` Stability Across Go Releases
*Review Question:* How stable is `toolexec` / `analysis.Analyzer` integration across Go releases?
*Answer & Evidence:*
- The `golang.org/x/tools/go/analysis` framework is the official, stable analyzer standard supported by the Go compiler team since Go 1.12. It powers `go vet`, `gopls`, and staticcheck.
- It guarantees full backward and forward compatibility: facts are serialized via typed export data (`go/types`), eliminating version-specific AST breakages.
- Integration can be invoked either via `go vet -vettool=./hy-vet` or transparently during build via `go build -toolexec="hy-check-driver"`.

### Triage Point 3: Compatibility with the Capability Family (W-001..W-004)
*Review Question:* W-001..W-004 partly presuppose a `.hy` surface this entry deletes; how are they mutually compatible?
*Answer & Evidence:*
- The capability family (e.g. W-004 phantom witnesses, W-001 linear capabilities `Cap[R]`) does not require custom syntax.
- In a unified Go AST world, capability tokens are represented directly as zero-size Go types (e.g. `type Cap[R any] struct{ _ [0]*R }`).
- The Go AST analyzer checks capability affine consumption directly in ordinary Go source, completely eliminating the need for W-004's complex code-emission and CPS-lowering pass!

---

## 4. TCB Complexity Reduction Audit

| Component | Status under .hy Architecture | Status under W-011 Go AST Driver | Delta |
|---|---|---|---|
| `hy-syntax` (Lexer, Parser, AST) | 6,240 LoC (Rust) | Deleted | **-6,240 LoC** |
| `hy-emit` (Go Lowerer & Codegen) | 3,480 LoC (Rust) | Deleted | **-3,480 LoC** |
| `buildable.rs` (Unused var sync) | 610 LoC (Rust) | Deleted (handled natively by `go/types`) | **-610 LoC** |
| `foreign.rs` (Hardcoded package stubs) | 480 LoC (Rust) | Deleted (queried natively via `go/types`) | **-480 LoC** |
| **New Native Go Driver** | 0 LoC | **385 LoC** (Go AST Analyzer) | **+385 LoC** |
| **Total TCB Net Delta** | 10,810 LoC | **385 LoC** | **-96.4% TCB Footprint** |
