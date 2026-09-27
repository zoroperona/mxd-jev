# 架构与接口

```text
Windows 客户区截图 → OpenCV 模板 / 血条 / 小地图 → Observation
                                                ↓
                                 本地约束、血蓝阈值、候选动作
                                                ↓
                              rules 或异步 Jev Choice 决策
                                                ↓
                                新鲜度 / 焦点 / 启用状态检查
                                                ↓
                             有时限的 SendInput → 松键 → 再观察
```

## 模块

| 文件 | 职责 |
| --- | --- |
| `config.py` | 默认值、参数验证、项目本地配置 |
| `vision.py` | 模板匹配、去重、血蓝条比例、小地图黄点 |
| `policy.py` | 本地动作候选、血蓝优先级、路线、无进展检测 |
| `jev.py` | 原生 API、严格响应检查、单个异步请求 |
| `windows.py` | Windows API、客户区捕获、扫描码、焦点和热键 |
| `runtime.py` | 录像与实时运行、执行闸门、日志 |
| `calibrate.py` | 选区、模板与配置保存 |
| `cli.py` | 命令入口 |

## Jev 契约

参考 [TypeSafe API](https://docs.typesafe.ai/api) 与 [LiteLLM 透传说明](https://docs.litellm.ai/docs/pass_through/typesafe)。配置的 `endpoint` 是完整 URL，不自动追加 `/v1`。

```json
{
  "model": "typesafe/jev-1.13",
  "state": {"left_targets_in_reach": 0, "right_targets_in_reach": 3},
  "questions": {
    "action": {
      "type": "choice",
      "instructions": "Select the next short action from allowed options.",
      "criteria": {"wait": "Hold position", "attack_right": "Attack nearby targets on the right"}
    }
  }
}
```

要求响应为 `answers.action`，保留原生选项概率和置信度。校验选项集合、数值范围、概率和及最大概率选项。网关若需要另一种请求协议，应在确认真实契约后增加适配器，不能猜测 Chat Completions 包装。

只传发送决策所需的英文状态字段，不传图片、用户名、聊天或账号数据。距离与数量在本地算好。高置信度不保证判断正确，阈值需要领域测试。

一次只有一个请求在途；每个返回最多消费一次，按观测时间计算年龄。超过时限、候选动作变化或左右攻击目标分布变化即丢弃。响应没有通过门槛时等待；HTTP 错误暂停。仍需承认单目模板识别可能把不同怪物判为相似状态。

## 限制和后续

模板匹配不是通用目标检测器，对动画、遮挡、字形、分辨率敏感。当前只用高度差近似同层，未构建地图几何。自动 Buff、瞬移策略、自动脱困、换频道、复活返回、买药、背包整理和自动平台规划不在当前实现中。卡住后选择暂停，交给玩家接管。

改进顺序：Windows 输入实测 → 校准数据与多姿态模板 → 血蓝/角色检测稳定性 → 可解释的地图路径与脱困 → Jev 和规则的对照试验。完整路线和刷怪效率必须实机验收，不能从录像推算。
