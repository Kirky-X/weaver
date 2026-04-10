## 1. API Endpoints

- [x] 1.1 修改 `src/api/endpoints/search.py:126` — `embed()` → `embed_default()`

## 2. Knowledge Search Context

- [x] 2.1 修改 `src/modules/knowledge/search/context/global_context.py:223` — `embed()` → `embed_default()`
- [x] 2.2 修改 `src/modules/knowledge/search/context/ladybug_global_context.py:195` — `embed()` → `embed_default()`

## 3. Knowledge Graph

- [x] 3.1 修改 `src/modules/knowledge/graph/community_report_generator.py:416` — `embed()` → `embed_default()`

## 4. Processing Nodes

- [x] 4.1 修改 `src/modules/processing/nodes/entity_extractor.py:92` — `embed()` → `embed_default()`
- [x] 4.2 修改 `src/modules/processing/nodes/entity_extractor.py:181` — `embed()` → `embed_default()`
- [x] 4.3 修改 `src/modules/processing/nodes/re_vectorize.py:36` — `embed()` → `embed_default()`
- [x] 4.4 修改 `src/modules/processing/nodes/vectorize.py:32` — `embed()` → `embed_default()`

## 5. Verification

- [x] 5.1 运行 `temp/test_all_apis.py` 验证所有端点返回 200
- [x] 5.2 确认无硬编码标签残留：`grep -rn "embedding\.aiping\." src/ --include="*.py"`
- [x] 5.3 重启服务验证 `search_articles` 端点正常工作