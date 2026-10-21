#!/usr/bin/env node
import crypto from 'crypto';

function sha256(str) {
  return crypto.createHash('sha256').update(str, 'utf8').digest('hex');
}

class Effect {
  constructor(kind, target, key = null, val = null, observable = true) {
    this.kind = kind;
    this.target = target;
    this.key = key;
    this.val = val;
    this.observable = observable;
  }
  equals(other) {
    return this.kind === other.kind &&
           this.target === other.target &&
           this.key === other.key &&
           this.val === other.val &&
           this.observable === other.observable;
  }
}

class Block {
  constructor(blockId, effects, terminator, targets = []) {
    this.blockId = blockId;
    this.effects = effects;
    this.terminator = terminator;
    this.targets = targets;
  }
}

class ProgramCFG {
  constructor(name, entry, blocks) {
    this.name = name;
    this.entry = entry;
    this.blocks = blocks;
  }
  computeTrace() {
    const trace = [];
    let curr = this.entry;
    const visited = new Set();
    while (this.blocks[curr]) {
      if (visited.has(curr)) throw new Error("Loop without inductive invariant");
      visited.add(curr);
      const b = this.blocks[curr];
      for (const eff of b.effects) {
        if (eff.observable) trace.push(eff);
      }
      if (b.terminator === 'return') break;
      curr = b.targets[0];
    }
    return trace;
  }
}

function validate(sourceIR, emittedGo, cert, actualSrc, actualGo) {
  const srcHash = sha256(actualSrc);
  const goHash = sha256(actualGo);

  if (cert.source_sha256 !== srcHash) {
    return { ok: false, error: 'Source digest mismatch' };
  }
  if (cert.emitted_go_sha256 !== goHash) {
    return { ok: false, error: 'Go digest mismatch' };
  }

  let irTrace, goTrace;
  try {
    irTrace = sourceIR.computeTrace();
    goTrace = emittedGo.computeTrace();
  } catch (e) {
    return { ok: false, error: e.message };
  }

  if (irTrace.length !== goTrace.length) {
    return { ok: false, error: `Trace length mismatch: ${irTrace.length} vs ${goTrace.length}` };
  }

  for (let i = 0; i < irTrace.length; i++) {
    if (!irTrace[i].equals(goTrace[i])) {
      return { ok: false, error: `Effect divergence at step ${i}: expected ${irTrace[i].kind}, got ${goTrace[i].kind}` };
    }
  }

  const requiredLoans = new Set(cert.open_loans || []);
  for (const [id, block] of Object.entries(emittedGo.blocks)) {
    if (block.terminator === 'return') {
      const committed = new Set(block.effects.filter(e => e.kind === 'SlotCommit').map(e => e.val));
      for (const loan of requiredLoans) {
        if (!committed.has(loan)) {
          return { ok: false, error: `Uncommitted loan ${loan} at return block ${id}` };
        }
      }
    }
  }

  return { ok: true, traceSteps: irTrace.length };
}

console.log("=== W-013 Translation Validator Test Suite ===");
let passed = 0;
let failed = 0;

function assertTest(name, result, expectedOk, expectedErrorSubstr = '') {
  if (result.ok === expectedOk) {
    if (!expectedOk && expectedErrorSubstr && !result.error.includes(expectedErrorSubstr)) {
      console.error(`[FAIL] ${name}: Expected error containing '${expectedErrorSubstr}', got '${result.error}'`);
      failed++;
    } else {
      console.log(`[PASS] ${name}`);
      passed++;
    }
  } else {
    console.error(`[FAIL] ${name}: Expected ok=${expectedOk}, got ok=${result.ok} (${result.error || 'no error'})`);
    failed++;
  }
}

// P1: Straight-line slot mutation
{
  const src = "fn mutate(m: &mut map[int]int) { m[0]++ }";
  const go = "func mutate(m map[int]int) { v := m[0]; v++; m[0] = v }";
  const ir = new ProgramCFG("p1", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v")
    ], "return")
  });
  const goCfg = new ProgramCFG("p1_go", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("PureLocalAssign", "v", null, null, false),
      new Effect("SlotCommit", "m", 0, "v")
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go), open_loans: ["v"] };
  assertTest("P1: Straight-line slot mutation validated with pure stuttering steps", validate(ir, goCfg, cert, src, go), true);
}

// P2: Early return with clean store-back
{
  const src = "fn early(m: &mut map[int]int, cond: bool) { m[0]++; if cond { return }; m[1]++ }";
  const go = "func early(m map[int]int, cond bool) { v := m[0]; v++; m[0] = v; if cond { return }; w := m[1]; w++; m[1] = w }";
  const ir = new ProgramCFG("p2", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v")
    ], "return")
  });
  const goCfg = new ProgramCFG("p2_go", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v")
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go), open_loans: ["v"] };
  assertTest("P2: Early return path with complete store-back succeeds", validate(ir, goCfg, cert, src, go), true);
}

// P3: Branch join preservation
{
  const src = "fn branch_join(m: &mut map[int]int) { ... }";
  const go = "func branch_join(m map[int]int) { ... }";
  const ir = new ProgramCFG("p3", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v"),
      new Effect("ObservableCall", "log", null, null, true)
    ], "return")
  });
  const goCfg = new ProgramCFG("p3_go", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v"),
      new Effect("ObservableCall", "log", null, null, true)
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go), open_loans: ["v"] };
  assertTest("P3: Branch join effect sequence validated", validate(ir, goCfg, cert, src, go), true);
}

// P4: Multiple independent slot loans
{
  const src = "fn multi(m: &mut map[int]int) { m[0]++; m[1]++ }";
  const go = "func multi(m map[int]int) { m[0]++; m[1]++ }";
  const ir = new ProgramCFG("p4", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v1"),
      new Effect("SlotCommit", "m", 0, "v1"),
      new Effect("SlotBorrow", "m", 1, "v2"),
      new Effect("SlotCommit", "m", 1, "v2")
    ], "return")
  });
  const goCfg = new ProgramCFG("p4_go", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v1"),
      new Effect("SlotCommit", "m", 0, "v1"),
      new Effect("SlotBorrow", "m", 1, "v2"),
      new Effect("SlotCommit", "m", 1, "v2")
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go), open_loans: ["v1", "v2"] };
  assertTest("P4: Multiple independent sequential slot loans pass", validate(ir, goCfg, cert, src, go), true);
}

// F1: Reordered commit past alias observation (The MyTH-zyxeon witness)
{
  const src = "fn witness(m: &mut map[int]int) { m[0]++; alias := m; check(alias[0]) }";
  const go_broken = "func witness(m map[int]int) { v := m[0]; v++; alias := m; check(alias[0]); m[0] = v }";
  const ir = new ProgramCFG("f1", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v"),
      new Effect("ObservableCall", "check", null, null, true)
    ], "return")
  });
  const goCfg = new ProgramCFG("f1_go", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("ObservableCall", "check", null, null, true),
      new Effect("SlotCommit", "m", 0, "v")
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go_broken), open_loans: ["v"] };
  assertTest("F1: Reject delayed store-back across alias observation (MyTH-zyxeon witness)",
    validate(ir, goCfg, cert, src, go_broken), false, "Effect divergence");
}

// F2: Dropped store-back on early return
{
  const src = "fn early_leak(m: &mut map[int]int, cond: bool) { m[0]++; if cond { return } }";
  const go_broken = "func early_leak(m map[int]int, cond bool) { v := m[0]; v++; if cond { return }; m[0] = v }";
  const ir = new ProgramCFG("f2", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v"),
      new Effect("SlotCommit", "m", 0, "v")
    ], "return")
  });
  const goCfg = new ProgramCFG("f2_go", "b0", {
    "b0": new Block("b0", [
      new Effect("SlotBorrow", "m", 0, "v")
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go_broken), open_loans: ["v"] };
  assertTest("F2: Reject early exit that drops slot-loan store-back",
    validate(ir, goCfg, cert, src, go_broken), false, "Trace length mismatch");
}

// F3: Reordered observable side-effects
{
  const src = "fn reorder() { callA(); callB() }";
  const go_broken = "func reorder() { callB(); callA() }";
  const ir = new ProgramCFG("f3", "b0", {
    "b0": new Block("b0", [
      new Effect("ObservableCall", "callA", null, null, true),
      new Effect("ObservableCall", "callB", null, null, true)
    ], "return")
  });
  const goCfg = new ProgramCFG("f3_go", "b0", {
    "b0": new Block("b0", [
      new Effect("ObservableCall", "callB", null, null, true),
      new Effect("ObservableCall", "callA", null, null, true)
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go_broken), open_loans: [] };
  assertTest("F3: Reject reordered observable external calls",
    validate(ir, goCfg, cert, src, go_broken), false, "Effect divergence");
}

// F4: Duplicated side-effect
{
  const src = "fn duplicate() { send(ch, 42) }";
  const go_broken = "func duplicate() { send(ch, 42); send(ch, 42) }";
  const ir = new ProgramCFG("f4", "b0", {
    "b0": new Block("b0", [
      new Effect("ChannelSend", "ch", null, "42", true)
    ], "return")
  });
  const goCfg = new ProgramCFG("f4_go", "b0", {
    "b0": new Block("b0", [
      new Effect("ChannelSend", "ch", null, "42", true),
      new Effect("ChannelSend", "ch", null, "42", true)
    ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256(go_broken), open_loans: [] };
  assertTest("F4: Reject duplicated side-effect in emitted output",
    validate(ir, goCfg, cert, src, go_broken), false, "Trace length mismatch");
}

// F5: Stale / tampered certificate hash
{
  const src = "fn auth() { doWork() }";
  const go_tampered = "func auth() { maliciousInjection(); doWork() }";
  const ir = new ProgramCFG("f5", "b0", {
    "b0": new Block("b0", [ new Effect("ObservableCall", "doWork", null, null, true) ], "return")
  });
  const goCfg = new ProgramCFG("f5_go", "b0", {
    "b0": new Block("b0", [ new Effect("ObservableCall", "doWork", null, null, true) ], "return")
  });
  const cert = { source_sha256: sha256(src), emitted_go_sha256: sha256("func auth() { doWork() }"), open_loans: [] };
  assertTest("F5: Reject stale or tampered certificate digest",
    validate(ir, goCfg, cert, src, go_tampered), false, "Go digest mismatch");
}

console.log(`\nResults: ${passed} passed, ${failed} failed.`);
if (failed > 0) process.exit(1);
