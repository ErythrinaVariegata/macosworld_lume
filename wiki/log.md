Chronological record of wiki operations.
---

## [2026-04-14] ingest | Initial wiki creation

Bootstrapped 3-layer wiki from 8 raw source documents created during Lume migration work (Apr 2026). Consolidated overlapping content into 6 topic pages:

- **architecture.md** ← PROJECT_OVERVIEW.md + code analysis
- **lume-backend.md** ← LUME_ANALYSIS.md + LUME_QUICK_REFERENCE.md + code
- **grading.md** ← OSASCRIPT_GRADING_ANALYSIS.md + TIMEOUT_FIX_NOTES.md + code
- **agents.md** ← code analysis (tione.py, qwen.py, uitars.py)
- **task-format.md** ← task JSON files + code analysis
- **decisions.md** ← session history, code comments

Raw sources preserved in `wiki/raw/` as immutable artifacts.

## [2026-04-14] ingest | TCC app coverage fix

Added 4 missing apps to prepare_golden_vm.sh and lume_utils.py PROBES:
Automator, Xcode, Calendar, QuickTime Player.
Discovered by scanning all 221 task JSONs for `tell application` patterns in grading_command fields.

## [2026-04-14] ingest | VM limit diagnosis

Root cause of persistent `lume run` failures: macOS Virtualization.framework caps concurrent VMs. Stale `lume run` processes from previous crashed sessions consumed all slots. Fix: kill orphaned processes before starting new VMs. Documented in [lume-backend](lume-backend.md) failure modes.

## [2026-04-15] ingest | Pipeline analysis documents consolidation

Moved 5 top-level generated analysis files (macosworld_lume_ANALYSIS.md, macosworld_lume_ARCHITECTURE.md, macosworld_lume_SUMMARY.md, README_ANALYSIS.md, START_HERE.md) to `wiki/raw/` as immutable sources.

Extracted unique content into wiki pages:
- **architecture.md** — added retry hierarchy (4 levels), error classification table, file-based state machine diagram
- **decisions.md** — added 5 new entries: strategy pattern for VM backends, file-based state, hierarchical retry, try-finally cleanup guarantee, async event injection
- **pipeline-reference.md** (new) — CLI parameters, function signatures, deployment examples, supporting utilities reference
- **scaling.md** (new) — single-machine vs distributed architecture, extension points, future monitoring metrics
