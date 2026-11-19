# PaperLedger — paper-orchestrator

**English (60-second summary).** PaperLedger is an open-source, checkpointed
seven-stage pipeline for writing research papers with Claude Code, Codex, or
Antigravity. It ports the core ideas of Google's PaperOrchestra — an outline
JSON, literature stitching, figure specs, and LaTeX template assembly — into
host-agent skills, then adds two things a generic writing skill lacks: a
**claims ledger** (`claims.jsonl`) so every sentence is traceable, with no
invented citations or numbers, and a **voice pack** calibrated on award-winning
papers to remove defensive writing and AI tone. Every stage stops for a human
sign-off. The pipeline guarantees traceability; it does not make scientific
judgments for you.

**一句话定位.** 七阶段 checkpoint 科研论文流水线 skill：把 Google
PaperOrchestra 的核心思想（大纲 JSON / 文献缝合 / 图表 / 模板装配）搬进
Claude Code / Codex / Antigravity 宿主，用 claims 台账彻底杜绝乱编乱引，
用顶刊语料训练的 voice pack 消除防御性写作与 AI 腔。

---

## 为什么需要它：AI 写论文的三大病

### 1. 乱引用、乱编数字

模型会把「读过题录」说成「读过方法」，把二手摘要里的数字搬进方法段。

- 错（方法段）：`Prior work reports 93.4% accuracy, and our tool improves on that result.`
  —— 93.4 不在任何可核验的原文区间里，L3 题录也不支持方法细节。
- 对（related work，L3 只做指称）：`Vartak et al. (2016) addressed machine-learning model management.`
  —— 数字只能出现在其 `origin` 区间内；L3 的边界是「题录指称」，数字禁入
  方法段。

### 2. 不说人话、AI 腔

- 错：`本文提出一种新颖的框架，旨在深入探究该问题的内在机理。`
- 对：`We remove the per-token gate; training is 1.8× faster at equal accuracy.`
  —— 具体动作、具体数字、可核验。

### 3. 防御性写作

- 错：`该方案的可行性依旧存疑，仍有待进一步研究。`
- 对：`在 X 上取得 12.4% 提升；下一步在 Y 数据集上验证泛化性。`
  —— 把限制说具体，把已测到的说直，把下一步说明白。

---

## 核心机制

- **一本账：`claims.jsonl`。** 每条主张带 `claim / origin / evidence_level /
  boundary` 四字段，`evidence_level` 沿用 L0–L4 刻度：L1 支持任何主张；
  L2 只支持方向与 headline findings；L3 只支持题录指称；L0 是无数字的领域
  常识；L4（模型记忆）永不入账。正文每个阿拉伯数字都必须能在被引 claim 的
  origin 原文区间中逐字找到，或由声明过的白名单换算得出。
- **四个确定性脚本。** 机械工作不交给模型即兴发挥：

  | 脚本 | 作用 |
  |---|---|
  | `scripts/lit_search.py` | 文献检索（Semantic Scholar / arXiv / Crossref，含降级与限速披露） |
  | `scripts/plot_from_logs.py` | 从 CSV/JSONL 日志确定性绘出矢量图（无 LLM、无 `exec`） |
  | `scripts/latex_compose.py` | 模板装配、分节 `\input` 接线、`[n] → \cite{key}` 桥、完整性检查 |
  | `scripts/ledger_audit.py` | 台账审计：L3 越界、数字不在区间、强度错配，report-only |

- **七阶段检查点。** `材料入账 → 大纲 JSON → 文献缝合 → 分节成稿 → 图表
  → LaTeX 装配 → 自评审`。每阶段产出后停下等用户签字；支持「从阶段 N
  开始」并校验前序产物。签字 = 你在会话里回复确认/继续；各阶段检查点问题见
  `references/stage-playbook.md`。
- **一个声音（XOR）。** 润色只走 `paper-polish` **或** `academic-humanizer`
  之一，禁止两者叠加；阶段 7 的评审结论归 `pre-submission-reviewer`。
- **声音包插槽。** `references/voice-calibration.md` 是可替换的 voice pack。
  出厂版在 2023–2025 年 CS 顶会最佳论文语料上校准；其他学科按
  [`docs/voice-pack-training.md`](docs/voice-pack-training.md) 自训替换，
  流水线其他规则一律不动。
- **优雅降级。** 宿主没装某个兄弟 skill 时，该阶段由宿主模型直接承担；
  检查点、台账与审计规则不变，流水线不会因缺 skill 死锁。

---

## 快速开始

1. **安装 skill。** 把 `skills/` 下的文件夹整体拷进宿主的 skills 目录：

   | 宿主 | 默认 skills 目录 |
   |---|---|
   | Claude Code | `~/.claude/skills/` |
   | Codex | `~/.codex/skills/` |
   | Antigravity | `~/.gemini/config/skills/` |

   > 路径以本仓 `tools/manifest.example.json` 的示例为准；不同宿主版本可能
   > 不同，按其文档调整。Windows 下 `~` 为 `%USERPROFILE%`。

2. **触发。** 在宿主会话里说：

   - 全流程：`用 paper-orchestrator，材料在 <目录>，目标是 <会议>`
   - 单阶段：`从 paper-orchestrator 阶段4开始，outline.json 在 <路径>`
   - 任何检查点说「停」，产物与台账留在输出目录，可续跑。

3. **多宿主同步（可选）。** 用 `tools/sync-skills.ps1` 把 manifest 列出的
   skill 按字节镜像到多个根。先 dry-run 看计划，再去掉 `-DryRun`：

   ```powershell
   pwsh -NoProfile -File tools/sync-skills.ps1 `
     -ManifestPath tools/manifest.example.json -DryRun
   pwsh -NoProfile -File tools/sync-skills.ps1 `
     -ManifestPath tools/manifest.example.json
   ```

   `optional_targets`（如 `~/.agents/skills`）只有显式加 `-IncludeAgentsRoot`
   才会同步；脚本绝不创建缺失的根，也不碰 manifest 之外的任何目录。

---

## 目录结构

```
PaperLedger/
├── skills/
│   ├── paper-orchestrator/       # 本流水线（Apache-2.0；20 files）
│   │   ├── SKILL.md
│   │   ├── assets/               # claims 台账 / outline 模板
│   │   ├── references/           # 阶段手册、声音规则、voice pack、上游出处
│   │   ├── scripts/              # 四个确定性脚本
│   │   └── templates/cvpr2025/   # CVPR 作者套件（原条款）
│   └── <9 个兄弟 skill>/          # 原样保留，各自许可证
├── tools/
│   ├── sync-skills.ps1           # 多宿主字节镜像（含 -SelfTest）
│   └── manifest.example.json     # 示例 manifest（10 个 skill、占位路径）
├── tests/                        # 118 项 pytest + fixtures
├── docs/voice-pack-training.md   # 声音包自训配方（中文）
├── LICENSE                       # Apache-2.0
├── NOTICE                        # Apache §4 上游归属
├── THIRD_PARTY_NOTICES.md        # 第三方逐项清单
└── README.md
```

| 区域 | 文件数 |
|---|---|
| `skills/paper-orchestrator/` | 20 |
| 9 个兄弟 skill | 58 |
| `tools/` | 2 |
| `tests/` | 17 |
| `docs/` | 1 |

---

## 测试与验证

- **118 项 pytest 全绿。** 覆盖四个脚本的 CLI/边界、SKILL.md 内容契约、
  声音包对抗测试、同步脚本 `-SelfTest` 等。在公开树中运行：

  运行前先装依赖（Python ≥3.11）：

  ```bash
  pip install requests matplotlib pytest pyyaml
  ```

  LaTeX 工具链可选：未装 TeX 时阶段 6 走 source-only 检查回退。

  ```bash
  python -I -m pytest tests/ -q -p no:cacheprovider
  ```

  说明：公开树不附带 `vendor/` 上游 clone，CVPR 作者套件的字节一致性改由
  `tests/fixtures/cvpr2025_sha256.json` 中记录的 SHA-256 固定；其余测试与
  build 仓一致。

- **端到端 dry-run 含 L3 陷阱用例。** 演练稿在方法段故意植入
  `Prior work reports 93.4% accuracy...`（L3 题录 + 数字不在 origin 区间）。
  审计首跑同时抓出 **L3-in-methods + number-not-in-span** 双违规并 exit 1；
  修正后复跑 `0 violation(s)`，polish 后再跑仍为 0。台账只增补、不丢行。
- **加载冒烟。** Claude Code PASS；Antigravity (agy) PASS；Codex 桌面 app
  尚待用户人工确认——未获确认前不声称三端全绿。

---

## 许可证

- **本仓自己的代码与文档：Apache-2.0**（`LICENSE`）。搬入/改写的
  google-research/paper-orchestra 代码按 Apache §4 在 `NOTICE` 中署名
  （repo URL + commit + 文件清单）；上游无 NOTICE 文件。
- **9 个第三方 skill 原样保留各自许可证**：4 个 CC-BY-NC-SA-4.0
  （含**非商用**条款）、4 个 CC-BY-4.0、1 个 MIT。逐项见
  `THIRD_PARTY_NOTICES.md`。它们不因与本仓 Apache-2.0 代码同树而改变。
- **CVPR 作者套件**（`templates/cvpr2025/`）按会议/作者套件原条款保留；
  `ieeenat_fullname.bst` 为 LPPL（© 1993–2007 Patrick W. Daly）。见
  `THIRD_PARTY_NOTICES.md`。

---

## 致谢

- [google-research/paper-orchestra](https://github.com/google-research/paper-orchestra)
  （Apache-2.0）：大纲 schema、文献检索、模板装配与提示词存档的上游出处。
- 9 个兄弟 skill 的作者：paper-writer、intro-drafter、tech-paper-template、
  benchmark-paper-template、deep-research、figure-designer、
  pre-submission-reviewer、paper-polish、academic-humanizer
  —— 作者与来源链接**待补充**（其 SKILL.md 未声明 homepage/source）。
- CVPR 作者套件（[cvpr-org/author-kit](https://github.com/cvpr-org/author-kit)）；
  `ieeenat_fullname.bst` 作者 Patrick W. Daly。
- 声音包语料 8 篇最佳论文：
  1. *Visual Autoregressive Modeling*（NeurIPS 2024 Best Paper）
  2. *RHO-1: Not All Tokens Are What You Need*（NeurIPS 2024 runner-up）
  3. *Genie: Generative Interactive Environments*（ICML 2024 Best Paper）
  4. *Debating with More Persuasive LLMs Leads to More Truthful Answers*（ICML 2024 Best Paper）
  5. *Safety Alignment Should Be Made More Than Just a Few Tokens Deep*（ICLR 2025 Outstanding）
  6. *Learning Dynamics of LLM Finetuning*（ICLR 2025 Outstanding）
  7. *Generative Image Dynamics*（CVPR 2024 Best Paper）
  8. *Rich Human Feedback for Text-to-Image Generation*（CVPR 2024 Best Paper）

---

## 声明

本项目是独立衍生作品，与 Google 无隶属关系，也未获其背书。AI 辅助写作
应遵守目标期刊/会议的 AI 使用披露政策。流水线保证的是「每个主张可溯源」，
不替作者做科学判断：选题、实验设计、结论取舍与投稿责任仍在作者。