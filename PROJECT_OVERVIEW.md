# macosworld_lume Project Overview

## Project Purpose

**macOSWorld** is a **multilingual interactive benchmark for GUI agents** that evaluates how artificial intelligence agents interact with macOS GUI applications in a realistic environment.

### Key Metrics
- **Status:** Accepted to NeurIPS 2025
- **Framework:** Python-based benchmark system
- **VM Backend:** VMware Workstation (current)
- **Agent Models:** 8+ different AI models supported
- **Languages:** 5 (English, Chinese, Arabic, Japanese, Russian)
- **Task Categories:** 8 categories with 30+ macOS-native applications
- **Benchmark Scale:** Multilingual interactive tasks with multiple difficulty levels

---

## Project Architecture

```
macosworld_lume/
│
├── 📋 Core Execution
│   ├── run.py                    # Main benchmark runner with 12-hour timeout
│   ├── testbench.py              # Core testing framework for task execution
│   ├── cleanup.py                # Result cleanup and interrupt handling
│   └── constants.py              # Configuration and constants
│
├── 🤖 AI Agent Implementations
│   ├── agent/
│   │   ├── get_gui_agent.py      # Agent factory pattern
│   │   ├── openai.py             # GPT-4o vision model
│   │   ├── openai_omniparser.py  # GPT-4o with SoM (Set of Marks) annotations
│   │   ├── openai_cua.py         # OpenAI Computer Use API
│   │   ├── anthropic.py          # Claude with Computer Use
│   │   ├── gemini.py             # Google Gemini models
│   │   ├── showui.py             # ShowUI model (open source)
│   │   ├── uitars.py             # UI-TARS model (open source)
│   │   └── template_for_custom_agent.py  # Template for new agents
│
├── 📝 Benchmark Tasks
│   ├── tasks/
│   │   ├── sys_apps/             # System applications (Mail, Calendar, etc.)
│   │   ├── sys_and_interface/    # System UI interactions
│   │   ├── file_management/      # File operations and Finder
│   │   ├── productivity/          # Productivity apps (Pages, Numbers, etc.)
│   │   ├── media/                # Media apps (Photos, etc.)
│   │   ├── multi_apps/           # Multi-application workflows
│   │   ├── advanced/             # Advanced tasks (iMovie, etc.)
│   │   └── safety/               # Safety evaluation subset
│
├── 🛠️ Utilities & Infrastructure
│   ├── utils/
│   │   ├── vncclient_ssh.py      # SSH/VNC client for VM control
│   │   ├── completion_checker.py # Task completion verification
│   │   ├── vmware_tools.py       # VMware-specific operations
│   │   ├── log.py                # Logging utilities
│   │   ├── api.py                # API client management
│   │   └── [others]              # Various helper modules
│
├── 📊 Analysis & Visualization
│   ├── scripts/
│   │   ├── display_progress.py   # GUI progress display
│   │   ├── display_progress.ipynb # Jupyter notebook interface
│   │   ├── aggregate_results.ipynb # Result aggregation
│   │   ├── aggregate_results_utils.py
│   │   ├── simple_remote_control.ipynb # Manual VM control
│   │   ├── cleanup_result_directory.ipynb
│   │   └── replace_root_volume.ipynb
│
├── 📚 Documentation
│   ├── readme.md                 # Main documentation
│   ├── instructions/
│   │   ├── configure_vmware_env.md    # VMware setup guide
│   │   └── VNCClient_SSH_documentation.md  # Connection API docs
│   ├── LUME_ANALYSIS.md          # Lume vs VMware comparison (NEW)
│   ├── LUME_QUICK_REFERENCE.md   # Lume command reference (NEW)
│   └── PROJECT_OVERVIEW.md       # This file (NEW)
│
├── 🔐 Credentials & Configuration
│   ├── credential.pem            # SSH private key for VM access
│   ├── assets/                   # Project assets and media
│   └── .git/                     # Git repository
│
└── 📄 License
    └── LICENSE                   # Project license

```

---

## Execution Flow

### Benchmark Execution Pipeline

```
                            run.py
                            │
                ┌───────────┴───────────┐
                │                       │
           cleanup.py              Check completion
           (Task cleanup)           (all_tasks_completed)
                │                       │
                ├───────────┬───────────┤
                │           │           │
            ✅ Done     ⏳ In Progress  ❌ Not Done
                │           │           │
            [DONE]      [CONTINUE]   testbench.py
                                        │
                            ┌───────────┴───────────┐
                            │                       │
                     For each task:          Connect to VM
                            │                (VNCClient_SSH)
                            │                       │
                    ┌───────┴────────┐        ┌─────┴──────┐
                    │                │        │             │
                SSH to VM      Load agent   Take snapshot  SSH tunnel
                    │                │        │             │
            ┌───────┴────────┐  ┌────┴────┐  │         ┌────┴────┐
            │                │  │          │  │         │         │
         Reset VM      Select Language  Restore snapshot  VNC     VMware
       (snapshot)                          │       client  tools
                            │              │        │
                     Task:  │         ┌─────────┐   │
                     - Query agent    │Desktop │   │
                     - Get action     │State   │   │
                     - Execute GUI    └─────────┘   │
                     - Capture state               │
                     - Repeat until done    Screenshot (optimized)
                            │
                     ┌───────┴────────┐
                     │                │
              Success/Failure    Save results
                                (JSON/logs)
                            │
                   Next task or Complete
```

---

## Supported AI Agents

### Vision-Based Models (with screenshots)
1. **GPT-4o** (OpenAI)
   - Standard: `gpt-4o`, `gpt-4o-2024-08-06`
   - With SoM: `gpt-4o/omniparser`, `gpt-4o-2024-08-06/omniparser`
   - Computer Use: `openai/computer-use-preview`

2. **Gemini** (Google)
   - `gemini-1.5-pro-002`
   - `gemini-2.5-pro-preview-03-25`

3. **Claude** (Anthropic)
   - `claude-3-7-sonnet-20250219/computer-use-2025-01-24`

### Open-Source Models
4. **UI-TARS-7B-DPO** (Bytedance)
5. **ShowUI-2B** (ShowLab)

### Special Implementations
- **OmniParser**: Set of Marks (SoM) annotations for better UI understanding
- **Computer Use APIs**: Direct API-based control

---

## Task Categories

### 1. System & Interface (sys_and_interface)
- macOS system preferences and settings
- System UI interactions
- Accessibility features

### 2. System Applications (sys_apps)
- Mail, Calendar, Contacts
- Reminders, Notes
- Dictionary, Calculator
- System utilities

### 3. File Management
- Finder operations
- File creation, moving, organizing
- Disk management
- Permissions and properties

### 4. Productivity Applications
- Pages (word processing)
- Numbers (spreadsheets)
- Keynote (presentations)
- Document operations

### 5. Media Applications
- Photos app
- Preview
- Image editing operations
- Media management

### 6. Advanced Applications
- iMovie (video editing) - *Excluded from VMware implementation*
- GarageBand
- Logic Pro
- Other advanced tools

### 7. Multi-App Workflows
- Tasks requiring multiple applications
- Cross-app data transfer
- Complex workflows

### 8. Safety Evaluation
- Context deception tests
- Agent resilience under misleading inputs
- Security-focused evaluations

---

## VM Integration Architecture

### Current: VMware Workstation

```
Benchmark Script (Python)
        │
        ├─ SSH Tunnel Forwarder
        │  └─ Port 5900 (VNC)
        │
        ├─ VNCClient_SSH
        │  ├─ SSH Commands
        │  ├─ VNC Screenshots
        │  ├─ Mouse/Keyboard Control
        │  └─ Scroll Operations
        │
        └─ VMware Tools
           ├─ Snapshot Recovery
           ├─ VM State Management
           └─ Direct Screenshot (optimized)

                    │
                    ↓
        [macOS VM - VMware]
        ├─ Snapshot 1 (Task State)
        ├─ Snapshot 2 (Task State)
        └─ Snapshot N (Task State)
```

### Alternative: Lume

```
Benchmark Script (Python)
        │
        ├─ Lume SSH
        │  └─ Direct SSH to VM
        │
        ├─ Lume VNC
        │  ├─ VNC Server (auto-port)
        │  ├─ Screenshots
        │  ├─ Mouse/Keyboard Control
        │  └─ Scroll Operations
        │
        └─ Lume API
           ├─ REST API (port 7777)
           ├─ MCP Server (stdio)
           └─ VM Management

                    │
                    ↓
        [macOS VM - Lume]
        ├─ Lightweight snapshots
        ├─ Fast recovery (<1 min)
        └─ Container-based distribution
```

---

## Data Flow

### Input Data
```
tasks/
├── */
│   ├── task_uuid_1.json
│   │   {
│   │     "uuid": "...",
│   │     "task": "...",
│   │     "expected_action": "...",
│   │     "language": "en"
│   │   }
│   └── task_uuid_2.json
```

### Output Data
```
results/
├── [agent_name]/
│   ├── [task_category]/
│   │   ├── [task_uuid]/
│   │   │   ├── [language]/
│   │   │   │   ├── trajectory.json
│   │   │   │   ├── screenshots/
│   │   │   │   ├── success.json
│   │   │   │   ├── attempts.json
│   │   │   │   └── logs.txt
│   │   │   └── ...
│   │   └── ...
│   └── ...
```

### Result Format (success.json)
```json
{
  "task_uuid": "...",
  "agent": "gpt-4o-2024-08-06",
  "status": "success|failure|timeout",
  "steps": 5,
  "max_steps": 15,
  "duration_seconds": 120,
  "language_pair": "task_en_env_en",
  "final_state_matches": true
}
```

---

## Benchmark Execution Example

```bash
python run.py \
    --vmx_path /path/to/macOSWorld.vmx \
    --ssh_pkey credential.pem \
    --gui_agent_name gpt-4o-2024-08-06 \
    --paths_to_eval_tasks \
        ./tasks/sys_apps \
        ./tasks/sys_and_interface \
        ./tasks/productivity \
        ./tasks/media \
        ./tasks/file_management \
        ./tasks/multi_apps \
    --languages \
        task_en_env_en \
        task_zh_env_zh \
        task_ar_env_ar \
        task_ja_env_ja \
        task_ru_env_ru \
    --base_save_dir ./results/gpt_4o \
    --max-steps 15 \
    --snapshot_recovery_timeout_seconds 120 \
    --task_step_timeout 120
```

**Key Parameters:**
- `--vmx_path`: VMware VM configuration file
- `--ssh_pkey`: SSH private key for VM access
- `--gui_agent_name`: Which AI model to benchmark
- `--paths_to_eval_tasks`: Which task categories to run
- `--languages`: Language pairs to test (e.g., English task in English environment)
- `--max-steps`: Maximum turns per task conversation
- `--snapshot_recovery_timeout_seconds`: Time allowed for VM recovery

---

## Performance Metrics

### Current VMware Implementation
- **Snapshot Recovery:** 10-15 minutes per task
- **Task Execution:** 2-5 minutes per task (depends on complexity)
- **Total Benchmark:** ~8-10 hours per 100 tasks

### Potential Lume Implementation
- **Snapshot Recovery:** <1 minute per task (claimed)
- **Task Execution:** 2-5 minutes per task (same)
- **Total Benchmark:** ~3-5 hours per 100 tasks (70-80% time savings)

### Hardware Requirements
- **RAM:** 32 GB minimum
- **CPU:** Intel/AMD with AVX2 support
- **Disk:** 400 GB free space
- **Network:** SSH/VNC connectivity required

---

## Key Dependencies

### Python Packages
- `vncdotool==1.2.0` - VNC client library
- `boto3==1.36.20` - AWS SDK (if using EC2)
- `sshtunnel` - SSH tunnel forwarding
- `openai` / `anthropic` / `google-auth` - Model APIs
- `PIL` - Image processing
- `numpy` - Numerical operations
- `supervision==0.18.0` - Vision utilities
- `paddleocr` - OCR capabilities

### External Tools
- `vmrun` - VMware command-line tool
- SSH client
- VNC client

---

## Configuration Management

### Environment Variables
```bash
export OPENAI_API_KEY="sk-proj-..."           # For GPT models
export ANTHROPIC_API_KEY="sk-ant-..."         # For Claude
export GOOGLE_APPLICATION_CREDENTIALS="/path/to/creds.json"  # For Gemini
```

### Credential File
- `credential.pem` - SSH private key (chmod 400)
- Used for authentication to VMware VM

### Constants (constants.py)
```python
SCREEN_WIDTH = 1024
SCREEN_HEIGHT = 768

# AMI lookups for AWS instances
ami_lookup_table = {
    'snapshot_used_en': 'ami-...',
    'snapshot_used_zh': 'ami-...',
    # ... more languages
}
```

---

## Next Steps & Future Roadmap

### Immediate (Current)
- ✅ VMware-based benchmarking is stable
- 📊 Collect baseline results with multiple agents
- 📈 Publish NeurIPS results

### Short-term (Q2 2026)
- 🧪 Set up Lume testing environment
- 📋 Document integration points
- ⚙️ Create VM abstraction layer
- 📊 Profile performance

### Medium-term (Q3 2026)
- 🔄 Implement dual-backend support
- ✨ Run parallel benchmarks on both platforms
- 📈 Compare results and performance
- 🛠️ Optimize Lume integration

### Long-term (Q4 2026+)
- 🚀 Migrate to Lume as primary platform
- 💾 Leverage container registry for distribution
- 🌐 Enable cloud-based benchmarking
- 🤝 Community contributions and improvements

---

## Contributing & Customization

### Adding New Agents
1. Create `agent/your_agent.py` based on template
2. Implement required interface
3. Register in `agent/get_gui_agent.py`

### Adding New Tasks
1. Create JSON task files in appropriate category
2. Follow standard task format
3. Provide translations for all 5 languages

### Adding New Languages
1. Extend `language_lookup_table` in constants.py
2. Provide task translations
3. Update environment setup scripts

---

## Key Contacts & Resources

- **Project Website:** https://macos-world.github.io
- **Paper:** arXiv:2506.04135
- **GitHub:** macosworld_lume repository
- **Conference:** NeurIPS 2025 (accepted)

---

## Summary

**macosworld_lume** is a sophisticated benchmark system that:
1. Evaluates GUI agents on realistic macOS tasks
2. Supports multiple AI models (proprietary and open-source)
3. Provides multilingual evaluation
4. Measures agent performance on 30+ applications
5. Uses VMware for stable, reproducible environments

The system is production-ready and positioned for migration to Lume for better performance and lower costs in 2026.

