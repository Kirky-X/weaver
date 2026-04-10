## ADDED Requirements

### Requirement: NewsNow source ID command-line parameter

The test script SHALL support `--source-id` parameter to specify which NewsNow source to fetch data from.

#### Scenario: Default source ID
- **WHEN** user runs `scripts/test_pipeline.py --mode newsnow` without `--source-id`
- **THEN** script uses `36kr` as the default source ID

#### Scenario: Custom source ID
- **WHEN** user runs `scripts/test_pipeline.py --mode newsnow --source-id hupu --max-items 5`
- **THEN** script fetches data from `https://www.newsnow.world/api/s?id=hupu`

#### Scenario: Help text displays parameter
- **WHEN** user runs `scripts/test_pipeline.py --help`
- **THEN** help text shows `--source-id` parameter with description