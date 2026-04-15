Scaling architecture: single-machine baseline and distributed execution design.
---

## Current: Single-Machine Execution

```
run.py (Supervisor)
  └─► testbench.py (Sequential)
      ├─► run_task(task_1) → eval_result_1.txt
      ├─► run_task(task_2) → eval_result_2.txt
      └─► run_task(task_N) → eval_result_N.txt

Duration: O(N × avg_task_time)
Resources: 1 host + coordination process
Bottleneck: Sequential task execution
```

## Why Distribution Is Straightforward

The system already has the properties needed for parallelization:

- **No cross-task dependencies.** Every `run_task()` call is independent.
- **File-based state.** Task completion is determined by `eval_result.txt` presence — no central database required.
- **Idempotent cleanup.** `cleanup.py` and `completion_checker.py` are safe to run concurrently from multiple workers.
- **Ephemeral VMs.** Each task gets a fresh VM, so no shared mutable state during execution.

## Proposed: Distributed Execution

```
Coordinator Service
  ├─ Task Queue: [(task_id, task_lang, env_lang), ...]
  ├─ Shared State: NFS / shared filesystem for {base_save_dir}
  └─ Health Check: Worker heartbeats

Worker Nodes (N parallel):
  ├─► Worker 1: run_task(dequeue())
  ├─► Worker 2: run_task(dequeue())
  └─► Worker N: run_task(dequeue())

Duration: O(N × avg_task_time / num_workers)
```

### What Changes

| Component | Current | Distributed |
|-----------|---------|-------------|
| `testbench.py` loop | Sequential for-loop | Queue consumer (pull next task) |
| `run.py` supervisor | Single process, socket IPC | Multiple workers + coordinator |
| IPC | TCP socket `DONE` message | Message queue (Redis, RabbitMQ, etc.) |
| Result storage | Local filesystem | Shared NFS mount |

### What Stays the Same

- `run_task()` Phases 1-8 execution model
- File-based state machine (`eval_result.txt`, `fail.flag`)
- Try-finally cleanup guarantee
- Retry logic at Levels 2-4 (VM reset, SSH, pre-command)

## Extension Points

### Adding New Languages

1. Add mapping in `constants.language_lookup_table`
2. Add snapshot names and AMIs to `constants.ami_lookup_table`
3. Add Lume VM names to `constants.lume_snapshot_lookup`
4. Create task JSONs with new language fields

### Adding New GUI Agents

1. Implement agent class with `.step()` method (see `agent/template_for_custom_agent.py`)
2. Register in `agent/get_gui_agent.py` dispatcher
3. Pass `--gui_agent_name` on CLI

### Adding New VM Backends

1. Implement backend class with clone/start/stop/cleanup lifecycle
2. Add backend-specific init branch in `run_task()` Phase 1
3. Add VNC client variant if connection semantics differ

## Monitoring Metrics (Future)

For distributed runs, key metrics to track:

- `tasks_completed / hour` — throughput
- `failure_rate` — percentage of tasks needing retry
- `avg_task_time` — per-task latency
- `queue_depth` — backlog size
- `worker_health` — heartbeat freshness

## See Also

- [architecture](architecture.md) — retry hierarchy and state machine details
- [decisions](decisions.md) — why file-based state was chosen
- [lume-backend](lume-backend.md) — Lume VM management specifics
