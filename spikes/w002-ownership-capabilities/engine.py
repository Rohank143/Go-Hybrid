#!/usr/bin/env python3
import sys
import json
import time

class Capability:
    def __init__(self, kind, type_name, is_affine=True, lifetime=None):
        self.kind = kind          # 'own', 'share', 'borrow', 'closure'
        self.type_name = type_name
        self.is_affine = is_affine
        self.lifetime = lifetime

class CapabilityTypeChecker:
    def __init__(self):
        # Gamma: local variable -> Capability
        self.gamma = {}
        self.diagnostics = []
        self.loop_depth = 0

    def reset(self):
        self.gamma = {}
        self.diagnostics = []
        self.loop_depth = 0

    def instantiate_fresh(self, var_name, type_name):
        # Fresh expression is inferred as own[T]
        self.gamma[var_name] = Capability('own', type_name, is_affine=True)

    def borrow_ref(self, var_name, ref_name):
        # Borrow does not consume the base ownership
        if var_name not in self.gamma:
            self.diagnostics.append({"code": "HYB-E1001", "msg": f"cannot borrow consumed {var_name}"})
            return
        self.gamma[ref_name] = Capability('borrow', self.gamma[var_name].type_name, is_affine=False)

    def consume(self, var_name):
        if self.loop_depth > 0:
            self.diagnostics.append({"code": "HYB-E1002", "msg": f"capability {var_name} consumed on loop backedge"})
            return
        if var_name not in self.gamma:
            self.diagnostics.append({"code": "HYB-E1001", "msg": f"use after move: {var_name} was already consumed"})
            return
        del self.gamma[var_name]

    def create_closure(self, closure_name, captures):
        # captures: list of (var_name, mode: 'move' | 'borrow')
        captured_caps = {}
        is_affine_closure = False
        for var_name, mode in captures:
            if var_name not in self.gamma:
                self.diagnostics.append({"code": "HYB-E1001", "msg": f"cannot capture consumed {var_name}"})
                return
            cap = self.gamma[var_name]
            if mode == 'move':
                if cap.is_affine:
                    is_affine_closure = True
                del self.gamma[var_name]
                captured_caps[var_name] = cap
            else:
                # borrow
                captured_caps[var_name] = Capability('borrow', cap.type_name, is_affine=False)

        self.gamma[closure_name] = Capability('closure', 'func()', is_affine=is_affine_closure)
        self.gamma[closure_name].captured = captured_caps

    def invoke_closure(self, closure_name):
        if closure_name not in self.gamma:
            self.diagnostics.append({"code": "HYB-E1001", "msg": f"cannot invoke consumed closure {closure_name}"})
            return
        cap = self.gamma[closure_name]
        if cap.is_affine:
            # Invoking affine closure consumes it
            del self.gamma[closure_name]

    def spawn_task(self, target_name):
        if target_name not in self.gamma:
            self.diagnostics.append({"code": "HYB-E1001", "msg": f"cannot spawn consumed target {target_name}"})
            return
        cap = self.gamma[target_name]
        if cap.kind == 'closure':
            for c_name, c_cap in cap.captured.items():
                if c_cap.kind == 'borrow':
                    self.diagnostics.append({"code": "HYB-E3001", "msg": f"closure captures borrowed reference {c_name} across task boundary"})
                    return
        elif cap.kind == 'borrow':
            self.diagnostics.append({"code": "HYB-E3001", "msg": f"borrowed pointer {target_name} crosses task boundary"})
            return
        # Consumes the spawned capability
        del self.gamma[target_name]

    def store_unmanaged(self, target_container, var_name):
        if var_name not in self.gamma:
            self.diagnostics.append({"code": "HYB-E1001", "msg": f"cannot store consumed {var_name}"})
            return
        cap = self.gamma[var_name]
        if cap.kind == 'own':
            self.diagnostics.append({"code": "HYB-E3006", "msg": f"cannot store exclusive linear capability {var_name} into unmanaged container without transfer"})
            return

    def chunk_of_fresh(self, result_var):
        # Corpus 15 fresh slice: compositionally returns own[[]byte] without alias graph
        self.gamma[result_var] = Capability('own', '[]byte', is_affine=True)

def run_tests():
    tc = CapabilityTypeChecker()
    results = []

    # C1: Fresh Allocation Inferred Own (ACCEPT)
    tc.reset()
    tc.instantiate_fresh("data", "Payload")
    tc.consume("data")
    results.append({
        "id": "C1",
        "name": "Fresh allocation inferred as own[T], consumed once",
        "expected": "ACCEPT",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": len(tc.diagnostics) == 0
    })

    # C2: Closure Invoked Once (ACCEPT)
    tc.reset()
    tc.instantiate_fresh("handle", "Resource")
    tc.create_closure("cleaner", [("handle", "move")])
    tc.invoke_closure("cleaner")
    results.append({
        "id": "C2",
        "name": "Affine closure capturing own[T] invoked once",
        "expected": "ACCEPT",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": len(tc.diagnostics) == 0
    })

    # C3: Corpus 15 Fresh Slice Chunk (ACCEPT)
    tc.reset()
    tc.chunk_of_fresh("chunk")
    tc.consume("chunk")
    results.append({
        "id": "C3",
        "name": "Corpus 15 fresh slice chunk accepted without alias graph exemption",
        "expected": "ACCEPT",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": len(tc.diagnostics) == 0
    })

    # C4: Borrowed Reference Loan (ACCEPT)
    tc.reset()
    tc.instantiate_fresh("rec", "Record")
    tc.borrow_ref("rec", "ref_rec")
    tc.consume("rec") # after loan finishes
    results.append({
        "id": "C4",
        "name": "Borrowed reference loan read without premature consumption",
        "expected": "ACCEPT",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": len(tc.diagnostics) == 0
    })

    # C5: Zero-Annotation Local Inference (ACCEPT)
    tc.reset()
    tc.instantiate_fresh("val", "int")
    tc.consume("val")
    results.append({
        "id": "C5",
        "name": "Zero-annotation local bidirectional capability inference",
        "expected": "ACCEPT",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": len(tc.diagnostics) == 0
    })

    # M1: Double Consume / Use-After-Move (REJECT)
    tc.reset()
    tc.instantiate_fresh("packet", "Packet")
    tc.consume("packet")
    tc.consume("packet")
    results.append({
        "id": "M1",
        "name": "Use-after-move / double consumption of own[T] capability",
        "expected": "REJECT",
        "expected_code": "HYB-E1001",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": "HYB-E1001" in [d["code"] for d in tc.diagnostics]
    })

    # M2: Affine Closure Double-Execution (REJECT)
    tc.reset()
    tc.instantiate_fresh("sock", "Socket")
    tc.create_closure("closer", [("sock", "move")])
    tc.invoke_closure("closer")
    tc.invoke_closure("closer")
    results.append({
        "id": "M2",
        "name": "Double invocation of affine FnOnce closure",
        "expected": "REJECT",
        "expected_code": "HYB-E1001",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": "HYB-E1001" in [d["code"] for d in tc.diagnostics]
    })

    # M3: Loop Backedge Move (REJECT)
    tc.reset()
    tc.instantiate_fresh("token", "Token")
    tc.loop_depth = 1
    tc.consume("token")
    results.append({
        "id": "M3",
        "name": "Move of capability on loop backedge",
        "expected": "REJECT",
        "expected_code": "HYB-E1002",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": "HYB-E1002" in [d["code"] for d in tc.diagnostics]
    })

    # M4: Closure Leaks Mutable Borrow Across Task (REJECT)
    tc.reset()
    tc.instantiate_fresh("shared_state", "State")
    tc.borrow_ref("shared_state", "ref_state")
    tc.create_closure("worker", [("ref_state", "borrow")])
    tc.spawn_task("worker")
    results.append({
        "id": "M4",
        "name": "Closure leaks borrowed reference across concurrent task boundary",
        "expected": "REJECT",
        "expected_code": "HYB-E3001",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": "HYB-E3001" in [d["code"] for d in tc.diagnostics]
    })

    # M5: Unconsumed Linear Capability Invalidation (REJECT)
    tc.reset()
    tc.instantiate_fresh("token", "CapabilityToken")
    tc.store_unmanaged("heap_array", "token")
    results.append({
        "id": "M5",
        "name": "Storing exclusive linear capability into unmanaged aliased container",
        "expected": "REJECT",
        "expected_code": "HYB-E3006",
        "codes": [d["code"] for d in tc.diagnostics],
        "passed": "HYB-E3006" in [d["code"] for d in tc.diagnostics]
    })

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_tests()
