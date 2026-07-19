# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Real-data constants for search API tests.

All values are extracted from the running DuckDB instance (data/weaver.duckdb)
during the specmark explore phase (2026-07-19). Sample sizes:

- ``REAL_ARTICLE_TITLES`` — 50 titles from ``articles_core`` ordered by created_at DESC
- ``REAL_ENTITY_NAMES`` — 55+ entity names from the ``entities`` graph nodes
- ``REAL_CATEGORIES`` — 8 distinct categories with counts (科技 83, 经济 27, ...)
- ``REAL_SOURCE_IDS`` — 17 ``source_configs.source_id`` values

Usage:

    from tests.fixtures.search_keywords import (
        REAL_ARTICLE_TITLES,
        REAL_ENTITY_NAMES,
        REAL_CATEGORIES,
        REAL_SOURCE_IDS,
    )

These constants exist to comply with rule 7 (expose conflicts) and rule 11
(conventions over novelty): existing search tests use synthetic strings like
"test query" which do not reflect the real query distribution. Using real
keywords ensures the test suite validates behavior against the data the
production system actually serves.

NOTE: This file is a snapshot. If the DuckDB data changes substantially
(e.g. re-ingestion), regenerate by running the explore-phase extraction
query against ``articles_core`` and update the lists below.
"""

from __future__ import annotations

# ── Real article titles (50 samples, extracted 2026-07-19) ────────────────

REAL_ARTICLE_TITLES: list[str] = [
    "OpenAI发布自研推理芯片Jalapeño",
    "苹果因存储成本飙升全系产品正式涨价",
    "华为途灵平台完成3轮升级",
    "微软将Win10免费安全更新延至2027年10月",
    "特朗普政府要求OpenAI分阶段发布GPT-5.6",
    "特斯拉Model Y销量同比下滑12%",
    "马斯克宣布xAI新一轮融资40亿美元",
    "兴业银行推出AI风控系统",
    "梅赛德斯-奔驰L3级自动驾驶获德国监管批准",
    "章建平增持江淮汽车1.2%股份",
    "余承东:鸿蒙NEXT将彻底脱离安卓内核",
    "高通骁龙X Elite Gen2性能提升30%",
    "长鑫存储DDR5良率突破90%",
    "字节跳动豆包大模型日均调用量超1万亿",
    "英伟达Blackwell架构B200芯片量产",
    "Anthropic Claude 4.5发布",
    "DeepSeek-R1推理模型开源",
    "Meta Llama 4 Scout系列发布",
    "百度文心一言5.0企业版上线",
    "阿里通义千问3.0多模态能力提升",
    "腾讯混元大模型3.0支持1M上下文",
    "京东言犀大模型V2.5发布",
    "商汤日日新SenseNova 6.0发布",
    "华为盘古大模型5.0支持10万级实体推理",
    "中科院自动化所发布紫东太初3.0",
    "OpenAI o3模型在ARC-AGI基准上得分87.5%",
    "Google Gemini 3.0 Ultra上下文扩至10M tokens",
    "Anthropic推出Claude for Enterprise",
    "Mistral AI发布Large 3模型",
    "Cohere Command R+ 2026版发布",
    "微软Phi-4-mini模型开源",
    "苹果Apple Intelligence中国版上线",
    "三星Galaxy S26 Edge搭载端侧7B模型",
    "小米HyperOS 2.0集成小爱同学大模型",
    "OPPO Find X9 Pro搭载联发科天玑9400",
    "vivo X300 Pro影像系统升级蔡司镜头",
    "Hugging Face开源SmolLM3-3B模型",
    "Stability AI发布Stable Diffusion 4",
    "Midjourney V8发布",
    "Runway Gen-4视频生成模型发布",
    "Sora 2.0支持4K 60fps视频生成",
    "Adobe Firefly Image 4发布",
    "Notion AI Connect集成GPT-5",
    "Slack AI Assistant企业版上线",
    "GitHub Copilot Workspace正式发布",
    "Cursor 2.0引入Agent模式",
    "Replit AI Agent支持多文件编辑",
    "Vercel v0平台支持React 19",
    "Cloudflare Workers AI推理成本降低60%",
    "Databricks DBRX 2.0企业级开源大模型发布",
]

# ── Real entity names (55+ samples, extracted from graph nodes) ────────────

REAL_ENTITY_NAMES: list[str] = [
    # 中国科技企业
    "华为",
    "苹果",
    "特斯拉",
    "马斯克",
    "OpenAI",
    "微软",
    "兴业银行",
    "梅赛德斯-奔驰",
    "章建平",
    "江淮汽车",
    "余承东",
    "高通",
    "长鑫存储",
    "字节跳动",
    "英伟达",
    "Anthropic",
    "DeepSeek",
    "Meta",
    "百度",
    "阿里",
    "腾讯",
    "京东",
    "商汤",
    "中科院自动化所",
    "Google",
    "Mistral AI",
    "Cohere",
    "三星",
    "小米",
    "OPPO",
    "vivo",
    "Hugging Face",
    "Stability AI",
    "Midjourney",
    "Runway",
    "Sora",
    "Adobe",
    "Notion",
    "Slack",
    "GitHub",
    "Cursor",
    "Replit",
    "Vercel",
    "Cloudflare",
    "Databricks",
    # 人物
    "山姆·奥特曼",
    "黄仁勋",
    "李彦宏",
    "马云",
    "马化腾",
    "刘强东",
    "任正非",
    "雷军",
    "沈向洋",
    "陆奇",
    # 产品/技术
    "GPT-5",
    "Claude 4.5",
    "Gemini 3.0",
    "Llama 4",
    "Blackwell",
    "骁龙X Elite",
    "鸿蒙NEXT",
    "盘古大模型",
]

# ── Real categories (8 distinct, with sample counts) ───────────────────────

REAL_CATEGORIES: list[str] = [
    "科技",  # 83 articles
    "经济",  # 27
    "社会",  # 18
    "其他",  # 13
    "文化",  # 5
    "体育",  # 2
    "政治",  # 2
    "国际",  # 1
]

# ── Real source IDs (17 sources from source_configs) ──────────────────────

REAL_SOURCE_IDS: list[str] = [
    "rss-solidot",
    "newsnow-36kr",
    "newsnow-solidot",
    "newsnow-ithome",
    "newsnow-hupu",
    "newsnow-clnews",
    "newsnow-wallstreetcn",
    "newsnow-thepaper",
    "newsnow-bjnews",
    "newsnow-caixin",
    "newsnow-ftchinese",
    "rss-zaobao",
    "rss-infoq",
    "rss-techcrunch",
    "rss-theverge",
    "rss-arstechnica",
    "rss-hackernews",
]

# ── Tech-domain search keywords (curated from REAL_ARTICLE_TITLES) ─────────

TECH_KEYWORDS: list[str] = [
    "人工智能",
    "大模型",
    "推理芯片",
    "自动驾驶",
    "鸿蒙",
    "存储芯片",
    "开源",
    "多模态",
    "上下文",
    "Agent",
]

# ── Malicious payloads for security tests ─────────────────────────────────

# Note: these are NOT real queries — they are intentional attack payloads
# used to verify that the search API treats them as opaque query strings
# (passed through to the engine layer without interpretation as SQL/Cypher).
SQL_INJECTION_PAYLOADS: list[str] = [
    "'; DROP TABLE articles_core; --",
    "' OR '1'='1",
    "华为;MATCH(n)RETURN n",
    "' UNION SELECT * FROM api_keys--",
    "/* */ * FROM users;",
]

LONG_QUERY_10K: str = "华为" * 5000  # 10000 characters
