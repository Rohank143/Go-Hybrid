#!/usr/bin/env node
import { execSync } from 'child_process';
import path from 'path';

console.log('Running W-002 Type-Carried Ownership Capabilities Verification Suite...');
try {
  const output = execSync('python engine.py', { cwd: import.meta.dirname, encoding: 'utf8' });
  const results = JSON.parse(output);
  console.log(`Successfully executed ${results.length} controls:`);
  let allPassed = true;
  for (const r of results) {
    console.log(`[${r.passed ? 'PASS' : 'FAIL'}] ${r.id}: ${r.name} -> Expected: ${r.expected}, Codes: ${r.codes.join(', ') || 'none'}`);
    if (!r.passed) allPassed = false;
  }
  if (allPassed) {
    console.log('\nVERDICT: PASS — All 10/10 pre-registered controls verified.');
  } else {
    console.log('\nVERDICT: FAIL');
    process.exit(1);
  }
} catch (e) {
  console.error('Error running engine.py:', e);
  process.exit(1);
}
