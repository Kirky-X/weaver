#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: © 2026 Weaver Contributors
"""SSE client test script for validating streaming endpoints.

Usage:
    python tests/scripts/test_sse_client.py --url http://localhost:8000/api/v1/pipeline/url/stream --api-key YOUR_KEY
"""

from __future__ import annotations

import argparse
import asyncio
import json

import httpx


async def sse_stream(url: str, api_key: str, test_url: str) -> None:
    """Test SSE streaming endpoint.

    Args:
        url: SSE endpoint URL.
        api_key: API key for authentication.
        test_url: URL to process through pipeline.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }

    payload = {"url": test_url}

    print(f"Connecting to {url}...")
    print(f"Processing URL: {test_url}")
    print("-" * 50)

    event_count = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            print(f"Response status: {response.status_code}")
            print(f"Headers: {dict(response.headers)}")
            print("-" * 50)

            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event_count += 1
                    data = json.loads(line[6:])  # Remove "data: " prefix

                    event_type = data.get("type", "unknown")
                    timestamp = data.get("timestamp", "")

                    if event_type == "log":
                        level = data.get("level", "info")
                        message = data.get("message", "")
                        print(f"[{timestamp}] [{level.upper()}] {message}")

                    elif event_type == "result":
                        print(f"[{timestamp}] RESULT: {json.dumps(data.get('data', {}), indent=2)}")

                    elif event_type == "error":
                        message = data.get("message", "")
                        print(f"[{timestamp}] ERROR: {message}")

                    elif event_type == "heartbeat":
                        print(".", end="", flush=True)

                    else:
                        print(f"[{timestamp}] {event_type}: {data}")

            print()
            print("-" * 50)
            print(f"Stream completed. Total events: {event_count}")


async def disconnect(url: str, api_key: str, test_url: str) -> None:
    """Test client disconnect handling.

    Args:
        url: SSE endpoint URL.
        api_key: API key for authentication.
        test_url: URL to process.
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "text/event-stream",
    }

    payload = {"url": test_url}

    print("Testing disconnect handling...")
    print("Will disconnect after 3 events...")

    event_count = 0

    async with httpx.AsyncClient(timeout=120.0) as client:
        async with client.stream("POST", url, headers=headers, json=payload) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    event_count += 1
                    data = json.loads(line[6:])
                    print(f"Event {event_count}: {data.get('type', 'unknown')}")

                    if event_count >= 3:
                        print("Disconnecting...")
                        break

    print(f"Disconnected after {event_count} events")


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Test SSE streaming endpoint")
    parser.add_argument(
        "--url",
        default="http://localhost:8000/api/v1/pipeline/url/stream",
        help="SSE endpoint URL",
    )
    parser.add_argument(
        "--api-key",
        required=True,
        help="API key for authentication",
    )
    parser.add_argument(
        "--test-url",
        default="https://example.com",
        help="URL to process through pipeline",
    )
    parser.add_argument(
        "--test-disconnect",
        action="store_true",
        help="Test disconnect handling",
    )

    args = parser.parse_args()

    if args.test_disconnect:
        asyncio.run(disconnect(args.url, args.api_key, args.test_url))
    else:
        asyncio.run(sse_stream(args.url, args.api_key, args.test_url))


if __name__ == "__main__":
    main()
