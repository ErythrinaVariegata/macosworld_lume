import json
import subprocess
import time
import uuid

import paramiko

from utils.log import print_message


class LumeInfraError(RuntimeError):
    """Non-retryable Lume infrastructure failure.

    Raised when Lume VM operations fail in a way that indicates a systemic
    problem (e.g., hypervisor crash, resource exhaustion) rather than a
    transient glitch.  Callers should abort the benchmark run instead of
    retrying further tasks.
    """


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
        self._cached_ip = None  # type: str | None

    @staticmethod
    def cleanup_stale_vms(prefix: str = "macosworld_"):
        """Delete any stale VMs whose names start with the given prefix.

        Handles both stopped and running VMs left over from previous
        runs that crashed before cleanup.  Uses ``lume delete --force``
        directly when ``lume stop`` fails due to stale lock files.
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
                if not name.startswith(prefix):
                    continue
                if status == "running":
                    print_message(f'Stopping stale running VM "{name}"', title="Lume")
                    stop_result = subprocess.run(
                        ["lume", "stop", name],
                        capture_output=True, text=True, timeout=60,
                    )
                    if stop_result.returncode != 0:
                        print_message(
                            f'lume stop failed for stale VM "{name}" (exit {stop_result.returncode}), '
                            f'will force-delete anyway',
                            title="Lume Warning",
                        )
                    time.sleep(2)
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
        """Stop the VM and delete it. Best-effort; logs warnings on failure.

        Handles the common case where ``lume stop`` fails with exit code 130
        because the background ``lume run`` process was killed and left a
        stale lock file.  In that scenario ``lume delete --force`` still
        succeeds, so we proceed with deletion regardless of the stop result.
        """
        # Kill the background lume run process if we launched one
        proc = getattr(self, "_vm_process", None)
        if proc is not None and proc.poll() is None:
            try:
                proc.terminate()  # SIGTERM first for graceful shutdown
                proc.wait(timeout=10)
            except Exception:
                try:
                    proc.kill()  # SIGKILL if terminate didn't work
                    proc.wait(timeout=5)
                except Exception:
                    pass

        # Wait for the VM process to fully exit and release its lock
        time.sleep(2)

        if not self.vm_exists(self.vm_name):
            return

        # Try to stop the VM gracefully; retry once if it fails
        # (lume stop can fail with exit 130 when a stale lock file exists)
        stopped_ok = self.stop_vm()
        if not stopped_ok:
            # Give it a moment and retry — the lock may still be releasing
            time.sleep(3)
            stopped_ok = self.stop_vm()

        if not stopped_ok:
            print_message(
                f"lume stop failed for {self.vm_name}, proceeding with force-delete anyway",
                title="Lume Warning",
            )

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
                self._cached_ip = ip
                return ip
            if status in ("stopped", "error"):
                print_message(f"VM entered unexpected state: {status}", title="Lume Error")
                return None
            time.sleep(poll_interval)
        print_message("Timeout waiting for VM IP", title="Lume Error")
        return None

    def get_ip(self):
        """Return the VM's current IP address (from lume get), or None."""
        info = self.get_vm_info()
        ip = info.get("ip") or info.get("ipAddress")
        if ip and ip not in ("", "0.0.0.0", "N/A"):
            self._cached_ip = ip
            return ip
        return self._cached_ip

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
        """Check SSH connectivity via direct paramiko connection."""
        ip = self._cached_ip or self.get_ip()
        if not ip:
            return False
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(
                ip,
                username=self.guest_username,
                password=self.guest_password,
                timeout=10,
                look_for_keys=False,
                allow_agent=False,
            )
            _, stdout, _ = client.exec_command("echo ok", timeout=10)
            result = stdout.read().decode().strip()
            client.close()
            return result == "ok"
        except Exception:
            return False

    def run_ssh_command(self, command: str, timeout: int = 120) -> tuple:
        """Execute a command on the guest via direct SSH (paramiko).

        Falls back to ``lume ssh`` when the VM IP is not available.

        Returns (success: bool, output: str).
        """
        ip = self._cached_ip or self.get_ip()
        if ip:
            return self._run_ssh_paramiko(ip, command, timeout)
        # Fallback: use lume ssh
        return self._run_ssh_lume(command, timeout)

    def _run_ssh_paramiko(self, ip: str, command: str, timeout: int) -> tuple:
        """Execute a command via paramiko (direct SSH to VM IP)."""
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            client.connect(
                ip,
                username=self.guest_username,
                password=self.guest_password,
                timeout=15,
                look_for_keys=False,
                allow_agent=False,
            )
            _, stdout, stderr = client.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            if exit_status == 0:
                return True, out
            return False, err or out
        except Exception as e:
            return False, str(e)
        finally:
            client.close()

    def _run_ssh_lume(self, command: str, timeout: int) -> tuple:
        """Execute a command via lume ssh (fallback when IP is unknown)."""
        try:
            result = self._run_lume_command(
                [
                    "ssh", self.vm_name, command,
                    "-u", self.guest_username,
                    "-p", self.guest_password,
                    "-t", str(timeout),
                ],
                timeout=timeout + 30,
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

    # Deep (document-level or window-level) AppleEvent probes for apps that need
    # document access or window manipulation.  On freshly cloned VMs, these apps may prompt
    # for a second TCC Automation dialog even if the basic "return 1"
    # probe already succeeded.  The golden VM preparation script only
    # grants the basic Automation permission; document-level commands
    # like ``count every document`` or window commands like ``close windows``
    # require a separate TCC grant.
    _DEEP_PROBES = [
        # (label, osascript body, app_name_for_quit)
        ("Numbers:docs", 'tell application "Numbers" to count every document', "Numbers"),
        ("Pages:docs", 'tell application "Pages" to count every document', "Pages"),
        ("Keynote:docs", 'tell application "Keynote" to count every document', "Keynote"),
        ("TextEdit:docs", 'tell application "TextEdit" to count every document', "TextEdit"),
        ("Xcode:windows", 'tell application "Xcode" to count every window', "Xcode"),
    ]

    def _prewarm_apps(self):
        """Grant TCC permissions for osascript grading via VNC auto-Allow.

        When ``sshd-keygen-wrapper`` triggers an osascript command, macOS may
        show TCC permission dialogs.  If the golden VM was prepared with
        ``scripts/prepare_golden_vm.sh``, no dialogs appear and this method
        finishes almost instantly.  Otherwise, it triggers osascript probes
        and auto-clicks "Allow" on each TCC dialog via keyboard (Tab + Space).

        After the basic TCC check, this method also grants **deep AppleEvent**
        permissions for document-based apps (Numbers, Pages, Keynote, TextEdit).
        The golden VM preparation only grants the basic ``return 1`` level of
        Automation permission; document-level commands like ``count every
        document`` require a separate TCC grant that is triggered by actually
        using those commands.
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
            ("Calendar", 'tell application "Calendar" to get the name of every calendar'),
            ("Automator", 'tell application "Automator" to return 1'),
            ("Xcode", 'tell application "Xcode" to return 1'),
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
            # Even though basic TCC is granted, we still need to grant
            # deep AppleEvent permissions for document-based apps.
            # The golden VM preparation only grants "return 1" level;
            # document-level commands like "count every document" need
            # their own TCC grant.
            self._grant_deep_appleevent_permissions()
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

        # Also grant deep AppleEvent permissions for document-based apps
        self._grant_deep_probes_via_vnc(vnc_client)

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
            "osascript -e 'tell application \"Pages\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Calendar\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Automator\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"Xcode\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"QuickTime Player\" to quit' 2>/dev/null; "
            "osascript -e 'tell application \"TextEdit\" to quit' 2>/dev/null"
        )

        print_message("TCC permission granting complete", title="Lume")

    def _grant_deep_appleevent_permissions(self):
        """Grant deep AppleEvent permissions for document-based apps.

        The golden VM preparation only grants the basic Automation
        permission (``tell application "X" to return 1``).  Document-level
        commands like ``count every document`` require a *separate* TCC
        grant that is not part of the golden VM preparation.

        This method opens each document-based app, fires a deep AppleScript
        command in the background (which triggers a TCC Automation dialog),
        and clicks "Allow" via VNC.
        """
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
            print_message(
                "Cannot grant deep AppleEvent permissions: VNC port unknown",
                title="Lume Warning",
            )
            return

        try:
            from vncdotool import api
            vnc_client = api.connect(
                f"localhost::{vnc_port}",
                password=vnc_password or "",
                timeout=30,
            )
        except Exception as e:
            print_message(
                f"VNC connect failed for deep AppleEvent granting: {e}",
                title="Lume Warning",
            )
            return

        self._grant_deep_probes_via_vnc(vnc_client)

        try:
            vnc_client.disconnect()
        except Exception:
            pass

        # Quit any apps we opened
        quit_cmds = "; ".join(
            f"osascript -e 'tell application \"{app}\" to quit' 2>/dev/null"
            for _, _, app in self._DEEP_PROBES
        )
        self.run_ssh_command(quit_cmds)

        print_message("Deep AppleEvent permissions granted", title="Lume")

    def _grant_deep_probes_via_vnc(self, vnc_client):
        """Fire deep AppleScript probes and click Allow on TCC dialogs.

        For each document-based app, this:
        1. Opens the app
        2. Fires a deep AppleScript command in the background
        3. Waits for a TCC dialog to appear
        4. Clicks "Allow" via VNC (Tab + Space)
        5. Kills the app
        """
        import subprocess as _sp

        for label, script, app_name in self._DEEP_PROBES:
            print_message(f"Granting deep AppleEvent: {label}", title="Lume")

            # Open the app
            self.run_ssh_command(f"open -a '{app_name}'")
            time.sleep(5)

            # Fire the deep command in the background via paramiko
            # (lume ssh can't be used here because we need reliable background execution)
            ip = self._cached_ip or self.get_ip()
            if not ip:
                print_message(
                    f"Cannot grant {label}: no VM IP",
                    title="Lume Warning",
                )
                self.run_ssh_command(f"killall '{app_name}' 2>/dev/null")
                continue

            # Use paramiko to fire the command in background
            # The & makes it background, disown prevents SSH from killing it
            bg_cmd = (
                f"osascript -e '{script}' 2>/dev/null &\n"
                f"disown\n"
            )
            self.run_ssh_command(bg_cmd, timeout=5)

            # Wait for TCC dialog to appear
            time.sleep(3)

            # Click "Allow" via Tab + Space (may need multiple attempts)
            for _ in range(3):
                self._click_allow_button(vnc_client)
                time.sleep(1)

            # Kill the app
            self.run_ssh_command(f"killall '{app_name}' 2>/dev/null")
            time.sleep(2)

            # Verify the permission was granted
            ok, _ = self.run_ssh_command(
                f"osascript -e '{script}'",
                timeout=15,
            )
            if ok:
                print_message(f"Deep AppleEvent permission granted: {label}", title="Lume")
            else:
                print_message(
                    f"Deep AppleEvent permission may not be granted for {label}",
                    title="Lume Warning",
                )

        # After granting permissions, dismiss template choosers for iWork apps.
        # On freshly cloned VMs, Numbers/Pages/Keynote show a template chooser
        # on first launch that blocks "make new document" commands even when
        # the AppleEvent permission is granted.  We dismiss these by opening
        # each app and pressing Escape via VNC, then quitting.
        self._dismiss_iwork_template_choosers(vnc_client)

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

    def _dismiss_iwork_template_choosers(self, vnc_client):
        """Dismiss the template chooser dialogs for iWork apps via VNC.

        On freshly cloned VMs, Numbers, Pages, and Keynote show a template
        chooser on first launch.  Even after the deep AppleEvent permission
        is granted, some apps (especially Pages) block ``make new document``
        commands when the template chooser is showing.

        Strategy: open each app, press Escape via VNC to close the chooser,
        then kill the app.  After this, the next ``make new document`` call
        will open the app fresh and create the document directly.
        """
        for app_name in ("Numbers", "Pages", "Keynote"):
            print_message(f"Dismissing template chooser for {app_name}", title="Lume")

            # Open the app
            self.run_ssh_command(f"open -a '{app_name}'")
            time.sleep(8)

            # Press Escape to dismiss the template chooser
            # Then press Cmd+D to close the "no document" state
            try:
                vnc_client.keyPress('esc')
                time.sleep(1)
                vnc_client.keyPress('esc')
                time.sleep(1)
            except Exception:
                pass  # best effort

            # Kill the app (force-quit since it may be showing the chooser)
            self.run_ssh_command(f"killall '{app_name}' 2>/dev/null")
            time.sleep(3)

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
