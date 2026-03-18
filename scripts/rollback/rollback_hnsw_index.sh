#!/bin/bash
# Copyright (c) 2026 KirkyX. All Rights Reserved
# 回滚 HNSW 索引
# 用途: 使用 Alembic downgrade 删除 HNSW 索引，恢复到之前的状态

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 默认参数
DRY_RUN=false
PROJECT_ROOT="/home/dev/projects/weaver"
ALEMBIC_DIR="${PROJECT_ROOT}/src"
BACKUP_DIR="${PROJECT_ROOT}/.rollback_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${PROJECT_ROOT}/logs/rollback_hnsw_${TIMESTAMP}.log"

# 创建备份和日志目录
mkdir -p "${BACKUP_DIR}"
mkdir -p "$(dirname ${LOG_FILE})"

# 日志函数
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1" | tee -a "${LOG_FILE}"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1" | tee -a "${LOG_FILE}"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1" | tee -a "${LOG_FILE}"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1" | tee -a "${LOG_FILE}"
}

# 使用说明
usage() {
    cat << EOF
用法: $0 [选项]

选项:
    -n, --dry-run    仅模拟执行，不实际修改数据库
    -h, --help       显示此帮助信息

示例:
    $0                  # 执行回滚
    $0 --dry-run        # 模拟执行

功能:
    1. 检查当前数据库迁移状态
    2. 备份当前迁移状态
    3. 执行 Alembic downgrade（回滚 HNSW 索引迁移）
    4. 验证索引已删除
    5. 显示回滚结果

注意:
    - 此操作需要数据库连接正常
    - 回滚将在表上持有锁，可能影响性能
    - 建议在低峰期执行
    - 确保 Alembic 迁移文件存在且正确

EOF
    exit 1
}

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            usage
            ;;
        *)
            log_error "未知参数: $1"
            usage
            ;;
    esac
done

log_info "=========================================="
log_info "开始回滚 HNSW 索引"
log_info "=========================================="
log_info "时间: $(date)"
log_info "模式: $([ "${DRY_RUN}" = true ] && echo 'DRY-RUN (模拟执行)' || echo 'LIVE (实际执行)')"
log_info ""

# 检查 Alembic 配置
if [[ ! -f "${ALEMBIC_DIR}/alembic.ini" ]]; then
    log_error "Alembic 配置文件不存在: ${ALEMBIC_DIR}/alembic.ini"
    exit 1
fi

# 检查数据库连接
log_info "检查数据库连接..."
if [[ "${DRY_RUN}" = false ]]; then
    cd "${ALEMBIC_DIR}"
    if alembic current 2>&1 | tee -a "${LOG_FILE}"; then
        log_success "数据库连接正常"
    else
        log_error "数据库连接失败"
        exit 1
    fi
else
    log_warning "[DRY-RUN] 跳过数据库连接检查"
fi

# 获取当前迁移版本
log_info "获取当前迁移版本..."
cd "${ALEMBIC_DIR}"
CURRENT_VERSION=$(alembic current 2>&1 | grep -oP 'c619ab9ba95a' || echo "")

if [[ "${CURRENT_VERSION}" == "c619ab9ba95a" ]]; then
    log_info "当前版本: c619ab9ba95a (包含 HNSW 索引迁移)"
elif [[ -z "${CURRENT_VERSION}" ]]; then
    log_warning "当前版本: 20260313 (HNSW 索引可能已回滚)"
    log_warning "请确认数据库状态"
    exit 0
else
    log_warning "当前版本: ${CURRENT_VERSION}"
    log_warning "版本不匹配，请检查迁移历史"
    exit 0
fi

# 备份当前数据库状态
log_info "备份当前迁移状态..."
BACKUP_FILE="${BACKUP_DIR}/alembic_status_${TIMESTAMP}.txt"
if [[ "${DRY_RUN}" = false ]]; then
    alembic history > "${BACKUP_FILE}" 2>&1
    alembic current >> "${BACKUP_FILE}" 2>&1
    log_success "迁移状态已备份到: ${BACKUP_FILE}"
else
    log_warning "[DRY-RUN] 跳过备份"
fi

# 确认执行
if [[ "${DRY_RUN}" = false ]]; then
    log_warning ""
    log_warning "警告: 此操作将在表上持有锁，可能影响性能"
    log_warning "建议在低峰期执行"
    log_warning ""
    read -p "$(echo -e ${RED}确认继续? [y/N]: ${NC})" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "操作已取消"
        exit 0
    fi
fi

# 执行回滚
log_info "开始执行 Alembic downgrade..."
if [[ "${DRY_RUN}" = false ]]; then
    cd "${ALEMBIC_DIR}"

    # 执行 downgrade
    if alembic downgrade -1 2>&1 | tee -a "${LOG_FILE}"; then
        log_success "Downgrade 执行成功"
    else
        log_error "Downgrade 执行失败"
        exit 1
    fi

    # 验证迁移版本
    log_info "验证迁移版本..."
    NEW_VERSION=$(alembic current 2>&1 | grep -oP '[a-f0-9]{12}' || echo "")
    if [[ "${NEW_VERSION}" == "20260313" ]]; then
        log_success "迁移版本已回滚到: 20260313"
    else
        log_warning "当前版本: ${NEW_VERSION}"
        log_warning "请手动检查迁移状态"
    fi
else
    log_warning "[DRY-RUN] 将执行: alembic downgrade -1"
fi

# 验证索引已删除
log_info "验证 HNSW 索引已删除..."
if [[ "${DRY_RUN}" = false ]]; then
    # 检查 article_vectors 表的索引
    python3 << 'PYTHON_SCRIPT'
import asyncio
import asyncpg
import os

async def check_indexes():
    # 从环境变量获取数据库连接信息
    database_url = os.getenv(
        "DATABASE_URL",
        "postgresql://postgres:postgres@localhost:5432/weaver"
    )

    conn = await asyncpg.connect(database_url)

    try:
        # 查询 article_vectors 表的索引
        indexes = await conn.fetch("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'article_vectors'
            AND indexname LIKE '%hnsw%'
        """)

        if indexes:
            print("警告: 仍然存在 HNSW 索引:")
            for idx in indexes:
                print(f"  - {idx['indexname']}")
            exit(1)
        else:
            print("验证通过: HNSW 索引已删除")

        # 查询 entity_vectors 表的索引
        indexes = await conn.fetch("""
            SELECT indexname
            FROM pg_indexes
            WHERE tablename = 'entity_vectors'
            AND indexname LIKE '%hnsw%'
        """)

        if indexes:
            print("警告: 仍然存在 HNSW 索引:")
            for idx in indexes:
                print(f"  - {idx['indexname']}")
            exit(1)
        else:
            print("验证通过: entity_vectors 表的 HNSW 索引已删除")

    finally:
        await conn.close()

asyncio.run(check_indexes())
PYTHON_SCRIPT

    if [[ $? -eq 0 ]]; then
        log_success "索引验证完成"
    else
        log_error "索引验证失败，请检查数据库"
        exit 1
    fi
else
    log_warning "[DRY-RUN] 跳过索引验证"
fi

# 显示结果
log_info "=========================================="
log_info "回滚完成"
log_info "=========================================="
if [[ "${DRY_RUN}" = false ]]; then
    log_info "备份文件: ${BACKUP_FILE}"
    log_info "日志文件: ${LOG_FILE}"
    log_success "HNSW 索引已成功回滚"

    log_warning ""
    log_warning "后续步骤:"
    log_warning "  1. 验证应用功能正常"
    log_warning "  2. 监控查询性能（回滚后可能变慢）"
    log_warning "  3. 如需恢复，执行: alembic upgrade head"
    log_warning "  4. 检查相关测试是否通过"
else
    log_info "[DRY-RUN] 模拟完成，未实际修改数据库"
fi