# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for EntityResolver module."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from modules.graph_store.entity_resolver import EntityResolver


class TestEntityResolver:
    """Tests for EntityResolver."""

    @pytest.fixture
    def mock_entity_repo(self):
        """Mock entity repository."""
        repo = MagicMock()
        repo.find_entity = AsyncMock(return_value=None)
        repo.find_entity_by_id = AsyncMock(return_value=None)
        repo.merge_entity = AsyncMock(return_value="neo4j_id_123")
        repo.add_alias = AsyncMock()
        return repo

    @pytest.fixture
    def mock_vector_repo(self):
        """Mock vector repository."""
        repo = MagicMock()
        repo.find_similar_entities = AsyncMock(return_value=[])
        repo.upsert_entity_vector = AsyncMock()
        return repo

    @pytest.fixture
    def mock_llm(self):
        """Mock LLM client."""
        llm = MagicMock()
        llm.chat = AsyncMock(return_value=MagicMock(content='{"should_merge": false}'))
        return llm

    @pytest.fixture
    def resolver(self, mock_entity_repo, mock_vector_repo, mock_llm):
        """Create entity resolver instance."""
        return EntityResolver(
            entity_repo=mock_entity_repo, vector_repo=mock_vector_repo, llm=mock_llm
        )

    def test_initialization(self, mock_entity_repo, mock_vector_repo):
        """Test resolver initializes correctly."""
        resolver = EntityResolver(entity_repo=mock_entity_repo, vector_repo=mock_vector_repo)
        assert resolver._entity_repo is mock_entity_repo
        assert resolver._vector_repo is mock_vector_repo

    def test_similarity_threshold(self):
        """Test similarity threshold is 0.85."""
        assert EntityResolver.SIMILARITY_THRESHOLD == 0.85

    def test_max_merge_retries(self):
        """Test max merge retries is 3."""
        assert EntityResolver.MAX_MERGE_RETRIES == 3

    @pytest.mark.asyncio
    async def test_exact_match(self, resolver, mock_entity_repo):
        """Test exact match returns existing entity."""
        mock_entity_repo.find_entity = AsyncMock(
            return_value={"neo4j_id": "existing_id", "canonical_name": "张三"}
        )

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result["neo4j_id"] == "existing_id"
        assert result["is_new"] is False
        assert result["merged"] is False

    @pytest.mark.asyncio
    async def test_vector_similarity_candidates(self, resolver, mock_vector_repo, mock_entity_repo):
        """Test vector similarity finds candidates."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(
            return_value=[MagicMock(neo4j_id="candidate_1", similarity=0.9)]
        )
        mock_entity_repo.find_entity_by_id = AsyncMock(
            return_value={"neo4j_id": "candidate_1", "canonical_name": "张三", "similarity": 0.9}
        )

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_create_new_entity(self, resolver, mock_entity_repo, mock_vector_repo):
        """Test creating new entity when no match found."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(return_value=[])
        mock_entity_repo.merge_entity = AsyncMock(return_value="new_neo4j_id")

        result = await resolver.resolve_entity(
            name="新实体", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result["is_new"] is True
        assert result["neo4j_id"] == "new_neo4j_id"

    @pytest.mark.asyncio
    async def test_merge_with_existing(
        self, resolver, mock_llm, mock_entity_repo, mock_vector_repo
    ):
        """Test merging with existing entity."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(
            return_value=[MagicMock(neo4j_id="existing_id", similarity=0.95)]
        )
        mock_entity_repo.find_entity_by_id = AsyncMock(
            return_value={"neo4j_id": "existing_id", "canonical_name": "张三", "similarity": 0.95}
        )
        mock_llm.chat = AsyncMock(
            return_value=MagicMock(
                content='{"should_merge": true, "target_entity": {"neo4j_id": "existing_id", "canonical_name": "张三"}}'
            )
        )

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result.get("neo4j_id") == "existing_id"

    @pytest.mark.asyncio
    async def test_llm_deduplicate_merge(
        self, resolver, mock_llm, mock_entity_repo, mock_vector_repo
    ):
        """Test LLM deduplication decides to merge."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(
            return_value=[MagicMock(neo4j_id="existing_id", similarity=0.88)]
        )
        mock_entity_repo.find_entity_by_id = AsyncMock(
            return_value={"neo4j_id": "existing_id", "canonical_name": "张三", "similarity": 0.88}
        )
        mock_llm.chat = AsyncMock(
            return_value=MagicMock(
                content='{"should_merge": true, "target_entity": {"canonical_name": "张三", "neo4j_id": "existing_id"}}'
            )
        )

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_llm_deduplicate_no_merge(
        self, resolver, mock_llm, mock_entity_repo, mock_vector_repo
    ):
        """Test LLM deduplication decides not to merge."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(
            return_value=[MagicMock(neo4j_id="existing_id", similarity=0.86)]
        )
        mock_entity_repo.find_entity_by_id = AsyncMock(
            return_value={"neo4j_id": "existing_id", "canonical_name": "李四", "similarity": 0.86}
        )
        mock_llm.chat = AsyncMock(return_value=MagicMock(content='{"should_merge": false}'))

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result is not None

    @pytest.mark.asyncio
    async def test_canonical_name_resolution(self, resolver, mock_entity_repo, mock_vector_repo):
        """Test canonical name resolution."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(return_value=[])
        mock_entity_repo.merge_entity = AsyncMock(return_value="new_id")

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert "canonical_name" in result

    @pytest.mark.asyncio
    async def test_resolve_entities_batch(self, resolver, mock_entity_repo, mock_vector_repo):
        """Test batch entity resolution."""
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(return_value=[])
        mock_entity_repo.merge_entity = AsyncMock(return_value="new_id")

        entities = [
            {"name": "张三", "type": "人物", "embedding": [0.1] * 1024},
            {"name": "李四", "type": "人物", "embedding": [0.2] * 1024},
        ]

        results = await resolver.resolve_entities_batch(entities)

        assert len(results) == 2

    @pytest.mark.asyncio
    async def test_no_llm_uses_first_candidate(self, mock_entity_repo, mock_vector_repo):
        """Test without LLM, uses first candidate."""
        resolver = EntityResolver(
            entity_repo=mock_entity_repo, vector_repo=mock_vector_repo, llm=None
        )
        mock_entity_repo.find_entity = AsyncMock(return_value=None)
        mock_vector_repo.find_similar_entities = AsyncMock(
            return_value=[MagicMock(neo4j_id="candidate_1", similarity=0.9)]
        )
        mock_entity_repo.find_entity_by_id = AsyncMock(
            return_value={"neo4j_id": "candidate_1", "canonical_name": "张三", "similarity": 0.9}
        )

        result = await resolver.resolve_entity(
            name="张三", entity_type="人物", embedding=[0.1] * 1024
        )

        assert result["merged"] is True
