# 冒险岛 × Jev：Windows 视觉控制原型

目标是先在一张地图上验证稳定刷怪。截图由本地程序分析，Jev 只接收结构化状态，并从已验证的候选动作中选择。独立的 `rules` 模式用于建立对照基线。

**当前是待 Windows 实机验收的原型，不是已验证可挂机的成品。** tapsvc 认证与请求路由尚未打通；没有用模拟输出冒充真实 Jev。跨平台路线需要人工配置；尚未实现自动地图建模和可靠的绳索寻路。

## 已实现

- Windows 游戏客户区截图、可配置键位、短时扫描码输入。
- 交互式校准：角色名牌、怪物模板、血蓝条、小地图和游戏区域。
- 录像离线分析、标记视频、逐帧 JSONL 日志和识别覆盖率汇总。
- 同高度范围内的目标选择、定向攻击、移动、补药、可选人工路线。
- 默认只观察；`--execute` 后仍需 F8 启动，F8 暂停、F9 退出。
- 失焦、窗口尺寸改变、角色/血蓝识别丢失、移动无进展、补药无效时暂停。
- Jev 原生 HTTP 适配、严格概率验证、异步单请求、置信度和过期结果检查。
- 单元测试及 Windows/Linux CI；不包含真实游戏自动化测试。

## Windows 开始使用

安装 Git 和 **Python 3.12 64 位**，登录能访问该私有仓库的 GitHub 账号：

```powershell
git clone https://github.com/zoroperona/mxd-jev.git
cd mxd-jev
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup-windows.ps1
```

该命令的执行策略只作用于本次 PowerShell 进程，不修改系统设置。安装后按 [Windows 操作说明](docs/WINDOWS.md) 配置键位、截图、校准和观察，再进行短时实机测试。

## Jev 接入状态

- tapsvc 模型名：`typesafe/jev-1.13`（用户提供，尚未成功认证验证）。
- 候选请求地址：`https://llm-proxy.tapsvc.com/typesafe/v1/systemone`。
- 无凭据探测该路径的 `/models` 返回 404；当前会话环境凭据访问 `/v1/models` 返回 401。
- 因此候选路径只作为配置起点，不表示 tapsvc 已支持它。
- 工程仅读取 `MXD_JEV_API_KEY`，不读取或修改 Codex 的配置、认证文件或 `OPENAI_API_KEY`。
- 如果 tapsvc 仅开放 Chat Completions，需要确认它如何映射 `state/questions` 和原生概率；本工程不会把普通模型生成的 JSON 概率当成原生 Jev 概率。

详见 [架构与接口](docs/ARCHITECTURE.md)。

## 开发与验证

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest -q
.venv/bin/mxd-jev --help
```

`local/`、`outputs/`、环境文件和视频均被 Git 忽略。个人密钥、游戏截图、校准数据和运行日志不随代码上传。

尚未验证的项目及录像实验见 [验收状态](docs/VALIDATION.md)。
