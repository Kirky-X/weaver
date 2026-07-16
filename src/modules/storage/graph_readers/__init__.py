# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Graph readers for graph repository - composition-based reader classes.

Each reader handles a single responsibility:
- GraphEntityReader: entity-centric reads (lookup, relations, co-occurrence)
- GraphArticleReader: article-centric reads (article node, entities, relationships)
- GraphVisualizer: visualization reads (nodes, edges, subgraph extraction)
- GraphTraverser: multi-hop traversal (full and aggregate modes)

GraphRepository composes these readers and delegates read operations to them.
"""

from modules.storage.graph_readers.article import GraphArticleReader
from modules.storage.graph_readers.base import GraphReaderBase
from modules.storage.graph_readers.entity import GraphEntityReader
from modules.storage.graph_readers.traverser import GraphTraverser
from modules.storage.graph_readers.visualizer import GraphVisualizer

__all__ = [
    "GraphArticleReader",
    "GraphEntityReader",
    "GraphReaderBase",
    "GraphTraverser",
    "GraphVisualizer",
]
