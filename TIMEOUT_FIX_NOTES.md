# SSH Timeout Improvements for Cold VM osascript Grading

## Problem Statement

When executing osascript grading commands on freshly cloned macOS VMs (Lume or VMware), many tasks fail with "SSH operation timed out" errors. Analysis identified that 12 unique macOS applications used in grading commands experience 24-60+ seconds of cold-start penalties on cold VMs.

### Root Causes

1. **SSH timeout was too short**: 30 seconds insufficient for cold VM startup
2. **12 macOS applications with cold-start penalties**:
   - System Events: 291 uses (72% of all commands)
   - Notes: 65 uses
   - Numbers: 48 uses  
   - Pages: 25 uses
   - Keynote: 25 uses
   - Contacts: 10 uses
   - Reminders: 8 uses
   - QuickTime Player: 5 uses
   - Script Editor: 2 uses
   - Finder: 2 uses
   - Music: 2 uses

3. **Cold-start penalty breakdown**:
   - First osascript call: 2-3 seconds (process spawn)
   - System Events initialization: 1-2 seconds (accessibility framework)
   - Application launch/activation: 2-5 seconds per app
   - **Total for complex grading**: 24-60+ seconds minimum

## Solutions Implemented

### 1. Increased SSH Timeout for Lume (lume_adapters.py)
- **SSH_TIMEOUT**: 30s → 90s (lume ssh -t parameter)
- **SUBPROCESS_TIMEOUT**: 45s → 120s (Python subprocess hard timeout)

### 2. Added SSH Timeout for VMware (evaluator.py)
- **SSH_TIMEOUT**: Added 120s timeout (was previously no timeout)
- **Error handling**: Now explicitly catches subprocess.TimeoutExpired

### 3. Timing Breakdown for Cold VM

```
VM Clone + Start:           ~10-20s
env_init_command:           ~5s (system cleanup)
Task pre_command:           ~5-10s (if present)
before_action_delay:        ~10s (configured)
GUI agent interaction:      ~20-40s typical
before_grading_delay:       ~30s (task-specific)
eval_init_command:          ~2-3s (first osascript call)
Grading commands:           ~15-30s (cold app startup + osascript execution)
───────────────────────────────────────────
Total for cold VM:          ~90-150+ seconds
```

### 4. What Each Timeout Controls

| Timeout | Where | Effect | New Value |
|---------|-------|--------|-----------|
| SSH_TIMEOUT (Lume) | lume_adapters.py | lume ssh -t parameter | 90s |
| SUBPROCESS_TIMEOUT (Lume) | lume_adapters.py | Python hard timeout | 120s |
| SSH_TIMEOUT (Evaluator) | evaluator.py | Python hard timeout | 120s |
| before_grading_delay | task JSON | Wait before grading starts | Varies (30s current) |
| task_step_timeout | CLI arg | Timeout for GUI agent steps | 120s (CLI default) |

## Recommendations

### For Task Definitions

Current `before_grading_delay_seconds` values are typically 30s. For cloned VMs:

- **Minimum safe value**: 30s (as currently configured)
- **Recommended for cloned VMs**: 60s (ensures warm VM state after GUI interaction)
- **Maximum safe value**: 90s (diminishing returns after warm-up)

### For Production Usage

1. **Cold VM mode** (each task gets a fresh clone):
   - Use before_grading_delay_seconds: 60
   - SSH timeouts: 120s (already implemented)

2. **Warm VM mode** (VM reused across tasks):
   - Use before_grading_delay_seconds: 30
   - SSH timeouts: 60-90s should suffice

3. **Monitoring**:
   - Check eval_result.txt files for timeout errors
   - Pattern: "eval_failed" + "SSH operation timed out"
   - Consider adjusting before_grading_delay if failures persist

## Testing the Fix

To verify the timeout improvements:

```bash
# Run a single task with tione agent (fastest)
python3 run.py \
  --gui_agent_name tione \
  --paths_to_eval_tasks tasks/sys_apps \
  --languages en_en \
  --lume_golden_vm golden_used_en \
  --max-steps 5

# Check results
find results -name "eval_result.txt" -exec cat {} \;
```

## Technical Details

### Lume Mode (Apple Silicon Mac)
- Uses `lume ssh` wrapper command
- SSH_TIMEOUT: controls lume ssh -t (command timeout)
- SUBPROCESS_TIMEOUT: controls Python process hard kill

### VMware Mode (Linux/Windows Host)
- Uses raw SSH with PEM key
- SSH_TIMEOUT: controls subprocess.check_output timeout
- Explicit TimeoutExpired exception handling

## Related Files

- utils/lume_adapters.py - Lume SSH timeouts
- utils/evaluator.py - VMware SSH timeouts
- utils/run_task.py - Task orchestration and before_grading_delay
- tasks/**/*.json - Individual task configurations

## Commit

This fix was implemented in: `27e896d`

```
fix: increase SSH timeouts for cold VM osascript grading commands

- Lume SSH_TIMEOUT: 30s → 90s
- Lume SUBPROCESS_TIMEOUT: 45s → 120s  
- Evaluator SSH_TIMEOUT: added 120s for VMware mode
```
