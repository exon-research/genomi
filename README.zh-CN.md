<p align="center">
  <img src="assets/genomi-logo.png" alt="Genomi logo" width="160">
  <br>
  <strong>读懂自己，从基因开始。</strong>
  <br>
  <a href="https://www.genomiagent.com/">官网</a>
  ·
  <a href="https://raw.githubusercontent.com/exon-research/genomi/main/INSTALL_FOR_AGENTS.md">安装指南</a>
  ·
  <a href="README.md">English</a>
</p>

<p align="center">
  <a href="https://www.python.org/downloads/"><img alt="Python" src="https://img.shields.io/badge/python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white&labelColor=111827"></a>
  <a href="https://modelcontextprotocol.io/"><img alt="MCP" src="https://img.shields.io/badge/MCP-agent--native-7C3AED?style=flat-square&labelColor=111827"></a>
  <a href="SKILL.md"><img alt="Skill" src="https://img.shields.io/badge/skill-agent--ready-0E7490?style=flat-square&labelColor=111827"></a>
  <a href="#privacy"><img alt="Local-first" src="https://img.shields.io/badge/privacy-local--first-15803D?style=flat-square&labelColor=111827"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-64748B?style=flat-square&labelColor=111827"></a>
</p>

# 基诺米 Genomi

> 我会秃头吗？我的 DNA 对阿尔茨海默病风险怎么说？布洛芬对我为什么没用？

这些问题，归根到底都是 DNA 的事。营养、用药、睡眠、运动、遗传性状、某些疾病的风险——背后那套蛋白质、酶、受体、通路怎么搭，全是它在拍板。DNA 写不了你的命，但论贴近你自己，没有哪份数据比得过它。

可它的体量也大到离谱。光碱基对就有 30 亿，基因 2 万多个，每个人身上还压着几百万个已知变异。医生装不下，实验室装不下，谁都装不下。

好在 AI 终于强到能接住这种规模的活。基因组正好是给这种新能力准备的题——头一回，我们手上的工具，跟得上它真实的尺度。

基诺米（Genomi）就是为这件事写的。它是一套本地基因组学运行框架（Harness），Claude Code、Codex、OpenClaw、Hermes，以及任何能讲 MCP 的 host 都接得上。Genomi 给 agent 留一块私有工作区：变异躺在本地的 Active Genome Index 里，公共遗传学证据随手可查，它记得你查过什么，DNA 的问题它能写成有据可查的报告。基因组不出你的机器。活儿，agent 干。

## TL;DR

连 TL;DR 都嫌长？直接把下面这段贴给 agent：

```text
Hey please read this and tell me why Genomi is different from other AI
agent harnesses. Why is this actually useful for understanding my DNA privately?
https://raw.githubusercontent.com/exon-research/genomi/main/llms-full.txt
```

## 直接装就完事了

让 agent 帮你装。一条指令贴过去，回答几个问题，剩下的它自己搞定：

```text
Install and configure Genomi by following the instructions here:
https://raw.githubusercontent.com/exon-research/genomi/main/INSTALL_FOR_AGENTS.md
```

安装指南里写了依赖检查、库的挑选、MCP 注册、可选的基因组源导入，以及最后的校验。

## 各家 agent 都能用

Genomi 不挑聊天 app。只要 host 会调 MCP 工具、跑得起本地命令、或者能加载已装好的 skill，就接得上同一份本地 Genomi。

| Host 家族 | 怎么接 |
| --- | --- |
| Claude Code | MCP server + Genomi skills |
| Codex CLI | MCP server + Genomi skill |
| OpenCode、OpenClaw、Hermes | MCP server，能加 skill 的就加 |
| Cursor、Gemini CLI、Cline、Goose、Roo Code、Windsurf、Claude Desktop | MCP server |
| 其他支持 MCP 的 host | `genomi serve` 走 stdio |

本地一个 Genomi home 就够装下全部家当——公共库、Active Genome Index 记录、score 缓存、journal 全在里面。会话访问该走的审批规则照走，但底下那块证据空间，是几个 host agent 一起共享的。

## 想手动装也行

不想让 agent 代劳？自己来——clone、装、配 MCP，三步。脚本干的就是这套流程。
[agent 安装指南](INSTALL_FOR_AGENTS.md) 是权威；下面这版要是和它对不上，听它的。

1. **拉源码。**

   ```bash
   git clone git@github.com:exon-research/genomi.git ~/.genomi/genomi
   cd ~/.genomi/genomi
   ```

2. **装包和公共库。** 默认参考库一次全拉，省得 Genomi 答到一半发现缺数据。只有磁盘、带宽、时间紧的时候，才从下面这几个小一点的 purpose 里挑一个：`common-questions`、`medication-response`、`ancestry-context`、`sequence-and-regions`、`cell-and-tissue`、`everything`、`setup-only`。

   ```bash
   export GENOMI_HOME=~/.genomi
   python3 scripts/install_for_agents.py --libraries everything
   ```

   装完会在 `$GENOMI_HOME/bin/genomi` 留一个稳定入口。想在任意 shell 里直接敲 `genomi`，就把它加进 PATH：

   ```bash
   export PATH="$GENOMI_HOME/bin:$PATH"
   ```

   以后要刷新已有的 checkout：

   ```bash
   "$GENOMI_HOME/bin/genomi" update
   ```

   它会把本地 Genomi 的 checkout 和运行时资源一起更新。支持 skill 的 host 里用 `/genomi update`，Codex 里换成 `$genomi update`。源码变了的话，记得重启 host agent，重新加载 MCP server。

3. **把 MCP server 注册给 host agent。**

   ```json
   {
     "mcpServers": {
       "genomi": {
         "command": "/absolute/path/to/GENOMI_HOME/bin/genomi",
         "args": ["serve"]
       }
     }
   }
   ```

   源码 checkout、还没生成稳定 shim 的时候，用这个：

   ```json
   {
     "mcpServers": {
       "genomi": {
         "command": "bash",
         "args": ["-lc", "cd /path/to/genomi && PYTHONPATH=src python3 -m genomi serve"]
       }
     }
   }
   ```

   重新加载 host 的 MCP server。host 不会自动读项目说明的，把它指到 `AGENTS.md`。要用 URL 喂的话，`llms.txt` 是精简地图，`llms-full.txt` 是把所有参考内联进单文件的完整版。

## 可以这样问它

接好之后，跟 agent 这么说话就行。Codex 里把 `/genomi` 换成 `$genomi`。先问点轻松的：

> `/genomi` 我的 DNA 对阿尔茨海默病风险怎么说？
>
> `/genomi` 我有没有早发心脏病的风险？
>
> `/genomi` 我会秃头吗？
>
> `/genomi` 我是快代谢还是慢代谢？
>
> `/genomi` 糖尿病要不要担心？
>
> `/genomi` 我乳糖不耐受吗？
>
> `/genomi` 我喝酒到底好不好？

再扔点重的：

> `/genomi` 准备开始吃 SSRI。带我过一遍我的 CYP2D6 和 CYP2C19 状态，主要指南对剂量怎么说，哪些是初步证据，哪些是真的可以落地的。

> `/genomi` 把我吃的每种药都做一遍药物基因组学回顾。指南背书的剂量调整放最前，证据弱的信号放第二位，超出范围的明说。

> `/genomi` 根据我的 HPO 词条给我做一页纸的罕见病初筛。候选基因按证据排序，每一条标引用，并告诉我在交给医生之前还差什么。

或者干脆全交出去：

> `/genomi decode`

一条命令。agent 把全部能力都对你的基因组扫一遍——变异、ClinVar、药物基因组学、祖源、多基因评分、营养基因组学，连同你的调查日志——把结果做成一个自包含的 dashboard，挂在 localhost 上。浏览器打开就看。

在这些回答底下撑着的，是 2 万多个人类基因、你文件里几百万条基因型观察，加上 Genomi 替 agent 接好的那一批公共证据源——它说的话，落得到证据上。

## Genomi 给你的是什么

| 层 | 你拿到什么 |
| --- | --- |
| Active Genome Index | 本地可查的台账：等位基因、合子性、质量、深度、过滤标记，再加上来自原始基因组的可调用性信息。 |
| Evidence Library | 一组聚焦工具：变异、ClinVar、GWAS、HPO、药物基因组学、祖源、PRS、序列。 |
| Journal | 连续的工作日志：你查过什么、什么是重点、哪条证据撑住了它。 |
| Skills | 给 agent 看的说明书：怎么路由问题、什么时候要审批、哪些先验来源不能丢、答案怎么讲清楚。 |

### 把自己的基因组带进来

DNA 文件在哪儿，Genomi 就在哪儿读。磁盘上任何一份 VCF 或 gVCF——临床导出的、研究 callset、只要合规范——指过去就行。后面整条流水线无论文件来源是哪，都走同一份 Active Genome Index。

主流的消费级 DTC 厂商也原生支持。账户里导出来什么样，原样递给 Genomi，它自己会认：

- **23andMe**、**AncestryDNA**、**MyHeritage**、**FamilyTreeDNA**（Family Finder）、**Living DNA**——原始基因型文本、zip、`.csv.gz` 都行。
- **Nebula Genomics**、**Dante Labs**、**Sequencing.com**——它们交付的 VCF 会被认出来，并打上来源厂商的标签。
- **Nebula / Dante / Sequencing.com 的 FASTQ**——双端原始 reads 在本地比对（长读 minimap2，短读 bwa-mem2），排序之后走同一条 BAM → 衍生 VCF 的通路。`wgs-alignment` 这个 install purpose 会把两个比对器一起拉下来。

### 还没自己的 DNA 文件？拿公开数据先试

手头还没基因组、但想看看 Genomi 能干嘛，去 [Personal Genome Project — Harvard Medical School](https://my.pgp-hms.org/public_genetic_data)。那儿放着真实参与者的真实消费级 DNA 交付件，上面列的每家厂商都覆盖。随便挑一位，把 Genomi 指过去，开始问。不送自己去测序的前提下，这是最干净的一种试水方式。

顺便说，Genomi 之所以能原生支持那么多厂商，也多亏了这份 PGP-HMS 数据集。每个检测器、每个奇怪的列、每段头部 banner、每份消费级阵列和厂商标签 VCF 的测试 fixture，都拿真实参与者的导出文件对过。MyHeritage、FamilyTreeDNA、Living DNA、Nebula、Dante、Sequencing.com 的原生支持能做出来，是因为 PGP-HMS 用一份宽松的再利用许可，把真实样本免费公开了——这是开放消费基因组学领域里默默的一笔贡献，Genomi 直接受益。

基因组数据是可选的。没有的话，Genomi 也能答纯公共的遗传学问题。

## 为什么要做这个

我做 Genomi，是想让 AI 去接以前接不了的事，做到以前做不到的规模。DNA 正是这种事。

人类基因组的体量太大。实验室一辈子盯一个基因。报告把几千条变异压成一行字。再厉害的医生，也没法把 2 万多个基因、几百万条基因型观察全塞进脑子里。这不是用不用心的问题，是规模的问题。而规模的问题，正好是 AI 终于能去顶一下的那一类。

自己想用，也想给家人用。但前提是它得诚实——证据要扎实，默认本地跑，agent 把推理过程亮出来，不能凭记忆瞎编。

原始基因组留在你机器上。Genomi 是工作空间，不是静态 PDF 报告。答案要么追得到来源，要么就不配叫答案。整套东西从第一行代码起就是冲着 agent + MCP 设计的，不是后补的补丁。

通用 AI 当然能讲遗传学。但话一旦落到某个具体变异、某份基因组文件、某条指南、某项覆盖度限制上，它就不该靠猜。需要证据的地方，Genomi 把工具递给 agent；剩下的地方，它不挡道。

## Genomi 能陪你探索什么

Genomi 不是一份静态报告，是一块私有工作区。agent 拿着它，可以在基因组的不同角落把问题问得更准。

- 性状和日常反应：乳糖、咖啡因、酒精、味觉、营养、睡眠、运动这类很个人的事。
- 用药反应：哪些基因和变异可能影响你身体怎么处理某种药。
- 携带者和遗传风险：精确变异核查、ClinVar 断言、基因与疾病的证据。
- 常见性状研究：复杂性状的 GWAS 和已发表的评分背景，边界讲清楚。
- 罕见病和表型评估：HPO 词条、基因-疾病有效性、有来源背书的候选基因比较。
- 祖源参考面板背景：定性的相似度和 overlap 检查，不是种族或族裔预测。
- 报告和记忆：带引用的 Markdown 报告，再加一份 journal，记下你查过什么、哪些是重点、哪些还得跟进。

## 答案怎么保持诚实

DNA 的问题往往很私人、很乱、很容易讲过头。Genomi 把不同来源的证据分开摆，让 agent 自己把推理过程亮出来。

- 你的基因组证据：基因型、合子性、深度、质量、过滤标记、精确的等位基因观察值、可调用性。
- 公共证据：ClinVar 断言、人群频率、GWAS 记录、基因-疾病有效性、表型注释、来源版本。
- 已审阅的发现：针对某个具体目标或问题写下的、有来源背书的小范围笔记。
- agent 的记忆：观察、决策、未解的问题，以及回到证据的链接。
- 个人背景：可选的表型、用药、家族史，或者你愿意提供的其他信息。

不同证据有时会指向不同方向。Genomi 帮 agent 把它们摆在一起对比，而不是假装某一个数据库就是真相。

## 隐私

最敏感的那部分数据，Genomi 一直留在你身边。

- 原始基因组从头到尾都在你的机器上。
- 个人基因组文件就地解析成 Active Genome Index，agent 只查当前这一问用得着的变异。
- 之前生成过的 Active Genome Index，再要拿来读时，Genomi 会先问你这一会话同不同意——除非它本来就是配置好的默认用户。
- 公共查询只送出具体目标：rsID、基因、药名、疾病、指南问题。
- Journal 是 agent 自己写下的记忆，不算证据。
- 项目级 journal 在 v1 里直接拒收私有 / 样本证据的链接。
- 记忆导出默认就把私有证据链接抹掉，除非你点头同意。

## Genomi 接的可信来源

答案得扎在真实证据上，不能靠感觉。所以 Genomi 接的，全是可信、能核对的数据库和基因组学工具。一部分装在本地，私有、可复现地查；剩下的走在线。

本地参考库：

- [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/docs/downloads/)
  GRCh38/GRCh37 VCF 缓存，用来做变异解读。
- [HPO](https://obophenotype.github.io/human-phenotype-ontology/annotations/)
  表型基因和疾病注释文件。
- [GenCC](https://search.thegencc.org/download) 基因-疾病有效性记录。
- [UCSC Genome Browser downloads](https://hgdownload.soe.ucsc.edu/downloads.html)
  hg38/hg19 参考 FASTA，用在序列和可调用性流程里。
- [GENCODE](https://www.gencodegenes.org/human/) GRCh38/GRCh37 转录本注释。
- [ENCODE SCREEN](https://www.encodeproject.org/software/screen/) cCRE 注释。
- [PanglaoDB](https://panglaodb.se/markers.html?cell_type=%27all_cells%27) 和
  [CellMarker](http://bio-bigdata.hrbmu.edu.cn/CellMarker/) 人类细胞类型标志物表。
- [1000 Genomes 30x GRCh38](https://www.internationalgenome.org/data-portal/data-collections/30x-grch38.html)
  祖源参考面板。
- [PharmCAT](https://pharmcat.org/) 一体化 JAR，做广覆盖的药物基因组学 calling。
- 启用之后会接上 [MSigDB Hallmark](https://www.gsea-msigdb.org/gsea/msigdb/human/collections.jsp#H)
  通路合集。

在线公共来源：

- [gnomAD](https://gnomad.broadinstitute.org/) 人群频率查询。
- [PGS Catalog](https://www.pgscatalog.org/) 评分元数据和打分文件。
- [ClinPGx](https://www.clinpgx.org/) 药物基因组学指南、注释、标签背景。
- [PGxDB](https://pgx-db.org/) 药物-基因-变异关联记录。
- FDA [pharmacogenomic biomarker](https://www.fda.gov/drugs/science-and-research-drugs/table-pharmacogenomic-biomarkers-drug-labeling/)
  和 [pharmacogenetic association](https://www.fda.gov/medical-devices/precision-medicine/table-pharmacogenetic-associations) 表。
- 支持的地方还会接 [KEGG](https://www.kegg.jp/kegg/pathway.html)、
  [Reactome](https://reactome.org/)、
  [Human Protein Atlas](https://www.proteinatlas.org/)。

## 工作原理

Genomi 对外只露一组很小的基础 MCP 工具，再加一个 dispatcher，用来调专用的基因组学工具。host agent 负责跟你聊；扎实的查询、Active Genome Index 的创建、证据检索、报告组装，全归 Genomi。

1. **把 agent 通过 MCP 接进来。** 配置片段见上面 [想手动装也行](#想手动装也行) 那一节。

2. **想要个人化背景，就给 agent 一份基因组文件。** Genomi 会把它解析成 Active Genome Index——本地的查询底座，覆盖变异、合子性、质量、深度、过滤标记、可调用性。纯公共问题跳过这步即可。

   ```json
   {
     "tool": "genomi.parse_source",
     "params": {
       "source": "<genome-file>"
     }
   }
   ```

3. **开问。** agent 会挑能搞定问题的最小那个 Genomi 操作来调。`genomi.parse_source`、`genomi.describe_context`、`journal.append_entry` 这类基础操作是直接 MCP 工具；capability 操作走 `genomi.invoke`，前提是 agent 先读过对应的 `skills/<capability>/SKILL.md`。

   ```json
   {
     "tool": "genomi.invoke",
     "params": {
       "tool": "variant.resolve",
       "params": {
         "rsid": "rs429358"
       }
     }
   }
   ```

4. **顺手检查证据、默认值和边界。** 返回里会带结构化证据、来源覆盖范围，假设有意义的地方会标 `defaults_applied`。库没装、外部源不可用、后台作业还在跑的情况，会显式返回状态，不会当成反证。

5. **让它记下来。** Journal 收下观察、决策、未解的问题，以及回到证据的链接。

## 用 Genomi 做点东西

Genomi 是开源的。它写给那些想让 AI agent 老老实实做基因组学的人——本地优先，证据为本，知道自己几斤几两。拿去探索、解释、记笔记、出报告，原始基因组一行不用外传。

## 状态

> [!WARNING]
> **实验阶段。仅作研究和参考用途。**
> Genomi 不是诊断设备，也不能替代医生的临床判断。
> 原始基因组按设计就在你机器上——但结果跑出来之后你怎么往外发，
> 那是你的事。

schema、工具表面、capability 布局都还会动。要在升级之间保稳定，自己 pin 一个 commit。

## 许可证

Genomi 以 [Apache License 2.0](LICENSE) 发布。

## 引用

如果你在研究、出版物、报告、benchmark、demo、衍生工具里用到了 Genomi，请用 [CITATION.cff](CITATION.cff) 引用，并在合适的地方致谢。

```bibtex
@software{genomi2026,
  title = {Genomi: A Local Genomics Harness for AI Agents},
  author = {Zeng, Mingde and Zhou, Hongjian and Liu, Fenglin and Wu, Jinge},
  year = {2026},
  url = {https://www.genomiagent.com/},
  version = {0.1.0}
}
```

## 贡献

欢迎来提 issue 和 pull request。报 bug 时麻烦带上三样东西：基因组源是什么格式（VCF / gVCF / 23andMe / AncestryDNA / …）、跑了哪个操作、agent 收到的那份结构化报错信封——一般就够复现了。
