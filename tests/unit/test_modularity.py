# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for modularity calculation module."""

from modules.community.modularity import (
    ModularityCalculator,
    ModularityResult,
    calculate_modularity,
)


class TestModularityResult:
    """Test ModularityResult dataclass."""

    def test_initialization(self):
        """Test ModularityResult initialization."""
        result = ModularityResult(
            score=0.65,
            resolution=1.0,
            community_count=3,
            community_sizes={0: 5, 1: 3, 2: 2},
            interpretation="good",
        )

        assert result.score == 0.65
        assert result.resolution == 1.0
        assert result.community_count == 3


class TestModularityCalculator:
    """Test ModularityCalculator class."""

    def test_init_default(self):
        """Test default initialization."""
        calc = ModularityCalculator()
        assert calc._resolution == 1.0

    def test_init_custom(self):
        """Test custom initialization."""
        calc = ModularityCalculator(resolution=0.5)
        assert calc._resolution == 0.5

    def test_calculate_empty_graph(self):
        """Test calculation on empty graph."""
        calc = ModularityCalculator()
        result = calc.calculate([], {})

        assert result.score == 0.0
        assert result.community_count == 0

    def test_calculate_no_edges(self):
        """Test calculation with no edges."""
        calc = ModularityCalculator()
        partitions = {"A": 0, "B": 0, "C": 0}
        result = calc.calculate([], partitions)

        assert result.score == 0.0

    def test_calculate_single_community(self):
        """Test calculation with single community."""
        calc = ModularityCalculator()
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("C", "A", 1.0)]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = calc.calculate(edges, partitions)

        assert result.score >= 0.0
        assert result.community_count == 1

    def test_calculate_two_communities(self):
        """Test calculation with two communities."""
        calc = ModularityCalculator()
        edges = [
            ("A", "B", 1.0),
            ("B", "C", 1.0),
            ("X", "Y", 1.0),
        ]
        partitions = {"A": 0, "B": 0, "C": 0, "X": 1, "Y": 1}

        result = calc.calculate(edges, partitions)

        assert result.score >= 0.0
        assert result.community_count == 2

    def test_calculate_with_weights(self):
        """Test calculation with weighted edges."""
        calc = ModularityCalculator()
        edges = [("A", "B", 2.0), ("B", "C", 2.0)]
        partitions = {"A": 0, "B": 0, "C": 0}

        result = calc.calculate(edges, partitions)

        assert result.score >= 0.0

    def test_calculate_from_adjacency(self):
        """Test calculation from adjacency dict."""
        calc = ModularityCalculator()
        adjacency = {
            "A": {"B": 1.0, "C": 1.0},
            "B": {"A": 1.0, "C": 1.0},
            "C": {"A": 1.0, "B": 1.0},
        }
        partitions = {"A": 0, "B": 0, "C": 0}

        result = calc.calculate_from_adjacency(adjacency, partitions)

        assert result.score >= 0.0

    def test_compare_partitions(self):
        """Test partition comparison."""
        calc = ModularityCalculator()
        edges = [("A", "B", 1.0), ("B", "C", 1.0), ("X", "Y", 1.0)]

        partitions1 = {"A": 0, "B": 0, "C": 0, "X": 1, "Y": 1}
        partitions2 = {"A": 0, "B": 1, "C": 2, "X": 3, "Y": 4}

        results = calc.compare_partitions(edges, [partitions1, partitions2])

        assert len(results) == 2
        assert results[0].score >= results[1].score

    def test_interpret_score_excellent(self):
        """Test score interpretation for excellent."""
        calc = ModularityCalculator()
        interp = calc._interpret_score(0.8)

        assert interp == "excellent"

    def test_interpret_score_good(self):
        """Test score interpretation for good."""
        calc = ModularityCalculator()
        interp = calc._interpret_score(0.6)

        assert interp == "good"

    def test_interpret_score_moderate(self):
        """Test score interpretation for moderate."""
        calc = ModularityCalculator()
        interp = calc._interpret_score(0.35)

        assert interp == "moderate"

    def test_interpret_score_weak(self):
        """Test score interpretation for weak."""
        calc = ModularityCalculator()
        interp = calc._interpret_score(0.1)

        assert interp == "weak"

    def test_interpret_score_poor(self):
        """Test score interpretation for poor."""
        calc = ModularityCalculator()
        interp = calc._interpret_score(-0.2)

        assert interp == "poor"

    def test_get_community_sizes(self):
        """Test community sizes calculation."""
        calc = ModularityCalculator()
        partitions = {"A": 0, "B": 0, "C": 1, "D": 1}

        sizes = calc._get_community_sizes(partitions)

        assert sizes[0] == 2
        assert sizes[1] == 2


def test_calculate_modularity_convenience():
    """Test convenience function."""
    edges = [("A", "B", 1.0), ("B", "C", 1.0)]
    partitions = {"A": 0, "B": 0, "C": 0}

    score = calculate_modularity(edges, partitions)

    assert isinstance(score, float)
    assert -1.0 <= score <= 1.0
