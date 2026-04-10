## Context

当前项目的 `CommunityDetector` 使用 `graspologic.partition.hierarchical_leiden` 进行层次化社区检测。由于 graspologic 与 PyTorch 2.x 的 POT 兼容性问题，导致 `GRASPOLOGIC_AVAILABLE` 经常为 `False`，6 个核心测试被跳过，生产环境中的社区检测功能实际可能不工作。

项目中已存在 `leidenalg`（>=0.11.0）和 `python-igraph`（>=0.11.0）依赖，且 `IncrementalCommunityUpdater` 已成功使用它们进行增量社区检测（单层 Leiden + igraph 子图）。本次变更将统一两个模块的社区检测实现，全部使用 leidenalg + igraph。

**关键约束**：
- 必须保持 `_run_hierarchical_leiden` 的输出格式不变（`list[HierarchicalCluster]`）
- 下游消费者 `_build_communities_from_clusters` 和 `_calculate_modularity` 不需要修改
- 存在两份重复文件（DDD 重构遗留）：`graph_store/community_detector.py` 和 `knowledge/community/detector.py`

## Goals / Non-Goals

**Goals:**

- 用 leidenalg + igraph 替换 graspologic 实现层次化 Leiden 社区检测
- 消除 graspologic 的 PyTorch 兼容性问题
- 恢复当前被跳过的 6 个社区检测测试
- 移除 graspologic 依赖链，减轻项目依赖负担
- 保持 `HierarchicalCluster` 输出格式完全兼容

**Non-Goals:**

- 不统一两份重复的 detector 文件（属于 DDD 重构的遗留清理，单独处理）
- 不修改 `IncrementalCommunityUpdater`（已使用 leidenalg）
- 不修改 `_build_communities_from_clusters` 或 `_calculate_modularity` 的逻辑
- 不引入新的社区检测算法或改变社区检测的语义

## Decisions

### Decision 1: 递归子图分裂实现层次化

**选择**: 对超过 `max_cluster_size` 的社区，提取 igraph 子图并递归调用 `leidenalg.find_partition`

**替代方案**:
- A) 使用 `leidenalg.CPMVertexPartition` 配合不同 `resolution_parameter` 生成多粒度分区 → 需要经验调参，且层次结构与 graspologic 行为不一致
- B) 仅使用单层分区，放弃层次结构 → 丢失层次信息，影响 Global Search 等依赖多级社区的搜索策略

**理由**: 递归子图分裂精确模拟了 graspologic `hierarchical_leiden` 的行为——先做一次全图 Leiden 分区，然后对大社区递归处理。这种方式：
1. 层次结构自然（只有真正过大的社区才被分裂）
2. 不需要调参
3. 代码逻辑清晰（~60-80 行）
4. 与 `IncrementalCommunityUpdater` 的模式一致

### Decision 2: 使用 `leidenalg.ModularityVertexPartition`

**选择**: 使用 `ModularityVertexPartition` 作为分区类型（与 IncrementalCommunityUpdater 一致）

**替代方案**: `RBConfigurationVertexPartition`（考虑节点度）、`CPMVertexPartition`（恒Resolution 参数）

**理由**: 与现有代码风格统一。ModularityVertexPartition 是最常用的社区检测分区类型，适合无向加权图。

### Decision 3: 递归深度限制为 10

**选择**: 设置 `max_depth=10` 硬限制防止无限递归

**理由**: 实际场景中层次通常为 2-4 层（max_cluster_size=10 时），10 层远超实际需要。即使极端情况（万级节点），每层至少二分，10 层足以覆盖 2^10=1024 个子社区。

### Decision 4: 保持接口签名不变

**选择**: `_run_hierarchical_leiden(edges, max_cluster_size, seed)` 签名保持不变，仅修改内部实现

**理由**: 最小化变更范围，确保 `detect_communities()` 公共接口完全不受影响。

### Decision 5: Level 编号反转策略

**选择**: 在递归函数中使用 `level = max_depth - current_depth` 反转 level 编号

**替代方案**:
- A) 收集完所有结果后统一重新映射 level → 需要额外的后处理步骤，增加复杂度
- B) 改变下游消费者逻辑适配新的 level 语义 → 破坏性变更，影响范围更大

**理由**: 在递归函数内部直接反转 level 编号是最简洁的解决方案：
1. 不需要额外的后处理步骤
2. 不影响下游消费者逻辑
3. 代码逻辑清晰，易于理解
4. `max_depth=10` 时，递归深度 0 → level 10，递归深度 10 → level 0

## Risks / Trade-offs

**[CRITICAL: Level 语义不匹配]** → graspologic 的 `hierarchical_leiden` 与递归子图分裂产生**相反的 level 语义**：
- **graspologic**: level 0 = leaf（最细粒度），level N > 0 = root（更抽象）
- **递归实现**: level 0 = initial partition（大社区），level 1 = finer split（更细粒度）

下游消费者 `_build_communities_from_clusters`（第340-353行）期望 graspologic 语义：
```python
# Process levels from 0 (leaf) to max
for level in sorted(level_clusters.keys()):
    ...
    parent_key = (level + 1, parent_map[cluster_id])  # parent 在 level + 1 层
```

**解决方案**：递归函数 SHALL 使用反转的 level 计算：
```python
def _recursive_partition(g, node_names, max_cluster_size, seed, depth=0, parent_cluster_id=None):
    max_depth = 10
    current_level = max_depth - depth  # 反转 level 编号
    # ... 分区逻辑 ...
    for node_idx, cluster_id in enumerate(partition.membership):
        clusters.append(HierarchicalCluster(
            node=node_names[node_idx],
            cluster=cluster_id,
            level=current_level,  # 反转后的 level
            parent_cluster=parent_cluster_id,
            is_final_cluster=len(partition[cluster_id]) <= max_cluster_size,
        ))
```

**[igraph 子图节点索引重映射]** → igraph 的 `subgraph()` 方法会重新编号顶点为 0..N-1。需要维护 `node_names` 列表将子图索引映射回原始节点名。实测验证：`subgraph()` 自动继承 `vertex['name']` 和 `edge['weight']` 属性。

**[cluster ID 跨层级冲突]** → 不同递归层级的 cluster ID 可能重复（都是 0, 1, 2...）。但下游消费者 `_build_communities_from_clusters` 通过 `(level, cluster)` 二元组分组，天然处理了此问题。

**[递归过度分裂导致社区过小]** → 设置 `max_cluster_size` 作为分裂阈值，且只在社区节点数超过阈值时递归。`is_final_cluster=True` 标记不再分裂的叶子社区。

**[graspologic 和 leidenalg 结果不完全一致]** → 两者都实现 Leiden 算法，但随机种子、分区初始化等细节可能不同。社区划分在结构上等价（都是高质量分区），但具体边界可能有差异。这不影响功能正确性，但需在测试中避免硬编码特定分区结果。
