# fasttext-wheel 供应链替换评估（T033）

> 变更：`comprehensive-optimization` · 日期：2026-09-14 · 结论先行：**推荐维持 fasttext-wheel 短期锁定 + 中期迁移到 ONNX Runtime 推理**，不建议替换为 `fasttext-predict`。

## 1. 现状

- 依赖：`fasttext-wheel>=0.9.2`（pyproject.toml），用于语言识别/分类特征（ingestion 分类级联的 ML 分支）。
- 风险：`fasttext` 官方包 2019 年后基本停滞（Facebookresearch 维护重心转移）；`fasttext-wheel` 是社区预编译分发，无官方安全响应通道；构建链（setuptools/wheel 兼容性）在新 Python 版本上易碎。
- 实际使用面：仅推理（load 模型 + predict），无训练需求——这决定了替换成本的下限很低。

## 2. 候选替换方案对比

| 方案 | 维护状态 | 迁移成本 | 性能 | 风险 | 备注 |
|------|---------|---------|------|------|------|
| **A. fasttext-predict** | 低活跃（个人维护） | 低（API 近似） | 相当 | 中：单点维护，替代后同样面临停滞 | 仅推理精简版，仍是 fasttext 内核 |
| **B. 官方 fasttext + 构建约束** | 停滞 | 低 | 相当 | 高：源码编译在 Windows/Py3.12 常失败 | 当初选 wheel 版就是为了绕开编译 |
| **C. ONNX Runtime 推理** | 活跃（LF AI 基金会） | 中 | 更优（量化/图优化） | 低：运行时成熟 | 需一次性模型导出脚本 |
| **D. 移除 fasttext，改用轻量启发式/keyboard 库** | — | 中 | 最优 | 中：识别质量回归需验证 | 项目已有级联分类器兜底（规则层） |

## 3. 推荐结论

**短期（本变更内）**：锁定 `fasttext-wheel` 当前可用版本，不立即替换——它不在关键安全路径上（仅内容分类特征），且替换的回归验证成本 > 当前风险敞口。

**中期（1-2 个迭代，另立变更）**：按方案 C 执行：
1. 导出：用一次性脚本将现有 `.bin` 模型导出为 ONNX（fasttext 官方提供 `export` 能力，或经由 `optimum` 转换）。
2. 推理层替换：`LanguageIdentifier` 接口不变，实现切换到 `onnxruntime.InferenceSession`。
3. 依赖替换：`fasttext-wheel` → `onnxruntime`（OTel 自动埋点任务 T029 已引入 onnxruntime 相邻生态，边际成本降低）。
4. 回归验证：用生产采样语料对比新旧语言识别一致率，阈值 ≥99% 方可切换。

## 4. 回归验证方案（中期实施时）

- 数据：从 articles_core 抽样 1 万条（按 category 分层），人工标注语言标签子集 500 条。
- 指标：语言识别一致率（新旧实现输出对比）、500 条人工子集准确率。
- 门禁：一致率 <99% 时逐条分析差异样本，确认无误伤再合并。
