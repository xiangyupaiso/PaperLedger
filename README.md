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
  L2 只支持方向与 headline findings；L3 只支持题录指称（经白名单限定于 Related Work）；
  L0 是无数字且不含专名的领域常识；L4（模型记忆）永不入账。正文与表格中每个
  受审数字（含数据性内联数学如 `$93.4\%$`、`$1.8\times$` 与单位后缀数字）都必须能在被引 claim
  的 `origin` 原文区间中逐字找到，或由声明过的白名单换算（支持链式换算）得出。
- **四个确定性脚本。** 机械工作不交给模型即兴发挥：

  | 脚本 | 作用 |
  |---|---|
  | `scripts/lit_search.py` | S2 / Crossref / arXiv 检索（`--queries-from outline.json`、`--source auto\|s2\|crossref\|arxiv`、`--append --existing-bib` 锁键不漂移、`--emit-ledger-draft`、`--emit-numeric-map`、`--rank`，L3 默认剥离 AI `tldr`） |
  | `scripts/plot_from_logs.py` | 从 CSV/JSONL 确定性绘出矢量图与 `booktabs` 表格（`--mode table` 纯标准库无需 `matplotlib`；支持双通道编码、误差棒、`table*`、`bold_best`、自定义表头） |
  | `scripts/latex_compose.py` | 模板装配、`sections/*.tex` 与 `--tables` 接线、`--outline` 元数据注入（标题/作者/paperID）、`\bibliography` 自动同步并清理残留 `.bib`、过滤伴随 `.png` 预览、`[n] → \cite{key}` 桥、`.log`/`.blg` 编译诊断校验 |
  | `scripts/ledger_audit.py` | 台账门禁与审计（L3 白名单限制在 Related Work、表格块级 `% @claim:` 绑定与 `--tables`、数据性内联数学审计、单位后缀数字与链式白名单换算、`--outline` 与 `--bib` 校验、`--strength-report` + `--dispositions` 处置指纹持久化） |

- **七阶段检查点。** `材料入账 → 大纲 JSON → 文献缝合 → 分节成稿 → 图表
  → LaTeX 装配 → 自评审`。每阶段产出后停下等用户签字；支持「从阶段 N
  开始」并校验前序产物。签字 = 你在会话里回复确认/继续；各阶段检查点问题见
  `references/stage-playbook.md`。
- **单一事实源与阶段 7 顺序。** 阶段 4–7 全程只修改 `sections/*.tex`、`tables/*.tex`、
  `outline.json`、`claims.jsonl`，`compiled/` 仅由 `latex_compose.py` 重建；
  阶段 7 严格锁定 `7.1 → 7.5`（任何编辑后必重跑 `ledger_audit` 与 `latex_compose`），
  Abstract 在阶段 5 后最终定稿。
- **一个声音（XOR）。** 润色只走 `paper-polish` **或** `academic-humanizer`
  之一，禁止两者叠加；阶段 7 的评审结论归 `pre-submission-reviewer`。
- **声音包与提示词分离。** `references/voice-calibration.md` 是可替换的 voice pack，
  出厂版在 2023–2025 年 CS 顶会最佳论文语料上校准；其他学科按
  [`docs/voice-pack-training.md`](docs/voice-pack-training.md) 自训替换。
  `references/reflection-prompts.md` 仅为精简的运行时自评 Rubric；上游
  PaperOrchestra 原始提示词归档位于 [`docs/upstream-prompts-archive.md`](docs/upstream-prompts-archive.md)。
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

3. **多宿主同步（可选）。** 推荐从仓库根目录使用跨平台纯标准库脚本
   `tools/sync_skills.py`（支持 macOS / Linux / Windows）；示例 manifest
   `tools/manifest.example.json` 默认以 `"source": "./skills"` 同步至
   `~/.claude/skills`、`~/.codex/skills`、`~/.gemini/config/skills`：

   ```bash
   python tools/sync_skills.py --manifest tools/manifest.example.json --dry-run
   python tools/sync_skills.py --manifest tools/manifest.example.json
   python tools/sync_skills.py --self-test
   ```

   Windows 环境亦可在仓库根目录使用 `tools/sync-skills.ps1`：

   ```powershell
   pwsh -NoProfile -File tools/sync-skills.ps1 `
     -ManifestPath tools/manifest.example.json -DryRun
   pwsh -NoProfile -File tools/sync-skills.ps1 `
     -ManifestPath tools/manifest.example.json
   ```

   `optional_targets`（如 `~/.agents/skills`）只有显式加
   `--include-agents-root`（或 PowerShell `-IncludeAgentsRoot`）才会同步；
   两个脚本均绝不自动创建缺失的目标根目录，也不碰 manifest 之外的任何目录。

---

## 目录结构

```
PaperLedger/
├── pyproject.toml                        # 依赖声明与 pytest 配置
├── skills/
│   ├── paper-orchestrator/               # 本流水线（Apache-2.0；20 files）
│   │   ├── SKILL.md
│   │   ├── assets/                       # claims 台账 / outline 模板
│   │   ├── references/                   # 阶段手册、声音规则、voice pack、自评 Rubric、上游出处
│   │   ├── scripts/                      # 四个确定性脚本
│   │   └── templates/cvpr2025/           # CVPR 作者套件（原条款）
│   └── <9 个兄弟 skill>/                  # 原样保留，各自许可证
├── tools/
│   ├── sync_skills.py                    # 跨平台纯标准库多宿主镜像（含 --self-test）
│   ├── sync-skills.ps1                   # Windows PowerShell 镜像脚本（含 -SelfTest）
│   └── manifest.example.json             # 示例 manifest（./skills -> 3 个默认宿主目录）
├── tests/                                # pytest 套件、端到端集成测试与 fixtures
├── docs/
│   ├── voice-pack-training.md            # 声音包自训配方（中文）
│   └── upstream-prompts-archive.md       # 上游 PaperOrchestra 原始提示词归档
├── LICENSE                               # Apache-2.0
├── NOTICE                                # Apache §4 上游归属
├── THIRD_PARTY_NOTICES.md                # 第三方逐项清单与公开发布前合规提示
└── README.md
```

| 区域 | 文件数 |
|---|---|
| `skills/paper-orchestrator/` | 20 |
| 9 个兄弟 skill | 58 |
| `tools/` | 3 |
| `tests/` | 20 |
| `docs/` | 2 |

---

## 测试与验证

- **依赖配置（`pyproject.toml`）。** 需 Python ≥ 3.11。完整安装测试依赖：

  ```bash
  pip install -e ".[dev]"
  ```

  若仅运行核心纯标准库与表格模式工具链（不渲染矢量图表），最小测试依赖为：

  ```bash
  pip install requests pyyaml pytest
  ```

  LaTeX 工具链可选：未装 TeX 时阶段 6 走 source-only 检查回退。

- **已验证测试范围（当前仓库实测）。**
  - 核心确定性套件（无需 `matplotlib`、TeX、实时网络或 Windows junction 权限）：
    ```bash
    python -m pytest tests/ --ignore=tests/test_plot_from_logs.py --ignore=tests/test_smoke.py --ignore=tests/test_sync_script.py -q -p no:cacheprovider
    ```
    结果：**147 passed**（覆盖台账门禁、L3 白名单、表格块与内联数据数学审计、链式换算、纲要与引文校验、`lit_search` 多源检索与不漂移锁键、`latex_compose` 元数据注入与编译日志检查、`plot_from_logs` 表格生成、多 skill 冲突与阶段 7 顺序契约、`sync_skills.py` 单测、阶段 1→7 端到端集成与对抗样本机检）。
  - 跨平台与 PowerShell 同步校验：
    ```bash
    python -m pytest tests/test_sync_script.py -k "not selftest" -q -p no:cacheprovider
    python tools/sync_skills.py --self-test
    ```
    结果：`test_sync_script.py -k "not selftest"` **2 passed, 1 deselected**；`sync_skills.py --self-test` 退出 0。
  - 完整全套执行（`python -m pytest tests/ -q -p no:cacheprovider`）额外依赖 `matplotlib`（`test_plot_from_logs.py`、`test_smoke.py`）与具备创建 NTFS junction 权限的 Windows PowerShell 环境（`test_sync_script.py::test_selftest`）。
  - 说明：公开树不附带 `vendor/` 上游 clone，CVPR 作者套件字节一致性由 `tests/fixtures/cvpr2025_sha256.json` 固定。

- **端到端 Stage 1→7 与声音包评测边界。**
  - [`tests/test_e2e_pipeline.py`](tests/test_e2e_pipeline.py) 覆盖阶段 1→7 自动化演练，在 `03_approach.tex` 故意植入未入账 `$99.9\%$` 与越界 L3 `\cite` 验证双违规必返回 exit 1，随后完成 `tab_main.tex`、`--strength-report`、`--dispositions`、阶段 7 润色与幂等重新装配。
  - [`tests/test_voice_calibration_adversarial.py`](tests/test_voice_calibration_adversarial.py) 在 `pytest` 中仅对**历史宿主模型评测记录快照**运行确定性 `ledger_audit` 断言、文档规则一致性与 B 组改写非捏造数字检查（不调用实时大模型）；任何对 `voice-calibration.md` 的修改都必须按 [`docs/voice-pack-training.md`](docs/voice-pack-training.md) 第 6 步重开干净上下文完成实时 LLM A/B/C 复测。
- **加载冒烟。** Claude Code PASS；Antigravity (agy) PASS；Codex 桌面 app
  尚待用户人工确认——未获确认前不声称三端全绿。

---

## 许可证

- **本仓自己的代码与文档：Apache-2.0**（`LICENSE`）。搬入/改写的
  google-research/paper-orchestra 代码按 Apache §4 在 `NOTICE` 中署名
  （repo URL + commit + 文件清单）；上游无 NOTICE 文件。
- **9 个第三方 skill 原样保留各自许可证**：4 个 CC-BY-NC-SA-4.0
  （含**非商用**条款）、4 个 CC-BY-4.0、1 个 MIT。逐项见
  [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。它们不因与本仓 Apache-2.0 代码同树而改变。
  **公开发布前合规阻断项**：这 9 个目录目前缺少经核验的上游作者署名与来源链接，且 `skills/academic-humanizer/` 缺少 MIT 许可证正文与版权行；公开发布前须按 `THIRD_PARTY_NOTICES.md` 第 1 节补齐真实溯源，或移除该 9 个第三方目录（由硬规则 10 优雅降级）。
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