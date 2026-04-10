## Why

当前项目的社区检测功能依赖 `graspologic` 库，但它存在严重的兼容性问题：

1. **PyTorch 2.x 不兼容**：`graspologic` 依赖 POT (Python Optimal Transport)，而 POT 与 PyTorch 2.x 存在已知冲突（`torch.Tensor` 被移除），导致 `GRASPOLOGIC_AVAILABLE` 经常为 `False`
2. **6 个测试被跳过**：因上述兼容性问题，`TestCommunityDetectorRunHierarchicalLeiden` 和 `TestCommunityDetectorDetectCommunities` 两个测试类被 `@pytest.mark.skipif` 跳过
3. **依赖链过重**：`graspologic` → `graspologic-native` → 间接依赖 `torch`/`scipy`/`numpy` 等重型库
4. **SyntaxWarning 噪音**：需在 `pytest.ini` 和 `pyproject.toml` 中配置 `ignore::SyntaxWarning:graspologic` 来抑制无效转义序列警告

项目中已依赖 `leidenalg`（>=0.11.0）和 `python-igraph`（>=0.11.0），且 `IncrementalCommunityUpdater` 已成功使用它们进行增量社区检测。统一使用 `leidenalg` 可消除兼容性问题、减轻依赖负担、恢复被跳过的测试。

## What Changes

- 将 `CommunityDetector._run_hierarchical_leiden` 从调用 `graspologic.partition.hierarchical_leiden` 替换为基于 `leidenalg.find_partition` + `igraph` 的递归层次化实现
- 移除 `GRASPOLOGIC_AVAILABLE` 守卫及相关 try/except 导入逻辑
- **BREAKING**: 移除 `graspologic` 依赖（`pyproject.toml` 中删除 `"graspologic>=3.4.4"`）
- 移除 `pytest.ini` 和 `pyproject.toml` 中针对 graspologic/hyppo 的 SyntaxWarning 过滤器
- 移除测试中所有 `@pytest.mark.skipif(not GRASPOLOGIC_AVAILABLE, ...)` 标记
- 更新 `docs/ARCHITECTURE.md` 中相关描述

## Capabilities

### New Capabilities

- `hierarchical-leiden-igraph`: 使用 `leidenalg` + `igraph` 实现递归层次化 Leiden 社区检测算法，替代 graspologic 的 `hierarchical_leiden` 函数。核心行为：对超过 `max_cluster_size` 的社区递归提取子图并重新分区，生成多级层次结构

### Modified Capabilities

## Impact

- **源码**: `src/modules/graph_store/community_detector.py`、`src/modules/knowledge/community/detector.py`
- **依赖**: `pyproject.toml` 移除 `graspologic>=3.4.4`，保留 `leidenalg>=0.11.0` 和 `python-igraph>=0.11.0`
- **测试**: `tests/unit/modules/graph_store/test_community_detector.py`、`tests/performance/test_community_detection_performance.py`
- **配置**: `pytest.ini`、`pyproject.toml` 的 `filterwarnings`
- **文档**: `docs/ARCHITECTURE.md`
