VENDOR_COMMIT: d9bae997e793a015ed38bb1605be9eb58c00284f

# vendor-notices — PaperOrchestra 上游出处、分歧记录与 cvpr2025 结构备忘

- 上游仓库：https://github.com/google-research/paper-orchestra（PaperOrchestra: A Multi-Agent Framework for Automated AI Research Paper Writing，Google Cloud AI Research）
- 本仓记录之 VENDOR_COMMIT（首行 40-hex）为 `git clone --depth 1` 于 **2026-11-17** 拉取到的 HEAD，上游提交时间 2026-11-15（"Merge pull request #4 from obrienciaran/fix/invalid-escape-sequences"）。
- 上游许可证：**Apache-2.0**（根目录 `LICENSE`，"Apache License Version 2.0, January 2004"）。上游全部 31 个 `.py`（共 31 个）均带 `# Copyright 2026 Google LLC` + Apache-2.0 头。
- 上游**无 NOTICE 文件**（`find . -iname "*notice*"` 零命中），亦无第三方声明清单；因此本文件同时承担第三方出处记录职责。
- clone 位于 `vendor/paper-orchestra/`（已 gitignore，不入库）；本 notices 是后续所有搬入任务引用的唯一出处台账。
- **诚实性约束**：Apache/Google 头只允许出现在**真正逐行搬入的 .py** 上。现状（fix-wave 2026-11-19 更新）：`scripts/lit_search.py`（Task 3）与 `scripts/latex_compose.py`（Task 5）**已搬入**上游代码并带 Apache-2.0 + Adapted 头；`plot_from_logs.py`（Task 4）与 `ledger_audit.py`（Task 6）为自研，无 Apache 头。`templates/cvpr2025/*` 属作者套件原样保留物，**不得**贴 Apache/Google 头。

## 一、搬入清单表

| 上游路径（@VENDOR_COMMIT） | 本仓去向（任务号） | 搬入性质 |
|---|---|---|
| `utils/scholar_utils.py`（100 行） | `skill/paper-orchestrator/scripts/lit_search.py`（Task 3） | 净搬 + bug 修复 + 字段补全 + 回退通道；实质重写检索函数签名与返回，头部按"Apache-2.0 + Adapted from"处理 |
| `methods/agents/plotting_agent.py`、`utils/paper_banana_utils.py` | 不搬代码，仅参照（Task 4 `plot_from_logs.py` 自研） | 无 Apache 头 |
| `utils/pdf_utils.py::compile_latex`（:169–:184）、`methods/paper_writer.py::shutil.copytree` 模板拷贝（:68） | `skill/paper-orchestrator/scripts/latex_compose.py`（Task 5） | copytree/compile 段搬入（Apache 头 + Adapted 行）；\input 接线与 `to_cites` 为自研 |
| `methods/prompts/outline_agent.py` 输出 schema（:83） | `assets/outline_template.json`、`references/outline-schema.md`（Task 6） | 参照 schema 扩展（非逐字搬代码） |
| `templates/cvpr2025/`（6 文件） | `skill/paper-orchestrator/templates/cvpr2025/`（Task 5） | **原样逐字节复制**，原条款（见"三"） |
| `methods/agents/content_refinement_agent.py`、`methods/prompts/content_refinement_agent.py:17`、`autoraters/agent_review.py` 等提示词 | `docs/upstream-prompts-archive.md`（完整存档）与 `references/reflection-prompts.md`（运行时精简评分模板） | 提示词文本存档（Apache 出处头保留），不建 .py |

## 二、分歧记录（与上游行为的每一处偏离）

1. **API-key 打印 bug——本仓修复**
   上游 `utils/scholar_utils.py:28`：`print(f"Using S2 API Key: {S2_API_KEY}")`，模块导入即把密钥打到 stdout（:27 读取环境变量）。本仓 `lit_search.py` 绝不打印 key；由 Task 3 测试 `test_api_key_never_printed` 钉死。
2. **检索返回字段扩展——authors 展平 / externalIds / bibtex 为自加**
   上游 `s2_title_search` 仅请求 `fields=title,authors,venue,year,abstract,citationCount,journal,publicationDate`（`utils/scholar_utils.py:68`，`limit=3` :67），且原样返回单个原始 API 条目或 None（fuzz 匹配阈值 >70，:95–:97）。全仓 grep：`externalIds`、`citationStyles` 在上游**零命中**；上游 bibtex 只有两处——LLM 本地拼串（`methods/agents/literature_review_agent.py:134`、`_generate_bibtex` :540）与编译期调用 `bibtex` 可执行程序（`utils/pdf_utils.py:182`）。本仓 `search_papers` 归一化返回 10 键（含 `authors: list[str]` 展平、`externalIds`（DOI/ArXiv）），`build_bibtex` 为确定性自研（非 LLM、非上游检索层）；返回列表（≤limit）而非单一最佳匹配。**注**：`authors` 字段上游响应里本有（原始对象列表），"自加"指本仓归一化形态与 externalIds/bibtex 两项上游所无。**补记（fix-wave）**：请求超时自上游 5s（`utils/scholar_utils.py:70`）提高为 10s（5s→10s）；`limit` 由上游硬编码 3（:67）**参数化**为函数参数与 CLI `--limit`（默认 20）。
3. **plot——自研，非上游 codegen**
   上游绘图对 `plot` 类图采用 LLM 生成 matplotlib 代码再 `exec` 执行：`utils/paper_banana_utils.py:657`（`generate_figure_visuals` :646 内，"Use python matplotlib to generate…"提示词）、`execute_plot_code_worker` :292–:319（:308 `exec(code_clean, exec_globals)`，:311 存 JPEG/base64）；`diagram` 类走图像模型（`methods/agents/plotting_agent.py:35` `image_model_name="gemini-3-pro-image-preview"`，:262 `base64.b64decode(res["base64_img"])`）。本仓 `plot_from_logs.py` 完全不同路线：spec 驱动的确定性 CSV/JSONL→matplotlib，无 LLM、无 `exec` 任意代码执行，PDF 矢量 + PNG 预览双出。
4. **compose 接线 / to_cites——自研；copytree 与编译序列为搬入**
   上游不做 \input 分节接线：由 LLM 整篇重写 template.tex（`methods/prompts/literature_review_agent.py:39-40` "return the full code for the new 'template.tex'"；`methods/prompts/section_writing_agent.py:72` 同）。上游可搬的部分：模板目录 `shutil.copytree(latex_template_dir, latex_writeup_dir, dirs_exist_ok=True)`（`methods/paper_writer.py:68`）与编译序列 `pdflatex → bibtex → pdflatex → pdflatex`（`utils/pdf_utils.py:181-184`，:169 函数头）。本仓 `latex_compose.py` 的按文件名序 \input 接线、`% >>> paper-orchestrator: sections` 标记、`to_cites` 数字引用桥（`[n]→\cite{key}`）、工具链探测扩展（latexmk→xelatex→pdflatex）均为自研，上游无任何对应物。
5. **outline schema 的 `lit_strategy`——扩展字段，上游无**
   上游 outline 输出 schema 恰为三个顶层键：`"plotting_plan"`、`"intro_related_work_plan"`、`"section_plan"`（`methods/prompts/outline_agent.py:83`，示例 JSON 自 :87 起，:85 "Example Output:"）。全仓 grep `lit_strategy` 零命中。本仓 outline schema 增加 `lit_strategy{queries[], must_contain[]}` 顶层字段，属本仓扩展，`references/outline-schema.md` 中须同样标注。

## 三、原样保留物（原条款，不贴 Apache 头）

1. **cvpr2025 作者套件（author-kit）**：`vendor/paper-orchestra/templates/cvpr2025/` 六文件（`template.tex`、`preamble.tex`、`cvpr.sty`、`ieeenat_fullname.bst`、`references.bib`、`guidelines.md`）Task 5 起逐字节复制入本仓 `skill/paper-orchestrator/templates/cvpr2025/`。这些**不是 Google 的原创代码**：`template.tex:1` 自我声明 `% CVPR 2025 Paper Template; see https://github.com/cvpr-org/author-kit`；`cvpr.sty:350` 亦引用 author-kit issue。`ieeenat_fullname.bst` 头部为 `Copyright 1993-2007 Patrick W Daly`（natbib 系列，"redistributed and/or modified under the terms of the LaTeX Project Public License … either version 1 of the License, or any later version"，见该文件 :4、:11-14）。处置：**原样保留、原条款**（CVPR author-kit / LPPL 条款随文件头原封携带），Task 5 测试 `test_cvpr_template_copied_byte_identical` 钉字节一致。
2. **reflection 提示词字符串存档**：`methods/agents/content_refinement_agent.py` 的反思循环（`max_reflections: int = 3` :42；循环 :249；循环内 f-string 提示词 `user_prompt_text = f"""` :259 起、文本 `REFLECTION ITERATION {i+1}.` 在 :260）与系统提示词 `content_refinement_agent_system_prompt`（`methods/prompts/content_refinement_agent.py:17`，Apache-2.0 文件）。本仓以**字符串存档**方式原样保留于 references（存档时保留其 Apache 出处注释，不重实现逻辑）。

## 四、templates/cvpr2025 结构备忘（真实锚点，Task 5 接线依据）

以下全部事实抄自 clone 的 `vendor/paper-orchestra/templates/cvpr2025/template.tex`（`cat -n` 行号），非臆测。**先纠正 brief 中的文件名假设**：

- 上游主文件叫 **`template.tex`，全仓不存在 `main.tex`**；"main.tex" 仅出现于 `frontend/app.py:498`，是展示 zip 时的重命名目标（`os.path.join(zip_source_dir, "main.tex")`）。Task 5 brief 要求复制为 `tests/fixtures/cvpr_real/main.tex`——内容=下列 77 行的 `template.tex` 逐字节复制，文件名以 Task 5 为准。

**总行数 77。** 锚点逐条：

| 行号 | 内容（原文引用） | 结构意义 |
|---|---|---|
| :1 | `% CVPR 2025 Paper Template; see https://github.com/cvpr-org/author-kit` | 作者套件出处注释（唯一文件级注释头） |
| :3 | `\documentclass[10pt,twocolumn,letterpaper]{article}` | |
| :4 | `\usepackage{cvpr}` | 样式包 |
| :6 | `\input{preamble}` | 宏区入口（preamble.tex 共 10 行，仅 `\red/\todo/\TODO` 批注宏） |
| :10-:11 | `\definecolor{cvprblue}…` + `\usepackage[pagebackref,…]{hyperref}` | |
| :13-:15 | `\def\paperID{12345678}`、`\def\confName{CVPR}`、`\def\confYear{2025}` | **宏定义区到此结束** |
| :17 | `%%%%%%%%% TITLE - PLEASE UPDATE` | 标题区起始标记 |
| :18 | `\title{My Title}` | 示例标题 |
| :20-:24 | `\author{Ambitious AI Researcher\\ … }` | 示例作者块（:24 闭合 `}`） |
| :26 | `\begin{document}` | |
| :27 | `\maketitle` | **`\maketitle` 存在，全文件唯一命中（grep -c 验证=1）。接线规则锚点：\input 插在此行之后（示例正文区替换点）** |
| :29-:33 | `\begin{abstract}` … `Abstract here.`（:31）… `\end{abstract}` | 示例正文区开始于 :29 |
| :35-:63 | 五个 `\section`：Introduction :35/:36 label、Related Work :41、Methodology :47、Experiments :53、Conclusion :59；占位正文 `Introduction here.` :38、`Related work here.` :44、`Methodology here.` :50、`Experimental setup, results, and analysis here.` :56、`Conclusion here.` :62 | 每节均带 `\label{sec:*}`，正文均为单行占位句 |
| :63 | `%%%%%%%%% CONCLUSION %%%%%%%%%`（闭线） | **示例正文区结束于 :63** |
| :65-:69 | `{\small` / `\bibliographystyle{ieeenat_fullname}`（:67）/ `\bibliography{references}`（:68）/ `}` | **bibliography 块，接线时必须保留** |
| :71-:75 | `%%%%%%%%% Appendix %%%%%%%%%` 与注释掉的 `% \appendix`（:73）、`% \section{xxx}`（:74） | 附录说明为注释态，非生效内容 |
| :77 | `\end{document}` | |

**注释标记实情**：文件中**没有** `% >>> paper-orchestrator: sections` 之类的本仓标记（grep 零命中）——印证 Task 5 "无标记 → 按备忘规则"是常态路径。上游标记样式为成对的 `%%%%%%%%% <名称> %%%%%%%%%` 包裹占位正文（如 :37/:39 包 INTRODUCTION），以及 :17 的 `TITLE - PLEASE UPDATE`。备忘规则（供 Task 5 照抄）：**首个（也是唯一一个）`\maketitle`（:27）之后、`\small` bibliography 块（:65）之前的整段示例正文（:28–:64，即 abstract+五节，含其成对 `%%%%%%%%%` 标记）替换为按文件名序的 `\input{…}`；:65-:69 bibliography 与 :71-:77 原样保留。** 示例正文字符串（`Abstract here.`、`Introduction here.` 等）即 Task 5 测试"示例正文标记串不再出现"的断言对象。
