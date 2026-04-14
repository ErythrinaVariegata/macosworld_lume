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
