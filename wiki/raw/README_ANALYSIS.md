# MacOSWorld Lume Evaluation Pipeline - Complete Analysis Documentation

## Three-Part Deep Dive

This analysis provides a comprehensive exploration of the macosworld_lume project's evaluation pipeline, organized into three complementary documents:

### 1. **macosworld_lume_SUMMARY.md** ⭐ START HERE
**Quick Reference Guide** (~18 KB)
- System overview diagram
- File-by-file summaries (1-2 paragraphs each)
- Quick lookup tables
- State machine diagram
- Deployment parameter examples
- Distributed system design notes

**Use this for**: Quick lookups, high-level understanding, deployment parameters

---

### 2. **macosworld_lume_ANALYSIS.md** 📚 DETAILED REFERENCE
**Complete Technical Analysis** (~31 KB)
- Full content of all 5 files
- Complete function signatures
- Line-by-line control flow explanations
- All error handling patterns
- Data flow diagrams
- Architecture patterns and implications
- Supporting utilities documentation
- Distributed system design implications

**Use this for**: Understanding internals, planning modifications, distributed redesign

---

### 3. **macosworld_lume_ARCHITECTURE.md** 🏗️ DESIGN DEEP DIVE
**System Architecture & Design Patterns** (~15 KB)
- High-level architecture diagram
- Execution phase dependency chain
- VM backend architecture (Lume/VMware/AWS)
- File-based state machine
- Retry logic (4 hierarchical levels)
- Data flow for single task
- Error handling strategy
- Configuration customization points
- Scaling architecture (single vs distributed)
- 6 key design patterns with code examples

**Use this for**: System design decisions, optimization, scaling to distributed version

---

## Quick File Reference

### The Five Core Files Analyzed

```
1. run.py (150 lines)
   ├─ Outer loop supervisor
   ├─ 12-hour watchdog timer
   ├─ SIGINT handler for graceful shutdown
   └─ Socket-based IPC with testbench

2. testbench.py (180 lines)
   ├─ Task iteration engine
   ├─ Language combination handling
   ├─ Retry loop orchestration
   └─ Calls run_task() for each task

3. utils/run_task.py (390 lines)
   ├─ Single task execution pipeline
   ├─ 8-phase execution model
   ├─ Multi-backend VM support (Lume/VMware/AWS)
   └─ Try-finally cleanup guarantee

4. constants.py (42 lines)
   ├─ Configuration tables
   ├─ AMI lookups, golden VM mappings
   ├─ Init commands (env + eval)
   └─ Language abbreviation lookup

5. cleanup.py (45 lines)
   ├─ Incomplete task cleanup
   ├─ File-based state detection
   └─ Runs before each testbench cycle
```

---

## Execution Flow at a Glance

```
┌─────────────────────────────────────┐
│ run.py (OUTER LOOP - Supervisor)   │ Runs indefinitely
│ ├─ cleanup.py                       │ Remove failed tasks
│ ├─ all_tasks_completed() check      │ Exit if done
│ └─ testbench.py (subprocess)        │ Max 12 hours
│    ├─ For each language combo       │ EN, ZH, AR, etc
│    │  └─ For each task JSON         │ Load from disk
│    │     ├─ run_task() call         │ Execute 1 task
│    │     │  ├─ Phase 1: Env reset   │ Clone/revert/replace
│    │     │  ├─ Phase 2: SSH conn    │ Poll + connect
│    │     │  ├─ Phase 3: Init        │ Prep commands
│    │     │  ├─ Phase 4: Event inj   │ Background handler
│    │     │  ├─ Phase 5: Agent loop  │ Screenshot + decide
│    │     │  ├─ Phase 6: Event grade │ Eval distraction
│    │     │  ├─ Phase 7: Task grade  │ Run eval command
│    │     │  └─ Phase 8: Cleanup     │ VNC + Lume cleanup
│    │     └─ Save results to disk    │ eval_result.txt
│    └─ Send DONE to socket           │ Signal completion
└─────────────────────────────────────┘
        ↓
{base_save_dir}/ (Results stored here)
├─ sys_apps/
│  └─ task_uuid_en_en/
│     ├─ eval_result.txt
│     ├─ context/
│     └─ fail.flag (if failed)
└─ safety/
   └─ task_uuid_en_en/
      ├─ eval_result.txt
      ├─ distraction_result.txt
      ├─ context/
      └─ fail.flag (if failed)
```

---

## Key Design Decisions

### 1. **Multi-Level Retry Architecture**
- Task attempt (testbench.py)
- Environment reset (run_task Phase 1)
- Pre-command execution (run_task Phase 3)
- SSH connectivity (run_task Phase 2)

**Why**: Fault tolerance at multiple granularities

### 2. **File-Based State Machine**
- PENDING: No directory
- IN_PROGRESS: context/ exists, no .txt files
- EVAL_FAILED: eval_result.txt starts with "eval_failed"
- COMPLETED: eval_result.txt starts with integer
- FAILED: fail.flag marker file

**Why**: Distributed-ready without database

### 3. **Try-Finally Cleanup Guarantee**
```python
try:
    run_task_phases_1_through_7()
finally:
    remote_client.disconnect()
    lume_tools.stop_and_cleanup()
```

**Why**: No resource leaks even on hard failures

### 4. **Multi-Backend Strategy Pattern**
- Lume (macOS Apple Silicon): Clone golden VM
- VMware (local): Revert snapshot
- AWS EC2 (cloud): Replace root volume

**Why**: Single codebase, multiple platforms

### 5. **Socket-Based IPC (run.py ↔ testbench.py)**
```python
srv.accept()  # run.py waits
s.sendall(b"DONE")  # testbench signals
```

**Why**: Lightweight, no external dependencies

### 6. **Optional In-Process Events**
- Background SSH command handler
- Runs while agent executes
- Captures output for distraction evaluation

**Why**: Separate task focus from distraction resilience testing

---

## Scaling & Distribution Implications

### Current (Single-Machine)
```
run.py (Supervisor) → testbench.py (Sequential) → N × run_task()
Duration: O(N × avg_task_time)
```

### Proposed (Distributed)
```
Coordinator (Task Queue) → N × Worker (run_task)
Duration: O(N × avg_task_time / num_workers)

Key advantages:
- File-based state → no locks needed
- Independent tasks → perfect parallelization
- Idempotent cleanup → safe to retry anywhere
```

---

## For Planning Distributed Version

### Three Files to Study Most:
1. **run_task.py** - Core business logic (VM setup → agent loop → grading)
2. **completion_checker.py** - State detection logic (task completion criteria)
3. **cleanup.py** - Cleanup patterns (failure recovery)

### Key Extension Points:
1. Replace `testbench.py` loop with task queue consumer
2. Use NFS for shared `{base_save_dir}` (state storage)
3. Run multiple instances of task queue consumer
4. Keep `run_task()` unchanged (or minimal changes)

### What Doesn't Change:
- Phase 1-8 execution model
- File-based state machine
- Try-finally cleanup guarantee
- Retry logic (Level 2-4)

### What Changes:
- testbench.py: Sequential loop → Queue consumer
- run.py: Single supervisor → Multiple workers + coordinator
- IPC: Socket → Message queue (RabbitMQ, Redis, etc.)

---

## Testing Recommendations

### For Validation:
1. **Unit test**: Each phase in isolation (mock VMs)
2. **Integration test**: Full task with test VM
3. **Fault injection**: Simulate timeouts, SSH failures
4. **State recovery**: Kill at each phase, verify cleanup

### For Distributed Version:
1. **Worker crash simulation**: Kill mid-task, verify cleanup + requeue
2. **Concurrent execution**: 5 workers on same task queue
3. **File system consistency**: Multiple writers to eval_result.txt
4. **Cleanup idempotency**: Run cleanup multiple times

---

## Recommended Reading Order

**For Quick Understanding (15 min)**:
1. Start with System Overview diagram (SUMMARY.md)
2. Read File-by-File Summary (SUMMARY.md)
3. Skim Deployment Parameters (SUMMARY.md)

**For Implementation (1-2 hours)**:
1. Read High-Level Architecture (ARCHITECTURE.md)
2. Study Execution Phases (ARCHITECTURE.md)
3. Read run.py code + corresponding section (ANALYSIS.md)
4. Read testbench.py code + section (ANALYSIS.md)
5. Read run_task.py phases (ANALYSIS.md)

**For Distributed Redesign (2-3 hours)**:
1. Read all of ARCHITECTURE.md
2. Study Scaling Architecture section (ARCHITECTURE.md)
3. Read retry logic (ARCHITECTURE.md)
4. Read Task State Management (ARCHITECTURE.md)
5. Study distributed benefits section

**For Deep Dive (4+ hours)**:
1. Read all three documents sequentially
2. Cross-reference code with explanations
3. Study design patterns (ARCHITECTURE.md)
4. Map out distributed version in detail

---

## Files on Disk

All three documents are saved to:
```
~/Desktop/macosworld_lume_SUMMARY.md       (18 KB) - START HERE
~/Desktop/macosworld_lume_ANALYSIS.md      (31 KB) - Full reference
~/Desktop/macosworld_lume_ARCHITECTURE.md  (15 KB) - Design patterns
```

---

## Key Takeaway

The macosworld_lume system is a **well-engineered, production-grade evaluation pipeline** with:

✅ **Multi-level fault tolerance** - Recovers from transient failures
✅ **Scalable architecture** - Ready for distributed version
✅ **Clean abstractions** - Strategy pattern for VM backends
✅ **File-based state** - No database dependencies
✅ **Guaranteed cleanup** - Try-finally prevents resource leaks
✅ **Observable behavior** - State encoded in file presence

The design principles are ideal for a distributed version with minimal code changes.

