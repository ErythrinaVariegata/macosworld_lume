Technical decisions made during the Lume migration and their rationale.
---

## Clone-based reset instead of snapshot revert

**Decision:** Use APFS `lume clone` instead of VMware snapshot revert for environment reset.

**Why:** Apple Virtualization.framework has no snapshot API. APFS clone is copy-on-write, making it nearly instant (~2s for clone, ~40s total with boot). Each task gets a fresh VM cloned from a golden template, then deleted after grading. This is actually faster than VMware snapshot revert (~60s).

**Trade-off:** Each clone consumes disk space (though COW minimizes actual allocation). Stale VMs can accumulate if the process crashes — mitigated by `cleanup_stale_vms()` at startup.

## Direct VNC instead of SSH tunnel

**Decision:** VNCClient_Lume connects directly to `localhost:<vnc_port>` exposed by Lume, rather than tunneling through SSH like VNCClient_SSH.

**Why:** Lume runs on the same host as the benchmark, so SSH tunneling adds unnecessary overhead and complexity. The VNC port is dynamically allocated by `lume run` and retrieved via `lume get -f json` → `vncUrl` field.

## Pre-warm apps before grading

**Decision:** Call `_pre_warmup_for_grading()` before executing any grading commands. Also run `_prewarm_apps()` during `clone_and_start()`.

**Why:** macOS Apple Events (osascript) has a cold-start penalty of 24-60 seconds on first invocation per app. Without warmup, grading commands time out at the 75s subprocess limit. Warmup launches each app and exercises its scripting interface so subsequent calls return in <5s. See [grading](grading.md) for details.

## Popen for lume run (non-blocking)

**Decision:** `start_vm()` uses `subprocess.Popen` with stdout/stderr redirected to DEVNULL, then polls for "running" status.

**Why:** `lume run --no-display` blocks until the VM shuts down. We need the VM running in the background while the benchmark proceeds. The Popen handle is kept for cleanup but output is discarded.

## command→alt key mapping in VNC

**Decision:** In `_filter_key()`, `command`/`cmd` maps to `alt`, and `option` maps to `meta`.

**Why:** vncdotool's KEYMAP uses X11 keysym names. On macOS-over-VNC, the physical Command key corresponds to `alt` in X11 terminology, and Option corresponds to `meta`. This was verified empirically on keyboardtester.com. The mapping enables hotkeys like `command+space` (Spotlight) to work correctly.

## UUID-based task VM names

**Decision:** Each task VM is named `macosworld_<8-char-hex>` using `uuid.uuid4().hex[:8]`.

**Why:** Prevents naming collisions when multiple benchmarks run in sequence. The `macosworld_` prefix enables `cleanup_stale_vms()` to identify and delete orphaned VMs from crashed runs without touching golden VMs or unrelated VMs.

## Socket-based IPC for testbench timeout

**Decision:** `run.py` creates a TCP socket, passes the port to `testbench.py`, and waits for a "DONE" message with a 12-hour timeout.

**Why:** `subprocess.run` timeout doesn't work well for long-running processes. The socket approach lets `run.py` kill a stuck testbench after 12 hours, clean up, and restart. Interrupted tasks get re-benchmarked on the next loop iteration.

## Strategy pattern for VM backends

**Decision:** `run_task()` selects one of three VM backends (Lume / VMware / EC2) via CLI flags (`--lume_golden_vm`, `--vmx_path`, or default EC2) using if/elif/else branching.

**Why:** Each backend has distinct lifecycle semantics (clone vs revert vs replace-root-volume) but the 8-phase execution pipeline is identical. The strategy selection at Phase 1 keeps the rest of `run_task()` backend-agnostic.

## File-based state machine instead of database

**Decision:** Task state is tracked by file presence (`eval_result.txt`, `fail.flag`, `context/`) in the results directory rather than a database.

**Why:** No external dependency, works on any filesystem, naturally idempotent. `cleanup.py` and `completion_checker.py` can operate by scanning directories without coordination. Also enables future distributed execution where workers write to a shared NFS mount without locking.

## Hierarchical retry with 4 levels

**Decision:** Retries are nested at 4 levels: task attempt (testbench), VM reset (run_task Phase 1), SSH connectivity (Phase 2), and pre-command (Phase 3).

**Why:** Different failure modes require different recovery strategies. A transient SSH failure shouldn't restart the whole task; a VM clone failure shouldn't abort the benchmark. Each level catches failures at the appropriate granularity and escalates only when retries are exhausted.

## Try-finally guaranteed cleanup

**Decision:** `run_task()` wraps Phases 1-7 in `try:` and VNC disconnect + Lume VM cleanup in `finally:`. Cleanup exceptions are caught and logged but never re-raised.

**Why:** Resource leaks (orphaned VMs, dangling VNC connections) are worse than swallowed cleanup errors. Even if grading crashes with an unhandled exception, the ephemeral VM is always destroyed and VNC is always disconnected.

## Async in-process event injection

**Decision:** Distraction events use a background `AsyncSSHCommandHandler` that runs an SSH command during the agent loop and captures stdout/stderr after the loop finishes.

**Why:** The distraction test needs the event to occur concurrently with agent steps — blocking would defeat the purpose. The handler injects at a specific timestep, then results are evaluated against gold/distraction criteria to measure agent focus resilience.
