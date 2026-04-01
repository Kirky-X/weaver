# Copyright (c) 2026 KirkyX. All Rights Reserved.
"""Unit tests for pipeline configuration."""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

from modules.pipeline.config import (
    BatchConfig,
    PhaseConfig,
    PipelineConfig,
    PipelineConfigLoader,
    StageConfig,
    _dict_to_batch,
    _dict_to_phase,
    _dict_to_stage,
    dict_to_config,
    save_default_config,
)


class TestStageConfig:
    """Tests for StageConfig dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        stage = StageConfig(name="test", class_path="test.Module")
        assert stage.name == "test"
        assert stage.class_path == "test.Module"
        assert stage.enabled is True
        assert stage.timeout == 60
        assert stage.retry == 3
        assert stage.retry_delay == 5
        assert stage.params == {}

    def test_custom_values(self):
        """Test custom initialization."""
        stage = StageConfig(
            name="custom",
            class_path="custom.Parser",
            enabled=False,
            timeout=120,
            retry=5,
            retry_delay=10,
            params={"key": "value"},
        )
        assert stage.enabled is False
        assert stage.timeout == 120
        assert stage.params == {"key": "value"}


class TestPhaseConfig:
    """Tests for PhaseConfig dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        phase = PhaseConfig()
        assert phase.concurrency == 5
        assert phase.stages == []

    def test_enabled_stages(self):
        """Test enabled_stages property."""
        phase = PhaseConfig(
            stages=[
                StageConfig(name="enabled", class_path="test.E", enabled=True),
                StageConfig(name="disabled", class_path="test.D", enabled=False),
            ]
        )
        enabled = phase.enabled_stages
        assert len(enabled) == 1
        assert enabled[0].name == "enabled"

    def test_all_disabled_stages(self):
        """Test when all stages are disabled."""
        phase = PhaseConfig(
            stages=[
                StageConfig(name="d1", class_path="test.D1", enabled=False),
                StageConfig(name="d2", class_path="test.D2", enabled=False),
            ]
        )
        assert len(phase.enabled_stages) == 0


class TestBatchConfig:
    """Tests for BatchConfig dataclass."""

    def test_default_values(self):
        """Test default initialization."""
        batch = BatchConfig()
        assert "BatchMergerNode" in batch.merger_class
        assert batch.enabled is True
        assert batch.timeout == 180

    def test_custom_values(self):
        """Test custom initialization."""
        batch = BatchConfig(
            merger_class="custom.Merger",
            enabled=False,
            timeout=300,
        )
        assert batch.merger_class == "custom.Merger"
        assert batch.enabled is False
        assert batch.timeout == 300


class TestPipelineConfig:
    """Tests for PipelineConfig dataclass."""

    def test_default_creates_phases(self):
        """Test that default() creates complete config."""
        config = PipelineConfig.default()
        assert config.version == "1.0"
        assert len(config.phase1.stages) == 4
        assert len(config.phase3.stages) == 5

    def test_default_phase1_stages(self):
        """Test default phase1 stages."""
        config = PipelineConfig.default()
        stage_names = [s.name for s in config.phase1.stages]
        assert "classifier" in stage_names
        assert "cleaner" in stage_names
        assert "categorizer" in stage_names
        assert "vectorize" in stage_names

    def test_default_phase3_stages(self):
        """Test default phase3 stages."""
        config = PipelineConfig.default()
        stage_names = [s.name for s in config.phase3.stages]
        assert "re_vectorize" in stage_names
        assert "analyze" in stage_names
        assert "quality_scorer" in stage_names
        assert "credibility" in stage_names
        assert "entity_extractor" in stage_names

    def test_to_dict_structure(self):
        """Test to_dict returns proper structure."""
        config = PipelineConfig.default()
        data = config.to_dict()

        assert "pipeline" in data
        assert "version" in data["pipeline"]
        assert "phase1" in data["pipeline"]
        assert "phase3" in data["pipeline"]
        assert "batch" in data["pipeline"]


class TestDictToStage:
    """Tests for _dict_to_stage function."""

    def test_minimal_dict(self):
        """Test with minimal dictionary."""
        stage = _dict_to_stage({"name": "test", "class": "test.Module"})
        assert stage.name == "test"
        assert stage.class_path == "test.Module"

    def test_full_dict(self):
        """Test with full dictionary."""
        stage = _dict_to_stage(
            {
                "name": "full",
                "class": "full.Module",
                "enabled": False,
                "timeout": 90,
                "retry": 2,
                "retry_delay": 3,
            }
        )
        assert stage.enabled is False
        assert stage.timeout == 90
        assert stage.retry == 2

    def test_extra_params(self):
        """Test that extra params are captured."""
        stage = _dict_to_stage(
            {
                "name": "extra",
                "class": "extra.Module",
                "custom_param": "value",
                "another": 123,
            }
        )
        assert stage.params["custom_param"] == "value"
        assert stage.params["another"] == 123


class TestDictToPhase:
    """Tests for _dict_to_phase function."""

    def test_empty_dict(self):
        """Test with empty dictionary."""
        phase = _dict_to_phase({})
        assert phase.concurrency == 5
        assert phase.stages == []

    def test_with_stages(self):
        """Test with stages."""
        phase = _dict_to_phase(
            {
                "concurrency": 10,
                "stages": [
                    {"name": "s1", "class": "test.S1"},
                    {"name": "s2", "class": "test.S2"},
                ],
            }
        )
        assert phase.concurrency == 10
        assert len(phase.stages) == 2


class TestDictToBatch:
    """Tests for _dict_to_batch function."""

    def test_empty_dict(self):
        """Test with empty dictionary."""
        batch = _dict_to_batch({})
        assert "BatchMergerNode" in batch.merger_class

    def test_custom_values(self):
        """Test with custom values."""
        batch = _dict_to_batch(
            {
                "merger_class": "custom.Merger",
                "enabled": False,
                "timeout": 200,
            }
        )
        assert batch.merger_class == "custom.Merger"
        assert batch.enabled is False
        assert batch.timeout == 200


class TestDictToConfig:
    """Tests for dict_to_config function."""

    def test_empty_dict(self):
        """Test with empty dictionary."""
        config = dict_to_config({})
        assert config.version == "1.0"

    def test_full_config(self):
        """Test with full configuration."""
        data = {
            "pipeline": {
                "version": "2.0",
                "phase1": {
                    "concurrency": 3,
                    "stages": [{"name": "s1", "class": "test.S1"}],
                },
                "phase3": {
                    "concurrency": 2,
                    "stages": [],
                },
            }
        }
        config = dict_to_config(data)
        assert config.version == "2.0"
        assert config.phase1.concurrency == 3
        assert len(config.phase1.stages) == 1


class TestPipelineConfigLoader:
    """Tests for PipelineConfigLoader class."""

    def test_init(self):
        """Test initialization."""
        loader = PipelineConfigLoader()
        assert loader._config_cache == {}

    def test_load_from_file_not_found(self):
        """Test loading from nonexistent file."""
        loader = PipelineConfigLoader()
        with pytest.raises(FileNotFoundError):
            loader.load_from_file("/nonexistent/config.yaml")

    def test_load_from_file_valid(self):
        """Test loading from valid file."""
        loader = PipelineConfigLoader()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {
                    "pipeline": {
                        "version": "test-1.0",
                        "phase1": {"stages": []},
                        "phase3": {"stages": []},
                    }
                },
                f,
            )
            f.flush()

            config = loader.load_from_file(f.name)
            assert config.version == "test-1.0"

        os.unlink(f.name)

    def test_load_from_file_empty(self):
        """Test loading from empty file."""
        loader = PipelineConfigLoader()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            f.write("")
            f.flush()

            config = loader.load_from_file(f.name)
            assert config.version == "1.0"  # Default

        os.unlink(f.name)

    def test_load_from_directory_not_found(self):
        """Test loading from nonexistent directory."""
        loader = PipelineConfigLoader()
        with pytest.raises(NotADirectoryError):
            loader.load_from_directory("/nonexistent/dir")

    def test_load_from_directory_empty(self):
        """Test loading from empty directory."""
        loader = PipelineConfigLoader()

        with tempfile.TemporaryDirectory() as tmpdir:
            configs = loader.load_from_directory(tmpdir)
            assert configs == []

    def test_load_from_directory_with_files(self):
        """Test loading from directory with config files."""
        loader = PipelineConfigLoader()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create config file
            config_path = Path(tmpdir, "config.yaml")
            with open(config_path, "w") as f:
                yaml.dump(
                    {
                        "pipeline": {
                            "version": "dir-test",
                            "phase1": {"stages": []},
                            "phase3": {"stages": []},
                        }
                    },
                    f,
                )

            configs = loader.load_from_directory(tmpdir)
            assert len(configs) == 1
            assert configs[0].version == "dir-test"

    def test_load_with_env_override_no_env(self):
        """Test loading with no env overrides."""
        loader = PipelineConfigLoader()

        with patch.dict(os.environ, {}, clear=True):
            config = loader.load_with_env_override()
            assert config is not None

    def test_load_with_env_override_concurrency(self):
        """Test loading with concurrency overrides."""
        loader = PipelineConfigLoader()

        with patch.dict(
            os.environ,
            {
                "WEAVER_PHASE1_CONCURRENCY": "10",
                "WEAVER_PHASE3_CONCURRENCY": "20",
            },
        ):
            config = loader.load_with_env_override()
            assert config.phase1.concurrency == 10
            assert config.phase3.concurrency == 20

    def test_cache_used(self):
        """Test that cache is used for repeated loads."""
        loader = PipelineConfigLoader()

        with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
            yaml.dump(
                {
                    "pipeline": {
                        "version": "cached",
                        "phase1": {"stages": []},
                        "phase3": {"stages": []},
                    }
                },
                f,
            )
            f.flush()

            loader.load_from_file(f.name)
            assert f.name in loader._config_cache

        os.unlink(f.name)


class TestSaveDefaultConfig:
    """Tests for save_default_config function."""

    def test_save_to_file(self):
        """Test saving default config to file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "pipeline.yaml")
            save_default_config(path)

            assert path.exists()

            with open(path) as f:
                data = yaml.safe_load(f)

            assert "pipeline" in data
            assert data["pipeline"]["version"] == "1.0"

    def test_save_creates_parent_dirs(self):
        """Test that parent directories are created."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir, "subdir", "nested", "pipeline.yaml")
            save_default_config(path)

            assert path.exists()
            assert path.parent.is_dir()
