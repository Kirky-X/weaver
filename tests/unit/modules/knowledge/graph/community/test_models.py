# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Unit tests for community data models."""

from dataclasses import fields

from modules.knowledge.graph.community.models import Community


class TestCommunityModelDocs:
    """Documentation contract for ``Community``."""

    def test_docstring_documents_every_field(self) -> None:
        """#13: every dataclass field must be documented in ``Attributes:``."""
        docstring = Community.__doc__ or ""

        for field_info in fields(Community):
            assert f"{field_info.name}:" in docstring, (
                f"Community.{field_info.name} is undocumented"
            )
