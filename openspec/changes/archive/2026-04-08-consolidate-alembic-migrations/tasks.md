## 1. 创建新迁移文件

- [x] 1.1 创建 `src/alembic/versions/01_initial.py`，包含所有表定义
- [x] 1.2 添加 4 个 ENUM 类型定义（category_type, persist_status, emotion_type, vector_type）
- [x] 1.3 添加 pgvector 扩展和 HNSW 索引
- [x] 1.4 编写完整的 `downgrade()` 函数

## 2. 验证新迁移

- [x] 2.1 创建测试数据库，执行 `alembic upgrade head`
- [x] 2.2 验证所有 13 个表正确创建
- [x] 2.3 验证所有索引和约束正确创建
- [x] 2.4 对比新旧 schema 确保一致

## 3. 生产环境迁移

- [x] 3.1 备份生产数据库
- [x] 3.2 执行 `alembic stamp 01_initial`
- [x] 3.3 验证 `alembic current` 显示正确版本

## 4. 清理旧迁移

- [x] 4.1 删除 `src/alembic/versions/` 下除 `01_initial.py` 外的所有文件
- [x] 4.2 提交变更 (commit: 6eade0766807cc0137e0ba319dce253c8ea6f353)