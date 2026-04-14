import io
import os
from PIL import Image
import time
import uuid
# import copy
from vncdotool import api
from vncdotool.client import KEYMAP
from sshtunnel import SSHTunnelForwarder
from utils.log import print_message
from utils.vmware_utils import VMwareTools
import subprocess

class AttributeContainer:
    pass

class VNCClient:
    def __init__(self, host, username, password):
        self.vnc_host = host
        self.guest_username = username
        self.guest_password = password
        self.client = None

    def connect(self):
        """Connect to the VNC server."""
        self.client = api.connect(self.vnc_host, username=self.guest_username, password=self.guest_password)

    def capture_screenshot(self):
        """Capture a screenshot and return it as a PIL Image."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        fp = io.BytesIO()
        fp.name = 'screenshot.png'
        self.client.captureScreen(fp)
        fp.seek(0)
        image = Image.open(fp)
        del fp
        return image

    def left_click(self):
        """Perform a left mouse click."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        self.client.mouseDown(1)
        self.client.mouseUp(1)

    def middle_click(self):
        """Perform a middle mouse click."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        self.client.mouseDown(2)
        self.client.mouseUp(2)

    def right_click(self):
        """Perform a right mouse click."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        self.client.mouseDown(3)
        self.client.mouseUp(3)

    def move_to(self, x, y):
        """Move the mouse to the coordinates (x, y)."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        self.client.mouseMove(x, y)

    def key_press(self, key):
        """Press a key on the keyboard."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        self.client.keyPress(key)

    def type_text(self, text):
        """Type a string of text."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        for char in text:
            self.client.keyPress(char)

    def disconnect(self):
        """Disconnect from the VNC server."""
        if self.client is None:
            raise ConnectionError("VNC client is not connected.")
        
        self.client.disconnect()
        self.client = None


import time

class VNCClient_SSH:
    def __init__(self, guest_username, guest_password, ssh_host, ssh_pkey, retry_attempts=3, retry_delay=5, action_interval_seconds=1, vmx_path=None, vnc_connection_timeout=600):
        self.guest_username = guest_username
        self.guest_password = guest_password
        self.ssh_host = ssh_host
        self.ssh_pkey = ssh_pkey
        self.tunnel = None
        self.client = None
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.action_interval_seconds = action_interval_seconds
        self.vmx_path = vmx_path
        self.vnc_connection_timeout = vnc_connection_timeout

        if self.vmx_path is not None:
            self.vmware_tools = VMwareTools(
                guest_username = guest_username,
                guest_password = guest_password,
                ssh_host = ssh_host,
                ssh_pkey = ssh_pkey,
                vmx_path = vmx_path
            )

    def check_ssh_connectivity(self):
        """Check if SSH connection can be established. Returns True if successful, False otherwise."""
        try:
            temp_tunnel = SSHTunnelForwarder(
                (self.ssh_host, 22),
                ssh_username=self.guest_username,
                ssh_pkey=self.ssh_pkey,
                remote_bind_address=('localhost', 5900),
                allow_agent=False,
                host_pkey_directories=None,
            )
            temp_tunnel.start()
            temp_tunnel.stop()
            return True
        except Exception:
            return False
        
    def run_ssh_command(self, command: str) -> str:
        command = command.replace('\\', '\\\\').replace('"', '\\"').replace('$', '\\$')
        ssh_command = f'ssh -o StrictHostKeyChecking=no -i "{self.ssh_pkey}" {self.guest_username}@{self.ssh_host} "{command}"'
        try:
            output = subprocess.check_output(ssh_command, shell=True, stderr=subprocess.STDOUT).decode().strip()
            return True, output
        except Exception as e: # subprocess.CalledProcessError
            return False, e

    def connect(self):
        """Connect to the VNC server, with retries on failure."""
        for attempt in range(1, self.retry_attempts + 1):
            try:
                print_message(title = 'VNC Client', content = 'Connecting')
                self.tunnel = SSHTunnelForwarder(
                    (self.ssh_host, 22),
                    ssh_username=self.guest_username,
                    ssh_pkey=self.ssh_pkey,
                    remote_bind_address=('localhost', 5900)
                )
                self.tunnel.start()
                self.client = api.connect(f'localhost::{self.tunnel.local_bind_port}',
                                          username=self.guest_username,
                                          password=self.guest_password,
                                          timeout=self.vnc_connection_timeout)
                return
            except Exception as e:
                print_message(title = 'VNC Client', content = f"Connection attempt {attempt} failed: {e}")
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay)
                else:
                    raise ConnectionError("Failed to connect to VNC server after multiple attempts.")

    def capture_screenshot(self):
        """Capture a screenshot and return it as a PIL Image."""
        image = None
        if self.vmx_path is None:
            # Capture a screenshot using VNC
            self._ensure_connection()
            fp = io.BytesIO()
            fp.name = 'screenshot.png'
            self.client.captureScreen(fp)
            fp.seek(0)
            image = Image.open(fp)
            del fp
        else:
            # Capture a screenshot using VMware (VNC screenshot could be slow on VMware machines)
            cache_image_path = f'./{uuid.uuid4().hex}.png'
            max_trials = 5

            for _ in range(max_trials):
                try:
                    # Reload vmware tools
                    if not self.vmware_tools.reload_vmware_tools():
                        print(f'Error reloading VMware Tools. Screen capture failed.', title = 'Error')
                        continue

                    screen_capture_command = f'vmrun -gu {self.guest_username} -gp {self.guest_password} captureScreen "{self.vmx_path}" {cache_image_path}'

                    # Capture screenshot to cache path
                    screen_capture_result = subprocess.run(screen_capture_command, shell=True, text=True, capture_output=True, encoding="utf-8", env=os.environ.copy())

                    # Debug printing
                    if screen_capture_result.returncode != 0:
                        print(f'Screen capture failed.\nSTDOUT: {screen_capture_result.stdout}\nSTDERR: {screen_capture_result.stderr}', title = 'Error')

                    # Read in from cache path and clear cache
                    image = Image.open(cache_image_path)
                    os.remove(cache_image_path)

                    # Update resolution
                    self.client.screen = AttributeContainer()
                    self.client.screen.width, self.client.screen.height = image.size
                except Exception:
                    continue
            
        if image == None:
            raise RuntimeError(f'Screen capture failed after maximum trials')
        return image
    
    def mouse_down(self, button):
        """Press and hold a specified mouse button."""
        self._ensure_connection()
        if button.lower() == "left":
            self.client.mouseDown(1)
        elif button.lower() == "middle":
            self.client.mouseDown(2)
        elif button.lower() == "right":
            self.client.mouseDown(3)

    def mouse_up(self, button):
        """Release a specified mouse button."""
        self._ensure_connection()
        if button.lower() == "left":
            self.client.mouseUp(1)
        elif button.lower() == "middle":
            self.client.mouseUp(2)
        elif button.lower() == "right":
            self.client.mouseUp(3)

    def left_click(self):
        """Perform a left mouse click."""
        self._ensure_connection()
        self.client.mouseDown(1)
        self.client.mouseUp(1)

    def middle_click(self):
        """Perform a middle mouse click."""
        self._ensure_connection()
        self.client.mouseDown(2)
        self.client.mouseUp(2)

    def right_click(self):
        """Perform a right mouse click."""
        self._ensure_connection()
        self.client.mouseDown(3)
        self.client.mouseUp(3)

    def double_click(self):
        """Perform a double left mouse click."""
        self._ensure_connection()
        self.client.mouseDown(1)
        self.client.mouseUp(1)
        self.client.mouseDown(1)
        self.client.mouseUp(1)

    def triple_click(self):
        """Perform a triple left mouse click."""
        self._ensure_connection()
        self.client.mouseDown(1)
        self.client.mouseUp(1)
        self.client.mouseDown(1)
        self.client.mouseUp(1)
        self.client.mouseDown(1)
        self.client.mouseUp(1)

    def drag_to(self, x, y):
        """Perform a drag action by holding down the left mouse button, moving to (x, y), then releasing."""
        self._ensure_connection()
        # Ensure client screen width/height is not None
        if self.client.screen is None:
            _ = self.capture_screenshot()
        # Calculate pixel coordinates as in move_to:
        x_scaled = int(round(x * (self.client.screen.width - 1)))
        y_scaled = int(round(y * (self.client.screen.height - 1)))
        self.client.mouseDown(1)
        self.client.mouseMove(x_scaled, y_scaled)
        self.client.mouseUp(1)

    def scroll_down(self, amount, by_pixel=False):
        """Perform a scrolling down. 
        
        If `by_pixel`, `amount` is the number of pixels to scroll down. Should be non-negative integer. Otherwise, `amount` is the proportion of pixels to scroll down, should be a float value between 0 and 1."""
        self._ensure_connection()

        if by_pixel:
            scaled_amount = amount
        else:
            scaled_amount = int(round(amount * self.client.screen.height))
        scaled_amount = max(0, scaled_amount)
        for _ in range(scaled_amount):
            self.client.mouseDown(5)
            self.client.mouseUp(5)

    def scroll_up(self, amount, by_pixel=False):
        """Perform a mouse scrolling up. 
        
        If `by_pixel`, `amount` is the number of pixels to scroll up. Should be non-negative integer. Otherwise, `amount` is the proportion of pixels to scroll up, should be a float value between 0 and 1."""
        self._ensure_connection()

        if by_pixel:
            scaled_amount = amount
        else:
            scaled_amount = int(round(amount * self.client.screen.height))
        scaled_amount = max(0, scaled_amount)
        for _ in range(scaled_amount):
            self.client.mouseDown(4)
            self.client.mouseUp(4)

    def scroll_left(self, amount, by_pixel=False):
        """Perform a mouse scrolling up. 
        
        If `by_pixel`, `amount` is the number of pixels to scroll left. Should be non-negative integer. Otherwise, `amount` is the proportion of pixels to scroll left, should be a float value between 0 and 1."""
        self._ensure_connection()

        if by_pixel:
            scaled_amount = amount
        else:
            scaled_amount = int(round(amount * self.client.screen.width))
        scaled_amount = max(0, scaled_amount)
        for _ in range(scaled_amount):
            self.client.mouseDown(6)
            self.client.mouseUp(6)

    def scroll_right(self, amount, by_pixel=False):
        """Perform a mouse scrolling up. 
        
        If `by_pixel`, `amount` is the number of pixels to scroll right. Should be non-negative integer. Otherwise, `amount` is the proportion of pixels to scroll right, should be a float value between 0 and 1."""
        self._ensure_connection()

        if by_pixel:
            scaled_amount = amount
        else:
            scaled_amount = int(round(amount * self.client.screen.width))
        scaled_amount = max(0, scaled_amount)
        for _ in range(scaled_amount):
            self.client.mouseDown(7)
            self.client.mouseUp(7)

    def move_to(self, x, y):
        """Move the mouse to the normalised coordinates (x, y).
        
        `(x, y)` should be float values between 0 and 1."""
        self._ensure_connection()

        if self.client.screen is None:
            _ = self.capture_screenshot()

        x_scaled = int(round(x * (self.client.screen.width - 1)))
        y_scaled = int(round(y * (self.client.screen.height - 1)))
        
        x_scaled = max(0, min(self.client.screen.width, x_scaled))
        y_scaled = max(0, min(self.client.screen.height, y_scaled))

        self.client.mouseMove(x_scaled, y_scaled)

    def move_to_pixel(self, x, y):
        """Move the mouse to the pixel coordinates (x, y)."""       
        self._ensure_connection()
        self.client.mouseMove(x, y)

    def key_press(self, key):
        """Press a key on the keyboard.
        
        Keys available: single ASCII characters, ctrl, command, option, backspace, tab, enter, esc, del, left, up, right, down"""
        key = self._filter_key(key)
        if key is None:
            return
        self._ensure_connection()
        self.client.keyPress(key)

    def key_press_and_hold(self, key, duration_seconds: int):
        """Press a key or a key combination on the keyboard; hold for `duration_seconds` seconds before releasing.
        
        Keys available: single ASCII characters, ctrl, command, option, backspace, tab, enter, esc, del, left, up, right, down"""
        key = self._filter_key(key)
        if key is None:
            return
        self._ensure_connection()
        self.client.keyDown(key)
        time.sleep(duration_seconds)
        self.client.keyUp(key)

    def type_text(self, text):
        """Type a string of (ASCII characters only)."""
        text = self._filter_text(text)
        if text is None:
            return
        self._ensure_connection()
        for char in text:
            self.client.keyPress(char)
            time.sleep(0.1)

    def disconnect(self):
        """Disconnect from the VNC server."""
        if self.client is not None:
            self.client.disconnect()
            self.client = None
        if self.tunnel is not None:
            self.tunnel.stop()
            self.tunnel = None

    def _filter_text(self, text):
        if not isinstance(text, str):
            return None
        # Remove all non-ascii characters
        return ''.join(char for char in text if ord(char) < 128)

    def _filter_key(self, key):
        if not isinstance(key, str):
            return None
        if len(key) == 0:
            return None
        if len(key) == 1:
            return self._filter_text(key)
        
        # Split the string using `-` or `+` into a list of strings
        import re as _re
        substrings = _re.split(r'[-+]', key)
        processed_substrings = []

        for substring in substrings:
            if len(substring) >= 2:
                substring = substring.lower()
                # Key mapping tested on keyboardtester.com; mapping is different
                if substring == 'option':
                    substring = 'meta'
                elif substring == 'command':
                    substring = 'alt'
                elif substring == 'cmd':
                    substring = 'alt'
                elif substring == 'backspace':
                    substring = 'bsp'
                if substring in KEYMAP:
                    processed_substrings.append(substring)
            elif len(substring) == 1:
                if ord(substring) < 128:  # Check if it's an ASCII character
                    processed_substrings.append(substring)

        # Reconnect and return all the sub-strings using `-`; if nothing is left, return None (don't return an empty string)
        result = '-'.join(processed_substrings)
        return result if result else None

    def _ensure_connection(self):
        """Ensure that the VNC client is connected, and attempt to reconnect if needed."""
        if self.client is None:
            self.connect()


class VNCClient_Lume:
    """VNC client for Lume-managed macOS VMs.

    Unlike VNCClient_SSH, this class connects directly to the VNC port
    exposed by Lume on the host (no SSH tunnel needed).  SSH commands
    are executed via ``lume ssh``.
    """

    def __init__(
        self,
        vm_name: str,
        guest_username: str = "lume",
        guest_password: str = "lume",
        vnc_port: int | None = None,
        vnc_password: str | None = None,
        retry_attempts: int = 3,
        retry_delay: int = 5,
        action_interval_seconds: int = 1,
        vnc_connection_timeout: int = 600,
    ):
        from utils.lume_utils import LumeTools

        self.vm_name = vm_name
        self.guest_username = guest_username
        self.guest_password = guest_password
        self.vnc_port = vnc_port
        self.vnc_password = vnc_password
        self.client = None
        self.retry_attempts = retry_attempts
        self.retry_delay = retry_delay
        self.action_interval_seconds = action_interval_seconds
        self.vnc_connection_timeout = vnc_connection_timeout

        self.lume_tools = LumeTools(
            vm_name=vm_name,
            guest_username=guest_username,
            guest_password=guest_password,
            vnc_password=vnc_password,
        )

        # Retina scale factor (set on first capture_screenshot)
        self._retina_scale_x = 1.0
        self._retina_scale_y = 1.0

    def check_ssh_connectivity(self) -> bool:
        """Check SSH connectivity via lume ssh."""
        return self.lume_tools.check_ssh_connectivity()

    def run_ssh_command(self, command: str) -> tuple:
        """Execute a command on the guest via lume ssh."""
        return self.lume_tools.run_ssh_command(command)

    def connect(self):
        """Connect to the Lume VNC server directly (no SSH tunnel)."""
        # Resolve VNC port if not provided
        if self.vnc_port is None:
            self.vnc_port = self.lume_tools.get_vnc_port()
        if self.vnc_port is None:
            raise ConnectionError(
                f"Cannot determine VNC port for VM '{self.vm_name}'. "
                "Ensure the VM is running."
            )

        for attempt in range(1, self.retry_attempts + 1):
            try:
                print_message(
                    title="VNC Client (Lume)",
                    content=f"Connecting to localhost:{self.vnc_port} (attempt {attempt})",
                )
                self.client = api.connect(
                    f"localhost::{self.vnc_port}",
                    password=self.vnc_password or "",
                    timeout=self.vnc_connection_timeout,
                )
                return
            except Exception as e:
                print_message(
                    title="VNC Client (Lume)",
                    content=f"Connection attempt {attempt} failed: {e}",
                )
                if attempt < self.retry_attempts:
                    time.sleep(self.retry_delay)
                else:
                    raise ConnectionError(
                        "Failed to connect to Lume VNC server after multiple attempts."
                    )

    def capture_screenshot(self):
        """Capture a screenshot via VNC and return as a PIL Image.

        Lume VNC exposes Retina (2x) physical pixels, so a 1024x768
        logical display yields a 2048x1536 raw capture.  We downscale
        to the logical resolution so that:
          - Agent prompts that mention 1024x768 stay correct
          - Agents returning pixel coordinates (e.g. qwen computer_use)
            produce values in the logical coordinate space
        The VNC move/click methods also operate in the logical space
        by applying the same scale factor.
        """
        self._ensure_connection()
        fp = io.BytesIO()
        fp.name = "screenshot.png"
        self.client.captureScreen(fp)
        fp.seek(0)
        image = Image.open(fp)
        del fp

        # Detect Retina scale factor from VNC raw size vs configured display
        from constants import SCREEN_WIDTH, SCREEN_HEIGHT
        raw_w, raw_h = image.size
        if raw_w > SCREEN_WIDTH or raw_h > SCREEN_HEIGHT:
            self._retina_scale_x = raw_w / SCREEN_WIDTH
            self._retina_scale_y = raw_h / SCREEN_HEIGHT
            image = image.resize((SCREEN_WIDTH, SCREEN_HEIGHT), Image.LANCZOS)
        else:
            self._retina_scale_x = 1.0
            self._retina_scale_y = 1.0

        return image

    def mouse_down(self, button):
        """Press and hold a specified mouse button."""
        self._ensure_connection()
        btn_map = {"left": 1, "middle": 2, "right": 3}
        self.client.mouseDown(btn_map.get(button.lower(), 1))

    def mouse_up(self, button):
        """Release a specified mouse button."""
        self._ensure_connection()
        btn_map = {"left": 1, "middle": 2, "right": 3}
        self.client.mouseUp(btn_map.get(button.lower(), 1))

    def left_click(self):
        """Perform a left mouse click."""
        self._ensure_connection()
        self.client.mouseDown(1)
        self.client.mouseUp(1)

    def middle_click(self):
        """Perform a middle mouse click."""
        self._ensure_connection()
        self.client.mouseDown(2)
        self.client.mouseUp(2)

    def right_click(self):
        """Perform a right mouse click."""
        self._ensure_connection()
        self.client.mouseDown(3)
        self.client.mouseUp(3)

    def double_click(self):
        """Perform a double left mouse click."""
        self._ensure_connection()
        self.client.mouseDown(1)
        self.client.mouseUp(1)
        self.client.mouseDown(1)
        self.client.mouseUp(1)

    def triple_click(self):
        """Perform a triple left mouse click."""
        self._ensure_connection()
        for _ in range(3):
            self.client.mouseDown(1)
            self.client.mouseUp(1)

    def drag_to(self, x, y):
        """Perform a drag action to normalised coordinates (x, y)."""
        self._ensure_connection()
        if self.client.screen is None:
            _ = self.capture_screenshot()
        x_scaled = int(round(x * (self.client.screen.width - 1)))
        y_scaled = int(round(y * (self.client.screen.height - 1)))
        self.client.mouseDown(1)
        self.client.mouseMove(x_scaled, y_scaled)
        self.client.mouseUp(1)

    def scroll_down(self, amount, by_pixel=False):
        """Scroll down by amount (proportion 0-1, or pixels if by_pixel)."""
        self._ensure_connection()
        scaled = amount if by_pixel else int(round(amount * self.client.screen.height))
        for _ in range(max(0, scaled)):
            self.client.mouseDown(5)
            self.client.mouseUp(5)

    def scroll_up(self, amount, by_pixel=False):
        """Scroll up by amount (proportion 0-1, or pixels if by_pixel)."""
        self._ensure_connection()
        scaled = amount if by_pixel else int(round(amount * self.client.screen.height))
        for _ in range(max(0, scaled)):
            self.client.mouseDown(4)
            self.client.mouseUp(4)

    def scroll_left(self, amount, by_pixel=False):
        """Scroll left by amount (proportion 0-1, or pixels if by_pixel)."""
        self._ensure_connection()
        scaled = amount if by_pixel else int(round(amount * self.client.screen.width))
        for _ in range(max(0, scaled)):
            self.client.mouseDown(6)
            self.client.mouseUp(6)

    def scroll_right(self, amount, by_pixel=False):
        """Scroll right by amount (proportion 0-1, or pixels if by_pixel)."""
        self._ensure_connection()
        scaled = amount if by_pixel else int(round(amount * self.client.screen.width))
        for _ in range(max(0, scaled)):
            self.client.mouseDown(7)
            self.client.mouseUp(7)

    def move_to(self, x, y):
        """Move mouse to normalised coordinates (x, y) in [0, 1]."""
        self._ensure_connection()
        if self.client.screen is None:
            _ = self.capture_screenshot()
        x_scaled = int(round(x * (self.client.screen.width - 1)))
        y_scaled = int(round(y * (self.client.screen.height - 1)))
        x_scaled = max(0, min(self.client.screen.width, x_scaled))
        y_scaled = max(0, min(self.client.screen.height, y_scaled))
        self.client.mouseMove(x_scaled, y_scaled)

    def move_to_pixel(self, x, y):
        """Move mouse to pixel coordinates (x, y) in logical space.

        If the VM uses Retina (2x), coordinates are scaled up to
        physical VNC pixels automatically.
        """
        self._ensure_connection()
        scale_x = getattr(self, '_retina_scale_x', 1.0)
        scale_y = getattr(self, '_retina_scale_y', 1.0)
        self.client.mouseMove(int(round(x * scale_x)), int(round(y * scale_y)))

    def key_press(self, key):
        """Press a key on the keyboard."""
        key = self._filter_key(key)
        if key is None:
            return
        self._ensure_connection()
        self.client.keyPress(key)

    def key_press_and_hold(self, key, duration_seconds: int):
        """Press and hold a key for duration_seconds before releasing."""
        key = self._filter_key(key)
        if key is None:
            return
        self._ensure_connection()
        self.client.keyDown(key)
        time.sleep(duration_seconds)
        self.client.keyUp(key)

    def type_text(self, text):
        """Type a string of ASCII characters."""
        text = self._filter_text(text)
        if text is None:
            return
        self._ensure_connection()
        for char in text:
            self.client.keyPress(char)
            time.sleep(0.1)

    def disconnect(self):
        """Disconnect from the VNC server."""
        if self.client is not None:
            self.client.disconnect()
            self.client = None

    def _filter_text(self, text):
        if not isinstance(text, str):
            return None
        return "".join(char for char in text if ord(char) < 128)

    def _filter_key(self, key):
        if not isinstance(key, str):
            return None
        if len(key) == 0:
            return None
        if len(key) == 1:
            return self._filter_text(key)

        import re as _re
        substrings = _re.split(r'[-+]', key)
        processed_substrings = []

        for substring in substrings:
            if len(substring) >= 2:
                substring = substring.lower()
                if substring == "option":
                    substring = "meta"
                elif substring in ("command", "cmd"):
                    substring = "alt"
                elif substring == "backspace":
                    substring = "bsp"
                if substring in KEYMAP:
                    processed_substrings.append(substring)
            elif len(substring) == 1:
                if ord(substring) < 128:
                    processed_substrings.append(substring)

        result = "-".join(processed_substrings)
        return result if result else None

    def _ensure_connection(self):
        """Ensure VNC client is connected; reconnect if needed."""
        if self.client is None:
            self.connect()

