# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Rate limiting middleware using slowapi."""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)
