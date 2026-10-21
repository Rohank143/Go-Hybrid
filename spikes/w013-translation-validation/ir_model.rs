// spikes/w013-translation-validation/ir_model.rs
// Bounded formal feasibility model for Wildcard Bounty #345 (W-013)
// Translation validation of lowered Go against a checked-effect IR.

use std::collections::{BTreeMap, BTreeSet};

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct LocalId(pub u32);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct HeapId(pub u32);

#[derive(Clone, Copy, Debug, Eq, PartialEq, Ord, PartialOrd)]
pub struct BlockId(pub u32);

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Effect {
    PureLocalAssign { target: LocalId },
    SlotBorrow { map: HeapId, key: i64, temp: LocalId },
    SlotCommit { map: HeapId, key: i64, val: LocalId },
    ObservableCall { name: &'static str, args: Vec<LocalId> },
    ChannelSend { chan: HeapId, val: LocalId },
    ChannelRecv { chan: HeapId, target: LocalId },
}

impl Effect {
    pub fn is_observable(&self) -> bool {
        match self {
            Effect::PureLocalAssign { .. } => false,
            Effect::SlotBorrow { .. } => true,
            Effect::SlotCommit { .. } => true,
            Effect::ObservableCall { .. } => true,
            Effect::ChannelSend { .. } | Effect::ChannelRecv { .. } => true,
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum Terminator {
    Return(Option<LocalId>),
    Branch { cond: LocalId, then_block: BlockId, else_block: BlockId },
    Jump(BlockId),
}

#[derive(Clone, Debug)]
pub struct IRBlock {
    pub id: BlockId,
    pub effects: Vec<Effect>,
    pub terminator: Terminator,
}

#[derive(Clone, Debug)]
pub struct CheckedEffectIR {
    pub name: String,
    pub blocks: BTreeMap<BlockId, IRBlock>,
    pub entry: BlockId,
}

#[derive(Clone, Debug)]
pub struct ReconstructedGoCFG {
    pub name: String,
    pub blocks: BTreeMap<BlockId, IRBlock>,
    pub entry: BlockId,
}

#[derive(Clone, Debug)]
pub struct Certificate {
    pub source_digest: [u8; 32],
    pub emitted_go_digest: [u8; 32],
    pub active_loan_invariants: BTreeSet<LocalId>,
}

#[derive(Debug, PartialEq, Eq)]
pub enum ValidationError {
    DigestMismatch,
    TraceDivergence { step: usize, expected: String, actual: String },
    UncommittedLoanAtExit { loan: LocalId },
    ReorderedCommitAcrossObservation { slot: HeapId },
    UnsupportedConstruct(&'static str),
}

pub struct SimulationValidator;

impl SimulationValidator {
    pub fn validate(
        ir: &CheckedEffectIR,
        go: &ReconstructedGoCFG,
        cert: &Certificate,
        actual_source_digest: &[u8; 32],
        actual_go_digest: &[u8; 32],
    ) -> Result<usize, ValidationError> {
        if cert.source_digest != *actual_source_digest || cert.emitted_go_digest != *actual_go_digest {
            return Err(ValidationError::DigestMismatch);
        }
        let ir_trace = Self::collect_observable_trace(ir)?;
        let go_trace = Self::collect_observable_trace(go)?;

        if ir_trace.len() != go_trace.len() {
            return Err(ValidationError::TraceDivergence {
                step: std::cmp::min(ir_trace.len(), go_trace.len()),
                expected: format!("Trace length {}", ir_trace.len()),
                actual: format!("Trace length {}", go_trace.len()),
            });
        }

        for (idx, (e_ir, e_go)) in ir_trace.iter().zip(go_trace.iter()).enumerate() {
            if e_ir != e_go {
                return Err(ValidationError::TraceDivergence {
                    step: idx,
                    expected: format!("{:?}", e_ir),
                    actual: format!("{:?}", e_go),
                });
            }
        }

        Self::verify_loan_obligations(go, cert)?;
        Ok(ir_trace.len())
    }

    fn collect_observable_trace(ir: &CheckedEffectIR) -> Result<Vec<Effect>, ValidationError> {
        let mut trace = Vec::new();
        let mut curr = ir.entry;
        let mut visited = BTreeSet::new();

        while let Some(block) = ir.blocks.get(&curr) {
            if !visited.insert(curr) {
                return Err(ValidationError::UnsupportedConstruct("Loop invariants require inductive certificates"));
            }
            for eff in &block.effects {
                if eff.is_observable() {
                    trace.push(eff.clone());
                }
            }
            match &block.terminator {
                Terminator::Jump(next) => curr = *next,
                Terminator::Return(_) => break,
                Terminator::Branch { then_block, .. } => curr = *then_block,
            }
        }
        Ok(trace)
    }

    fn verify_loan_obligations(go: &ReconstructedGoCFG, cert: &Certificate) -> Result<(), ValidationError> {
        for block in go.blocks.values() {
            if let Terminator::Return(_) = block.terminator {
                let mut active_loans = cert.active_loan_invariants.clone();
                for eff in &block.effects {
                    if let Effect::SlotCommit { val, .. } = eff {
                        active_loans.remove(val);
                    }
                }
                if let Some(leaked) = active_loans.iter().next() {
                    return Err(ValidationError::UncommittedLoanAtExit { loan: *leaked });
                }
            }
        }
        Ok(())
    }
}
