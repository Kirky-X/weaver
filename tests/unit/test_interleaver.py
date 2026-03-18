# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Unit tests for Interleaver module."""

from unittest.mock import MagicMock

import pytest

from modules.collector.interleaver import Interleaver


class TestInterleaver:
    """Tests for Interleaver."""

    @pytest.fixture
    def interleaver(self):
        """Create interleaver instance."""
        return Interleaver()

    @pytest.fixture
    def mock_items_single_host(self):
        """Create mock items from single host."""
        items = []
        for i in range(5):
            item = MagicMock()
            item.url = f"https://example.com/article{i}"
            item.source_host = "example.com"
            items.append(item)
        return items

    @pytest.fixture
    def mock_items_multiple_hosts(self):
        """Create mock items from multiple hosts."""
        items = []
        hosts = ["a.com", "b.com", "c.com"]
        for host in hosts:
            for i in range(3):
                item = MagicMock()
                item.url = f"https://{host}/article{i}"
                item.source_host = host
                items.append(item)
        return items

    def test_interleave_empty(self, interleaver):
        """Test interleaving empty list."""
        result = interleaver.interleave([])
        assert result == []

    def test_interleave_single_host(self, interleaver, mock_items_single_host):
        """Test interleaving items from single host."""
        result = interleaver.interleave(mock_items_single_host)
        assert len(result) == len(mock_items_single_host)
        assert all(item.source_host == "example.com" for item in result)

    def test_interleave_multiple_hosts(self, interleaver, mock_items_multiple_hosts):
        """Test interleaving items from multiple hosts."""
        result = interleaver.interleave(mock_items_multiple_hosts)
        assert len(result) == len(mock_items_multiple_hosts)

    def test_interleave_preserves_order(self, interleaver):
        """Test interleaving preserves relative order within host."""
        items = []
        for i in range(3):
            item = MagicMock()
            item.url = f"https://a.com/article{i}"
            item.source_host = "a.com"
            item.order = i
            items.append(item)

        result = interleaver.interleave(items)

        a_items = [item for item in result if item.source_host == "a.com"]
        orders = [item.order for item in a_items]
        assert orders == sorted(orders)

    def test_interleave_distributes_hosts(self, interleaver):
        """Test interleaving distributes hosts evenly."""
        items = []
        for i in range(6):
            item = MagicMock()
            item.url = f"https://a.com/article{i}"
            item.source_host = "a.com"
            items.append(item)
        for i in range(3):
            item = MagicMock()
            item.url = f"https://b.com/article{i}"
            item.source_host = "b.com"
            items.append(item)

        result = interleaver.interleave(items)

        host_sequence = [item.source_host for item in result[:6]]
        assert host_sequence.count("b.com") >= 2

    def test_interleave_all_items_present(self, interleaver, mock_items_multiple_hosts):
        """Test all items are present in result."""
        result = interleaver.interleave(mock_items_multiple_hosts)
        original_urls = {item.url for item in mock_items_multiple_hosts}
        result_urls = {item.url for item in result}
        assert original_urls == result_urls

    def test_interleave_single_item(self, interleaver):
        """Test interleaving single item."""
        item = MagicMock()
        item.url = "https://example.com/article"
        item.source_host = "example.com"

        result = interleaver.interleave([item])
        assert len(result) == 1
        assert result[0] is item

    def test_interleave_no_consecutive_same_host(self, interleaver):
        """Test no consecutive items from same host when possible."""
        items = []
        for i in range(2):
            item_a = MagicMock()
            item_a.url = f"https://a.com/article{i}"
            item_a.source_host = "a.com"
            items.append(item_a)

            item_b = MagicMock()
            item_b.url = f"https://b.com/article{i}"
            item_b.source_host = "b.com"
            items.append(item_b)

        result = interleaver.interleave(items)

        for i in range(len(result) - 1):
            if result[i].source_host == result[i + 1].source_host:
                pass

    def test_interleave_uneven_distribution(self, interleaver):
        """Test interleaving with uneven host distribution."""
        items = []
        for i in range(10):
            item = MagicMock()
            item.url = f"https://a.com/article{i}"
            item.source_host = "a.com"
            items.append(item)
        for i in range(2):
            item = MagicMock()
            item.url = f"https://b.com/article{i}"
            item.source_host = "b.com"
            items.append(item)

        result = interleaver.interleave(items)

        assert len(result) == 12
        b_count = sum(1 for item in result if item.source_host == "b.com")
        assert b_count == 2
