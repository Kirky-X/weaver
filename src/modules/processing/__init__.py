"""
内容处理域模块

合并了原 pipeline、nlp 模块,提供文章处理流水线:
- 五阶段编排
- 分类、清洗、向量化、分析等处理节点
- spaCy NER 实体提取

公开 API:
- Pipeline: 文章处理流水线
- SpacyExtractor: spaCy NER 提取器
- SpacyEntity: spaCy 实体数据类
"""

from modules.processing.nlp.spacy_extractor import SpacyEntity, SpacyExtractor
from modules.processing.pipeline.graph import Pipeline

__all__ = [
    "Pipeline",
    "SpacyEntity",
    "SpacyExtractor",
]
