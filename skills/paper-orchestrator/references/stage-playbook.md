# stage-playbook — 阶段表全文、进入/退出协议、接线与 numeric-map

本文件是 SKILL.md 七阶段协议的操作细则。规则事实源是设计 spec 与
SKILL.md 硬规则；本文件不新增规则，只展开操作。分级与核查语义一律引用
canonical 文件（`paper-writer/references/evidence-discipline.md`、
`paper-writer/references/verification-ladder.md`），不复述定义表。

## 1. 阶段表全文

| 阶段 | 干什么 | 调用谁 | 产出（入账） | 检查点问题 |
|---|---|---|---|---|
| 1 材料入账 | 想法/实验日志/目标会议清点，建 claims 台账骨架 | 无（自检清单） | materials.md + claims.jsonl 空账 | 材料齐全？会议确认？ |
| 2 大纲 JSON | 章节计划+文献检索策略+可视化计划 | tech-paper-template / benchmark-paper-template 定位 | outline.json | 结构与贡献定位认可？检索策略覆盖？ |
| 3 文献缝合 | 检索→排序→逐条独立上下文核查（Rung 1 优先；无子代理降 Rung 2 并披露）→BibTeX 装配→按大纲分配引用 | deep-research 检索纪律 + paper-writer 验证阶梯 + scripts/lit_search.py | refs.bib + refs.jsonl + 台账增补（带 evidence_level） | 引用池与分级认可？降级披露知悉？ |
| 4 分节成稿 | 按 outline 逐节写作，正文主干先行，Abstract 待实验与图表定型后定稿；主张句绑 `% @claim:` | paper-writer、intro-drafter | sections/*.tex + 台账增补 | 文本与主张边界认可？审计清零？ |
| 5 图表 | 数据图/表从日志确定性生成（色盲安全、≥9pt、booktabs）；概念图给规范后执行 | figure-designer 规范 + scripts/plot_from_logs.py | figures/*.pdf + tables/*.tex + 生成 spec 存档 | 图表准确表达数据？ |
| 6 LaTeX 装配 | 套会议模板、注入 bib、接线、剥离 `% @claim:`、编译自检 | scripts/latex_compose.py | manuscript/ 可编译包 + compose_report.json | 报告干净？无 TeX 接受源码包？ |
| 7 自评审 | 严格按 7.1 审稿核查 → 7.2 逻辑修订与错配处置 → 7.3 XOR 润色 → 7.4 重审计与重装配 → 7.5 终稿签字 | pre-submission-reviewer、paper-polish **XOR** academic-humanizer | review.md + score.md + 终稿 tex | 处置认可？错配已清？终稿签字？ |

每阶段产出后停下等用户签字；签字前该阶段的审计/核查必须完成
（阶段 4/7 的 ledger_audit 违规清零；阶段 3/7 的独立核查无未决条目；
阶段 7 的强度错配报告非空必须逐条处置）。

**阶段 4/7 补注（能力提供者缺失）**：阶段点名的兄弟 skill（paper-writer、
intro-drafter、pre-submission-reviewer 等）是能力提供者，不是前置产物；
宿主缺少同名 skill 时，缺同名 skill 由宿主直接承担——检查点、台账与审计
规则不变，流水线不得因此停下。

**阶段 7 补注（单真源、五步执行序与润色后重审计）**：`sections/*.tex`、`tables/*.tex` 与
`outline.json` 是唯一可编辑真源，`manuscript/` 只是装配构建产物（禁止手工改
`manuscript/`）。阶段 7 严格按下列五步确定性次序执行（禁止倒置）：

- **7.1 审稿与独立核查**：隔离上下文引文抽查复核（Rung 1/2）+ `pre-submission-reviewer` 五维评审（`review.md`）+ 运行时 autorater 参考分（`score.md`，只作参考不做 gate，模板见 `references/reflection-prompts.md`）；
- **7.2 逻辑修订与错配处置**：先修复 CRITICAL/MAJOR 逻辑与事实问题，跑 `ledger_audit.py ... --strength-report [--dispositions dispositions.json]` 逐条处置错配并记录 `dispositions.json`（全部改写落在 `sections/*.tex` / `tables/*.tex`）；
- **7.3 XOR 收尾润色**：对 `sections/*.tex` 一次性执行 `paper-polish` **XOR** `academic-humanizer`（保留 `% @claim:` 标记，遵循 `voice-calibration.md` 刻度优先，不得柔化已测结果或把诚实前瞻句压成免责声明）；
- **7.4 润色后重审计与重装配**：**润色之后、终稿签字之前**，必须重跑 `python scripts/ledger_audit.py claims.jsonl --materials materials/ [--outline outline.json] --sections sections/ [--tables tables/ --bib refs.bib] --strength-report --dispositions dispositions.json`（润色可能改动数字句与主张句），确认违规清零且无新增未处置错配后，再重跑 `latex_compose.py`（带 `--outline outline.json` 与 `--tables tables/`）刷新 `manuscript/` 并确认编译/完整性通过；
- **7.5 终稿签字**：交付 `review.md`、`score.md`、`compose_report.json` 与处置记录，获用户签字后完成。重审计时同时核对：没有诚实前瞻句被压成免责声明，也没有已测结果被柔化（声音刻度见 `references/voice-calibration.md`）。

**阶段 3 补注（作者自带文献）**：作者自带的参考文献在阶段 3 同样入账：
origin 用 `material:<bib文件路径>#L<行>`，citekey 由 `assign_citekeys`
统一分配，evidence_level 按实际持有的全文/摘要/题录定级。

## 2. 输出目录约定

一次流水线一个输出目录，产物按阶段落位：

```
<输出目录>/
  materials/            # 阶段 1：作者材料（或指向原路径的清单）
  materials.md          # 阶段 1：材料清单
  claims.jsonl          # 台账，贯穿全程，只增补不丢行
  outline.json          # 阶段 2
  refs.jsonl  refs.bib  # 阶段 3
  sections/*.tex        # 阶段 4（文件名序 = 装配序，如 01_intro.tex）
  specs/*.json          # 阶段 5：绘图/表格 spec 存档（可复现）
  figures/*.pdf (+.png 预览)   # 阶段 5
  tables/*.tex          # 阶段 5
  manuscript/           # 阶段 6：可编译包 + compose_report.json
  review.md  score.md   # 阶段 7
```

## 3. 单阶段进入/退出协议

**进入**：用户声明"从阶段 N 开始 + 已有产物路径"。

1. 校验已有产物：路径存在且可读。前置清单**只要求前序阶段的产出，
   绝不要求本阶段自己的产出**（与阶段表"产出入账"列对齐）：
   - 进阶段 1：作者材料（idea/实验日志/目标会议信息），无前置产物。
   - 进阶段 2：materials/ + materials.md + claims.jsonl（阶段 1 产出）。
   - 进阶段 3：上述 + outline.json（阶段 2 产出，必需键齐，见
     outline-schema.md）。
   - 进阶段 4：outline.json + refs.bib + claims.jsonl + materials/
     （阶段 2/3 产出）。sections/ 只在**阶段 4 中途续跑**时要求。
   - 进阶段 5：outline.json（取 viz_plan）+ 实验日志 + claims.jsonl；
     spec 可选（作者自带则用，否则本阶段生成）。specs/ 是本阶段产出，
     不作前置。
   - 进阶段 6：sections/ + refs.bib + figures/ + tables/*.tex（阶段 4/5 产出）+
     模板目录（用户自备或 templates/cvpr2025/）。
   - 进阶段 7：manuscript/ + sections/ + claims.jsonl + materials/
     （阶段 6/4 产出；sections/ 供审计与抽查复核）。
2. 台账先跑 `python scripts/ledger_audit.py claims.jsonl --materials <材料目录> [--outline outline.json]`
   确认可解析、无死链、大纲结构与引用完整；有违规先报告，不静默继续。
3. 从阶段 N 接续，**不重做前序阶段**。缺产物或产物与声明不符 → 停下问
   用户，不臆造补齐。
4. 阶段 7 单独进入时，独立上下文抽查复核与强度错配处置照常执行，
   不因"只评审"而跳过。

**退出**：用户任何时候说"停"即停。产物与台账留在输出目录；报告当前
阶段、已签字阶段与待办清单。续跑按"进入"协议从当前阶段接续。

**独立使用不拦截**：用户直接叫 paper-writer / deep-research 等时不经过
本流水线；本文件规则只在流水线会话内生效。

## 4. 接线标记约定（阶段 6）

入口文件：模板目录有 `main.tex` 用之，否则 `template.tex`（cvpr2025
作者套件上游即 template.tex，无 main.tex）。

- **有标记**：入口文件含单独一行
  `% >>> paper-orchestrator: sections`
  → `\input{sections/<文件名去扩展名>}` 行插在该标记**下一行**，按
  sections/*.tex 文件名字典序。自备模板推荐加此标记，位置即正文起点。
- **无标记（真实会议模板常态）**：按 `references/vendor-notices.md` 四的
  结构备忘——替换首个 `\maketitle` 之后、`\small` bibliography 块的 `{`
  之前的整段示例正文；bibliography 块、注释态附录与 `\end{document}`
  原样保留。无 `\maketitle` 时退到 `\begin{document}` 之后插入（不删
  示例正文，报告 warning）；连 `\begin{document}` 也没有则报错停下。

装配同时：剥离整行 `% @claim:<id>` 注释（终稿不含标记）；带
`--numeric-map` 时把 `[n]`/`[n,m]` 桥接为 `\cite{key}`（to_cites）。
完整性检查：缺引用键、缺文件、光栅图引用（.png/.jpg/.jpeg）都会让
`compose_report.json` 的 `ok=false`；修复后重跑。编译工具链探测顺序
latexmk → xelatex → pdflatex；都没有则 `compiled=None`，交付源码包并
在检查点说明（不算失败）。

**表格接线约定（阶段 5 → 6）**：支持两种等价方式：
- **方式 A（独立表文件，推荐）**：阶段 6 传 `--tables tables/` 把 `tables/*.tex`
  同步到 `manuscript/tables/`（同步剥离 `% @claim:`），正文可用
  `\input{tables/...}`；阶段 4/7 审计同步传 `--tables tables/`。
- **方式 B（内联章节）**：阶段 5 生成的 booktabs 表格块**直接粘贴进对应章节**的
  `sections/*.tex`；`% @claim:` 标记行放在 `\begin{table}` 上方（tabular 环境
  **之外**），审计脚本会把该绑定覆盖到表注与表格数据行。未传 `--tables` 时**不要**用
  `\input{tables/...}`——否则该引用会报 missing_files 使 `ok=false`。

**模板占位符与 bib 同步（阶段 6 检查点）**：推荐传 `--outline outline.json`，
compose 会按 `title` 与 `metadata.authors` / `metadata.paper_id` 自动替换
`\title{My Title}`、示例作者块（Ambitious AI Researcher）与
`\paperID{12345678}` 占位符，并自动把 `\bibliography{...}` 同步为 `--bib`
对应的文件名（同时清理模板自带的假 `.bib`）；若未传 `--outline` 导致占位符
存活，compose 会报 warning，检查点必须手动更新后再签字。

## 5. numeric-map 生成（阶段 3 台账 → 阶段 6 桥）

作者粘贴 paper-writer 线稿常带 `[n]` 数字引用（paper-writer 默认数字
顺序编码）。桥接规则：

1. 阶段 3 交付时，把台账中**所有带 citekey 的行**按**入账顺序**编号
   `"1".."N"`——既含 `origin` 为 `retrieval:<citekey>` 的检索行，也含
   作者自带 `material:<bib文件路径>#L<行>` 行（其 citekey 同样由
   `assign_citekeys` 统一分配）——可由 `lit_search.py --emit-numeric-map numeric_map.json`
   自动生成 `numeric_map.json`（再并入作者自带条目）：
   `{"1": "<citekey1>", "2": "<citekey2>", ...}`，并把编号表随 refs.bib
   一起交给作者。线稿的 `[n]` 语义必须与该编号表一致。
2. **装配前核对（必做）**：阶段 6 装配前，作者确认线稿自带的参考文献
   列表与编号表逐条对齐（线稿第 n 条 = 编号 n 的文献）；不一致 → 修
   numeric_map 或修线稿编号，绝不猜。
3. 阶段 6 用 `--numeric-map numeric_map.json` 传入；`to_cites` 把每个
   `[n]` 换成对应 `\cite{citekey}`（数学环境内的 `[n]` 与 `\cite[...]`
   可选参数不会被桥接）。缺号/越界 → CiteError（退出码 2），
   停下核对编号表，不猜。
4. 多个编号映射到同一 citekey 是合法的多点引用：`to_cites` 去重合并，
   compose 只报 warning，不报错。
5. 线稿已直接写 `\cite{citekey}` 时不需要 map；citekey 仍必在台账。

## 6. 脚本 CLI 速查（实际接口）

```
# 阶段 3：检索 + 回退补全 + BibTeX（requests；key 可选，绝不打印）
python scripts/lit_search.py (--query "<检索串>" | --queries-from outline.json) \
    --limit 20 --out refs.jsonl [--bib refs.bib] [--source s2|crossref|arxiv|auto] \
    [--fallback crossref|arxiv|off] [--append --existing-bib prev.bib] \
    [--rank --keywords "..."] [--emit-ledger-draft claims_refs.jsonl] \
    [--emit-numeric-map numeric_map.json] [--keep-l3-tldr] [--api-key KEY]
# key 优先级 --api-key > SEMANTIC_SCHOLAR_API_KEY > 公开层（行标 rate: public-tier）
# 回退候选题名相似度 < 0.70 即跳过防错配；仍缺字段标 needs_manual:<field>
# citekey = slug(姓)+年份+标题首个实词；追加/锁定已有 bib 键时不漂移旧键

# 阶段 5：日志 → 图 / booktabs 表（table 模式纯 stdlib；离线、确定性）
python scripts/plot_from_logs.py --mode plot  --log train_log.csv --spec plot.json [--out DIR]
python scripts/plot_from_logs.py --mode table --log train_log.csv --spec table.json [--out tab.tex]
# plot spec: x_col, y_cols[], kind=line|bar, xlabel, ylabel, out_dir[, title, name, labels, yerr_cols, xscale, yscale, xlim, ylim]
# table spec: columns[], caption, label, round{列:小数位}[, star, headers, bold_best]
# 缺列报错并列出实际列名；输入 .csv（表头）或 .jsonl（每行扁平对象）

# 阶段 6：装配（stdlib；编译可选；--outline 自动注入元数据）
python scripts/latex_compose.py --template <模板目录> --sections sections/ \
    --bib refs.bib [--figures figures/ --tables tables/ --outline outline.json] \
    --out manuscript/ [--numeric-map map.json]

# 阶段 4/7：台账与大纲审计（stdlib）
python scripts/ledger_audit.py claims.jsonl --materials materials/ \
    [--outline outline.json] [--sections sections/ --tables tables/ --bib refs.bib \
     --strength-report [--dispositions dispositions.json]]
# 退出码 0 当且仅当台账+大纲+数值违规为零；--strength-report 只报告不影响退出码
```

脚本路径相对本 skill 根目录；在输出目录工作时用绝对路径或先 cd 到
skill 根。四个脚本都不调用任何模型，可在三个宿主下原样运行。