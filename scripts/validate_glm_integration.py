#!/usr/bin/env python
# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Quick validation script for GLM-4.7 LLM integration.

Tests:
1. Configuration loading
2. GLM-4.7 provider availability
3. Simple chat completion request

Usage:
    uv run python scripts/validate_glm_integration.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.settings import Settings
from core.llm.config_manager import LLMConfigManager
from core.llm.providers.chat import ChatProvider


async def main() -> None:
    """Run GLM-4.7 integration validation."""
    print("=" * 60)
    print("GLM-4.7 Integration Validation")
    print("=" * 60)

    # Step 1: Load configuration
    print("\n[1/3] Loading configuration...")
    try:
        settings = Settings()
        print(f"✓ Settings loaded from config/settings.toml")
    except Exception as e:
        print(f"✗ Failed to load settings: {e}")
        sys.exit(1)

    # Step 2: Verify GLM-4.7 provider configuration
    print("\n[2/3] Verifying cc_stitch provider...")
    try:
        llm_config = LLMConfigManager(settings.llm)

        # Get cc_stitch provider
        provider_config = llm_config.get_provider("cc_stitch")

        print(f"  Provider type: {provider_config.provider}")
        print(f"  Model: {provider_config.model}")
        print(f"  Base URL: {provider_config.base_url}")
        print(f"  API Key: {'(empty)' if not provider_config.api_key else '(set)'}")
        print(f"  Timeout: {provider_config.timeout}s")

        if provider_config.provider != "openai":
            print(f"✗ Expected provider 'openai', got '{provider_config.provider}'")
            sys.exit(1)

        if provider_config.model != "glm-4.7":
            print(f"✗ Expected model 'glm-4.7', got '{provider_config.model}'")
            sys.exit(1)

        if provider_config.base_url != "http://127.0.0.1:5000/v1":
            print(
                f"✗ Expected base_url 'http://127.0.0.1:5000/v1', got '{provider_config.base_url}'"
            )
            sys.exit(1)

        print("✓ Provider configuration correct")

    except Exception as e:
        print(f"✗ Failed to verify provider config: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Step 3: Test chat completion
    print("\n[3/3] Testing chat completion...")
    try:
        chat_provider = ChatProvider(
            api_key=provider_config.api_key or "not-needed",
            base_url=provider_config.base_url,
            model=provider_config.model,
            timeout=30.0,
        )

        print("  Sending test request: '你好，请用一句话介绍你自己'")
        response = await chat_provider.chat(
            system_prompt="你是一个友好的助手。",
            user_content="你好，请用一句话介绍你自己。",
            temperature=0.7,
        )

        print(
            f"  Response: {response[:100]}..." if len(response) > 100 else f"  Response: {response}"
        )
        print("✓ Chat completion successful")

    except Exception as e:
        print(f"✗ Chat completion failed: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Success!
    print("\n" + "=" * 60)
    print("✓ All validation checks passed!")
    print("✓ GLM-4.7 integration is working correctly")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
