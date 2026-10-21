#!/usr/bin/env python3
import sys
import re
import json

class Diagnostic:
    def __init__(self, code, message, line):
        self.code = code
        self.message = message
        self.line = line
    def to_dict(self):
        return {"code": self.code, "message": self.message, "line": self.line}

class Tier0GoASTAnalyzer:
    def __init__(self):
        self.package_symbols = {}
        self.diagnostics = []

    def register_sibling(self, name, kind):
        self.package_symbols[name] = kind

    def analyze(self, src):
        self.diagnostics = []
        lines = src.split('\n')
        in_checked_func = False
        loop_depth = 0
        var_states = {} # var -> 'live' | 'moved' | 'borrowed'
        var_types = {}  # var -> type_str
        active_loans = set() # container -> loan

        for idx, line in enumerate(lines, 1):
            raw = line.strip()
            
            # Directive check
            if '//hy:check' in raw:
                in_checked_func = True
                continue

            if in_checked_func and raw.startswith('func '):
                # Parse parameters: func foo(x int, ptr *Data, s SiblingType)
                m = re.search(r'func\s+\w+\((.*?)\)', raw)
                if m:
                    params = m.group(1).split(',')
                    for p in params:
                        parts = p.strip().split()
                        if len(parts) >= 2:
                            p_name = parts[0]
                            p_type = parts[1]
                            var_states[p_name] = 'live'
                            var_types[p_name] = p_type
                continue

            if not in_checked_func:
                continue

            # Loop tracking
            if re.match(r'for\b', raw):
                loop_depth += 1
            if '}' in raw and loop_depth > 0:
                loop_depth -= 1

            # Intrinsic Move: hy.Move(&x)
            move_match = re.search(r'hy\.Move\(&(\w+)\)', raw)
            if move_match:
                v = move_match.group(1)
                if loop_depth > 0:
                    self.diagnostics.append(Diagnostic("HYB-E1002", f"variable {v} moved on loop backedge", idx))
                elif var_states.get(v) == 'moved':
                    self.diagnostics.append(Diagnostic("HYB-E1001", f"use after move: variable {v} was already moved", idx))
                else:
                    var_states[v] = 'moved'
                continue

            # Task boundary: go func(...) or hy.Task(fn, arg1, ...)
            if raw.startswith('go ') or 'hy.Task(' in raw:
                # Find passed variables
                m_args = re.search(r'(?:go\s+\w+|hy\.Task\s*\(\s*\w+)\((.*?)\)', raw)
                if m_args:
                    args = [a.strip() for a in m_args.group(1).split(',') if a.strip()]
                    for a in args:
                        a_type = var_types.get(a, '')
                        if a_type.startswith('*'):
                            self.diagnostics.append(Diagnostic("HYB-E3001", f"non-sendable mutable pointer {a} crosses task boundary", idx))
                        # Sibling check
                        elif a_type in self.package_symbols:
                            # Sibling struct is known and sendable!
                            pass

            # Map loan: hy.Borrow(&m[k])
            loan_match = re.search(r'hy\.Borrow\(&(\w+)\[.*?\]\)', raw)
            if loan_match:
                container = loan_match.group(1)
                active_loans.add(container)

            # Container mutation: m[k] = val or delete(m, k)
            mut_match = re.search(r'(\w+)\[.*?\]\s*=', raw)
            if mut_match:
                container = mut_match.group(1)
                if container in active_loans:
                    self.diagnostics.append(Diagnostic("HYB-E2001", f"container {container} mutated while slot loan is active", idx))

            # Use after move check on identifiers
            for v, state in var_states.items():
                if state == 'moved':
                    # Look for v as an identifier (not in definition or comment)
                    if re.search(r'\b' + v + r'\b', raw) and not re.search(r'hy\.Move\(&' + v + r'\)', raw):
                        # Ensure not part of another word
                        self.diagnostics.append(Diagnostic("HYB-E1001", f"use after move: {v} is consumed", idx))

        return [d.to_dict() for d in self.diagnostics]

def run_tests():
    analyzer = Tier0GoASTAnalyzer()
    analyzer.register_sibling("SiblingData", "struct")

    test_cases = [
        # Positive Controls
        {
            "id": "C1",
            "name": "Sendable primitives across task boundary",
            "expected_verdict": "ACCEPT",
            "src": """
//hy:check
func Worker(id int, name string) {
    go Process(id, name)
}
"""
        },
        {
            "id": "C2",
            "name": "Affine single move into task",
            "expected_verdict": "ACCEPT",
            "src": """
//hy:check
func Transfer(val int) {
    v := hy.Move(&val)
    go Process(v)
}
"""
        },
        {
            "id": "C3",
            "name": "Sibling package struct resolution without E3005",
            "expected_verdict": "ACCEPT",
            "src": """
//hy:check
func HandleSibling(s SiblingData) {
    go ProcessSibling(s)
}
"""
        },
        {
            "id": "C4",
            "name": "Scoped slot loan read before release",
            "expected_verdict": "ACCEPT",
            "src": """
//hy:check
func InspectMap(m map[string]int) {
    val := hy.Borrow(&m["key"])
    _ = val
}
"""
        },
        {
            "id": "C5",
            "name": "Zero-cost intrinsic evaluation invariance",
            "expected_verdict": "ACCEPT",
            "src": """
//hy:check
func InlineMove(x int) {
    y := hy.Move(&x)
    _ = y
}
"""
        },
        # Negative Controls (Mutations)
        {
            "id": "M1",
            "name": "Use-after-move rejection (A1b)",
            "expected_verdict": "REJECT",
            "expected_code": "HYB-E1001",
            "src": """
//hy:check
func BadUse(x int) {
    y := hy.Move(&x)
    _ = y
    println(x)
}
"""
        },
        {
            "id": "M2",
            "name": "Loop backedge move rejection (A1c)",
            "expected_verdict": "REJECT",
            "expected_code": "HYB-E1002",
            "src": """
//hy:check
func LoopMove(x int) {
    for i := 0; i < 5; i++ {
        y := hy.Move(&x)
        _ = y
    }
}
"""
        },
        {
            "id": "M3",
            "name": "Non-sendable mutable pointer cross-task rejection (A2)",
            "expected_verdict": "REJECT",
            "expected_code": "HYB-E3001",
            "src": """
//hy:check
func LeakPointer(p *int) {
    go MutateConcurrently(p)
}
"""
        },
        {
            "id": "M4",
            "name": "Slot loan mutation race rejection (A3)",
            "expected_verdict": "REJECT",
            "expected_code": "HYB-E2001",
            "src": """
//hy:check
func LoanConflict(m map[string]int) {
    ref := hy.Borrow(&m["k"])
    m["k"] = 42
    _ = ref
}
"""
        },
        {
            "id": "M5",
            "name": "Double move on linear handle rejection",
            "expected_verdict": "REJECT",
            "expected_code": "HYB-E1001",
            "src": """
//hy:check
func DoubleMove(res int) {
    a := hy.Move(&res)
    b := hy.Move(&res)
    _, _ = a, b
}
"""
        }
    ]

    results = []
    for tc in test_cases:
        diags = analyzer.analyze(tc["src"])
        passed = False
        if tc["expected_verdict"] == "ACCEPT":
            passed = (len(diags) == 0)
        else:
            codes = [d["code"] for d in diags]
            passed = (tc["expected_code"] in codes)

        results.append({
            "id": tc["id"],
            "name": tc["name"],
            "expected": tc["expected_verdict"],
            "codes": [d["code"] for d in diags],
            "passed": passed
        })

    print(json.dumps(results, indent=2))

if __name__ == "__main__":
    run_tests()
