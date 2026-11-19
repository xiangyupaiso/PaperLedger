# plot-style-notes — 绘图风格依据与确定性默认

VENDOR_COMMIT: d9bae997e793a015ed38bb1605be9eb58c00284f

阶段 5 的风格事实源。上游 PaperOrchestra 没有确定性 log→plot 代码
（Plotting agent 是 LLM 生成 matplotlib 代码再 `exec()` 执行），可搬的
只有风格提示词；本仓 `scripts/plot_from_logs.py` 是自研的 spec 驱动
确定性管线，不搬 codegen、不执行任意代码。出处与分歧见
`references/vendor-notices.md` 二.3。

## 1. 上游风格提示词（蒸馏来源，原文存档）

> 出处：`vendor/paper-orchestra/utils/paper_banana_utils.py:198`
> （PLOT_VISUALIZER_AGENT_SYSTEM_PROMPT）与 `:657`
> （generate_figure_visuals 内 plot 分支提示词）
> VENDOR_COMMIT: d9bae997e793a015ed38bb1605be9eb58c00284f ・ Apache-2.0，Copyright 2026 Google LLC

:198 系统提示词原文：

```text
You are an expert statistical plot illustrator. Write code to generate high-quality statistical plots based on user requests.
```

:657 用户提示词原文（`{figure_description}` 为占位符）：

```text
Use python matplotlib to generate a statistical plot based on the following detailed description: {figure_description}
 Only provide the code without any explanations. Code:
```

蒸馏结论：上游对"统计图"的意图是**出版级统计插图、matplotlib、
代码即产物**。本仓把"高质量"落实为下面的确定性默认，而不是交给模型
每次即兴发挥；概念图（diagram 类）不走本脚本，给 figure-designer
规范后执行。

## 2. 本仓确定性默认（plot_from_logs.py 已钉）

调色板——Okabe-Ito 色盲安全 8 色，按系列序循环取色，不得自造颜色：

| 序 | hex | 色名 |
|---|---|---|
| 0 | #0072B2 | blue |
| 1 | #E69F00 | orange |
| 2 | #009E73 | bluish green |
| 3 | #D55E00 | vermillion |
| 4 | #CC79A7 | reddish purple |
| 5 | #56B4E9 | sky blue |
| 6 | #F0E442 | yellow |
| 7 | #000000 | black |

字号与字体——图内一切文字 ≥9pt（spec 底线 ≥8pt，留 PDF 转换余量）：
`font.size 10`、`axes.titlesize 11`、`axes.labelsize 10`、
`xtick/ytick.labelsize 9`、`legend.fontsize 9`；`pdf.fonttype 42`
（TrueType 嵌入，避免 Type 3 位图字体）。

版面与双编码——`axes.spines.top/right False`（去顶右边框）；图例
`frameon False`、`loc best`（最小重叠位，不压数据）；
figsize 折线 4.0×3.0 in、柱状 4.8×3.2 in（单栏宽度量级）；
`tight_layout`。折线采用色盲安全色 + `LINESTYLES` + `MARKERS` 双编码
（`linewidth 1.6`，点数 `>40` 时自动启用 `markevery` 防糊），可选 `yerr_cols`
绘误差阴影带、`labels` 自定义图例名及 `xscale`/`yscale`/`xlim`/`ylim`；
柱状为分组柱（组宽 0.8/n），同步轮转 `HATCHES` 图案填充（带 `#000000`
边线）与可选 `yerr_cols` 误差棒，x 刻度抽稀到 ≤10 个、旋转 45° 右对齐，
保证 ≥9pt 下不糊。若正文 `\caption{...}` 已给出完整图题，spec 可省略
`title` 以免与图注重复。

确定性与依赖——同输入两次运行字节一致（PDF CreationDate 抑制，无时间戳）；
缺列报 ColumnError 并列出实际列名，不静默画错；`--mode table` 延迟跳过
`matplotlib` 导入，可在纯 stdlib 环境运行。

## 3. 交付规则（阶段 5 → 阶段 6）

- **稿内图只交 PDF 矢量**：`\includegraphics` 只引 `.pdf`；脚本同时
  产 300dpi PNG 仅作预览/审阅，绝不进稿。latex_compose 的完整性检查
  会把 `.png/.jpg/.jpeg` 引用记入 `raster_refs` 并使 `ok=false`。
- **表格走 `log_to_table`**（`--mode table`）：完整 booktabs 块
  （`\toprule/\midrule/\bottomrule`），数值列右对齐、文本列左对齐，
  单元格 LaTeX 转义；`round` 字典控制小数位；caption/label 按原始
  LaTeX 处理；支持可选 `star: true`（`table*` 跨双栏）、`headers`（列展示名）
  与 `bold_best`（`{列: "max"|"min"}` 最优值加粗 `\textbf{...}`）。
  禁止手抄日志数字进表格——手抄即绕过数值审计。
- 每张图/表对应的数据主张入台账（L1，origin 指向日志行区间）；
  生成 spec JSON 存 `specs/` 存档，保证可复现。

## 4. spec 示例

plot.json（折线）：

```json
{
  "x_col": "step",
  "y_cols": ["train_acc", "val_acc"],
  "kind": "line",
  "xlabel": "Training step",
  "ylabel": "Accuracy",
  "title": "Convergence",
  "out_dir": "figures",
  "name": "fig_convergence"
}
```

table.json（booktabs）：

```json
{
  "columns": ["method", "acc", "f1"],
  "caption": "Main results on the validation split.",
  "label": "tab:main",
  "round": {"acc": 2, "f1": 2}
}
```

输入日志：`.csv`（首行表头）或 `.jsonl`（每行一个扁平 JSON 对象）。