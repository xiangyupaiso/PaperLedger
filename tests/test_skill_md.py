"""Task 7: SKILL.md + orchestration references (the harness-neutral payload).

Content contract from the task brief:
  - frontmatter yaml-parseable, keys subset of {name, description, license,
    compatibility}; compatibility declares claude-code / codex / antigravity
  - seven stage names + the seven key strings present in SKILL.md
  - every scripts/*.py path referenced in the payload exists on disk
  - NEGATIVE: no ``superpowers`` (case-insensitive), no ``Gemini`` / ``OpenAI``
    anywhere in SKILL.md or references/. (vendor-notices.md quotes lowercase
    upstream model identifiers as provenance data -- reviewed in Tasks 2/5 --
    so the brand check uses the brief's exact capitalised strings; the five
    Task-7 files are additionally checked case-insensitively.)
  - SKILL.md < 400 lines
"""
import re
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "paper-orchestrator"
SKILL_MD = SKILL / "SKILL.md"
REFS = SKILL / "references"

ALLOWED_KEYS = {"name", "description", "license", "compatibility"}
STAGE_NAMES = [
    "材料入账",
    "大纲 JSON",
    "文献缝合",
    "分节成稿",
    "图表",
    "LaTeX 装配",
    "自评审",
]
KEY_STRINGS = [
    "% >>> paper-orchestrator: sections",
    "% @claim:",
    "Rung",
    "evidence_level",
    "to_cites",
    "booktabs",
    "XOR",
]
SCRIPT_NAMES = [
    "lit_search.py",
    "plot_from_logs.py",
    "latex_compose.py",
    "ledger_audit.py",
]
VENDOR_COMMIT = "d9bae997e793a015ed38bb1605be9eb58c00284f"
# the five files Task 7 authors (stricter lowercase brand check applies)
TASK7_FILES = [
    SKILL_MD,
    REFS / "stage-playbook.md",
    REFS / "voice-rules.md",
    REFS / "reflection-prompts.md",
    REFS / "plot-style-notes.md",
]


def _text() -> str:
    return SKILL_MD.read_text(encoding="utf-8")


def _frontmatter() -> dict:
    text = _text()
    m = re.match(r"\A---\n(.*?)\n---\n", text, re.DOTALL)
    assert m, "SKILL.md must open with a --- frontmatter block"
    data = yaml.safe_load(m.group(1))
    assert isinstance(data, dict)
    return data


# --------------------------------------------------------------- frontmatter


def test_skill_md_exists():
    assert SKILL_MD.is_file(), f"missing {SKILL_MD}"


def test_frontmatter_yaml_parseable_key_subset():
    fm = _frontmatter()
    assert set(fm) <= ALLOWED_KEYS, f"extra frontmatter keys: {set(fm) - ALLOWED_KEYS}"
    assert fm["name"] == "paper-orchestrator"
    assert isinstance(fm["description"], str) and fm["description"].strip()


def test_frontmatter_compatibility_three_hosts():
    fm = _frontmatter()
    compat = fm["compatibility"]
    values = compat.split() if isinstance(compat, str) else list(compat)
    assert set(values) == {"claude-code", "codex", "antigravity"}


def test_description_carries_triggers():
    desc = _frontmatter()["description"]
    assert "paper-orchestrator" in desc
    assert "流水线" in desc
    # stage names double as trigger phrases
    assert any(name in desc for name in STAGE_NAMES)


# ------------------------------------------------------------- body contract


def test_seven_stage_names_present():
    text = _text()
    for name in STAGE_NAMES:
        assert name in text, f"stage name missing: {name}"


def test_key_strings_present():
    text = _text()
    for s in KEY_STRINGS:
        assert s in text, f"key string missing: {s}"


def test_line_budget_under_400():
    assert len(_text().splitlines()) < 400


def test_all_four_scripts_referenced_and_exist():
    text = _text()
    for name in SCRIPT_NAMES:
        assert f"scripts/{name}" in text, f"SKILL.md never references {name}"
    # every scripts/*.py path mentioned anywhere in the payload must exist
    payload = [SKILL_MD, *sorted(REFS.glob("*.md"))]
    seen = set()
    for path in payload:
        for rel in re.findall(r"scripts/[A-Za-z0-9_]+\.py", path.read_text(encoding="utf-8")):
            seen.add(rel)
            assert (SKILL / rel).is_file(), f"{path.name} references missing {rel}"
    assert seen, "no script paths found at all"


def test_independent_verification_step_explicit():
    text = _text()
    assert "独立上下文" in text
    assert "Rung 1" in text and "Rung 2" in text
    assert "披露" in text  # degradation is disclosed
    # canonical semantics referenced by path, not restated wholesale
    assert "paper-writer/references/evidence-discipline.md" in text
    assert "paper-writer/references/verification-ladder.md" in text
    assert "L1 full text / data" not in text
    assert "L4 model memory" not in text


def test_xor_polish_rule_fixed():
    text = _text()
    assert "paper-polish" in text and "academic-humanizer" in text
    assert "二选一" in text
    assert "叠加" in text  # 禁止两者叠加调用
    assert "中式英语" in text  # decision condition written down


def test_strength_report_disposition_before_signoff():
    text = _text()
    assert "--strength-report" in text
    assert "处置" in text and "签字" in text


def test_adjudication_table_in_skill_md():
    text = _text()
    assert "orchestrator" in text
    assert "pre-submission-reviewer" in text
    assert "最严" in text  # 引用资格归验证阶梯最严者


# ---------------------------------------------------------- harness neutrality


def test_payload_harness_neutral():
    for path in [SKILL_MD, *sorted(REFS.glob("*.md"))]:
        text = path.read_text(encoding="utf-8")
        assert "superpowers" not in text.lower(), path.name
        assert "Gemini" not in text, path.name
        assert "OpenAI" not in text, path.name
    for path in TASK7_FILES:
        text = path.read_text(encoding="utf-8").lower()
        assert "gemini" not in text, path.name
        assert "openai" not in text, path.name


# ------------------------------------------------------------------ references


def test_stage_playbook_contract():
    doc = (REFS / "stage-playbook.md").read_text(encoding="utf-8")
    for name in STAGE_NAMES:
        assert name in doc, f"playbook missing stage {name}"
    assert "从阶段" in doc  # single-stage entry protocol
    assert "已有产物" in doc
    assert "% >>> paper-orchestrator: sections" in doc
    assert "--numeric-map" in doc
    assert "停" in doc  # exit protocol


def test_entry_prerequisites_never_demand_own_outputs():
    # Round 1 fix: entering stage N requires PRIOR stages' outputs only.
    # sections/ is stage 4's output (required only when resuming mid-stage-4);
    # specs/ is stage 5's output (user-supplied spec optional, never required).
    doc = (REFS / "stage-playbook.md").read_text(encoding="utf-8")
    assert "4/6/7 起要有" not in doc  # old conflated prerequisite wording
    assert "前序阶段" in doc  # the principle is stated
    assert "中途续跑" in doc  # sections/ only when resuming mid-stage-4
    assert "不作前置" in doc  # specs/ explicitly not a stage-5 prerequisite
    # controller ruling: author-supplied references have a stated ledger path
    for path in (REFS / "stage-playbook.md", SKILL_MD):
        text = path.read_text(encoding="utf-8")
        assert "作者自带的参考文献" in text, path.name
        assert "assign_citekeys" in text, path.name
        assert "material:<bib文件路径>#L<行>" in text, path.name


def test_voice_rules_contract():
    doc = (REFS / "voice-rules.md").read_text(encoding="utf-8")
    assert "一个声音" in doc and "一本账" in doc
    # four adjudication rows
    assert "流程" in doc and "orchestrator" in doc
    assert "拥有者" in doc
    assert "引用资格" in doc and "最严" in doc
    assert "评审结论" in doc and "pre-submission-reviewer" in doc
    # dual-list strength audit, no budget numbers
    assert "weakened_strong" in doc and "overclaimed_weak" in doc
    assert "HEDGE_BUDGET" not in doc
    assert "quota" not in doc.lower()
    for word in ("limitations", "suggest", "indicate"):
        assert word in doc  # named as normal verbs, not penalties
    for word in ("may", "could", "potentially", "likely"):
        assert word in doc
    assert "paper-writer/references/evidence-discipline.md" in doc
    assert "paper-writer/references/verification-ladder.md" in doc


def test_voice_rules_signal_words_inputs_not_verdicts():
    doc = (REFS / "voice-rules.md").read_text(encoding="utf-8")
    assert "不是判决" in doc  # signal words are inputs, not verdicts
    assert "voice-calibration.md" in doc  # disposition calibrated by the scale
    assert "诚实前瞻句" in doc  # honest forward steps are not hedge targets


def test_playbook_stage7_forward_step_and_measured_result_guard():
    doc = (REFS / "stage-playbook.md").read_text(encoding="utf-8")
    assert "诚实前瞻" in doc  # no honest forward-step flattened into disclaimer
    assert "柔化" in doc  # no measured result softened by polish


def test_reflection_prompts_archive():
    doc = (REFS / "reflection-prompts.md").read_text(encoding="utf-8")
    assert VENDOR_COMMIT in doc
    assert "Apache" in doc  # prompt archives KEEP Apache attribution
    # provenance: every archived upstream file is named
    for upstream in (
        "methods/prompts/content_refinement_agent.py",
        "methods/prompts/outline_agent.py",
        "autoraters/prompts/lit_review_quality_prompts.py",
        "autoraters/prompts/sxs_quality_prompts.py",
    ):
        assert upstream in doc, f"missing provenance for {upstream}"
    # characteristic text of each archived prompt survived
    for marker in (
        "REFLECTION ITERATION",
        "Rebuttal via Revision",
        "plotting_plan",
        "ANTI-INFLATION",
        "Side-by-Side",
        "Overall",
    ):
        assert marker in doc, f"archive lost prompt text: {marker}"
    # round 1 hardening: the limitation-sentence note carries an explicit
    # instantiation instruction next to the fenced block
    assert "实例化本模板时删除或以套件规则替换该句" in doc


def test_plot_style_notes_filled():
    doc = (REFS / "plot-style-notes.md").read_text(encoding="utf-8")
    assert "Placeholder" not in doc
    assert "Okabe-Ito" in doc
    assert "booktabs" in doc
    assert "9pt" in doc  # >=9pt in-figure type
    assert "矢量" in doc or "vector" in doc.lower()
    assert VENDOR_COMMIT in doc
    assert "paper_banana_utils.py" in doc

# ------------------------------------------------- voice-calibration payload

VOICE_CAL = REFS / "voice-calibration.md"
VOICE_CAL_HEADLINES = [
    "断言强度随离证据的距离衰减",
    "hedge 是承重结构",
    "一次只走一个被许可的步子",
    "局限平直、具体、与贡献同高",
    "词强度匹配效应大小",
    "一个具体锚点承载抽象概念",
    "大胆在框架层，礼貌在优先权层",
    "结论在实际展示的层面重述成就",
]


def test_voice_calibration_exists_with_scale_core():
    assert VOICE_CAL.is_file(), f"missing {VOICE_CAL}"
    doc = VOICE_CAL.read_text(encoding="utf-8")
    assert "刻度尺" in doc
    assert "断言强度 = 离证据的距离" in doc  # the core scale, verbatim
    # the two iron rules of the scale
    assert "已测" in doc or "测量到" in doc
    assert "两步" in doc  # two-step inference never in measurement voice


def test_voice_calibration_eight_principles_two_sided():
    doc = VOICE_CAL.read_text(encoding="utf-8")
    for h in VOICE_CAL_HEADLINES:
        assert h in doc, f"principle headline missing: {h}"
    assert doc.count("两侧失败模式") >= 8  # every principle keeps both sides
    assert "防御侧" in doc and "膨胀侧" in doc


def test_voice_calibration_anti_overfit_section_intact():
    doc = VOICE_CAL.read_text(encoding="utf-8")
    assert "这不是什么" in doc
    for marker in (
        "这不是句型模板",
        "这不是 hedge 配额",
        "这不是表面光洁度标准",
        "这不是结构规则",
        "永远谦虚",
        "永远大胆",
        "单篇模式",
        "降级为变异",
    ):
        assert marker in doc, f"anti-overfit marker missing: {marker}"
    # the corpus' own counterexamples survive (anti-template guarantee)
    assert "verify" in doc and "It is clear" in doc


def test_voice_calibration_type_variation_kept():
    doc = VOICE_CAL.read_text(encoding="utf-8")
    assert "按类型变异" in doc or "按论文类型" in doc
    for t in ("方法类", "分析类", "数据集类"):
        assert t in doc, f"type-variation missing: {t}"
    assert "贡献实际是什么" in doc  # follow the actual contribution, not the label


def test_voice_calibration_audit_disposition_guidance():
    doc = VOICE_CAL.read_text(encoding="utf-8")
    assert "对审计错配的处置指引" in doc
    assert "weakened_strong" in doc and "overclaimed_weak" in doc
    assert "诚实前瞻句" in doc
    assert "不是 hedge" in doc
    assert "不得被当作防御语言删除" in doc
    assert "信号词只是输入" in doc and "不是判决" in doc
    assert "逐条处置" in doc  # never tells the host to ignore the report


def test_voice_calibration_provenance_header():
    doc = VOICE_CAL.read_text(encoding="utf-8")
    assert "CCF-A" in doc
    assert "2023" in doc and "2025" in doc
    assert "2026-11" in doc  # distilled by a study pass
    assert "fair use" in doc
    assert "arXiv" in doc  # 3 papers were arXiv versions, disclosed
    for venue in ("NeurIPS", "ICML", "ICLR", "CVPR"):
        assert venue in doc


def test_skill_md_wires_voice_calibration_both_stages():
    text = _text()
    assert text.count("references/voice-calibration.md") >= 2  # stage 4 + stage 7


def test_voice_calibration_harness_neutral_strict():
    text = VOICE_CAL.read_text(encoding="utf-8").lower()
    for brand in ("superpowers", "gemini", "openai"):
        assert brand not in text


# -------------------------------------------- cartridge: voice pack + degradation


def test_skill_md_declares_voice_pack_slot():
    text = _text()
    assert "声音包插槽" in text  # the slot is declared in SKILL.md
    assert "references/voice-calibration.md" in text  # the slot lives here
    assert "替换" in text  # swapping the pack is supported
    assert "其他任何规则" in text  # ... and changes nothing else
    assert "CS" in text  # shipped instance is the CS-calibrated pack


def test_skill_md_missing_sibling_skill_degrades():
    text = _text()
    assert "兄弟 skill" in text
    assert "能力提供者" in text  # stages name siblings as providers
    assert "由宿主模型直接承担" in text  # host model does the stage itself
    assert "死锁" in text  # the pipeline never dead-ends on a missing skill
    # same checkpoint/ledger/audit rules still apply
    assert "检查点、台账与审计规则不变" in text


def test_references_degradation_lines():
    rules = (REFS / "voice-rules.md").read_text(encoding="utf-8")
    assert "声音包插槽" in rules  # voice guidance source = the slot
    assert "最佳学术判断" in rules  # degrades to host model's judgment
    playbook = (REFS / "stage-playbook.md").read_text(encoding="utf-8")
    assert "缺同名 skill 由宿主直接承担" in playbook


def test_voice_calibration_slot_banner():
    doc = VOICE_CAL.read_text(encoding="utf-8")
    assert "插槽声明" in doc
    assert "VOICE PACK" in doc  # this file IS a pack instance
    assert "字段无关" in doc or "学科无关" in doc  # pipeline is field-agnostic
    assert "CS" in doc  # calibrated on 2023-2025 CS best papers
    for step in ("选语料", "研读", "校准", "对抗测试", "替换本文件"):
        assert step in doc, f"training recipe step missing: {step}"
    for contract in ("刻度尺核心", "两侧失败模式", "这不是什么", "按类型变异"):
        assert contract in doc, f"pack interface section missing: {contract}"


def test_playbook_fix_wave_seams():
    """Final-review fix wave: F4 placeholder checkpoint, F5 tables convention,
    F6 numeric-map covers all citekey rows + pre-compose verification,
    F7 post-polish re-audit before sign-off."""
    doc = (REFS / "stage-playbook.md").read_text(encoding="utf-8")
    # F4: stage-6 checkpoint directs title/author/paperID update from outline.json
    assert r"\title{My Title}" in doc
    assert r"\paperID{12345678}" in doc
    assert "占位符" in doc
    # F5: tables paste convention, markers OUTSIDE tabular, no \input{tables/...}
    assert "直接粘贴进对应章节" in doc
    assert r"\input{tables/" in doc
    assert "之外" in doc
    # F5: tables/*.tex listed as a stage-6 entry prerequisite (stage-5 output)
    assert "tables/*.tex（阶段 4/5 产出）" in doc
    # F6: number ALL citekey-bearing rows (retrieval + author material:<bib>)
    assert "所有带 citekey 的行" in doc
    assert "装配前核对" in doc
    assert "绝不猜" in doc
    # F7: re-run ledger_audit --strength-report AFTER polish, BEFORE sign-off
    assert "润色之后、终稿签字之前" in doc
    assert "重跑" in doc
