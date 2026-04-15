Detailed CLI parameters, function signatures, deployment examples, and supporting utilities reference.
---

## CLI Parameters

### Required

| Flag | Type | Description |
|------|------|-------------|
| `--gui_agent_name` | str | Agent to use (`tione`, `showui`, `openai`, `anthropic`, `gemini`, `uitars`, `qwen`) |
| `--paths_to_eval_tasks` | str+ | One or more paths to task JSON directories |
| `--languages` | str+ | Language combos in `task_XX_env_YY` format (e.g. `task_en_env_en`, `task_zh_env_zh`) |

### VM Backend (one required)

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--lume_golden_vm` | str | None | Enable Lume mode; golden VM name prefix |
| `--vmx_path` | str | None | VMware .vmx file path |
| `--instance_id` | str | None | AWS EC2 instance ID |

### Connection

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--guest_username` | str | `ec2-user` | SSH login (auto-set to `lume` in Lume mode) |
| `--guest_password` | str | `000000` | SSH password (auto-set to `lume` in Lume mode) |
| `--ssh_host` | str | None | Direct SSH host for pre-existing VM |
| `--ssh_pkey` | str | `credential.pem` | Path to SSH private key |

### Timeouts & Retries

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--snapshot_recovery_timeout_seconds` | int | 120 | VM startup timeout |
| `--pre_command_max_trials` | int | 3 | Pre-command retry count |
| `--task_max_attempts` | int | 2 | Task-level retry count |
| `--task_step_timeout` | int | 120 | Agent step timeout (seconds) |
| `--max-steps` | int | 15 | Max agent interaction steps per task |

### Other

| Flag | Type | Default | Description |
|------|------|---------|-------------|
| `--base_save_dir` | str | `./results` | Root output directory |
| `--override_env_reset` | bool | False | Manual reset mode (inserts breakpoint) |

## Key Function Signatures

### `run_task()`

```python
def run_task(
    task_id: str,                           # display label, e.g. "(1/50)"
    task_dict: dict,                        # loaded task JSON
    task_language: str,                     # e.g. "en", "zh"
    env_language: str,                      # e.g. "en", "zh"
    save_dir: str,                          # output directory
    snapshot_name: str,                     # e.g. "snapshot_used_en"
    instance_id: str,                       # AWS EC2 instance ID
    snapshot_recovery_timeout_seconds: int,
    override_env_reset: bool,
    vmx_path: str,
    guest_username: str,
    guest_password: str,
    ssh_host: str,
    ssh_pkey: str,
    gui_agent_name: str,
    max_steps: int,
    task_step_timeout: int,
    pre_command_max_trials: int,
    env_init_command: str,
    eval_init_command: str,
    lume_golden_vm: str = None,
)
```

### `LumeTools.__init__()`

```python
LumeTools(
    vm_name: str,           # ephemeral VM name (macosworld_{uuid8})
    username: str = "lume",
    password: str = "lume",
)
```

Key methods: `clone_and_start(golden_vm_name, timeout)`, `stop_and_cleanup()`, `cleanup_stale_vms()` (class method).

### `all_tasks_completed()`

```python
def all_tasks_completed(
    base_save_dir: str,
    paths_to_eval_tasks: List[str],
    languages: List[str],
) -> bool
```

Returns `True` iff every (task, language) combination has a valid `eval_result.txt` with an integer score on line 1. For `safety` category tasks, `distraction_result.txt` must also exist.

## Supporting Utilities

| Module | Purpose |
|--------|---------|
| `utils/log.py` | `print_message(content, title)` — timestamped formatted logging |
| `utils/timeout.py` | `timeout(seconds)` context manager using Unix SIGALRM |
| `utils/languages.py` | `parse_language_list(["task_en_env_zh"])` → `[("en", "zh")]` |
| `utils/completion_checker.py` | `all_tasks_completed()` — scan result dirs against task list |
| `utils/VNCClient.py` | `VNCClient_SSH` (tunneled) and `VNCClient_Lume` (direct) |
| `utils/evaluator.py` | Run grading commands over SSH, return score or error |
| `utils/lume_utils.py` | Lume VM lifecycle: clone, start, stop, cleanup |
| `utils/lume_adapters.py` | `LumeEvaluator`, `LumeAsyncSSHCommandHandler` |
| `utils/async_utils.py` | `AsyncSSHCommandHandler` for background distraction events |
| `utils/vmware_utils.py` | VMware snapshot revert via `vmrun` |

## Deployment Examples

### Lume (macOS Apple Silicon)

```bash
source .venv/bin/activate
python run.py \
  --gui_agent_name tione \
  --paths_to_eval_tasks ./tasks/sys_apps_single \
  --languages task_zh_env_zh \
  --lume_golden_vm macos-tahoe-cua_macosworld \
  --base_save_dir ./results/output
```

### VMware

```bash
python run.py \
  --gui_agent_name showui \
  --paths_to_eval_tasks ./tasks/sys_apps \
  --languages task_en_env_en \
  --vmx_path /path/to/vm.vmx \
  --snapshot_recovery_timeout_seconds 300
```

### AWS EC2

```bash
python run.py \
  --gui_agent_name showui \
  --paths_to_eval_tasks ./tasks/sys_apps ./tasks/safety \
  --languages task_en_env_en task_zh_env_zh \
  --instance_id i-0123456789abcdef0
```

### Custom Timeouts

```bash
python run.py \
  --gui_agent_name tione \
  --paths_to_eval_tasks ./tasks/advanced \
  --languages task_en_env_en \
  --lume_golden_vm macos-tahoe-cua_macosworld \
  --task_max_attempts 3 \
  --task_step_timeout 300 \
  --pre_command_max_trials 5 \
  --max-steps 25
```

## Internal Constants

| Constant | Value | Location |
|----------|-------|----------|
| `SCREEN_WIDTH` | 1024 | `constants.py` |
| `SCREEN_HEIGHT` | 768 | `constants.py` |
| `TESTBENCH_TIMEOUT_SECONDS` | 43200 (12h) | `run.py` |

## See Also

- [architecture](architecture.md) — execution flow and state machine
- [lume-backend](lume-backend.md) — Lume-specific setup and troubleshooting
- [agents](agents.md) — agent interface and how to add new agents
- [task-format](task-format.md) — task JSON schema
