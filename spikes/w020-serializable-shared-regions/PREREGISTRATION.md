# W-020 Spike Preregistration: Serializable Shared-State Regions

- **Track & Slot:** Wildcard Track, Slot 20 (Issue #417, W-020)
- **Base Commit:** `ec3fe0b` (`upstream/main`)
- **Review Window:** 2026-11-01 / December Window (Discussion #365)
- **Spike Submitter:** @Rohank143 (Architectural proposal credit: @matheuswallace)
- **Status:** Preregistered prior to validation measurements

---

## 1. Stated Hypotheses

1. **H1 (Serializability Equivalence):** Multi-version read-set validation with atomic publication is strictly equivalent to a serial execution oracle across all possible interleaving execution schedules.
2. **H2 (Write-Skew Falsification):** A mutant that validates write-cell versions only will admit conflicting write-skew schedules, whereas full read-set validation rejects 100% of conflicting commits.
3. **H3 (Effect Admission Fail-Closed):** Transactions containing side-effects (I/O, channel transfers, task spawning, external mutable captures) are rejected at compile time.

---

## 2. Pre-Registered Test Matrix (10 Falsification Controls)

### Positive Controls (Accept 5/5)
- **C1 (Lost Update Prevention):** Two concurrent transactions incrementing the same cell produce serial value $V_0 + 2$.
- **C2 (Serial Balance Transfer):** Atomic transfer between two accounts preserves total invariant $A + B == C$.
- **C3 (Read-Your-Writes Invariance):** Staged private write is immediately observed by subsequent reads in the same transaction.
- **C4 (Disjoint Concurrent Commits):** Concurrent transactions operating on disjoint cells both commit without false conflict.
- **C5 (Read-Only Snapshot Validation):** Read-only transaction reads consistent snapshot without interfering with concurrent writers.

### Negative Controls (Reject 5/5)
- **M1 (Write-Skew Falsifier):** Classical write-skew interleaving (balance constraint $x + y \ge 10$) is rejected by full read-set validation.
- **M2 (Stale Read Conflict Abort):** Transaction committing after read cell was updated by another transaction is aborted.
- **M3 (Forbidden I/O Effect):** Transaction containing I/O call fails effect admission with `HYB-E6001`.
- **M4 (Forbidden Channel Transfer):** Transaction containing channel send/recv fails effect admission with `HYB-E6002`.
- **M5 (Forbidden Concurrent Spawn):** Transaction attempting to spawn `go func()` fails effect admission with `HYB-E6003`.
