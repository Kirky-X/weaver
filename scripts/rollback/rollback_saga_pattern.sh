#!/bin/bash
# Copyright (c) 2026 KirkyX. All Rights Reserved
# 回滚 Saga 模式
# 用途: 注释 batch_merger.py 中的 persist_batch_saga() 方法，恢复到简单的持久化逻辑

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
BATCH_MERGER_FILE="${PROJECT_ROOT}/src/modules/pipeline/nodes/batch_merger.py"
BACKUP_DIR="${PROJECT_ROOT}/.rollback_backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="${PROJECT_ROOT}/logs/rollback_saga_${TIMESTAMP}.log"

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
    1. 备份 batch_merger.py 文件
    2. 注释 persist_batch_saga() 方法（第 261-453 行）
    3. 验证语法正确性
    4. 显示回滚结果

注意:
    - 此操作将移除 Saga 模式的跨数据库原子性保证
    - 回滚后，需要修改调用 persist_batch_saga() 的代码
    - 建议在测试环境验证后再在生产环境执行

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
log_info "开始回滚 Saga 模式"
log_info "=========================================="
log_info "时间: $(date)"
log_info "模式: $([ "${DRY_RUN}" = true ] && echo 'DRY-RUN (模拟执行)' || echo 'LIVE (实际执行)')"
log_info ""

# 验证文件存在
if [[ ! -f "${BATCH_MERGER_FILE}" ]]; then
    log_error "文件不存在: ${BATCH_MERGER_FILE}"
    exit 1
fi

# 备份原文件
BACKUP_FILE="${BACKUP_DIR}/batch_merger.py.backup_${TIMESTAMP}"
log_info "创建备份: ${BACKUP_FILE}"
if [[ "${DRY_RUN}" = false ]]; then
    cp "${BATCH_MERGER_FILE}" "${BACKUP_FILE}"
    log_success "备份完成"
else
    log_warning "[DRY-RUN] 跳过备份"
fi

# 检查 Saga 方法是否存在
if grep -q "async def persist_batch_saga" "${BATCH_MERGER_FILE}"; then
    log_info "检测到 persist_batch_saga() 方法"
else
    log_warning "未找到 persist_batch_saga() 方法，可能已经回滚"
    exit 0
fi

# 确认执行
if [[ "${DRY_RUN}" = false ]]; then
    log_warning ""
    log_warning "警告: 此操作将移除 Saga 模式的跨数据库原子性保证"
    log_warning "建议在测试环境验证后再在生产环境执行"
    log_warning ""
    read -p "$(echo -e ${RED}确认继续? [y/N]: ${NC})" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "操作已取消"
        exit 0
    fi
fi

# 执行回滚
log_info "开始注释 persist_batch_saga() 方法..."

if [[ "${DRY_RUN}" = false ]]; then
    # 使用 sed 注释方法定义 (第 261-453 行)
    log_info "注释方法定义 (行 261-453)"

    # 使用 Python 脚本进行更精确的注释
    python3 << 'PYTHON_SCRIPT'
import sys

file_path = "/home/dev/projects/weaver/src/modules/pipeline/nodes/batch_merger.py"

with open(file_path, 'r') as f:
    lines = f.readlines()

# 找到 persist_batch_saga 方法的开始和结束
start_line = None
end_line = None
indent_level = None

for i, line in enumerate(lines):
    if 'async def persist_batch_saga(' in line:
        start_line = i
        # 获取方法的缩进级别
        indent_level = len(line) - len(line.lstrip())
        continue

    if start_line is not None and line.strip() and not line.strip().startswith('#'):
        # 检查是否是同级或更高级的新定义
        current_indent = len(line) - len(line.lstrip())
        if current_indent <= indent_level and (line.strip().startswith('def ') or line.strip().startswith('async def ')):
            end_line = i
            break

# 如果没有找到结束，则到文件末尾
if start_line is not None and end_line is None:
    end_line = len(lines)

# 注释方法
if start_line is not None:
    for i in range(start_line, end_line):
        if lines[i].strip():  # 只注释非空行
            lines[i] = '    # [ROLLBACK] ' + lines[i].lstrip()

    with open(file_path, 'w') as f:
        f.writelines(lines)

    print(f"已注释方法: 行 {start_line + 1} 到 {end_line}")
else:
    print("错误: 未找到方法", file=sys.stderr)
    sys.exit(1)
PYTHON_SCRIPT

    if [[ $? -eq 0 ]]; then
        log_success "方法已注释"
    else
        log_error "注释失败，恢复备份"
        cp "${BACKUP_FILE}" "${BATCH_MERGER_FILE}"
        exit 1
    fi
else
    log_warning "[DRY-RUN] 将注释:"
    log_warning "  - persist_batch_saga() 方法完整定义"
fi

# 验证语法
log_info "验证 Python 语法..."
if [[ "${DRY_RUN}" = false ]]; then
    if python3 -m py_compile "${BATCH_MERGER_FILE}" 2>&1 | tee -a "${LOG_FILE}"; then
        log_success "语法验证通过"
    else
        log_error "语法验证失败，恢复备份"
        cp "${BACKUP_FILE}" "${BATCH_MERGER_FILE}"
        exit 1
    fi
else
    log_warning "[DRY-RUN] 跳过语法验证"
fi

# 检查是否有代码调用了 persist_batch_saga
log_info "检查调用代码..."
if grep -r "persist_batch_saga" "${PROJECT_ROOT}/src" --include="*.py" 2>/dev/null | grep -v "batch_merger.py"; then
    log_warning "发现其他文件调用了 persist_batch_saga()，需要手动修改调用代码"
else
    log_success "未发现其他调用代码"
fi

# 显示结果
log_info "=========================================="
log_info "回滚完成"
log_info "=========================================="
if [[ "${DRY_RUN}" = false ]]; then
    log_info "备份文件: ${BACKUP_FILE}"
    log_info "日志文件: ${LOG_FILE}"
    log_success "Saga 模式已成功回滚"

    log_warning ""
    log_warning "后续步骤:"
    log_warning "  1. 检查并修改所有调用 persist_batch_saga() 的代码"
    log_warning "  2. 实现替代的持久化逻辑（如果需要）"
    log_warning "  3. 运行测试验证功能正常"
    log_warning "  4. 如需恢复，使用备份文件: ${BACKUP_FILE}"
else
    log_info "[DRY-RUN] 模拟完成，未实际修改文件"
fi