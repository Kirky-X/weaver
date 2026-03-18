#!/bin/bash
# Copyright (c) 2026 KirkyX. All Rights Reserved
# 回滚健康检查端点
# 用途: 注释 main.py 中的健康检查端点定义，恢复到添加健康检查之前的状态

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
MAIN_FILE="${PROJECT_ROOT}/src/main.py"
BACKUP_DIR="${PROJECT_ROOT}/.rollback_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${PROJECT_ROOT}/logs/rollback_health_${TIMESTAMP}.log"

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
    -n, --dry-run    仅模拟执行，不实际修改文件
    -h, --help       显示此帮助信息

示例:
    $0                  # 执行回滚
    $0 --dry-run        # 模拟执行

功能:
    1. 备份 main.py 文件
    2. 注释健康检查端点定义（第 368-374 行）
    3. 注释健康检查导入（第 26-34 行）
    4. 验证语法正确性
    5. 显示回滚结果

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
log_info "开始回滚健康检查端点"
log_info "=========================================="
log_info "时间: $(date)"
log_info "模式: $([ "${DRY_RUN}" = true ] && echo 'DRY-RUN (模拟执行)' || echo 'LIVE (实际执行)')"
log_info ""

# 验证文件存在
if [[ ! -f "${MAIN_FILE}" ]]; then
    log_error "文件不存在: ${MAIN_FILE}"
    exit 1
fi

# 备份原文件
BACKUP_FILE="${BACKUP_DIR}/main.py.backup_${TIMESTAMP}"
log_info "创建备份: ${BACKUP_FILE}"
if [[ "${DRY_RUN}" = false ]]; then
    cp "${MAIN_FILE}" "${BACKUP_FILE}"
    log_success "备份完成"
else
    log_warning "[DRY-RUN] 跳过备份"
fi

# 检查健康检查端点是否存在
if grep -q "@app.get(\"/health\")" "${MAIN_FILE}"; then
    log_info "检测到健康检查端点定义"
else
    log_warning "未找到健康检查端点定义，可能已经回滚"
    exit 0
fi

# 执行回滚
log_info "开始注释健康检查端点..."

if [[ "${DRY_RUN}" = false ]]; then
    # 使用 sed 注释端点定义 (第 368-374 行)
    log_info "注释端点定义 (行 368-374)"
    sed -i '368,374s/^/# /' "${MAIN_FILE}"

    # 注释健康检查相关导入 (第 26-34 行)
    log_info "注释导入语句 (行 26-34)"
    sed -i '26,34s/^/# /' "${MAIN_FILE}"

    log_success "端点已注释"
else
    log_warning "[DRY-RUN] 将注释以下内容:"
    log_warning "  - 第 26-34 行: 健康检查导入"
    log_warning "  - 第 368-374 行: 健康检查端点定义"
fi

# 验证语法
log_info "验证 Python 语法..."
if [[ "${DRY_RUN}" = false ]]; then
    if python3 -m py_compile "${MAIN_FILE}" 2>&1 | tee -a "${LOG_FILE}"; then
        log_success "语法验证通过"
    else
        log_error "语法验证失败，恢复备份"
        cp "${BACKUP_FILE}" "${MAIN_FILE}"
        exit 1
    fi
else
    log_warning "[DRY-RUN] 跳过语法验证"
fi

# 显示结果
log_info "=========================================="
log_info "回滚完成"
log_info "=========================================="
if [[ "${DRY_RUN}" = false ]]; then
    log_info "备份文件: ${BACKUP_FILE}"
    log_info "日志文件: ${LOG_FILE}"
    log_success "健康检查端点已成功回滚"

    log_warning ""
    log_warning "后续步骤:"
    log_warning "  1. 验证应用启动正常: python -m src.main"
    log_warning "  2. 确认 /health 端点已移除"
    log_warning "  3. 如需恢复，使用备份文件: ${BACKUP_FILE}"
else
    log_info "[DRY-RUN] 模拟完成，未实际修改文件"
fi