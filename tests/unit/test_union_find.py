"""Unit tests for Union-Find algorithm used in batch merger."""

import pytest
from modules.pipeline.nodes.batch_merger import UnionFind


class TestUnionFind:
    """Tests for Union-Find data structure."""

    def test_union_find_initialization(self):
        """Test UnionFind initializes with all elements as separate sets."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        # Each element should be its own parent
        for elem in elements:
            assert uf.find(elem) == elem

    def test_find_with_path_compression(self):
        """Test find compresses path."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        # Union a and b
        uf.union("a", "b")

        # Find should return root
        assert uf.find("a") == uf.find("b")
        assert uf.find("a") != uf.find("c")

    def test_union_same_element(self):
        """Test unioning same element is no-op."""
        elements = ["a", "b"]
        uf = UnionFind(elements)

        uf.union("a", "a")

        # Should still be separate
        assert uf.find("a") == "a"

    def test_union_different_elements(self):
        """Test unioning different elements merges sets."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        uf.union("a", "b")

        assert uf.find("a") == uf.find("b")
        assert uf.find("a") != uf.find("c")

    def test_union_transitive(self):
        """Test union is transitive."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        uf.union("a", "b")
        uf.union("b", "c")

        # All should now be in same set
        assert uf.find("a") == uf.find("b") == uf.find("c")

    def test_get_groups(self):
        """Test get_groups returns correct groups."""
        elements = ["a", "b", "c", "d"]
        uf = UnionFind(elements)

        uf.union("a", "b")
        uf.union("c", "d")

        groups = uf.get_groups()

        # Should have 2 groups
        assert len(groups) == 2

        # Each group should have correct members
        group_values = [set(v) for v in groups.values()]
        assert {"a", "b"} in group_values
        assert {"c", "d"} in group_values

    def test_get_groups_all_separate(self):
        """Test get_groups when no unions performed."""
        elements = ["a", "b", "c"]
        uf = UnionFind(elements)

        groups = uf.get_groups()

        # Each element is its own group
        assert len(groups) == 3
        for elem in elements:
            assert elem in groups[elem]

    def test_rank_based_union(self):
        """Test union uses rank for optimization."""
        # Create UnionFind with ranks
        uf = UnionFind(["a", "b", "c"])

        # Initially all ranks are 0
        assert uf._rank["a"] == 0

        # Union a and b
        uf.union("a", "b")

        # One should have rank 1
        root = uf.find("a")
        assert uf._rank[root] == 1

    def test_find_nonexistent(self):
        """Test find raises error for nonexistent element."""
        uf = UnionFind(["a", "b"])

        with pytest.raises(KeyError):
            uf.find("nonexistent")


class TestUnionFindEdgeCases:
    """Edge case tests for UnionFind."""

    def test_single_element(self):
        """Test with single element."""
        uf = UnionFind(["a"])

        assert uf.find("a") == "a"
        groups = uf.get_groups()
        assert len(groups) == 1
        assert groups["a"] == ["a"]

    def test_empty_set(self):
        """Test with empty set."""
        uf = UnionFind([])

        groups = uf.get_groups()
        assert len(groups) == 0

    def test_duplicate_union_calls(self):
        """Test multiple union calls between same elements."""
        uf = UnionFind(["a", "b", "c"])

        uf.union("a", "b")
        uf.union("a", "b")  # Duplicate
        uf.union("a", "b")  # Another duplicate

        # Should still be in same group
        assert uf.find("a") == uf.find("b")

    def test_large_set(self):
        """Test with larger set of elements."""
        elements = [f"elem_{i}" for i in range(100)]
        uf = UnionFind(elements)

        # Connect every other element
        for i in range(0, 99, 2):
            uf.union(elements[i], elements[i + 1])

        groups = uf.get_groups()

        # Should have 50 groups
        assert len(groups) == 50


class TestUnionFindAdd:
    """Tests for UnionFind add method."""

    def test_add_new_element(self):
        """Test adding new element dynamically."""
        uf = UnionFind(["a", "b"])
        uf.add("c")
        assert "c" in uf._parent
        assert uf._parent["c"] == "c"
        assert uf._rank["c"] == 0

    def test_add_existing_element_no_change(self):
        """Test adding existing element doesn't change state."""
        uf = UnionFind(["a", "b"])
        original_parent = uf._parent["a"]
        uf.add("a")
        assert uf._parent["a"] == original_parent

    def test_add_and_union(self):
        """Test adding element and then union."""
        uf = UnionFind(["a"])
        uf.add("b")
        uf.union("a", "b")
        assert uf.find("a") == uf.find("b")

    def test_add_multiple_elements(self):
        """Test adding multiple elements."""
        uf = UnionFind(["a"])
        for i in range(10):
            uf.add(f"new_{i}")
        assert len(uf._parent) == 11

    def test_add_after_get_groups(self):
        """Test adding element after get_groups."""
        uf = UnionFind(["a", "b"])
        uf.union("a", "b")
        groups1 = uf.get_groups()
        uf.add("c")
        groups2 = uf.get_groups()
        assert len(groups2) == 2
