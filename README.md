# 知径 Zhijing · 人机共学

> **以知为径，与 AI 同行。**
> *Zhijing — a terminal-native AI learning companion. It maps what you already know into a weighted knowledge graph, plans the minimum-cost path to your learning goal, teaches with sourced explanations and spaced reviews, and graduates you with a full knowledge graph, scorecard and timeline. Built on [Pi agent](https://github.com/badlogic/pi-mono) + DeepSeek V4 Pro.*

[完整操作手册](使用手册.md) · [设计文档](docs/) · [协议](AGENTS.md) · [MIT License](LICENSE)

## 它是什么

知径是一个住在终端里的 AI 学习伙伴，围绕三个核心思想构建：

1. **AI 是头脑的唯一接口**——熟悉、可信、多视角防偏，同时用五级事实分级 + 来源标注防幻觉；
2. **知识之间有权重，学习有最优路径**——把你"已经会的"和目标放进一张加权知识图谱（知识点=节点、关联度=边、掌握度=状态），用 Dijkstra 求出**权重最小**的学习路径（不是跳数最短）；
3. **四阶段闭环 + 反馈校准**——探寻 → 计划 → 演示 → 教学，练习成绩与学习感受持续校准系统，防自欺、防路径依赖。

日常你只需要说四句话：

| 你说 | 它做 |
|---|---|
| "我想学习 X" | 建学习线、开始探寻你的背景知识 |
| "继续学习 X" | 自动找到进行中的目标，接着上课 |
| "学到哪了 / 我要复习 X" | 进度总览 / 三轮科学复习（回忆→变式→连接）+ 成绩单 |
| "我学完了" | 毕业：完整知识图谱 + 成绩单 + 学习报告 + 时间线图，自动归档 |

## ✨ 特性

- **加权知识图谱**：掌握度 m、关联度 r、步进代价 `c=(1+λ(1−m))/r`；练习巩固 → 权重逐步减小
- **最小权重路径规划**：多源 Dijkstra + 贪心前沿扩张（每步新点直接挂在已知区上）
- **门禁与防自欺**：m ≥ 0.8 才进入下一课；信心 vs 实际校准；不提示的生成式回忆
- **复习评估体系**：每次复习出成绩单（分数 = m×50 + 复习×15 + 表现×20 + 校准×15）+ 多标签（难度/掌握/熟练/稳定/关键前提/卡点/兴趣）
- **像 git 一样的学习日志**：每课 `commit` 一笔，`log` 回望，毕业时生成时间线图
- **读书捕获**：看不懂 → 用已知作锚解答、缺口补进路径；有感悟 → 提炼成你的专属连接（高关联边）
- **默认自动出图**：diagram-design 自主选型（架构图/流程图/概念图/仪表盘），数据永远取自工具输出（图不幻觉）
- **确定性内核**：`tools/graph_ops.py`（23 个子命令）承担全部计算，LLM 只讲解、不口算
- **隐私本地化**：所有学习数据留在你自己的工作区，仓库不含任何个人数据

## 快速开始

**方式 A · 开箱即用（推荐先试）**：

```powershell
python zhijing.py            # 进入交互：说"我想学习 X"开始（无需任何配置）
python zhijing.py --check    # 环境自检
```

设置环境变量 `DEEPSEEK_API_KEY` 后，讲解/提问/解答自动交给 DeepSeek（可选）。

**方式 B · Pi agent 完整方案**：

1. 安装 [Pi agent](https://github.com/badlogic/pi-mono)，接入 DeepSeek（[官方指引](https://api-docs.deepseek.com/quick_start/agent_integrations/pi_mono/)：`DEEPSEEK_API_KEY` + `deepseek-chat`/`deepseek-reasoner`）；
2. 克隆本仓库到你的学习工作区，把 `AGENTS.md` 放到工作区根目录；
3. 打开 pi，说：**"我想学习 <主题>"** —— 它会自动建目录、开始探寻；
4. 之后每次会话只说 **"继续学习"**。

```powershell
python tools\graph_ops.py init-goal <目录名> --goal <目标>   # 或直接对 pi 说"我想学习 X"
python tests\smoke_test.py                                    # 自检（33 项断言）
```

## 架构

```mermaid
flowchart LR
  U[我] <-->|唯一接口| A[终端教学 Agent]
  subgraph 核心引擎
    KG[(加权知识图谱<br/>知识点 + 关联度 + 掌握度)]
    PA[路径规划器<br/>最小权重路径 Dijkstra]
    SR[练习调度器<br/>间隔重复 SM-2]
    FC[反馈校准器<br/>成绩+感受 → 校准参数]
  end
  subgraph 四阶段闭环
    E[一 探寻] --> P[二 计划] --> D[三 演示] --> T[四 教学]
    T -.反馈校准/动态重规划.-> P
  end
  A --> KG
  MAT[(我的笔记 + 收集材料)] -.导入 · 来源锚定.-> KG
  KG --> PA --> D
  T --> SR --> KG
  T --> FC --> KG
  FC -.重规划.-> PA
  KG -.学习完成.-> FKG[终局知识图谱 + 成绩单 + 时间线]
end
```

- **Pi agent = 手**（终端、文件、命令、权限与审计）；**DeepSeek V4 Pro = 脑**（讲解、规划）
- **`AGENTS.md` + `skills/` = 操作手册**；**`graph.json` = 记忆**（记忆在文件里，不在对话里）
- **`tools/graph_ops.py` = 确定性内核**：路径/m/间隔/校准/评价/导出/提交，全部由代码计算

## 目录结构

```
├─ AGENTS.md            ← 协议（放到你的学习工作区根目录，pi 自动加载）
├─ 使用手册.md           ← 完整操作手册（从安装到毕业）
├─ 背景知识.模板.md      ← 个人背景档案模板（复制为 背景知识.md 使用，勿上传个人版）
├─ docs\                ← 完整设计文档 01–12（理念/图谱模型/路径算法/四阶段/防幻觉/复习/校准/路线图…）
├─ skills\zhijing\      ← 教学技能卡 + 探寻问卷（pi skill）
├─ tools\graph_ops.py   ← 确定性计算内核（23 个子命令）
├─ templates\           ← 新目标图谱模板
├─ prototype\           ← 路径算法演示（demo_path.py）
├─ tests\               ← 回归测试（33 项断言）
└─ pi\                  ← 首次会话开场白（粘贴给 pi）
```

## 文档导航

 · [01 核心理念与信任设计](docs/01-核心理念与信任设计.md) 

· [02 知识图谱模型](docs/02-知识图谱模型.md) 

· [03 最优学习路径算法](docs/03-最优学习路径算法.md) 

· [04 四阶段交互流程](docs/04-四阶段交互流程.md) 

· [05 幻觉规避与可靠性](docs/05-幻觉规避与可靠性.md) 

· [06 练习巩固与防自欺](docs/06-练习巩固与防自欺.md) 

· [07 实施路线图](docs/07-实施路线图.md) 

· [08 反馈收集与持续校准](docs/08-反馈收集与持续校准.md) 

· [09 终端 Agent 形态与材料接入](docs/09-终端形态与材料接入.md) 

· [10 学习完成与知识图谱生成](docs/10-学习完成·知识图谱生成.md) 

· [11 上手使用指南](docs/11-上手使用指南.md) · [12 调参手册与常见问题](docs/12-调参手册与常见问题.md)

## 开发状态

核心功能已实现并通过回归测试（`tests/smoke_test.py`，33/33）：四阶段教学、门禁、复习评估、成绩单、时间线、git 式提交、读书札记、材料导入、图谱导出。设计源自真实学习场景的长期迭代。

## License

[MIT](LICENSE) © 2026 知径项目贡献者
