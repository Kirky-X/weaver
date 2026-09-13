# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""Tests for event bus unification.

The container must reuse the module-level ``core.event.event_bus`` singleton
so that sync emitters deep in the resilience layer (CircuitStateEvent) reach
the same handlers the container subscribes. A previous version created a
second ``EventBus()`` instance inside the container, splitting the bus in two
and silently dropping circuit state events.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

import pytest

from core.event import CircuitStateEvent, EventBus
from core.event import event_bus as global_event_bus

_LIFECYCLE = Path(__file__).resolve().parents[3] / "src" / "container" / "lifecycle.py"
_SERVICES = Path(__file__).resolve().parents[3] / "src" / "container" / "services.py"


class TestEventBusUnification:
    """The container must never fork the event bus."""

    def test_container_does_not_instantiate_event_bus(self):
        """lifecycle.py / services.py must reuse the singleton, not new EventBus()."""
        for path in (_LIFECYCLE, _SERVICES):
            source = path.read_text(encoding="utf-8")
            assert "= EventBus()" not in source, (
                f"{path.name} creates a private EventBus instance; "
                "use `from core.event import event_bus` instead"
            )

    def test_global_bus_is_the_container_bus(self):
        """core.event.event_bus is an EventBus instance (sanity)."""
        assert isinstance(global_event_bus, EventBus)

    @pytest.mark.asyncio
    async def test_circuit_state_event_reaches_singleton_subscribers(self):
        """A breaker transition must deliver CircuitStateEvent to subscribers."""
        from core.resilience.circuit_breaker import CBState, CircuitBreaker

        received: list[CircuitStateEvent] = []

        async def handler(event: CircuitStateEvent) -> None:
            received.append(event)

        global_event_bus.subscribe(CircuitStateEvent, handler)
        try:
            breaker = CircuitBreaker(provider="test-provider", threshold=1, timeout_secs=1)
            await breaker.record_failure()  # threshold=1 → CLOSED→OPEN transition

            # emit() schedules publish via create_task; wait for delivery.
            for _ in range(50):
                if received:
                    break
                await asyncio.sleep(0.01)

            assert len(received) == 1
            assert received[0].provider == "test-provider"
            assert received[0].from_state == CBState.CLOSED.value
            assert received[0].to_state == CBState.OPEN.value
        finally:
            handlers = global_event_bus._handlers.get(CircuitStateEvent, [])
            if handler in handlers:
                handlers.remove(handler)


class TestEventBusUnsubscribe:
    """unsubscribe() must fully detach handlers (restart-safety)."""

    @pytest.mark.asyncio
    async def test_unsubscribe_stops_delivery(self):
        from core.event import BaseEvent

        @dataclass
        class _Probe(BaseEvent):
            value: int = 0

        received: list[int] = []

        async def handler(event) -> None:
            received.append(event.value)

        global_event_bus.subscribe(_Probe, handler)
        await global_event_bus.publish(_Probe(value=1))
        assert received == [1]

        global_event_bus.unsubscribe(_Probe, handler)
        global_event_bus.publish(_Probe(value=2))
        await asyncio.sleep(0.05)
        assert received == [1]

        # Unsubscribing an unknown handler is a no-op
        global_event_bus.unsubscribe(_Probe, handler)
