# Windows 操作说明

## 1. 安装与配置键位

运行 README 中的安装命令后，编辑 `local/config.json`：

- `window_title`：游戏窗口标题的唯一子串。匹配到零个或多个窗口会拒绝启动。
- `keys`：填写你自己的左右、上下、攻击、跳跃、瞬移、红药、蓝药键。
- 键名支持字母、数字、方向键、`ctrl`、`alt`、`shift`、`space`、`delete`、`insert`、`home`、`end`、`pageup`、`pagedown`、`tab`、F1–F12；F8/F9 保留，不能绑定技能。
- 第一版只支持单键绑定，各动作键不能重复。`teleport` 预留，当前自动策略未启用瞬移。
- `hp_threshold` / `mp_threshold` 是血蓝比例阈值；默认分别为 0.45 / 0.25。
- `max_session_minutes` 默认每次启用最多 10 分钟。

默认键位只是示例，务必核对。不要把 API 密钥写入 JSON。

```powershell
.venv\Scripts\mxd-jev.exe check
```

## 2. 截图与校准

让角色站在能看清名牌、怪物和血蓝条的位置。使用窗口模式，保证窗口不被其他窗口遮挡。

```powershell
.venv\Scripts\mxd-jev.exe capture --delay 5
```

运行后 5 秒内切回游戏，得到 `local/capture.png`。截图不会按游戏按键。

```powershell
.venv\Scripts\mxd-jev.exe calibrate local/capture.png
```

依次拖框，回车确认：

1. 自己的**唯一角色名牌**，不要选宠物名字、翅膀或技能效果。
2. 角色身体中心附近的小框，用于确定名牌相对人物的位置。
3. 一只无遮挡怪物的身体，尽量少带背景。
4. 血条**完整内部宽度**，包含未填充部分；框在数字下方，排除文字和边框。
5. 蓝条，要求同上。
6. 小地图内部，可按 Esc 跳过；路线模式必须配置。
7. 游戏区域，排除 HUD 和小地图，但覆盖所有可能出现角色名牌的位置。

选区使用统一的参考分辨率；窗口客户区会缩放到 `reference_size` 后识别。缩放比例改变可能影响文字和模板匹配，不能保证自动适配。窗口比例或 UI 布局变化时应重新校准。

如果某些姿态漏检，可从另一张客户区截图追加样本，不必重做所有校准。怪物可尝试选择辨识度高的头部，减少身体动画和背景影响；角色样本仍选唯一名牌：

```powershell
.venv\Scripts\mxd-jev.exe add-template monster local/capture-2.png
.venv\Scripts\mxd-jev.exe add-template player local/capture-2.png
```

也可以从录像选帧：`add-template monster video.mp4 --seconds 25 --video-crop`，使用该配置保存的录像客户区裁剪。不要降低阈值来掩盖误识别；先检查标记结果。

## 3. 先观察，再启用按键

```powershell
.venv\Scripts\mxd-jev.exe run
```

这条命令**不发送游戏按键**。切回游戏查看日志或预览，确认绿圈跟随自己、黄框对应怪物、血蓝比例正常。预览获得焦点时会暂停采集；可以放在第二屏查看。

确认后退出观察模式，运行：

```powershell
.venv\Scripts\mxd-jev.exe run --execute --mode rules
```

- 切回游戏，按 **F8** 启动；再次 F8 暂停。
- **F9** 结束整个程序；终端 Ctrl+C 也会清理按键。
- 首次只测试 30–60 秒，先确认方向、攻击、补药均对应正确技能。
- 手工按住已配置的操作键时，不再注入新动作并暂停。
- 失焦、窗口尺寸改变、识别异常都会要求重新 F8 启用。
- 如果按键无效，记录情况；程序不会尝试驱动注入或绕过游戏输入保护。游戏与终端的权限级别也可能影响 `SendInput`。

正常退出、异常抛出和失焦都执行松键；操作系统强制终止进程等情况无法保证运行清理逻辑。每次按键脉冲最多 150ms。

## 4. Jev 配置

先拿到有 tapsvc 权限的 Key。在**当前 PowerShell** 设置独立环境变量，可用以下方式避免将密钥明文写进命令历史：

```powershell
$jevSecret = Read-Host "tapsvc API key" -AsSecureString
$jevCredential = [System.Net.NetworkCredential]::new("", $jevSecret)
$env:MXD_JEV_API_KEY = $jevCredential.Password
Remove-Variable jevSecret, jevCredential
.venv\Scripts\mxd-jev.exe probe
```

这只改变当前终端及其子进程，不写全局配置。关闭终端即失效，也可执行：

```powershell
Remove-Item Env:MXD_JEV_API_KEY
```

`probe` 发起一次小型原生决策请求，并检查 `choice`、`probabilities`、`confidence`；不会上传游戏截图。401/403 表示权限问题，404 需要确认网关路径，其他错误按网关实际返回定位。**模型名存在不等于原生接口已开放。**

只有探测成功后才运行：

```powershell
.venv\Scripts\mxd-jev.exe run --execute --mode jev
```

Jev 仅在 F8 启用后调用；补药与紧急停止始终由本地规则优先处理。低置信度、场景变化和过期回答不会执行；网关错误暂停，不静默切成规则模式。日志记录实际返回的模型、用量和延迟。没有自动请求重试。

## 5. 人工路线（实验功能）

首轮保持 `route.enabled=false`，先验证同平台战斗。无怪时默认等待，不盲目移动。

路线中的每个点表示**要到达的小地图位置及到达前使用的动作**，坐标相对小地图选区归一化到 0–1。到达目标容差范围后切换到下一点，最后循环回首点。

```json
{
  "enabled": true,
  "tolerance": 0.025,
  "waypoints": [
    {"x": 0.8, "y": 0.5, "action": "move_right"},
    {"x": 0.2, "y": 0.5, "action": "move_left"}
  ]
}
```

上面仅是结构示例，不是视频地图的实测坐标。支持 `move_left`、`move_right`、`jump_left`、`jump_right`、`climb_up`、`climb_down`。先手动走通，再配置。程序不自动判断绳索是否对齐，不理解平台连通性；同高度筛选也不能完全排除隔墙、跨平台目标。识别不到唯一黄色小地图标记就暂停。

## 6. 录像与反馈

录像校准和实机校准建议用独立配置：

```powershell
.venv\Scripts\mxd-jev.exe --config local/video/config.json init
.venv\Scripts\mxd-jev.exe --config local/video/config.json calibrate "C:\videos\1790438198296.mp4" --seconds 40 --crop-client
.venv\Scripts\mxd-jev.exe --config local/video/config.json replay "C:\videos\1790438198296.mp4" --output outputs/replay
```

`--crop-client` 会先要求选取录像里的游戏客户区，后续回放使用同一裁剪。实机截图已是客户区，不需要这个选项。

回放生成标记视频、`events.jsonl`、`summary.json`。优先输出 `annotated.mp4`，系统编码器不可用时尝试 `annotated.avi`，实际文件名记在汇总中。回放动作都是建议，不能证明角色执行后会成功。汇总中的有效帧比例是识别覆盖率，不是准确率。

首次 Windows 测试请反馈：截图是否正常、名牌和血蓝是否稳定识别、F8/F9 是否有效、短按是否生效、暂停原因，以及对应 `outputs/live-*.jsonl`。日志不含密钥；不要把本地配置或环境文件提交到仓库。
