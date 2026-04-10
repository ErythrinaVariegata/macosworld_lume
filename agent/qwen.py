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


QWEN_SYSTEM_PROMPT = f"""You are a helpful assistant

# Tools

You may call one or more functions to assist with the user query.

You are provided with function signatures within <tools></tools> XML tags:
<tools>
{{"type": "function", "function": {{"name_for_human": "computer_use", "name": "computer_use", "description": "Use a mouse and keyboard to interact with a computer, and take screenshots.\\n* This is an interface to a desktop GUI. You do not have access to a terminal or applications menu. You must click on desktop icons to start applications.\\n* Some applications may take time to start or process actions, so you may need to wait and take successive screenshots to see the results of your actions. E.g. if you click on Firefox and a window doesn't open, try wait and taking another screenshot.\\n* The screen's resolution is {SCREEN_WIDTH}x{SCREEN_HEIGHT}.\\n* Whenever you intend to move the cursor to click on an element like an icon, you should consult a screenshot to determine the coordinates of the element before moving the cursor.\\n* If you tried clicking on a program or link but it failed to load, even after waiting, try adjusting your cursor position so that the tip of the cursor visually falls on the element that you want to click.\\n* Make sure to click any buttons, links, icons, etc with the cursor tip in the center of the element. Don't click boxes on their edges unless asked.", "parameters": {{"properties": {{"action": {{"description": "The action to perform. The available actions are:\\n* `key`: Performs key down presses on the arguments passed in order, then performs key releases in reverse order.\\n* `type`: Type a string of text on the keyboard.\\n* `mouse_move`: Move the cursor to a specified (x, y) pixel coordinate on the screen.\\n* `left_click`: Click the left mouse button.\\n* `left_click_drag`: Click and drag the cursor to a specified (x, y) pixel coordinate on the screen.\\n* `right_click`: Click the right mouse button.\\n* `middle_click`: Click the middle mouse button.\\n* `double_click`: Double-click the left mouse button.\\n* `scroll`: Performs a scroll of the mouse scroll wheel.\\n* `wait`: Wait specified seconds for the change to happen.\\n* `terminate`: Terminate the current task and report its completion status.", "enum": ["key", "type", "mouse_move", "left_click", "left_click_drag", "right_click", "middle_click", "double_click", "scroll", "wait", "terminate"], "type": "string"}}, "keys": {{"description": "Required only by `action=key`.", "type": "array"}}, "text": {{"description": "Required only by `action=type`.", "type": "string"}}, "coordinate": {{"description": "(x, y): The x (pixels from the left edge) and y (pixels from the top edge) coordinates to move the mouse to. Required only by `action=mouse_move` and `action=left_click_drag`.", "type": "array"}}, "pixels": {{"description": "The amount of scrolling to perform. Positive values scroll up, negative values scroll down. Required only by `action=scroll`.", "type": "number"}}, "time": {{"description": "The seconds to wait. Required only by `action=wait`.", "type": "number"}}, "status": {{"description": "The status of the task. Required only by `action=terminate`.", "type": "string", "enum": ["success", "failure"]}}}}, "required": ["action"], "type": "object"}}, "args_format": "Format the arguments as a JSON object."}}}}
</tools>

For each function call, return a json object with function name and arguments within <tool_call></tool_call> XML tags:
<tool_call>
{{"name": <function-name>, "arguments": <args-json-object>}}
</tool_call>"""


class Qwen_GUI_AGENT:
    def __init__(
        self,
        model: str,
        system_prompt: str,
        remote_client: VNCClient_SSH,
        only_n_most_recent_images: int,
        max_tokens: int,
        top_p: float,
        temperature: float,
    ):
        base_url = os.environ.get("MODEL_BASE_URL")
        api_key = os.environ.get("MODEL_API_KEY", "empty")

        if not base_url:
            raise ValueError(
                "MODEL_BASE_URL environment variable is required for Qwen agent. "
                "Set it to your OpenAI-compatible API endpoint."
            )

        self.prompt_client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.system_prompt = system_prompt
        self.remote_client = remote_client
        self.only_n_most_recent_images = only_n_most_recent_images
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature

        self.messages = []
        self.screenshots = []

        self.token_usage = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

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

        response = self.prompt_client.chat.completions.create(
            model=self.model,
            messages=self.messages,
            max_tokens=self.max_tokens,
            top_p=self.top_p,
            temperature=self.temperature,
        )
        response_content = response.choices[0].message.content

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

    def parse_agent_output(self, raw_response: str) -> list:
        """Parse model response containing <tool_call> XML tags into action dicts.

        Each returned dict has 'func' and 'kwargs' keys, matching the pattern
        used by uitars.py / openai.py execute_actions methods.
        """
        parsed_actions = []

        # Extract tool calls from <tool_call>...</tool_call>
        tool_call_pattern = r'<tool_call>(.*?)</tool_call>'
        matches = re.findall(tool_call_pattern, raw_response, re.DOTALL)

        # Fallback: try to find bare JSON objects if no XML tags
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

            if tool_call.get("name") != "computer_use":
                continue

            args = tool_call.get("arguments", {})
            action = args.get("action", "")

            if action == "left_click":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                parsed_actions.append({'func': 'left_click', 'kwargs': {}})

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

            elif action == "mouse_move":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})

            elif action == "left_click_drag":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'drag_to', 'kwargs': {
                        'x': int(coord[0]) / SCREEN_WIDTH,
                        'y': int(coord[1]) / SCREEN_HEIGHT,
                    }})

            elif action == "type":
                text = args.get("text", "")
                parsed_actions.append({'func': 'type_text', 'kwargs': {'text': text}})

            elif action == "key":
                keys = args.get("keys", [])
                if isinstance(keys, str):
                    keys = [keys]
                # Join keys with '-' for hotkey format (e.g. ['ctrl', 'c'] -> 'ctrl-c')
                key_str = '-'.join(keys) if keys else ''
                if key_str:
                    parsed_actions.append({'func': 'hotkey', 'kwargs': {'key': key_str}})

            elif action == "scroll":
                coord = args.get("coordinate", [])
                if coord and len(coord) == 2:
                    parsed_actions.append({'func': 'move_to_pixel', 'kwargs': {'x': int(coord[0]), 'y': int(coord[1])}})
                pixels = args.get("pixels", 0)
                if pixels > 0:
                    parsed_actions.append({'func': 'scroll_up', 'kwargs': {}})
                elif pixels < 0:
                    parsed_actions.append({'func': 'scroll_down', 'kwargs': {}})

            elif action == "wait":
                wait_time = args.get("time", 5)
                parsed_actions.append({'func': 'wait', 'kwargs': {'seconds': wait_time}})

            elif action == "terminate":
                status = args.get("status", "success")
                parsed_actions.append({'func': 'finished', 'kwargs': {'status': status}})

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
                elif act == 'drag_to':
                    self.remote_client.drag_to(**kwargs)
                elif act == 'type_text':
                    self.remote_client.type_text(**kwargs)
                elif act == 'hotkey':
                    self.remote_client.key_press(**kwargs)
                elif act == 'scroll_up':
                    self.remote_client.scroll_up(0.5)
                elif act == 'scroll_down':
                    self.remote_client.scroll_down(0.5)
                elif act == 'scroll_left':
                    self.remote_client.scroll_left(0.5)
                elif act == 'scroll_right':
                    self.remote_client.scroll_right(0.5)
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
            content='Calling Qwen2.5-VL agent...',
        )
        raw_response = self.call_agent(task=task, screenshot=current_screenshot)

        # Action
        print_message(
            title=f'Task {task_id}/{env_language}/{task_language} Step {current_step}/{max_steps}',
            content='Actuating...',
        )
        parsed_actions = self.parse_agent_output(raw_response)
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
        # Remove all images before saving to reduce file size
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
