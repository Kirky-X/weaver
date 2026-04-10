## MODIFIED Requirements

### Requirement: Support multiple pipeline test modes

The script SHALL support `--mode` parameter with values `newsnow`, `rss`, and `strategy` to test different data ingestion paths. The NewsNow mode SHALL use the updated API endpoint at `https://www.newsnow.world/api/s?id=`.

#### Scenario: NewsNow mode test
- **WHEN** user runs `scripts/test_pipeline.py --mode newsnow --max-items 5`
- **THEN** script fetches data from NewsNow API at `https://www.newsnow.world/api/s?id=36kr`, processes through pipeline, and verifies storage

#### Scenario: NewsNow mode with custom source
- **WHEN** user runs `scripts/test_pipeline.py --mode newsnow --source-id hupu --max-items 5`
- **THEN** script fetches data from NewsNow API at `https://www.newsnow.world/api/s?id=hupu`, processes through pipeline, and verifies storage

#### Scenario: RSS mode test
- **WHEN** user runs `scripts/test_pipeline.py --mode rss --source solidot --max-items 2`
- **THEN** script fetches data from RSS feed, processes through pipeline, and verifies storage

#### Scenario: Strategy mode test
- **WHEN** user runs `scripts/test_pipeline.py --mode strategy`
- **THEN** script tests database failover using `core.db.strategy.create_strategy()`