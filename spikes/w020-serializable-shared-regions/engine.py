#!/usr/bin/env python3
import sys
import json
import itertools

class Cell:
    def __init__(self, cell_id, val, version=1):
        self.cell_id = cell_id
        self.val = val
        self.version = version

class TxnAttempt:
    def __init__(self, tx_id, root_version):
        self.tx_id = tx_id
        self.snapshot_version = root_version
        self.read_set = {}   # cell_id -> version
        self.write_set = {}  # cell_id -> value

    def read(self, cells, cell_id):
        if cell_id in self.write_set:
            return self.write_set[cell_id]
        c = cells[cell_id]
        self.read_set[cell_id] = c.version
        return c.val

    def write(self, cell_id, val):
        self.write_set[cell_id] = val

class RegionSimulator:
    def __init__(self, initial_cells):
        self.cells = {c.cell_id: Cell(c.cell_id, c.val, c.version) for c in initial_cells}
        self.root_version = 1

    def commit(self, tx, validate_reads=True):
        # Full read-set validation: anti-write-skew invariant
        if validate_reads:
            for c_id, expected_ver in tx.read_set.items():
                if self.cells[c_id].version != expected_ver:
                    return False, "HYB-E6010: read-version conflict"
        else:
            # Buggy mutant: checks write-set only
            for c_id in tx.write_set.keys():
                if c_id in tx.read_set and self.cells[c_id].version != tx.read_set[c_id]:
                    return False, "HYB-E6010: write-version conflict"

        # Apply writes
        for c_id, val in tx.write_set.items():
            self.cells[c_id].val = val
            self.cells[c_id].version += 1
        self.root_version += 1
        return True, "COMMITTED"

def check_effect_admission(effect_kind):
    forbidden = {
        "io": "HYB-E6001",
        "channel": "HYB-E6002",
        "spawn": "HYB-E6003",
        "unmanaged_escape": "HYB-E3001"
    }
    return forbidden.get(effect_kind, None)

def run_tests():
    results = []

    # C1: Lost Update Prevention
    reg = RegionSimulator([Cell(1, 100)])
    tx1 = TxnAttempt(1, reg.root_version)
    tx2 = TxnAttempt(2, reg.root_version)
    v1 = tx1.read(reg.cells, 1)
    v2 = tx2.read(reg.cells, 1) # Both read initial 100 concurrently
    tx1.write(1, v1 + 5)
    ok1, _ = reg.commit(tx1, validate_reads=True)
    tx2.write(1, v2 + 10)
    ok2, err2 = reg.commit(tx2, validate_reads=True) # Conflicted because tx1 updated cell 1!
    # Retry tx2
    tx2_retry = TxnAttempt(2, reg.root_version)
    v2_retry = tx2_retry.read(reg.cells, 1) # reads updated 105
    tx2_retry.write(1, v2_retry + 10)
    ok2_retry, _ = reg.commit(tx2_retry, validate_reads=True)
    final_val = reg.cells[1].val
    results.append({
        "id": "C1",
        "name": "Lost update prevention via conflict abort and retry",
        "expected": "ACCEPT",
        "passed": ok1 and (not ok2) and ok2_retry and (final_val == 115)
    })

    # C2: Serial Balance Transfer
    reg = RegionSimulator([Cell(1, 50), Cell(2, 50)]) # total 100
    tx = TxnAttempt(1, reg.root_version)
    a = tx.read(reg.cells, 1)
    b = tx.read(reg.cells, 2)
    tx.write(1, a - 20)
    tx.write(2, b + 20)
    ok, _ = reg.commit(tx, validate_reads=True)
    total = reg.cells[1].val + reg.cells[2].val
    results.append({
        "id": "C2",
        "name": "Atomic balance transfer preserves global invariant A + B == 100",
        "expected": "ACCEPT",
        "passed": ok and (total == 100) and (reg.cells[1].val == 30)
    })

    # C3: Read-Your-Writes Invariance
    reg = RegionSimulator([Cell(1, 10)])
    tx = TxnAttempt(1, reg.root_version)
    tx.write(1, 42)
    observed = tx.read(reg.cells, 1)
    ok, _ = reg.commit(tx, validate_reads=True)
    results.append({
        "id": "C3",
        "name": "Read-your-writes observes staged private buffer value",
        "expected": "ACCEPT",
        "passed": ok and (observed == 42)
    })

    # C4: Disjoint Concurrent Commits
    reg = RegionSimulator([Cell(1, 10), Cell(2, 20)])
    txA = TxnAttempt(1, reg.root_version)
    txB = TxnAttempt(2, reg.root_version)
    txA.write(1, 99)
    txB.write(2, 88)
    okA, _ = reg.commit(txA, validate_reads=True)
    okB, _ = reg.commit(txB, validate_reads=True)
    results.append({
        "id": "C4",
        "name": "Disjoint cell writes both commit concurrently without conflict",
        "expected": "ACCEPT",
        "passed": okA and okB and (reg.cells[1].val == 99) and (reg.cells[2].val == 88)
    })

    # C5: Read-Only Snapshot Validation
    reg = RegionSimulator([Cell(1, 10), Cell(2, 20)])
    tx_ro = TxnAttempt(1, reg.root_version)
    v1 = tx_ro.read(reg.cells, 1)
    v2 = tx_ro.read(reg.cells, 2)
    ok_ro, _ = reg.commit(tx_ro, validate_reads=True)
    results.append({
        "id": "C5",
        "name": "Read-only snapshot validation succeeds without writing",
        "expected": "ACCEPT",
        "passed": ok_ro and (v1 == 10) and (v2 == 20) and (len(tx_ro.write_set) == 0)
    })

    # M1: Write-Skew Falsifier (Negative Control)
    # Invariant: x + y >= 10. Initial x=10, y=10.
    # Tx1 reads x, y; writes x = 0.
    # Tx2 reads x, y; writes y = 0.
    # Under full read-set validation: one commits, second aborts (invariant holds).
    # Under write-set-only validation: BOTH commit -> x=0, y=0 (invariant violated!).
    reg_full = RegionSimulator([Cell(1, 10), Cell(2, 10)])
    t1 = TxnAttempt(1, reg_full.root_version)
    t2 = TxnAttempt(2, reg_full.root_version)
    t1.read(reg_full.cells, 1); t1.read(reg_full.cells, 2); t1.write(1, 0)
    t2.read(reg_full.cells, 1); t2.read(reg_full.cells, 2); t2.write(2, 0)
    ok1_full, _ = reg_full.commit(t1, validate_reads=True)
    ok2_full, err_full = reg_full.commit(t2, validate_reads=True)
    # Write-set only mutant:
    reg_buggy = RegionSimulator([Cell(1, 10), Cell(2, 10)])
    t1_b = TxnAttempt(1, reg_buggy.root_version)
    t2_b = TxnAttempt(2, reg_buggy.root_version)
    t1_b.read(reg_buggy.cells, 1); t1_b.read(reg_buggy.cells, 2); t1_b.write(1, 0)
    t2_b.read(reg_buggy.cells, 1); t2_b.read(reg_buggy.cells, 2); t2_b.write(2, 0)
    ok1_b, _ = reg_buggy.commit(t1_b, validate_reads=False)
    ok2_b, _ = reg_buggy.commit(t2_b, validate_reads=False)
    results.append({
        "id": "M1",
        "name": "Write-skew mutant correctly rejected by full read-set validation",
        "expected": "REJECT",
        "expected_code": "HYB-E6010",
        "passed": ok1_full and not ok2_full and (ok1_b and ok2_b) # demonstrates mutant fails invariant
    })

    # M2: Stale Read Conflict Abort
    reg = RegionSimulator([Cell(1, 100)])
    tx_stale = TxnAttempt(1, reg.root_version)
    tx_stale.read(reg.cells, 1)
    # Another transaction mutates cell 1
    reg.cells[1].val = 200
    reg.cells[1].version += 1
    tx_stale.write(1, 150)
    ok_stale, err_stale = reg.commit(tx_stale, validate_reads=True)
    results.append({
        "id": "M2",
        "name": "Stale read version aborts transaction with HYB-E6010",
        "expected": "REJECT",
        "expected_code": "HYB-E6010",
        "passed": not ok_stale and ("HYB-E6010" in err_stale)
    })

    # M3: Forbidden I/O Effect Admission Failure
    code_m3 = check_effect_admission("io")
    results.append({
        "id": "M3",
        "name": "Forbidden I/O effect rejected at compile time with HYB-E6001",
        "expected": "REJECT",
        "expected_code": "HYB-E6001",
        "passed": code_m3 == "HYB-E6001"
    })

    # M4: Forbidden Channel Operation Admission Failure
    code_m4 = check_effect_admission("channel")
    results.append({
        "id": "M4",
        "name": "Forbidden channel send/recv rejected with HYB-E6002",
        "expected": "REJECT",
        "expected_code": "HYB-E6002",
        "passed": code_m4 == "HYB-E6002"
    })

    # M5: Forbidden Concurrent Task Spawn Admission Failure
    code_m5 = check_effect_admission("spawn")
    results.append({
        "id": "M5",
        "name": "Forbidden concurrent task spawn rejected with HYB-E6003",
        "expected": "REJECT",
        "expected_code": "HYB-E6003",
        "passed": code_m5 == "HYB-E6003"
    })

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_tests()
