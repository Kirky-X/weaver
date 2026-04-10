## MODIFIED Requirements

### Requirement: No security vulnerabilities in dependencies

系统 SHALL not have known security vulnerabilities in its dependencies.

#### Scenario: Bandit scan passes

- **WHEN** 运行 `bandit -r src/`
- **THEN** no HIGH or CRITICAL issues SHALL be reported

#### Scenario: SQL injection detection

- **WHEN** 运行 Bandit 安全扫描
- **THEN** 检测 f-string 用于 SQL/Cypher 查询的情况
- **AND** 报告为 HIGH 级别漏洞

#### Scenario: Pickle deserialization detection

- **WHEN** 运行 Bandit 安全扫描
- **THEN** 检测 `pickle.load` 和 `pickle.loads` 调用
- **AND** 报告为 HIGH 级别漏洞（除非有 # trust-verified 注释）

### Requirement: Security configuration audit at startup

Application startup SHALL perform security configuration audit and report issues before accepting requests.

#### Scenario: Startup security check

- **WHEN** application starts in any environment
- **THEN** it SHALL log security configuration status (configured/missing/default)

#### Scenario: Development environment warnings

- **WHEN** application starts in development mode with insecure defaults
- **THEN** it SHALL emit WARNING level logs for each insecure configuration

#### Scenario: Injection vulnerability check

- **WHEN** 应用启动时执行安全审计
- **THEN** 扫描代码中的 f-string + SQL/Cypher 模式
- **AND** 发现潜在注入漏洞时发出 CRITICAL 日志