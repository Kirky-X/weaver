from typing import Any

from core.models.shared import CommunitySearchResultView


class CommunitySearchResultMapper:
    """Maps community search results to CommunitySearchResultView.

    Implements: Data Contract Layer — CommunitySearchResultMapper
    """

    @staticmethod
    def to_view(data: dict[str, Any]) -> CommunitySearchResultView:
        converted = dict(data)
        # Ensure score is float
        if "score" in converted and converted["score"] is not None:
            converted["score"] = float(converted["score"])
        return CommunitySearchResultView.model_validate(converted)
