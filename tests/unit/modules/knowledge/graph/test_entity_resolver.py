# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for EntityResolver in knowledge module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.shared import EntityView


class TestEntityResolverInit:
    """Tests for EntityResolver initialization."""

    def test_init_with_required_params(self):
        """Test EntityResolver initializes with required params."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        mock_vector_repo = MagicMock()
        mock_entity_repo = MagicMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        assert resolver._entity_repo is mock_entity_repo
        assert resolver._vector_repo is mock_vector_repo
        assert resolver._llm is None

    def test_init_with_optional_params(self):
        """Test EntityResolver initializes with optional params."""
        from modules.knowledge.graph.entity_resolver import EntityResolver
        from modules.knowledge.graph.name_normalizer import NameNormalizer
        from modules.knowledge.graph.resolution_rules import EntityResolutionRules

        mock_vector_repo = MagicMock()
        mock_entity_repo = MagicMock()
        mock_llm = MagicMock()
        mock_rules = MagicMock(spec=EntityResolutionRules)
        mock_normalizer = MagicMock(spec=NameNormalizer)

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
            resolution_rules=mock_rules,
            name_normalizer=mock_normalizer,
        )

        assert resolver._llm is mock_llm
        assert resolver._rules is mock_rules
        assert resolver._normalizer is mock_normalizer


class TestEntityResolverResolveEntity:
    """Tests for EntityResolver.resolve_entity()."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j-id-123")
        repo.add_alias = AsyncMock()
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo, mock_vector_repo):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

    @pytest.mark.asyncio
    async def test_resolve_entity_filters_metric_string(self, resolver):
        """Test resolve_entity filters out metric strings."""
        result = await resolver.resolve_entity(
            name="12.73%",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "filtered_metric"
        assert result["is_new"] is False

    @pytest.mark.asyncio
    async def test_resolve_entity_filters_monetary_value(self, resolver):
        """Test resolve_entity filters out monetary values."""
        result = await resolver.resolve_entity(
            name="97.65亿元",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "filtered_metric"

    @pytest.mark.asyncio
    async def test_resolve_entity_returns_exact_match(self, resolver, mock_entity_repo):
        """Test resolve_entity returns exact match."""
        mock_entity_repo.find_entity.return_value = EntityView.model_validate(
            {"neo4j_id": "existing-id", "name": "Test Entity", "entity_type": "PERSON"}
        )

        result = await resolver.resolve_entity(
            name="Test Entity",
            entity_type="PERSON",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "exact"
        assert result["is_new"] is False
        assert result["neo4j_id"] == "existing-id"

    @pytest.mark.asyncio
    async def test_resolve_entity_creates_new_without_embedding(self, resolver, mock_entity_repo):
        """Test resolve_entity creates new entity without embedding."""
        result = await resolver.resolve_entity(
            name="New Entity",
            entity_type="ORG",
            embedding=[],
        )

        assert result["is_new"] is True
        assert result["match_type"] == "new"
        mock_entity_repo.merge_entity.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_entity_finds_similar(self, resolver, mock_entity_repo, mock_vector_repo):
        """Test resolve_entity finds similar entities."""
        mock_similar = MagicMock()
        mock_similar.neo4j_id = "similar-id"
        mock_similar.similarity = 0.9

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]
        mock_entity_repo.find_entities_by_ids.return_value = [
            EntityView.model_validate(
                {"neo4j_id": "similar-id", "name": "Similar Entity", "entity_type": "PERSON"}
            )
        ]

        result = await resolver.resolve_entity(
            name="Similar Entity",
            entity_type="PERSON",
            embedding=[0.1] * 1536,
        )

        # Should have called find_similar_entities
        mock_vector_repo.find_similar_entities.assert_called_once()

    @pytest.mark.asyncio
    async def test_resolve_entity_creates_new_when_no_similar(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        """Test resolve_entity creates new when no similar found."""
        mock_vector_repo.find_similar_entities.return_value = []

        result = await resolver.resolve_entity(
            name="Unique Entity",
            entity_type="PERSON",
            embedding=[0.1] * 1536,
        )

        assert result["is_new"] is True
        assert result["match_type"] == "new"


class TestEntityResolverMetricFiltering:
    """Tests for _looks_like_metric_string method."""

    @pytest.fixture
    def resolver(self):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=MagicMock(),
            vector_repo=MagicMock(),
        )

    def test_filters_percentage(self, resolver):
        """Test filters percentage values."""
        assert resolver._looks_like_metric_string("12.73%") is True
        assert resolver._looks_like_metric_string("9.90%") is True

    def test_filters_monetary_values(self, resolver):
        """Test filters monetary values."""
        assert resolver._looks_like_metric_string("97.65亿元") is True
        assert resolver._looks_like_metric_string("6亿元") is True

    def test_filters_share_counts(self, resolver):
        """Test filters share counts."""
        assert resolver._looks_like_metric_string("2.42亿股") is True

    def test_filters_composite_metrics(self, resolver):
        """Test filters composite metrics."""
        assert resolver._looks_like_metric_string("本土市场游戏收入1642亿元") is True

    def test_does_not_filter_regular_names(self, resolver):
        """Test does not filter regular entity names."""
        assert resolver._looks_like_metric_string("腾讯公司") is False
        assert resolver._looks_like_metric_string("张三") is False

    def test_filters_empty_string(self, resolver):
        """Test handles empty string."""
        assert resolver._looks_like_metric_string("") is False


class TestEntityResolverHelperMethods:
    """Tests for helper methods."""

    @pytest.fixture
    def resolver(self):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=MagicMock(),
            vector_repo=MagicMock(),
        )

    def test_resolve_canonical_name_empty_candidates(self, resolver):
        """Test _resolve_canonical_name with empty candidates."""
        result = resolver._resolve_canonical_name("QueryName", "PERSON", [])
        assert result == "QueryName"

    def test_resolve_canonical_name_with_candidates(self, resolver):
        """Test _resolve_canonical_name with candidates."""
        candidates = [
            {"canonical_name": "CandidateA"},
            {"canonical_name": "CandidateB"},
        ]
        result = resolver._resolve_canonical_name("QueryName", "PERSON", candidates)
        # Should return a name from candidates or query name
        assert result in ["QueryName", "CandidateA", "CandidateB"]

    def test_get_resolution_stats(self, resolver):
        """Test get_resolution_stats returns stats."""
        stats = resolver.get_resolution_stats()

        assert "known_aliases" in stats
        assert "abbreviations" in stats
        assert "translations" in stats
        assert "rules_count" in stats


class TestEntityResolverPreResolveCheck:
    """Tests for pre_resolve_check method."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=MagicMock(),
        )

    @pytest.mark.asyncio
    async def test_pre_resolve_check_returns_existing(self, resolver, mock_entity_repo):
        """Test pre_resolve_check finds existing entity."""
        mock_entity_repo.find_entity.return_value = EntityView.model_validate(
            {"neo4j_id": "existing-id", "name": "Existing Entity", "entity_type": "PERSON"}
        )

        result = await resolver.pre_resolve_check("Existing Entity", "PERSON")

        assert result is not None
        assert result["exists"] is True
        assert result["neo4j_id"] == "existing-id"

    @pytest.mark.asyncio
    async def test_pre_resolve_check_returns_none(self, resolver, mock_entity_repo):
        """Test pre_resolve_check returns None when not found."""
        mock_entity_repo.find_entity.return_value = None

        result = await resolver.pre_resolve_check("NonExistent", "PERSON")

        assert result is None


class TestEntityResolverBatch:
    """Tests for resolve_entities_batch method."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j-id-123")
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo, mock_vector_repo):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

    @pytest.mark.asyncio
    async def test_resolve_entities_batch(self, resolver):
        """Test resolve_entities_batch processes multiple entities."""
        entities = [
            {"name": "Entity1", "type": "PERSON", "embedding": [0.1] * 1536},
            {"name": "Entity2", "type": "ORG", "embedding": [0.2] * 1536},
        ]

        results = await resolver.resolve_entities_batch(entities)

        assert len(results) == 2
        assert all("neo4j_id" in r for r in results)


class TestConstraintError:
    """Tests for ConstraintError handling."""

    def test_is_constraint_error(self):
        """Test _is_constraint_error detection."""
        from modules.knowledge.graph.entity_resolver import _is_constraint_error

        class ConstraintError(Exception):
            pass

        assert _is_constraint_error(ConstraintError("test")) is True
        assert _is_constraint_error(Exception("test")) is False


class TestEntityResolverResolveEntityExtended:
    """Extended tests for resolve_entity covering more branches."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j-id-new")
        repo.add_alias = AsyncMock()
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo, mock_vector_repo):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

    @pytest.mark.asyncio
    async def test_resolve_entity_normalized_name_match(self, resolver, mock_entity_repo):
        """Test resolve_entity finds match via normalized name."""
        from modules.knowledge.graph.name_normalizer import NameNormalizer

        # Mock normalizer to return different normalized name
        resolver._normalizer = MagicMock(spec=NameNormalizer)
        norm_result = MagicMock()
        norm_result.normalized = "normalized_entity"
        resolver._normalizer.normalize.return_value = norm_result
        resolver._normalizer.select_canonical.return_value = "normalized_entity"

        # First find_entity (normalized) returns None, second (original) returns match
        mock_entity_repo.find_entity.side_effect = [
            None,  # normalized name not found
            EntityView.model_validate(
                {"neo4j_id": "existing-id", "name": "Original Name", "entity_type": "PERSON"}
            ),  # original name found
        ]

        result = await resolver.resolve_entity(
            name="Original Name",
            entity_type="PERSON",
            embedding=[0.1] * 10,
        )

        assert result["match_type"] == "normalized_exact"
        assert result["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_resolve_entity_similar_with_no_candidates_from_map(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        """Test resolve_entity when similar found but entities map has no matching IDs."""
        from modules.knowledge.graph.resolution_rules import EntityResolutionRules

        resolver._rules = MagicMock(spec=EntityResolutionRules)
        resolver._rules.resolve.return_value = MagicMock(
            match_type=MagicMock(value="none"),
            confidence=0.0,
            canonical_name=None,
        )
        resolver._rules.get_canonical_suggestion.return_value = "TestEntity"
        resolver._normalizer = MagicMock()
        resolver._normalizer.normalize.return_value = MagicMock(normalized="TestEntity")
        resolver._normalizer.select_canonical.return_value = "TestEntity"

        mock_similar = MagicMock()
        mock_similar.neo4j_id = "similar-id"
        mock_similar.similarity = 0.9

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]
        # entities_by_ids returns empty -> no candidates after filtering
        mock_entity_repo.find_entities_by_ids.return_value = []

        result = await resolver.resolve_entity(
            name="TestEntity",
            entity_type="PERSON",
            embedding=[0.1] * 10,
        )

        # Should create new entity since no candidates found
        assert result["is_new"] is True

    @pytest.mark.asyncio
    async def test_resolve_entity_rule_based_high_confidence_merge(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        """Test resolve_entity merges when rule-based resolution has high confidence."""
        from modules.knowledge.graph.resolution_rules import EntityResolutionRules, MatchType

        resolver._rules = MagicMock(spec=EntityResolutionRules)
        resolver._rules.resolve.return_value = MagicMock(
            match_type=MatchType.EXACT,
            confidence=0.95,
            canonical_name="TargetEntity",
        )
        resolver._normalizer = MagicMock()
        resolver._normalizer.normalize.return_value = MagicMock(normalized="TestEntity")

        mock_similar = MagicMock()
        mock_similar.neo4j_id = "sim-id"
        mock_similar.similarity = 0.92

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]
        mock_entity_repo.find_entities_by_ids.return_value = [
            EntityView.model_validate(
                {"neo4j_id": "sim-id", "name": "TargetEntity", "entity_type": "PERSON"}
            )
        ]

        result = await resolver.resolve_entity(
            name="TestEntity",
            entity_type="PERSON",
            embedding=[0.1] * 10,
        )

        assert result["merged"] is True
        assert result["match_type"] == "exact"
        assert result["confidence"] == 0.95

    @pytest.mark.asyncio
    async def test_resolve_entity_rule_no_high_conf_target(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        """Test resolve_entity when rule matches but target not in candidates."""
        from modules.knowledge.graph.resolution_rules import EntityResolutionRules, MatchType

        resolver._rules = MagicMock(spec=EntityResolutionRules)
        resolver._rules.resolve.return_value = MagicMock(
            match_type=MatchType.FUZZY,
            confidence=0.95,
            canonical_name="NonExistentTarget",
        )
        resolver._rules.get_canonical_suggestion.return_value = "TestEntity"
        resolver._normalizer = MagicMock()
        resolver._normalizer.normalize.return_value = MagicMock(normalized="TestEntity")
        resolver._normalizer.select_canonical.return_value = "TestEntity"

        mock_similar = MagicMock()
        mock_similar.neo4j_id = "sim-id"
        mock_similar.similarity = 0.9

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]
        mock_entity_repo.find_entities_by_ids.return_value = [
            EntityView.model_validate(
                {"neo4j_id": "sim-id", "name": "DifferentEntity", "entity_type": "PERSON"}
            )
        ]
        # find_entity for canonical name returns None
        mock_entity_repo.find_entity.return_value = None

        result = await resolver.resolve_entity(
            name="TestEntity",
            entity_type="PERSON",
            embedding=[0.1] * 10,
        )

        # Since target not found and no LLM, creates new
        assert result["is_new"] is True

    @pytest.mark.asyncio
    async def test_resolve_entity_llm_dedup_merge(self, mock_entity_repo, mock_vector_repo):
        """Test resolve_entity merges via LLM dedup.

        entity-resolver-batch-select: 单实体路径委托批量契约（v1.2.0），
        mock call_at 返回 EntityBatchDedupOutput（target 须在候选集内）。
        """
        from modules.knowledge.graph.entity_resolver import (
            EntityBatchDecision,
            EntityBatchDedupOutput,
            EntityResolver,
        )

        mock_llm = MagicMock()
        mock_llm.call_at = AsyncMock(
            return_value=EntityBatchDedupOutput(
                decisions=[
                    EntityBatchDecision(
                        entity_index=0,
                        should_merge=True,
                        target_neo4j_id="sim-id",
                        target_canonical_name="TargetEntity",
                        confidence=0.85,
                    )
                ]
            )
        )

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=mock_llm,
        )

        from modules.knowledge.graph.resolution_rules import EntityResolutionRules, MatchType

        resolver._rules = MagicMock(spec=EntityResolutionRules)
        resolver._rules.resolve.return_value = MagicMock(
            match_type=MatchType.NONE,
            confidence=0.5,
        )
        resolver._rules.get_canonical_suggestion.return_value = "TestEntity"
        resolver._normalizer = MagicMock()
        resolver._normalizer.normalize.return_value = MagicMock(normalized="TestEntity")

        mock_similar = MagicMock()
        mock_similar.neo4j_id = "sim-id"
        mock_similar.similarity = 0.9

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]
        mock_entity_repo.find_entities_by_ids.return_value = [
            EntityView.model_validate(
                {"neo4j_id": "sim-id", "name": "TargetEntity", "entity_type": "PERSON"}
            )
        ]

        result = await resolver.resolve_entity(
            name="TestEntity",
            entity_type="PERSON",
            embedding=[0.1] * 10,
        )

        assert result["merged"] is True
        assert result["match_type"] == "llm_dedup"

    @pytest.mark.asyncio
    async def test_resolve_entity_canonical_resolved_with_alias(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        """Test resolve_entity adds alias when canonical name resolves to existing."""
        from modules.knowledge.graph.resolution_rules import EntityResolutionRules, MatchType

        resolver._rules = MagicMock(spec=EntityResolutionRules)
        resolver._rules.resolve.return_value = MagicMock(
            match_type=MatchType.NONE,
            confidence=0.5,
        )
        resolver._rules.get_canonical_suggestion.return_value = "CanonicalName"
        resolver._normalizer = MagicMock()
        resolver._normalizer.normalize.return_value = MagicMock(normalized="TestEntity")
        resolver._normalizer.select_canonical.return_value = "CanonicalName"

        mock_similar = MagicMock()
        mock_similar.neo4j_id = "sim-id"
        mock_similar.similarity = 0.9

        mock_vector_repo.find_similar_entities.return_value = [mock_similar]
        mock_entity_repo.find_entities_by_ids.return_value = [
            EntityView.model_validate(
                {"neo4j_id": "sim-id", "name": "SomeEntity", "entity_type": "PERSON"}
            )
        ]
        # find_entity sequence:
        # 1st call: normalized name "TestEntity" -> None
        # (no 2nd call because normalized==name)
        # 2nd call (actually): canonical_name "CanonicalName" -> found
        mock_entity_repo.find_entity.side_effect = [
            None,  # normalized name lookup at line 120
            EntityView.model_validate(
                {"neo4j_id": "canonical-id", "name": "CanonicalName", "entity_type": "PERSON"}
            ),  # canonical lookup at line 243
        ]

        result = await resolver.resolve_entity(
            name="TestEntity",
            entity_type="PERSON",
            embedding=[0.1] * 10,
        )

        assert result["match_type"] == "alias_added"
        assert result["merged"] is True
        mock_entity_repo.add_alias.assert_called_once()


class TestEntityResolverMergeWithExisting:
    """Tests for _merge_with_existing method."""

    @pytest.mark.asyncio
    async def test_merge_adds_alias_when_different_name(self):
        """Test _merge_with_existing adds alias when names differ."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        mock_entity_repo = MagicMock()
        mock_entity_repo.add_alias = AsyncMock()
        mock_vector_repo = MagicMock()
        mock_vector_repo.upsert_entity_vector = AsyncMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        result = await resolver._merge_with_existing(
            new_name="NewName",
            entity_type="PERSON",
            target={"canonical_name": "CanonicalName", "neo4j_id": "id-1"},
            embedding=[0.1] * 10,
            match_type="fuzzy",
            confidence=0.85,
        )

        assert result["merged"] is True
        assert result["canonical_name"] == "CanonicalName"
        mock_entity_repo.add_alias.assert_called_once_with("CanonicalName", "PERSON", "NewName")
        mock_vector_repo.upsert_entity_vector.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_no_alias_when_same_name(self):
        """Test _merge_with_existing does not add alias when names match."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        mock_entity_repo = MagicMock()
        mock_entity_repo.add_alias = AsyncMock()
        mock_vector_repo = MagicMock()
        mock_vector_repo.upsert_entity_vector = AsyncMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        result = await resolver._merge_with_existing(
            new_name="SameName",
            entity_type="PERSON",
            target={"canonical_name": "SameName", "neo4j_id": "id-1"},
            embedding=[0.1] * 10,
            match_type="exact",
            confidence=1.0,
        )

        mock_entity_repo.add_alias.assert_not_called()
        mock_vector_repo.upsert_entity_vector.assert_called_once()

    @pytest.mark.asyncio
    async def test_merge_no_embedding(self):
        """Test _merge_with_existing with empty embedding."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        mock_entity_repo = MagicMock()
        mock_entity_repo.add_alias = AsyncMock()
        mock_vector_repo = MagicMock()
        mock_vector_repo.upsert_entity_vector = AsyncMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        result = await resolver._merge_with_existing(
            new_name="NewName",
            entity_type="PERSON",
            target={"canonical_name": "Canonical", "neo4j_id": "id-1"},
            embedding=[],
            match_type="alias",
            confidence=0.9,
        )

        mock_vector_repo.upsert_entity_vector.assert_not_called()


class TestEntityResolverCreateEntity:
    """Tests for _create_entity method."""

    @pytest.mark.asyncio
    async def test_create_entity_success(self):
        """Test _create_entity creates new entity."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        mock_entity_repo = MagicMock()
        mock_entity_repo.merge_entity = AsyncMock(return_value="new-neo4j-id")
        mock_vector_repo = MagicMock()
        mock_vector_repo.upsert_entity_vector = AsyncMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        result = await resolver._create_entity(
            name="TestEntity",
            entity_type="PERSON",
            embedding=[0.1] * 10,
            description="Test description",
            is_new=True,
            match_type="new",
            confidence=1.0,
        )

        assert result["neo4j_id"] == "new-neo4j-id"
        assert result["is_new"] is True
        mock_vector_repo.upsert_entity_vector.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_entity_constraint_error_recovery(self):
        """Test _create_entity recovers from constraint error."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        class FakeConstraintError(Exception):
            pass

        mock_entity_repo = MagicMock()
        # merge_entity raises, then find_entity succeeds
        mock_entity_repo.merge_entity = AsyncMock(side_effect=FakeConstraintError("constraint"))
        mock_entity_repo.find_entity = AsyncMock(
            return_value=EntityView.model_validate(
                {"neo4j_id": "concurrent-id", "name": "TestEntity", "entity_type": "PERSON"}
            )
        )
        mock_vector_repo = MagicMock()
        mock_vector_repo.upsert_entity_vector = AsyncMock()

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        with patch(
            "modules.knowledge.graph.entity_resolver._is_constraint_error",
            return_value=True,
        ):
            with patch(
                "modules.knowledge.graph.entity_resolver.ConstraintError",
                FakeConstraintError,
            ):
                result = await resolver._create_entity(
                    name="TestEntity",
                    entity_type="PERSON",
                    embedding=[0.1] * 10,
                    description=None,
                    is_new=True,
                    match_type="new",
                    confidence=1.0,
                )

        assert result["match_type"] == "concurrent_create"
        assert result["neo4j_id"] == "concurrent-id"


class TestEntityResolverPreResolveCheckExtended:
    """Extended tests for pre_resolve_check covering alias lookup."""

    @pytest.mark.asyncio
    async def test_pre_resolve_checks_aliases(self):
        """Test pre_resolve_check finds entity via alias."""
        from modules.knowledge.graph.entity_resolver import EntityResolver
        from modules.knowledge.graph.name_normalizer import NameNormalizer
        from modules.knowledge.graph.resolution_rules import EntityResolutionRules

        mock_entity_repo = MagicMock()
        # First call (normalized): None, second (original): None, third (alias): found
        mock_entity_repo.find_entity = AsyncMock(
            side_effect=[
                None,
                None,
                EntityView.model_validate(
                    {"neo4j_id": "alias-id", "name": "CanonicalEntity", "entity_type": "PERSON"}
                ),
            ]
        )

        mock_rules = MagicMock(spec=EntityResolutionRules)
        mock_rules.get_all_aliases.return_value = ["Alias1"]

        mock_normalizer = MagicMock(spec=NameNormalizer)
        norm_result = MagicMock(normalized="NormalizedEntity")
        mock_normalizer.normalize.return_value = norm_result

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=MagicMock(),
            resolution_rules=mock_rules,
            name_normalizer=mock_normalizer,
        )

        result = await resolver.pre_resolve_check("TestEntity", "PERSON")

        assert result is not None
        assert result["matched_alias"] == "Alias1"

    @pytest.mark.asyncio
    async def test_pre_resolve_normalized_match(self):
        """Test pre_resolve_check finds via normalized name when original differs."""
        from modules.knowledge.graph.entity_resolver import EntityResolver
        from modules.knowledge.graph.name_normalizer import NameNormalizer

        mock_entity_repo = MagicMock()
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        # But on second call with original name, returns existing
        mock_entity_repo.find_entity = AsyncMock(
            side_effect=[
                None,  # normalized not found
                EntityView.model_validate(
                    {"neo4j_id": "orig-id", "name": "OriginalEntity", "entity_type": "PERSON"}
                ),  # original found
            ]
        )

        mock_normalizer = MagicMock(spec=NameNormalizer)
        norm_result = MagicMock(normalized="normalized_different")
        mock_normalizer.normalize.return_value = norm_result

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=MagicMock(),
            name_normalizer=mock_normalizer,
        )

        result = await resolver.pre_resolve_check("OriginalEntity", "PERSON")

        assert result is not None
        assert result["exists"] is True


class TestEntityResolverMetricFilteringExtended:
    """Extended tests for metric filtering covering more patterns."""

    @pytest.fixture
    def resolver(self):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=MagicMock(),
            vector_repo=MagicMock(),
        )

    def test_filters_dividend_expression(self, resolver):
        """Test filters dividend/bonus expressions."""
        assert resolver._looks_like_metric_string("每10股派发现金红利0.86元(含税)") is True

    def test_filters_numeric_with_units(self, resolver):
        """Test filters numeric expressions with units."""
        assert resolver._looks_like_metric_string("1.4亿") is True

    def test_does_not_filter_whitespace_only(self, resolver):
        """Test does not filter whitespace-only string."""
        assert resolver._looks_like_metric_string("   ") is False

    def test_filters_share_expression(self, resolver):
        """Test filters share expressions like '6亿股'."""
        assert resolver._looks_like_metric_string("6亿股") is True


class TestEntityResolverDisableDataMetricsConfig:
    """Tests for disable_data_metrics configuration in EntityResolver."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j-id-123")
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.mark.asyncio
    async def test_disable_data_metrics_blocks_data_metric_type(
        self, mock_entity_repo, mock_vector_repo
    ):
        """Test that disable_data_metrics=True blocks 数据指标 entities."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            disable_data_metrics=True,
        )

        result = await resolver.resolve_entity(
            name="某个指标",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "filtered_metric"
        assert result["is_new"] is False
        # Should not call merge_entity
        mock_entity_repo.merge_entity.assert_not_called()

    @pytest.mark.asyncio
    async def test_disable_data_metrics_allows_other_types(
        self, mock_entity_repo, mock_vector_repo
    ):
        """Test that disable_data_metrics=True allows non-数据指标 types."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            disable_data_metrics=True,
        )

        result = await resolver.resolve_entity(
            name="腾讯公司",
            entity_type="组织机构",
            embedding=[0.1] * 1536,
        )

        assert result["is_new"] is True
        assert result["match_type"] == "new"
        mock_entity_repo.merge_entity.assert_called_once()

    @pytest.mark.asyncio
    async def test_disable_data_metrics_false_allows_data_metrics(
        self, mock_entity_repo, mock_vector_repo
    ):
        """Test that disable_data_metrics=False allows 数据指标 entities (unless metric string)."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            disable_data_metrics=False,
        )

        result = await resolver.resolve_entity(
            name="GDP增长率",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        # Should create new entity since it doesn't look like metric string
        assert result["is_new"] is True
        mock_entity_repo.merge_entity.assert_called_once()

    @pytest.mark.asyncio
    async def test_metric_string_filtering_still_works_with_config_disabled(
        self, mock_entity_repo, mock_vector_repo
    ):
        """Test that metric string filtering still works when disable_data_metrics=False."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            disable_data_metrics=False,
        )

        # This should still be filtered because it looks like a metric string
        result = await resolver.resolve_entity(
            name="12.73%",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["match_type"] == "filtered_metric"

    @pytest.mark.asyncio
    async def test_disable_data_metrics_default_false(self, mock_entity_repo, mock_vector_repo):
        """Test that disable_data_metrics defaults to False."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

        # By default, data metrics should be allowed
        result = await resolver.resolve_entity(
            name="某个指标",
            entity_type="数据指标",
            embedding=[0.1] * 1536,
        )

        assert result["is_new"] is True


class TestEntityBatchDecisionModels:
    """批量决策模型契约（R-entity-resolution-001）."""

    def test_batch_decision_from_valid_json(self):
        import json

        from modules.knowledge.graph.entity_resolver import (
            EntityBatchDedupOutput,
            EntityBatchDecision,
        )

        raw = json.dumps(
            {
                "decisions": [
                    {
                        "entity_index": 0,
                        "should_merge": True,
                        "target_neo4j_id": "id-1",
                        "target_canonical_name": "OpenAI",
                        "confidence": 0.9,
                    },
                    {"entity_index": 1, "should_merge": False, "confidence": 0.2},
                ]
            }
        )
        out = EntityBatchDedupOutput.model_validate_json(raw)
        assert len(out.decisions) == 2
        assert out.decisions[0].entity_index == 0
        assert out.decisions[0].should_merge is True
        assert out.decisions[1].target_neo4j_id is None

    def test_batch_decision_requires_entity_index(self):
        import pytest
        from pydantic import ValidationError

        from modules.knowledge.graph.entity_resolver import EntityBatchDecision

        with pytest.raises(ValidationError):
            EntityBatchDecision(should_merge=False)

    def test_batch_decision_confidence_bounds(self):
        import pytest
        from pydantic import ValidationError

        from modules.knowledge.graph.entity_resolver import EntityBatchDecision

        with pytest.raises(ValidationError):
            EntityBatchDecision(entity_index=0, should_merge=True, confidence=1.5)


class TestEntityResolverPromptBatchContract:
    """prompt 批量契约（R-llm-integration-001）."""

    def test_prompt_loader_returns_batch_contract(self):
        from core.prompt.loader import PromptLoader

        system = PromptLoader("config/prompts").get("entity_resolver")
        assert "entity_index" in system
        assert "decisions" in system
        # 单实体语义关键词仍保留
        assert "should_merge" in system
        assert "confidence" in system


class TestResolveEntitiesBatchTwoPhase:
    """两阶段批量消解（R-entity-resolution-002/003）."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="merged-id")
        repo.add_alias = AsyncMock()
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        repo.create_entity = AsyncMock(return_value="new-id")
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    def _candidate_sim(self, idx: int):
        from unittest.mock import MagicMock

        sim = MagicMock()
        sim.neo4j_id = f"cand-{idx}"
        sim.similarity = 0.88
        return sim

    def _candidate_entity(self, idx: int):
        from unittest.mock import MagicMock

        e = MagicMock()
        e.id = f"cand-{idx}"
        e.canonical_name = f"Known Entity {idx}"
        e.type = "PERSON"
        return e

    def _entities(self, n: int) -> list[dict]:
        return [
            {
                "name": f"New Entity {i}",
                "type": "PERSON",
                "embedding": [0.1 + i * 0.001] * 8,
                "description": None,
            }
            for i in range(n)
        ]

    def _wire_candidates(self, mock_vector_repo, mock_entity_repo, n: int):
        """每个实体返回 1 个候选（互不相同），触发 LLM 待决。"""
        mock_vector_repo.find_similar_entities = AsyncMock(
            side_effect=lambda **kw: [self._candidate_sim(0)]
        )
        mock_entity_repo.find_entities_by_ids = AsyncMock(
            side_effect=lambda ids: [self._candidate_entity(0) for _ in ids]
        )

    def _batch_output(self, n: int, merge_all: bool = False, order=None):
        from modules.knowledge.graph.entity_resolver import (
            EntityBatchDecision,
            EntityBatchDedupOutput,
        )

        decisions = []
        for i in range(n):
            merge = merge_all or (i % 2 == 0)
            decisions.append(
                EntityBatchDecision(
                    entity_index=i,
                    should_merge=merge,
                    target_neo4j_id=f"cand-{i}" if merge else None,
                    target_canonical_name=f"Known Entity {i}" if merge else None,
                    confidence=0.85,
                )
            )
        if order == "reversed":
            decisions.reverse()
        return EntityBatchDedupOutput(decisions=decisions)

    @pytest.mark.asyncio
    async def test_five_pending_entities_single_llm_call(self, mock_entity_repo, mock_vector_repo):
        """5 个待决实体恰好 1 次 LLM 决策调用（原实现 5 次）."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        self._wire_candidates(mock_vector_repo, mock_entity_repo, 5)
        llm = MagicMock()
        llm.call_at = AsyncMock(return_value=self._batch_output(5))
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        results = await resolver.resolve_entities_batch(entities=self._entities(5))

        assert llm.call_at.await_count == 1
        assert len(results) == 5
        payload = llm.call_at.await_args.args[1]
        assert len(payload["entities"]) == 5
        # 决策应用：merge 的实体 match_type=llm_dedup
        assert results[0]["match_type"] == "llm_dedup"

    @pytest.mark.asyncio
    async def test_exact_match_entities_excluded_from_llm(self, mock_entity_repo, mock_vector_repo):
        """含精确命中实体时不为其发起 LLM 决策."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        existing = MagicMock()
        existing.id = "known-id"
        existing.canonical_name = "Known Entity 0"

        async def find_entity(name, etype):
            return existing if name.startswith("Known") else None

        mock_entity_repo.find_entity = AsyncMock(side_effect=find_entity)
        self._wire_candidates(mock_vector_repo, mock_entity_repo, 3)
        llm = MagicMock()
        llm.call_at = AsyncMock(return_value=self._batch_output(2))
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        entities = self._entities(3)
        entities[0]["name"] = "Known Entity 0"
        results = await resolver.resolve_entities_batch(entities=entities)

        assert llm.call_at.await_count == 1
        payload = llm.call_at.await_args.args[1]
        assert len(payload["entities"]) == 2
        assert results[0]["match_type"] == "exact"

    @pytest.mark.asyncio
    async def test_index_echo_aligns_reversed_decisions(self, mock_entity_repo, mock_vector_repo):
        """decisions 乱序返回时按 entity_index 回显对齐."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        self._wire_candidates(mock_vector_repo, mock_entity_repo, 2)
        llm = MagicMock()
        llm.call_at = AsyncMock(return_value=self._batch_output(2, order="reversed"))
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        results = await resolver.resolve_entities_batch(entities=self._entities(2))

        assert results[0]["match_type"] == "llm_dedup"
        assert results[1]["match_type"] != "llm_dedup"

    @pytest.mark.asyncio
    async def test_mismatch_retries_then_succeeds(self, mock_entity_repo, mock_vector_repo):
        """首次长度不符重试一次后成功."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        self._wire_candidates(mock_vector_repo, mock_entity_repo, 2)
        llm = MagicMock()
        llm.call_at = AsyncMock(side_effect=[self._batch_output(1), self._batch_output(2)])
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        results = await resolver.resolve_entities_batch(entities=self._entities(2))

        assert llm.call_at.await_count == 2
        assert all(r is not None for r in results)

    @pytest.mark.asyncio
    async def test_persistent_failure_degrades_to_per_entity(
        self, mock_entity_repo, mock_vector_repo
    ):
        """批量持续失败 → 逐实体回退，最终结果完整."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        self._wire_candidates(mock_vector_repo, mock_entity_repo, 3)
        llm = MagicMock()
        llm.call_at = AsyncMock(side_effect=RuntimeError("api down"))
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        results = await resolver.resolve_entities_batch(entities=self._entities(3))

        assert len(results) == 3
        assert all(r is not None for r in results)
        # 批量 2 次重试 + 逐实体回退 3 次（每次含批量契约重试 2 次）= 8
        assert llm.call_at.await_count == 8

    @pytest.mark.asyncio
    async def test_chunking_over_max_batch(self, mock_entity_repo, mock_vector_repo):
        """21 个待决实体 → 2 次批量调用（20+1）."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        self._wire_candidates(mock_vector_repo, mock_entity_repo, 21)

        async def respond(call_point, payload, **kwargs):
            from modules.knowledge.graph.entity_resolver import (
                EntityBatchDecision,
                EntityBatchDedupOutput,
            )

            n = len(payload["entities"])
            return EntityBatchDedupOutput(
                decisions=[
                    EntityBatchDecision(
                        entity_index=j,
                        should_merge=False,
                        target_neo4j_id=None,
                        target_canonical_name=None,
                        confidence=0.2,
                    )
                    for j in range(n)
                ]
            )

        llm = MagicMock()
        llm.call_at = AsyncMock(side_effect=respond)
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        results = await resolver.resolve_entities_batch(entities=self._entities(21))

        assert llm.call_at.await_count == 2
        assert len(results) == 21


class TestEntityResolverTokenBudget:
    """批量候选清单 token 限额（R-llm-integration-002）."""

    def test_entity_resolver_limit_is_3000(self):
        from core.llm.config.token_budget import LIMITS
        from core.llm.types import CallPoint

        assert LIMITS[CallPoint.ENTITY_RESOLVER] == 3000


# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for EntityResolver in knowledge module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.models.shared import EntityView


class TestBatchTargetValidation:
    """H3：决策 target_neo4j_id 必须来自候选集（防幻觉 id）."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="merged-id")
        repo.add_alias = AsyncMock()
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        repo.create_entity = AsyncMock(return_value="new-id")
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.mark.asyncio
    async def test_invalid_target_id_falls_back_to_create(self, mock_entity_repo, mock_vector_repo):
        """幻觉 target_neo4j_id（不在候选集）→ 拒绝合并走创建."""
        from modules.knowledge.graph.entity_resolver import (
            EntityBatchDecision,
            EntityBatchDedupOutput,
            EntityResolver,
        )

        sim = MagicMock()
        sim.neo4j_id = "real-cand-id"
        sim.similarity = 0.9
        mock_vector_repo.find_similar_entities = AsyncMock(return_value=[sim])
        ent = MagicMock()
        ent.id = "real-cand-id"
        ent.canonical_name = "Known Entity"
        ent.type = "PERSON"
        mock_entity_repo.find_entities_by_ids = AsyncMock(return_value=[ent])

        llm = MagicMock()
        llm.call_at = AsyncMock(
            return_value=EntityBatchDedupOutput(
                decisions=[
                    EntityBatchDecision(
                        entity_index=0,
                        should_merge=True,
                        target_neo4j_id="hallucinated-id",
                        target_canonical_name="Ghost",
                        confidence=0.99,
                    )
                ]
            )
        )
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        results = await resolver.resolve_entities_batch(
            entities=[{"name": "New Entity", "type": "PERSON", "embedding": [0.1] * 8}]
        )

        assert results[0]["match_type"] != "llm_dedup"
        # 无效目标被拒后走创建路径（_create_entity 内部用 merge_entity 做 upsert）

    @pytest.mark.asyncio
    async def test_single_entity_path_uses_batch_contract(self, mock_entity_repo, mock_vector_repo):
        """单实体 resolve_entity 第 6 步委托批量契约（H2 修复锁定）."""
        from modules.knowledge.graph.entity_resolver import (
            EntityBatchDecision,
            EntityBatchDedupOutput,
            EntityResolver,
        )

        sim = MagicMock()
        sim.neo4j_id = "cand-9"
        sim.similarity = 0.9
        mock_vector_repo.find_similar_entities = AsyncMock(return_value=[sim])
        ent = MagicMock()
        ent.id = "cand-9"
        ent.canonical_name = "Known Entity"
        ent.type = "PERSON"
        mock_entity_repo.find_entities_by_ids = AsyncMock(return_value=[ent])

        llm = MagicMock()
        llm.call_at = AsyncMock(
            return_value=EntityBatchDedupOutput(
                decisions=[
                    EntityBatchDecision(
                        entity_index=0,
                        should_merge=True,
                        target_neo4j_id="cand-9",
                        target_canonical_name="Known Entity",
                        confidence=0.9,
                    )
                ]
            )
        )
        resolver = EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
            llm=llm,
        )

        result = await resolver.resolve_entity(
            name="New Entity", entity_type="PERSON", embedding=[0.1] * 8
        )

        assert result["match_type"] == "llm_dedup"
        # payload 为批量契约形态（entities 列表）
        payload = llm.call_at.await_args.args[1]
        assert "entities" in payload


class TestBatchRetrievalConcurrency:
    """T008: Phase A retrieval is bounded-concurrent with order preserved."""

    @pytest.fixture
    def mock_entity_repo(self):
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j-id-123")
        repo.find_entities_by_ids = AsyncMock(return_value=[])
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.fixture
    def resolver(self, mock_entity_repo, mock_vector_repo):
        from modules.knowledge.graph.entity_resolver import EntityResolver

        return EntityResolver(
            entity_repo=mock_entity_repo,
            vector_repo=mock_vector_repo,
        )

    @pytest.mark.asyncio
    async def test_retrieval_concurrent_bounded_and_ordered(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        import asyncio

        from unittest.mock import patch

        inflight = 0
        max_inflight = 0

        async def slow_exact(name, normalized, entity_type):
            nonlocal inflight, max_inflight
            inflight += 1
            max_inflight = max(max_inflight, inflight)
            await asyncio.sleep(0.02)
            inflight -= 1
            return

        mock_vector_repo.find_similar_entities = AsyncMock(return_value=[])

        entities = [
            {"name": f"Entity{i}", "type": "PERSON", "embedding": [0.1] * 1536} for i in range(20)
        ]
        with patch.object(resolver, "_try_exact_match", new=slow_exact):
            results = await resolver.resolve_entities_batch(entities)

        assert len(results) == 20
        names = [r.get("canonical_name") for r in results]
        assert names == [f"Entity{i}" for i in range(20)], "result order must match input"
        assert max_inflight > 1, "retrieval still fully serial"
        assert max_inflight <= 8, "retrieval exceeds concurrency bound"

    @pytest.mark.asyncio
    async def test_exact_match_short_circuits_vector_lookup(
        self, resolver, mock_entity_repo, mock_vector_repo
    ):
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        existing = {"name": "Known", "neo4j_id": "id-1"}
        from unittest.mock import patch

        with (
            patch.object(
                resolver, "_try_exact_match", new=AsyncMock(return_value=existing)
            ) as mock_exact,
            patch.object(resolver, "_find_similar_candidates", new=AsyncMock()) as mock_similar,
        ):
            results = await resolver.resolve_entities_batch(
                [{"name": "Known", "type": "PERSON", "embedding": [0.1] * 1536}]
            )

        mock_exact.assert_awaited_once()
        mock_similar.assert_not_awaited()
        assert results[0] == existing
