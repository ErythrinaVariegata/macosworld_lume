# macosworld_lume

macOSWorld benchmark with Lume VM backend for Apple Silicon Macs. Evaluates GUI agents on macOS tasks using clone-based environment reset, VNC-based interaction, and osascript-based grading.

## Wiki

This project maintains a 3-layer knowledge base following the [LLM Wiki](https://gist.github.com/karpathy/442a6bf555914893e9891c11519de94f) pattern:

| Layer | Location | Owner | Purpose |
|-------|----------|-------|---------|
| Raw sources | `wiki/raw/` | Human | Immutable source documents. Never modified by LLM. |
| Wiki | `wiki/` | LLM | Synthesized, cross-referenced knowledge pages. LLM writes; human reads. |
| Schema | This file | Human + LLM | Conventions, workflows, quick reference. Co-evolved. |

### Workflows

**Ingest** — When new knowledge is discovered (bug fix, architecture change, new feature):
1. If there's a source document, place it in `wiki/raw/`
2. Read relevant wiki pages via `wiki/index.md`
3. Update or create wiki pages with new information
4. Update `wiki/index.md` with any new/changed pages
5. Append entry to `wiki/log.md`: `## [YYYY-MM-DD] ingest | <title>`

**Query** — When answering questions about the project:
1. Read `wiki/index.md` to find relevant pages
2. Read those pages, synthesize answer
3. If the answer is reusable, file it back into the wiki

**Lint** — Periodic health check:
1. Check for contradictions between wiki pages and current code
2. Flag stale claims superseded by recent changes
3. Find orphan pages with no inbound links
4. Identify missing cross-references

### Conventions

- Wiki pages use kebab-case filenames: `lume-backend.md`, not `LUME_BACKEND.md`
- Cross-reference with relative links: `[grading](grading.md)`
- Each page starts with a one-line summary, then `---`, then content
- `wiki/raw/` files are NEVER modified — they are historical artifacts

## Quick Reference

```bash
# Run benchmark
source .venv/bin/activate
python run.py --lume_golden_vm <vm-name> --gui_agent_name tione \
  --paths_to_eval_tasks ./tasks/sys_apps_single --languages task_zh_env_zh \
  --base_save_dir ./results/output

# Lume VM management
lume ls -f json              # list VMs
lume clone <src> <dst>       # clone golden VM
lume run <name> --no-display # start headless
lume stop <name>             # stop VM
lume delete <name> --force   # delete VM
lume ssh <name> "<cmd>" -u lume -p lume -t 30  # run command

# Prepare golden VM (one-time)
./scripts/prepare_golden_vm.sh <golden-vm-name>
```

## Key Environment Variables

- `MODEL_BASE_URL` — OpenAI-compatible API endpoint for GUI agent
- `MODEL_API_KEY` — API key (may be empty for some endpoints)

## Project Structure

```
run.sh              → shell wrapper with env vars
run.py              → outer loop: cleanup → check completion → testbench
testbench.py        → iterate tasks, call run_task per task
utils/run_task.py   → single task: VM setup → agent loop → grading → cleanup
utils/lume_utils.py → LumeTools: clone, start, SSH, VNC, TCC permissions
utils/lume_adapters.py → LumeEvaluator, LumeAsyncSSHCommandHandler
utils/VNCClient.py  → VNCClient_Lume: screenshot, mouse, keyboard via VNC
agent/tione.py      → TiOne GUI agent (OpenAI-compatible, CUA-style)
constants.py        → screen size, lookup tables, init commands
```
