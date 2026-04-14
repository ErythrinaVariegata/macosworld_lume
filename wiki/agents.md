GUI agent system: pluggable agents that observe screenshots and emit VNC actions to complete tasks on a remote macOS desktop.

---

## Agent Interface

Every agent must implement two methods:

### `step()`

```python
def step(self, task_id, current_step, max_steps, env_language, task_language, task, task_step_timeout, save_dir) -> str
```
One iteration of the agent loop:

1. **Capture** a screenshot via `remote_client.capture_screenshot()`
2. **Call** the model with the task string and screenshot (`call_agent()`)
3. **Parse** the raw response into action dicts (`parse_agent_output()`)
4. **Execute** actions via VNC (`execute_actions()`)
5. **Save** the screenshot, raw response, and parsed actions to `save_dir/context/`

Returns a status string: `"unfinished"`, `"finished"`, or `"call_user"`.

### `save_conversation_history()`

```python
def save_conversation_history(self, save_dir: str)
```
Strips all images from the message history, then writes `chat_log.json` and `token_usage.json` to `save_dir/context/`.

## Factory: `get_gui_agent()`

`agent/get_gui_agent.py` is the single entry point. It takes `gui_agent_name` (string) and `remote_client` (VNCClient_SSH) and returns the matching agent instance.

Agent selection is a chain of `if/elif` checks on the name string:

| Name pattern | Agent class | Source |
|---|---|---|
| `gpt*/omniparser` | `OpenAI_OmniParser_Agent` | `agent/openai_omniparser.py` |
| `openai/computer-use-preview` | `OpenAI_CUA` | `agent/openai_cua.py` |
| `gpt*` | `OpenAI_General_Agent` | `agent/openai.py` |
| `claude-3-7-sonnet*/computer-use*` | `ClaudeComputerUseAgent` | `agent/anthropic.py` |
| `UI-TARS-7B-DPO` | `UITARS_GUI_AGENT` | `agent/uitars.py` |
| `showlab/ShowUI-2B` | `ShowUI_Agent` | `agent/showui.py` |
| `gemini*` | `Gemini_General_Agent` | `agent/gemini.py` |
| `qwen*` | `Qwen_GUI_AGENT` | `agent/qwen.py` |
| `tione*` | `TiOne_GUI_Agent` | `agent/tione.py` |

Raises `NotImplementedError` if no pattern matches.

## TiOne Agent (detailed)

**File:** `agent/tione.py`

### Connection

Uses the OpenAI Python SDK against an external endpoint. Requires env vars:

- `MODEL_BASE_URL` -- OpenAI-compatible API base URL (mandatory)
- `MODEL_API_KEY` -- API key (defaults to `"empty"`)

### System Prompt

A CUA-style prompt that defines a single `computer` tool inside `<tools>` XML. The model is instructed to return actions as:

```xml
<tool_call>
{"name": "computer", "arguments": {"action": "left_click", "coordinate": [x, y]}}
</tool_call>
```

### Action Space

| Action | Required params | Description |
|---|---|---|
| `key` | `text` | Press key combo (xdotool keysyms, `+` separator) |
| `type` | `text` | Type a string |
| `mouse_move` | `coordinate` | Move cursor to `[x, y]` |
| `left_click` | `coordinate`, optional `text` (modifier) | Click; modifier hold if `text` set |
| `left_click_drag` | `start_coordinate`, `coordinate` | Drag from start to end |
| `right_click` | `coordinate` | Right-click |
| `middle_click` | `coordinate` | Middle-click |
| `double_click` | `coordinate` | Double-click |
| `triple_click` | `coordinate` | Triple-click |
| `scroll` | `coordinate`, `scroll_direction`, `scroll_amount` | Scroll (amount * 100 px) |
| `wait` | `duration` | Sleep N seconds |
| `screenshot` | -- | No-op (automatic each step) |
| `terminate` | `status` (`success`/`failure`) | End the task |

### `parse_agent_output()`

1. Regex-extracts `<tool_call>...</tool_call>` blocks
2. Falls back to bare JSON lines with `"name"` field
3. Filters to `name == "computer"`, reads `arguments.action`
4. Maps each action to internal `{'func': ..., 'kwargs': ...}` dicts
5. Also detects `` ```DONE``` `` / `` ```FAIL``` `` text flags

### `execute_actions()`

Iterates parsed action dicts and dispatches to `remote_client` VNC methods:

- `move_to_pixel`, `left_click`, `double_click`, `right_click`, etc.
- `modifier_click` -- holds modifier key, moves, clicks, releases
- `scroll_{up,down,left,right}` with pixel amounts
- `type_text` / `hotkey` (key_press)
- `wait` -- `time.sleep()`
- `finished` / `call_user` -- returns terminal status

Includes retry logic (3 attempts, 5s delay) and HTML error page detection.

## Qwen Agent

**File:** `agent/qwen.py` -- Qwen2.5-VL via OpenAI-compatible API.

Key differences from TiOne:

- Tool name is `computer_use` (not `computer`)
- `key` action uses a `keys` array (joined with `-`), not a `text` string
- `scroll` uses a `pixels` number (positive = up, negative = down) instead of direction + amount
- `left_click_drag` normalizes coordinates to `[0, 1]` range via `drag_to()`
- No triple-click support
- No API retry logic
- Passes `max_tokens` to the API

## UI-TARS Agent

**File:** `agent/uitars.py` -- ByteDance UI-TARS-7B-DPO via local vLLM.

Key differences:

- **No XML tool calling.** Output format is plain text: `Thought: ...\nAction: ...`
- Action space uses function-call syntax: `click(start_box='(x,y)')`, `hotkey(key='...')`, `type(content='...')`, `scroll(start_box='...', direction='...')`, `drag(start_box='...', end_box='...')`
- Coordinates are **0-1000 normalized** (divided by 1000, multiplied by screen dimensions)
- Custom parser: `find_actions()` walks the string matching function names + balanced parens; `parse_kwargs()` handles `key='value'` pairs with escape sequences
- Connects to local vLLM (`http://127.0.0.1:8000/v1`), hardcoded `api_key="empty"`
- Uses `frequency_penalty=1` in API call
- System prompt is prepended to first user message (no separate system role)
- Supports `call_user()` action for unsolvable tasks

## Adding a New Agent

1. Create `agent/<name>.py` with a class implementing `step()` and `save_conversation_history()`
2. Define a system prompt constant (e.g., `MY_AGENT_SYSTEM_PROMPT`)
3. Accept `remote_client: VNCClient_SSH` in the constructor
4. Implement the internal pipeline: `format_messages()` -> `call_agent()` -> `parse_agent_output()` -> `execute_actions()`
5. Map model output actions to `{'func': ..., 'kwargs': ...}` dicts that dispatch to `remote_client` VNC methods
6. Return `"unfinished"`, `"finished"`, or `"call_user"` from `step()`
7. In `save_conversation_history()`, strip images then dump `chat_log.json` and `token_usage.json`
8. Register in `get_gui_agent.py`: add an `elif` branch matching your name pattern
9. Test with: `python run.py --gui_agent_name "your-pattern"`
