import json
import subprocess
import time
import uuid

from utils.log import print_message


class LumeTools:
    """Lume VM management tools, replacing VMwareTools for Apple Silicon Macs."""

    def __init__(
        self,
        vm_name: str,
        guest_username: str = "lume",
        guest_password: str = "lume",
        vnc_password: str = None,
    ):
        self.vm_name = vm_name
        self.guest_username = guest_username
        self.guest_password = guest_password
        self.vnc_password = vnc_password

    @staticmethod
    def cleanup_stale_vms(prefix: str = "macosworld_"):
        """Delete any stopped VMs whose names start with the given prefix.

        This is a best-effort garbage collector for VMs left over from
        previous runs that crashed before cleanup.
        """
        try:
            result = subprocess.run(
                ["lume", "ls", "-f", "json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return
            import json as _json
            vms = _json.loads(result.stdout)
            if not isinstance(vms, list):
                return
            for vm in vms:
                name = vm.get("name", "")
                status = vm.get("status", "")
                if name.startswith(prefix) and status == "stopped":
                    print_message(f'Cleaning up stale VM "{name}"', title="Lume")
                    subprocess.run(
                        ["lume", "delete", name, "--force"],
                        capture_output=True, text=True, timeout=30,
                    )
        except Exception:
            pass  # best-effort

    @staticmethod
    def _run_lume_command(args: list, timeout: int = 300) -> subprocess.CompletedProcess:
        """Run a lume CLI command and return the result."""
        cmd = ["lume"] + args
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )

    def get_vm_info(self) -> dict:
        """Get VM information (IP, VNC port, status, etc.) as a dict.

        Returns a dict parsed from ``lume get <name> -f json``.
        """
        result = self._run_lume_command(["get", self.vm_name, "-f", "json"])
        if result.returncode != 0:
            print_message(
                f"Failed to get VM info for {self.vm_name}\n"
                f"STDOUT: {result.stdout}\nSTDERR: {result.stderr}",
                title="Lume Error",
            )
            return {}
        try:
            data = json.loads(result.stdout)
            # lume get returns a list with one element
            if isinstance(data, list) and len(data) > 0:
                return data[0]
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            print_message(
                f"Failed to parse VM info JSON: {result.stdout}",
                title="Lume Error",
            )
            return {}

    @staticmethod
    def vm_exists(vm_name: str) -> bool:
        """Check if a VM exists in Lume."""
        try:
            result = subprocess.run(
                ["lume", "get", vm_name, "-f", "json"],
                capture_output=True, text=True, timeout=15,
            )
            return result.returncode == 0
        except Exception:
            return False

    @staticmethod
    def list_vms() -> list:
        """List all available Lume VMs."""
        try:
            result = subprocess.run(
                ["lume", "ls", "-f", "json"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode != 0:
                return []
            data = json.loads(result.stdout)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def clone_from_golden(self, golden_vm_name: str) -> bool:
        """Clone a new VM from a golden (template) VM.

        The golden VM must be in a stopped state.
        Raises ValueError immediately if the golden VM does not exist.

        Returns True on success.
        """
        # Fail fast if golden VM doesn't exist
        if not self.vm_exists(golden_vm_name):
            available = [vm.get("name", "") for vm in self.list_vms()]
            raise ValueError(
                f'Golden VM "{golden_vm_name}" not found. '
                f'Available VMs: {available}'
            )

        print_message(
            f'Cloning "{golden_vm_name}" → "{self.vm_name}"',
            title="Lume",
        )
        result = self._run_lume_command(["clone", golden_vm_name, self.vm_name])
        if result.returncode != 0:
            print_message(
                f"Clone failed\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}",
                title="Lume Error",
            )
            return False
        return True

    def start_vm(self) -> bool:
        """Start the VM in headless mode (no display).

        ``lume run --no-display`` blocks until the VM shuts down, so we
        launch it as a background process and poll until the VM is running.

        Returns True on success.
        """
        print_message(f'Starting VM "{self.vm_name}"', title="Lume")
        cmd = ["lume", "run", self.vm_name, "--no-display"]
        if self.vnc_password is not None:
            cmd += ["--vnc-password", self.vnc_password]

        # Launch as a non-blocking background process
        self._vm_process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        # Poll until VM status is "running" (or timeout)
        for _ in range(30):  # up to ~30 seconds
            time.sleep(1)
            info = self.get_vm_info()
            status = info.get("status", "")
            if status == "running":
                return True
            if self._vm_process.poll() is not None:
                # Process exited unexpectedly
                print_message(
                    f"lume run process exited with code {self._vm_process.returncode}",
                    title="Lume Error",
                )
                return False
        print_message("Timeout waiting for VM to reach 'running' state", title="Lume Error")
        return False

    def stop_vm(self) -> bool:
        """Stop the VM."""
        print_message(f'Stopping VM "{self.vm_name}"', title="Lume")
        result = self._run_lume_command(["stop", self.vm_name], timeout=60)
        if result.returncode != 0:
            print_message(
                f"Stop failed\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}",
                title="Lume Warning",
            )
            return False
        return True

    def delete_vm(self) -> bool:
        """Delete the VM forcefully."""
        print_message(f'Deleting VM "{self.vm_name}"', title="Lume")
        result = self._run_lume_command(["delete", self.vm_name, "--force"], timeout=60)
        if result.returncode != 0:
            print_message(
                f"Delete failed\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}",
                title="Lume Warning",
            )
            return False
        return True

    def stop_and_cleanup(self):
        """Stop the VM and delete it. Best-effort; logs warnings on failure."""
        if not self.vm_exists(self.vm_name):
            return
        self.stop_vm()
        # Give the VM a moment to fully shut down
        time.sleep(2)
        self.delete_vm()

    def wait_for_ip(self, timeout_seconds: int = 120, poll_interval: int = 5) -> str | None:
        """Poll ``lume get`` until the VM has an IP address.

        Returns the IP address string, or None on timeout.
        """
        print_message(
            f'Waiting for VM "{self.vm_name}" to obtain an IP address',
            title="Lume",
        )
        start = time.time()
        while time.time() - start < timeout_seconds:
            info = self.get_vm_info()
            ip = info.get("ip") or info.get("ipAddress")
            status = info.get("status", "")
            if ip and ip not in ("", "0.0.0.0", "N/A"):
                print_message(f"VM IP: {ip}", title="Lume")
                return ip
            if status in ("stopped", "error"):
                print_message(f"VM entered unexpected state: {status}", title="Lume Error")
                return None
            time.sleep(poll_interval)
        print_message("Timeout waiting for VM IP", title="Lume Error")
        return None

    def get_vnc_port(self) -> int | None:
        """Retrieve the VNC port from ``lume get``."""
        info = self.get_vm_info()
        port = info.get("vncPort") or info.get("vnc_port") or info.get("vncUrl")
        if port is None:
            return None
        # If port is a URL like vnc://localhost:5901, extract the port
        if isinstance(port, str) and ":" in port:
            try:
                return int(port.rsplit(":", 1)[-1])
            except ValueError:
                return None
        try:
            return int(port)
        except (ValueError, TypeError):
            return None

    def check_ssh_connectivity(self) -> bool:
        """Check SSH connectivity via ``lume ssh``."""
        try:
            result = self._run_lume_command(
                [
                    "ssh", self.vm_name, "echo ok",
                    "-u", self.guest_username,
                    "-p", self.guest_password,
                    "-t", "15",
                ],
                timeout=30,
            )
            return result.returncode == 0 and "ok" in result.stdout
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    def run_ssh_command(self, command: str) -> tuple:
        """Execute a command on the guest via ``lume ssh``.

        Returns (success: bool, output: str).
        """
        try:
            result = self._run_lume_command(
                [
                    "ssh", self.vm_name, command,
                    "-u", self.guest_username,
                    "-p", self.guest_password,
                    "-t", "30",
                ],
                timeout=45,
            )
            if result.returncode == 0:
                return True, result.stdout.strip()
            return False, result.stderr.strip() or result.stdout.strip()
        except subprocess.TimeoutExpired:
            return False, f"Command timed out"
        except Exception as e:
            return False, str(e)

    def _dismiss_setup_assistant(self):
        """Dismiss Setup Assistant and ensure the desktop is ready.

        After ``lume clone``, macOS may launch Setup Assistant due to
        the new machine identity.  This method unconditionally:
        1. Waits for the GUI to finish loading
        2. Kills Setup Assistant and related processes (no-op if absent)
        3. Unlocks the login screen via VNC if needed
        """
        print_message("Ensuring desktop is ready (dismissing any setup dialogs)...", title="Lume")
        time.sleep(15)  # Wait for GUI to fully load after boot

        # Kill Setup Assistant and helpers unconditionally (no-op if not running)
        self.run_ssh_command("killall 'Setup Assistant' 2>/dev/null; killall mbuseragent 2>/dev/null; killall mbusertrampoline 2>/dev/null; killall mbsystemadministration 2>/dev/null")
        time.sleep(3)

        # Now we're at the lock screen — unlock via VNC
        vnc_port = self.get_vnc_port()
        full_info = self.get_vm_info()
        vnc_url = full_info.get("vncUrl", "")
        vnc_password = None
        if vnc_url:
            import re
            m = re.search(r"vnc://:(.+)@", vnc_url)
            if m:
                vnc_password = m.group(1)

        if vnc_port is None:
            print_message("Cannot unlock: VNC port unknown", title="Lume Warning")
            return

        try:
            from vncdotool import api
            client = api.connect(
                f"localhost::{vnc_port}",
                password=vnc_password or "",
                timeout=30,
            )
            time.sleep(1)

            # Click on the password field area and type password
            client.mouseMove(512, 500)
            client.mouseDown(1)
            client.mouseUp(1)
            time.sleep(0.5)
            for c in self.guest_password:
                client.keyPress(c)
                time.sleep(0.05)
            client.keyPress("enter")
            time.sleep(5)
            client.disconnect()
            print_message("Desktop unlocked", title="Lume")
        except Exception as e:
            print_message(f"VNC unlock failed: {e}", title="Lume Warning")

    def _prewarm_apps(self):
        """Grant TCC permissions for osascript grading via VNC auto-Allow.

        When ``sshd-keygen-wrapper`` triggers an osascript command, macOS may
        show TCC permission dialogs.  If the golden VM was prepared with
        ``scripts/prepare_golden_vm.sh``, no dialogs appear and this method
        finishes almost instantly.  Otherwise, it triggers osascript probes
        and auto-clicks "Allow" on each TCC dialog via keyboard (Tab + Space).
        """
        import subprocess as _sp

        # Key grading apps that need TCC permissions
        PROBES = [
            # (label, osascript body)
            ("Contacts:AE", 'tell application "Contacts" to return 1'),
            ("Contacts:data", 'tell application "Contacts" to count every person'),
            ("Reminders:AE", 'tell application "Reminders" to return 1'),
            ("Reminders:data", 'tell application "Reminders" to count every list'),
            ("Notes", 'tell application "Notes" to count every note'),
            ("Music", 'tell application "Music" to return 1'),
            ("SysEvents", 'tell application "System Events" to get the name of every process whose frontmost is true'),
            ("Finder", 'tell application "Finder" to get the name of every window'),
            ("Keynote", 'tell application "Keynote" to return 1'),
            ("Numbers", 'tell application "Numbers" to return 1'),
            ("Pages", 'tell application "Pages" to return 1'),
            ("ScriptEditor", 'tell application "Script Editor" to return 1'),
            ("QuickTime", 'tell application "QuickTime Player" to return 1'),
        ]

        print_message("Checking TCC permissions for osascript grading...", title="Lume")

        # Quick check: if Contacts data query works, golden VM was prepared
        ok, _ = self.run_ssh_command(
            "osascript -e 'tell application \"Contacts\" to count every person'"
        )
        if ok:
            print_message("TCC permissions already granted (golden VM prepared)", title="Lume")
            # Quit any apps that launched during the probe
            self.run_ssh_command(
                "osascript -e 'tell application \"Contacts\" to quit' 2>/dev/null"
            )
            return

        # TCC permissions NOT yet granted — auto-grant via VNC
        print_message("TCC permissions needed — auto-granting via VNC...", title="Lume")

        # Kill akd to avoid iCloud sign-in prompts
        self.run_ssh_command("killall akd 2>/dev/null")

        # Connect VNC
        vnc_port = self.get_vnc_port()
        full_info = self.get_vm_info()
        vnc_url = full_info.get("vncUrl", "")
        vnc_password = None
        if vnc_url:
            import re as _re
            m = _re.search(r"vnc://:(.+)@", vnc_url)
            if m:
                vnc_password = m.group(1)

        if vnc_port is None:
            print_message("Cannot auto-grant TCC: VNC port unknown", title="Lume Warning")
            return

        try:
            from vncdotool import api
            vnc_client = api.connect(
                f"localhost::{vnc_port}",
                password=vnc_password or "",
                timeout=30,
            )
        except Exception as e:
            print_message(f"VNC connect failed for TCC granting: {e}", title="Lume Warning")
            return

        for label, script in PROBES:
            # Fire a non-blocking osascript (may trigger TCC dialog)
            probe_proc = _sp.Popen(
                [
                    "lume", "ssh", self.vm_name,
                    f"osascript -e '{script}' 2>/dev/null",
                    "-u", self.guest_username,
                    "-p", self.guest_password,
                    "-t", "10",
                ],
                stdout=_sp.DEVNULL,
                stderr=_sp.DEVNULL,
            )
            time.sleep(2)

            # Click "Allow" via Tab (focus) + Space (activate)
            self._click_allow_button(vnc_client)

            try:
                probe_proc.wait(timeout=12)
            except _sp.TimeoutExpired:
                probe_proc.kill()

        try:
            vnc_client.disconnect()
        except Exception:
            pass

        # Quit any apps that may have launched during probing
        self.run_ssh_command(
            "osascript -e 'tell application \"Contacts\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Reminders\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Notes\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Music\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Keynote\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Numbers\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Pages\" to quit' 2>/dev/null"
        )

        print_message("TCC permission granting complete", title="Lume")

    @staticmethod
    def _click_allow_button(vnc_client):
        """Click the 'Allow' button on a TCC permission dialog via VNC.

        Uses keyboard navigation: Tab moves focus to the "Allow" button,
        then Space activates it.  This is more reliable than coordinate-based
        mouse clicks because TCC dialog position varies.
        """
        try:
            vnc_client.keyPress('tab')
            time.sleep(0.3)
            vnc_client.keyPress('space')
            time.sleep(0.5)
        except Exception:
            pass  # best effort

    def clone_and_start(
        self,
        golden_vm_name: str,
        timeout_seconds: int = 120,
    ) -> tuple:
        """Clone from a golden VM, start it, and wait until ready.

        Returns (success: bool, vm_info: dict).
        ``vm_info`` contains ``ip``, ``vnc_port``, and the full info dict.
        """
        # Step 1: Clone
        if not self.clone_from_golden(golden_vm_name):
            return False, {}

        # Step 2: Start
        if not self.start_vm():
            self.delete_vm()
            return False, {}

        # Step 3: Wait for IP
        ip = self.wait_for_ip(timeout_seconds=timeout_seconds)
        if ip is None:
            self.stop_and_cleanup()
            return False, {}

        # Step 4: Wait for SSH
        print_message(f"Waiting for SSH connectivity on {ip}", title="Lume")
        ssh_start = time.time()
        while time.time() - ssh_start < timeout_seconds:
            if self.check_ssh_connectivity():
                break
            time.sleep(5)
        else:
            print_message("Timeout waiting for SSH", title="Lume Error")
            self.stop_and_cleanup()
            return False, {}

        # Step 4.5: Dismiss Setup Assistant if present (clone triggers it)
        self._dismiss_setup_assistant()

        # Step 4.6: Pre-warm iCloud-dependent apps to avoid osascript hangs
        self._prewarm_apps()

        # Step 5: Gather info
        vnc_port = self.get_vnc_port()
        full_info = self.get_vm_info()
        vnc_url = full_info.get("vncUrl", "")
        vnc_password = None
        if vnc_url:
            import re
            m = re.search(r"vnc://:(.+)@", vnc_url)
            if m:
                vnc_password = m.group(1)
        info = {
            "ip": ip,
            "vnc_port": vnc_port,
            "vnc_password": vnc_password,
            "vm_name": self.vm_name,
        }
        print_message(
            f"VM ready: IP={ip}, VNC port={vnc_port}",
            title="Lume",
        )
        return True, info
