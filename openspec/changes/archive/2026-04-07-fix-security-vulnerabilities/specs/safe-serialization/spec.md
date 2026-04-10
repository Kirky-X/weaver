## ADDED Requirements

### Requirement: No pickle deserialization from untrusted sources

系统 MUST NOT 使用 pickle.load 或 pickle.loads 反序列化来自外部文件的数据。

#### Scenario: bm25_retriever.py avoids pickle

- **WHEN** 查看 `src/modules/knowledge/search/retrievers/bm25_retriever.py` 的索引加载代码
- **THEN** 不存在 `pickle.load(f)` 或 `pickle.loads(data)` 调用
- **AND** 索引数据使用 JSON 格式存储和加载

### Requirement: JSON serialization with integrity verification

需要持久化的索引数据 MUST 使用 JSON 格式，并包含签名验证机制。

#### Scenario: Index file integrity verification

- **WHEN** 加载 BM25 索引文件
- **THEN** 文件包含 HMAC 签名验证数据完整性
- **AND** 签名验证失败时抛出 IntegrityError
- **AND** 拒绝加载被篡改的索引文件

#### Scenario: JSON format for index storage

- **WHEN** 保存 BM25 索引到磁盘
- **THEN** 使用 `json.dump()` 写入 JSON 格式文件
- **AND** 文件包含签名字段 `signature`

### Requirement: Signing key management

签名密钥 MUST 通过环境变量配置，禁止硬编码。

#### Scenario: Signing key from environment

- **WHEN** 初始化 BM25Retriever
- **THEN** 签名密钥从 `INDEX_SIGNING_KEY` 环境变量获取
- **AND** 未配置时生成临时密钥并发出警告日志

#### Scenario: Development mode warning

- **WHEN** 运行在开发环境且未配置签名密钥
- **THEN** 日志输出 WARNING: Using generated signing key for development

### Requirement: Legacy index migration support

系统 SHALL 支持旧格式索引文件的迁移。

#### Scenario: Detect legacy pickle format

- **WHEN** 加载索引文件且文件非 JSON 格式
- **THEN** 检测为旧格式并记录 WARNING 日志
- **AND** 可选择迁移或拒绝加载

#### Scenario: Migrate on first load

- **WHEN** 检测到旧格式索引文件且用户配置允许迁移
- **THEN** 自动转换为 JSON+签名格式
- **AND** 保存新格式文件覆盖旧文件