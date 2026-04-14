# macOSWorld: VMware → Lume 迁移实现计划

## 1. 背景与动机

### 1.1 当前架构（VMware Workstation）

macOSWorld 评测框架通过 VMware Workstation 在 Linux/Windows 主机上运行 macOS 虚拟机。核心流程：

```
run.py (循环调度)
  → cleanup.py (清理中断任务)
  → testbench.py (遍历所有 task)
    → run_task.py (单个 task 执行)
      ├─ VMwareTools.revert_to_snapshot()    # 恢复快照
      ├─ VNCClient_SSH.connect()             # SSH 隧道 + VNC 连接
      ├─ gui_agent.step()                    # Agent 交互循环
      └─ Evaluator()                         # SSH 执行评分命令
```

**VMware 关键依赖点：**

| 组件 | VMware 实现 | 调用方式 |
|------|-------------|----------|
| 快照恢复 | `vmrun revertToSnapshot` | `vmware_utils.py` subprocess |
| VM 启动 | `vmrun start` | `vmware_utils.py` subprocess |
| 获取 IP | `vmrun getGuestIPAddress` | `vmware_utils.py` subprocess |
| 截图 | `vmrun captureScreen` | `VNCClient.py` (VMware 模式) |
| VMware Tools | `vmrun runScriptInGuest` | `vmware_utils.py` |
| SSH 命令 | `ssh -i pem user@ip` | 多处使用 |
| VNC 连接 | SSH 隧道到 localhost:5900 | `sshtunnel` + `vncdotool` |

### 1.2 Lume 的能力

Lume v0.3.9 是一个轻量级 macOS VM CLI，基于 Apple Virtualization.framework，**仅运行于 macOS（Apple Silicon）主机**。

**Lume 已具备的能力：**
- `lume create` - 创建 VM（支持 unattended setup）
- `lume clone` - 克隆 VM
- `lume run` - 启动 VM（内建 VNC server，自动分配端口）
- `lume stop` - 停止 VM
- `lume ssh` - SSH 执行命令（内建密码认证，默认 lume/lume）
- `lume get` - 获取 VM 详细信息（JSON 输出含 IP、状态、VNC 端口等）
- `lume pull/push` - 从 GHCR 拉取/推送 VM 镜像
- `lume serve` - REST API server（端口 7777）
- `lume set` - 修改 VM 配置（CPU、内存、磁盘、分辨率）

**Lume 不具备的能力（关键缺口）：**
- ❌ **没有快照（snapshot）功能** — 无 revert/create snapshot 命令
- ❌ 没有 `captureScreen` 等价命令（需要通过 VNC 截图）
- ❌ 没有 VMware Tools 等价物（guest agent）

### 1.3 迁移目标

在 Apple Silicon Mac 上用 Lume 替换 VMware Workstation 运行 macOSWorld 评测，实现：
- 无需 VMware 许可证和 unlocker 的原生 macOS 虚拟化
- 利用 Apple Silicon 的硬件虚拟化加速
- 通过 clone 机制替代 snapshot 恢复

---

## 2. 核心设计决策

### 2.1 快照恢复替代方案：Clone-based Recovery

**问题：** VMware 的 `revertToSnapshot` 是评测环境重置的核心。Lume 没有快照功能。

**方案：** 使用 "golden VM" + `lume clone` 模式

```
准备阶段:
  golden_vm (基线模板 VM，始终关机状态)
  
每个 task 执行:
  1. lume clone golden_vm → task_vm_<uuid>    # 从模板克隆
  2. lume run task_vm_<uuid> --no-display     # 启动克隆
  3. 等待 VM 就绪（SSH 可连接）
  4. 执行 task
  5. lume stop task_vm_<uuid>                  # 停止
  6. lume delete task_vm_<uuid> --force        # 删除克隆
```

**多快照支持：** 原项目有多个快照（`snapshot_used_en`、`snapshot_usedApps_zh` 等），对应不同语言环境。在 Lume 中需要为每个快照创建一个 golden VM：

```
golden_used_en        # 对应 snapshot_used_en
golden_used_zh        # 对应 snapshot_used_zh
golden_usedApps_en    # 对应 snapshot_usedApps_en
...
```

### 2.2 VNC 连接方式

**VMware 方案：** SSH 隧道到 guest 的 localhost:5900
**Lume 方案：** Lume 内建 VNC server，直接暴露到 host

```python
# 获取 VNC 端口
vm_info = json.loads(subprocess.check_output(["lume", "get", vm_name, "-f", "json"]))
vnc_port = vm_info["vncPort"]  # 或 vncUrl

# 直接连接，无需 SSH 隧道
client = api.connect(f'localhost::{vnc_port}', password=vnc_password)
```

### 2.3 SSH 连接方式

**VMware 方案：** `ssh -i credential.pem user@<vm_ip>`
**Lume 方案：** `lume ssh <vm_name> "<command>"` 或直接 SSH（Lume 自动处理密码认证）

推荐直接用 `lume ssh` 命令封装，减少密钥管理复杂度。

### 2.4 截图方式

**VMware 方案：** `vmrun captureScreen`（VNC 截图在 VMware 上慢，所以用 vmrun）
**Lume 方案：** 直接用 VNC 截图（Lume 基于本地虚拟化，VNC 性能好）

---

## 3. 文件修改清单

### 3.1 新增文件

| 文件 | 说明 |
|------|------|
| `utils/lume_utils.py` | Lume VM 管理工具类（替代 `vmware_utils.py`） |
| `utils/lume_vm_pool.py` | VM 池管理器（可选，用于并行评测优化） |
| `constants_lume.py` | Lume 专用常量（golden VM 名称映射等） |
| `instructions/configure_lume_env.md` | Lume 环境配置指南 |

### 3.2 修改文件

| 文件 | 修改内容 |
|------|----------|
| `utils/VNCClient.py` | 新增 `VNCClient_Lume` 类或修改 `VNCClient_SSH` 支持 Lume 模式 |
| `utils/run_task.py` | 环境重置逻辑分支：VMware / AWS / Lume |
| `testbench.py` | 添加 `--lume_vm` 参数 |
| `run.py` | 传递 Lume 相关参数 |
| `constants.py` | 添加 Lume golden VM 映射表 |

### 3.3 不需要修改的文件

| 文件 | 原因 |
|------|------|
| `agent/*` | Agent 层通过 VNCClient 抽象交互，不感知 VM 后端 |
| `utils/evaluator.py` | 基于 SSH，只要能 SSH 到 VM 即可 |
| `utils/async_utils.py` | 基于 SSH，同上 |
| `tasks/*` | Task JSON 不变 |

---

## 4. 详细实现计划

### Phase 1: `utils/lume_utils.py` — Lume 管理工具类

```python
class LumeTools:
    """Lume VM 管理工具，替代 VMwareTools"""

    def __init__(self, vm_name: str, guest_username: str = "lume",
                 guest_password: str = "lume"):
        self.vm_name = vm_name
        self.guest_username = guest_username
        self.guest_password = guest_password

    def clone_and_start(self, golden_vm_name: str, timeout_seconds: int = 120) -> tuple[bool, dict]:
        """
        从 golden VM 克隆并启动一个新 VM。
        返回 (success, vm_info_dict)
        vm_info_dict 包含 ip, vnc_port 等信息
        """
        # 1. lume clone golden_vm_name → self.vm_name
        # 2. lume run self.vm_name --no-display --vnc-port 0
        # 3. 轮询 lume get self.vm_name -f json 直到获取 IP
        # 4. 等待 SSH 就绪
        pass

    def stop_and_cleanup(self):
        """停止并删除 VM"""
        # 1. lume stop self.vm_name
        # 2. lume delete self.vm_name --force
        pass

    def get_vm_info(self) -> dict:
        """获取 VM 信息（IP、VNC 端口、状态等）"""
        # lume get self.vm_name -f json
        pass

    def run_ssh_command(self, command: str) -> tuple[bool, str]:
        """通过 lume ssh 执行命令"""
        # lume ssh self.vm_name "<command>" -u user -p password
        pass

    def check_ssh_connectivity(self) -> bool:
        """检查 SSH 连通性"""
        # lume ssh self.vm_name "echo ok"
        pass
```

### Phase 2: `utils/VNCClient.py` — 新增 Lume VNC 模式

新增 `VNCClient_Lume` 类，或在 `VNCClient_SSH` 中添加 Lume 分支：

```python
class VNCClient_Lume:
    """基于 Lume 的 VNC 客户端（无需 SSH 隧道）"""

    def __init__(self, vm_name: str, guest_username: str = "lume",
                 guest_password: str = "lume", vnc_password: str = None):
        self.vm_name = vm_name
        self.guest_username = guest_username
        self.guest_password = guest_password
        self.vnc_password = vnc_password
        self.lume_tools = LumeTools(vm_name, guest_username, guest_password)
        self.client = None  # vncdotool client

    def connect(self):
        """直接通过 VNC 端口连接（无 SSH 隧道）"""
        vm_info = self.lume_tools.get_vm_info()
        vnc_port = vm_info["vncPort"]
        self.client = api.connect(
            f'localhost::{vnc_port}',
            password=self.vnc_password
        )

    def capture_screenshot(self):
        """纯 VNC 截图（Lume 本地虚拟化性能好，不需要 vmrun）"""
        fp = io.BytesIO()
        fp.name = 'screenshot.png'
        self.client.captureScreen(fp)
        fp.seek(0)
        image = Image.open(fp)
        return image

    def run_ssh_command(self, command: str) -> tuple[bool, str]:
        """通过 lume ssh 执行命令"""
        return self.lume_tools.run_ssh_command(command)

    def check_ssh_connectivity(self) -> bool:
        return self.lume_tools.check_ssh_connectivity()

    # ... 其余 VNC 操作方法（click, move_to, key_press 等）
    # 与 VNCClient_SSH 完全相同，因为都通过 vncdotool 操作
```

**关键差异：**
- 不需要 `SSHTunnelForwarder`，直接连接 Lume 暴露的 VNC 端口
- 截图统一用 VNC，不需要 vmrun captureScreen
- SSH 命令通过 `lume ssh` 执行，不需要 PEM 密钥

### Phase 3: `utils/run_task.py` — 添加 Lume 环境重置分支

在 `run_task()` 函数中添加第三个分支：

```python
def run_task(..., lume_golden_vm: str = None, ...):
    if override_env_reset:
        # 手动模式
        ...
    elif lume_golden_vm is not None:
        # Lume 模式
        task_vm_name = f"macosworld_task_{uuid.uuid4().hex[:8]}"
        golden_vm_name = lume_snapshot_lookup[snapshot_name]  # 映射 snapshot → golden VM

        lume_tools = LumeTools(task_vm_name)
        success, vm_info = lume_tools.clone_and_start(golden_vm_name)
        if not success:
            raise RuntimeError(f"Failed to start Lume VM from {golden_vm_name}")

        ssh_host = vm_info["ip"]
        vnc_port = vm_info["vnc_port"]

        remote_client = VNCClient_Lume(
            vm_name=task_vm_name,
            vnc_password=vm_info.get("vnc_password")
        )
    elif vmx_path is not None:
        # VMware 模式（现有逻辑不变）
        ...
    else:
        # AWS 模式（现有逻辑不变）
        ...

    # ... 后续流程不变（connect, agent.step, evaluate）

    # Lume 清理
    if lume_golden_vm is not None:
        lume_tools.stop_and_cleanup()
```

### Phase 4: 参数传递链路更新

**`run.py`** 添加：
```python
parser.add_argument('--lume_golden_vm', type=str, default=None,
                    help='使用 Lume 模式时的 golden VM 前缀名')
```

**`testbench.py`** 添加相同参数并传递给 `run_task()`。

**`constants.py`** 添加映射：
```python
lume_snapshot_lookup = {
    'snapshot_used_en': 'golden_used_en',
    'snapshot_used_zh': 'golden_used_zh',
    'snapshot_used_ar': 'golden_used_ar',
    'snapshot_used_ja': 'golden_used_ja',
    'snapshot_used_ru': 'golden_used_ru',
    'snapshot_usedApps_en': 'golden_usedApps_en',
    'snapshot_usedApps_zh': 'golden_usedApps_zh',
    'snapshot_usedApps_ar': 'golden_usedApps_ar',
    'snapshot_usedApps_ja': 'golden_usedApps_ja',
    'snapshot_usedApps_ru': 'golden_usedApps_ru',
}
```

### Phase 5: Golden VM 准备流程

需要为每个 snapshot 创建对应的 golden VM：

```bash
# 1. 创建基础 VM
lume create macosworld_base --ipsw latest --cpu 4 --memory 8GB \
    --disk-size 100GB --display 1024x768 --unattended sequoia

# 2. 启动并配置环境（手动或脚本）
lume run macosworld_base
# 配置：安装所需 apps, 设置语言, 启用 Remote Login (SSH), 设置用户密码等

# 3. 为每种语言环境克隆 golden VM
lume stop macosworld_base
lume clone macosworld_base golden_used_en
lume clone macosworld_base golden_used_zh
# ... 分别启动每个克隆，设置对应语言环境，然后停止

# 4. 或者从 GHCR 拉取预制镜像（如果将来发布的话）
# lume pull macosworld:used_en golden_used_en
```

---

## 5. 风险与缓解措施

### 5.1 Clone 性能

| 风险 | 影响 | 缓解 |
|------|------|------|
| Clone + Start 比 snapshot revert 慢 | 每个 task 额外等待时间 | Lume clone 是文件级复制（~50GB），在 SSD 上应在 1-2 分钟完成。后续可用 APFS clonefile 加速 |
| 磁盘空间消耗 | 每个 clone ~50GB | 每个 task 完成后立即删除 clone |

### 5.2 VNC 连接稳定性

| 风险 | 缓解 |
|------|------|
| Lume VNC 端口动态分配 | 每次通过 `lume get -f json` 获取实际端口 |
| VNC 密码随机生成 | 启动时指定 `--vnc-password` 或从 get 输出获取 |

### 5.3 SSH 连通性

| 风险 | 缓解 |
|------|------|
| Lume VM 需要预配置 Remote Login | 使用 `--unattended` 创建的 VM 已启用 SSH |
| 默认用户名密码 (lume/lume) 与原项目不同 | `lume ssh` 自动处理密码认证 |

### 5.4 macOS 版本兼容性

| 风险 | 缓解 |
|------|------|
| Lume 使用 Virtualization.framework，仅支持 macOS 13+ | 评测目标本身就是 macOS，不影响 |
| 某些 app 行为可能因 macOS 版本不同而异 | 选择与原评测一致的 macOS 版本 |

### 5.5 平台限制

| 风险 | 缓解 |
|------|------|
| Lume 仅支持 Apple Silicon Mac | 明确标注为 Apple Silicon 专用实现 |
| 无法在 Linux/x86 CI 上运行 | 保留 VMware/AWS 路径作为备选 |

---

## 6. 实现优先级与里程碑

### Milestone 1: 基础 Lume 集成（核心路径打通）
**预计耗时：2-3 天**

- [ ] 实现 `utils/lume_utils.py` — LumeTools 类
- [ ] 实现 `VNCClient_Lume` 类（或修改 VNCClient_SSH）
- [ ] 修改 `run_task.py` 添加 Lume 分支
- [ ] 修改 `testbench.py` 和 `run.py` 传递 Lume 参数
- [ ] 手动创建一个 golden VM 并跑通单个 task

### Milestone 2: 环境准备自动化
**预计耗时：1-2 天**

- [ ] 编写 golden VM 创建脚本（或文档）
- [ ] 为所有 10 个 snapshot 创建对应 golden VM
- [ ] 验证各语言环境 VM 正常工作

### Milestone 3: 端到端验证
**预计耗时：1-2 天**

- [ ] 每个 task 类别各跑几个 task 验证
- [ ] 对比 VMware 和 Lume 的评测结果一致性
- [ ] 修复发现的问题

### Milestone 4: 优化（可选）
**预计耗时：2-3 天**

- [ ] VM Pool 预热机制（提前克隆，减少等待）
- [ ] APFS clonefile 快速克隆
- [ ] 并行评测支持（多个 VM 同时运行）
- [ ] `lume serve` REST API 集成（替代 CLI 调用）

---

## 7. 使用方式（目标）

```bash
# 环境准备
# 1. 安装 lume: brew install lume (或从 GitHub releases)
# 2. 创建/拉取 golden VMs
# 3. 验证: lume ls 能看到所有 golden VMs

# 运行评测
python run.py \
    --lume_golden_vm golden \
    --gui_agent_name gpt-4o-2024-08-06 \
    --paths_to_eval_tasks ./tasks/sys_apps ./tasks/sys_and_interface \
    --languages task_en_env_en task_zh_env_zh \
    --base_save_dir ./results/gpt_4o \
    --max-steps 15
```

---

## 8. 架构对比总结

```
VMware 模式:
  vmrun revertToSnapshot → vmrun start → vmrun getGuestIPAddress
  → SSH tunnel → VNC (localhost:5900) → vmrun captureScreen

Lume 模式:
  lume clone → lume run → lume get (IP + VNC port)
  → VNC (localhost:<port>) → VNC captureScreen
  → lume ssh (命令执行)
  → lume stop + lume delete (清理)

AWS 模式 (不变):
  EC2 replace root volume → SSH → VNC → SSH evaluate
```

三种模式共享同一个 Agent 层和评分层，仅 VM 管理和连接方式不同。
