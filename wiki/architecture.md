Multilingual GUI agent benchmark that evaluates AI models on realistic macOS tasks inside disposable VMs.
---

## System Purpose

macOSWorld is a benchmark (accepted NeurIPS 2025) that measures how well AI agents interact with macOS GUI applications. It supports 8+ agent models, 5 languages, 8 task categories across 30+ native apps. The system spins up a macOS VM per task, lets an agent interact via VNC, then grades the result via SSH.

## Execution Flow

```
run.sh / CLI
  └─► run.py                          # outer loop, 12h timeout per cycle
        │
        ├─ cleanup.py                  # purge incomplete results in base_save_dir
        ├─ all_tasks_completed()       # scan results dir; if done → exit
        │
        └─ testbench.py (subprocess)   # socket-based IPC on ephemeral port
              │
              ├─ load task JSONs from paths_to_eval_tasks
              ├─ skip tasks with eval_result.txt (already graded)
              ├─ delete tasks with fail.flag (retry)
              │
              └─ for each (task, language):
                    run_task()
                      ├─ VM setup (clone/revert/AMI)
                      ├─ SSH connectivity check
                      ├─ VNC connect
                      ├─ env_init_command (dismiss crash dialogs, eject drives)
                      ├─ pre_command (task-specific setup)
                      ├─ agent loop (max_steps iterations):
                      │     screenshot → agent.step() → execute action → repeat
                      ├─ grading (eval_init_command → grading_command via SSH)
                      └─ cleanup (disconnect VNC, destroy ephemeral VM)
```

**`run.py` outer loop** (`run.py:69-141`): Runs `cleanup.py`, checks completion, spawns `testbench.py` as a subprocess. Uses a TCP socket (`socket.AF_INET`) to detect when testbench finishes. If no message arrives within `TESTBENCH_TIMEOUT_SECONDS` (12h), kills the subprocess and loops. On Ctrl+C, terminates child and calls `LumeTools.cleanup_stale_vms()`.

**`testbench.py` task iteration** (`testbench.py:62-180`): Builds a flat list of `(category, json_path)` tuples. For each language combination, checks if `eval_result.txt` exists (skip) or `fail.flag` exists (retry). Calls `run_task()` up to `task_max_attempts` times. On completion, sends `b"DONE"` back to the parent socket.

**`run_task()` execution** (`utils/run_task.py:34-390`): Three VM backends selected by args:
- **Lume**: `LumeTools.clone_and_start()` from a golden VM, direct VNC via `VNCClient_Lume`
- **VMware**: `VMwareTools.revert_to_snapshot()`, SSH-tunneled VNC via `VNCClient_SSH`
- **AWS EC2**: `create_replace_root_volume_task()` from AMI, SSH-tunneled VNC

## VM Lifecycle (Lume)

```
┌─────────────────┐
│  Golden VM       │  (stopped, read-only template per language)
│  e.g. golden_en  │
└────────┬────────┘
         │ clone_and_start()
         ▼
┌─────────────────┐
│  Ephemeral VM    │  macosworld_{uuid8}
│  ├─ SSH ready    │
│  ├─ VNC active   │
│  └─ task running │
└────────┬────────┘
         │ run_task() completes or fails
         ▼
┌─────────────────┐
│  stop_and_cleanup│  VM deleted, resources freed
└─────────────────┘
```

VMware follows the same pattern but uses snapshot revert instead of clone, and reuses the same VM.

## Key Files

| File | Purpose |
|------|---------|
| `run.sh` | Shell entry point: activate venv, set env vars, invoke `run.py` with Lume flags |
| `run.py` | Outer loop: cleanup → completion check → spawn testbench with 12h timeout |
| `testbench.py` | Iterate tasks/languages, skip completed, call `run_task()`, report done via socket |
| `cleanup.py` | Remove incomplete result directories from `base_save_dir` |
| `constants.py` | Screen dimensions (1024x768), AMI lookup table, env/eval init commands, Lume snapshot map |
| `utils/run_task.py` | Single-task executor: VM setup → SSH/VNC → agent loop → grading → cleanup |
| `utils/VNCClient.py` | `VNCClient_SSH` (SSH-tunneled) and `VNCClient_Lume` (direct) — screenshot, mouse, keyboard |
| `utils/vmware_utils.py` | VMware snapshot revert and VM state management via `vmrun` |
| `utils/lume_utils.py` | Lume VM clone, start, stop, cleanup via Lume CLI/API |
| `utils/lume_adapters.py` | Lume-specific adapters for `AsyncSSHCommandHandler` and `Evaluator` |
| `utils/evaluator.py` | Run grading commands over SSH, return eval result |
| `utils/async_utils.py` | `AsyncSSHCommandHandler` for in-process distraction events |
| `utils/completion_checker.py` | `all_tasks_completed()` — scan result dirs against task list |
| `utils/log.py` | `print_message()` formatted logging |
| `utils/languages.py` | `parse_language_list()` — parse `task_xx_env_yy` strings into tuples |
| `agent/get_gui_agent.py` | Factory: agent name string → agent instance |
| `agent/openai.py` | GPT-4o vision agent |
| `agent/anthropic.py` | Claude computer-use agent |
| `agent/gemini.py` | Gemini agent |
| `agent/uitars.py` | UI-TARS open-source agent |
| `agent/showui.py` | ShowUI open-source agent |
| `agent/template_for_custom_agent.py` | Skeleton for adding new agents |

## Directory Structure

```
macosworld_lume/
├── run.sh                    # shell entry point
├── run.py                    # outer loop
├── testbench.py              # task orchestrator
├── cleanup.py                # result cleanup
├── constants.py              # config, lookup tables
├── credential.pem            # SSH key (chmod 400)
│
├── agent/                    # AI agent implementations
│   ├── get_gui_agent.py      # factory
│   ├── openai.py, anthropic.py, gemini.py, ...
│   └── template_for_custom_agent.py
│
├── utils/                    # infrastructure
│   ├── run_task.py           # single-task execution
│   ├── VNCClient.py          # VNC + SSH client
│   ├── vmware_utils.py       # VMware backend
│   ├── lume_utils.py         # Lume backend
│   ├── lume_adapters.py      # Lume SSH/eval adapters
│   ├── evaluator.py          # grading
│   ├── completion_checker.py # progress tracking
│   └── ...
│
├── tasks/                    # benchmark task definitions (JSON)
│   ├── sys_apps/
│   ├── sys_and_interface/
│   ├── file_management/
│   ├── productivity/
│   ├── media/
│   ├── multi_apps/
│   ├── advanced/
│   └── safety/
│
├── results/                  # output (created at runtime)
│   └── {agent}/{category}/{uuid}_{task_lang}_{env_lang}/
│       ├── context/          # screenshots, conversation
│       ├── eval_result.txt   # grading output
│       └── fail.flag         # present if task failed
│
├── scripts/                  # analysis notebooks and utilities
└── wiki/                     # documentation
```

## Configuration Constants (`constants.py`)

- `SCREEN_WIDTH = 1024`, `SCREEN_HEIGHT = 768` — VM display resolution
- `language_lookup_table` — alias mapping (`cn` → `zh`, `jp` → `ja`)
- `ami_lookup_table` — snapshot name → AWS AMI ID (10 entries, 5 languages x 2 snapshot types)
- `lume_snapshot_lookup` — snapshot name → Lume golden VM name
- `env_init_command` — dismisses crash dialogs, ejects stale drives
- `eval_init_command` — exits fullscreen before grading
