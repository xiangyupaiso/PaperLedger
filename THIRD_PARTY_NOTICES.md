# THIRD_PARTY_NOTICES

本文件逐项列出本仓库再分发的第三方材料及其许可证。本仓库自己的代码与
文档（`skills/paper-orchestrator/` 中未标注来源的部分、`tools/`、`tests/`、
`docs/`）以 Apache-2.0 发布，见 `LICENSE` 与 `NOTICE`。

## 1. 九个第三方 skill（原样保留，未修改）

> **[!CAUTION] 公开发布前的合规阻断项（Compliance Blocker Before Redistribution）**
> 1. 下表中的 9 个第三方 skill 当前仅带有各目录 `SKILL.md` frontmatter 中的 `license:` 字段，**缺失真实的作者署名、许可证正文链接与上游仓库来源 URL**（CC-BY / CC-BY-NC-SA 要求的 Attribution 要素尚不完整）；
> 2. 此外，`skills/academic-humanizer` 的 frontmatter 声明为 `MIT`，但仓库中**尚未包含 MIT 许可证全文与原始 copyright 声明**（MIT 许可证要求在再分发时保留版权声明和许可文本）。
>
> **公开发布 / 再分发前必须二选一完成处置（严禁凭记忆或猜测编造作者/URL）**：
> - **路径 A（补全真实授权信息）**：核实原始发布页面与版权声明，在下表逐项补齐经过核验的作者署名、上游 URL 与版权信息，并为 `academic-humanizer` 补入上游原始 MIT 许可证正文及 copyright 行；
> - **路径 B（剥离第三方目录仅保留自有 Apache-2.0 代码）**：若无法逐一核验上述 9 个目录的原始作者与完整 MIT 文本，则在公开发布或打包分发前从仓库中移除这 9 个第三方 skill 目录；`paper-orchestrator` 会依据硬规则 10 自动以「独立引擎 + 自有规则参考」优雅降级运行，核心流水线功能不受阻断。

以下目录从此前本地安装副本逐字节复制，许可证取自各自 `SKILL.md` frontmatter 的
`license:` 字段。它们的 frontmatter 中未包含 `homepage` / `source` 字段，故来源
链接与作者署名当前标为「待补充」。

| # | Skill 目录 | 许可证（frontmatter） | 来源链接 | 备注 |
|---|---|---|---|---|
| 1 | `skills/paper-writer/` | CC-BY-NC-SA-4.0 | 待补充 | 非商用；相同方式共享 |
| 2 | `skills/intro-drafter/` | CC-BY-NC-SA-4.0 | 待补充 | 非商用；相同方式共享 |
| 3 | `skills/deep-research/` | CC-BY-NC-SA-4.0 | 待补充 | 非商用；相同方式共享 |
| 4 | `skills/paper-polish/` | CC-BY-NC-SA-4.0 | 待补充 | 非商用；相同方式共享 |
| 5 | `skills/tech-paper-template/` | CC-BY-4.0 | 待补充 | 署名 |
| 6 | `skills/benchmark-paper-template/` | CC-BY-4.0 | 待补充 | 署名 |
| 7 | `skills/figure-designer/` | CC-BY-4.0 | 待补充 | 署名 |
| 8 | `skills/pre-submission-reviewer/` | CC-BY-4.0 | 待补充 | 署名 |
| 9 | `skills/academic-humanizer/` | MIT | 待补充 | 另含 `version: 0.3.3` |

许可证文本：

- CC-BY-4.0: https://creativecommons.org/licenses/by/4.0/
- CC-BY-NC-SA-4.0: https://creativecommons.org/licenses/by-nc-sa/4.0/
- MIT: https://opensource.org/license/mit

注意：4 个 CC-BY-NC-SA-4.0 skill 带有**非商用**条款。它们保持原许可证，
不因与本仓库的 Apache-2.0 代码放在同一目录树而改变；再分发或商用前请
自行核对相应条款。

## 2. CVPR 2025 作者套件（原样保留）

`skills/paper-orchestrator/templates/cvpr2025/` 下的六个文件
（`template.tex`、`preamble.tex`、`cvpr.sty`、`references.bib`、
`guidelines.md`、`ieeenat_fullname.bst`）来自 CVPR 作者套件，经上游
google-research/paper-orchestra 仓库再分发。它们不是 Google 的原创代码，
按会议/作者套件的原始条款保留，文件头原封不动。

- 上游再分发点：https://github.com/google-research/paper-orchestra/tree/d9bae997e793a015ed38bb1605be9eb58c00284f/templates/cvpr2025
- 作者套件来源：https://github.com/cvpr-org/author-kit
- 条款：按 CVPR 2025 作者套件随附的原始使用条款（`template.tex` 首行与
  `guidelines.md` 内说明）；本仓库不对该目录附加 Apache-2.0。

## 3. `ieeenat_fullname.bst`

`skills/paper-orchestrator/templates/cvpr2025/ieeenat_fullname.bst` 是
Patrick W. Daly 的 natbib  bibliography style。

- 版权：© 1993–2007 Patrick W. Daly
- 许可证：LaTeX Project Public License（LPPL），version 1 或任何更新版本
  （见文件头第 4、11–14 行）
- 许可证文本：https://www.latex-project.org/lppl/

## 4. 上游 PaperOrchestra 代码

搬入/改写的代码见 `NOTICE`：google-research/paper-orchestra @
`d9bae997e793a015ed38bb1605be9eb58c00284f`，Apache-2.0。