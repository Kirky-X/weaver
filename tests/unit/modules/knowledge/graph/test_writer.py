# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Neo4jWriter in knowledge module."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestNeo4jWriterInit:
    """Tests for Neo4jWriter initialization."""

    def test_init_with_pool(self):
        """Test Neo4jWriter initializes with pool."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo"),
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo"),
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_pool = MagicMock()

            writer = Neo4jWriter(pool=mock_pool)

            assert writer._pool is mock_pool
            assert writer._normalizer is None

    def test_init_with_normalizer(self):
        """Test Neo4jWriter initializes with normalizer."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo"),
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo"),
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_pool = MagicMock()
            mock_normalizer = MagicMock()

            writer = Neo4jWriter(pool=mock_pool, relation_type_normalizer=mock_normalizer)

            assert writer._normalizer is mock_normalizer


class TestNeo4jWriterProperties:
    """Tests for Neo4jWriter properties."""

    @pytest.fixture
    def writer(self):
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            return Neo4jWriter(pool=MagicMock())

    def test_entity_repo_property(self, writer):
        """Test entity_repo property returns repository."""
        repo = writer.entity_repo
        assert repo is not None

    def test_article_repo_property(self, writer):
        """Test article_repo property returns repository."""
        repo = writer.article_repo
        assert repo is not None


class TestNeo4jWriterEnsureConstraints:
    """Tests for ensure_constraints()."""

    @pytest.fixture
    def writer(self):
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo"),
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            writer = Neo4jWriter(pool=MagicMock())
            mock_entity_repo.return_value.ensure_constraints = AsyncMock()
            yield writer

    @pytest.mark.asyncio
    async def test_ensure_constraints_calls_repo(self, writer):
        """Test ensure_constraints calls entity repo."""
        await writer.ensure_constraints()

        writer._entity_repo.ensure_constraints.assert_called_once()


class TestNeo4jWriterWrite:
    """Tests for write()."""

    @pytest.fixture
    def mock_state(self):
        """Create mock pipeline state."""
        return {
            "article_id": "test-article-id",
            "raw": MagicMock(
                title="Test Article",
                publish_time=datetime.now(UTC),
                url="https://example.com/test",
            ),
            "cleaned": {"title": "Cleaned Title"},
            "category": MagicMock(value="tech"),
            "score": 0.85,
            "entities": [
                {"name": "Entity 1", "type": "PERSON", "role": "author"},
                {"name": "Entity 2", "type": "ORG", "role": "publisher"},
            ],
            "relations": [],
            "merged_source_ids": [],
        }

    @pytest.fixture
    def writer_with_mocks(self):
        """Create writer with mocked repos."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_entity_repo = MagicMock()
            mock_entity_repo.merge_entities_batch = AsyncMock(return_value={"created": 2})
            mock_entity_repo.add_aliases_batch = AsyncMock()
            mock_entity_repo.find_entity = AsyncMock(
                return_value={"neo4j_id": "entity-id", "canonical_name": "Entity 1"}
            )
            mock_entity_repo.find_entities_by_keys = AsyncMock(return_value=[])
            mock_entity_repo.merge_mentions_batch = AsyncMock(return_value=2)

            mock_article_repo = MagicMock()
            mock_article_repo.create_article = AsyncMock(return_value="article-neo4j-id")
            mock_article_repo.add_mention = AsyncMock()
            mock_article_repo.add_followed_by = AsyncMock()

            mock_entity_repo_cls.return_value = mock_entity_repo
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(pool=MagicMock())
            yield writer, mock_entity_repo, mock_article_repo

    @pytest.mark.asyncio
    async def test_write_without_article_id_raises(self, writer_with_mocks):
        """Test write raises without article_id."""
        writer, _, _ = writer_with_mocks
        state = {"raw": MagicMock(title="Test")}

        with pytest.raises(ValueError, match="article_id not found"):
            await writer.write(state)

    @pytest.mark.asyncio
    async def test_write_creates_article(self, writer_with_mocks, mock_state):
        """Test write creates article node."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        await writer.write(mock_state)

        mock_article_repo.create_article.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_processes_entities(self, writer_with_mocks, mock_state):
        """Test write processes entities."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        await writer.write(mock_state)

        # Should call merge_entities_batch
        mock_entity_repo.merge_entities_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_returns_neo4j_ids(self, writer_with_mocks, mock_state):
        """Test write returns list of Neo4j IDs."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        result = await writer.write(mock_state)

        assert isinstance(result, list)


class TestNeo4jWriterWriteWithRelations:
    """Tests for write() with relations."""

    @pytest.fixture
    def mock_state_with_relations(self):
        """Create mock state with relations."""
        return {
            "article_id": "test-id",
            "raw": MagicMock(
                title="Test",
                publish_time=datetime.now(UTC),
                url="https://example.com",
            ),
            "cleaned": {"title": "Title"},
            "category": "news",
            "score": None,
            "entities": [
                {"name": "Entity 1", "type": "PERSON"},
                {"name": "Entity 2", "type": "ORG"},
            ],
            "relations": [
                {
                    "source": "Entity 1",
                    "target": "Entity 2",
                    "relation_type": "WORKS_FOR",
                },
            ],
            "merged_source_ids": [],
        }

    @pytest.fixture
    def writer_with_mocks(self):
        """Create writer with mocked repos."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_entity_repo = MagicMock()
            mock_entity_repo.merge_entities_batch = AsyncMock(return_value={"created": 2})
            mock_entity_repo.add_aliases_batch = AsyncMock()
            mock_entity_repo.find_entity = AsyncMock(
                return_value={"neo4j_id": "entity-id", "canonical_name": "Entity 1"}
            )
            mock_entity_repo.find_entities_by_keys = AsyncMock(return_value=[])
            mock_entity_repo.merge_mentions_batch = AsyncMock(return_value=2)
            mock_entity_repo.merge_relation = AsyncMock()

            mock_article_repo = MagicMock()
            mock_article_repo.create_article = AsyncMock(return_value="article-id")
            mock_article_repo.add_mention = AsyncMock()

            mock_entity_repo_cls.return_value = mock_entity_repo
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(pool=MagicMock())
            yield writer, mock_entity_repo, mock_article_repo

    @pytest.mark.asyncio
    async def test_write_with_relations_handled(self, writer_with_mocks, mock_state_with_relations):
        """Test write processes relations without error."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        # This test verifies that relations are processed without raising errors
        result = await writer.write(mock_state_with_relations)

        assert isinstance(result, list)

    @pytest.mark.asyncio
    async def test_write_with_normalizer(self, mock_state_with_relations):
        """Test write with relation type normalizer."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_normalizer = MagicMock()
            mock_normalized = MagicMock()
            mock_normalized.name_en = "WORKS_FOR"
            mock_normalized.is_symmetric = False
            mock_normalizer.normalize = AsyncMock(return_value=mock_normalized)

            mock_entity_repo = MagicMock()
            mock_entity_repo.merge_entities_batch = AsyncMock(return_value={"created": 2})
            mock_entity_repo.add_aliases_batch = AsyncMock()
            mock_entity_repo.find_entity = AsyncMock(
                return_value={"neo4j_id": "entity-id", "canonical_name": "Entity 1"}
            )
            mock_entity_repo.find_entities_by_keys = AsyncMock(return_value=[])
            mock_entity_repo.merge_mentions_batch = AsyncMock(return_value=2)
            mock_entity_repo.merge_relation = AsyncMock()

            mock_article_repo = MagicMock()
            mock_article_repo.create_article = AsyncMock(return_value="article-id")

            mock_entity_repo_cls.return_value = mock_entity_repo
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(
                pool=MagicMock(),
                relation_type_normalizer=mock_normalizer,
            )

            result = await writer.write(mock_state_with_relations)

            # Verify writer was created with normalizer
            assert writer._normalizer is mock_normalizer
            assert isinstance(result, list)


class TestNeo4jWriterMergeSources:
    """Tests for write() with merged sources."""

    @pytest.fixture
    def mock_state_with_merges(self):
        """Create mock state with merged source IDs."""
        return {
            "article_id": "primary-id",
            "raw": MagicMock(
                title="Primary Article",
                publish_time=datetime.now(UTC),
                url="https://example.com/primary",
            ),
            "cleaned": {"title": "Primary"},
            "category": "tech",
            "score": 0.9,
            "entities": [],
            "relations": [],
            "merged_source_ids": ["merged-1", "merged-2"],
        }

    @pytest.fixture
    def writer_with_mocks(self):
        """Create writer with mocked repos."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_entity_repo = MagicMock()
            mock_entity_repo.merge_entities_batch = AsyncMock(return_value={"created": 0})

            mock_article_repo = MagicMock()
            mock_article_repo.create_article = AsyncMock(return_value="article-id")
            mock_article_repo.find_article_by_pg_id = AsyncMock(return_value=None)
            mock_article_repo.create_followed_by_relation = AsyncMock()

            mock_entity_repo_cls.return_value = mock_entity_repo
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(pool=MagicMock())
            yield writer, mock_entity_repo, mock_article_repo

    @pytest.mark.asyncio
    async def test_write_creates_followed_by(self, writer_with_mocks, mock_state_with_merges):
        """Test write creates FOLLOWED_BY relationships."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        await writer.write(mock_state_with_merges)

        # Should add FOLLOWED_BY for each merged source
        assert mock_article_repo.create_followed_by_relation.call_count == 2


class TestNeo4jWriterCleanup:
    """Tests for cleanup methods."""

    @pytest.fixture
    def writer_with_mocks(self):
        """Create writer with mocked repos."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_entity_repo = MagicMock()
            mock_entity_repo.delete_orphan_entities = AsyncMock(return_value=5)

            mock_article_repo = MagicMock()
            mock_article_repo.delete_old_articles = AsyncMock(return_value=10)

            mock_entity_repo_cls.return_value = mock_entity_repo
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(pool=MagicMock())
            yield writer, mock_entity_repo, mock_article_repo

    @pytest.mark.asyncio
    async def test_cleanup_orphan_entities(self, writer_with_mocks):
        """Test cleanup_orphan_entities method."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        result = await writer.cleanup_orphan_entities()

        assert result == 5
        mock_entity_repo.delete_orphan_entities.assert_called_once()

    @pytest.mark.asyncio
    async def test_archive_old_articles(self, writer_with_mocks):
        """Test archive_old_articles method."""
        writer, mock_entity_repo, mock_article_repo = writer_with_mocks

        result = await writer.archive_old_articles(days=30)

        assert result == 10
        mock_article_repo.delete_old_articles.assert_called_once_with(30)
        mock_entity_repo.delete_orphan_entities.assert_called_once()


class TestNeo4jWriterEdgeCases:
    """Tests for edge cases in _write_entities and _write_entity_relations."""

    @pytest.fixture
    def writer_with_mocks(self):
        """Create writer with mocked repos."""
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_entity_repo = MagicMock()
            mock_entity_repo.merge_entities_batch = AsyncMock(return_value={"created": 2})
            mock_entity_repo.add_aliases_batch = AsyncMock()
            mock_entity_repo.find_entity = AsyncMock(
                return_value={"neo4j_id": "entity-id", "canonical_name": "Entity 1"}
            )
            mock_entity_repo.merge_mentions_batch = AsyncMock(return_value=1)
            mock_entity_repo.merge_relation = AsyncMock()
            mock_entity_repo.find_entities_by_keys = AsyncMock(return_value=[])

            mock_article_repo = MagicMock()
            mock_article_repo.create_article = AsyncMock(return_value="article-id")

            mock_entity_repo_cls.return_value = mock_entity_repo
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(pool=MagicMock())
            yield writer, mock_entity_repo, mock_article_repo

    @pytest.mark.asyncio
    async def test_write_entities_batch_failure(self, writer_with_mocks):
        """Test _write_entities returns empty when batch merge fails."""
        writer, mock_entity_repo, _ = writer_with_mocks
        mock_entity_repo.merge_entities_batch = AsyncMock(side_effect=Exception("Batch error"))

        state = {
            "article_id": "test-id",
            "raw": MagicMock(title="T", publish_time=None, url=""),
            "entities": [{"name": "E1", "type": "PERSON"}],
        }

        result = await writer._write_entities("article-neo4j-id", state["entities"], state)
        assert result == []

    @pytest.mark.asyncio
    async def test_write_entities_with_alias(self, writer_with_mocks):
        """Test _write_entities creates alias when name != canonical_name."""
        writer, mock_entity_repo, _ = writer_with_mocks
        # find_entity returns different canonical_name -> alias created
        mock_entity_repo.find_entity = AsyncMock(
            side_effect=[
                {"neo4j_id": "id1", "canonical_name": "Canonical E1"},  # resolve canonical
                {"neo4j_id": "id1", "canonical_name": "Canonical E1"},  # find after batch
            ]
        )
        # find_entities_by_keys returns the entity so entity_ids is populated
        mock_entity_repo.find_entities_by_keys = AsyncMock(
            return_value=[{"canonical_name": "Canonical E1", "type": "PERSON", "neo4j_id": "id1"}]
        )

        state = {
            "article_id": "test-id",
            "entities": [{"name": "E1 Alias", "type": "PERSON", "role": "author"}],
        }

        result = await writer._write_entities("article-neo4j-id", state["entities"], state)
        assert len(result) == 1
        mock_entity_repo.add_aliases_batch.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_entities_skips_invalid(self, writer_with_mocks):
        """Test _write_entities skips entities without name or type."""
        writer, mock_entity_repo, _ = writer_with_mocks

        entities = [
            {"name": "", "type": "PERSON"},  # no name
            {"name": "E2", "type": ""},  # no type
            {"name": None, "type": "ORG"},  # None name
        ]

        state = {"article_id": "test-id"}
        result = await writer._write_entities("article-neo4j-id", entities, state)
        assert result == []

    @pytest.mark.asyncio
    async def test_write_entities_empty(self, writer_with_mocks):
        """Test _write_entities returns empty for empty list."""
        writer, _, _ = writer_with_mocks
        result = await writer._write_entities("id", [], {})
        assert result == []

    @pytest.mark.asyncio
    async def test_write_entity_relations_no_ids(self, writer_with_mocks):
        """Test _write_entity_relations skips when source/target not in map."""
        writer, _, _ = writer_with_mocks

        relations = [{"source": "Unknown", "target": "AlsoUnknown", "relation_type": "X"}]
        name_to_id = {"Entity1": "id1"}

        count = await writer._write_entity_relations(relations, name_to_id)
        assert count == 0

    @pytest.mark.asyncio
    async def test_write_entity_relations_normalizer_no_name_en(self, writer_with_mocks):
        """Test _write_entity_relations with normalizer returning no name_en."""
        writer, mock_entity_repo, _ = writer_with_mocks

        mock_normalizer = MagicMock()
        mock_normalized = MagicMock()
        mock_normalized.name_en = None
        mock_normalized.is_symmetric = False
        mock_normalizer.normalize = AsyncMock(return_value=mock_normalized)
        mock_normalizer.record_unknown = AsyncMock()
        writer._normalizer = mock_normalizer

        relations = [{"source": "E1", "target": "E2", "relation_type": "CUSTOM"}]
        name_to_id = {"E1": "id1", "E2": "id2"}

        count = await writer._write_entity_relations(relations, name_to_id)
        assert count == 1
        mock_normalizer.record_unknown.assert_called_once()

    @pytest.mark.asyncio
    async def test_write_entity_relations_normalizer_exception(self, writer_with_mocks):
        """Test _write_entity_relations handles normalizer exception."""
        writer, mock_entity_repo, _ = writer_with_mocks

        mock_normalizer = MagicMock()
        mock_normalizer.normalize = AsyncMock(side_effect=Exception("Norm error"))
        writer._normalizer = mock_normalizer

        relations = [{"source": "E1", "target": "E2", "relation_type": "X"}]
        name_to_id = {"E1": "id1", "E2": "id2"}

        count = await writer._write_entity_relations(relations, name_to_id)
        assert count == 1

    @pytest.mark.asyncio
    async def test_write_entity_relations_merge_failure(self, writer_with_mocks):
        """Test _write_entity_relations handles merge_relation exception."""
        writer, mock_entity_repo, _ = writer_with_mocks
        mock_entity_repo.merge_relation = AsyncMock(side_effect=Exception("Merge error"))

        relations = [{"source": "E1", "target": "E2", "relation_type": "X"}]
        name_to_id = {"E1": "id1", "E2": "id2"}

        count = await writer._write_entity_relations(relations, name_to_id)
        assert count == 0

    @pytest.mark.asyncio
    async def test_write_entity_relations_dual_write(self, writer_with_mocks):
        """Test _write_entity_relations with dual-write env var."""
        writer, mock_entity_repo, _ = writer_with_mocks

        relations = [{"source": "E1", "target": "E2", "relation_type": "X"}]
        name_to_id = {"E1": "id1", "E2": "id2"}

        with patch.dict("os.environ", {"WEAVER_DUAL_WRITE": "true"}):
            count = await writer._write_entity_relations(relations, name_to_id)

        assert count == 1
        assert mock_entity_repo.merge_relation.call_count == 2  # typed + RELATED_TO

    @pytest.mark.asyncio
    async def test_write_entity_relations_empty(self, writer_with_mocks):
        """Test _write_entity_relations with empty relations."""
        writer, _, _ = writer_with_mocks
        count = await writer._write_entity_relations([], {})
        assert count == 0

    @pytest.mark.asyncio
    async def test_write_entity_relations_missing_fields(self, writer_with_mocks):
        """Test _write_entity_relations skips incomplete relations."""
        writer, _, _ = writer_with_mocks

        relations = [
            {"source": "", "target": "E2", "relation_type": "X"},
            {"source": "E1", "target": "", "relation_type": "X"},
            {"source": "E1", "target": "E2", "relation_type": ""},
        ]
        name_to_id = {"E1": "id1", "E2": "id2"}

        count = await writer._write_entity_relations(relations, name_to_id)
        assert count == 0


class TestNeo4jWriterFollowedBy:
    """Extended tests for _create_followed_relations."""

    @pytest.fixture
    def writer_with_mocks(self):
        with (
            patch("modules.knowledge.graph.neo4j_writer.Neo4jEntityRepo") as mock_entity_repo_cls,
            patch("modules.knowledge.graph.neo4j_writer.Neo4jArticleRepo") as mock_article_repo_cls,
        ):
            from modules.knowledge.graph.neo4j_writer import Neo4jWriter

            mock_article_repo = MagicMock()
            mock_article_repo.create_followed_by_relation = AsyncMock()
            mock_article_repo.find_article_by_pg_id = AsyncMock(return_value=None)

            mock_entity_repo_cls.return_value = MagicMock()
            mock_article_repo_cls.return_value = mock_article_repo

            writer = Neo4jWriter(pool=MagicMock())
            return writer, mock_article_repo

    @pytest.mark.asyncio
    async def test_followed_with_time_gap(self, writer_with_mocks):
        """Test _create_followed_relations calculates time gap."""
        writer, mock_article_repo = writer_with_mocks

        source_time = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        target_time = datetime(2026, 1, 1, 15, 0, 0, tzinfo=UTC)

        mock_article_repo.find_article_by_pg_id = AsyncMock(
            return_value={"publish_time": source_time}
        )

        await writer._create_followed_relations("article-1", ["source-1"], target_time)

        mock_article_repo.create_followed_by_relation.assert_called_once()
        call_kwargs = mock_article_repo.create_followed_by_relation.call_args
        assert call_kwargs.kwargs["time_gap_hours"] == 3.0

    @pytest.mark.asyncio
    async def test_followed_with_error(self, writer_with_mocks):
        """Test _create_followed_relations handles error gracefully."""
        writer, mock_article_repo = writer_with_mocks
        mock_article_repo.find_article_by_pg_id = AsyncMock(side_effect=Exception("DB error"))

        # Should not raise
        await writer._create_followed_relations("article-1", ["source-1"], None)
        mock_article_repo.create_followed_by_relation.assert_not_called()

    @pytest.mark.asyncio
    async def test_followed_no_publish_time(self, writer_with_mocks):
        """Test _create_followed_relations with no publish time."""
        writer, mock_article_repo = writer_with_mocks

        await writer._create_followed_relations("article-1", ["source-1"], None)

        mock_article_repo.create_followed_by_relation.assert_called_once()
        call_kwargs = mock_article_repo.create_followed_by_relation.call_args
        assert call_kwargs.kwargs["time_gap_hours"] is None
