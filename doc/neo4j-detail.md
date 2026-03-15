Q1：Neo4j 约束要求 (e.canonical_name, e.type) 唯一，但现有 article 表没有唯一约束。
A1：这是一个**刻意的设计不对称**，两者约束不同是合理的，原因如下：

---

## Neo4j 为什么要加唯一约束

Neo4j 存的是**实体**，实体天然要求去重。"习近平"+"人物"在现实世界只对应一个节点，如果没有唯一约束，并发写入时多篇文章同时发现"习近平"不存在，就会创建出多个重复节点，图谱的关系连接会碎片化，`RELATED_TO` 边会指向不同的孤立节点，图遍历结果就完全错了。所以 `MERGE` + 唯一约束是 Neo4j 这类图数据库的标准写法，约束本身也是 `MERGE` 的匹配依据。

---

## articles 表为什么不加同类约束

articles 存的是**资讯事件的一次报道**，它天然允许多条。同一个事件可以有新华社、Reuters、36kr 三篇报道，它们的 `title` 相近但不完全相同，`body` 各有侧重，`source_url` 各不相同。如果在 articles 上加 `(title, category)` 唯一约束，就等于强制说"同一事件只能存一篇"，这与 Merger 的设计目标矛盾——Merger 的职责正是在多篇存在的前提下做语义合并，而不是靠数据库约束直接拒绝写入。

articles 表已有的唯一约束是 `source_url`，这才是正确粒度：**同一篇原始文章不重复采集**，但**同一事件的不同来源报道允许共存**，由 Merger 逻辑决定是否合并。

---

## 真正需要注意的一个潜在问题

文档里 `merged_into` 是自引用 FK，已有 `chk_no_self_merge` 约束防止自指，但没有防止**循环引用**（A→B→A）。这个问题靠数据库约束无法直接解决，需要在 `article_repo` 的 `resolve_final_merge_target` 方法里做链路追踪，检测环并截断，或者在 persist 节点写入前强制铺平为直接指向链尾，确保 `merged_into` 永远只有一跳深度。

Q2：neo4j需要如何处理？
A2：Neo4j 这边有两个独立问题需要处理：

---

## 问题一：并发写入竞态

`MERGE` + 唯一约束虽然能保证最终只有一个节点，但在高并发下两个事务同时执行 `MERGE` 找不到节点、同时尝试创建，Neo4j 会让其中一个事务等待，另一个报 `ConstraintValidationFailed`。

**处理方式是在 `entity_resolver` 里加重试：**

```python
# modules/graph_store/entity_resolver.py

MAX_MERGE_RETRIES = 3

async def _create_entity(self, entity: dict, embedding: list[float]) -> str:
    for attempt in range(MAX_MERGE_RETRIES):
        try:
            neo4j_id = await self._neo4j_repo.merge_entity(entity)
            await self._vector_repo.upsert_entity_vector(neo4j_id, embedding)
            return neo4j_id
        except ConstraintError:
            # 另一个并发事务已创建，直接查出来用
            if attempt == MAX_MERGE_RETRIES - 1:
                raise
            existing = await self._neo4j_repo.find_entity(
                canonical_name=entity["name"],
                type=entity["type"],
            )
            if existing:
                return existing["id"]
            await asyncio.sleep(0.05 * (attempt + 1))  # 指数退避
```

---

## 问题二：canonical_name 的确定时机

唯一约束的 key 是 `(canonical_name, type)`，但 `entity_extractor` 吐出来的实体名可能是别名，比如"苹果公司"和"Apple Inc."在不同文章里都出现，`entity_resolver` 靠向量召回判断是同一实体后，需要决定哪个是 `canonical_name`、哪个是 `alias`。

**当前文档没有明确这个决策逻辑，需要补充：**

```python
# modules/graph_store/neo4j/entity_repo.py

async def merge_entity(self, entity: dict, is_canonical: bool = False) -> str:
    """
    首次创建：用传入的 name 作为 canonical_name
    后续 MATCH 到已有节点：只追加 alias，不改 canonical_name
    is_canonical=True 时强制覆写（人工干预场景）
    """
    query = """
    MERGE (e:Entity {canonical_name: $canonical_name, type: $type})
    ON CREATE SET
        e.id          = $id,
        e.aliases     = [$name],
        e.description = $description,
        e.created_at  = datetime()
    ON MATCH SET
        e.aliases   = CASE
                        WHEN NOT $name IN e.aliases
                        THEN e.aliases + [$name]
                        ELSE e.aliases
                      END,
        e.updated_at = datetime()
    RETURN e.id AS id
    """
    # canonical_name 取第一次写入时的名称，后续不变
    # entity_resolver 负责在调用前统一 canonical_name
    ...
```

`entity_resolver` 里的决策规则：

```python
async def _resolve_canonical_name(
    self,
    query_name: str,
    candidates: list[dict],
) -> str:
    """
    规则（按优先级）：
    1. 候选节点已有 canonical_name → 沿用，不改变
    2. 候选节点来自权威来源（tier=1）→ 用权威来源的写法
    3. 都不满足 → 用中文名优先（系统面向中文场景）
    """
    if candidates:
        return candidates[0]["canonical_name"]  # 已有节点，沿用
    # 新节点，用传入名称
    return query_name
```

---

## 问题三：图数据老化时的孤儿节点

文档里的老化 Cypher 是 `DETACH DELETE` 掉旧 Article 节点，但 `DETACH DELETE` 会同时删除该节点的所有关系，包括 `MENTIONS` 关系。如果一个 Entity 节点的所有 `MENTIONS` 来源都被老化删掉了，这个 Entity 就变成孤儿节点——没有任何文章引用它，但它还留在图里，占空间且干扰向量召回。

**老化时需要联动清理孤儿 Entity：**

```cypher
// 第一步：删除旧 Article 节点（保留有后续文章的）
MATCH (a:Article)
WHERE a.publish_time < datetime() - duration({days: 90})
  AND NOT (a)-[:FOLLOWED_BY]->()
DETACH DELETE a;

// 第二步：清理孤儿 Entity（无任何 MENTIONS 指向）
MATCH (e:Entity)
WHERE NOT ()-[:MENTIONS]->(e)
  AND NOT (e)-[:RELATED_TO]-()   // 保留还有关系的实体
  AND NOT ()-[:RELATED_TO]->(e)
DELETE e;
```

同时 Postgres 的 `entity_vectors` 表也需要联动清理，否则孤儿实体的向量还会参与 ANN 召回：

```python
# modules/graph_store 补偿任务
async def cleanup_orphan_entity_vectors():
    # 查出所有 neo4j_id 仍存在于 Neo4j 的集合
    active_ids = await self._neo4j_repo.list_all_entity_ids()
    # 删除 entity_vectors 中已不存在的条目
    await self._vector_repo.delete_orphan_entity_vectors(active_ids)
```

这个补偿任务加入到每周的老化调度里，在 `archive_old_neo4j_nodes` 之后执行。