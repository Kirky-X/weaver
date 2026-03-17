#!/usr/bin/env python3
"""Nuitka Build Script - 极致性能优化的生产构建"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.resolve()
SRC_DIR = PROJECT_ROOT / "src"
DIST_DIR = PROJECT_ROOT / "dist"
BUILD_DIR = PROJECT_ROOT / "build"


def get_cpu_cores() -> int:
    """获取CPU核心数用于并行编译"""
    return os.cpu_count() or 4


def clean_build_dirs() -> None:
    """清理旧的构建目录"""
    for dir_path in [DIST_DIR, BUILD_DIR]:
        if dir_path.exists():
            shutil.rmtree(dir_path)
            print(f"已清理: {dir_path}")


def check_nuitka() -> None:
    """检查 Nuitka 是否已安装"""
    try:
        result = subprocess.run(
            ["nuitka", "--version"],
            capture_output=True,
            text=True,
            check=True,
        )
        print(f"Nuitka 版本: {result.stdout.strip()}")
    except FileNotFoundError:
        print("错误: Nuitka 未安装")
        print("请运行: pip install nuitka")
        sys.exit(1)
    except subprocess.CalledProcessError:
        print("错误: 无法获取 Nuitka 版本")
        sys.exit(1)


def get_module_name() -> str:
    """获取主模块名称"""
    return "main"


def build_command() -> list[str]:
    """构建 Nuitka 编译命令"""
    main_module = SRC_DIR / "main.py"

    if not main_module.exists():
        print(f"错误: 找不到主模块 {main_module}")
        sys.exit(1)

    cpu_cores = get_cpu_cores()

    cmd = [
        "python",
        "-m",
        "nuitka",
        "--standalone",
        "--onefile",
        f"--jobs={cpu_cores}",
        f"--output-dir={DIST_DIR}",
        f"--include-source-dir={SRC_DIR}",
        "--python-flag=no_site",
        "--python-flag=no_asserts",
        "--python-flag=no_warnings",
        "--remove-output",
        "--no-pyi-file",
        f"--main={main_module}",
        "--company-name=Weaver",
        "--product-name=weaver",
        "--file-version=0.1.0",
        "--product-version=0.1.0",
        "--linux-onefile-icon=None",
        "--macos-onefile-icon=None",
        "--windows-onefile-icon=None",
    ]

    cmd.extend([
        "--lto=yes",
        "--clang",
        "--prefer-chrome-driver=yes",
    ])

    hidden_imports = [
        "asyncio",
        "aiosignal",
        "frozenlist",
        "multipart",
        "yaml",
        "httpx",
        "httpcore",
        "h11",
        "starlette",
        "fastapi",
        "uvicorn",
        "uvicorn.loops",
        "uvicorn.loops.auto",
        "uvicorn.protocols",
        "uvicorn.protocols.http",
        "uvicorn.protocols.http.auto",
        "uvicorn.protocols.websockets",
        "uvicorn.protocols.websockets.auto",
        "uvicorn.lifespan",
        "uvicorn.lifespan.on",
        "uvicorn.logging",
        "uvicorn.middleware",
        "uvicorn.middleware.proxy_headers",
        "slowapi",
        "slowapi.util",
        "slowapi.extension",
        "slowapi.errors",
        "redis",
        "redis.asyncio",
        "redis.asyncio.client",
        "redis.asyncio.connection",
        "asyncpg",
        "sqlalchemy",
        "sqlalchemy.ext.asyncio",
        "sqlalchemy.pool",
        "sqlalchemy.dialects.postgresql",
        "sqlalchemy.dialects.postgresql.asyncpg",
        "psycopg2",
        "psycopg2.extensions",
        "alembic",
        "alembic.config",
        "alembic.runtime.environment",
        "alembic.runtime.environment.process",
        "alembic.script",
        "neo4j",
        "neo4j.async_driver",
        "neo4j._async",
        "langchain",
        "langchain.agents",
        "langchain.chains",
        "langchain.chat_models",
        "langchain.llms",
        "langchain.schema",
        "langchain_core",
        "langchain_core.messages",
        "langchain_core.outputs",
        "langgraph",
        "langgraph.graph",
        "langgraph.pregel",
        "langgraph.checkpoint",
        "langgraph.checkpoint.base",
        "langgraph.checkpoint.memory",
        "openai",
        "tiktoken",
        "tiktoken_ext",
        "tiktoken_ext.openai_public",
        "numpy",
        "numpy.core",
        "numpy.core._multiarray_umath",
        "spacy",
        "spacy.lang.en",
        "spacy.lang.zh",
        "spacy.util",
        "feedparser",
        "feedparser.util",
        "trafilatura",
        "trafilatura.core",
        "playwright",
        "playwright._impl._api_types",
        "playwright._impl._driver",
        "playwright._impl._helper",
        "playwright.async_api",
        "bs4",
        "beautifulsoup4",
        "lxml",
        "lxml.etree",
        "lxml.html",
        "pydantic",
        "pydantic.fields",
        "pydantic.main",
        "pydantic_settings",
        "pydantic_settings.main",
        "prometheus_client",
        "prometheus_client.metrics",
        "prometheus_client.metrics_counter",
        "prometheus_client.metrics_gauge",
        "prometheus_client.metrics_histogram",
        "opentelemetry",
        "opentelemetry.sdk",
        "opentelemetry.sdk.trace",
        "opentelemetry.sdk.resources",
        "opentelemetry.instrumentation",
        "opentelemetry.instrumentation.fastapi",
        "opentelemetry.trace",
        "opentelemetry.sdk.trace.export",
        "apscheduler",
        "apscheduler.schedulers.asyncio",
        "apscheduler.triggers.interval",
        "apscheduler.triggers.cron",
        "dependency_injector",
        "dependency_injector.ext",
        "loguru",
        "loguru._defaults",
        "pgvector",
        "langchain_community",
        "langchain_community.embeddings",
        "langchain_community.vectorstores",
        "langchain_openai",
        "httpx",
        "httpcore",
        "httpcore._sync",
        "httpcore._async",
        "charset_normalizer",
        "certifi",
        "idna",
        "urllib3",
        "requests",
        "requests.adapters",
        "pypdf",
        "pypdf._utils",
        "markdown",
        "markdown.core",
        "anyio",
        "anyio._backends",
        "anyio._backends._asyncio",
        "propcache",
        "brotli",
        "sniffio",
        "cryptography",
        "cryptography.hazmat",
        "cryptography.hazmat.bindings",
        "websockets",
        "websockets.asyncio",
        "websockets.client",
        "websockets.server",
    ]

    for imp in hidden_imports:
        cmd.append(f"--include-module={imp}")

    data_files = [
        ("config", "config"),
    ]

    for src, dst in data_files:
        src_path = PROJECT_ROOT / src
        if src_path.exists():
            cmd.append(f"--include-data-dir={src_path}={dst}")
            print(f"包含数据目录: {src} -> {dst}")

    return cmd


def run_build() -> None:
    """执行编译"""
    print("\n" + "=" * 60)
    print("Nuitka 编译开始 - 极致性能优化模式")
    print("=" * 60)

    check_nuitka()
    clean_build_dirs()

    cmd = build_command()
    print(f"\n编译命令: {' '.join(cmd)}\n")

    try:
        result = subprocess.run(
            cmd,
            cwd=str(PROJECT_ROOT),
            check=True,
        )
        print("\n" + "=" * 60)
        print("编译成功!")
        print("=" * 60)
    except subprocess.CalledProcessError as e:
        print(f"\n编译失败，退出码: {e.returncode}")
        sys.exit(e.returncode)


def verify_output() -> None:
    """验证编译输出"""
    dist_files = list(DIST_DIR.glob("weaver*"))

    if not dist_files:
        print("错误: 编译输出目录为空")
        sys.exit(1)

    for f in dist_files:
        size_mb = f.stat().st_size / (1024 * 1024)
        print(f"输出文件: {f.name} ({size_mb:.2f} MB)")


def print_usage() -> None:
    """打印使用说明"""
    print("\n" + "=" * 60)
    print("使用方法")
    print("=" * 60)
    print(f"编译输出: {DIST_DIR}")
    print("\n运行方式:")
    print("  ./dist/weaver")
    print("\n或指定参数:")
    print("  ./dist/weaver --host 0.0.0.0 --port 8000")
    print("=" * 60)


def main() -> None:
    """主函数"""
    print("Nuitka Build Script for Weaver")
    print(f"项目目录: {PROJECT_ROOT}")
    print(f"源代码目录: {SRC_DIR}")

    run_build()
    verify_output()
    print_usage()


if __name__ == "__main__":
    main()
