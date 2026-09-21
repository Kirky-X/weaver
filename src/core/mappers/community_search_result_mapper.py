# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Kirky.X

from typing import Any

from core.models.shared import CommunitySearchResultView


class CommunitySearchResultMapper:
    """Maps community search results to CommunitySearchResultView.

    Implements: MapperProtocol
    """

    def to_view(self, data: dict[str, Any]) -> CommunitySearchResultView:
        converted = dict(data)
        # Ensure score is float
        if "score" in converted and converted["score"] is not None:
            try:
                converted["score"] = float(converted["score"])
            except (ValueError, TypeError) as exc:
                # 复用组件：非数值 score 应给出可定位的错误，而不是裸
                # ValueError。
                raise ValueError(f"Invalid score value: {converted['score']!r}") from exc
        return CommunitySearchResultView.model_validate(converted)
