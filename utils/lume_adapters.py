"""Lume-compatible replacements for Evaluator and AsyncSSHCommandHandler.

These classes use ``lume ssh`` instead of raw SSH with PEM keys,
keeping the same interface as their originals.
"""
import os
import signal
import subprocess


class LumeEvaluator:
    """Evaluator that executes grading commands via ``lume ssh``."""

    def __init__(self, vm_name: str, ssh_username: str = "lume", ssh_password: str = "lume"):
        self.vm_name = vm_name
        self.ssh_username = ssh_username
        self.ssh_password = ssh_password

    def run_command(self, command: str) -> tuple:
        """Run a command on the guest and return (success, output)."""
        try:
            result = subprocess.run(
                [
                    "lume", "ssh", self.vm_name, command,
                    "-u", self.ssh_username,
                    "-p", self.ssh_password,
                    "-t", "0",
                ],
                capture_output=True,
                text=True,
                timeout=300,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or result.stdout.strip()
        except Exception as e:
            return False, e

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
                "-t", "0",
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
