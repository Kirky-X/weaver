# Import Path Changelog

## 模块重构导入路径变更

生成时间: 2026-04-10
分支: main (commit 60c2f69)

### Community 子模块 (`modules.knowledge.graph.community_*` → `modules.knowledge.graph.community.*`)

| 旧路径                                                  | 新路径                                               |
| ------------------------------------------------------- | ---------------------------------------------------- |
| `modules.knowledge.graph.community_detector`            | `modules.knowledge.graph.community.detector`         |
| `modules.knowledge.graph.community_models`              | `modules.knowledge.graph.community.models`           |
| `modules.knowledge.graph.community_repo`                | `modules.knowledge.graph.community.repo`             |
| `modules.knowledge.graph.community_report_generator`    | `modules.knowledge.graph.community.report_generator` |
| `modules.knowledge.graph.community_health_checker`      | `modules.knowledge.graph.community.health.checker`   |
| `modules.knowledge.graph.community_health_models`       | `modules.knowledge.graph.community.health.models`    |
| `modules.knowledge.graph.community_health_repo`         | `modules.knowledge.graph.community.health.repo`      |
| `modules.knowledge.graph.community_repair_service`      | `modules.knowledge.graph.community.repair_service`   |
| `modules.knowledge.graph.incremental_community_updater` | `modules.knowledge.graph.community.updater`          |

### Core/LLM 重组 (`core.llm.*` → `core.llm.{routing,config,resilience,validation,evaluation}.*`)

| 旧路径                      | 新路径                                 |
| --------------------------- | -------------------------------------- |
| `core.llm.token_budget`     | `core.llm.config.token_budget`         |
| `core.llm.config`           | `core.llm.config.config`               |
| `core.llm.live_config`      | `core.llm.config.live_config`          |
| `core.llm.circuit_breaker`  | `core.llm.resilience.circuit_breaker`  |
| `core.llm.pool`             | `core.llm.resilience.pool`             |
| `core.llm.metrics`          | `core.llm.resilience.metrics`          |
| `core.llm.router`           | `core.llm.routing.router`              |
| `core.llm.model_selector`   | `core.llm.routing.model_selector`      |
| `core.llm.smart_router`     | `core.llm.routing.smart_router`        |
| `core.llm.output_validator` | `core.llm.validation.output_validator` |
| `core.llm.eval_runner`      | `core.llm.evaluation.eval_runner`      |
| `core.llm.experience`       | `core.llm.evaluation.experience`       |

### Processing Nodes (`modules.processing.nodes.*` → `modules.processing.nodes.{extraction,classification,merging,quality,vectorization}.*`)

| 旧路径                                         | 新路径                                                        |
| ---------------------------------------------- | ------------------------------------------------------------- |
| `modules.processing.nodes.analyze`             | `modules.processing.nodes.extraction.analyze`                 |
| `modules.processing.nodes.entity_extractor`    | `modules.processing.nodes.extraction.entity_extractor`        |
| `modules.processing.nodes.classifier`          | `modules.processing.nodes.classification.classifier`          |
| `modules.processing.nodes.categorizer`         | `modules.processing.nodes.classification.categorizer`         |
| `modules.processing.nodes.credibility_checker` | `modules.processing.nodes.classification.credibility_checker` |
| `modules.processing.nodes.batch_merger`        | `modules.processing.nodes.merging.batch_merger`               |
| `modules.processing.nodes.cleaner`             | `modules.processing.nodes.quality.cleaner`                    |
| `modules.processing.nodes.quality_scorer`      | `modules.processing.nodes.quality.quality_scorer`             |
| `modules.processing.nodes.vectorize`           | `modules.processing.nodes.vectorization.vectorize`            |
| `modules.processing.nodes.re_vectorize`        | `modules.processing.nodes.vectorization.re_vectorize`         |

### Core/Security 重组 (`core.security.*` → `core.security.{crypto,validation}.*`)

| 旧路径                        | 新路径                                   |
| ----------------------------- | ---------------------------------------- |
| `core.security.signing`       | `core.security.crypto.signing`           |
| `core.security.validator`     | `core.security.validation.validator`     |
| `core.security.ssrf`          | `core.security.validation.ssrf`          |
| `core.security.malicious_url` | `core.security.validation.malicious_url` |

### API Endpoints (`api.endpoints.*` → `api.endpoints.{admin,graph,content}.*`)

| 旧路径                              | 新路径                                    |
| ----------------------------------- | ----------------------------------------- |
| `api.endpoints.admin`               | `api.endpoints.admin.admin`               |
| `api.endpoints.articles`            | `api.endpoints.content.articles`          |
| `api.endpoints.pipeline`            | `api.endpoints.content.pipeline`          |
| `api.endpoints.search`              | `api.endpoints.content.search`            |
| `api.endpoints.sources`             | `api.endpoints.content.sources`           |
| `api.endpoints.graph`               | `api.endpoints.graph.graph`               |
| `api.endpoints.graph_metrics`       | `api.endpoints.graph.graph_metrics`       |
| `api.endpoints.graph_visualization` | `api.endpoints.graph.graph_visualization` |

### Storage 新增

| 路径                       | 说明                                                                       |
| -------------------------- | -------------------------------------------------------------------------- |
| `modules.storage.base`     | 公共 Protocol 抽象 (ArticleRepository, EntityRepository, VectorRepository) |
| `modules.storage.adapters` | 统一导出                                                                   |

### Ingestion 新增

| 路径                                     | 说明                              |
| ---------------------------------------- | --------------------------------- |
| `modules.ingestion.deduplication.models` | TitleItem 数据模型                |
| `modules.ingestion.fetching.models`      | FetchError, CircuitOpenError 异常 |
