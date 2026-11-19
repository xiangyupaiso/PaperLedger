"""Adversarial training test for references/voice-calibration.md.

Three failure directions are attacked, per the calibration brief:

  A. NO FRIENDLY-FIRE -- honest forward-step sentences, scoped-then-reanchored
     patterns, and direct-evidence sentences (verify / "It is clear") must be
     judged CORRECT by the written guidance, never pressured into hedge
     templates. The machine audit must never GATE them (exit 0).
  B. NO OVERFIT -- three different-voice paragraphs (method results / analysis
     insight / dataset stats) rewritten under the guidance must NOT converge
     to one rhythm: hedge density differs, not every paragraph ends with a
     forward step, and the doc's own corpus counterexamples anchor the
     rationale.
  C. NO HYPE THROUGH -- unsupported categorical sentences and
     small-effect-big-adjective prose are judged inflation-side failures by
     the guidance; ledger_audit's ACTUAL gate behavior on the same cases is
     run (claims + sections fixtures) and must not contradict the guidance.

Method: the guidance judgments/rationales below are a RECORDED TRANSCRIPT of
a host-model pass that read voice-calibration.md fresh and applied it case by
case (the doc is re-read at module import; the judgments cite its principles
and counterexamples). The machine half runs the real ledger_audit CLI on
per-case fixtures and pins the report-only / four-signal-word semantics.
Pass criteria: A false-flags = 0; B rhythm divergence demonstrable; C hype
all caught by guidance AND doc/audit behavior consistent (no doc-encouraged
sentence gated, no audit-demanded direction forbidden by the doc).

The audit script's gate logic is NOT modified anywhere in this file.
"""
import json
import re
import subprocess
import sys
from pathlib import Path

import ledger_audit

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills" / "paper-orchestrator"
DOC_PATH = SKILL / "references" / "voice-calibration.md"
SCRIPT = Path(ledger_audit.__file__).resolve()

# Read the written guidance FRESH, as a host model would at stage 4 / stage 7.
DOC = DOC_PATH.read_text(encoding="utf-8")

SIGNAL_WORDS = ("may", "could", "potentially", "likely")


def _signal_count(text: str) -> int:
    return len(re.findall(r"\b(?:may|could|potentially|likely)\b", text, re.IGNORECASE))


# --------------------------------------------------------------------------
# A + C + X cases: recorded guidance judgments with rationales, and (where
# marked) a machine fixture. judgment in {correct, defensive_failure,
# inflation_failure}. "expect" pins the REAL audit behavior: exit code and
# the two report-only list sizes.
# --------------------------------------------------------------------------

_RESULTS_CSV = "capability,note\ndiverse trajectories,unseen RL environments\n"

CASES = [
    # ---------------- A. NO FRIENDLY-FIRE ----------------
    dict(
        id="A1", paper_type="analysis", domain="CV",
        text="下一步在多中心队列验证泛化性。",
        judgment="correct",
        rationale=(
            "原则 4/8：局限与展望的功能是划界+指路。这是诚实前瞻句（点名道姓的"
            "下一步：多中心队列、泛化性），不是防御语言，不得删除。刻度尺上它是"
            "'下一步'而非结果断言。机器侧：无信号词、无台账 → 进 overclaimed_weak"
            "报告，但只报告不 gate；处置=记录理由保留（前瞻计划句非结果断言），"
            "不得为消报告给它加 hedge。"
        ),
        fixture=dict(
            materials={}, claims=[],
            sections={"05_conclusion.tex": "下一步在多中心队列验证泛化性。\n"},
            expect=dict(exit=0, weakened=0, overclaimed=1),
        ),
    ),
    dict(
        id="A2", paper_type="method", domain="CV",
        text=(
            "We hope our findings and open sources can facilitate a more seamless "
            "integration of the substantial successes from the natural language "
            "processing domain into computer vision."
        ),
        judgment="correct",
        rationale=(
            "原则 8：结尾允许一次克制的希望（语料 01 §9 原句）。'We hope' 不是"
            "四个信号词之一，也不是防御性削弱——它出现在成就重述之后，强度与"
            "正文证据一致。机器侧：无信号词、无台账 → overclaimed_weak 报告项，"
            "不 gate；处置=记录理由保留（结尾希望句），不得当防御语言删除。"
        ),
        fixture=dict(
            materials={}, claims=[],
            sections={"05_conclusion.tex": (
                "We hope our findings and open sources can facilitate a more seamless "
                "integration of the substantial successes from the natural language "
                "processing domain into computer vision.\n"
            )},
            expect=dict(exit=0, weakened=0, overclaimed=1),
        ),
    ),
    dict(
        id="A3", paper_type="method", domain="CV",
        text=(
            "We believe Genie could one day be used as a foundation world model "
            "for training generalist agents. We show that the model can already "
            "generate diverse trajectories in unseen RL environments."
        ),
        judgment="correct",
        rationale=(
            "原则 2：scoped-then-reanchored 范本（语料 03 §3.3）。'could one day'"
            "标出愿景与证据的真实距离（两步外推），下一句立刻用 'can already' "
            "重锚定已演示的能力。hedge 是承重结构，不是焦虑。机器侧：第一句绑"
            "L1 且含 could → weakened_strong 报告项；处置方向=不确定性真实 → "
            "保留 hedge、把愿景边界记入台账（fix-ledger 方向），不是删 hedge；"
            "第二句直陈已证能力，无报告。全程不 gate。"
        ),
        fixture=dict(
            materials={"results.csv": _RESULTS_CSV},
            claims=[dict(
                id="A3", claim="The model can generate diverse trajectories in unseen RL environments.",
                origin="material:results.csv#L1-L2", evidence_level="L1", boundary="any",
            )],
            sections={"03_results.tex": (
                "% @claim:A3\n"
                "We believe Genie could one day be used as a foundation world model "
                "for training generalist agents.\n\n"
                "% @claim:A3\n"
                "We show that the model can already generate diverse trajectories "
                "in unseen RL environments.\n"
            )},
            expect=dict(exit=0, weakened=1, overclaimed=0),
        ),
    ),
    dict(
        id="A4", paper_type="method", domain="CV",
        text="These results verify the strong scalability of our model.",
        judgment="correct",
        rationale=(
            "这不是什么 #1 的语料反例（01 §5.2 'These results verify the strong "
            "scalability of VAR'）：证据是直接验证，许可直陈。不得被压成 "
            "'This suggests that…' 模板——hedge 由推理距离决定，不由段落槽位决定。"
            "机器侧：绑 L1、无信号词 → 两个报告列表皆空，不 gate。"
        ),
        fixture=dict(
            materials={"results.csv": _RESULTS_CSV},
            claims=[dict(
                id="A4", claim="The results verify the strong scalability of the model.",
                origin="material:results.csv#L1-L2", evidence_level="L1", boundary="any",
            )],
            sections={"03_results.tex": (
                "% @claim:A4\nThese results verify the strong scalability of our model.\n"
            )},
            expect=dict(exit=0, weakened=0, overclaimed=0),
        ),
    ),
    dict(
        id="A5", paper_type="analysis", domain="NLP",
        text=(
            "It is clear that the squeezing effect is mitigated, because the "
            "confidence of other responses all decays slower during DPO."
        ),
        judgment="correct",
        rationale=(
            "这不是什么 #1 的语料反例（06 §4.3）：理论预测 + 曲线双重许可，"
            "'It is clear' 是刻度精确而非膨胀。不得模板化为 'This suggests'。"
            "机器侧：绑 L1、无信号词 → 报告为空，不 gate。"
        ),
        fixture=dict(
            materials={"results.csv": _RESULTS_CSV},
            claims=[dict(
                id="A5", claim="The squeezing effect is mitigated under DPO.",
                origin="material:results.csv#L1-L2", evidence_level="L1", boundary="any",
            )],
            sections={"04_analysis.tex": (
                "% @claim:A5\n"
                "It is clear that the squeezing effect is mitigated, because the "
                "confidence of other responses all decays slower during DPO.\n"
            )},
            expect=dict(exit=0, weakened=0, overclaimed=0),
        ),
    ),
    dict(
        id="A6", paper_type="method", domain="NLP",
        text="Our 7B model achieved a state-of-the-art 51.8% on the MATH dataset.",
        judgment="correct",
        rationale=(
            "原则 1/5：已测结果用平直、主动、带数字的陈述句（语料 02 §3.2 同型）。"
            "永不 hedge 已测数字；强动词 + 精确数字匹配大幅定量增益。机器侧：数字"
            "51.8 在 L1 origin 区间逐字可查 → 数值 gate 通过；无信号词 → 报告为空。"
            "直陈已测结果与台账契约不冲突（数字仍须入账）。"
        ),
        fixture=dict(
            materials={"math.csv": "model,math\n7B,51.8\n"},
            claims=[dict(
                id="A6", claim="The 7B model achieved 51.8% on the MATH dataset.",
                origin="material:math.csv#L2", evidence_level="L1", boundary="any",
            )],
            sections={"03_results.tex": (
                "% @claim:A6\n"
                "Our 7B model achieved a state-of-the-art 51.8% on the MATH dataset.\n"
            )},
            expect=dict(exit=0, weakened=0, overclaimed=0),
        ),
    ),
    # ---------------- C. NO HYPE THROUGH ----------------
    dict(
        id="C1", paper_type="analysis", domain="NLP",
        text="Our method proves debate yields truth.",
        judgment="inflation_failure",
        rationale=(
            "原则 1 膨胀侧：两步外的理论极限用测量句语气说出（语料反例原型 "
            "'our method proves debate yields truth'）。正确刻度：相关性直陈 + "
            "理论外推显式分级（04 §3 'This provides weak evidence that…'）。"
            "机器侧：无台账、无信号词 → overclaimed_weak；处置=补证据或缩小主张。"
        ),
        fixture=dict(
            materials={}, claims=[],
            sections={"04_results.tex": "Our method proves debate yields truth.\n"},
            expect=dict(exit=0, weakened=0, overclaimed=1),
        ),
    ),
    dict(
        id="C2", paper_type="method", domain="CV",
        text="本方法彻底改变临床实践。",
        judgment="inflation_failure",
        rationale=(
            "原则 7 膨胀侧：结果层宏大修辞（'revolutionizes' 出现在实验段的中文"
            "对应物）。大胆只放在框架/愿景层且须与兑现证据匹配；临床实践改变是"
            "未验证的多步外推。机器侧：无台账、无信号词 → overclaimed_weak；"
            "处置=缩小主张到所测范围或补证据。"
        ),
        fixture=dict(
            materials={}, claims=[],
            sections={"04_results.tex": "本方法彻底改变临床实践。\n"},
            expect=dict(exit=0, weakened=0, overclaimed=1),
        ),
    ),
    dict(
        id="C3", paper_type="method", domain="NLP",
        text="Our remarkable breakthrough achieves a 0.2-point gain.",
        judgment="inflation_failure",
        rationale=(
            "原则 5 膨胀侧：小效应配大词（+0.2 说成 remarkable breakthrough；"
            "语料对照 02 §3.2 小效应用 'a certain degree of'）。机器侧：数字有 "
            "L1 支撑、无信号词 → 报告为空——四信号词审计管证据–信号词错配，"
            "管不了形容词强度；这正是'信号词只是输入不是判决'的分工：刻度尺"
            "（人/宿主判断）抓形容词–效应错配，机器抓台账–措辞错配，二者互补"
            "不矛盾。guidance 判膨胀侧，audit 沉默，均符合各自语义。"
        ),
        fixture=dict(
            materials={"delta.csv": "delta\n0.2\n"},
            claims=[dict(
                id="C3", claim="The method achieves a 0.2-point gain.",
                origin="material:delta.csv#L2", evidence_level="L1", boundary="any",
            )],
            sections={"03_results.tex": (
                "% @claim:C3\nOur remarkable breakthrough achieves a 0.2-point gain.\n"
            )},
            expect=dict(exit=0, weakened=0, overclaimed=0),
        ),
    ),
    dict(
        id="C4", paper_type="dataset", domain="CV",
        text="Our dataset solves text-to-image generation.",
        judgment="inflation_failure",
        rationale=(
            "原则 8 膨胀侧：结论宣称解决宏大问题，超出正文证据。数据集类的正确"
            "刻度（语料 08）：贡献动词 collect/contribute/demonstrate，模型自称 "
            "initial models，结论开具体的门（资源用法枚举）而非 'solves'。"
            "机器侧：无台账、无信号词 → overclaimed_weak；处置=缩小主张。"
        ),
        fixture=dict(
            materials={}, claims=[],
            sections={"05_conclusion.tex": "Our dataset solves text-to-image generation.\n"},
            expect=dict(exit=0, weakened=0, overclaimed=1),
        ),
    ),
    dict(
        id="C5", paper_type="method", domain="CV",
        text="Our method may potentially somewhat improve FID.",
        judgment="defensive_failure",
        rationale=(
            "原则 1 防御侧：给已测结果加缓冲（'may potentially somewhat improve "
            "FID'，语料中零例）。FID 增益是测到的，刻度读数应为直陈。机器侧："
            "绑 L1 且含 may/potentially → weakened_strong；处置=改肯定（直接陈述"
            "发现），与 guidance 方向一致。这是 doc 与 audit 同向捕获的对照案例。"
        ),
        fixture=dict(
            materials={"results.csv": _RESULTS_CSV},
            claims=[dict(
                id="C5", claim="Our method improves FID.",
                origin="material:results.csv#L1-L2", evidence_level="L1", boundary="any",
            )],
            sections={"03_results.tex": (
                "% @claim:C5\nOur method may potentially somewhat improve FID.\n"
            )},
            expect=dict(exit=0, weakened=1, overclaimed=0),
        ),
    ),
    # ---------------- X. canonical L3 deixis control ----------------
    dict(
        id="X1", paper_type="method", domain="NLP",
        text="Smith et al. (2023) addressed graph classification \\cite{smith2023}.",
        judgment="correct",
        rationale=(
            "刻度尺 + 台账契约：L3 题录证据恰好支持指称级断言，这就是该证据允许"
            "的强度——既不得膨胀成方法细节/性能数字，也不得防御性地再削弱。"
            "机器侧：canonical L3 deixis 豁免（related work、无数据数字、"
            "et al.+年份+指称动词+\\cite）→ 报告为空，不 gate。doc 不禁止该形式，"
            "audit 不要求削弱它。"
        ),
        fixture=dict(
            materials={},
            claims=[dict(
                id="X1", claim="Smith et al. (2023) addressed graph classification.",
                origin="retrieval:smith2023", evidence_level="L3", boundary="related_work_only",
            )],
            sections={"02_related.tex": (
                "% @claim:X1\n"
                "Smith et al. (2023) addressed graph classification \\cite{smith2023}.\n"
            )},
            expect=dict(exit=0, weakened=0, overclaimed=0),
        ),
    ),
]


# --------------------------------------------------------------------------
# B. NO OVERFIT -- three different-voice paragraphs, before/after applying the
# guidance. Recorded host-model outputs; the rationale cites the doc's own
# corpus counterexamples (01 §5.2 "verify", 06 §4.3 "It is clear", 03 abstract
# nearly hedge-free vs 04 explicit evidence grading).
# --------------------------------------------------------------------------

B_PARAGRAPHS = [
    dict(
        id="B1", paper_type="method", domain="CV",
        before=(
            "Our method may potentially somewhat improve FID. The results could "
            "suggest that the approach is likely better than baselines. "
            "Feasibility remains doubtful."
        ),
        after=(
            "Our method improves FID from 18.65 to 1.73 with 20x faster inference. "
            "These results establish the model as potentially a more efficient and "
            "scalable alternative to diffusion transformers; whether this holds at "
            "larger scales may depend on the tokenizer."
        ),
        rationale=(
            "原则 1/5：已测 FID 增益直陈（防御侧缓冲全删，语料零例）；跨基准一般化"
            "与未触碰组件（tokenizer）保留校准 hedge（01 §5.1 'potentially' 同型）。"
            "结尾停在一般化边界，不接前瞻句——方法类结果段的自信峰值在数字。"
        ),
    ),
    dict(
        id="B2", paper_type="analysis", domain="NLP",
        before=(
            "Debate proves that truth always wins. Our results are amazing and "
            "show the method works perfectly."
        ),
        after=(
            "We note a strong correlation between debater persuasiveness and judge "
            "accuracy. This provides weak evidence that under optimal play debate "
            "produces truthful information; the mechanism may involve judges "
            "directing debates towards their key uncertainties. For debates in "
            "QuALITY, telling the truth is easier than lying."
        ),
        rationale=(
            "原则 1/2：相关性直陈、理论外推显式分级（04 §3 'weak evidence' 同型），"
            "机制解释推一步用 may，范围随 hedge 给出（'For debates in QuALITY'）。"
            "结尾是 scoped 断言而非前瞻句——分析类贡献是论证，重锚定在论证层面。"
            "反例依据：04 显式分级 vs 03 摘要几乎无 hedge，两者都对（这不是 hedge 配额）。"
        ),
    ),
    dict(
        id="B3", paper_type="dataset", domain="CV",
        before=(
            "We propose a novel paradigm that revolutionizes text-to-image "
            "evaluation. Our perfect dataset solves the problem."
        ),
        after=(
            "Around 25% of annotations show perfect annotator agreement and around "
            "85% show good agreement. The multi-head version of our model performs "
            "worse than ResNet-50, but the augmented-prompt version outperforms it. "
            "We hope RichHF-18K and our initial models inspire three promising "
            "directions: RL reward signals, weighted maps, and exploiting misaligned "
            "sequences."
        ),
        rationale=(
            "原则 5/8：自信峰值在标注统计（08 §3.4 同型）；不利数字与有利数字同样"
            "平直（08 §4.2.2 自家模型输给基线直说）；模型自称 initial models，结尾"
            "一次克制的希望 + 点名道姓的资源用法清单。零四信号词——数据集类的"
            "统计直陈不需要 hedge（反例依据：03 摘要几乎不含 hedge 同样获奖）。"
        ),
    ),
]

B_RATIONALE_COUNTEREXAMPLES = (
    "语料反例库（doc '这不是什么' #1/#2）：01 §5.2 'These results verify the strong "
    "scalability of VAR'（直接验证许可直陈）；06 §4.3 'It is clear that the squeezing "
    "effect is mitigated'（理论+曲线双重许可）；03 摘要几乎不含 hedge 而 04 显式 "
    "'weak evidence' 分级——两者都对，不存在每段配额。三段输出因此保留各自语域。"
)


# --------------------------------------------------------------------------
# machine runner: real ledger_audit CLI on per-case fixtures
# --------------------------------------------------------------------------

def _run_audit(tmp_path, fixture):
    m = tmp_path / "materials"
    m.mkdir()
    for name, content in fixture["materials"].items():
        (m / name).write_text(content, encoding="utf-8")
    sec = tmp_path / "sections"
    sec.mkdir()
    for name, content in fixture["sections"].items():
        (sec / name).write_text(content, encoding="utf-8")
    claims = tmp_path / "claims.jsonl"
    claims.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in fixture["claims"]),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [sys.executable, "-I", "-X", "utf8", str(SCRIPT), str(claims),
         "--materials", str(m), "--sections", str(sec), "--strength-report"],
        capture_output=True, text=True, encoding="utf-8",
    )
    lines = proc.stdout.splitlines()
    h = next(i for i, l in enumerate(lines) if l.startswith("STRENGTH MISMATCH REPORT"))
    v = next(i for i, l in enumerate(lines) if re.match(r"^\d+ violation\(s\)$", l))
    report = json.loads("\n".join(lines[h + 1 : v]))
    return proc.returncode, report, proc.stdout


# --------------------------------------------------------------------------
# guidance invariants (the written model must carry its own guards)
# --------------------------------------------------------------------------

def test_doc_read_fresh_and_carries_scale_and_guards():
    assert "断言强度 = 离证据的距离" in DOC
    assert "这不是什么" in DOC and "这不是句型模板" in DOC
    assert "诚实前瞻句" in DOC and "不得被当作防御语言删除" in DOC
    assert "信号词只是输入" in DOC and "不是判决" in DOC
    assert "只报告" in DOC and "不影响退出码" in DOC
    assert "逐条处置" in DOC
    # the scale never exempts the ledger contract (numbers still gate)
    assert "数值一致性" in DOC


def test_signal_set_is_exactly_four_and_not_a_ban_list():
    assert ledger_audit.HEDGE_WORDS == SIGNAL_WORDS  # gate logic untouched
    assert "恰为四个" in DOC
    for w in SIGNAL_WORDS:
        assert w in DOC
    assert "不是禁词" in DOC
    for normal in ("limitations", "suggest", "indicate"):
        assert normal in DOC  # named as normal verbs, not penalties


# --------------------------------------------------------------------------
# A. NO FRIENDLY-FIRE
# --------------------------------------------------------------------------

def test_A_guidance_never_friendly_fires():
    a_cases = [c for c in CASES if c["id"].startswith("A")]
    assert len(a_cases) >= 5
    false_flags = [c["id"] for c in a_cases if c["judgment"] != "correct"]
    assert false_flags == [], f"friendly-fire on honest prose: {false_flags}"


def test_A_machine_never_gates_honest_prose(tmp_path):
    for c in CASES:
        if not c["id"].startswith("A") or "fixture" not in c:
            continue
        case_dir = tmp_path / c["id"]
        case_dir.mkdir()
        rc, report, _ = _run_audit(case_dir, c["fixture"])
        assert rc == 0, f"{c['id']}: honest prose gated by audit (exit {rc})"


def test_A_forward_steps_not_hedge_targets():
    # the doc explicitly protects honest forward steps and end-of-paper hope
    assert "下一步在" in DOC  # the canonical forward-step shape is named
    assert "We hope" in DOC


# --------------------------------------------------------------------------
# B. NO OVERFIT
# --------------------------------------------------------------------------

def test_B_rhythm_divergence():
    afters = [p["after"] for p in B_PARAGRAPHS]
    densities = [_signal_count(a) for a in afters]
    # hedge density differs across the three voices (2 / 1 / 0)
    assert len(set(densities)) == 3, f"hedge densities converged: {densities}"
    # not every paragraph ends with a forward step: exactly one does (B3)
    forward_endings = [
        a for a in afters
        if re.search(r"(We hope|下一步|future (work|directions)|inspire)", a.split(". ")[-1])
    ]
    assert len(forward_endings) == 1
    # no template convergence: no paragraph ends on the "This suggests" slot
    for a in afters:
        assert not a.rstrip().endswith("This suggests that.")
        assert "This suggests that" not in a.split(". ")[-1]
    # openings differ in voice (numeric-led / observation-led / stats-led)
    first_words = [a.split()[0] for a in afters]
    assert len(set(first_words)) == 3
    # before/after actually changed (the guidance was applied, not ignored)
    for p in B_PARAGRAPHS:
        assert p["before"] != p["after"]


def test_B_rationale_cites_corpus_counterexamples():
    joined = " ".join(p["rationale"] for p in B_PARAGRAPHS) + B_RATIONALE_COUNTEREXAMPLES
    assert "verify" in joined and "It is clear" in joined
    assert "03" in joined and "04" in joined
    # and those counterexamples really live in the doc's anti-overfit section
    anti = DOC.split("这不是什么", 1)[1]
    assert "verify" in anti and "It is clear" in anti


def test_B_defensive_buffer_removed_but_calibrated_hedge_kept():
    b1 = B_PARAGRAPHS[0]["after"]
    assert "may potentially somewhat" not in b1  # defensive stack gone
    assert "potentially" in b1  # calibrated generalization hedge kept
    b3 = B_PARAGRAPHS[2]["after"]
    assert _signal_count(b3) == 0  # dataset stats voice: no hedge quota
    assert "performs worse" in b3  # unfavorable number stays plain


# --------------------------------------------------------------------------
# C. NO HYPE THROUGH + doc/audit consistency
# --------------------------------------------------------------------------

def test_C_guidance_catches_all_hype():
    hype = [c for c in CASES if c["id"] in ("C1", "C2", "C3", "C4")]
    missed = [c["id"] for c in hype if c["judgment"] != "inflation_failure"]
    assert missed == [], f"hype passed guidance: {missed}"
    c5 = next(c for c in CASES if c["id"] == "C5")
    assert c5["judgment"] == "defensive_failure"  # two-sided: defensive also caught


def test_C_machine_audit_behavior_matches_expectations(tmp_path):
    for c in CASES:
        if "fixture" not in c:
            continue
        case_dir = tmp_path / c["id"]
        case_dir.mkdir()
        rc, report, _ = _run_audit(case_dir, c["fixture"])
        exp = c["fixture"]["expect"]
        assert rc == exp["exit"], f"{c['id']}: exit {rc} != {exp['exit']}"
        assert len(report["weakened_strong"]) == exp["weakened"], c["id"]
        assert len(report["overclaimed_weak"]) == exp["overclaimed"], c["id"]


def test_C_audit_is_report_only_and_offers_both_directions(tmp_path):
    for c in CASES:
        if "fixture" not in c:
            continue
        case_dir = tmp_path / c["id"]
        case_dir.mkdir()
        rc, report, stdout = _run_audit(case_dir, c["fixture"])
        assert "report-only, non-gating" in stdout
        for item in report["weakened_strong"] + report["overclaimed_weak"]:
            assert "Author decides" in item["advice"]
            assert " OR " in item["advice"]  # both directions offered


def test_C_doc_and_audit_do_not_contradict(tmp_path):
    # (1) no sentence the doc encourages is GATED by the audit: every
    #     guidance-CORRECT case exits 0 (checked above); re-assert here on the
    #     subset that carries numbers or hedges (the risky shapes).
    for cid in ("A3", "A6", "X1"):
        c = next(x for x in CASES if x["id"] == cid)
        case_dir = tmp_path / ("con_" + cid)
        case_dir.mkdir()
        rc, _, _ = _run_audit(case_dir, c["fixture"])
        assert rc == 0, f"doc-encouraged shape {cid} gated"
    # (2) no direction the audit demands is forbidden by the doc: the audit's
    #     two advice directions (upgrade-to-assertive / fix-ledger-shrink) are
    #     both present in the doc's disposition guidance.
    assert "改肯定" in DOC
    assert "缩小主张" in DOC
    assert "改台账" in DOC or "补证据" in DOC
    # (3) the doc never tells the host to silence the report by adding hedges
    assert "不得为消报告" in DOC or "不得为消 flag" in DOC
    # (4) weakened_strong disposition is calibrated assertion, not hedge deletion
    assert "不是删" in DOC or "不是删除所有 hedge" in DOC
    # (5) overclaimed_weak disposition is evidence-or-shrink, not word counts
    assert "词频" in DOC and "不是判决" in DOC


def test_case_coverage_brief_requirements():
    assert len(CASES) + len(B_PARAGRAPHS) >= 12
    types = {c["paper_type"] for c in CASES} | {p["paper_type"] for p in B_PARAGRAPHS}
    domains = {c["domain"] for c in CASES} | {p["domain"] for p in B_PARAGRAPHS}
    assert types == {"method", "analysis", "dataset"}
    assert domains == {"CV", "NLP"}