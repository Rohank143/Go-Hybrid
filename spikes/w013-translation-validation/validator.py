#!/usr/bin/env python3
"""
spikes/w013-translation-validation/validator.py
Standalone translation validation engine for Go-Hybrid lowered output.
Verifies simulation equivalence between checked-effect IR and emitted Go CFG.
"""

import hashlib
import json
import sys
from typing import List, Dict, Optional, Tuple, Set

class Effect:
    def __init__(self, kind: str, target: str, key: Optional[int] = None, val: Optional[str] = None, observable: bool = True):
        self.kind = kind
        self.target = target
        self.key = key
        self.val = val
        self.observable = observable

    def __eq__(self, other):
        if not isinstance(other, Effect):
            return False
        return (self.kind, self.target, self.key, self.val, self.observable) == \
               (other.kind, other.target, other.key, other.val, other.observable)

    def __repr__(self):
        return f"{self.kind}({self.target}, key={self.key}, val={self.val})"


class Block:
    def __init__(self, block_id: str, effects: List[Effect], terminator: str, targets: List[str] = None):
        self.block_id = block_id
        self.effects = effects
        self.terminator = terminator
        self.targets = targets or []


class ProgramCFG:
    def __init__(self, name: str, entry: str, blocks: Dict[str, Block]):
        self.name = name
        self.entry = entry
        self.blocks = blocks

    def compute_observable_trace(self) -> List[Effect]:
        trace = []
        curr = self.entry
        visited = set()
        while curr in self.blocks:
            if curr in visited:
                raise ValueError("Unbounded loop without inductive certificate")
            visited.add(curr)
            b = self.blocks[curr]
            for eff in b.effects:
                if eff.observable:
                    trace.append(eff)
            if b.terminator == "return":
                break
            elif b.terminator in ("jump", "branch") and b.targets:
                curr = b.targets[0]
            else:
                break
        return trace


class TranslationValidator:
    @staticmethod
    def sha256_bytes(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def validate(source_ir: ProgramCFG,
                 emitted_go: ProgramCFG,
                 cert_json: dict,
                 actual_source_code: str,
                 actual_go_code: str) -> Tuple[bool, str]:
        src_digest = TranslationValidator.sha256_bytes(actual_source_code.encode("utf-8"))
        go_digest = TranslationValidator.sha256_bytes(actual_go_code.encode("utf-8"))

        if cert_json.get("source_sha256") != src_digest:
            return False, f"Source digest mismatch: cert={cert_json.get('source_sha256')[:8]} actual={src_digest[:8]}"

        if cert_json.get("emitted_go_sha256") != go_digest:
            return False, f"Emitted Go digest mismatch: cert={cert_json.get('emitted_go_sha256')[:8]} actual={go_digest[:8]}"

        try:
            ir_trace = source_ir.compute_observable_trace()
            go_trace = emitted_go.compute_observable_trace()
        except ValueError as e:
            return False, f"Unsupported control flow: {e}"

        if len(ir_trace) != len(go_trace):
            return False, f"Trace length mismatch: IR has {len(ir_trace)} effects, Go has {len(go_trace)}"

        for i, (e_ir, e_go) in enumerate(zip(ir_trace, go_trace)):
            if e_ir != e_go:
                return False, f"Effect divergence at step {i}: expected {e_ir}, got {e_go}"

        required_loans: Set[str] = set(cert_json.get("open_loans", []))
        for b_id, block in emitted_go.blocks.items():
            if block.terminator == "return":
                committed = {eff.val for eff in block.effects if eff.kind == "SlotCommit"}
                uncommitted = required_loans - committed
                if uncommitted:
                    return False, f"Exit block '{b_id}' leaks uncommitted loans: {uncommitted}"

        return True, "VALIDATION_PASSED"

if __name__ == "__main__":
    print("TranslationValidator engine initialized cleanly.")
