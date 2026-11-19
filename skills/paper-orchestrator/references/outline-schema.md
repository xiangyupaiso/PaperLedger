# outline schema、claims 台账与 ledger_audit 说明

本文件定义 paper-orchestrator 的 outline 结构、claims 台账（JSONL）格式，以及
`scripts/ledger_audit.py` 的审计语义。**分级与核查的定义不在这里复述**，一律引用
canonical 文件（见下）。模板见 `assets/outline_template.json` 与
`assets/claims_ledger_template.jsonl`。

## 1. Canonical 引用（只引用路径与语义，不复制定义表）

- 主张强度分级 L0–L4：`paper-writer/references/evidence-discipline.md`
  的强度表。本仓 `evidence_level` 的语义逐字对齐该表：L1 全文/数据可支持任何主张；
  L2 有 abstract 只支持方向与 headline findings（禁具体数值/方法步骤）；L3 仅题录
  元数据只支持 “X et al. (Year) addressed Y” 级指称（禁方法细节与性能数字）；
  L0 字段常识无数字、无专名、无量化比较；L4 模型记忆不支持任何主张，**永不入账**。
- 引文独立核查降档机制 Rung 1/2/3：`paper-writer/references/verification-ladder.md`。
  阶段 3 与阶段 7 的独立上下文核查步按该文件执行（优先 Rung 1 新上下文核查器；
  无子代理能力降 Rung 2 并在交付说明披露）。**ledger_audit.py 不实现核查本身**，
  只做确定性的台账/数值/强度审计。

## 2. outline 必需键

顶层必需键：`title`、`venue`、`sections[]`、`lit_strategy`、`viz_plan`。

- 可选顶层键 `metadata`：含 `authors[]`（每项 `name`、`affiliation`、`email`）与 `paper_id`，供阶段 6 `latex_compose.py --outline` 确定性注入标题/作者/论文 ID，避免重跑装配覆盖模板元数据。
- `sections[]`：每项含 `id`、`kind`、`claims`（claim id 列表）、`purpose`。
- `lit_strategy`：含 `queries[]`（检索查询串）与 `must_contain[]`（相关工作必须
  覆盖的主题）。**这是本仓扩展字段，上游 PaperOrchestra 的 outline schema 没有它**
  （上游仅 `plotting_plan` / `intro_related_work_plan` / `section_plan` 三键；
  见 `references/vendor-notices.md` 二.5）。
- `viz_plan`：含 `figures[]`，每项含 `id`、`source_section`（须为某 section 的
  `id`）、`kind`、`data_ref`。

## 3. claims 台账行（JSONL）

每行一个 JSON 对象，必需键：`id`、`claim`、`origin`、`evidence_level`、`boundary`；
可选键 `conversions`（见 §5）与 `citekey`（用于作者自带 `material:<bib文件路径>#L<行>` 文献行记录统一分配的 citekey，便于 `--bib` 交叉校验与 `numeric_map` 生成）。

`origin` 三种格式：

- `material:<相对路径>#L<起>[-L<止>]`：materials 目录下的文件，行区间**1-based、
  闭区间**；省略 `-L<止>` 表示单行。越界（超出文件行数）= 死链违规。
- `retrieval:<citekey>`：检索得到的文献，以 citekey 定位。**无本地行区间**。
- `field_common`：字段常识，无来源文件。

`evidence_level ∈ {L0,L1,L2,L3,L4}`，语义见 §1（L4 永不入账）。
`boundary ∈ {any, directional, headline_only, related_work_only, none}`，
**由 level 推导**，审计校验二者一致：

| level | 推导 boundary |
|---|---|
| L1 | any |
| L2 | headline_only |
| L3 | related_work_only |
| L0 | directional |
| L4 | none |

level/boundary 矛盾（如 L3 + directional）= 违规。

## 4. 草稿 → 台账绑定（定死）

阶段 4 的 `sections/*.tex` 中，每个主张句**上方一行** `% @claim:<id>[,<id>...]`
注释。`ledger_audit` 按标记把正文与 claim 对齐：

- 标记绑定其后**第一个 prose 句**；同段后续句若无自己的标记则视为无绑定。
- 无标记的数值句 = **孤儿违规**（orphan）。
- 标记指向不存在的 id = **死链违规**（dead-link）。
- 阶段 6 装配时 `latex_compose.py` 剥离这些注释行（Task 5 已钉），终稿不含标记。

## 5. 模块常量（ledger_audit.py）

### 5.1 强度信号词表 `HEDGE_WORDS`

恰为四个词：**may、could、potentially、likely**。`limitations`、`suggest`、
`indicate` **不是**惩罚词，不出现在任何词表常量中。强度错配审计只按这四词判定弱化。

### 5.2 数值换算白名单 `CONVERSIONS`

| 名称 | 语义 |
|---|---|
| `x100_percent` | fraction × 100 → percent |
| `div100_percent` | percent ÷ 100 → fraction |
| `round_0dp` | 四舍五入取整 |
| `round_1dp` | 四舍五入到 1 位小数 |
| `round_2dp` | 四舍五入到 2 位小数 |
| `round_3dp` | 四舍五入到 3 位小数 |

claim 须在 `conversions` 列表中**声明**换算，它才能豁免一个正文数字；
未声明的换算不豁免。声明白名单外的名称 = 违规。支持**按声明顺序链式复合换算**
（例如 `["x100_percent", "round_1dp"]` 将 `0.9341` 换算为 `93.4`；列表中各项也
保留单步匹配能力）；无换算时允许规范化数值等价（如 `0.850` 与 `0.85`，但符号仍严格一致）。

## 6. audit_numbers 剔除集（先剔除，再扫描）

扫描正文数据数字前，先空白化以下非数据区域（保留行号）：

- 未转义 `%` 起的 TeX 注释；
- display 公式环境 `equation/align/gather/multline/flalign/eqnarray`（含 starred）、`$$...$$` 与 `\[...\]`；
- 行内 `\(...\)` 以及纯符号公式 `$...$`；**行内数据数学表达式**（含 `\%`、数字后 `\times`、数字旁 `\pm`、或独立带符号增量如 `$+12.4$`/`$-0.5$`）剥除定界符/符号后**参与**数值审计，纯符号公式（如 `$1e^{-3}$`、`$0.5$`、`$\alpha=.57$`）继续剔除；
- `\cite/\citep/\citet/\citeauthor/\citeyear/\citealt/\citealp/\parencite/\textcite/\ref/\eqref/\cref/\Cref/\autoref/\pageref/\nameref/\label` 的参数（含可选 `[...]` 参数）；
- `\includegraphics` 与排版尺寸命令（`\vspace`/`\hspace`/`\scalebox`/`\resizebox`/`\multicolumn`/`\multirow`/`minipage`/`\setlength`/`\renewcommand{\arraystretch}`）；
- TeX 计数器/编号语法（`\setcounter`、`\addtocounter`、`\newcounter`、
  `\stepcounter`、`\refstepcounter`、`\value`、`\arabic`、`\roman`、`\alph`、
  `\thepage`、`\number` 等）；
- 括号内出版年份 `(YYYY)`（引文元数据，非数据数字；canonical L3 指称形如
  “X et al. (Year) addressed Y”）；
- 连字符专名标识符（如 `ResNet-50`、`CIFAR-100`、`GPT-4`、`Top-1`）与独立小序号枚举 `(1)`/`(2)`；数值范围 `4--7` 拆为两个正数而非负号。

带定量单位后缀的数字（如 `20x`/`70B`/`16GB`/`1FPS`/`100ms`）纳入数值审计。剩余正文数字必须**逐字**（或同号精确数值等价）落在某条被 `@claim` 绑定的 **L1** claim 的 origin 区间原文中，
或按该 claim 声明过的白名单换算得出，否则违规。L2/L3/L0/L4 不支持具体数值；
`retrieval:`/`field_common` 无本地行区间，不能豁免数值。

- **表格块绑定**：`% @claim:<id>` 置于 `\begin{table}` / `\begin{table*}` 上方时，覆盖整个 `table` 环境（caption 与 `tabular` 数据行）；也支持 `--tables tables/` 直接审计独立表文件。
- **L3 白名单边界**：`boundary=related_work_only`（L3）的 claim 仅允许在 related work / background / literature / prior work 章节出现，其余章节（如 method/approach/framework/pipeline/experiments/abstract/conclusion）绑定引用 = 违规（含 citekey 定位）。
- **L0 正文专名检查**：绑定为 `L0 (field_common)` 的正文句同样受专名与数字禁令审计。
- **可选 `--bib refs.bib` 交叉校验**：启用后检查正文每条 `\cite{key}` 均已在台账入账，且 L3 文献不可在非 related-work 章节无绑定直接引用。

## 7. field_common 专名启发式（简单、已文档化，不做 NLP）

L0 常识主张禁数字与专名。专名判定用三条正则： capitalized 多词名
（连续 ≥2 个首字母大写词）、camelCase 标识符（如 ImageNet）、全大写缩略词（≥2 字母）。
句首大写后接小写词（如 “Neural networks”）不误报；Title Case 短语会被标记，
故 L0 主张宜用小写泛称表述。

## 8. audit_strength_mismatch（只报告，无 gate）

输出两个列表，**无任何词频预算、无 quota、无 gate 数字**：

- `weakened_strong`：L1/L2 支持却用 may/could/potentially/likely 弱化的句子。
- `overclaimed_weak`：L3/L4 支持或无账、却肯定断言（无上述四词）的句子。

每项含 `file`、`line`、`claim_ids`、`matched_claim`、`match_ratio`（difflib 模糊对齐
claim 文本与标记句）、`sentence`、`fingerprint`、`advice`。`advice` 同时给出两个处置方向
（upgrade-to-assertive 或 fix-ledger/shrink-claim），**不强制方向**，由作者裁决。非主张结构导语句（如 `In this section, we describe...`）、L0 常识句与表格数据行自动从 `overclaimed_weak` 降噪跳过。

## 9. CLI、大纲校验与处置持久化（`--outline` 与 `--dispositions`）

```
python ledger_audit.py claims.jsonl --materials materials/ \
    [--outline outline.json] [--sections sections/ --tables tables/ --bib refs.bib \
     --strength-report [--dispositions dispositions.json]]
```

- 退出码 0 当且仅当 `audit_claims` + `audit_outline` + `audit_numbers` 违规为零。
- `--outline` 确定性校验 `outline.json` 必需键、无重复 `sections[].id`、对 `claims.jsonl` 的死链引用、`viz_plan` 的 `source_section` 与 `data_ref` 存在性及可选 `metadata`。
- `--sections` 启用数值/绑定审计；缺省只审计台账（与可选 `--outline`）。
- `--tables` 与 `--bib` 为可选扩展校验参数（需配合 `--sections`）。
- `--strength-report` 打印强度错配报告，但**不**影响退出码（需配合 `--sections`）。
- `--dispositions dispositions.json`（需配合 `--strength-report`）读取包含 `{"fingerprint", "decision", "rationale"}` 对象的列表（或 `{"dispositions": [...]}`），过滤已处置项并输出 `disposed_fingerprints`；一旦润色改写句子或绑定，指纹变更后将重新浮出。