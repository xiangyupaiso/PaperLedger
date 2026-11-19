# voice-calibration — 语料校准的声音模型（阶段 4 起草 / 阶段 7 处置）

## 插槽声明（voice pack slot）

> **本文件是一份可替换的声音包实例（VOICE PACK）。** 出厂版在 2023–2025 年
> CS 领域最佳论文语料上校准（语料清单见下方出处）；校准的是文风倾向，不是
> 论文内容。本 skill 的核心流水线与学科无关：阶段、检查点、台账与脚本都
> 不动，**换领域只换声音包**。
>
> **其他领域按同一文档契约自训自己的声音包**：选语料 → 研读 → 校准 →
> 对抗测试 → 替换本文件。接口 = 本文档契约，四部分缺一不可：
> ①刻度尺核心（断言强度 = 离证据的距离）；②带两侧失败模式的若干条倾向；
> ③「这不是什么」反模板声明（防空转、防过拟合）；④按类型变异（校准不
> 抹平贡献类型差异）。替换后本文件以外的任何规则都不需要改。

> **语料出处**：8 篇 CCF-A 最佳论文（检索窗口 2023–2025，获奖年份 2024–2025），
> 2026-11 由一次独立 study pass 蒸馏为倾向性参考。英文引文均为短句/短语
> （fair use），标注论文编号与章节。其中 3 篇（01 VAR、03 Genie、05 Safety
> Alignment）为 arXiv 版（v2/v1/v1），措辞可能与最终获奖版略有出入。
> 本文件是**正面声音模型**：给起草（阶段 4）与错配处置（阶段 7）提供刻度，
> 不是规则清单；与 `voice-rules.md` 的裁决规则配套，不新增流程规则。
>
> 语料清单：01 Visual Autoregressive Modeling（NeurIPS 2024 Best Paper，
> 方法/CV）；02 RHO-1: Not All Tokens Are What You Need（NeurIPS 2024
> runner-up，方法/NLP）；03 Genie: Generative Interactive Environments
> （ICML 2024 Best Paper，方法/世界模型）；04 Debating with More Persuasive
> LLMs Leads to More Truthful Answers（ICML 2024 Best Paper，分析/NLP）；
> 05 Safety Alignment Should Be Made More Than Just a Few Tokens Deep
> （ICLR 2025 Outstanding，分析）；06 Learning Dynamics of LLM Finetuning
> （ICLR 2025 Outstanding，分析/理论）；07 Generative Image Dynamics
> （CVPR 2024 Best Paper，方法/CV）；08 Rich Human Feedback for Text-to-Image
> Generation（CVPR 2024 Best Paper，数据集/CV）。

## 〇、刻度尺核心

**断言强度 = 离证据的距离。** 自信与谨慎不是两种文风的切换，而是同一根
刻度尺上的读数：

- **测量到的结果永不 hedge**：平直、主动、带数字的陈述句。语料 8 篇中
  没有一处把 hedge 加在已测数字本身上。
- **两步外的推理永不用测量语气**：推一步（机制、解释）用 suggests / may；
  推两步（理论极限、宏大类比）显式给证据分级（weak evidence /
  hypothetical / initially）。触发 hedge 的是真实存在的推理缺口，不是焦虑。

语料总体感觉：一位既兴奋又诚实的合作者——对测到的东西直言不讳，对外推
明码标价，对没做到的具体交代（16 帧记忆、1FPS、≤7B），然后立刻指出下一步
从哪里走。舒服且严谨的来源不是句子漂亮，而是每个断言的强度恰好等于证据
允许它拥有的强度。

## 一、八条倾向（每条附两侧失败模式）

每条是**倾向 + 为什么有效**，不是情境规则。两侧失败模式按语料实际形态
命名：防御侧（把已确立的说弱/说空）与膨胀侧（把未确立的说强/说满）。

### 原则 1｜断言强度随离证据的距离衰减

不随句子位置或重要性衰减。WHY：读者信任来自"强度=证据"的精确对应。
例：01 摘要 "improving Fréchet inception distance (FID) from 18.65 to
1.73 … with 20× faster inference speed"（测到的，直陈）；02 §3.5 "This
may suggest that the model first optimizes tokens with a larger learnable
space"（机制，推一步）；04 §3 "This provides weak evidence that under
optimal play debate produces truthful information"（理论，推两步；同句的
相关性本身直陈）。分级可以是词汇、动词（verify / explain / shed light on）
或范围副词（initially, often）——01 §5.1 硬证据之后仍写 "potentially a
more efficient and scalable model"，因为跨基准一般化超出所测范围。
**两侧失败模式**：防御侧——给已测结果加缓冲（"may potentially somewhat
improve FID"），语料零例；膨胀侧——两步外推用测量语气（"proves debate
yields truth"），或小效应配大形容词。

### 原则 2｜hedge 是承重结构：标出边界，随后重新锚定

好的 hedge 携带范围信息（哪个数据集、哪类攻击、哪个规模），随后几乎总跟
一个重锚定，把读者拉回已确立的贡献。WHY：局限因此吞不没贡献——贡献被
重新陈述在它真正成立的层面上。例：04 "This suggests that, for debates in
QuALITY, telling the truth is easier than lying"；03 §3.3 "We believe
Genie could one day be used as a foundation world model … In Figure 14 we
show that the model can already be used for generating diverse
trajectories"；05 结论 "may not be a perfect defense … but they are an
initial step … Fundamentally, our results are primarily to support our
argument"。优先权声明配礼貌性认识限定（"To our knowledge, this is the
first time…"）——标记"无法穷尽文献"的真实不确定性，不是削弱结果。
**两侧失败模式**：防御侧——hedge 只传递情绪不带范围，段末停在悬空让步上
没有重锚定；膨胀侧——无范围全称断言（"makes alignment robust"）。

### 原则 3｜一次只走一个被许可的步子，许可证摆在明处

观察→断言→含义的每一步由前一步或外部证据（图、引文、推导、明说的假设）
许可。WHY：没有需要读者自行补跳的缝隙，也没有未出示证据就起跳的断言。
例：06 §4.3 理论预测 → "It is clear that the squeezing effect is
mitigated, because …"（曲线验证）→ 胜率表；05 §4 把假设明确标记为假设再
设计实验检验（"we posit that: If … then we should be able to …"）。步子
粒度随段落功能变化，连接手段多样，设问与真实惊讶（04 "This is
surprising, as …"）让读者感到思考者在场。
**两侧失败模式**：喘不上气侧（缺口侧）——大断言间无可见许可（"X is
powerful. Therefore we propose Y."）；机械侧（过拟合侧）——每段强塞
"证据→断言→含义"三连拍、连接词千篇一律，语料零例。

### 原则 4｜局限平直、具体、与贡献同高，然后指路

真实局限不藏脚注、不道歉包裹，以报告成功的同一语气给出，带具体参数或
失败情形，随后接建设性动作。WHY：局限段的功能是划界+指路，不是免责。
例：03 §5 "Genie currently operates around 1FPS … Still, we believe Genie
opens up vast potential"；07 §8 "it can fail to model non-oscillating
motions … this may be resolved by using learned motion bases"；02 附录 C
"we have only verified … on smaller models (<=7B parameters)"，随后把更大
规模写成开放研究问题而非可行性忏悔。语料找不到一句空泛的 "more research
is needed"。
**两侧失败模式**：免责侧（防御侧）——局限堆成道歉式免责声明；推销侧
（膨胀侧）——全文无局限或只有空泛一句，语料零例。

### 原则 5｜词强度匹配效应大小，不利数字同样平直

大幅定量增益用强动词+精确数字；定性结果用克制形容词（decent, plausible）；
指标→质量的代理推理用 suggest；小幅增益用小词（a certain degree of）。
不利/零结果平直报告+（常为试探性的）解释。WHY：坏消息也直说，好消息才
值得信——对称性是信任来源。例：01 §6 "decent results" / "plausible
content" 对照摘要的 FID 强断言；08 §4.2.2 "the multi-head version of our
model performs worse than ResNet-50, but … The main reason might be …"；
04 零结果 + 真实惊讶。
**两侧失败模式**：膨胀侧——小效应配大词（+0.2 说成 remarkable
breakthrough）、代理指标当质量本身；防御侧——大效应配小词（16.5% 增益说成
"some improvement"）、不利结果埋附录或被动语态模糊。

### 原则 6｜一个具体锚点承载抽象概念

尽早引入一个读者拿得住的具体对象（场景、例子、比喻、图），全文复用它
指代抽象机制。WHY：读者每步推理都有参照物，严谨才显得舒服——跨全部 8 篇
的最强共性之一。例：05 的肯定前缀对话场景与 shallow/deep 空间比喻；06 的
MNIST '4'→'9' 与 pull up/push down/squeezing 力学比喻三节复用；07 "candles
will flicker in certain ways, trees will sway"；02 图 2 的 token 标注例子。
锚点一两个，复用而非堆砌，是工作性的（用来做推理）不是装饰性的。
**两侧失败模式**：悬空侧（防御侧的艰涩形态）——全程抽象名词操作无参照物；
装饰侧（膨胀侧的修辞形态）——每段硬配俏皮比喻、互相矛盾或喧宾夺主。

### 原则 7｜大胆在框架层，礼貌在优先权层，结果层只留数字

标题/引言可以很强（甚至因果断言、"第一次"断言），但大胆有固定位置：
框架/愿景/优先权；结果句保持数字化平直。WHY：强度与兑现证据匹配时，
强断言是诚实的概括而非炒作。例：04 标题即因果断言，摘要收尾回到 "encouraging
empirical evidence for the viability"；01 "for the first time" 由表 1 支撑，
正文加 "To our knowledge"；对先行工作平静精确让功（05 "share a similar
insight"；04 直说先行负面结果并解释差异）。宏大修辞出现在引言与图注，
不出现在结果段。
**两侧失败模式**：膨胀侧——结果层也宏大（"revolutionizes image
generation" 进实验段）、优先权不限定且与证据不符；焦虑侧（防御侧）——真实
首创性说成 "we merely extend"、定位含糊。

### 原则 8｜结论在实际展示的层面重述成就，再开一扇具体的门

成就重述（强度与正文一致，常带 initially / promising 成熟度标记）→ 点名
道姓的下一步（更好的 tokenizer、debate 做 RL 微调、更多模型家族的数据），
不是泛泛 "future work will address this"。结尾允许一次克制的自豪或希望。
WHY：门的具体程度暴露作者对领域的真实把握；重述不失真则全文刻度闭环。
例：01 §9 "initially verified … We hope our findings and open sources can
facilitate …"；04 "a promising approach for scalable oversight"（不是
"solves"）；08 "We hope RichHF-18K and our initial models inspire quests …"。
**两侧失败模式**：防御侧——结论把已确立的东西重新 hedge 一遍，读完像什么
都没做成；膨胀侧——宣称开创领域/解决宏大问题，或下一步只有空泛一句。

## 二、这不是什么（反过拟合声明）

1. **这不是句型模板。** 典型误用：把原则 1 读成"每个结果段必须以 This
   suggests that… 结尾"。语料内部就有反例：01 §5.2 "These results
   **verify** the strong scalability of VAR"（直接验证，许可直陈）；
   06 §4.3 "**It is clear that** the squeezing effect is mitigated"
   （理论预测+曲线双重许可）。hedge 由推理距离决定，不由段落槽位决定。
   把任何原则变成"每段必有的句子成分"，产出的就是怪异腔调。
2. **这不是 hedge 配额。** 03 的摘要几乎不含 hedge（能力断言都有演示
   支撑），04 显式给证据分级（weak evidence）。两者都对。不存在"每段至少
   一个 may"或"摘要不许出现 suggest"的规则。
3. **这不是表面光洁度标准。** 最佳论文里真实存在语法瑕疵：01 §7 "a way
   more better FID"；02 §3.2 "We evalute base models"。声音 = 校准 + 逻辑，
   不是无瑕句法。不必模仿这些错误——要点是别把"每句都 polished 得像模板"
   当目标，那会牺牲直接性。
4. **这不是结构规则。** 04 的 "Insight N: <断言句>" 小标题、05 的设问式
   章节标题都是单篇/局部选择，不是共性原则；01/02/07 用普通陈述式标题同样
   获奖。不要强制任何一种。
5. **这不是"永远谦虚"或"永远大胆"。** 语料横跨两种语域，甚至在同一摘要内
   切换（06）。要学的是刻度尺，不是某个固定读数。
6. **单篇模式已按约束降级为变异**：例如"Insight 编号"（仅 04）、"设问章节
   标题"（05 为主）、"脚注里的手柄类比"（仅 03）均未列为原则。

## 三、按类型变异（校准不要抹平差异）

**方法类（01、02、03、07）**：自信峰值在基准数字与对比表；hedge 集中在
一般化边界（跨基准/规模/任务）与未触碰组件。局限典型形态：正交组件未优化、
规模未验证、速度/记忆、表示频率范围；未来工作=同一机器的延伸。定性证据
占比高，定性形容词刻意克制（decent / plausible），静态图不足则诚实外包
视频/补充材料。

**分析类（04、05、06）**：贡献是论证/框架而非工件，hedge 集中在解释性
断言且常显式分级（hypothetical / weak evidence）。独有动作：把证据强度当
对象来谈论；结论重锚定到"论证成立"而非"产品可用"（05 是范本）。局限典型
形态：类比与设置的边界。理论+实证混合体按证据类型分层：可推导部分用
demonstrate，经验解释部分用 may / shed light on（06）。

**数据集类（08）**：自信峰值在标注统计与一致性；模型自称 initial models，
应用自称 "some instances" / "three promising ways"。局限典型形态：标注噪声
与覆盖范围；未来工作=资源用法的枚举清单。贡献动词是 collect / contribute /
demonstrate，而非 propose a novel paradigm。

**CV vs NLP 是弱趋势不是规则**：CV 偏感知锚点与定性图证（指标→质量用
suggest）；NLP/分析偏基准差值、token 级机制与显式分级。会议差异远小于类型
差异。**纯类型是理想型：校准应跟随你的贡献实际是什么**（论证、工件、还是
资源），而不是跟随投稿类别标签（08 本身就是数据集+模型+应用三合一）。

## 四、对审计错配的处置指引（阶段 7，配 voice-rules.md §5）

`ledger_audit.py --strength-report` 的信号词**恰为四个**：may / could /
potentially / likely。信号词只是输入，不是判决：命中与否都不直接决定句子
对错；`limitations` / `suggest` / `indicate` 是正常学术动词，不是禁词。
报告**只报告、不影响退出码**；错配非空仍须逐条处置（记录理由）后才能签字。
处置方向由刻度尺校准，不由词频决定：

- **weakened_strong 标记你**（L1/L2 强证据 + 信号词）：修复方向是**按刻度尺
  校准断言**——若不确定性是焦虑性的，改肯定，直接陈述已测发现；若不确定性
  是真实的（如 A3 型愿景句 "could one day"），保留 hedge、把边界记入台账或
  缩小主张（fix-ledger 方向）。**不是删除所有 hedge**：把承重 hedge 删光与
  把已测结果说弱是同一种刻度失真。
- **overclaimed_weak 标记你**（L3/L4 或无台账 + 肯定断言）：补证据或缩小
  主张（改台账方向）——降到指称级、补强证据、或删句；台账升级到 L1/L2 后
  才可改肯定。
  刻度尺决定方向，不是词数。canonical L3 指称（"X et al. (Year) addressed
  Y \cite{…}"）恰是题录证据支持的强度，审计有窄豁免，不必再削弱。
- **诚实前瞻句不是 hedge**："下一步在X验证Y"、结尾的 "We hope …"、
  scoped-then-reanchored 的后半句，是划界+指路动作，
  **不得被当作防御语言删除**，也不得被润色压成免责声明。若此类句子进了
  overclaimed_weak 报告（无台账的计划/希望句常被扫到），处置=记录理由保留
  （它是前瞻计划句，非结果断言，不在刻度尺的结果端）；不得为消报告给它加
  hedge 蒙混。
- **刻度尺不豁免台账契约**：已测结果的直陈仍须数字入账——数值一致性审计
  是 gate，"不加 hedge"不等于"不入账"，也不允许加 hedge 蒙混数值违规。

一句话：审计修的是证据与措辞的错配；刻度尺告诉你错配朝哪个方向修。
两者同向，词频永远只是报告项。