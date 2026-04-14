How macOSWorld tasks are scored: osascript commands, cold-start warmup, TCC permissions, and retry logic.

---

## Grading overview

Each task JSON contains a `grading_command` field: a list of `[osascript_command, score]` pairs. `LumeEvaluator.__call__` iterates the list and runs each command via `lume ssh`. The first command whose output contains `"true"` (case-insensitive) wins — the evaluator returns that pair's score. If no command matches, it returns `0`.

```
grading_command: [
  ["osascript -e '...' | grep -q 'expected' && echo True || echo False", 100],
  ["osascript -e '...' | grep -q 'partial' && echo True || echo False",  50],
]
```

### Binary grading

When `binary_grading=True` (the default), only entries where `score == 100` are evaluated. All other entries are filtered out before any command runs.

### eval_init_command

Before grading commands execute, `eval_init_command` (from `constants.py`) runs once. It checks whether the frontmost window is fullscreen via System Events and exits fullscreen with `Ctrl+Cmd+F` if so:

```
osascript -e 'tell application "System Events" to get value of attribute
  "AXFullScreen" of window 1 of (first application process whose frontmost
  is true)' | grep -q true && osascript -e 'tell application "System Events"
  to keystroke "f" using {control down, command down}'
```

## TCC permissions

osascript grading requires macOS Automation (TCC) permission for `sshd-keygen-wrapper` to control each app. 16 apps need permission:

| # | App | Permission type |
|---|-----|-----------------|
| 1 | Contacts | Automation + data access |
| 2 | Reminders | Automation + data access |
| 3 | Notes | Automation + data access |
| 4 | Calendar | Automation + data access |
| 5 | System Events | Accessibility |
| 6 | Finder | Automation + data access |
| 7 | Music | Automation |
| 8 | Keynote | Automation |
| 9 | Numbers | Automation |
| 10 | Pages | Automation |
| 11 | Script Editor | Automation |
| 12 | QuickTime Player | Automation |
| 13 | Automator | Automation |
| 14 | Xcode | Automation |

**Golden VM preparation** (`scripts/prepare_golden_vm.sh`): Run once on the golden VM before cloning. It triggers each TCC dialog and waits for manual "Allow" clicks via VNC. Clones inherit the granted permissions.

**Runtime fallback** (`_prewarm_apps` in `lume_utils.py`): If the golden VM was not prepared, triggers each probe and auto-clicks "Allow" via VNC using `Tab + Space`.

## Cold-start problem

On a freshly cloned VM, the first osascript call to any app forces:

- Process spawn and System Events daemon startup (2-3s)
- Application launch and Apple Events initialization (2-5s per app)
- Disk I/O for cold cache (2-4s per app)

With 12 apps, total cold-start penalty is 24-60+ seconds. The original 30s `before_grading_delay` was insufficient.

## Warmup strategy

`LumeEvaluator._pre_warmup_for_grading` runs once before any grading command executes:

1. Scans all grading commands and extracts unique app names via regex
2. For each app, calls `_warmup_app`:
   - `open -a "AppName"` (force-launch, 15s timeout)
   - Sleeps 5s for app initialization
   - Runs a heavy probe (real data query, not just `return 1`):
     - Reminders: `get the name of every list`
     - Contacts: `count every person`
     - Notes: `count every note`
     - Calendar: `get the name of every calendar`
     - Other apps: `return 1`
   - Sleeps 2s after successful probe (5s on failure)

This forces the full Apple Events scripting interface to initialize before timed grading begins.

## Timeout configuration

| Parameter | Value | Location |
|-----------|-------|----------|
| `SSH_TIMEOUT` | 60s | `lume_adapters.py` — `lume ssh -t` flag |
| `SUBPROCESS_TIMEOUT` | 75s | `lume_adapters.py` — Python `subprocess.run` hard kill |
| `GRADING_RETRY_COUNT` | 3 | `lume_adapters.py` — retries after first timeout |
| `before_grading_delay` | 30s (default) | Task JSON — sleep before grading starts |

## Retry logic

`LumeEvaluator.run_command` implements timeout-aware retry:

```
1. Run command via lume ssh (60s timeout, 75s hard kill)
2. If success or non-timeout error → return immediately
3. If "timed out" in output:
   a. Extract app name from command
   b. For attempt 1..3:
      - Log retry attempt
      - Warm up the app (_warmup_app)
      - Re-run the command
      - If success or non-timeout → return
4. Return last result (may still be failure)
```

Hung `lume ssh` processes are killed via `pkill -f "lume ssh {vm_name}"` on each timeout.

## Common grading failures

| Symptom | Cause | Fix |
|---------|-------|-----|
| `SSH operation timed out` | Cold app startup exceeds timeout | Increase `before_grading_delay`; verify golden VM was prepared |
| `execution error: not allowed` | Missing TCC permission | Re-run `prepare_golden_vm.sh` on golden VM |
| Score 0 on correct task | App still in fullscreen, grading queries wrong window | Verify `eval_init_command` ran; check fullscreen state |
| `No result returned` | App crashed or not running | Check if task `pre_command` launches the required app |
| Intermittent timeouts | VM under heavy I/O load | Reduce parallel VM count; increase `SUBPROCESS_TIMEOUT` |

## Key files

| File | Relevant code |
|------|---------------|
| `utils/lume_adapters.py` | `LumeEvaluator` class, timeout constants, retry logic |
| `utils/lume_utils.py` | `_prewarm_apps`, PROBES list, TCC auto-grant via VNC |
| `constants.py` | `eval_init_command` (fullscreen exit) |
| `scripts/prepare_golden_vm.sh` | Golden VM TCC preparation script |
| `utils/run_task.py` | Orchestration: delay → eval_init → grading |
