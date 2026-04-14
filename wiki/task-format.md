Task JSON format, language system, categories, and grading specification.

---

## Task JSON Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `id` | `string` (UUID) | yes | Unique task identifier |
| `snapshot` | `dict[lang → string]` | yes | Maps env language code to VM snapshot name (e.g. `{"en": "snapshot_used_en"}`) |
| `force_snapshot_recovery` | `bool` | no | Force VM snapshot revert before task |
| `task` | `dict[lang → string]` | yes | Maps task language code to instruction text |
| `grading_command` | `list[[cmd, score], ...]` | yes | osascript/shell commands with point values (see Grading) |
| `pre_command` | `string \| dict[lang → string]` | no | Shell command(s) to run before the task starts. Dict form selects by `env_language` |
| `before_action_delay_seconds` | `int` | no | Seconds to wait after env setup, before agent begins |
| `before_grading_delay_seconds` | `int` | no | Seconds to wait after agent finishes, before grading |
| `in_process` | `[cmd, start_step, gold_elements, distracting_elements]` | no | Async distraction event injected mid-task (safety tasks) |
| `force_error_free_prep` | `bool` | no | When `true`, abort if `pre_command` fails after max retries |

### Supported language codes

`en`, `zh`, `ar`, `ja`, `ru` — used as keys in both `snapshot` and `task`.

## Language System

### CLI format

```
--languages task_xx_env_yy [task_xx_env_yy ...]
```

Parsed by `utils/languages.py` via regex `task_([a-z]{2})_env_([a-z]{2})` into `(task_lang, env_lang)` tuples.

- **task_lang** — language of the instruction shown to the agent
- **env_lang** — language/locale of the macOS VM snapshot

### Alias table (`constants.py`)

```python
language_lookup_table = {"cn": "zh", "jp": "ja"}
```

Aliases are resolved before matching against `task["task"]` and `task["snapshot"]`. Tasks missing the requested language are skipped.

## Task Categories

Directories under `tasks/`:

| Category | Description |
|----------|-------------|
| `advanced` | Complex multi-step tasks |
| `file_management` | File/folder operations |
| `media` | Media/image/audio tasks |
| `multi_apps` | Cross-application workflows |
| `productivity` | Productivity app tasks |
| `safety` | Safety & distraction-handling tasks |
| `sys_and_interface` | System settings & UI |
| `sys_apps` | System application tasks |
| `sys_apps_single` | Single system-app tasks |

Each directory contains `.json` task files. The category name is derived from the directory basename.

## Grading Command Format

```json
"grading_command": [
  ["osascript -e '...' && echo \"True\" || echo \"False\"", 100]
]
```

Each element is `[shell_command, points]`. The evaluator runs commands via SSH and sums points for passing checks. Total score ≤ 100. Negative result means eval failure.

## In-Process Events

```json
"in_process": [command, start_timestep, gold_elements, distracting_elements]
```

- `command` — async shell command injected at `start_timestep`
- `gold_elements` — correct response strings (stdout match → `"gold"`)
- `distracting_elements` — distractor strings (stdout match → `"distracted"`)
- No match → `"error_no_match"`; command killed before completion → `"not_handled"`

Result saved to `distraction_result.txt`.

## Save Directory Structure

```
{base_save_dir}/
  {category}/
    {task_uuid}_{task_lang}_{env_lang}/
      context/          # Agent screenshots & step data
      eval_result.txt   # Score or "eval_failed"
      distraction_result.txt  # (safety tasks only)
      fail.flag         # Written on task failure, cleared on retry
```

Existing `eval_result.txt` causes the task to be skipped. Existing `fail.flag` triggers cleanup and retry.
