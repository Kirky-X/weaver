## ADDED Requirements

### Requirement: Level semantics compatibility with graspologic

**CRITICAL DISCOVERY**: graspologic 的 `hierarchical_leiden` 与递归子图分裂实现产生**相反的 level 语义**：

| 实现方式 | Level 0 含义 | Level N 含义 | 递增方向 |
|---------|-------------|-------------|---------|
| **graspologic** | Leaf（最细粒度/最小社区） | Root（最抽象/最大社区） | Leaf → Root |
| **原始递归实现** | Initial partition（最大社区） | Finer split（更细社区） | Root → Leaf（错误！） |

下游消费者 `_build_communities_from_clusters`（第340-353行）期望 graspologic 语义：
```python
# Process levels from 0 (leaf) to max
for level in sorted(level_clusters.keys()):
    ...
    if cluster_id in parent_map:
        parent_key = (level + 1, parent_map[cluster_id])  # parent 在 level + 1 层
```

**解决方案**：递归函数 SHALL 在生成 HierarchicalCluster 时使用**反转的 level 计算**：
- `final_level = max_depth - current_recursion_depth`
- 或在收集完所有结果后统一重新映射 level

#### Scenario: Level numbering reversed correctly
- **WHEN** 递归深度为 0（初始分区）且 `max_depth=10`
- **THEN** 该层级的 cluster 被标记为 `level=10`（最接近 root）
- **AND** 递归深度为 1（第一次分裂）时，cluster 被标记为 `level=9`
- **AND** 最终叶子社区的 level 为 `0`

#### Scenario: Parent-child level relationship preserved
- **WHEN** 子社区在 level=L，其父社区在 level=L+1
- **THEN** `_build_communities_from_clusters` 能正确找到 `parent_key = (L+1, parent_cluster_id)`
- **AND** `parent_community_id` 正确指向父社区的 UUID

### Requirement: Recursive hierarchical Leiden partitioning

The `_run_hierarchical_leiden` 方法 SHALL 使用 `leidenalg.find_partition` 配合 `igraph` 子图递归实现层次化社区检测。 给定边列表和 `max_cluster_size` 参数，方法 SHALL 对全图运行 Leiden 分区，然后对超过 `max_cluster_size` 的社区递归提取子图并重新分区。

**关键约束**：level 编号必须遵循 graspologic 语义（level 0 = leaf）。

#### Scenario: Small graph with no clusters exceeding max_cluster_size
- **WHEN** 输入边列表 `[(A,B,1.0), (B,C,1.0), (C,D,1.0)]` 且 `max_cluster_size=10`
- **THEN** 系统返回 level=0 的 `HierarchicalCluster` 列表，所有节点的 `is_final_cluster=True`，不产生更深层级

#### Scenario: Large cluster triggers recursive split
- **WHEN** 输入边列表产生一个超过 `max_cluster_size` 的社区（如 15 个节点在同一个社区），`max_cluster_size=10`）
- **THEN** 系统返回高 level 的 cluster 中该大社区的 `is_final_cluster=False`
- **AND** 返回低 level 的子社区，子社区的 `parent_cluster` 指向高 level 的父社区 ID
- **AND** 子社区的 level < 父社区的 level（遵循 graspologic 语义）

#### Scenario: Empty edge list
- **WHEN** 输入空边列表 `[]`
- **THEN** 系统返回空列表 `[]`

#### Scenario: Seed reproducibility
- **WHEN** 使用相同 seed=42 和相同输入运行两次 `_run_hierarchical_leiden`
- **THEN** 两次返回的 cluster 列表在结构和层次上完全一致

#### Scenario: Recursion depth limit
- **WHEN** 递归深度超过 `max_depth=10`
- **THEN** 系统停止递归，将当前层级所有节点标记为 `is_final_cluster=True`

### Requirement: igraph graph construction from edge list

系统 SHALL 将 `list[tuple[str, str, float]]` 格式的边列表转换为 `igraph.Graph` 对象。 转换过程 SHALL 维护节点名到索引的双向映射，边权重 SHALL 作为 igraph 边属性 `"weight"` 传递。

#### Scenario: Weighted edges preserved
- **WHEN** 输入 `[(A, B, 2.5), (B, C, 1.0)]`
- **THEN** igraph 图的边 `A-B` 权重为 2.5，`B-C` 权重为 1.0

#### Scenario: Duplicate edges normalized
- **WHEN** 输入包含重复边 `[(A, B, 1.0), (B, A, 0.5)]`
- **THEN** igraph 图对重复边正确处理（归一化方向、保留最高权重）

### Requirement: igraph subgraph API behavior (validated)

**igraph `subgraph()` 方法验证结果**（通过 `/tmp/test_leidenalg.py` 测试确认）：

| 操作 | 行为验证 | 结果 |
|------|---------|------|
| `g.subgraph(vertices)` | 顶点重新编号为 0..N-1 | ✅ 确认 |
| `vertex['name']` 属性 | 自动继承到子图 | ✅ 确认 |
| `edge['weight']` 属性 | 自动继承到子图 | ✅ 确认 |
| 单顶点子图 `subgraph([0])` | 返回 `membership=[0]` | ✅ 确认 |
| 断连图（无边） | 每节点独立成簇 | ✅ 确认 |
| 无 weight 属性图 | `ModularityVertexPartition` 正常工作 | ✅ 确认 |

**关键 API 用法**：
```python
# leidenalg 分区调用
partition = leidenalg.find_partition(
    g,
    leidenalg.ModularityVertexPartition,
    weights="weight",  # 使用边属性名（不是属性值列表）
    seed=42,
)

# 获取簇成员列表
members = partition[cid]  # 返回属于簇 cid 的顶点索引列表

# 获取全局 membership 映射
membership = partition.membership  # list[int]，索引 i 的顶点属于簇 membership[i]

# 提取子图
sub_g = g.subgraph(members)  # 顶点重新编号，属性继承

# 获取子图顶点的原始名称
sub_node_names = [g.vs[v]['name'] for v in members]  # 映射回原始节点名
```

#### Scenario: Subgraph preserves vertex['name'] attribute
- **WHEN** 原图顶点有 `vertex['name'] = "entity_123"` 属性
- **AND** 使用 `g.subgraph([0, 1, 2])` 提取子图
- **THEN** 子图顶点 `sub_g.vs[0]['name']` 返回原图 `g.vs[0]['name']` 的值
- **AND** 子图顶点 `sub_g.vs[1]['name']` 返回原图 `g.vs[1]['name']` 的值

#### Scenario: Subgraph preserves edge['weight'] attribute
- **WHEN** 原图边有 `edge['weight'] = 2.5` 属性
- **AND** 该边的两端顶点都在子图中
- **THEN** 子图对应边继承相同的 weight 属性值

#### Scenario: Single vertex subgraph partition
- **WHEN** 子图仅包含一个顶点（无边）
- **AND** 运行 `leidenalg.find_partition`
- **THEN** 返回 `partition.membership = [0]`，单顶点属于簇 0

#### Scenario: Disconnected graph partition
- **WHEN** 图有 3 个顶点但无边（完全断连）
- **AND** 运行 `leidenalg.find_partition`
- **THEN** 返回 `partition.membership = [0, 1, 2]`，每顶点独立成簇

### Requirement: Subgraph node name remapping

在递归分裂时，igraph 的 `subgraph()` 方法 SHALL 重新编号顶点为 0..N-1。 实现 SHALL 维护 `node_names` 列表，将子图顶点索引映射回原始节点名。

#### Scenario: Subgraph index remapping
- **WHEN** 全图有节点 `[A, B, C, D, E]`，子图包含 `[B, C, D]`（子图索引 0→B, 1→C, 2→D）
- **THEN** 子图分区结果的节点名正确映射回 `B`, `C`, `D`

#### Scenario: Subgraph edge weights preserved
- **WHEN** 子图提取时
- **THEN** 子图边继承原始图的权重属性

### Requirement: Parent-cluster mapping logic

递归分裂时，parent_cluster 映射 SHALL 通过在递归调用时传递父簇 ID 实现。

**映射逻辑验证**：

```
递归层级结构:
  Level 10 (root/初始分区): [Cluster 0, Cluster 1, Cluster 2]
    Cluster 0 超过 max_cluster_size，需要分裂
    ↓ 递归调用（depth=1）
  Level 9 (第一次分裂): [Cluster 0_0, Cluster 0_1, Cluster 0_2]
    Cluster 0_0 超过 max_cluster_size，继续分裂
    ↓ 递归调用（depth=2）
  Level 8 (第二次分裂): [Cluster 0_0_0, Cluster 0_0_1]
    ...
  Level 0 (leaf): 最终稳定社区
```

**parent_cluster 映射实现要点**：
1. 递归函数参数包含 `parent_cluster_id: int`
2. 每个生成的 HierarchicalCluster 的 `parent_cluster` 设置为传入的 `parent_cluster_id`
3. 当递归分裂一个簇时，传入该簇的 ID 作为子簇的 `parent_cluster_id`

#### Scenario: Parent cluster ID passed correctly
- **WHEN** Level 10 的 Cluster 0（包含节点 [A, B, C, D, E, F]）超过 `max_cluster_size=5`
- **AND** 递归分裂产生 Level 9 的 Cluster 0_0（包含节点 [A, B, C]）和 Cluster 0_1（包含节点 [D, E, F]）
- **THEN** Cluster 0_0 的 `parent_cluster=0`
- **AND** Cluster 0_1 的 `parent_cluster=0`

#### Scenario: Nested parent chain preserved
- **WHEN** 三层递归分裂：Level 10 → Level 9 → Level 8
- **AND** Level 8 的 Cluster 来自 Level 9 的 Cluster 2
- **AND** Level 9 的 Cluster 2 来自 Level 10 的 Cluster 5
- **THEN** Level 8 Cluster 的 `parent_cluster=2`（直接父簇）
- **AND** Level 9 Cluster 的 `parent_cluster=5`（其直接父簇）
- **AND** Level 10 Cluster 的 `parent_cluster=None`（root 层）

### Requirement: No graspologic dependency
        `CommunityDetector` 模块 SHALL NOT 导入或依赖 `graspologic` 库。 所有社区检测功能 SHALL 仅依赖 `leidenalg` 和 `igraph`。

#### Scenario: Module imports after migration
- **WHEN** 检查 `community_detector.py` 的导入语句
- **THEN** 文件中不存在任何 `from graspologic` 导入

#### Scenario: GRASPOLOGIC_AVAILABLE removed
- **WHEN** 检查模块级变量
- **THEN** 不存在 `GRASPOLOGIC_AVAILABLE` 变量
