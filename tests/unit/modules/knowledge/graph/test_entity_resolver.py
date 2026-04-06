# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for EntityResolver in knowledge module."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


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
        mock_entity_repo.find_entity.return_value = {
            "neo4j_id": "existing-id",
            "canonical_name": "Test Entity",
        }

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
            {"neo4j_id": "similar-id", "canonical_name": "Similar Entity", "type": "PERSON"}
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
        mock_entity_repo.find_entity.return_value = {
            "neo4j_id": "existing-id",
            "canonical_name": "Existing Entity",
        }

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
            {"neo4j_id": "existing-id", "canonical_name": "Original Name"},  # original name found
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
            {"neo4j_id": "sim-id", "canonical_name": "TargetEntity", "type": "PERSON"}
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
            {"neo4j_id": "sim-id", "canonical_name": "DifferentEntity", "type": "PERSON"}
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
        """Test resolve_entity merges via LLM dedup."""
        from modules.knowledge.graph.entity_resolver import EntityResolver

        mock_llm = MagicMock()
        mock_llm.chat = AsyncMock(
            return_value=MagicMock(
                content='{"should_merge": true, "confidence": 0.85, "target_entity": {"canonical_name": "TargetEntity", "neo4j_id": "target-id"}}'
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
            {
                "neo4j_id": "sim-id",
                "canonical_name": "TargetEntity",
                "type": "PERSON",
                "similarity": 0.9,
            }
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
            {"neo4j_id": "sim-id", "canonical_name": "SomeEntity", "type": "PERSON"}
        ]
        # find_entity sequence:
        # 1st call: normalized name "TestEntity" -> None
        # (no 2nd call because normalized==name)
        # 2nd call (actually): canonical_name "CanonicalName" -> found
        mock_entity_repo.find_entity.side_effect = [
            None,  # normalized name lookup at line 120
            {
                "neo4j_id": "canonical-id",
                "canonical_name": "CanonicalName",
            },  # canonical lookup at line 243
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
            return_value={
                "neo4j_id": "concurrent-id",
                "canonical_name": "TestEntity",
            }
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
                {"neo4j_id": "alias-id", "canonical_name": "CanonicalEntity"},
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
                {"neo4j_id": "orig-id", "canonical_name": "OriginalEntity"},  # original found
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
