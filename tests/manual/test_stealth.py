# Copyright (c) 2026 KirkyX. All Rights Reserved
"""Test script to verify playwright-stealth anti-detection functionality."""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from modules.fetcher.playwright_pool import PlaywrightContextPool


async def test_stealth():
    """Test stealth functionality on bot detection websites."""
    print("=" * 60)
    print("Playwright-Stealth 反检测功能测试")
    print("=" * 60)

    pool = PlaywrightContextPool(
        pool_size=1,
        stealth_enabled=True,
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport_width=1920,
        viewport_height=1080,
        locale="zh-CN",
        timezone="Asia/Shanghai",
        random_delay_min=0.1,
        random_delay_max=0.3,
    )

    print("\n[1/4] 启动浏览器池...")
    await pool.startup()
    print(f"     ✅ 浏览器池已启动 (stealth_enabled={pool._stealth_enabled})")

    test_sites = [
        {
            "name": "Sannysoft Bot Detection",
            "url": "https://bot.sannysoft.com/",
            "check": "检查 navigator.webdriver 是否被隐藏",
        },
        {
            "name": "Are You Headless",
            "url": "https://arh.antoinevastel.com/bots/areyouheadless",
            "check": "检查是否被识别为 headless 浏览器",
        },
        {
            "name": "Intoli Chrome Headless Test",
            "url": (
                "https://intoli.com/blog/not-possible-to-block-chrome-headless/chrome-headless-test.html"
            ),
            "check": "检查 Chrome headless 检测绕过",
        },
    ]

    async with pool.acquire() as ctx:
        page = await ctx.new_page()
        try:
            for i, site in enumerate(test_sites, 1):
                print(f"\n[{i + 1}/4] 测试: {site['name']}")
                print(f"     URL: {site['url']}")
                print(f"     检查: {site['check']}")

                try:
                    response = await page.goto(
                        site["url"], timeout=30000, wait_until="domcontentloaded"
                    )
                    await asyncio.sleep(2)

                    if response and response.status == 200:
                        print(f"     ✅ 页面加载成功 (状态码: {response.status})")

                        title = await page.title()
                        print(f"     页面标题: {title}")
                    else:
                        print(
                            f"     ⚠️ 页面加载异常 (状态码: {response.status if response else 'N/A'})"
                        )
                except Exception as e:
                    print(f"     ❌ 访问失败: {e}")

            print("\n[4/4] 检查 navigator.webdriver 属性...")
            webdriver_value = await page.evaluate("navigator.webdriver")
            print(f"     navigator.webdriver = {webdriver_value}")

            if webdriver_value is None or not webdriver_value:
                print("     ✅ webdriver 属性已被隐藏")
            else:
                print("     ⚠️ webdriver 属性仍可见")

            plugins_count = await page.evaluate("navigator.plugins.length")
            languages = await page.evaluate("navigator.languages")
            print(f"\n     navigator.plugins.length = {plugins_count}")
            print(f"     navigator.languages = {languages}")

            if plugins_count > 0:
                print("     ✅ 插件列表已模拟")
            else:
                print("     ⚠️ 插件列表为空")

        finally:
            await page.close()

    print("\n" + "=" * 60)
    print("关闭浏览器池...")
    await pool.shutdown()
    print("测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_stealth())
