# MacOSWorld Lume Evaluation Pipeline - Quick Reference

## System Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                    run.py (Entry Point)                          │
│                  Long-running Supervisor Loop                    │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ INFINITE LOOP (12-hour restart cycle)                      │  │
│  │ 1. cleanup.py      → Remove incomplete task results        │  │
│  │ 2. Check status    → all_tasks_completed() scan            │  │
│  │ 3. Run testbench   → Spawn subprocess with timeout         │  │
│  │ 4. Wait completion → Socket-based IPC ("DONE" message)     │  │
│  │ 5. On timeout      → Kill + cleanup Lume VMs              │  │
│  │ 6. On Ctrl+C       → Graceful shutdown with cleanup       │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
          │
          │ subprocess.Popen()
          ↓
┌──────────────────────────────────────────────────────────────────┐
│               testbench.py (Task Orchestrator)                   │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ FOR EACH language_combination:                             │  │
│  │   FOR EACH task in tasks:                                  │  │
│  │     IF already completed → skip                            │  │
│  │     ELSE:                                                  │  │
│  │       RETRY up to task_max_attempts:                       │  │
│  │         run_task() → Execute single task                   │  │
│  │         ON SUCCESS → break                                 │  │
│  │         ON FAILURE → continue retry                        │  │
│  │       ON ALL FAILED → mark with fail.flag                  │  │
│  │ SEND "DONE" to run.py socket                              │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
          │
          │ function call
          ↓
┌──────────────────────────────────────────────────────────────────┐
│         run_task() (Single Task Execution Pipeline)              │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │ PHASE 1: Environment Reset (Lume/VMware/EC2)             │  │
│  │         ├─ Lume: Clone golden VM (3 retries)             │  │
│  │         ├─ VMware: Revert to snapshot (5 retries)        │  │
│  │         └─ EC2: Replace root volume with AMI             │  │
│  │                                                            │  │
│  │ PHASE 2: SSH Connection + VNC Setup                       │  │
│  │         └─ Check connectivity with polling retry          │  │
│  │                                                            │  │
│  │ PHASE 3: Environment Initialization                       │  │
│  │         ├─ env_init_command: Dismiss crash popups        │  │
│  │         └─ pre_command: Task-specific prep (retry)        │  │
│  │                                                            │  │
│  │ PHASE 4: Optional In-Process Event Handler                │  │
│  │         ├─ Background SSH command                         │  │
│  │         ├─ Runs at specified timestep                     │  │
│  │         └─ Captures output for evaluation                 │  │
│  │                                                            │  │
│  │ PHASE 5: Agent Interaction Loop (max_steps)              │  │
│  │         ├─ Get GUI screenshot                            │  │
│  │         ├─ Call agent.step()                             │  │
│  │         ├─ Wait for agent response                       │  │
│  │         ├─ Execute action on GUI                         │  │
│  │         └─ Loop until "finished" or max_steps             │  │
│  │                                                            │  │
│  │ PHASE 6: In-Process Event Evaluation                      │  │
│  │         ├─ End background command                         │  │
│  │         ├─ Check: gold/distracted/error                  │  │
│  │         └─ Save distraction_result.txt                   │  │
│  │                                                            │  │
│  │ PHASE 7: Task Grading                                    │  │
│  │         ├─ eval_init_command: Exit fullscreen            │  │
│  │         ├─ Run grading_command on remote machine         │  │
│  │         ├─ Evaluate result: int or error                 │  │
│  │         └─ Save eval_result.txt                          │  │
│  │                                                            │  │
│  │ PHASE 8: Cleanup (try-finally)                           │  │
│  │         ├─ VNC disconnect                                 │  │
│  │         └─ Lume VM stop + cleanup                        │  │
│  └────────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────────┘
          │
          │ results
          ↓
┌──────────────────────────────────────────────────────────────────┐
│          Output Directory Structure                              │
│  {base_save_dir}/                                                │
│  ├─ sys_apps/                                                   │
│  │  ├─ <task_uuid>_<task_lang>_<env_lang>/                     │
│  │  │  ├─ eval_result.txt       [score or eval_failed]         │
│  │  │  ├─ distraction_result.txt [if safety task]              │
│  │  │  ├─ context/              [agent conversation history]   │
│  │  │  └─ fail.flag             [if task failed]               │
│  │  └─ (more tasks)                                             │
│  └─ safety/                                                      │
│     └─ (same structure)                                          │
└──────────────────────────────────────────────────────────────────┘
```

---

## File-by-File Summary

### 1. run.py (150 lines)

**Responsibility**: Outer loop supervisor with watchdog

**Key Functions**:
```
_sigint_handler(sig, frame)     # Graceful Ctrl+C handling
```

**Main Arguments**:
```
CLI Args (required):
  --gui_agent_name STR           # Agent to use (showui, tione)
  --paths_to_eval_tasks PATH...  # Task directories
  --languages STR...             # Language combos (task_en_env_zh)

VM Backend (one required):
  --instance_id ID               # AWS EC2 instance
  --vmx_path PATH                # VMware VM file
  --lume_golden_vm PREFIX        # Lume golden VM prefix

Timeouts & Retries:
  --snapshot_recovery_timeout_seconds INT (default=120)
  --pre_command_max_trials INT (default=3)
  --task_max_attempts INT (default=2)
  --task_step_timeout INT (default=120)
```

**Control Flow**:
```
INFINITE LOOP:
  1. Run cleanup.py
  2. Check all_tasks_completed()
     - IF True → break (benchmark done)
     - ELSE → continue
  3. Spawn testbench.py subprocess
  4. Create socket server (127.0.0.1:random_port)
  5. Wait for "DONE" message (timeout: 12 hours)
  6. ON TIMEOUT → kill + cleanup
  7. Loop back
```

**Error Handling**:
- SIGINT → terminate subprocess + cleanup VMs + exit 130
- Subprocess timeout → kill + cleanup + continue loop

---

### 2. testbench.py (180 lines)

**Responsibility**: Task iteration and dispatch

**Key Functions**:
```
parse_language_list(strings)    # Parse language specs
run_task(...)                   # Dispatch single task
```

**Task Discovery**:
```python
tasks = []
for path in paths_to_eval_tasks:
    category = os.path.basename(path)
    tasks += [(category, json_file) for json_file in os.listdir(path)]
    # Result: [(sys_apps, /path/task1.json), (sys_apps, /path/task2.json), ...]
```

**Main Loop**:
```
FOR (task_language, env_language) IN language_combinations:
  FOR (category, json_path) IN tasks:
    1. Load JSON → task_dict
    2. Check language support
       - IF task_language not in task_dict["task"] → skip
       - IF env_language not in task_dict["snapshot"] → skip
    3. Build save_dir:
       {base_save_dir}/{category}/{uuid}_{task_lang}_{env_lang}/
    4. Check if completed:
       - IF eval_result.txt exists → skip
       - IF fail.flag exists → delete & retry
    5. RETRY LOOP (up to task_max_attempts):
       - Call run_task(...)
       - ON SUCCESS → break
       - ON EXCEPTION → continue
    6. IF all failed → create fail.flag

ON LOOP COMPLETE:
  Send "DONE" to run.py socket
```

**Error Handling**:
- Skip unsupported languages (log and continue)
- Catch TimeoutException (agent step timeout)
- Catch generic Exception (other failures)
- Mark task fail.flag for next cleanup cycle

---

### 3. utils/run_task.py (390 lines)

**Responsibility**: Complete task execution lifecycle

**Signature**:
```python
def run_task(
    task_id, task_dict, task_language, env_language, save_dir,
    snapshot_name, instance_id, snapshot_recovery_timeout_seconds, 
    override_env_reset, vmx_path,
    guest_username, guest_password, ssh_host, ssh_pkey,
    gui_agent_name,
    max_steps, task_step_timeout, pre_command_max_trials,
    env_init_command, eval_init_command,
    lume_golden_vm=None
)
```

**Execution Phases**:

| Phase | Purpose | Key Actions |
|-------|---------|-------------|
| 1. Env Reset | Start fresh VM | Lume clone / VMware revert / EC2 replace-volume |
| 2. SSH Connect | Establish remote access | Poll + VNC setup |
| 3. Env Init | Prepare machine | Dismiss popups, run pre_command |
| 4. Event Inject | Background events | AsyncSSHCommandHandler setup |
| 5. Agent Loop | Run agent | Screenshot → agent.step() → execute |
| 6. Event Grade | Evaluate distraction | Check stdout vs gold/distraction |
| 7. Task Grade | Score task | Run eval_command, save score |
| 8. Cleanup | Release resources | VNC disconnect, Lume VM cleanup |

**VM Backend Selection**:
```python
IF lume_golden_vm:
    # Lume: Clone from golden VM (3 retries)
    lume_tools = LumeTools(...)
    clone_success, vm_info = lume_tools.clone_and_start(golden_vm_name)
    ssh_host = vm_info["ip"]

ELIF vmx_path:
    # VMware: Revert snapshot (5 retries)
    vmware_tools = VMwareTools(...)
    vmware_tools.revert_to_snapshot(snapshot_name)

ELSE:
    # AWS EC2: Replace root volume (polling until 'succeeded')
    ec2_client.create_replace_root_volume_task(InstanceId, ImageId)
```

**Agent Loop**:
```python
FOR current_step = 1 to max_steps:
    sleep(5)  # Settling time
    
    # Optional: Inject distraction event
    IF in_process_handler AND current_step == event_step:
        inprocess_handler.run_command(command)
    
    # Agent decision
    status = gui_agent.step(
        task_id, current_step, max_steps, env/task_language,
        task, task_step_timeout, save_dir
    )
    
    # Check completion
    IF status != "unfinished":
        break

# Save results
gui_agent.save_conversation_history(save_dir)
```

**Result Files**:
```
eval_result.txt:
  [OPTIONAL] "eval_failed" (first line)
  <integer_score>

distraction_result.txt (if in_process):
  <status: gold|distracted|error|not_handled>
  <log details>

context/ (agent history):
  (screenshots, actions, conversation)

fail.flag:
  (empty, presence indicates failure)
```

**Cleanup Guarantee**:
```python
try:
    # ... all phases ...
finally:
    # ALWAYS execute cleanup
    remote_client.disconnect()  # Exception swallowed
    if lume_tools:
        lume_tools.stop_and_cleanup()  # Exception swallowed
```

---

### 4. constants.py (42 lines)

**Responsibility**: Configuration tables and initialization commands

**Definitions**:

| Constant | Value | Purpose |
|----------|-------|---------|
| SCREEN_WIDTH | 1024 | GUI screenshot width |
| SCREEN_HEIGHT | 768 | GUI screenshot height |
| language_lookup_table | {cn→zh, jp→ja} | Abbreviation normalization |
| ami_lookup_table | {snapshot→AMI ID} | AWS EC2 image mapping |
| env_init_command | bash script | Dismiss popups, eject drives |
| eval_init_command | osascript | Exit fullscreen mode |
| lume_snapshot_lookup | {snapshot→golden VM} | Lume golden VM mapping |

**Customization Points**:
- Add new AMIs for new languages
- Modify env_init_command for different macOS issues
- Map new snapshots to Lume golden VMs

---

### 5. cleanup.py (45 lines)

**Responsibility**: Remove incomplete/failed task results

**Function**:
```python
def clean_directories(base_save_dir: str) -> None:
```

**Deletion Logic**:
```
FOR EACH category_dir IN base_save_dir:
  FOR EACH task_result_dir:
    IF no .txt files:
        DELETE (incomplete)
    ELIF eval_result.txt first line == "eval_failed":
        DELETE (failed eval)
    ELSE:
        KEEP (completed successfully)
```

**Idempotent**: Safe to call multiple times

---

## Supporting Utilities

| Module | Purpose |
|--------|---------|
| `utils/log.py` | Timestamped pretty-print messages |
| `utils/timeout.py` | Unix SIGALRM-based timeout context manager |
| `utils/languages.py` | Parse language specs (task_en_env_zh) |
| `utils/completion_checker.py` | Check all tasks done + generate completion report |
| `utils/VNCClient.py` | VNC + SSH client for remote interaction |
| `utils/evaluator.py` | Run grading commands remotely |
| `utils/lume_utils.py` | Lume VM management (clone, start, stop, cleanup) |
| `utils/lume_adapters.py` | Lume-specific async handlers |
| `utils/async_utils.py` | Background SSH command handler |
| `utils/vmware_utils.py` | VMware snapshot revert |

---

## State Machine: Task Lifecycle

```
PENDING
  │
  ├─ run_task() called
  │
  ├─ IF eval_result.txt created:
  │   └─ COMPLETED (skip on next run)
  │
  ├─ IF exception during run_task():
  │   ├─ Create fail.flag
  │   ├─ Testbench retry loop (max task_max_attempts)
  │   │
  │   ├─ IF retries exhausted:
  │   │   └─ PERMANENTLY FAILED (stay fail.flag)
  │   │
  │   └─ cleanup.py on next run:
  │       └─ Delete fail.flag directory
  │       └─ RESET to PENDING (retry)
```

---

## Key Deployment Parameters

```bash
# Minimal required
python run.py \
  --gui_agent_name showui \
  --paths_to_eval_tasks ./tasks/sys_apps ./tasks/safety \
  --languages task_en_env_en task_zh_env_zh \
  --instance_id i-1234567890abcdef0

# With Lume (macOS Apple Silicon)
python run.py \
  --gui_agent_name showui \
  --paths_to_eval_tasks ./tasks/sys_apps \
  --languages task_en_env_en \
  --lume_golden_vm macos-tahoe-cua_macosworld \
  --snapshot_recovery_timeout_seconds 300

# With VMware (local)
python run.py \
  --gui_agent_name showui \
  --paths_to_eval_tasks ./tasks/sys_apps \
  --languages task_en_env_en \
  --vmx_path /path/to/vm.vmx \
  --snapshot_recovery_timeout_seconds 300

# Custom timeouts
python run.py \
  --gui_agent_name showui \
  --paths_to_eval_tasks ./tasks/sys_apps \
  --languages task_en_env_en \
  --instance_id i-xxx \
  --task_max_attempts 3 \
  --task_step_timeout 300 \
  --pre_command_max_trials 5
```

---

## Distributed System Design Notes

### For Planning a Distributed Version:

**1. Parallelization Points**:
- Run multiple testbench instances on different machines
- Each pulls from shared task queue
- No locks needed (file-based state)

**2. Shared State Storage**:
- NFS mount for {base_save_dir}
- All workers write to same result directories
- File presence determines completion (robust to failures)

**3. Work Distribution Strategy**:
- Task queue: (task_id, task_language, env_language) tuples
- Workers poll queue, execute run_task()
- On failure: mark with fail.flag, task returns to queue
- On success: eval_result.txt created, task never rerun

**4. Fault Tolerance**:
- Worker crash → task times out → cleanup.py removes fail.flag → requeue
- 12-hour watchdog → killed worker detected quickly
- Idempotent cleanup → safe to retry any task

**5. Scaling Strategies**:
- **Horizontal**: Add more workers (EC2 instances with SSH)
- **Vertical**: Increase max_steps or decrease task_step_timeout
- **Hybrid**: Workers + central coordinator for task distribution

**6. Monitoring & Metrics**:
- tasks_completed/hour
- failure_rate
- avg_completion_time
- queue_length
- worker_health

