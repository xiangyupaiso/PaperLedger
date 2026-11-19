# voice-rules — 一个声音、一本账

这是 paper-orchestrator 的核心裁决规则全文。SKILL.md 硬规则是其摘要；
冲突时以本文件展开的语义为准，但本文件不新增 spec 之外的规则。
分级与核查的 canonical 定义只引用路径，不复述：

- L0–L4 强度表：`paper-writer/references/evidence-discipline.md`
- 独立核查降档机制 Rung 1/2/3：`paper-writer/references/verification-ladder.md`

## 1. 一个声音：每阶段一个文风拥有者

多 skill 规则叠加导致满篇 hedge 的"防御性写作"是本流水线要消除的
反模式。手段不是新增措辞规则，而是**写权独占**：

文风指导的来源是声音包插槽 `references/voice-calibration.md`（可整体
替换为其他领域的自训声音包）；缺该文件时降级为宿主模型自身的最佳学术判断，
不阻塞阶段，也不改变本文件任何裁决规则。

| 时期 | 文风拥有者 | 其他角色 |
|---|---|---|
| 起草期（阶段 4） | paper-writer（Introduction 由 intro-drafter 执笔，同属起草期文风） | 评审/审计只报告，不直接改稿 |
| 中间阶段（1/2/3/5/6） | 无润色权 | **不得提前套润色/去 AI 味规则** |
| 收尾期（阶段 7） | paper-polish **XOR** academic-humanizer，一次性完成 | 禁止两者叠加调用 |

收尾 XOR 判定条件（写死）：

- 线稿有**中译英残留/中式英语** → paper-polish（语法/流畅/中译英重写）。
- 线稿是**纯英文、只需去 AI 味** → academic-humanizer（清晰度与作者声音）。
- 二者互斥，一次收尾只调一个；判定依据是线稿本身的状态，不是用户用了
  哪个中文词提问。拿不准时停下问作者，不默认叠加。

评审建议（pre-submission-reviewer、autorater 参考分）一律走"报告 →
作者/拥有者处置"通道，不绕过拥有者直接改文字。

## 2. 一本账：台账契约（防伪）

每条主张在 `claims.jsonl` 一行，带四个字段：
`claim / origin / evidence_level / boundary（允许边界）`。

- `evidence_level` **直接沿用** `paper-writer/references/evidence-discipline.md`
  的 L0–L4 canonical 语义，不另造分级：L1 全文/数据支持任何主张；
  L2 有 abstract（用户给或检索到）支持方向与 headline findings，禁具体
  数值与方法步骤；L3 仅题录元数据（标题/作者/年份/venue，**无 abstract
  才是 L3**）只支持 "X et al. (Year) addressed Y" 级指称，禁方法细节与
  性能数字；L0 是无数字、无专名、无量化对比的领域常识；L4 模型记忆
  不支持任何主张，永不入账。
- `boundary` 由 level 推导（L1→any、L2→headline_only、L3→related_work_only、
  L0→directional、L4→none），审计校验二者一致；矛盾即违规。
- `origin` 支持**行区间**：`material:<相对路径>#L10-L15`（1-based 闭区间）；
  检索文献用 `retrieval:<citekey>`；常识用 `field_common`。
- **数值一致性**：正文每个阿拉伯数字必须能在被引 claim 的 origin 区间
  原文中逐字找到，或明确由区间内数值按该 claim **声明过**的白名单换算
  得出（换算白名单见 outline-schema.md §5.2）。否则按违规处理，
  **不允许加 hedge 蒙混**——"may reach 0.93" 与 "reaches 0.93" 在数值
  审计下同罪。
- 台账外的主张按 paper-writer 阶梯处理：补检索、改弱主张、删。没有
  第四条路（打占位标签不是路）。

确定性审计由 `scripts/ledger_audit.py` 执行（台账违规 + 数值/绑定违规
gate 退出码）；它不做引用核查本身——核查是下一节的独立步骤。

## 3. 独立上下文核查（显式保留，阶段 3 与阶段 7）

阶段 3 的逐条引用核查与阶段 7 的抽查复核必须在**与写作上下文隔离的
回合**执行。按 `paper-writer/references/verification-ladder.md`：

- **Rung 1（优先）**：fresh-context 核查器。只给它正文（带引用标记）与
  参考文献表，不给写作推理；逐条用检索能力核实存在性、元数据与引用强度。
- **Rung 2（降级）**：宿主无子代理能力时，同上下文 grounding——逐条从
  真实检索响应重新推导每个引用条目，绝不凭记忆复核。比 Rung 1 弱，
  必须明说。
- **Rung 3**：完全无检索时按阶梯闭书规则（只引用户 supplied 文献、
  只保留指称级引用、交付说明声明未做独立核查）。

沿用阶梯原文语义（措辞同一）：

> The discipline never degrades; only the verification mechanism degrades,
> and any degradation is disclosed to the user in the delivery note.

即：**纪律不降级；只有核查机制降级；任何降级必在交付说明中向用户披露。**
状态分级（VERIFIED / METADATA_MISMATCH / NOT_FOUND / OVERCLAIM /
INCONCLUSIVE）与处置路由按阶梯 §5；无未决问题条目才放行。

## 4. 冲突裁决表（流程规则听 orchestrator，领域规则听子 skill）

| 冲突 | 谁赢 | 例子 |
|---|---|---|
| 流程/顺序/检查点 | orchestrator | "不许跳步"压过"某 skill 想自己润色" |
| 文字风格/措辞 | 该阶段唯一拥有者 | 阶段 4 paper-writer 赢，评审建议不直接改稿 |
| 事实/引用资格 | 验证阶梯（最严者赢） | autorater 夸了但台账没有 → 不成立 |
| 评审结论 | pre-submission-reviewer | orchestrator 不自行加判 |

读法：行与行之间再冲突时，流程行管"做不做、什么顺序"，领域行管
"做成什么样"。orchestrator 永远不自行发明评审结论，也不自行改文风。

## 5. 证据强度–措辞匹配审计（取代机械 hedge 词频预算）

机械词频预算（每千词 hedge 配额一类）**已废除**：词频只做报告项，
不做 gate，本文件与脚本中不存在任何预算数字。收尾阶段（阶段 7）跑
`scripts/ledger_audit.py ... --strength-report`，逐主张对照，输出两个
列表（只报告，不影响退出码）：

| 列表 | 定义 | 处置方向 |
|---|---|---|
| `weakened_strong` | 有 L1/L2 强证据支持、却用信号词弱化的句子 | 改肯定，直接陈述发现；若不确定性是真实的，改台账/缩小主张。作者裁决，不强制方向 |
| `overclaimed_weak` | 只有 L3/L4 支持或无台账、却肯定断言（无信号词）的句子 | 改台账或缩小主张（降到指称级、补强证据、或删句）；台账升级到 L1/L2 后才可改肯定。作者裁决，不强制方向 |

信号词**恰为四个**：`may`、`could`、`potentially`、`likely`，且仅作为
错配审计的输入信号，不是禁词。`limitations`、`suggest`、`indicate`
**不是惩罚词**——它们是正常学术动词，不出现在任何惩罚词表中，用它们
不触发任何扣分。

信号词只是输入信号，**不是判决**：命中与否都不直接决定句子对错。处置
方向由 `references/voice-calibration.md` 的刻度尺（断言强度 = 离证据的
距离）校准，不由词频决定。诚实前瞻句（"下一步在X验证Y"、结尾的
"We hope …"）不是 hedge，不得被当作防御语言删除。

铁律：**绝不为了压词频把缺证据的句子强行改肯定。** 审计修的是"证据与
措辞的错配"，不是词频本身；证据缺口只能靠补证据或缩小主张解决。

**处置闭环**：错配报告非空时，必须逐条处置（两个方向任选其一，记录
理由）后才能检查点签字。未处置的错配条目与未决核查条目一样，阻塞签字。