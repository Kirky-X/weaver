from typing import Any

from core.models.shared import CommunityView


class CommunityMapper:
    """Maps community data to CommunityView.

    Implements: Data Contract Layer — CommunityMapper
    """

    @staticmethod
    def to_view(data: dict[str, Any]) -> CommunityView:
        return CommunityView.model_validate(data)
