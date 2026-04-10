## 1. TemporalParser 死代码清理

- [x] 1.1 删除 `src/modules/knowledge/search/temporal/` 目录
- [x] 1.2 从 `src/modules/knowledge/search/intent/router.py` 移除 `TemporalParser` 导入
- [x] 1.3 从 `IntentRouter.__init__` 移除 `_temporal` 属性及相关参数
- [x] 1.4 更新 `src/modules/knowledge/search/temporal/__init__.py`（删除后无需更新，目录已删除）

## 2. pyproject.toml 依赖修正

- [x] 2.1 彻底删除 langchain 系列依赖声明（移除注释行）
- [x] 2.2 将 flashrank 从注释状态移至 `[project.optional-dependencies]`
- [x] 2.3 添加 `search-enhancement` 可选依赖组定义
- [x] 2.4 更新依赖版本锁定文件 `uv.lock`

## 3. 构建配置清理

- [x] 3.1 从 `scripts/build_nuitka.py` 删除已注释的 langchain include 条目
- [x] 3.2 验证构建配置无遗留引用

## 4. 验证与测试

- [x] 4.1 运行 `uv sync` 验证依赖解析成功
- [x] 4.2 运行 `uv pip check` 验证无冲突
- [x] 4.3 运行单元测试验证无回归 `pytest tests/ -v --tb=short`
- [x] 4.4 验证 HybridSearchEngine 优雅降级机制正常工作

## 5. 文档更新

- [x] 5.1 更新 README.md 说明可选依赖安装方式
- [x] 5.2 确保项目文档反映 langchain 移除