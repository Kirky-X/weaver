# ⚡ Weaver LLM 调用优化方案

> 编制日期：2026-09-15 · 状态：**部分已实施（A/B + 前置项），详见下方实施记录**
> 代码基线：`636d4b1f`
> 所有行号引用基于上述基线，实施前请重新核对

> ## ✅ 实施记录（2026-09-15）
>
> | 项 | 状态 | 实施说明 |
> |---|---|---|
> | 前置：llm_call_total/latency/fallback 埋点 | ✅ 已实施 | `client.py` `_execute_single_provider`（成功/失败+延迟）+ `call()` fallback 计数 |
> | 前置：monte_carlo 配置接线（审计#2） | ✅ 已实施 | `PipelineSettings.monte_carlo` 字段；lifecycle suppress → WARNING |
> | 前置：content_hash 版本化失效 | ✅ 已实施 | `content_hash_version` 配置驱动，本次已 bump 2→3 |
> | 前置：BM25 增量任务（审计#3）/ persistence fail-open（审计#4） | ✅ 已实施 | 调度任务 `bm25_rebuild_index`（间隔可配）；置位仅对成功集合 |
> | **B** | ✅ 已实施 | narrative 自有调用 payload 移除 entities（缓存键+输入 token 双收益） |
> | **A** | ✅ 已实施（带开关） | `CallPoint.ANALYZE_NARRATIVE` + `config/prompts/analyze_narrative.toml` + `AnalyzeNarrativeOutput`（字段约束逐字镜像 NarrativeSchemaOutput，修正 §3.3 示例偏差：emphasis max 60、event_type 带 regex、pattern min_length=2）+ `merge_analyze_narrative` 开关（代码默认 false）+ 合并调用点 `max_tokens = 8192`（TOML 配置，非硬编码） |
> | **G** | ⚠️ 前提不成立，未实施 | SchemaNode 驱动 structured_output 校验闭环、NarrativeNode 是 briefing 叙事模式数据源——关闭属功能裁剪，需产品决策 |
> | D/E/C/F | ⏸ 未实施 | 按原计划：D/E 等埋点实测兜底率；C 在 A 稳定后；F 单独立项 |
>
> **§8.4 评测集仍为前置阻塞项**：`merge_analyze_narrative` 当前在 pipeline.toml 已置 true，但精度验证（结构合规率/一致性/硬性判据）未完成——上线前请按 §8.4 抽样对比；回滚置 false 即可。
> **模型配置已同步改造**：项目默认 `chat.openai.gpt-4o`，Agnes 降为测试专用（`agnes-3.0-flash`，参考官方文档：512K 上下文/最大输出 65,536 tokens），provider/模型/费率全部 TOML+环境变量可配。

---

## 📋 目录

- [1. 背景与现状基线](#1-背景与现状基线)
- [2. 目标与收益总览](#2-目标与收益总览)
- [3. 方案 A：合并 analyze + narrative_schema](#3-方案-a合并-analyze--narrative_schema)
- [4. 方案 B：清理 narrative 缓存键（1 行改动）](#4-方案-b清理-narrative-缓存键1-行改动)
- [5. 方案 C：合并 classifier + categorizer](#5-方案-c合并-classifier--categorizer)
- [6. 方案 D/E/G：配置层优化（零代码）](#6-方案-deg配置层优化零代码)
- [7. 方案 F：Phase 3 批量化（概要）](#7-方案-fphase-3-批量化概要)
- [8. 精度影响评估](#8-精度影响评估)
- [9. 验证计划](#9-验证计划)
- [10. 风险与回滚](#10-风险与回滚)
- [11. 建议实施顺序](#11-建议实施顺序)

---

## 1. 背景与现状基线

### 1.1 为什么必须优化

`config/llm.toml` 中所有 chat 调用点共用同一个模型 `agnes-2.0-flash`，且该 provider 配置：

```toml
[providers.agnes]
rpm_limit = 5      # 每分钟 5 次请求
concurrency = 2    # 瞬时并发 2
```

embedding 走本地 Ollama（`qwen3-embedding:0.6b`，`rpm_limit = 0` 不限流），**不占这个额度**。
因此 `rpm_limit = 5` 就是整条流水线 chat 侧的总吞吐天花板：每篇 4.7 次 chat ≈ 每分钟 1.06 篇。
**减少 chat 调用次数 = 直接线性提升吞吐**，这是当前最高杠杆。

### 1.2 单篇调用清单（实测）

入口：`src/modules/processing/pipeline/graph.py` → `_process_batch_impl()` → `_phase1_per_article()` / `_phase3_per_article()`。
统一出口：`LLMClient.call_at()`（`src/core/llm/client.py:742`）→ `LiteLLMCaller.chat()`。

| 阶段 | 节点 | 类型 | 次数 | 触发条件 |
|---|---|---|---|---|
| P1 | Classifier | chat | 0–1 | 规则 + fastText/SetFit cascade 均未命中才兜底 |
| P1 | Cleaner | chat | 0–2 | trafilatura 通过质量检查则 0；否则 LLM，最多 2 attempt（`_MAX_CLEANER_ATTEMPTS=2`） |
| P1 | Categorizer | chat | 0–1 | 关键词规则命中则 0 |
| P1 | Vectorize | embed | 1 | title+content 合并为 **1 次**批量请求 |
| P2 | BatchMerger | chat | 0–1 | 仅相似文章成组且成员 > 1 |
| P3 | ReVectorize | embed | 1 | 合并后重算 |
| P3 | Analyze | chat | 1 (+0~3) | 必调；正文 > 10000 字符触发蒙特卡洛采样（+1~2）；SKEP 不可用时情感回退（+1） |
| P3 | QualityScorer | — | 0 | 纯规则 |
| P3 | Credibility | — | 0 | 纯规则 |
| P3 | EntityExtractor | chat + embed | 1 + 1~2 | spaCy/GLiNER 一批 + LLM 新增实体一批，每 32 条一分批 |
| P3 | FakeNews | embed | 0 (缺向量时 1) | 复用已有向量 |
| P3 | ConflictDetector | chat | 0–1 | 需抽出数值 claim 且向量召回相似文章（阈值 0.7） |
| P3 | NarrativeSchema | chat | 1 | 必调 |
| P3 | SentimentTracker | — | 0 | 纯计算 |
| P3 | EntityResolver | chat | 0–N | N = ceil(待判定实体 / 20)，通常 0–1 |

**汇总**：典型 **chat 4–5 次 + embed 3–4 次 = 8–10 次 HTTP**；其中 chat 必调 3 次（analyze / entity_extractor / narrative_schema）。

### 1.3 三个已确认的事实

1. **analyze 与 narrative_schema 的输入完全重复**
   - `AnalyzeNode` payload：`title` + `body`
   - `NarrativeSchemaExtractorNode` payload：`title` + `body` + `entities`
   - 但 `config/prompts/narrative_schema.toml` 的 system 提示词**完全不消费 entities**
   - 两者被拆成两次调用纯属历史原因（`NarrativeSchemaOutput` 本身就是"把两次调用合并成一次"的产物，此模式项目内已有先例）

2. **`entities` 污染缓存键**
   - `client.py:71` 的 `NON_SEMANTIC_FIELDS` 只剥离 `article_id / task_id / timestamp / request_id / trace_id`，**不含 entities**
   - `build_stable_cache_key()`（`client.py:82`）对剩余 payload 做 sha256 → entities 任何变动都导致 cache miss
   - 同时 entities 被 `json.dumps` 进 user_content，白白增加 input token

3. **`batch_call` 是空转的**
   - `client.py:631` 的 `batch_call()` 全项目无调用方
   - 且它内部仍是 `for idx in uncached_indices: await self.call(...)`，只省 Redis 往返，**不省真实 LLM 调用**

---

## 2. 目标与收益总览

| 方案 | 动作 | chat 降幅 | 改动量 | 风险 |
|---|---|---|---|---|
| **A** | 合并 analyze + narrative_schema | 1 次/篇（必调 3→2） | 中 | 中 |
| **B** | 删除 narrative payload 的 entities | 提升缓存命中率 | 1 行 | 极低 |
| **C** | 合并 classifier + categorizer | 0–1 次/篇 | 中 | 中 |
| **D** | 放宽 trafilatura 阈值 | 0–2 次/篇 | 配置 | 低 |
| **E** | conflict_detector 默认走正则 | 0–1 次/篇 | 小 | 低 |
| **F** | Phase 3 批量化 | 3 次/篇 → 3 次/批 | 大 | 高 |
| **G** | TOML 关掉非核心阶段 | 1–2 次/篇 | 零代码 | 低 |

组合预期：**A+B** → 4.7 → 3.7 次/篇（−21%）；**A+B+F** → ≈1.9 次/篇（−60%）。

---

## 3. 方案 A：合并 analyze + narrative_schema

### 3.1 核心思路

**不改 DAG 顺序**，只改变"谁发起调用"：

- `AnalyzeNode` 发起一次合并调用，结果拆分后把 narrative 部分暂存进 state
- `NarrativeSchemaExtractorNode` 从 **LLM 节点退化为纯持久化节点**，只负责读 state 并写图

这样 Phase 3 的并发块（`_run_fake_news` / `_run_conflict` / `_run_narrative_schema`）里少一次 LLM 调用，而执行顺序、失败隔离边界、图写入时机全部保持不变。

### 3.2 两条实现路径（需评审选择）

#### 路径 A2（推荐，规范做法）

新增独立调用点，语义清晰、可按 call_point 独立观测。

改动清单：

| # | 文件 | 改动 |
|---|---|---|
| 1 | `src/core/llm/types.py:23` | `CallPoint` 枚举新增 `ANALYZE_NARRATIVE = "analyze_narrative"` |
| 2 | `src/core/llm/types.py:467` | `CACHE_TTL` 新增 `"analyze_narrative": 24 * 60 * 60` |
| 3 | `src/core/llm/config/token_budget.py` | 新增 `CallPoint.ANALYZE_NARRATIVE: 8000`（取 narrative 原值，不折中——见 §8.1 风险 3） |
| 4 | `config/prompts/analyze_narrative.toml` | **新增**，合并两段 system 提示词 |
| 5 | `src/core/llm/validation/output_validator.py` | **新增** `AnalyzeNarrativeOutput`（见 3.3） |
| 6 | `config/llm.toml` | 新增 `[call-points.analyze_narrative]`（见 3.6 约束冲突） |
| 7 | `src/modules/processing/nodes/extraction/analyze.py` | 合并调用 + 结果拆分（见 3.4） |
| 8 | `src/modules/processing/nodes/extraction/narrative_schema_extractor.py` | 改为读 state 持久化（见 3.5） |

#### 路径 A1（零配置风险备选）

复用现有 `CallPoint.ANALYZE`，只改 `config/prompts/analyze.toml` 的提示词内容 + 换 output model。

- 优点：不动 `llm.toml`、不动枚举、不动 token_budget
- 缺点：prompt 语义与文件名不符（analyze.toml 里含叙事框架）；narrative 的截断上限从 8000 降到 4000；metrics 无法区分合并前后

### 3.3 输出模型

```python
# src/core/llm/validation/output_validator.py
class AnalyzeNarrativeOutput(AnalyzeOutput):
    """analyze + narrative/schema 的合并输出。

    继承 AnalyzeOutput 以保持 analyze 侧字段契约不变，
    追加 NarrativeSchemaOutput 的 7 个字段。
    """
    source_bias: Literal[...] = "中立"
    frame: str = Field(min_length=1, max_length=100)
    tone: Literal[...] = "客观"
    emphasis: str = Field(default="事件概述", max_length=50)
    event_type: str = Field(default="事件陈述", max_length=50)
    pattern: str = ""
    confidence: float = Field(ge=0, le=1, default=0.0)

    def to_narrative_payload(self) -> NarrativeSchemaOutput:
        """拆出 narrative 部分，供持久化节点消费。"""
        return NarrativeSchemaOutput(
            source_bias=self.source_bias, frame=self.frame, tone=self.tone,
            emphasis=self.emphasis, event_type=self.event_type,
            pattern=self.pattern, confidence=self.confidence,
        )
```

字段约束**必须**镜像 `NarrativeSchemaOutput`（`output_validator.py:347`）——该注释明确指出这是"防止 prompt 注入进图数据库"的防线，不可放宽。

### 3.4 AnalyzeNode 改动

```python
# src/modules/processing/nodes/extraction/analyze.py
if self._merge_narrative and not state.get("terminal"):
    result: AnalyzeNarrativeOutput = await self._llm.call_at(
        CallPoint.ANALYZE_NARRATIVE,
        {"title": ..., "body": body, "article_id": ..., "task_id": ...},
        output_model=AnalyzeNarrativeOutput,
        article_id=state.get("article_id"),
        task_id=state.get("task_id"),
    )
    self._apply_analyze_fields(state, result)          # 现有逻辑抽成方法
    state["_narrative_schema_payload"] = result.to_narrative_payload()
else:
    ...  # 现有 AnalyzeOutput 路径，逐字保留
```

**开关**：`self._merge_narrative` 读 `config/pipeline.toml` 新增字段 `[phase3] merge_analyze_narrative = true`。
`config/pipeline.toml` 不在 AGENTS.md 的禁改清单内，且该文件已有 `enabled` 开关先例，回滚只需置 false。

### 3.5 NarrativeSchemaExtractorNode 改动

```python
async def _execute_impl(self, state: PipelineState) -> PipelineState:
    if state.get("terminal") or state.get("is_merged"):
        return state

    payload = state.get("_narrative_schema_payload")
    if payload is None:
        # 合并开关关闭，或 analyze 侧已降级 → 回落到自有 LLM 调用（现状路径）
        payload = await self._call_llm(state)
        if payload is None:
            state.setdefault("degraded_fields", []).extend(["narrative", "schema"])
            return state

    self._persist_all(state, payload)   # merge_narrative + merge_schema，现有逻辑抽成方法
    return state
```

该节点从此**不再产生 chat 调用**（开关开启时）。

### 3.6 ⚠️ 约束冲突（实施前必须确认）

`AGENTS.md` § 配置规范 写明：

> LLM 配置：`config/llm.toml`，禁止 `${ENV_VAR}` 语法，**禁止修改**

而 `router.py:60` 的 `get_call_point_route()` 在调用点未配置时**直接抛 `ValueError`**：

```python
routing = self._call_points.get(call_point)
if not routing:
    raise ValueError(f"Call point not configured: {call_point}")
```

即路径 A2 若在 `llm.toml` 漏配 `[call-points.analyze_narrative]`，运行时会 100% 抛错。

**处理建议**（三选一，需你拍板）：
1. 评审豁免：本次为新增调用点而非改动既有配置，允许在 `llm.toml` 追加 4 行
2. 走路径 A1，完全绕开该文件
3. 改由 `SmartRouter` 动态注册（改动更大，不建议）

### 3.7 Token 与延迟评估

- **input**：合并后 body 取 8000 字符（沿用 narrative 原值，见 §8.1 风险 3），相对 analyze 的 4000 翻倍。Agnes 为免费档（费率 0.0），成本不敏感；RPM 才是硬约束，**用单次更长请求换掉一次请求仍然划算**
- **output**：analyze ≈ 500 token + narrative（含 pattern，撑满 4000 字 ≈ 3000 token）≈ 3000–4000 token。**已逼近 `max_tokens = 4096` 上限，截断即双失**。合并调用点**必须**显式设 `max_tokens = 8192`（详见 §8.1 风险 1）
- **延迟**：Phase 3 的关键路径从 `max(analyze, quality) → ... → max(fake_news, conflict, narrative)` 少了一段 LLM，尾延迟下降约 1 个 RTT

---

## 4. 方案 B：清理 narrative 缓存键（1 行改动）

`src/modules/processing/nodes/extraction/narrative_schema_extractor.py:107`：

```python
{
    "title": title,
    "body": truncated_body,
    "entities": entities,        # ← 删除这一行
    "article_id": article_id,
    "task_id": state.get("task_id"),
}
```

**依据**：提示词模板不消费 entities；`NON_SEMANTIC_FIELDS` 不含它，故它同时污染 cache key 与 input token。

**收益**：同一篇文章重复处理（重跑、相似内容）时缓存命中率提升；单次 input token 下降。

**⚠️ 风险修正（2026-09-15）**：初稿称本项"风险极低、不改变输出语义"，该判断不严谨，予以修正。

`client.py:812` 的 `user_content = json.dumps(semantic_payload, ...)` 会把 entities **序列化后送进 user_content**，即 LLM 实际能看到它。虽然 system 提示词未指示使用，但模型可能隐式利用（`pattern` 的 properties 参考实体名、`event_type` 受实体类型启发）。

因此删除 entities 对输出质量的影响**方向不确定**，可能变好（减少干扰）也可能变坏（丢失有用信号）。**必须通过影子评估实测，不可按零风险处理。**

**注意**：会一次性使既有 narrative 缓存全部失效（key 变化），属预期的一次性代价。

---

## 5. 方案 C：合并 classifier + categorizer

两者都是"标题级分类 + 规则优先 + LLM 兜底"，且都在 Phase 1。

**难点**：当前顺序是 `classifier → cleaner → categorizer`，categorizer 消费 `cleaned` 后的正文，合并需要跨过 cleaner。且若 `is_news = False` 会 terminal，此时 category 无意义。

**建议做法**：
- 在 cleaner 之后、`terminal` 判定之后新增合并节点
- 仅当 classifier 与 categorizer **都**需要 LLM 兜底时才合并调用；若 classifier 已由规则/ML 判定，则退化成单独的 categorizer 调用
- 输出 `{is_news, category, language, region}`

**收益**：0–1 次/篇（仅在两者同时兜底时生效，实测该比例不高）。
**优先级**：低于 A 与 B，建议 A 稳定后再做。

---

## 6. 方案 D/E/G：配置层优化（零代码）

`config/pipeline.toml` 已支持按阶段 `enabled` 开关（`graph.py:139` 的 `_disabled_phase3_stage_names` 消费它）。

### G. 关掉非核心阶段（立即见效）

```toml
[[phase3.stages]]
name = "narrative_schema"
enabled = false      # 省 1 次必调 chat

[[phase3.stages]]
name = "conflict_detector"
enabled = false      # 省 0–1 次 chat
```

代价：丢失叙事框架分析与 SchemaNode 写入。若这两项目前没有下游消费方，这是最划算的一步。

### D. 提高 trafilatura 覆盖率

`CleanerNode` 的 LLM 兜底是最贵的分支（最多 2 次）。放宽 `_min_body_chars` / `_min_title_similarity` 可显著降低兜底率。

**⚠️ 风险等级修正（2026-09-15）**：初稿标注「低风险」为低估。清洗质量下降会**连锁污染下游全部 LLM 节点**（analyze / narrative / entity_extractor 均以 `cleaned.body` 为输入），修正为**中高风险**。
建议先埋点统计当前兜底率，并在评测集上对比放宽前后的下游字段质量，再决定阈值。

### E. conflict_detector 走纯正则

`conflict_detector.py:99` 的 `_extract_numerical_claims()` 已有 `NUM_PATTERNS` 正则兜底（`_extract_claims_regex`）。
增加配置开关默认走正则，可省 0–1 次 chat。代价：数值 claim 召回率下降。

---

## 7. 方案 F：Phase 3 批量化（概要）

把 analyze / narrative / entity_extractor 从"单篇一次调用"改成"一批文章一次调用"（batch payload + 数组化输出）。

- **收益**：3 次/篇 → 3 次/批。若 `worker_batch_size = 20`，则 0.15 次/篇，叠加条件调用后约 1.9 次/篇
- **代价**：
  - prompt 与 output model 全部数组化，需处理部分失败（某篇 JSON 不合法不能拖垮整批）
  - 单篇失败隔离语义被打破，现有 `return_exceptions` + 逐篇降级的机制要重写
  - 输出 token 随批量线性增长，`max_tokens` 需大幅上调
  - 缓存粒度从单篇变为整批，命中率可能反而下降
- **建议**：等 A 落地并观测稳定后，单独立项评估

---

## 8. 精度影响评估

### 8.0 ⚠️ 前置结论：当前不具备量化精度的条件

| 能力 | 现状 |
|---|---|
| Golden dataset | **无**（`tests/fixtures/` 仅 `search_keywords.py`） |
| 自动化质量打分 | **无** |
| 输出文本留痕 | **无**——`llm_compare_hourly`（`src/core/db/models/llm.py:164`）只存聚合计数与延迟，不存输出内容 |
| 影子评估 | 有，但只能对比「同 payload + 不同模型」（`eval_runner.py:154`），**不能对比不同 prompt** |

结论：「精度下降 X%」目前给不出来，只能做机制分析 + 人工抽样。**这是实施前必须先补的短板**，否则上线后无法判断变好还是变坏。

**利好**：`temperature = 0.0`（`llm.toml:35`），输出确定性高，A/B 对比可重复、结论可信。

### 8.1 方案 A 的精度风险（按严重度排序）

| # | 风险 | 机理 | 严重度 | 缓解 |
|---|---|---|---|---|
| 1 | **输出截断** | `max_tokens = 4096`；`pattern` 允许 4000 字，中文 JSON Schema 撑满约 3000 token；合并后典型 3000 / 撑满 4000，贴着上限。截断 → JSON 非法 → **analyze 与 narrative 双失**（现状为两个独立调用，互不影响） | **致命** | 合并调用点**必须**显式设 `max_tokens = 8192`（`call_at` 支持 call-point 级 override，`client.py:787`）。此为前置条件，非可选项 |
| 2 | **末尾字段退化** | 输出字段 11 → 18，token 500 → 3000+。长生成中靠后字段易退化，而 `pattern` 在最后且最复杂（合法 JSON Schema + 引号转义） | **高** | 分段 prompt（现有 narrative prompt 已是「第一部分/第二部分」结构）；`_JSON_FORMAT_TAIL` 追加在 system 末尾可利用 recency bias；**需实测确定 pattern 的最优位置** |
| 3 | **输入 budget 取舍** | analyze 4000 字符 / narrative 8000 字符。合并取 6000 → narrative 侧输入少 25%，影响 `event_type` 与 `pattern` 抽取 | 中 | **修正：建议保守取 8000**。Agnes 免费、瓶颈是 RPM 而非 token，多花 input 换质量划算 |
| 4 | **失败相关性** | 独立调用双失概率 p²，合并后为 p。p=2% 时 **0.04% → 2%，提高约 50 倍**。单字段成功率不变（均 1−p），但「两个功能同时丢失」显著变多 | 中 | 降级时同时标记 `degraded_fields += ["narrative","schema"]` 保证可观测；不做拆分重试（抵消收益） |
| 5 | **缓存粒度变粗** | 现状 analyze 命中 + narrative 未命中只需调 1 次；合并后任一侧未命中即整次重调 | 低 | 部分抵消收益，需实测实际命中率变化 |

### 8.2 方案 B 的风险修正

见 [§4](#4-方案-b清理-narrative-缓存键1-行改动)——entities 进入 user_content 被 LLM 可见，删除后影响**方向不确定**，须实测。

### 8.3 D/E/G 属于确定性损失

- **D（放宽 trafilatura 阈值）**：**连锁精度损失**。低质量正文会污染下游全部 LLM 节点（analyze / narrative / entity_extractor）。初稿标注「低风险」为低估，修正为**中高风险**
- **E（conflict 走正则）**：数值 claim 召回下降 → 漏报增加。损失明确但可控
- **G（关闭阶段）**：非精度问题，属功能裁剪

### 8.4 最小评测集建议（实施前必建）

抽样 **50–100 篇**，覆盖不同 category / language / 长度（含 >10000 字符长文以覆盖蒙特卡洛采样路径）。对每条路径各跑一遍，按由易到难评分：

1. **结构合规率**（全自动，最优先）
   - JSON 可解析率
   - 必填字段完整率
   - `pattern` 是否为合法 JSON Schema（`jsonschema` 校验）
2. **一致性**（全自动）
   - `event_type` 一致率、`sentiment` / `sentiment_score` 偏差、`source_bias` / `tone` 一致率
   - `summary` 语义相似度（embedding cosine）
3. **LLM-as-judge**（半自动）
   - 用独立模型对摘要质量、框架准确性打分

**硬性判据**（不达标则回滚）：
- 结构合规率不下降
- `event_type` 一致率 ≥ 90%
- `summary` 语义相似度 ≥ 0.85
- `pattern` JSON Schema 合法率不下降

**前置改造**：当前不留存输出文本，无法离线复盘。需在评测期间临时落盘或加 DEBUG 日志，否则上述 2、3 项无法执行。

---

## 9. 验证计划

### 9.1 单元验证

新增 `tests/unit/modules/processing/nodes/test_analyze_narrative_merge.py`：

- 合并输出模型能正确解析完整 JSON
- `to_narrative_payload()` 拆分正确，字段约束与 `NarrativeSchemaOutput` 一致
- `NarrativeSchemaExtractorNode` 在 `_narrative_schema_payload` 缺失时回落自有调用
- 开关 `merge_analyze_narrative = false` 时行为与现状逐字段一致（回归断言）

### 9.2 集成验证

- `tests/integration/modules/processing/test_pipeline_mode_integration.py` 扩样例：跑 10 篇样本，断言 `state["narrative"]`、`state["schema"]`、`state["summary_info"]` 均非空
- 对比开关开/关两种模式下上述字段的一致性（允许表述差异，不允许字段缺失）

### 9.3 指标验证（最硬的证据）

`MetricsCollector.llm_call_total{call_point, provider, status}`（`src/core/observability/metrics.py:27`）已按 call_point 打标：

```promql
# 优化前
sum by (call_point) (rate(llm_call_total{call_point=~"analyze|narrative_schema"}[1h]))

# 优化后：两个 call_point 之和应显著下降，analyze_narrative 上升
sum by (call_point) (rate(llm_call_total{call_point=~"analyze|narrative_schema|analyze_narrative"}[1h]))
```

判据：处理相同文章数，`analyze + narrative_schema + analyze_narrative` 总调用数应下降约 1/3（对应必调 3→2），且 `narrative` 字段缺失率不上升。

### 9.4 灰度

`LLMEvalConfig`（`src/core/llm/types.py`）已有 `sample_rate` / `target_call_points` 的影子评估机制，可先按 10% 影子流量对比合并输出与拆分输出的质量差异，再全量切换。

---

## 10. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 合并后单次失败影响面扩大 | 一次失败同时丢摘要与叙事框架 | analyze 的 except 分支显式 `extend(["narrative","schema"])`，保证 `degraded_fields` 可观测；不做拆分重试（会抵消收益） |
| 输出 token 超 `max_tokens` | JSON 被截断 → 解析失败 | 合并调用点显式 `max_tokens = 8192`；单测覆盖最长 pattern 场景 |
| prompt 合并后字段相互干扰 | 某一侧质量下降 | 影子评估对比；prompt 内用「第一部分/第二部分」明确分段（现有 narrative prompt 已是此结构） |
| `llm.toml` 漏配新调用点 | 100% 抛 `ValueError` | 见 3.6；集成测试必须覆盖；或选择路径 A1 绕开 |
| 缓存一次性全失效（方案 B） | 短期调用数反升 | 与方案 A 同批上线，用 A 的收益覆盖 B 的冷启动 |

**回滚**：
- 方案 A：`config/pipeline.toml` 置 `merge_analyze_narrative = false`，无需改代码、无需重启以外的操作
- 方案 B/E：改回一行配置或恢复 payload 字段
- 方案 G：TOML 置回 `enabled = true`

---

## 11. 建议实施顺序

1. **先埋点**：按 call_point 统计一周 `llm_call_total`，确认各阶段真实兜底率（尤其是 cleaner 与 classifier/categorizer），用实测数据校准上表的条件触发估算
2. **建最小评测集**（§8.4）— **方案 A 的前置阻塞项**，无此无法验证精度
3. **G**（零代码）— 确认 narrative/conflict 无下游消费后立即关，即时收益
4. **B**（1 行）— 与 G 同批；因影响方向不确定（§4），须在评测集上验证后再全量
5. **A**（核心）— 带开关实施；先建评测集 → 离线对比 → 10% 影子 → 全量。**必须先设 `max_tokens = 8192`**
6. **D/E**（配置）— 基于第 1 步的实测兜底率决定阈值；D 为连锁精度损失，谨慎
7. **C** — A 稳定后
8. **F** — 单独立项

---

## 附录：实施前必读的项目约定

摘自 `AGENTS.md`，实施时须遵守：

- **改动任何符号前 MUST 跑 `gitnexus_impact({direction: "upstream"})` 评估影响面**；HIGH/CRITICAL 必须先告知
- **提交前 MUST 跑 `gitnexus_detect_changes()`** 确认影响范围符合预期
- 异常处理：禁止 `except Exception: pass`，MUST 含日志；关键路径异常 MUST 记 WARNING 以上
- 类型注解：`None` 默认值用 `| None`；须过 `mypy --ignore-missing-imports`
- 格式：所有 Python 文件须过 `black --check`
- 配置：`config/llm.toml` 禁改（见 3.6）；`config/pipeline.toml` 可改，环境变量格式 `WEAVER_<SECTION>__<FIELD>`
