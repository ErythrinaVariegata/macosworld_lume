from openai import OpenAI
import os
from utils.VNCClient import VNCClient_SSH
from utils.log import print_message
from agent.llm_utils import pil_to_b64
from PIL import Image
import json
import time
import re
from constants import SCREEN_WIDTH, SCREEN_HEIGHT


# Claude CUA-style system prompt adapted for text-based tool calling.
# Describes the full action space with pixel coordinates.
TIONE_SYSTEM_PROMPT = f"""You are a helpful assistant that can control a computer to complete tasks.

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{"type": "function", "function": {{"name": "computer", "description": "Use a mouse and keyboard to interact with a computer, and take screenshots.\\n* This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.\\n* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions.\\n* The screen's resolution is {SCREEN_WIDTH}x{SCREEN_HEIGHT} with pixel coordinates.\\n* Whenever you intend to move the cursor to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.\\n* If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.\\n* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked.", "parameters": {{"properties": {{"action": {{"description": "The action to perform. The available actions are:\\n\\n* `key`: Press a key or key-combination on the keyboard.\\n  - This supports xdotool keysyms, e.g. `Return`, `BackSpace`, `Tab`, `Escape`, `Delete`, `Left`, `Right`, `Up`, `Down`, and single characters.\\n  - To press multiple keys simultaneously, use `+` as separator, e.g. `command+c`, `command+v`, `command+space`, `ctrl+a`, `shift+Return`.\\n  - Required parameter: `text`.\\n\\n* `type`: Type a string of text on the keyboard. Use this for entering text into fields, search bars, etc.\\n  - Required parameter: `text`.\\n\\n* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.\\n  - Required parameter: `coordinate` [x, y].\\n\\n* `left_click`: Click the left mouse button at the specified coordinate.\\n  - Required parameter: `coordinate` [x, y].\\n  - Optional parameter: `text` — a modifier key to hold during the click (e.g. `command`, `shift`, `option`, `ctrl`).\\n\\n* `left_click_drag`: Click and drag from start_coordinate to coordinate.\\n  - Required parameters: `start_coordinate` [x, y], `coordinate` [x, y].\\n\\n* `right_click`: Right-click at the specified coordinate.\\n  - Required parameter: `coordinate` [x, y].\\n\\n* `middle_click`: Middle-click at the specified coordinate.\\n  - Required parameter: `coordinate` [x, y].\\n\\n* `double_click`: Double-click at the specified coordinate.\\n  - Required parameter: `coordinate` [x, y].\\n\\n* `triple_click`: Triple-click at the specified coordinate.\\n  - Required parameter: `coordinate` [x, y].\\n\\n* `scroll`: Scroll the mouse wheel.\\n  - Required parameters: `coordinate` [x, y], `scroll_direction` (one of: up, down, left, right), `scroll_amount` (integer, number of clicks).\\n\\n* `wait`: Wait for a specified duration.\\n  - Required parameter: `duration` (seconds).\\n\\n* `screenshot`: Take a screenshot of the screen.\\n\\n* `terminate`: Terminate the current task and report its completion status.\\n  - Required parameter: `status` (one of: success, failure).", "enum": ["key", "type", "mouse_move", "left_click", "left_click_drag", "right_click", "middle_click", "double_click", "triple_click", "scroll", "wait", "screenshot", "terminate"], "type": "string"}}, "text": {{"description": "Required by `action=key` and `action=type`. For `key`, use xdotool keysyms (e.g. `Return`, `command+c`). For `type`, the text string to type.", "type": "string"}}, "coordinate": {{"description": "[x, y]: The pixel coordinate. Required for click, scroll, and mouse_move actions.", "type": "array"}}, "start_coordinate": {{"description": "[x, y]: The starting pixel coordinate for `left_click_drag`.", "type": "array"}}, "scroll_direction": {{"description": "The direction to scroll: up, down, left, or right. Required by `action=scroll`.", "type": "string", "enum": ["up", "down", "left", "right"]}}, "scroll_amount": {{"description": "The number of scroll clicks. Required by `action=scroll`.", "type": "integer"}}, "duration": {{"description": "The number of seconds to wait. Required by `action=wait`.", "type": "number"}}, "status": {{"description": "The task completion status. Required by `action=terminate`.", "type": "string", "enum": ["success", "failure"]}}}}, "required": ["action"], "type": "object"}}}}}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": "computer", "arguments": <args-json-object>}}
</tool_call>

# Guidelines

* At the end of each step, always take a screenshot. In the next round, carefully evaluate if you have achieved the right outcome. Explicitly show your thinking: "I have evaluated step X..." If not correct, try again. Only when you confirm a step was executed correctly should you move on to the next one.
* When you think the task is completed, use `action=terminate` with `status=success`. When you think the task cannot be done, use `action=terminate` with `status=failure`. Try your best to complete the task before reporting failure.
* Your username is "ec2-user" and password is "000000"."""


class TiOne_GUI_Agent:
    def __init__(
        self,
        model: str,
        system_prompt: str,
        remote_client: VNCClient_SSH,
        screenshot_rolling_window: int,
        top_p: float,
        temperature: float,
    ):
        base_url = os.environ.get("MODEL_BASE_URL")
        api_key = os.environ.get("MODEL_API_KEY", "empty")

        if not base_url:
            raise ValueError(
                "MODEL_BASE_URL environment variable is required for TiOne agent. "
                "Set it to your OpenAI-compatible API endpoint."
            )

        self.prompt_client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.remote_client = remote_client
        self.only_n_most_recent_images = screenshot_rolling_window
        self.top_p = top_p
        self.temperature = temperature

        self.messages = []
        self.screenshots = []

        self.token_usage = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    # Maximum retries for transient API errors (e.g. 503)
    API_MAX_RETRIES = 3
    API_RETRY_DELAY = 5  # seconds

    def format_messages(self, task: str, screenshot: Image.Image):
        """Add task instruction (first turn only) and current screenshot to messages."""
        if len(self.messages) == 0:
            self.messages.append({
                "role": "system",
                "content": [{"type": "text", "text": self.system_prompt}]
            })
            self.messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Task: {task}"},
                    {
                        "type": "image_url",
                        "image_url": {"url": pil_to_b64(screenshot)}
                    },
                ]
            })
        else:
            self.messages.append({
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": pil_to_b64(screenshot)}
                    }
                ]
            })

    def filter_to_n_most_recent_images(self, n: int):
        """Keep only the N most recent images in the message history."""
        for message_index in range(len(self.messages) - 1, -1, -1):
            if self.messages[message_index]['role'] == 'user':
                if isinstance(self.messages[message_index]['content'], list):
                    for content_index in range(
                        len(self.messages[message_index]['content']) - 1, -1, -1
                    ):
                        if self.messages[message_index]['content'][content_index].get('type') == 'image_url':
                            if n > 0:
                                n -= 1
                            else:
                                del self.messages[message_index]['content'][content_index]
                    if len(self.messages[message_index]['content']) == 0:
                        del self.messages[message_index]

    def call_agent(self, task: str, screenshot: Image.Image) -> str:
        """Send the task and screenshot to the model and return raw response."""
        self.format_messages(task=task, screenshot=screenshot)
        self.filter_to_n_most_recent_images(self.only_n_most_recent_images)

        last_error = None
        for attempt in range(1, self.API_MAX_RETRIES + 1):
            try:
                response = self.prompt_client.chat.completions.create(
                    model=self.model,
                    messages=self.messages,
                    top_p=self.top_p,
                    temperature=self.temperature,
                )
                response_content = response.choices[0].message.content

                # Detect HTML error pages returned as content
                if response_content and response_content.strip().startswith("<html"):
                    raise RuntimeError(f"API returned HTML error page: {response_content[:200]}")

                # Append assistant response to history
                self.messages.append({
                    "role": "assistant",
                    "content": [{"type": "text", "text": response_content}]
                })

                # Track token usage
                if hasattr(response, 'usage') and response.usage:
                    self.token_usage.append({
                        "step": "step_index",
                        "prompt_tokens": response.usage.prompt_tokens,
                        "completion_tokens": response.usage.completion_tokens,
                    })
                    self.total_prompt_tokens += response.usage.prompt_tokens
                    self.total_completion_tokens += response.usage.completion_tokens

                return response_content

            except Exception as e:
                last_error = e
                if attempt < self.API_MAX_RETRIES:
                    print(f"API call failed (attempt {attempt}/{self.API_MAX_RETRIES}): {e}. Retrying in {self.API_RETRY_DELAY}s...")
                    time.sleep(self.API_RETRY_DELAY)
                else:
                    raise RuntimeError(
                        f"API call failed after {self.API_MAX_RETRIES} attempts. Last error: {last_error}"
                    )

    def parse_agent_output(self, raw_response: str) -> list:
        """Parse model response into action dicts.

        Supports <tool_call> JSON format with Claude CUA-style action space.
        """
        parsed_actions = []

        # Extract <tool_call> blocks
        tool_call_pattern = r'<tool_call>(.*?)</tool_call>'
        matches = re.findall(tool_call_pattern, raw_response, re.DOTALL)

        # Also try bare JSON objects with "name" field
        if not matches:
            for line in raw_response.split('\n'):
                line = line.strip()
                if line.startswith('{') and '"name"' in line:
                    matches.append(line)

        for match in matches:
            try:
                tool_call = json.loads(match.strip())
            except json.JSONDecodeError:
                print(f"Error parsing tool call JSON: {match[:100]}")
                continue

            if tool_call.get("name") != "computer":
                continue

            args = tool_call.get("arguments", {})
            action = args.get("action", "")

            if action == "key":
                text = args.get("text", "")
                if text:
                    # Convert Claude CUA key format (command+c) to our hotkey format
                    parsed_actions.append({'func': 'hotkey', 'kwargs': {'key': text}})

            elif action == "type":
                text = args.get("text", "")
                parsed_actions.append({'func': 'type_text', 'kwargs': {'text': text}})

            elif action == "mouse_move":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})

            elif action == "left_click" or action == "click":
                coord = args.get("coordinate", [])
                modifier = args.get("text", None)

                if modifier:
                    # Hold modifier key during click
                    parsed_actions.append({'func': 'modifier_click', 'kwargs': {
                        'x': int(coord[0]) if coord else 0,
                        'y': int(coord[1]) if coord else 0,
                        'modifier': modifier,
                    }})
                else:
                    if coord and len(coord) == 2:
                        parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                    parsed_actions.append({'func': 'left_click', 'kwargs': {}})

            elif action == "left_click_drag":
                start_coord = args.get("start_coordinate", [])
                end_coord = args.get("coordinate", [])
                if (start_coord and len(start_coord) == 2 and
                        end_coord and len(end_coord) == 2):
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(start_coord[0]), 'y': int(start_coord[1])}})
                    parsed_actions.append({'func': 'mouse_down', 'kwargs': {'button': 'left'}})
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(end_coord[0]), 'y': int(end_coord[1])}})
                    parsed_actions.append({'func': 'mouse_up', 'kwargs': {'button': 'left'}})

            elif action == "right_click":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                parsed_actions.append({'func': 'right_click', 'kwargs': {}})

            elif action == "middle_click":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                parsed_actions.append({'func': 'middle_click', 'kwargs': {}})

            elif action == "double_click":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                parsed_actions.append({'func': 'double_click', 'kwargs': {}})

            elif action == "triple_click":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                parsed_actions.append({'func': 'triple_click', 'kwargs': {}})

            elif action == "scroll":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                scroll_direction = args.get("scroll_direction", "down")
                scroll_amount = args.get("scroll_amount", 3)
                # Convert scroll clicks to pixel amount (matching Claude CUA: amount * 100)
                pixel_amount = scroll_amount * 100
                parsed_actions.append({'func': f'scroll_{scroll_direction}', 'kwargs': {'amount': pixel_amount}})

            elif action == "wait":
                duration = args.get("duration", 5)
                parsed_actions.append({'func': 'wait', 'kwargs': {'seconds': duration}})

            elif action == "screenshot":
                # Screenshot is handled automatically at each step; skip
                pass

            elif action == "terminate":
                status = args.get("status", "success")
                parsed_actions.append({'func': 'finished', 'kwargs': {'status': status}})

        # Also check for DONE/FAIL flags in text (Claude CUA convention)
        if "```DONE```" in raw_response:
            parsed_actions.append({'func': 'finished', 'kwargs': {'status': 'success'}})
        elif "```FAIL```" in raw_response:
            parsed_actions.append({'func': 'finished', 'kwargs': {'status': 'failure'}})

        return parsed_actions

    def execute_actions(self, actions: list) -> str:
        """Execute parsed actions via VNC remote_client.

        Returns status: 'unfinished', 'finished', or 'call_user'.
        """
        status = 'unfinished'
        for action in actions:
            act = action['func']
            kwargs = action['kwargs']
            try:
                if act == 'left_click':
                    self.remote_client.left_click()
                elif act == 'double_click':
                    self.remote_client.double_click()
                elif act == 'triple_click':
                    self.remote_client.triple_click()
                elif act == 'right_click':
                    self.remote_client.right_click()
                elif act == 'middle_click':
                    self.remote_client.middle_click()
                elif act == 'move_to_pixel':
                    self.remote_client.move_to_pixel(**kwargs)
                elif act == 'mouse_down':
                    self.remote_client.mouse_down(**kwargs)
                elif act == 'mouse_up':
                    self.remote_client.mouse_up(**kwargs)
                elif act == 'type_text':
                    self.remote_client.type_text(**kwargs)
                elif act == 'hotkey':
                    self.remote_client.key_press(**kwargs)
                elif act == 'modifier_click':
                    # Hold modifier, move, click, release modifier
                    x = kwargs['x']
                    y = kwargs['y']
                    modifier = kwargs['modifier']
                    modifier = self.remote_client._filter_key(modifier)
                    self.remote_client.client.keyDown(modifier)
                    self.remote_client.move_to_pixel(x, y)
                    self.remote_client.left_click()
                    self.remote_client.client.keyUp(modifier)
                elif act == 'scroll_up':
                    self.remote_client.scroll_up(kwargs.get('amount', 300), by_pixel=True)
                elif act == 'scroll_down':
                    self.remote_client.scroll_down(kwargs.get('amount', 300), by_pixel=True)
                elif act == 'scroll_left':
                    self.remote_client.scroll_left(kwargs.get('amount', 300), by_pixel=True)
                elif act == 'scroll_right':
                    self.remote_client.scroll_right(kwargs.get('amount', 300), by_pixel=True)
                elif act == 'wait':
                    time.sleep(kwargs.get('seconds', 5))
                elif act in ['finished', 'call_user']:
                    status = act
                time.sleep(self.remote_client.action_interval_seconds)
            except Exception as e:
                print(f'Error executing action {action}: {e}')
        return status

    def step(
        self,
        task_id: int,
        current_step: int,
        max_steps: int,
        env_language: str,
        task_language: str,
        task: str,
        task_step_timeout: int,
        save_dir: str,
    ):
        # Capture screenshot
        print_message(
            title=f'Task {task_id}/{env_language}/{task_language} Step {current_step}/{max_steps}',
            content='Capturing screenshot...',
        )
        current_screenshot = self.remote_client.capture_screenshot()

        # Prediction
        print_message(
            title=f'Task {task_id}/{env_language}/{task_language} Step {current_step}/{max_steps}',
            content='Calling GUI agent...',
        )
        raw_response = self.call_agent(task=task, screenshot=current_screenshot)

        # Action
        parsed_actions = self.parse_agent_output(raw_response)
        actions_summary = '; '.join(
            a['func'] + (' ' + str(a['kwargs']) if a['kwargs'] else '')
            for a in parsed_actions
        ) or '(empty)'
        print_message(
            title=f'Task {task_id}/{env_language}/{task_language} Step {current_step}/{max_steps}',
            content=f'Actuating: {actions_summary}',
        )
        status = self.execute_actions(parsed_actions)

        # Save screenshot
        current_screenshot.save(
            os.path.join(save_dir, 'context', f'step_{str(current_step).zfill(3)}.png')
        )

        # Save raw response
        with open(
            os.path.join(save_dir, 'context', f'step_{str(current_step).zfill(3)}_raw_response.txt'), 'w'
        ) as f:
            f.write(raw_response)

        # Save parsed actions
        with open(
            os.path.join(save_dir, 'context', f'step_{str(current_step).zfill(3)}_parsed_actions.json'), 'w'
        ) as f:
            json.dump(parsed_actions, f, indent=4)

        return status

    def save_conversation_history(self, save_dir: str):
        """Save conversation history and token usage to disk."""
        self.filter_to_n_most_recent_images(0)

        chat_log_path = os.path.join(save_dir, 'context', 'chat_log.json')
        with open(chat_log_path, 'w') as f:
            json.dump(self.messages, f)

        self.token_usage.append({
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
        })
        token_path = os.path.join(save_dir, 'context', 'token_usage.json')
        with open(token_path, 'w') as f:
            json.dump(self.token_usage, f)
