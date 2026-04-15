# MacOSWorld Lume Evaluation Pipeline - Comprehensive Analysis

## Executive Summary

The macosworld_lume project is an **evaluation benchmark system** for GUI agents on macOS. It orchestrates:
- **Task discovery & execution** across multiple language/environment combinations
- **VM/EC2 environment reset** before each task (snapshots)
- **GUI agent interaction** with screenshots and actions
- **Automated grading** of task completion
- **Fault tolerance** with task retries and automatic cleanup

The system is designed to run continuously, with a 12-hour restart cycle to prevent subprocess stalls.

---

## 1. RUN.PY - Outer Loop / Entry Point

**Purpose**: Long-running supervisor process that orchestrates the entire benchmark.

### Function Signatures & Arguments

```python
argparse.ArgumentParser() with these arguments:
```

#### Connection & VM Management:
- `--guest_username` (str, default='ec2-user'): SSH login for guest VM
- `--guest_password` (str, default='000000'): SSH password for guest VM
- `--ssh_host` (str, default=None): Direct SSH host (for pre-existing VM)
- `--ssh_pkey` (str, default='credential.pem'): Path to SSH private key
- `--instance_id` (str): AWS EC2 instance ID
- `--vmx_path` (str, default=None): Path to VMware .vmx file
- `--lume_golden_vm` (str, default=None): Enable Lume mode; prefix for golden VM names

#### Environment Reset:
- `--snapshot_recovery_timeout_seconds` (int, default=120): Timeout for snapshot restore
- `--override_env_reset` (bool): Manually reset environment (debug mode with breakpoint)

#### Task Execution:
- `--pre_command_max_trials` (int, default=3): Retry attempts for prep commands
- `--task_max_attempts` (int, default=2): Retry attempts per task
- `--task_step_timeout` (int, default=120): Timeout per agent step

#### Agent & Output:
- `--gui_agent_name` (str, required): Name of GUI agent to use (e.g., 'showui', 'tione')
- `--max-steps` (int, default=15): Max interaction steps per task
- `--base_save_dir` (str, default='./results'): Root output directory
- `--paths_to_eval_tasks` (nargs='+', required): Paths to task JSON files
- `--languages` (nargs='+', required): Language combinations (e.g., 'task_en_env_en')

### Control Flow / Orchestration Logic

```
INFINITE LOOP:
├─ Step 1: Run cleanup.py
│   └─ Removes incomplete/failed task directories from previous runs
│
├─ Step 2: Check completion status
│   └─ all_tasks_completed() scans base_save_dir
│   └─ IF all tasks done → break loop, exit with message
│   └─ ELSE → continue to Step 3
│
└─ Step 3: Run testbench.py subprocess
    ├─ Pass all arguments to subprocess
    ├─ Create socket server (127.0.0.1:random_port)
    ├─ Pass socket port to testbench
    ├─ Wait up to TESTBENCH_TIMEOUT_SECONDS (12 hours)
    ├─ testbench sends "DONE" message when finished
    ├─ IF timeout → kill testbench + cleanup stale Lume VMs
    └─ LOOP back to Step 1
```

### Graceful Shutdown Handling

- **SIGINT handler** (`_sigint_handler`):
  - Catches Ctrl+C
  - Terminates testbench subprocess (with 10s timeout before kill)
  - Calls `LumeTools.cleanup_stale_vms()` to clean up any orphaned Lume VMs
  - Exits with code 130

### Error Handling

- **12-hour timeout**: Forcibly kills testbench if it hangs
- **Stale VM cleanup**: On every SIGINT and testbench timeout
- **Socket-based communication**: Waits for testbench to send "DONE" via socket before proceeding

### Key Design Decisions

1. **Long-running outer loop**: Handles indefinite benchmarking by restarting testbench every 12 hours
2. **Socket-based IPC**: Uses TCP socket to detect testbench completion (heartbeat mechanism)
3. **Automatic stale cleanup**: Aggressive cleanup of VMs on interruption
4. **Subprocess delegation**: run.py only monitors; testbench does actual work

---

## 2. TESTBENCH.PY - Task Iteration & Dispatch

**Purpose**: Iterates through all task/language combinations and dispatches to `run_task()`.

### Function Signatures

```python
# Argument parsing (same as run.py, plus one additional):
arguments.port: int  # Socket port for communication with run.py

# Main dispatch logic (implicit in main script):
parse_language_list(languages) -> List[Tuple[str, str]]
  # Parses "task_en_env_zh" → (en, zh)
  # Returns list of (task_language, env_language) tuples
```

### Task Discovery & Loading

```python
tasks = []
for path in arguments.paths_to_eval_tasks:
    category_name = os.path.basename(path)  # e.g., 'sys_apps'
    # Find all .json files in path
    tasks += [(category_name, os.path.join(path, file)) 
              for file in os.listdir(path) if file.lower().endswith('json')]
```

**Task structure**:
```
tasks = [
    (category_name, json_path),
    (category_name, json_path),
    ...
]
```

### Task Dispatch Flow (Main Loop)

```
FOR EACH (task_language, env_language) COMBINATION:
  ├─ Apply language lookup (e.g., 'cn' → 'zh')
  │
  FOR EACH task (category, json_path) IN tasks:
    ├─ Load JSON file
    ├─ Extract task_uuid from JSON
    ├─ Check if task supports this language combo:
    │   ├─ IF task_language NOT in task_dict["task"] → skip
    │   ├─ IF env_language NOT in task_dict["snapshot"] → skip
    │   └─ ELSE → continue
    │
    ├─ Get snapshot_name from task_dict["snapshot"][env_language]
    │
    ├─ Build save_dir path:
    │   └─ {base_save_dir}/{category}/{uuid}_{task_language}_{env_language}/
    │
    ├─ Check if already completed:
    │   ├─ IF eval_result.txt exists → skip (already done)
    │   ├─ IF fail.flag exists → delete and retry
    │   └─ ELSE → create save_dir
    │
    └─ RETRY LOOP (up to task_max_attempts times):
        ├─ Call run_task(...)
        │   └─ Returns on success (status != "unfinished")
        │   └─ Raises TimeoutException or generic Exception on failure
        ├─ ON SUCCESS → set task_complete_flag = True, break retry loop
        ├─ ON TIMEOUT → log error, continue retry loop
        └─ ON EXCEPTION → log error, continue retry loop
    
    ├─ IF task failed after all retries:
    │   ├─ Create fail.flag file
    │   └─ Add to incomplete_task_list
```

### Lume Mode Auto-Detection

```python
if lume_golden_vm is not None:
    # Auto-set Lume credentials if not explicitly changed
    if guest_username == 'ec2-user':
        guest_username = 'lume'
    if guest_password == '000000':
        guest_password = 'lume'
```

### Completion Signaling

```python
if arguments.port is not None:
    s = socket.create_connection(("127.0.0.1", arguments.port))
    s.sendall(b"DONE")
    s.close()
```

Sends "DONE" message to run.py when all tasks finished.

### Error Handling

- **Skips invalid language combinations** (logs and continues)
- **Catches TimeoutException** (raised by run_task timeout)
- **Catches generic Exception** (other failures)
- **Retries failed tasks** up to task_max_attempts times
- **Incomplete tasks marked with fail.flag** for potential cleanup on next run

### Key Design Decisions

1. **Nested loops**: Language combinations (outer) × tasks (inner)
2. **Lazy task discovery**: Load JSON files on-demand rather than pre-load all
3. **Single retry per task**: Failure is caught per attempt, with retry loop wrapping
4. **Socket-based completion signaling**: Tells run.py when entire testbench is done

---

## 3. UTILS/RUN_TASK.PY - Single Task Execution

**Purpose**: Orchestrates the full lifecycle of a single task: VM setup → agent interaction → grading → cleanup.

### Function Signature

```python
def run_task(
    # Task-related params
    task_id: str,                              # e.g., "(1/50)" for display
    task_dict: dict,                           # Loaded JSON task definition
    task_language: str,                        # Task language (en, zh, etc.)
    env_language: str,                         # Environment language
    save_dir: str,                             # Output directory
    
    # Environment setup
    snapshot_name: str,                        # e.g., 'snapshot_used_en'
    instance_id: str,                          # AWS EC2 instance ID
    snapshot_recovery_timeout_seconds: int,    # VM startup timeout
    override_env_reset: bool,                  # Manual reset (debug)
    vmx_path: str,                             # VMware path (None if EC2)
    
    # Remote connection
    guest_username: str,
    guest_password: str,
    ssh_host: str,
    ssh_pkey: str,
    
    # GUI agent
    gui_agent_name: str,                       # Agent name (showui, tione)
    
    # Runtime
    max_steps: int,                            # Max interaction steps
    task_step_timeout: int,                    # Timeout per agent step
    pre_command_max_trials: int,               # Prep command retries
    env_init_command: str,                     # Env initialization
    eval_init_command: str,                    # Grading initialization
    
    # Lume params (optional)
    lume_golden_vm: str = None,                # Lume golden VM prefix
):
```

### Execution Flow

```
RUN_TASK FLOW:
│
├─ PHASE 1: ENVIRONMENT RESET
│  ├─ IF override_env_reset:
│  │   └─ breakpoint() for manual reset
│  │
│  ├─ IF lume_golden_vm is not None:
│  │   ├─ LumeTools.cleanup_stale_vms()  [safety]
│  │   ├─ Resolve golden_vm_name (lookup or default)
│  │   ├─ Generate unique task_vm_name
│  │   ├─ RETRY LOOP (up to 3 times):
│  │   │   ├─ lume_tools = LumeTools(task_vm_name, ...)
│  │   │   ├─ lume_tools.clone_and_start(golden_vm_name, timeout)
│  │   │   └─ ON SUCCESS → break, capture vm_info (ip, vnc_port, vnc_password)
│  │   ├─ ON FAILURE after all retries → raise RuntimeError
│  │   └─ ssh_host = vm_info["ip"]
│  │
│  ├─ ELIF vmx_path is not None:
│  │   ├─ vmware_tools = VMwareTools(...)
│  │   ├─ RETRY LOOP (up to 5 times):
│  │   │   └─ vmware_tools.revert_to_snapshot(snapshot_name)
│  │   │       └─ Returns (success_flag, ssh_host)
│  │   └─ ON FAILURE → no retry, continue
│  │
│  └─ ELSE (AWS mode):
│      ├─ snapshot_id = ami_lookup_table[snapshot_name]
│      ├─ ec2_client.create_replace_root_volume_task(
│      │     InstanceId=instance_id,
│      │     ImageId=snapshot_id,
│      │     DeleteReplacedRootVolume=True
│      │  )
│      ├─ POLL LOOP:
│      │   └─ While task not 'succeeded':
│      │       ├─ IF cumulative_waiting_time > timeout → raise TimeoutError
│      │       └─ sleep(10)
│      └─ [continue]
│
├─ PHASE 2: ESTABLISH REMOTE CONNECTION
│  ├─ IF lume_golden_vm is not None:
│  │   └─ remote_client = VNCClient_Lume(vm_name, vnc_port, vnc_password)
│  └─ ELSE:
│      └─ remote_client = VNCClient_SSH(ssh_host, ssh_pkey)
│
│  ├─ CHECK SSH CONNECTIVITY:
│  │   └─ POLL LOOP:
│  │       └─ While not connected:
│  │           ├─ IF cumulative_waiting_time > timeout → raise TimeoutError
│  │           └─ sleep(10)
│
│  └─ remote_client.connect()
│
├─ PHASE 3: ENVIRONMENT INITIALIZATION
│  ├─ remote_client.run_ssh_command(env_init_command)
│  │   [Handles panic popups, removes excess drives]
│  │
│  └─ IF 'pre_command' in task_dict:
│      ├─ RETRY LOOP (up to pre_command_max_trials):
│      │   ├─ IF pre_command is str:
│      │   │   └─ pre_command_complete_flag, output = run_ssh_command(pre_command)
│      │   ├─ ELIF pre_command is dict[env_language]:
│      │   │   └─ pre_command_complete_flag, output = run_ssh_command(...)
│      │   └─ IF pre_command_complete_flag → break
│      │
│      └─ IF "force_error_free_prep" in task_dict AND failed:
│          └─ raise RuntimeError
│
├─ PHASE 4: OPTIONAL IN-PROCESS EVENT HANDLER
│  ├─ IF 'in_process' in task_dict:
│  │   ├─ Extract: (command, event_step, gold_elements, distracting_elements)
│  │   ├─ IF lume_golden_vm:
│  │   │   └─ inprocess_event_handler = LumeAsyncSSHCommandHandler(...)
│  │   └─ ELSE:
│  │       └─ inprocess_event_handler = AsyncSSHCommandHandler(...)
│  │   [Handler will run command at specified timestep]
│
│  └─ IF 'before_action_delay_seconds' in task_dict:
│      └─ sleep(delay_seconds)
│
├─ PHASE 5: AGENT INTERACTION LOOP
│  ├─ Construct GUI Agent:
│  │   └─ gui_agent = get_gui_agent(gui_agent_name, remote_client)
│  │
│  └─ FOR current_step = 1 to max_steps:
│      ├─ sleep(5)  [settling time]
│      │
│      ├─ IF inprocess_event_handler AND current_step == event_step:
│      │   ├─ inprocess_event_handler.run_command(inprocess_command)
│      │   ├─ sleep(5)
│      │   └─ log "Distraction event injected"
│      │
│      ├─ gui_agent.step(
│      │     task_id, current_step, max_steps, env_language, task_language,
│      │     task, task_step_timeout, save_dir
│      │  )
│      │   └─ Returns status: "unfinished", "finished", or failure status
│      │
│      └─ IF status != "unfinished" → break loop
│      
│  └─ gui_agent.save_conversation_history(save_dir)
│
├─ PHASE 6: IN-PROCESS EVENT EVALUATION (if applicable)
│  └─ IF inprocess_event_handler is not None:
│      ├─ inprocess_event_handler.end_command()
│      │   └─ Returns (return_code, stdout, stderr, end_type)
│      │
│      ├─ EVALUATE RESULT:
│      │   ├─ IF end_type == 'killed' → eval = 'not_handled'
│      │   ├─ IF return_code == 0:
│      │   │   └─ inprocess_result_matching(stdout, gold_elements, distracting_elements)
│      │   │       ├─ IF any gold_element in stdout → 'gold'
│      │   │       ├─ IF any distracting_element in stdout → 'distracted'
│      │   │       └─ ELSE → 'error_no_match'
│      │   ├─ IF return_code == 1 AND '-128' in stdout:
│      │   │   └─ inprocess_result_matching(...)
│      │   └─ ELSE → eval = 'error'
│      │
│      └─ Save result to distraction_result.txt
│
├─ PHASE 7: TASK GRADING
│  ├─ IF 'before_grading_delay_seconds' in task_dict:
│  │   └─ sleep(delay_seconds)
│  │
│  ├─ Create Evaluator:
│  │   ├─ IF lume_golden_vm:
│  │   │   └─ evaluator = LumeEvaluator(...)
│  │   └─ ELSE:
│  │       └─ evaluator = Evaluator(ssh_host, guest_username, ssh_pkey)
│  │
│  ├─ evaluator.run_command(eval_init_command)
│  │   [Exits fullscreen mode on macOS]
│  │
│  ├─ eval_result = evaluator(task_dict["grading_command"])
│  │   └─ Returns: int (score) or list (error messages)
│  │
│  └─ Save result to eval_result.txt:
│      ├─ IF eval_result is int:
│      │   ├─ IF eval_result < 0 → prefix with "eval_failed"
│      │   └─ Write eval_result
│      ├─ ELIF eval_result is list:
│      │   ├─ Write "eval_failed"
│      │   └─ Write each line
│      └─ ELSE → raise RuntimeError("Illegal return type")
│
└─ PHASE 8: CLEANUP (ALWAYS)
   ├─ TRY:
   │   └─ remote_client.disconnect()
   │   └─ (Exception swallowed and logged)
   │
   └─ IF lume_tools is not None:
       └─ TRY:
           └─ lume_tools.stop_and_cleanup()
           └─ (Exception swallowed and logged)
```

### Key Features

1. **Three VM backend support**:
   - Lume (macOS native with golden VMs and cloning)
   - VMware (snapshot revert)
   - AWS EC2 (replace root volume via AMI)

2. **Robust retry logic**:
   - Lume clone: 3 retries
   - VMware snapshot: 5 retries
   - Pre-commands: configurable retries
   - SSH connectivity: timeout-based retry

3. **Optional in-process events**: 
   - Can inject distraction events at specific timestep
   - Captures stdout/stderr and evaluates against gold/distraction criteria

4. **Multi-phase initialization**:
   - Environment init (crash popup handling, drive cleanup)
   - Pre-command (prep work)
   - Optional delay before agent starts

5. **Guaranteed cleanup**: 
   - Try-finally ensures VNC disconnect and Lume VM cleanup
   - Exceptions logged but don't prevent cleanup

### Error Handling

- **TimeoutException**: Raised on SSH/snapshot timeout, caught by testbench retry loop
- **RuntimeError**: Raised on Lume clone failure, Lume/VMware issues, bad task dict
- **AssertionError**: Raised if task doesn't support required language
- **All exceptions logged** and cleanup still executes (finally block)

### Design Decisions

1. **Cumulative waiting time**: Tracks total elapsed time across all retry attempts
2. **Independent timeouts**: Each phase can timeout independently
3. **Stateful VM**: Lume tools tracked for guaranteed cleanup
4. **Socket-based SSH commands**: AsyncSSHCommandHandler for background events
5. **Result files**: Always written to disk for post-analysis

---

## 4. CONSTANTS.PY - Configuration & Lookups

### Screen Dimensions
```python
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768
```

### Language Lookup Table
```python
language_lookup_table = {
    'cn': 'zh',  # Chinese (simplified) code
    'jp': 'ja',  # Japanese code
}
```
Maps common abbreviations to ISO 639-1 codes.

### AWS AMI Lookup Table
```python
ami_lookup_table = {
    'snapshot_used_en': 'ami-0132f892c5d80f6ba',
    'snapshot_used_zh': 'ami-041d43ade1bded250',
    'snapshot_used_ar': 'ami-0788f9675451c8c0b',
    'snapshot_used_ja': 'ami-09bf9d80c30e9a2bb',
    'snapshot_used_ru': 'ami-02199d3a0f6b08a9f',
    'snapshot_usedApps_en': 'ami-07f4fd69378358c18',
    'snapshot_usedApps_zh': 'ami-05d53e9457be4cb2c',
    'snapshot_usedApps_ar': 'ami-0ddb58aed32bc4e64',
    'snapshot_usedApps_ja': 'ami-0e331d94ceb1a41ed',
    'snapshot_usedApps_ru': 'ami-07e98ef3c25032b50',
}
```
Maps snapshot names → AWS AMI IDs for EC2 restore.

### Environment Initialization Command
```python
env_init_command = """
find /Library/Logs/DiagnosticReports -type f -name "panic*.panic" -mmin -20 2>/dev/null | \
  grep -q . && osascript -e 'tell application "System Events" to click at {456,349}' && \
  rm -rf /Library/Logs/DiagnosticReports/*.panic; \
diskutil list | grep Creedence | awk '{print $NF}' | xargs -I {} diskutil eject {} 2>/dev/null
"""
```
- **Line 1**: Dismisses macOS panic popup windows (crash reports) by clicking at fixed coords
- **Line 2**: Ejects virtual drives (Creedence) to prevent Finder layout disruption

### Evaluation Initialization Command
```python
eval_init_command = """
osascript -e 'tell application "System Events" to get value of attribute "AXFullScreen" of window 1 of (first application process whose frontmost is true)' | \
  grep -q true && osascript -e 'tell application "System Events" to keystroke "f" using {control down, command down}'
"""
```
Detects fullscreen mode and exits it (Ctrl+Cmd+F) for grading.

### Lume Golden VM Mapping
```python
lume_snapshot_lookup = {
    'snapshot_used_en': 'macos-tahoe-cua_macosworld-en',
    'snapshot_used_zh': 'macos-tahoe-cua_macosworld-zh',
    'snapshot_used_ar': 'golden_used_ar',
    'snapshot_used_ja': 'golden_used_ja',
    'snapshot_used_ru': 'golden_used_ru',
    'snapshot_usedApps_en': 'golden_usedApps_en',
    'snapshot_usedApps_zh': 'golden_usedApps_zh',
    'snapshot_usedApps_ar': 'golden_usedApps_ar',
    'snapshot_usedApps_ja': 'golden_usedApps_ja',
    'snapshot_usedApps_ru': 'golden_usedApps_ru',
}
```
Maps snapshot names → Lume golden VM names for cloning.

---

## 5. CLEANUP.PY - Cleanup Operations

**Purpose**: Removes incomplete or failed task results before a new testbench run.

### Function Signature

```python
def clean_directories(base_save_dir: str) -> None:
```

### Cleanup Flow

```
CLEANUP FLOW:
│
└─ FOR EACH category_dir IN base_save_dir:
    ├─ FOR EACH subdirectory IN category_dir:
    │   ├─ List all files in subdirectory
    │   │
    │   ├─ Check for .txt files:
    │   │   ├─ IF no .txt files exist:
    │   │   │   ├─ DELETE entire subdirectory
    │   │   │   └─ log "Deleting (incomplete)"
    │   │   │
    │   │   └─ IF .txt files exist:
    │   │       ├─ Check eval_result.txt:
    │   │       │   ├─ IF file exists AND first line == "eval_failed":
    │   │       │   │   ├─ DELETE entire subdirectory
    │   │       │   │   └─ log "Deleting (eval_failed)"
    │   │       │   └─ ELSE:
    │   │       │       └─ Keep subdirectory (completed successfully)
```

### Deletion Rules

1. **Incomplete task** (no .txt files):
   - Indicates task was interrupted before results saved
   - **Action**: Delete for retry

2. **Failed evaluation** (eval_result.txt first line == "eval_failed"):
   - Indicates grading command failed
   - **Action**: Delete for retry

3. **Completed successfully** (eval_result.txt with numeric score):
   - **Action**: Keep (do not delete)

### Error Handling

```python
if not os.path.isdir(base_save_dir):
    return  # Silent return if directory doesn't exist
```

No exceptions raised; fails silently if directory missing.

### Entry Point

```python
if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--base_save_dir", type=str, required=True)
    args = parser.parse_args()
    clean_directories(args.base_save_dir)
```

---

## Supporting Utilities

### utils/log.py - Logging Utility

```python
def print_message(content, title=None):
    """
    Pretty-print timestamped messages with optional title.
    
    Output format:
    [YYYY-MM-DD HH:MM:SS] [title] content
    (Timestamp is in reverse video mode for visibility)
    """
```

### utils/timeout.py - Timeout Context Manager

```python
class TimeoutException(Exception):
    pass

class timeout:
    def __init__(self, seconds, message="Time limit exceeded."):
        self.seconds = seconds
        self.message = message
    
    def __enter__(self):
        signal.signal(signal.SIGALRM, self.handle_timeout)
        signal.alarm(self.seconds)
    
    def __exit__(self, exc_type, exc_value, traceback):
        signal.alarm(0)
```
Uses Unix SIGALRM signal for timeout mechanism.

### utils/languages.py - Language Parsing

```python
def parse_language_string(s: str) -> Tuple[str, str]:
    """
    Parses format: 'task_<xx>_env_<xx>'
    Returns: (task_lang, env_lang)
    Example: 'task_en_env_zh' → ('en', 'zh')
    """

def parse_language_list(strings: List[str]) -> List[Tuple[str, str]]:
    """
    Applies parse_language_string to each element.
    """
```

### utils/completion_checker.py - Completion Status

```python
def all_tasks_completed(base_save_dir: str, paths_to_eval_tasks: List[str], 
                       languages: List[str]) -> bool:
    """
    Checks if ALL tasks are completed.
    
    Completion criteria:
    1. Result directory exists: {base_save_dir}/{category}/{uuid}_{task_lang}_{env_lang}/
    2. eval_result.txt exists and first non-empty line is an integer
    3. IF category == "safety": distraction_result.txt must exist and be non-empty
    
    Returns: True iff all tasks meet completion criteria
    Returns: False if any task is missing or incomplete
    """
```

---

## Data Flow Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      run.py (Outer Loop)                   │
│  ├─ SIGINT handler for graceful shutdown                   │
│  ├─ Calls cleanup.py                                        │
│  ├─ Checks all_tasks_completed()                            │
│  └─ Spawns testbench.py (with 12-hour timeout)             │
└──────────────────────┬──────────────────────────────────────┘
                       │ subprocess.Popen()
                       ↓
┌─────────────────────────────────────────────────────────────┐
│               testbench.py (Task Iterator)                  │
│  ├─ Load all tasks from JSON files                          │
│  ├─ Generate language combinations                          │
│  ├─ For each (lang_combo, task):                            │
│  │   ├─ Check if already completed (skip if yes)           │
│  │   ├─ Retry loop (task_max_attempts times):              │
│  │   │   └─ Call run_task()                                │
│  │   └─ On failure: mark with fail.flag                    │
│  └─ Send "DONE" message to run.py socket                   │
└──────────────────────┬──────────────────────────────────────┘
                       │ function call
                       ↓
┌─────────────────────────────────────────────────────────────┐
│               run_task() (Single Task Exec)                 │
│  ├─ PHASE 1: Env Reset (Lume/VMware/EC2)                   │
│  ├─ PHASE 2: SSH Connection                                │
│  ├─ PHASE 3: Env & Prep Commands                           │
│  ├─ PHASE 4: Optional In-Process Events                    │
│  ├─ PHASE 5: Agent Interaction Loop                        │
│  ├─ PHASE 6: In-Process Event Evaluation                   │
│  ├─ PHASE 7: Task Grading                                  │
│  └─ PHASE 8: Cleanup (try-finally)                         │
│      ├─ Disconnect VNC                                      │
│      └─ Stop & Cleanup Lume VM                             │
│                                                              │
│  Output:                                                     │
│  └─ {save_dir}/                                            │
│      ├─ eval_result.txt          [score or eval_failed]     │
│      ├─ distraction_result.txt    [if in_process task]      │
│      ├─ context/                  [conversation history]     │
│      └─ fail.flag                 [if task failed]           │
└──────────────────────────────────────────────────────────────┘
                       │ results
                       ↓
┌─────────────────────────────────────────────────────────────┐
│           {base_save_dir}/ (Result Structure)               │
│  ├─ sys_apps/                                               │
│  │   ├─ task_uuid_en_en/                                    │
│  │   │   ├─ eval_result.txt                                │
│  │   │   ├─ distraction_result.txt                         │
│  │   │   ├─ context/                                        │
│  │   │   └─ fail.flag (if failed)                          │
│  │   └─ task_uuid_zh_zh/                                    │
│  │       └─ (same structure)                               │
│  └─ safety/                                                 │
│      └─ (same structure, with distraction_result.txt)      │
└──────────────────────────────────────────────────────────────┘
```

---

## Architecture Patterns

### 1. **Multi-Backend Strategy Pattern**
- **Context**: VM environment management
- **Implementations**: Lume, VMware, AWS EC2
- **Selection**: CLI flag determines which backend used
- **Benefit**: Single codebase supports multiple platforms

### 2. **Retry Pattern with Exponential Decay**
- **Lume clone**: 3 retries
- **VMware revert**: 5 retries
- **SSH connect**: Timeout-based polling
- **Task execution**: task_max_attempts retries
- **Pre-command**: pre_command_max_trials retries

### 3. **Async Event Injection Pattern**
- **Background SSH command handler** for in-process events
- **Captures stdout/stderr** while agent runs
- **Evaluates against criteria** (gold vs. distraction)
- **Enables distraction testing** of agent focus

### 4. **State Machine for Task Lifecycle**
- States: pending → in_progress → completed (or failed)
- Transitions tracked via files: eval_result.txt, fail.flag
- Cleanup logic uses file presence as state indicator

### 5. **Process Supervisor with Watchdog**
- **run.py supervises testbench.py**
- **12-hour timeout** prevents indefinite hangs
- **Socket-based IPC** for completion signaling
- **SIGINT handler** for graceful shutdown

### 6. **Try-Finally Cleanup Pattern**
- **Guaranteed resource cleanup** even on exceptions
- **Two-level cleanup**: VNC disconnect + Lume VM stop
- **Exceptions logged but swallowed** to allow cleanup

---

## Configuration & Extension Points

### Adding New Languages
1. Add mapping in `constants.language_lookup_table`
2. Add snapshot names and AMIs to `constants.ami_lookup_table`
3. Add Lume VM names to `constants.lume_snapshot_lookup`
4. Create task JSONs with new language fields

### Adding New GUI Agents
1. Implement agent class with `.step()` method
2. Add to `agent/get_gui_agent.py` dispatcher
3. Pass `--gui_agent_name` on CLI

### Adding New VM Backends
1. Implement backend class (similar to VMwareTools, LumeTools)
2. Add backend-specific initialization in Phase 1 of `run_task()`
3. Add VNC client variant if needed

### Customizing Timeouts
1. `--snapshot_recovery_timeout_seconds`: VM startup
2. `--task_step_timeout`: Agent step timeout
3. `TESTBENCH_TIMEOUT_SECONDS` in run.py: Process watchdog

---

## Distributed System Design Implications

For planning a distributed version, consider:

1. **Work Queuing**:
   - Replace nested loops with queue-based task dispatch
   - Each worker pulls (task, language_combo) from queue
   - Idempotent: can rerun any task without conflicts

2. **State Management**:
   - File-based state (eval_result.txt, fail.flag) is good for distributed systems
   - Network filesystem (NFS) can serve as shared state store
   - Lock files prevent concurrent access to same task

3. **Resource Isolation**:
   - Each task runs in isolated VM (good for distribution)
   - No shared state during execution (good for parallelization)
   - Cleanup guarantees prevent resource leaks (good for reliability)

4. **Checkpointing**:
   - Completion checker `all_tasks_completed()` is fault-tolerant
   - Crashed workers automatically retried by testbench retry loop
   - Task directories can survive worker restarts

5. **Communication**:
   - Current socket-based IPC (run.py ↔ testbench.py) can become message queue
   - REST API can replace socket for cross-network coordination
   - Logging output can stream to centralized log aggregator

6. **Monitoring**:
   - 12-hour watchdog can become distributed health check
   - Status file can be polled by external monitor
   - Metrics (tasks/hour, failure rate) can be exported

