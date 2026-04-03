# MAGMA Integration Guide

This guide explains how to MAGMA-inspired intent-aware routing and temporal inference features work.

## Intent Classification

The system uses an LLM-based classifier to identify query intent:

### Intent Types

- **WHY**: Causal reasoning queries ("为什么..."、"原因是什么...")
- **WHEN**: Time-based queries ("什么时候..."、"何时..."、"哪个时间...")
- **ENTITY**: Entity-focused queries ("X是什么..."、"告诉我关于Y...")
- **MULTI_HOP**: Multi-hop reasoning queries ("X和Y的关系..."、"对比X和Z...")
- **OPEN**: Open-domain queries ("关于..."、"告诉我...")

### Confidence Threshold

Classifications below the confidence threshold (default 0.7) trigger fallback mode.

### LLM Prompt Template

```
你是一个查询意图分类器。分析用户的搜索查询，识别其主要意图类型。

意图类型：
- WHY: 询问原因、理由、因果关系（"为什么..."、"因为什么..."、"原因是什么..."）
- WHEN: 询问时间、时间点、顺序（"什么时候..."、"何时..."、"哪个时间..."）
- ENTITY: 询问实体、事实、描述（"X是什么..."、"告诉我关于Y..."）
- MULTI_HOP: 需要多步推理的关系查询（"X和Y的关系..."、"对比X和Z..."）
- OPEN: 开放域、探索性查询（"关于..."、"告诉我..."）

同时检测：
1. 时间信号：识别任何相对时间表达式（如"yesterday"、"last week"、"next Monday"）
2. 实体信号：提取主要实体名称

返回 JSON：
{
    "intent": "WHY|WHEN|ENTITY|MULTI_HOP|OPEN",
    "confidence": 0.0-1.0,
    "temporal_signals": [{"expression": "yesterday", "anchor_type": "relative"}],
    "entity_signals": ["实体1", "实体2"],
    "keywords": ["关键", "词"]
}

查询：{query}
```

## Temporal Inference

### Supported Chinese Expressions

| Expression | Example      | Resolved Window               |
| ---------- | ------------ | ----------------------------- |
| 昨天       | yesterday    | 昨天 (reference date - 1 day) |
| 今天       | today        | 今天                          |
| N天前      | 3 days ago   | 之前 N 天                     |
| N个月前    | 2 months ago | 之前 N × 30 天                |
| 本周       | this week    | 本周 (从周一开始)             |
| 上周       | last week    | 上周 (上一整周)               |
| 下周       | next week    | 下周 (下一整周)               |
| 本月       | this month   | 本月 (1号开始)                |
| 上月       | last month   | 上月 (上个月)                 |
| 下月       | next month   | 下月 (下个月)                 |
| 上周一     | last Monday  | 上周一的星期一                |
| 下周五     | next Friday  | 下周五的星期五                |

### Time Window

For WHEN queries with relative time expressions:

1. Default window: 7 days
2. Extension for "week" expressions: full week range
3. Auto-anchoring: Relative expressions automatically anchored to current time

### Configuration

```python
# In config/settings.toml or src/config/settings.py

[search.intent_routing]
enabled = true
classification_threshold = 0.7
fallback_mode = "local"
allow_explicit_mode = true

[search.temporal_inference]
enabled = true
default_window_days = 7
parse_chinese_expressions = true
auto_anchor = true
```

## Migration Path

1. Deploy intent classification and router modules
2. Update API endpoint with intent-aware routing
3. Monitor classification accuracy
4. Gradually enable temporal inference features
5. Deprecate `mode` parameter (mark with warning in logs)

## Troubleshooting

### Intent Classification Issues

If queries are misclassified:

1. Check LLM temperature - set to 0 for deterministic output
2. Review prompt templates in `src/modules/knowledge/search/intent/classifier.py`
3. Adjust `classification_threshold` in settings
4. Enable debug logging to see classification results

### Temporal Parsing Issues

If time expressions are not parsed correctly:

1. Check `parse_chinese_expressions` is enabled
2. Review pattern definitions in `src/modules/knowledge/search/temporal/parser.py`
3. Add new patterns to `PATTERNS` dictionary
4. Test with unit tests in `tests/modules/knowledge/search/temporal/test_parser.py`

## API Usage

### Automatic Intent Routing

```http
GET /search?q=为什么服务器会崩溃？
→ WHY intent detected, uses local search with causal relationship focus

GET /search?q=上周五发生了什么？
→ WHEN intent detected, parses "上周五", applies 1-week time window

GET /search?q=Neo4j是什么？
→ ENTITY intent detected, extracts "Neo4j", searches entity neighborhood

GET /search?q=GraphRAG和MAGMA有什么区别？
→ MULTI_HOP intent detected, uses global search with community-level analysis
```

### Backward Compatibility

The `mode` parameter is deprecated but still supported:

```http
GET /search?mode=local&q=测试查询
→ Explicit mode specified, overrides automatic routing
```

Users can still use `mode` parameter if they prefer manual control.
