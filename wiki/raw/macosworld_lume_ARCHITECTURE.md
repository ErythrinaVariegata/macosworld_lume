# MacOSWorld Lume - System Architecture & Design Patterns

## High-Level Architecture

```
ENTRY POINT
    │
    ├─ run.py (150 lines)
    │   ├─ Responsibility: Outer loop supervisor
    │   ├─ Lifespan: Runs indefinitely (12-hour restart cycles)
    │   ├─ Features: Watchdog timeout, SIGINT handling, cleanup orchestration
    │   └─ IPC: Socket-based (127.0.0.1:random_port)
    │
    └─► testbench.py (180 lines)
        ├─ Responsibility: Task iteration & dispatch
        ├─ Lifespan: Runs until all tasks done (hours to days)
        ├─ Features: Language combination handling, retry logic
        ├─ IPC: Socket "DONE" message back to run.py
        │
        └─► run_task() (390 lines)
            ├─ Responsibility: Single task execution pipeline
            ├─ Lifespan: Runs per task (minutes)
            ├─ Features: 8-phase execution, multi-backend VM support
            └─ Output: eval_result.txt, distraction_result.txt, context/
```

---

## Execution Phases

### Phase Dependency Chain

```
run_task() {

  PHASE 1: Environment Reset
  ├─ Lume Clone (3 retries)
  ├─ VMware Revert (5 retries)
  └─ AWS Replace (polling)
     │
     └─► PHASE 2: SSH Connection
         ├─ Poll SSH availability (timeout-based)
         ├─ VNC setup (Lume/VMware/AWS)
         └─ Connection established
            │
            └─► PHASE 3: Environment Initialization
                ├─ env_init_command: Crash popup handling
                ├─ pre_command: Task-specific prep (configurable retries)
                └─ Environment ready
                   │
                   └─► PHASE 4: Optional Event Injection
                       ├─ AsyncSSHCommandHandler setup
                       ├─ (Will run at specific timestep)
                       └─ Ready for agent
                          │
                          └─► PHASE 5: Agent Loop
                              ├─ Sleep 5s settling
                              ├─ FOR step = 1 to max_steps:
                              │   ├─ Inject event if timestep matches
                              │   ├─ Screenshot capture
                              │   ├─ Agent decision (with timeout)
                              │   ├─ Execute action on GUI
                              │   └─ IF status != "unfinished" → break
                              ├─ Save conversation history
                              └─ Agent complete
                                 │
                                 └─► PHASE 6: In-Process Event Grading
                                     ├─ End background command
                                     ├─ Parse stdout/stderr
                                     ├─ Match against gold/distraction
                                     └─ Save distraction_result.txt
                                        │
                                        └─► PHASE 7: Task Grading
                                            ├─ eval_init_command: Exit fullscreen
                                            ├─ Run grading_command
                                            ├─ Parse result (int or error)
                                            └─ Save eval_result.txt
                                               │
                                               └─► PHASE 8: Cleanup (finally)
                                                   ├─ VNC disconnect
                                                   └─ Lume VM stop
}
```

---

## VM Backend Architecture

### Backend Selection Strategy

```
IF lume_golden_vm provided:
    ├─ BACKEND: Lume (macOS native, Apple Silicon)
    ├─ STARTUP: Clone from golden VM template
    ├─ RESET: Instant cloning (highly efficient)
    ├─ LANGUAGES: Supports language-specific golden VMs
    └─ CLEANUP: VM deletion + network cleanup

ELIF vmx_path provided:
    ├─ BACKEND: VMware (local or remote)
    ├─ STARTUP: Revert to snapshot
    ├─ RESET: Copy-on-write from snapshot
    ├─ LANGUAGES: Snapshot per language
    └─ CLEANUP: N/A (VM still running)

ELSE (default):
    ├─ BACKEND: AWS EC2 (cloud-native)
    ├─ STARTUP: Replace root volume from AMI
    ├─ RESET: Full volume replacement
    ├─ LANGUAGES: AMI per language
    └─ CLEANUP: N/A (instance still running)
```

### Retry Strategy per Backend

| Backend | Phase | Retries | Timeout | Strategy |
|---------|-------|---------|---------|----------|
| Lume | Clone + Start | 3 | snapshot_recovery_timeout | Backoff + full cleanup |
| VMware | Revert | 5 | snapshot_recovery_timeout | Exponential backoff |
| AWS | Replace Volume | ∞ | snapshot_recovery_timeout | Polling |
| All | SSH Connect | ∞ | snapshot_recovery_timeout | 10s poll interval |

---

## Task State Management

### File-Based State Machine

```
{base_save_dir}/{category}/{uuid}_{task_lang}_{env_lang}/
│
├─ NO FILES EXIST
│   └─ State: PENDING (never started)
│       └─ Action: testbench.py will execute
│
├─ context/ EXISTS, NO .txt
│   └─ State: IN_PROGRESS (started but not finished)
│       └─ Action: cleanup.py will delete (failed)
│       └─ testbench.py will retry (task_max_attempts)
│
├─ context/ + eval_result.txt + first_line="eval_failed"
│   └─ State: EVAL_FAILED (execution succeeded, grading failed)
│       └─ Action: cleanup.py will delete
│       └─ testbench.py will retry
│
├─ context/ + eval_result.txt + first_line=<integer>
│   └─ State: COMPLETED (success)
│       └─ Action: testbench.py will skip (already done)
│
├─ context/ + distraction_result.txt
│   └─ State: DISTRACTION_DONE (only for "safety" category)
│       └─ Action: completion_checker.py requires both files
│
└─ fail.flag
    └─ State: FAILED (all retries exhausted)
        └─ Action: cleanup.py will delete
        └─ testbench.py will retry on next cycle
```

---

## Retry Logic Architecture

### Hierarchical Retry Levels

```
LEVEL 1: Task Attempt (testbench.py)
    FOR task_attempt = 1 to task_max_attempts:
        │
        ├─ ON SUCCESS → break (proceed to next task)
        ├─ ON TIMEOUT → continue (try again)
        └─ ON EXCEPTION → continue (try again)
    
    ├─ ALL FAILED → create fail.flag
    │
    └─ NEXT RUN.PY CYCLE:
        └─ cleanup.py removes fail.flag
        └─ testbench.py re-executes (LEVEL 1 reset)

LEVEL 2: Environment Reset (run_task Phase 1)
    Lume:   3 retries with full VM cleanup between attempts
    VMware: 5 retries with exponential backoff
    AWS:    Infinite polling (until timeout)

LEVEL 3: Pre-Command (run_task Phase 3)
    FOR trial = 1 to pre_command_max_trials:
        ├─ SSH execute pre_command
        ├─ ON SUCCESS → proceed
        └─ ON FAILURE → retry
    
    IF force_error_free_prep AND failed:
        └─ raise RuntimeError (hard fail)

LEVEL 4: SSH Connectivity (run_task Phase 2)
    WHILE connected == False:
        ├─ Check SSH port
        ├─ IF available → establish connection
        ├─ IF timeout → raise TimeoutError
        └─ ELSE sleep(10) + retry
```

### Retry Decision Tree

```
IF TimeoutException:
    ├─ Caught by testbench.py
    ├─ Task attempt counter increments
    └─ RETRY if task_attempt < task_max_attempts

ELIF Exception (other):
    ├─ Caught by testbench.py
    ├─ Logged as error
    └─ RETRY if task_attempt < task_max_attempts

IF task_attempt == task_max_attempts AND still_failed:
    ├─ Create fail.flag file
    ├─ Add to incomplete_task_list
    └─ MOVE TO NEXT TASK (testbench.py loop continues)

ON NEXT run.py CYCLE:
    ├─ cleanup.py finds fail.flag
    ├─ Deletes entire task directory
    └─ testbench.py retries from PENDING (LEVEL 1 reset)
```

---

## Data Flow: Single Task Execution

```
INPUT:
  task_dict (JSON-loaded):
  ├─ id: UUID
  ├─ task: {en: "description", zh: "description", ...}
  ├─ snapshot: {en: "snapshot_name_en", zh: "snapshot_name_zh", ...}
  ├─ grading_command: "bash script to grade"
  ├─ pre_command: [optional] "prep script"
  ├─ in_process: [optional] (command, timestep, gold_elements, distracting_elements)
  ├─ before_action_delay_seconds: [optional]
  ├─ before_grading_delay_seconds: [optional]
  ├─ force_error_free_prep: [optional] boolean
  └─ force_ec2: [optional] boolean

PROCESSING:
  Phase 1: env_language ──► snapshot_name ──► ami_id/golden_vm_name
  Phase 3: pre_command[env_language] ──► SSH execution
  Phase 5: task_language ──► task_dict['task'][task_language]
  Phase 7: grading_command ──► evaluator.run_command()

OUTPUT:
  {save_dir}/
  ├─ eval_result.txt
  │   └─ [OPTIONAL] "eval_failed\n"
  │   └─ <integer_score>
  │
  ├─ distraction_result.txt (only if in_process task)
  │   └─ <status>
  │   └─ <log details>
  │
  ├─ context/
  │   └─ (agent conversation history)
  │
  └─ fail.flag (only if execution failed)
      └─ (empty file, presence = failure marker)
```

---

## Error Handling Strategy

### Error Classification

```
CRITICAL (Hard Fail):
  ├─ ValueError: Invalid parameters
  ├─ AssertionError: Task doesn't support language
  ├─ RuntimeError: Lume clone failed after retries, prep command failed with force_error_free_prep
  └─ OSError: Save directory exists with unexpected state

RECOVERABLE (Soft Fail, Trigger Retry):
  ├─ TimeoutException: Agent step timeout or connectivity timeout
  ├─ TimeoutError: VM startup timeout
  ├─ Generic Exception: SSH command failed, other runtime errors
  └─ Subprocess failures

NON-FATAL (Logged, Not Blocking):
  ├─ VNC disconnect errors (exception swallowed in finally)
  ├─ Lume VM cleanup errors (exception swallowed in finally)
  └─ Missing optional fields in task_dict
```

### Cleanup Guarantee Pattern

```python
try:
    # Phases 1-7: All critical operations
    # Each phase can raise exception → caught by testbench retry loop
finally:
    # Phase 8: ALWAYS execute regardless of exception
    try:
        remote_client.disconnect()
    except Exception as e:
        print_message(e, title='VNC Client Error')
    
    if lume_tools is not None:
        try:
            lume_tools.stop_and_cleanup()
        except Exception as e:
            print_message(e, title='Lume Cleanup Error')

# GUARANTEE: No resource leaks even on hard failures
```

---

## Configuration Customization Points

### Constants (constants.py)

| Constant | Impact | Customization |
|----------|--------|--------------|
| SCREEN_WIDTH/HEIGHT | GUI rendering | Update for different monitor resolutions |
| language_lookup_table | Language parsing | Add language abbreviations (e.g., en, zh) |
| ami_lookup_table | AWS environment | Add AMI IDs for new languages/snapshots |
| env_init_command | macOS startup | Modify for different crash types, drives |
| eval_init_command | Grading prep | Adjust for different app states |
| lume_snapshot_lookup | Lume VM names | Map snapshots to golden VM names |

### CLI Parameters (run.py)

| Parameter | Impact | Tuning |
|-----------|--------|--------|
| task_max_attempts | Failure tolerance | Increase for flaky agents |
| task_step_timeout | Agent timeout | Increase for slow agents/networks |
| pre_command_max_trials | Prep robustness | Increase for unstable environments |
| snapshot_recovery_timeout_seconds | VM startup | Increase for slow cloud, decrease for local |
| max-steps | Task execution length | Increase for complex tasks |

---

## Scaling Architecture

### Single-Machine Execution
```
run.py (Supervisor)
  └─► testbench.py (Sequential Task Iterator)
      ├─► run_task(task_1) → eval_result_1.txt
      ├─► run_task(task_2) → eval_result_2.txt
      └─► run_task(task_N) → eval_result_N.txt

Duration: O(N × avg_task_time)
Resources: 1 VM instance + coordination process
Bottleneck: Sequential execution
```

### Distributed Execution (Future)
```
Coordinator Service
  ├─ Task Queue: [(task_id, task_lang, env_lang), ...]
  ├─ Shared State: NFS mount for {base_save_dir}
  └─ Health Check: Poll worker heartbeats

Worker Nodes (N × parallel workers):
  ├─► Worker 1: run_task(dequeue())
  ├─► Worker 2: run_task(dequeue())
  ├─► Worker 3: run_task(dequeue())
  └─► Worker N: run_task(dequeue())

Result Storage (Shared):
  {base_save_dir}/
  ├─ sys_apps/task_1_en_en/eval_result.txt (Worker 1)
  ├─ sys_apps/task_2_en_en/eval_result.txt (Worker 2)
  ├─ sys_apps/task_3_en_en/eval_result.txt (Worker 3)
  └─ sys_apps/task_N_en_en/eval_result.txt (Worker N)

Duration: O(N × avg_task_time / num_workers)
Resources: N VM instances + 1 coordinator
Parallelization: Perfect (no cross-task dependencies)
```

### Distributed Benefits
- **Parallelization**: No task dependencies
- **Fault Tolerance**: Worker crash → task re-queued
- **Load Balancing**: Dynamic task pulling
- **Scalability**: Add workers without code changes

---

## Key Design Patterns

### 1. Strategy Pattern (VM Backend)

```python
# Context: run_task()
if lume_golden_vm:
    strategy = LumeStrategy()
elif vmx_path:
    strategy = VMwareStrategy()
else:
    strategy = AWSStrategy()

# Use strategy
strategy.reset_environment(snapshot_name)
ssh_host = strategy.get_ssh_host()
```

**Benefit**: Single run_task() works with 3 different backends

### 2. Retry Pattern (Multiple Levels)

```python
# Level 1: Task attempt
for task_attempt in range(task_max_attempts):
    try:
        run_task(...)  # May retry internally (Level 2-4)
        break
    except (TimeoutException, Exception):
        continue

# Level 2: Environment reset (inside run_task)
for retry in range(clone_max_trials):
    try:
        clone_and_start(...)
        break
    except Exception:
        cleanup()
        continue
```

**Benefit**: Fault tolerance at multiple granularities

### 3. Try-Finally Cleanup

```python
try:
    # Execute task (may fail anywhere)
    run_task_phases_1_through_7()
finally:
    # ALWAYS cleanup
    disconnect_vnc()
    cleanup_lume_vm()
```

**Benefit**: No resource leaks regardless of failure point

### 4. File-Based State Machine

```python
# State = file presence
if os.path.exists(f"{save_dir}/eval_result.txt"):
    # COMPLETED
elif os.path.exists(f"{save_dir}/fail.flag"):
    # FAILED
elif os.path.exists(f"{save_dir}/context"):
    # IN_PROGRESS (incomplete)
else:
    # PENDING
```

**Benefit**: Distributed system without database

### 5. Async Event Injection

```python
# Background handler
inprocess_handler.run_command(command)  # Non-blocking

# Agent loop
for step in range(max_steps):
    if step == injection_timestep:
        sleep(5)  # Let event run
    gui_agent.step()

# Foreground query
result = inprocess_handler.end_command()  # Blocks, gets result
```

**Benefit**: Distraction testing without blocking agent

### 6. Socket-Based IPC (run.py ↔ testbench.py)

```python
# run.py
srv = socket.socket()
srv.bind(("127.0.0.1", 0))
conn, _ = srv.accept()  # Blocks until testbench connects
msg = conn.recv(1024)   # Receives "DONE"

# testbench.py
socket.create_connection(("127.0.0.1", port))
s.sendall(b"DONE")
```

**Benefit**: Lightweight IPC without queue infrastructure

---

## Summary: System Characteristics

| Characteristic | Implementation | Implication |
|---|---|---|
| **Fault Tolerance** | Multi-level retry, try-finally cleanup | Robust to transient failures |
| **Scalability** | File-based state, no locks | Ready for distributed version |
| **Parallelization** | Independent tasks, no cross-dependencies | Perfect parallelization potential |
| **Monitoring** | Socket messages, file-based state | Observable without instrumentation |
| **Extensibility** | Backend strategy pattern, CLI config | Easy to add languages, VMs, agents |
| **Recovery** | Cleanup + state machine | Automatic recovery from crashes |
| **Idempotency** | File presence determines state | Safe to retry any operation |

