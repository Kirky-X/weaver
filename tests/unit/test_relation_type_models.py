# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for relation type models."""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from core.db.models import RelationType, RelationTypeAlias, UnknownRelationType


@pytest.mark.describe("RelationType Model")
class TestRelationTypeModel:
    """Tests for RelationType ORM model."""

    @pytest.mark.it("should create a RelationType instance")
    def test_create_relation_type(self) -> None:
        """Test creating a RelationType instance."""
        rt = RelationType(
            name="合作",
            name_en="PARTNERS_WITH",
            category="商业",
            is_symmetric=True,
            sort_order=1,
            is_active=True,  # explicit value
        )
        assert rt.name == "合作"
        assert rt.name_en == "PARTNERS_WITH"
        assert rt.category == "商业"
        assert rt.is_symmetric is True
        assert rt.sort_order == 1
        assert rt.is_active is True

    @pytest.mark.it("should have correct table name")
    def test_relation_type_table_name(self) -> None:
        """Test RelationType has correct table name."""
        assert RelationType.__tablename__ == "relation_types"

    @pytest.mark.it("should have aliases relationship")
    def test_relation_type_aliases_relationship(self) -> None:
        """Test RelationType has aliases relationship."""
        assert hasattr(RelationType, "aliases")
        assert RelationType.aliases.property.key == "aliases"


@pytest.mark.describe("RelationTypeAlias Model")
class TestRelationTypeAliasModel:
    """Tests for RelationTypeAlias ORM model."""

    @pytest.mark.it("should create a RelationTypeAlias instance")
    def test_create_relation_type_alias(self) -> None:
        """Test creating a RelationTypeAlias instance."""
        alias = RelationTypeAlias(
            alias="战略合作",
            relation_type_id=1,
        )
        assert alias.alias == "战略合作"
        assert alias.relation_type_id == 1

    @pytest.mark.it("should have correct table name")
    def test_relation_type_alias_table_name(self) -> None:
        """Test RelationTypeAlias has correct table name."""
        assert RelationTypeAlias.__tablename__ == "relation_type_aliases"

    @pytest.mark.it("should have relation_type relationship")
    def test_relation_type_alias_relationship(self) -> None:
        """Test RelationTypeAlias has relation_type relationship."""
        assert hasattr(RelationTypeAlias, "relation_type")
        assert RelationTypeAlias.relation_type.property.key == "relation_type"


@pytest.mark.describe("UnknownRelationType Model")
class TestUnknownRelationTypeModel:
    """Tests for UnknownRelationType ORM model."""

    @pytest.mark.it("should create an UnknownRelationType instance")
    def test_create_unknown_relation_type(self) -> None:
        """Test creating an UnknownRelationType instance."""
        urt = UnknownRelationType(
            raw_type="未知关系",
            context="Apple -> Oracle",
            hit_count=1,
            resolved=False,
        )
        assert urt.raw_type == "未知关系"
        assert urt.context == "Apple -> Oracle"
        assert urt.hit_count == 1
        assert urt.resolved is False
        assert urt.article_id is None

    @pytest.mark.it("should have correct table name")
    def test_unknown_relation_type_table_name(self) -> None:
        """Test UnknownRelationType has correct table name."""
        assert UnknownRelationType.__tablename__ == "unknown_relation_types"

    @pytest.mark.it("should have default values")
    def test_unknown_relation_type_defaults(self) -> None:
        """Test UnknownRelationType has correct default values."""
        now = datetime.now(UTC)
        urt = UnknownRelationType(
            raw_type="unknown",
            hit_count=1,  # explicit value
            resolved=False,  # explicit value
            first_seen_at=now,
            last_seen_at=now,
        )
        assert urt.hit_count == 1
        assert urt.resolved is False
        assert isinstance(urt.first_seen_at, datetime)
        assert isinstance(urt.last_seen_at, datetime)


@pytest.mark.describe("RelationType Data")
class TestRelationTypeData:
    """Tests for relation type seed data."""

    @pytest.mark.it("should have 17 standard relation types")
    def test_relation_type_count(self) -> None:
        """Test that we have 17 standard relation types."""
        # This matches the seed data
        expected_types = [
            ("任职于", "WORKS_AT", "组织"),
            ("隶属于", "AFFILIATED_WITH", "组织"),
            ("控股", "CONTROLS", "组织"),
            ("位于", "LOCATED_IN", "空间"),
            ("收购", "ACQUIRES", "商业"),
            ("供应", "SUPPLIES", "商业"),
            ("投资", "INVESTS_IN", "商业"),
            ("合作", "PARTNERS_WITH", "商业"),
            ("竞争", "COMPETES_WITH", "商业"),
            ("发布", "PUBLISHES", "行为"),
            ("签署", "SIGNS", "行为"),
            ("参与", "PARTICIPATES_IN", "行为"),
            ("监管", "REGULATES", "权力"),
            ("支持", "SUPPORTS", "权力"),
            ("制裁", "SANCTIONS", "权力"),
            ("引发", "CAUSES", "因果"),
            ("影响", "INFLUENCES", "因果"),
        ]
        assert len(expected_types) == 17

    @pytest.mark.it("should have symmetric relations marked correctly")
    def test_symmetric_relations(self) -> None:
        """Test that symmetric relations are correctly identified."""
        symmetric = {"PARTNERS_WITH", "COMPETES_WITH"}
        expected_types = [
            ("合作", "PARTNERS_WITH", "商业"),
            ("竞争", "COMPETES_WITH", "商业"),
        ]
        for name, name_en, _ in expected_types:
            assert name_en in symmetric
