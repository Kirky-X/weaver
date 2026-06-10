# Copyright (c) 2026 KirkyX. All Rights Reserved
"""NarrativeNode: Represents a narrative framing of an event.

Captures how different sources frame the same event through
their editorial lens, including bias, frame, tone, and emphasis.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class NarrativeNode:
    """Narrative framing of an event from a specific source perspective.

    Attributes:
        id: Unique identifier for the narrative.
        source_bias: Political/editorial bias of the source (left/center/right).
        frame: How the event is framed (e.g., economic_impact, political, security).
        tone: Emotional tone of the narrative (e.g., critical, neutral, alarmist).
        emphasis: What aspect is emphasized in the narrative.
    """

    id: str
    source_bias: str
    frame: str
    tone: str
    emphasis: str = ""
