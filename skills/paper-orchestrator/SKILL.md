---
name: paper-orchestrator
description: >-
  端到端科研论文流水线：把现有科研写作 skills 编排成七个带检查点签字的阶段
  （材料入账 → 大纲 JSON → 文献缝合 → 分节成稿 → 图表 → LaTeX 装配 → 自评审），
  配四个确定性脚本（文献检索、日志绘图、LaTeX 装配、台账审计），一个声音、
  一本账。Use when the user says 流水线 / paper-orchestrator /
  从阶段 N 开始, or names a stage: 材料入账、大纲 JSON、文献缝合、分节成稿、
  图表、LaTeX 装配、自评审。不拦截任何 skill 的独立触发。
license: Apache-2.0
compatibility: claude-code codex antigravity
---

# Paper Orchestrator

## 概述

把作者的 idea、实验日志与目标会议，经七个阶段组装成可投稿的 LaTeX 包。
编排由宿主模型执行；机械工作交给 `scripts/` 下四个确定性脚本；领域工作
交给现有 skills。每阶段产出后**停下等用户签字**，才进下一阶段。

三条边界，不可越：

- 不重写、不合并现有 skill。用户直接叫 paper-writer / deep-research 等
  独立使用时，不经过流水线；流水线不拦截、不重写它们的独立触发，也不把
  本文件规则叠上去。
- 不做无人值守一键投稿稿；每个检查点有人签字。
- 流程规则归本 skill，领域规则归该阶段唯一拥有者（裁决表见下）。

## 使用方式（给用户的话）

- 全流程：`用 paper-orchestrator，材料在 <目录>，目标是 <会议>` →
  七阶段逐个签字推进。
- 单点进入：`从 paper-orchestrator 阶段4开始，outline.json 在 <路径>` →
  按"单阶段进入/退出协议"校验已有产物后接续。
- 退出：任何时候说"停"。产物与台账留在输出目录，可续。

## 硬规则

1. **台账契约（防伪）。** 每条主张在 `claims.jsonl` 带
   `claim / origin / evidence_level / boundary（允许边界）` 四字段。
   `evidence_level` 直接沿用 canonical 语义：
   `paper-writer/references/evidence-discipline.md` 的 L0–L4 强度表，
   不另造分级。L1 支持任何主张；L2 只支持方向与 headline findings，禁具体
   数值与方法步骤；L3 仅题录元数据（无 abstract 才是 L3），只支持
   "X et al. (Year) addressed Y" 级指称；L0 是无数字、无专名、无量化对比的
   领域常识；L4 模型记忆不支持任何主张，**永不入账**。`boundary` 由 level
   推导（对照表见 `references/outline-schema.md`）。`origin` 支持行区间：
   `material:<相对路径>#L10-L15`。**数值一致性**：正文每个阿拉伯数字必须
   能在被引 claim 的 origin 区间原文中逐字找到，或由区间内数值按该 claim
   声明过的白名单换算得出；否则按违规处理，**不允许加 hedge 蒙混**。
   台账外的主张按 paper-writer 阶梯处理：补检索、改弱主张、删。
2. **独立上下文核查步（阶段 3 与阶段 7 显式存在）。** 阶段 3 的逐条引用
   核查与阶段 7 的抽查复核，必须在与写作上下文隔离的回合执行：优先
   verification-ladder 的 **Rung 1**（fresh-context 核查器，只拿到正文与
   参考文献表，不拿写作推理）。宿主无子代理能力时降 **Rung 2**
   （同上下文 grounding，逐条从真实检索响应重新推导，绝不凭记忆），
   并在交付说明中**披露降级**。沿用阶梯原文语义：纪律不降级；只有核查
   机制降级；任何降级必向用户披露。阶梯全文：
   `paper-writer/references/verification-ladder.md`。
3. **每阶段一个文风拥有者。** 起草期文风归 paper-writer；收尾期二选一
   （XOR）调用 paper-polish 或 academic-humanizer，一次性完成。中间任何
   阶段不得提前套润色/去 AI 味规则。
4. **阶段 4 引用规则。** `.tex` 内直接写 `\cite{citekey}`，citekey 必在
   台账（`retrieval:<citekey>` 行）。作者粘贴 paper-writer 线稿带 `[n]`
   数字引用时，走阶段 6 compose 的 `--numeric-map`（`to_cites` 桥
   `[n] → \cite{key}`）；map 由阶段 3 台账自动生成，规则见
   `references/stage-playbook.md`。
5. **阶段 5 图表规则。** 稿内图只交 `.pdf` 矢量（PNG 仅预览，绝不
   `\includegraphics`，compose 拷贝时自动跳过伴随 `.png` 预览）；表格走
   `log_to_table` 产 booktabs 块，可粘贴进 `sections/*.tex` 或放 `tables/` 传
   `--tables` 装配。
6. **阶段 6/7 单真源与装配规则。** `sections/*.tex`、`tables/*.tex` 与
   `outline.json` 是唯一可编辑真源；`manuscript/` 是 `latex_compose.py` 生成的
   纯构建产物（禁止手工改 `manuscript/`）。阶段 6 接线按标记或无标记路径，
   剥离 `% @claim:` 注释行，通过 `--outline outline.json` 注入标题/作者/paperID
   并自动同步 `\bibliography`；编译同时校验 `.log`/`.blg` 无致命错误或未定义引用，
   检测不到 TeX（`compiled=None`）只交付源码包并在检查点说明。
7. **阶段 7 收尾润色 XOR（判定条件写死）。** 线稿有中译英残留/中式英语
   → paper-polish；纯英文去 AI 味 → academic-humanizer。**禁止两者叠加
   调用。** 润色与修订一律改写 `sections/*.tex`（保留 `% @claim:`），重跑
   `ledger_audit.py --strength-report` 把强度错配处置清零后，再重跑
   `latex_compose.py` 刷新终稿 `manuscript/` 才能检查点签字。
8. **证据强度–措辞匹配审计取代机械 hedge 词频预算。** 收尾逐主张对照：
   有 L1/L2 强证据却弱化表达 → 改肯定（不确定性真实则改台账/缩小主张）；
   证据 L3/无台账却肯定断言 → 改台账或缩小主张。**绝不为了压词频把缺证据
   的句子强行改肯定。** 词频只做报告项不做 gate；`limitations`/`suggest`/
   `indicate` 是正常学术动词，不是惩罚词。全文见
   `references/voice-rules.md`。
9. **声音包插槽（voice pack slot）。** 阶段 4 与阶段 7 的文风指导只读
   `references/voice-calibration.md`；该文件是可替换的声音包实例（出厂版
   按 2023–2025 CS 最佳论文校准）。换成别的领域自训的声音包只替换该文件，
   不改本文件其他任何规则，接口契约见该文件的插槽声明。
10. **兄弟 skill 缺失时的降级。** 各阶段点名的兄弟 skill（paper-writer、
    deep-research、figure-designer 等）是能力提供者；宿主缺少某个同名
    skill 时，由宿主模型直接承担该阶段，检查点、台账与审计规则不变——
    流水线绝不因缺 skill 死锁。

### 冲突裁决表（流程听 orchestrator，领域听子 skill）

| 冲突 | 谁赢 | 例子 |
|---|---|---|
| 流程/顺序/检查点 | orchestrator | "不许跳步"压过"某 skill 想自己润色" |
| 流程元数据标记 | orchestrator | 阶段 4 允许并强制 `% @claim:<id>` 行注释（阶段 6 自动剥离） |
| 文字风格/措辞 | 该阶段唯一拥有者 | 阶段 4 paper-writer 赢，评审建议不直接改稿 |
| 声音包刻度 vs 泛化禁词/保守不改强 | `voice-calibration.md` | L1 强证据支持直陈或改肯定，不受保守不改强或泛化禁词表误杀 |
| 事实/引用资格 | 验证阶梯（最严者赢） | autorater 夸了但台账没有 → 不成立 |
| 评审结论 | pre-submission-reviewer | orchestrator 不自行加判 |

**三条流水线局部覆盖条款**（仅在流水线会话内生效，不改变兄弟 skill 独立触发时的规则）：
1. **流程元数据覆盖**：阶段 4 的 `% @claim:<id>` 行注释是台账硬契约（阶段 6 装配自动剥离，终稿零残留），在流水线内优先于 `paper-writer` 的「无内嵌溯源标记」规则；
2. **Abstract 最终定稿**：阶段 4 先写正文主干（Methods / Experiments / Related Work / Introduction），**Abstract 留待实验结果与阶段 5 图表定型后再定稿**（与 `paper-writer` 一致，防止提前编数与返工）；
3. **声音包刻度优先**：阶段 4 起草与阶段 7 错配处置/润色时，`references/voice-calibration.md` 的证据刻度尺优先于兄弟 skill（`paper-polish` / `academic-humanizer` / `pre-submission-reviewer`）的泛化禁词表与「不把已 hedge 句改强」保守条款——有 L1 强证据支持时允许改肯定、保留语料许可的精确限定（如 `To our knowledge`），无强证据时才按阶梯降强度或缩小主张。

## 七阶段协议

每阶段四件事：做什么 / 调用谁 / 产出入账 / 停下问什么。阶段表全文、
输出目录约定与脚本 CLI 速查见 `references/stage-playbook.md`。

### 阶段 1｜材料入账

- **做什么**：清点 idea、实验日志（CSV/JSONL）、目标会议、已有参考文献；
  建输出目录与 claims 台账骨架（格式样例
  `assets/claims_ledger_template.jsonl`）。
- **调用谁**：无（自检清单：材料可读？日志列名可映射？会议模板有无？）。
- **产出入账**：`materials.md`（材料清单+路径）+ `claims.jsonl` 空账骨架。
- **停下问什么**："材料清单是否齐全？目标会议确认？进大纲阶段？"

### 阶段 2｜大纲 JSON

- **做什么**：章节计划 + 文献检索策略 + 可视化计划，写成 `outline.json`
  （模板 `assets/outline_template.json`，schema 见
  `references/outline-schema.md`；`lit_strategy` 为本套件扩展字段）。
- **调用谁**：tech-paper-template（技术论文定位）/
  benchmark-paper-template（基准论文定位）。
- **产出入账**：`outline.json`（title/venue/sections/lit_strategy/viz_plan）。
- **停下问什么**："章节结构与贡献定位认可？检索策略覆盖 must_contain？"

### 阶段 3｜文献缝合

- **做什么**：按 `lit_strategy.queries` 检索 → 排序 → **逐条独立上下文
  核查**（硬规则 2）→ BibTeX 装配 → 按大纲分配引用。
- **调用谁**：deep-research 检索纪律 + paper-writer 验证阶梯 +
  `scripts/lit_search.py`：
  `python scripts/lit_search.py (--query "<query>" | --queries-from outline.json) --limit 20 --out refs.jsonl --bib refs.bib [--source auto --existing-bib prev.bib --rank --emit-ledger-draft claims_refs.jsonl --emit-numeric-map numeric_map.json]`
  （缺字段走 Crossref→arXiv 回退并补摘要，题名相似度不足即跳过防错配；仍缺的
  `needs_manual` 项走宿主联网检索兜底；无 API key 时公开层限流，
  行内带 `rate: public-tier` 标记，L3 默认屏蔽 AI `tldr`）。
- **产出入账**：`refs.bib` + `refs.jsonl` + 台账增补 `retrieval:<citekey>`
  行（带 `evidence_level`：有 abstract=L2，仅题录=L3）。citekey 由脚本
  确定性生成，台账与 bib 共用同一套键。作者自带的参考文献同样入账：
  origin 用 `material:<bib文件路径>#L<行>`，citekey 由 `assign_citekeys`
  统一分配，evidence_level 按实际持有的全文/摘要/题录定级。
- **停下问什么**："引用池与分级认可？核查降级披露（如有）知悉？"

### 阶段 4｜分节成稿

- **做什么**：按 outline 逐节写作，先写正文主干（Methods / Experiments / Related Work / Introduction），
  Abstract 留待实验结果与阶段 5 图表定型后定稿。引用按硬规则 4；
  每个主张句上方一行 `% @claim:<id>[,<id>...]` 绑定台账。
- **声音模型**：起草按 `references/voice-calibration.md` 的刻度尺
  （断言强度 = 离证据的距离）校准语气；它是倾向参考，不是句型模板。
- **调用谁**：paper-writer（各节）、intro-drafter（Introduction）。
- **产出入账**：`sections/*.tex`（文件名序=装配序）+ 台账增补。
  跑 `python scripts/ledger_audit.py claims.jsonl --materials materials/ [--outline outline.json] --sections sections/ [--tables tables/ --bib refs.bib]`，
  违规清零才交检查点。
- **停下问什么**："各节文本与主张边界认可？审计违规已清零？"

### 阶段 5｜图表

- **做什么**：数据图与表格从日志确定性生成（色盲安全调色板、图内字号
  ≥9pt、booktabs 表格）；概念图给 figure-designer 规范后执行。
- **调用谁**：figure-designer 规范 + `scripts/plot_from_logs.py`：
  `--mode plot --log <日志> --spec <plot.json>`（PDF 矢量+PNG 预览）；
  `--mode table --log <日志> --spec <table.json> --out <表.tex>`。
  风格依据见 `references/plot-style-notes.md`。
- **产出入账**：`figures/*.pdf` + `tables/*.tex` + 生成 spec JSON 存档；
  图/表对应的数据主张入账（L1，origin 指向日志行区间）。
- **停下问什么**："图表是否准确表达日志数据？概念图规范认可？"

### 阶段 6｜LaTeX 装配

- **做什么**：套真实会议模板（样例 `templates/cvpr2025/`，其余用户自备）、
  注入 bib、按文件名序接线 `\input`、剥离 `% @claim:` 注释、编译自检。
  接线标记 `% >>> paper-orchestrator: sections`；真实模板无标记时按
  `references/vendor-notices.md` 四的结构备忘替换示例正文区。
- **调用谁**：`scripts/latex_compose.py`：
  `python scripts/latex_compose.py --template <模板目录> --sections sections/ --bib refs.bib --figures figures/ --out manuscript/ [--tables tables/] [--outline outline.json] [--numeric-map map.json]`
- **产出入账**：`manuscript/` 可编译包 + `compose_report.json`。
  `missing_citations`/`missing_files`/`raster_refs` 非空 → 修复重跑；
  `compiled=None`（无 TeX）→ 交付源码包并在检查点说明。
- **停下问什么**："装配报告干净？无 TeX 时接受源码包交付？"

### 阶段 7｜自评审

- **做什么**：严格按五步顺序执行（详见 `references/stage-playbook.md`）：
  `7.1 审稿与独立核查（pre-submission-reviewer + autorater score.md 参考分 + Rung 1/2 抽查） → 7.2 逻辑修订与错配处置（改写落 sections/*.tex，记录 dispositions.json） → 7.3 XOR 收尾润色（作用于 sections/*.tex） → 7.4 重审计与重装配（刷新 manuscript/） → 7.5 终稿签字`。
  autorater 参考分不做 gate，模板见 `references/reflection-prompts.md`。
- **调用谁**：pre-submission-reviewer（评审结论唯一拥有者）；
  paper-polish **XOR** academic-humanizer（作用于 `sections/*.tex`）；核查按验证阶梯。
  审计：`python scripts/ledger_audit.py claims.jsonl --materials materials/ [--outline outline.json] --sections sections/ [--tables tables/ --bib refs.bib] --strength-report [--dispositions dispositions.json]`。
  错配报告非空 → 逐条处置（改肯定 / 改台账 / 缩小主张，作者裁决，写入 `dispositions.json`）后，
  重跑 `latex_compose.py` 刷新 `manuscript/` 方可签字。处置方向按
  `references/voice-calibration.md` 的刻度尺校准；
  诚实前瞻句不是 hedge，不得被当作防御语言删除。
- **产出入账**：`review.md` + `score.md` + 终稿 tex（重跑装配刷新 `manuscript/`）。
- **停下问什么**："评审意见处置认可？错配清单已处置？终稿签字？"

## 单阶段进入/退出协议

- 进入：用户声明"从阶段 N 开始 + 已有产物路径"。先校验已有产物（路径
  存在、outline 键齐、台账可解析），再从该阶段接续；**不重做前序阶段，
  缺产物停下问，不臆造**。细则见 `references/stage-playbook.md`。
- 退出：用户说"停"即停。产物与台账留在输出目录，报告当前阶段与待办，
  下次可续。

## 三端一致性

本载荷在 Claude Code、Codex、Antigravity 三个宿主装完全一样的一套：
同一 SKILL.md、同一脚本、同一参考文件。编排不依赖任何宿主特有能力——
子代理、联网检索等能力缺失时按阶梯降档并披露（硬规则 2），行为差异
只允许出现在"机制降级+披露"这一条通道里。脚本只依赖 Python 3.11+ 与
matplotlib、requests（ledger_audit 与 latex_compose 仅 stdlib）。

## 参考文件

- `references/stage-playbook.md` — 阶段表全文、进入/退出协议、接线标记、
  numeric-map 生成、脚本 CLI 速查。
- `references/voice-rules.md` — 一个声音一本账全文、裁决表、强度错配双列表。
- `references/voice-calibration.md` — 语料校准的声音模型（8 篇最佳论文
  倾向 + 反过拟合声明 + 错配处置指引），阶段 4 起草与阶段 7 处置用。
- `references/outline-schema.md` — outline/台账格式与 ledger_audit 语义。
- `references/reflection-prompts.md` — 运行时 autorater 参考评分模板（精简无冲突版；完整上游提示词存档见仓库根目录 `docs/upstream-prompts-archive.md`）。
- `references/plot-style-notes.md` — 绘图风格依据与确定性默认。
- `references/vendor-notices.md` — 上游出处、分歧记录、cvpr2025 结构备忘。

## 与兄弟 skills 的边界

- 起草文风归 paper-writer；Introduction 归 intro-drafter；结构定位归
  tech-paper-template / benchmark-paper-template；检索纪律归 deep-research；
  概念图规范归 figure-designer；评审结论归 pre-submission-reviewer；
  收尾润色归 paper-polish 或 academic-humanizer（XOR）。
- 本 skill 只拥有流程、顺序、检查点与台账。领域冲突按裁决表让位。