# Lume Quick Reference Guide

## Installation & Status
- **Installed:** Yes (`/Users/hanlynnke/.local/bin/lume`)
- **Version:** v0.3.9
- **Current VMs:** 0
- **Cached Images:** 0

## Essential Commands

### Getting Help
```bash
lume --help                    # Show all available commands
lume help create              # Show detailed help for 'create' command
lume help run                 # Show detailed help for 'run' command
lume dump-docs                # Export full API documentation as JSON
```

### VM Creation & Setup
```bash
# Pull latest macOS image
lume pull macOS:latest

# Create a new VM (minimal)
lume create my-vm

# Create with custom specs
lume create my-vm \
  --cpu 8 \
  --memory 16GB \
  --disk-size 100GB \
  --display 1280x800 \
  --ipsw latest

# Create with network and sharing
lume create my-vm \
  --network bridged:en0 \
  --shared-dir ~/Documents:rw
```

### VM Lifecycle
```bash
lume ls                       # List all VMs
lume get my-vm               # Get VM details
lume run my-vm               # Start VM with VNC display
lume run my-vm --no-display  # Start VM without VNC
lume stop my-vm              # Stop VM gracefully
lume delete my-vm            # Delete VM
```

### Remote Access
```bash
# SSH into VM
lume ssh my-vm

# Run command in VM
lume ssh my-vm "command here"

# Run in VM with output
lume ssh my-vm whoami
```

### VM Operations
```bash
# Clone an existing VM
lume clone existing-vm --name new-vm

# Adjust VM resources
lume set my-vm --cpu 16 --memory 32GB --disk-size 200GB

# Get macOS IPSW URL
lume ipsw
```

### Image Management
```bash
lume images                   # List cached images
lume pull org/repo:tag        # Pull from GitHub Container Registry
lume push my-vm               # Push to registry
lume convert legacy-image     # Convert to OCI format
lume prune                    # Remove cached images
```

### Server Mode
```bash
# Start HTTP API server
lume serve --port 7777

# Start MCP server (for AI agents)
lume serve --mcp

# View server logs
lume logs
```

## VM Access Methods

### 1. VNC (Graphical)
- Auto-opened when running `lume run <name>`
- Auto port assignment (check output for port)
- Password protected (auto-generated)
- Connect manually: Use VNC client to `localhost:PORT`

### 2. SSH (Terminal)
```bash
lume ssh my-vm                    # Interactive shell
lume ssh my-vm "echo hello"       # Execute command
```

### 3. REST API (When running `serve`)
```bash
# Example: List VMs
curl http://localhost:7777/vms

# Example: Get VM status
curl http://localhost:7777/vms/my-vm
```

## Configuration Tips

### Network Modes
- **NAT** (default): VM isolated, good for testing
- **Bridged**: VM gets IP from network, good for shared access
- **Bridged:interface**: Explicit interface (e.g., `bridged:en0`)

### Storage Options
- **Shared directories:** `--shared-dir ~/path:rw` or `:ro`
- **USB storage:** `--usb-storage disk.img`
- **Disk image:** `--disk-path /custom/path/disk.img`

### Display Settings
- **Default:** 1024x768
- **Custom:** `--display 1920x1080`
- **Recovery mode:** `--recovery-mode`

### Unattended Setup (Preview)
```bash
lume create my-vm \
  --unattended sequoia \
  --debug \
  --debug-dir /tmp/debug
```

## Integration with macosworld_lume

### Current Approach
- macosworld_lume uses **VMware Workstation**
- Connection via SSH tunnel + VNC
- Snapshot recovery: ~10-15 minutes per task

### Migration Strategy
1. **Test phase:** Run Lume in parallel
2. **Abstract layer:** Create VM backend interface
3. **Validation:** Benchmark consistency checking
4. **Migration:** Switch to Lume backend

### Required Changes for Integration
```python
# Create abstraction layer
class VMManager:
    def __init__(self, backend='vmware'):  # or 'lume'
        self.backend = backend
    
    def connect(self):
        # Backend-agnostic connection
        pass
    
    def snapshot_restore(self):
        # Backend-agnostic restoration
        pass
    
    def screenshot(self):
        # Backend-agnostic screenshot
        pass
```

## Performance Expectations

### Lume vs VMware (from macosworld_lume README)

| Operation | VMware | Lume |
|-----------|--------|------|
| Snapshot Recovery | 10-15 min | <1 min |
| VM Creation | ~5 min | ~3 min |
| VM Startup | 2-3 min | 1-2 min |
| Resource Overhead | Higher | Lower |

## Troubleshooting

### VMs Not Showing
```bash
# List with debug
lume ls --debug

# Check logs
lume logs
```

### SSH Connection Issues
```bash
# Test SSH connectivity
lume ssh my-vm "echo test"

# Check if VM is running
lume get my-vm
```

### Image Not Found
```bash
# List available images
lume images

# Pull the image
lume pull macOS:latest
```

### Server Won't Start
```bash
# Check if port is in use
lsof -i :7777

# Try different port
lume serve --port 7778
```

## Next Steps for macosworld_lume

### Short Term (Current)
- ✅ Maintain VMware integration
- ✅ Keep Lume as reference alternative
- ⚠️ Monitor Lume development

### Medium Term (Q2-Q3 2026)
- 📋 Set up parallel Lume test VM
- 📋 Document integration points
- 📋 Profile performance differences
- 📋 Create abstraction layer prototype

### Long Term (Q4 2026+)
- 🔄 Evaluate full migration
- 🔄 Implement dual-backend support
- 🔄 Transition to Lume as primary

## Resources

- **Lume GitHub:** https://github.com/trycua/lume
- **Documentation:** `lume help <command>`
- **API Docs:** `lume dump-docs | jq`
- **Container Registry:** ghcr.io/trycua/

## Key Advantages of Lume for macosworld_lume

1. **90% faster snapshots** → Massively reduced benchmark time
2. **No licensing fees** → Cost savings
3. **Native API** → Easier integration with agents
4. **Open source** → Community-driven improvements
5. **Container-based** → Better distribution and reproducibility
6. **MCP support** → Seamless AI agent integration

