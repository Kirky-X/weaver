"""
内容处理域模块

合并了原 pipeline、nlp 模块，提供文章处理流水线：
- 五阶段编排
- 分类、清洗、向量化、分析等处理节点
- spaCy NER 实体提取

公开 API:
- Pipeline: 处理流水线
- PipelineConfig: 流水线配置
- PipelineState: 流水线状态
- SpacyExtractor: spaCy NER 提取器
"""

from modules.processing.nlp.spacy_extractor import SpacyEntity, SpacyExtractor

# 临时兼容导出 - Phase 3 完成后移除
from modules.processing.pipeline.config import PipelineConfig
from modules.processing.pipeline.graph import Pipeline
from modules.processing.pipeline.state import PipelineState

__all__ = [
    "Pipeline",
    "PipelineConfig",
    "PipelineState",
    "SpacyEntity",
    "SpacyExtractor",
]
