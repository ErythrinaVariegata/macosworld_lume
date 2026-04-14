Lume is a lightweight CLI wrapping Apple's Virtualization.framework that manages macOS VMs with APFS clone-based instant reset.
---

## What is Lume

Lume (v0.3.9) is an open-source CLI and local API server for building, running, and managing macOS virtual machines on Apple Silicon. It uses Apple's Virtualization.framework natively and leverages APFS copy-on-write cloning for near-instant VM duplication. VMs are accessed via VNC (GUI) and SSH (commands), with no hypervisor licensing required. Lume also exposes a REST API (`lume serve --port 7777`) and an MCP server (`lume serve --mcp`).

## Essential CLI Commands

| Command | Purpose |
|---------|---------|
| `lume create <name> --cpu 8 --memory 16GB --disk-size 100GB --display 1024x768` | Create a VM |
| `lume run <name> --no-display --vnc-password <pw>` | Start VM headless with VNC |
| `lume stop <name>` | Graceful shutdown |
| `lume delete <name> --force` | Force-delete a VM |
| `lume clone <source> <target>` | APFS clone (instant copy) |
| `lume get <name> -f json` | VM info (IP, VNC port, status) |
| `lume ls -f json` | List all VMs |
| `lume ssh <name> "<cmd>" -u <user> -p <pass> -t <sec>` | Run guest command via SSH |
| `lume pull macOS:latest` | Pull macOS image from GHCR |
| `lume images` | List cached images |

## Golden VM Preparation

`scripts/prepare_golden_vm.sh` is run once on the template VM before any cloning. It pre-grants TCC (Transparency, Consent, and Control) permissions so clones inherit them.

**Steps:**
1. Start golden VM: `lume run <golden> --no-display`
2. Wait for SSH availability
3. Run the script: `./scripts/prepare_golden_vm.sh <golden>`
4. **Step 1 — AppleEvents TCC:** Fires `osascript -e 'tell application "<app>" to return 1'` for each grading app (Contacts, Reminders, Notes, Music, Keynote, Numbers, Pages, Calendar, Finder, Automator, Xcode, QuickTime Player, Script Editor). Operator clicks "Allow" on each VNC dialog.
5. **Step 2 — Data-access TCC:** Fires deeper osascript queries (e.g., `count every person` for Contacts, `count every list` for Reminders, System Events accessibility). Operator clicks "Allow" again.
6. **Step 3 — Deep warmup:** Opens each app, exercises its scripting interface with real data queries, then quits all apps. This caches Apple Events connections so clones don't timeout on first osascript call.
7. **Step 4 — Verify:** Dumps the TCC database: `sqlite3 ~/Library/Application Support/com.apple.TCC/TCC.db` to confirm `sshd-keygen-wrapper` entries.
8. Stop golden VM: `lume stop <golden>`. All future clones inherit the TCC database via APFS clone.

## Clone-Based Environment Reset Flow

`LumeTools.clone_and_start()` orchestrates the full reset cycle for each benchmark task:

```
clone_and_start(golden_vm_name)
  ├── clone_from_golden()           # lume clone <golden> <unique-name>  (APFS instant copy)
  ├── start_vm()                    # Popen("lume run --no-display"), non-blocking
  │   └── poll lume get until status == "running" (up to 30s)
  ├── wait_for_ip(timeout=120s)     # poll lume get for IP != 0.0.0.0
  ├── wait_for_ssh(timeout=120s)    # poll lume ssh "echo ok" every 5s
  ├── _dismiss_setup_assistant()
  │   ├── sleep 15s (wait for GUI load)
  │   ├── killall Setup Assistant + mbuseragent + helpers via SSH
  │   └── VNC unlock: click password field, type password, press Enter
  ├── _prewarm_apps()
  │   ├── Quick-check: if osascript Contacts data query succeeds → skip
  │   └── Otherwise: fire osascript probes + Tab/Space to click "Allow" on TCC dialogs
  └── return (ip, vnc_port, vnc_password)
```

Cleanup: `stop_and_cleanup()` calls `lume stop` then `lume delete --force`. A static `cleanup_stale_vms(prefix="macosworld_")` garbage-collects stopped leftover VMs on startup.

## Lume vs VMware Comparison

| Aspect | VMware Workstation | Lume |
|--------|-------------------|------|
| Reset mechanism | Snapshot revert | APFS clone + boot new VM |
| Reset time | 10-15 min | < 1 min |
| Display access | VMware captureScreen + VNC over SSH tunnel | Direct VNC on host (no tunnel) |
| SSH access | Direct SSH to VM IP | `lume ssh` wrapper (built-in) |
| Cost | Licensed | Open source |
| Platform | Linux/Windows/macOS | macOS (Apple Silicon only) |
| Guest OS | Any | macOS, Linux |
| API | vmrun CLI | CLI + REST + MCP |
| Image distribution | Custom VMX/VMDK | OCI images via GHCR |

## Known Failure Modes

| Failure | Cause | Mitigation |
|---------|-------|------------|
| VM limit exceeded | macOS caps concurrent Virtualization.framework VMs | `cleanup_stale_vms()` deletes stopped `macosworld_*` VMs before cloning |
| SSH timeout | Guest networking slow to initialize | `wait_for_ip` + `wait_for_ssh` with 120s timeout, 5s poll interval |
| Setup Assistant after clone | New machine identity triggers macOS OOBE | `_dismiss_setup_assistant()` kills processes via SSH, unlocks via VNC |
| TCC permission dialogs | osascript triggers consent prompts | `_prewarm_apps()` fires probes and auto-clicks Allow via Tab+Space over VNC |
| VNC port unknown | VM not fully started | `get_vnc_port()` parses `vncUrl` field from `lume get` JSON |
| `lume run` blocks | CLI blocks until VM shuts down | Launched via `subprocess.Popen` (non-blocking); status polled separately |

## VNC Retina Scaling

Lume VMs on Apple Silicon expose Retina (2x) physical pixels over VNC. A 1024x768 logical display produces a 2048x1536 raw VNC capture.

**Screenshot capture** (`VNCClient_Lume.capture_screenshot`):
- Capture raw frame from VNC (e.g., 2048x1536)
- Compare against `SCREEN_WIDTH` x `SCREEN_HEIGHT` from `constants.py`
- If raw > logical: compute `_retina_scale_x = raw_w / SCREEN_WIDTH`, downscale to logical size via `Image.LANCZOS`
- Return logical-resolution image so agent coordinates stay consistent

**Mouse movement** (`move_to_pixel`):
- Agent provides pixel coordinates in logical space (e.g., x=512 on a 1024-wide screen)
- Scales up: `vnc_x = round(x * _retina_scale_x)`, `vnc_y = round(y * _retina_scale_y)`
- VNC receives physical pixel coordinates (e.g., 1024 on the 2048-wide raw framebuffer)

**Normalised movement** (`move_to`):
- Accepts (x, y) as floats in [0, 1]
- Multiplies by `client.screen.width/height` (raw VNC dimensions)
- No additional scaling needed since it operates in VNC-native coordinates

## VNC Key Mapping

vncdotool uses X11 keysym names internally. macOS modifier keys must be remapped:

| macOS Key | VNC/vncdotool Key | Reason |
|-----------|-------------------|--------|
| `command` / `cmd` | `alt` | Virtualization.framework maps Cmd to Alt keysym |
| `option` | `meta` | Option maps to Meta keysym |
| `backspace` | `bsp` | vncdotool's KEYMAP alias |

The `_filter_key()` method in both `VNCClient_SSH` and `VNCClient_Lume` handles this translation. Key combinations like `command+c` are split on `-` or `+`, each part is mapped, then rejoined as `alt-c`. Only ASCII characters and keys present in vncdotool's `KEYMAP` dict are forwarded; all others are silently dropped.
