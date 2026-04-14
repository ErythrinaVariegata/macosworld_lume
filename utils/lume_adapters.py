"""Lume-compatible replacements for Evaluator and AsyncSSHCommandHandler.

These classes use ``lume ssh`` instead of raw SSH with PEM keys,
keeping the same interface as their originals.
"""
import os
import re
import signal
import subprocess
import time

from utils.log import print_message

SSH_TIMEOUT = "60"          # lume ssh -t value (seconds)
SUBPROCESS_TIMEOUT = 75     # subprocess.run hard kill (seconds)
GRADING_RETRY_COUNT = 3     # extra attempts after first timeout


class LumeEvaluator:
    """Evaluator that executes grading commands via ``lume ssh``.

    If an osascript command times out, the evaluator will attempt to
    warm up the target application and retry the command.
    """

    def __init__(self, vm_name: str, ssh_username: str = "lume", ssh_password: str = "lume"):
        self.vm_name = vm_name
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password

    def _run_lume_ssh(self, command: str, timeout: str = SSH_TIMEOUT,
                      subprocess_timeout: int = SUBPROCESS_TIMEOUT) -> tuple:
        """Low-level: run a single command via lume ssh.

        Returns (success: bool, output: str).
        """
        try:
            result = subprocess.run(
                [
                    "lume", "ssh", self.vm_name, command,
                    "-u", self.ssh_username,
                    "-p", self.ssh_password,
                    "-t", timeout,
                ],
                capture_output=True,
                text=True,
                timeout=subprocess_timeout,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or result.stdout.strip()
        except subprocess.TimeoutExpired:
            self._kill_hung_ssh()
            return False, f"Command timed out after {subprocess_timeout}s"
        except Exception as e:
            return False, str(e)

    def _kill_hung_ssh(self):
        """Kill any hung lume ssh processes for this VM."""
        try:
            subprocess.run(
                ["pkill", "-f", f"lume ssh {self.vm_name}"],
                capture_output=True, timeout=5,
            )
        except Exception:
            pass

    @staticmethod
    def _extract_app_name(command: str) -> str | None:
        """Extract the target application name from an osascript command."""
        m = re.search(r'tell application "([^"]+)"', command)
        return m.group(1) if m else None

    def _warmup_app(self, app_name: str):
        """Launch an app and give it time to initialise its data stores."""
        print_message(f'Warming up "{app_name}" before retry...', title="Lume Eval")
        # Step 1: Force-launch the app
        self._run_lume_ssh(f'open -a "{app_name}"', timeout="15", subprocess_timeout=20)
        time.sleep(8)
        # Step 2: Lightweight probe to trigger Apple Events / data store init
        success, output = self._run_lume_ssh(
            f'osascript -e \'tell application "{app_name}" to return 1\'',
            timeout="30",
            subprocess_timeout=40,
        )
        if not success:
            print_message(f'Warmup probe failed for "{app_name}": {output}', title="Lume Eval")
            time.sleep(5)
        else:
            time.sleep(3)

    def run_command(self, command: str) -> tuple:
        """Run a command on the guest, retrying on timeout with app warm-up."""
        success, output = self._run_lume_ssh(command)
        if success or "timed out" not in output:
            return success, output

        # Timeout occurred — try warming up the app and retrying
        app_name = self._extract_app_name(command)
        for attempt in range(1, GRADING_RETRY_COUNT + 1):
            print_message(
                f"Grading command timed out, retry {attempt}/{GRADING_RETRY_COUNT}",
                title="Lume Eval",
            )
            if app_name:
                self._warmup_app(app_name)
            success, output = self._run_lume_ssh(command)
            if success or "timed out" not in output:
                return success, output

        return success, output

    def __call__(self, eval_configs: list, binary_grading: bool = True) -> int:
        filtered_eval_configs = (
            [item for item in eval_configs if item[1] == 100]
            if binary_grading
            else eval_configs
        )
        for eval_config in filtered_eval_configs:
            command, return_value = eval_config
            success, output = self.run_command(command)
            if success and isinstance(output, str):
                if "true" in output.lower():
                    return return_value
                else:
                    continue
            else:
                return [command, return_value, output]
        return 0


class LumeAsyncSSHCommandHandler:
    """Async SSH command handler using ``lume ssh``.

    Spawns a background ``lume ssh`` process so the command runs
    asynchronously on the guest, matching the interface of
    AsyncSSHCommandHandler.
    """

    def __init__(self, vm_name: str, ssh_username: str = "lume", ssh_password: str = "lume"):
        self.vm_name = vm_name
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password
        self.process = None

    def run_command(self, command: str) -> subprocess.Popen:
        """Start the command asynchronously via ``lume ssh``."""
        self.process = subprocess.Popen(
            [
                "lume", "ssh", self.vm_name, command,
                "-u", self.ssh_username,
                "-p", self.ssh_password,
                "-t", "0",  # no timeout for async commands
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            preexec_fn=os.setsid,
        )
        return self.process

    def end_command(self) -> tuple:
        """Terminate the running command and return results.

        Returns (return_code, stdout, stderr, end_type).
        """
        if self.process:
            if self.process.poll() is None:
                os.killpg(os.getpgid(self.process.pid), signal.SIGTERM)
                end_type = "killed"
            else:
                end_type = "handled"
            stdout, stderr = self.process.communicate()
            return self.process.returncode, stdout, stderr, end_type
        else:
            return None, "", "No process is currently running.", None
