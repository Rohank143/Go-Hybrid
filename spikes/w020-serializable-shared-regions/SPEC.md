# Specification: Serializable Shared-State Regions via Admitted Transactions (W-020)

- **Track & Slot:** Wildcard Track, Slot 20 (Issue #417, W-020)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 / December Window (Discussion #365)
- **Author/Spike Submitter:** @Rohank143 (Architectural proposal credit: @matheuswallace)
- **Feasibility Spike Artifact:** `spikes/w020-serializable-shared-regions/`

---

## 1. Problem Statement & Motivation

Today in Go-Hybrid, concurrency safety is enforced strictly through **exclusive ownership** (`own`, move-on-send) or message isolation (`spikes/spike13`, `spikes/w005`). However, real-world systems frequently require multiple concurrent tasks to coordinate over **shared logical state** (e.g. shared caches, multi-account ledger balances, routing tables, game states).

Existing workarounds fail the core design criteria:
1. **Ad-hoc Mutexes:** Unchecked `sync.Mutex` maps violate compile-time safety; separate locks do not compose, deadlocks cannot be statically prevented without level-ordering, and data races remain possible.
2. **Actor Messaging:** Single-actor queues serialize all requests, introducing queue latency bottlenecks and complex failure rollback.
3. **Unchecked Shared Pointers:** Bypassing the checker degrades to raw Go, losing all race-freedom guarantees.

---

## 2. Proposed Architecture: Serializable Transactional Regions

W-020 introduces **Serializable Shared-State Regions** with **Multi-Version Read-Set Validation (MVSI)** and **Strict Effect Admission**.

### 2.1 The State & Snapshot Model
A transactional region manages a set of versioned scalar cells:
$$S = \langle v_{\text{root}}, \mathcal{C} \rangle, \quad \mathcal{C} = \{ k \mapsto (val, v_k) \}$$

1. **Snapshot Acquisition:** When an `atomic` block begins, it acquires the current immutable root snapshot $v_{\text{root}}$.
2. **Private Staging:**
   - `cell.Get()`: Reads from the snapshot, recording cell version $v_k$ in the transaction's read set $\mathcal{R}$. If previously written in this transaction, it reads the staged value (Read-Your-Writes).
   - `cell.Set(v)`: Staged in private write buffer $\mathcal{W}$. No in-place modification of shared memory occurs.
3. **Full Read-Set Validation (Anti-Write-Skew):**
   Under an atomic commit lock $\mathcal{L}_{\text{commit}}$, the transaction validates that *every cell read* still matches its version in the current global state:
   $$\forall k \in \mathcal{R}, \quad v_k == \text{current\_version}(k)$$
   *Critical Invariant:* Validating both read and written cells is strictly required. Validating write-set versions alone allows classical **write-skew anomalies**; full read-set validation guarantees strict serializability.
4. **Linearized Atomic Publication:**
   If validation succeeds, all writes in $\mathcal{W}$ are applied, cell versions incremented ($v'_k = v_k + 1$), and a new root snapshot $v'_{\text{root}} = v_{\text{root}} + 1$ is published atomically. On conflict, the transaction aborts and retries up to a bounded limit.

---

## 3. Strict Compiler Effect-Admission Grammar

To guarantee serializability and safe retries, transaction bodies are restricted to a **pure computational subset**:

$$\text{Stmt}_{\text{atomic}} ::= x := \text{cell.Get}() \mid \text{cell.Set}(e) \mid \text{local computations} \mid \text{pure conditionals/loops}$$

### Explicitly Forbidden Effects:
1. **No I/O Operations:** Network calls, filesystem access, and printing are rejected (`HYB-E6001`).
2. **No Channel Operations:** `ch <- v`, `<-ch`, and `select` are rejected (`HYB-E6002`) because channel communication cannot be rolled back on abort.
3. **No Concurrent Task Spawning:** Spawning `go func()` or `hy.Task` inside a transaction is rejected (`HYB-E6003`).
4. **No Unadmitted Foreign Calls:** Opaque external functions cannot be verified for side effects and fail closed (`HYB-E3005`).
5. **No Mutable Closure Escapes:** Closures capturing external mutable state are rejected (`HYB-E3001`).

---

## 4. Empirical Validation & Falsification Criteria

1. **Exhaustive Interleaving Simulation:** Exhaustively simulate all interleaving execution schedules of concurrent transactions over shared cells and verify 100% equivalence against a serial reference oracle.
2. **Falsifier Control (Write-Set Only Mutant):** Mutate validation to check write versions only; demonstrate that write skew produces observable invariant violations.
3. **Direct Comparison Against Baselines:** Benchmark throughput, abort rates, and latency under uncontended, disjoint, and contended workloads against Coarse Mutex and Actor baselines.
