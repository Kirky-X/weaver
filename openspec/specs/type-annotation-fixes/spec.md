# Type Annotation Fixes

## ADDED Requirements

### Requirement: Dataclass fields with None default must use Optional type

All dataclass fields that have `None` as a default value SHALL use `| None` or `Optional[T]` type annotation to ensure type safety.

#### Scenario: LLM routing config with None defaults
- **WHEN** `RoutingConfig` dataclass has `fallbacks: list[str] = None`
- **THEN** type annotation SHALL be `fallbacks: list[str] | None = None`

#### Scenario: Model config with None defaults
- **WHEN** `ModelConfig` dataclass has `models: dict[str, ModelConfig] = None`
- **THEN** type annotation SHALL be `models: dict[str, ModelConfig] | None = None`

### Requirement: Function return types must match actual return values

Function return type annotations SHALL accurately reflect the actual types returned by the function.

#### Scenario: sanitize_dict returns mixed types
- **WHEN** `sanitize_dict` function returns dict containing str, dict, list, and Any values
- **THEN** return type annotation SHALL be `dict[str, Any]` not `dict[str, str]`

### Requirement: Type annotations must pass mypy validation

All type annotations in the codebase SHALL pass `mypy --ignore-missing-imports` validation without errors.

#### Scenario: Running mypy on core llm types
- **WHEN** `mypy src/core/llm/types.py --ignore-missing-imports` is executed
- **THEN** no type errors SHALL be reported

#### Scenario: Running mypy on core utils
- **WHEN** `mypy src/core/utils/sanitize.py --ignore-missing-imports` is executed
- **THEN** no type errors SHALL be reported