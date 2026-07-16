# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors

from typing import Any

from core.models.shared import CommunityView


class CommunityMapper:
    """Maps community data to CommunityView.

    Implements: MapperProtocol
    """

    def to_view(self, data: dict[str, Any]) -> CommunityView:
        return CommunityView.model_validate(data)
