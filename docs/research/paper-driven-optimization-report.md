# 前沿论文驱动的优化研究报告

**日期**: 2026-09-12（第二轮扩充）· **方法**: liuxiang 检索精读 + kueiku RICE 排序
**研究对象**: weaver（新闻聚合 → 知识图谱 → LLM pipeline）

## 一、精读论文清单（8 篇）

| 论文 | 来源 | 精读文件 |
|---|---|---|
| LightRAG: Simple and Fast RAG (Guo et al., EMNLP 2025 Findings) | ACL Anthology | `docs/research/papers/lightrag.md` |
| LLMLingua-2: Data Distillation for Task-Agnostic Prompt Compression (Pan et al., ACL 2024 Findings) | ACL Anthology | `docs/research/papers/llmlingua2.md` |
| Match, Compare, or Select? LLMs for Entity Matching (Wang et al., COLING 2025, ComEM) | arXiv 2405.16884（网络受阻，经检索补证方法与结论） | — |
| **TERAG: Token-Efficient Graph-Based RAG (Cornell & HKUST, 2509.18667)** | arXiv HTML via webReader | `docs/research/papers/terag_notes.md` |
| **Towards Practical GraphRAG / KET-RAG 线 (2507.03226)** | arXiv HTML via webReader | `docs/research/papers/ketrag_notes.md` |
| **KARMA: Multi-Agent LLMs for KG Enrichment (2502.06472, ~70 引用)** | arXiv HTML via webReader | `docs/research/papers/karma_notes.md` |
| **GPTCache: Semantic Cache for LLM Interactions (2304.03679)** | arXiv via webReader | `docs/research/papers/gptcache_notes.md` |

第二轮覆盖 2025-2026 最新前沿：token 高效 GraphRAG（TERAG/KET-RAG）、多 agent KG 增强（KARMA）、语义缓存（GPTCache）。检索渠道：liuxiang 多源（OpenAlex/ACL）+ WebSearch 前沿清单 + webReader 全文（本地网络阻断 arXiv，经服务端通路绕行）。

## 一.5 第二轮新发现（关键增量）

### TERAG——比 LightRAG 更激进的"零建图 LLM"路线
单遍 NER 抽取（纯文本输出，无 JSON）+ **非 LLM 建图**（概念共现边）+ PPR 检索。建图输出 token 比主流方法少 **88-97%**（HotpotQA: 562,827 vs LightRAG 5,862,363 vs AutoSchemaKG 4,915,796），2Wiki EM 51.2 ≈ GraphRAG 51.4（token 仅 3-11%）。**性能主导因素是 NER 精度**——weaver 已有 spaCy/GLiNER 本地 NER，天然适配。

### KET-RAG 线——94% 性能 @ 10-20% LLM 索引覆盖
只对高价值子集（关键词排序选出的 top 文档 + 核心实体邻域）用 LLM 建索引，长尾走纯文本向量+BM25。LLM 索引覆盖率 10% 时收益已接近饱和。为方案 A 提供"渐进迁移"依据：**不必全量 LightRAG 化，影子层从 10-20% 覆盖起步**。

### KARMA——多 agent 增量融合
对齐 agent 的"一次调用携带 top-N 候选 + 冲突类型提示"是 token 效率主要来源，直接支撑方案 C 的 prompt 设计；增量只触碰局部子图的原则适用于 CommunityUpdateTrigger。

### GPTCache——语义缓存不立项的实证依据
95% 命中精度 + 5x 延迟改善，但误命中污染风险对抽取类调用不可接受，且查询类天然多样——维持 E 方案不立项，仅在未来搜索模板化时对 SEARCH_* 试点。

## 二、精读笔记

### 2.1 LightRAG（对 weaver 价值最高）

**方法**：① 图索引——chunk → LLM 抽取实体/关系 → LLM profiling 生成键值对（键=检索用词/短语，值=摘要段落）→ 去重；② 双层检索——低层（具体实体/关系）+ 高层（主题/概念），查询先由 LLM 生成双层关键词，再与索引键匹配、收集、重排；③ 增量更新——新文档抽取后与现有图做节点/边集并集，**不重建索引**。

**关键实证（Legal 数据集，Table 3）**：
- 检索阶段：GraphRAG（社区报告 map-reduce）= 610 个社区 × 1000 tokens = **610,000 tokens/查询，数百次调用**；LightRAG = **<100 tokens（关键词生成）+ 1 次调用**
- 增量更新：GraphRAG 需拆散社区结构全量重建报告（1,399 社区 × 2 × 5,000 tokens ≈ **1400 万 tokens**）；LightRAG 仅并集增量，零重建

**与 weaver 的映射**：weaver 的 `global_search`（top-3 社区报告 map-reduce）与 `CommunityUpdateTrigger`（增量后重跑社区检测+报告生成）正是论文中被量化的 GraphRAG 成本模式。weaver 已具备 LightRAG 全部前提：pgvector、实体/关系存储（含 description）、去重管线。

### 2.2 LLMLingua-2

**方法**：把 prompt 压缩建模为 token 二分类（抽取式，保真不幻觉）；从 LLM 蒸馏压缩标注训练小模型（XLM-RoBERTa-large / mBERT）；全句级变长压缩比。

**关键实证**：压缩比 2x-5x；比既有压缩方法快 3-6x；端到端延迟加速 1.6x-2.9x；任务无关、跨域泛化（MeetingBank 域内 + LongBench/ZeroScrolls/GSM8K/BBH 域外）。

**与 weaver 的映射**：briefing（4000 tokens 全文拼接收纳不了几十篇）、search_local（6000 tokens 图谱上下文）、narrative_synthesis（8000）目前用 TokenBudgetManager 硬截断（70/30 丢弃中段）——压缩替代截断可让同预算装下 2-5 倍信息。小模型可本地部署，与 weaver 既有的 ollama/GLiNER 本地化模式一致。

### 2.3 ComEM 实体匹配（COLING 2025）

**方法与结论**：LLM 实体匹配三种策略——Match（逐对分类）/ Compare（属性比对打分）/ Select（候选清单中选择）；候选交互式策略（尤其批量 Select）以**显著更少的调用次数**达到与逐对匹配相当或更优的 F1。

**与 weaver 的映射**：`entity_resolver` 目前每个"向量有候选但规则未命中"的实体单独调一次 LLM（全系统调用频次之最）——改为每篇文章一次批量 Select 调用（top-N 候选清单），与 MC 采样批量化的成功模式同构。

## 三、优化方案（kueiku RICE 确定性排序 + 第二轮修订）

| 排名 | 方案 | RICE | 论文依据 | 预期收益 | 工作量 |
|---|---|---|---|---|---|
| 1 | **C. entity_resolver 批量 Select**：每实体 1 次调用 → 每篇 1 次批量候选选择 | 0.9 | ComEM Select + KARMA 对齐 agent | 调用次数 -80%+ | 小-中 |
| 2 | **D. 单遍复合抽取（TERAG 化增强）**：analyze/entity/narrative/claim 合并；实体清单用纯文本输出（无 JSON 开销），关系靠非 LLM 共现推断，spaCy/GLiNER 主抽 + LLM 兜底 | 0.4↑ | LightRAG 索引 + **TERAG 88-97% 输出压缩实证** | 输入 17.3k→~8k 且**输出 token 大幅下降** | 中-大 |
| 3 | **B. LLMLingua-2 上下文压缩** | 0.4 | LLMLingua-2 | 同预算信息量 2-5 倍 | 中 |
| 4 | **A. global_search 检索改造（KET-RAG 渐进式）**：不二选一——影子层只对热点实体/高价值文章建 KV 图索引（10-20% 覆盖起步），长尾走 pgvector；可选 TERAG 式概念共现图 + PPR 作为零 LLM 建图变体 | 0.3→**0.45** | **KET-RAG 94%@10-20%** + TERAG PPR + LightRAG 双层检索 | 每查询 4 次调用 → 1-2 次；增量免全量重建；迁移成本比全量 LightRAG 化低 80% | 中-大（比原方案降级） |
| 5 | E. 语义缓存 | 0.1 | GPTCache 局限实证 | 不立项（见上） | — |

**第二轮排序变化**：方案 A 从"全量 LightRAG 化（RICE 0.3，工作量大）"修订为"KET-RAG 渐进混合索引（RICE 0.45）"——论文证明 10-20% 覆盖即可拿到 94% 收益，迁移风险与成本大降；方案 D 引入 TERAG 的"输出侧压缩 + 非 LLM 关系推断"，收益从输入侧扩展到输出侧。

**实施顺序建议**：C（即时可做，独立性强）→ D（等 llm_usage 按 call_point 真实数据校准收益）→ B（先小模型离线评测中文压缩质量再接入）→ A（最大的改造，建议独立 specmark change，先做 KV 索引只读影子层验证检索质量后再切换）。

## 四、置信度与不确定因素

- C/D：**高**（论文实证 + weaver 第一期 MC 批量化已在同一模式上验证成功）
- B：**中高**（论文主实验为英文 MeetingBank；中文 2-gram/token 化压缩质量需离线评测，本地算力需确认）
- A：**中**（论文数据充分，但 weaver 社区体系已有下游依赖（community_report 端点、简报），迁移需兼容期；检索质量需影子对比）
- 主要不确定因素：agnes 免费档限流使 A/B 实测对照的采样窗口受限；LLMLingua-2 官方模型为英文主导，中文需自训或换中文蒸馏模型
