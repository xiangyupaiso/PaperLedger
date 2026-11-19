# THIRD_PARTY_NOTICES

本文件逐项列出本仓库再分发的第三方材料及其许可证。本仓库自己的代码与
文档（`skills/paper-orchestrator/` 中未标注来源的部分、`tools/`、`tests/`、
`docs/`）以 Apache-2.0 发布，见 `LICENSE` 与 `NOTICE`。

## 1. 九个第三方 skill（原样保留，未修改）

> **[!NOTE] 合规状态：溯源已补齐（2026-11-19）**
> 9 个第三方目录的作者、来源仓库与许可证全文均已核实补全：8 个来自
> [HKUSTDial/Supervisor-Skills](https://github.com/HKUSTDial/Supervisor-Skills)
> （© 2026 Yuyu Luo（methodology）及贡献者，香港科技大学（广州）数据智能与
> 分析实验室 DIAL Lab），1 个来自
> [AIScientists-Dev/academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer)
> （© 2026 AIScientists-Dev，MIT）。上游许可证全文逐字收录于
> [`docs/licenses/`](docs/licenses/)。
>
> **差异记录**：`tech-paper-template`、`benchmark-paper-template`、
> `figure-designer`、`pre-submission-reviewer` 四个目录的 `SKILL.md`
> frontmatter 写 `CC-BY-4.0`，而上游仓库整体 LICENSE 为 **CC-BY-NC-SA-4.0**。
> 本仓作为再分发方按更严格的 CC-BY-NC-SA-4.0 对待并遵守（非商用、相同
> 方式共享）。

以下目录从此前本地安装副本逐字节复制，未做任何修改；下表「生效许可证」
以上游仓库 LICENSE 为准。

| # | Skill 目录 | 生效许可证 | 作者 / 单位 | 来源 |
|---|---|---|---|---|
| 1 | `skills/paper-writer/` | CC-BY-NC-SA-4.0 | 骆昱宇 (Yuyu Luo) 及实验室成员 · HKUST(GZ) DIAL Lab | [Supervisor-Skills](https://github.com/HKUSTDial/Supervisor-Skills) |
| 2 | `skills/intro-drafter/` | CC-BY-NC-SA-4.0 | 同上 | 同上 |
| 3 | `skills/deep-research/` | CC-BY-NC-SA-4.0 | 同上 | 同上 |
| 4 | `skills/paper-polish/` | CC-BY-NC-SA-4.0 | 同上 | 同上 |
| 5 | `skills/tech-paper-template/` | CC-BY-NC-SA-4.0（frontmatter 标 CC-BY-4.0，从严处理） | 同上 | 同上 |
| 6 | `skills/benchmark-paper-template/` | CC-BY-NC-SA-4.0（同上） | 同上 | 同上 |
| 7 | `skills/figure-designer/` | CC-BY-NC-SA-4.0（同上） | 同上 | 同上 |
| 8 | `skills/pre-submission-reviewer/` | CC-BY-NC-SA-4.0（同上） | 同上 | 同上 |
| 9 | `skills/academic-humanizer/` | MIT | AIScientists-Dev 社区（谱系基于 [blader/humanizer](https://github.com/blader/humanizer)，MIT；标准参考 [koaeraser/ARMS](https://github.com/koaeraser/ARMS)） | [academic-humanizer](https://github.com/AIScientists-Dev/academic-humanizer)（v0.3.3） |

许可证文本：

- Supervisor-Skills 套件（CC-BY-NC-SA-4.0）：全文见
  [`docs/licenses/LICENSE-Supervisor-Skills.txt`](docs/licenses/LICENSE-Supervisor-Skills.txt)；
  法典页：https://creativecommons.org/licenses/by-nc-sa/4.0/
- academic-humanizer（MIT）：全文见
  [`docs/licenses/LICENSE-academic-humanizer.txt`](docs/licenses/LICENSE-academic-humanizer.txt)；
  参考：https://opensource.org/license/mit

注意：**整套 Supervisor-Skills（8 个目录）含非商用条款**。它们保持原许可
证，不因与本仓库的 Apache-2.0 代码放在同一目录树而改变；再分发或商用前
请自行核对相应条款。

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
