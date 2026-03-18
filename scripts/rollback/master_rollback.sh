#!/bin/bash
# Copyright (c) 2026 KirkyX. All Rights Reserved
# 主回滚脚本 - 协调所有回滚操作
# 用途: 提供统一的回滚入口，按顺序执行所有回滚操作

set -euo pipefail

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 默认参数
DRY_RUN=false
PROJECT_ROOT="/home/dev/projects/weaver"
ROLLBACK_DIR="${PROJECT_ROOT}/scripts/rollback"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_DIR="${PROJECT_ROOT}/logs"
LOG_FILE="${LOG_DIR}/master_rollback_${TIMESTAMP}.log"

# 回滚组件状态
HEALTH_ENDPOINT_ROLLED_BACK=false
SAGA_PATTERN_ROLLED_BACK=false
HNSW_INDEX_ROLLED_BACK=false

# 创建日志目录
mkdir -p "${LOG_DIR}"

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

log_step() {
    echo -e "${CYAN}[STEP]${NC} $1" | tee -a "${LOG_FILE}"
}

# 使用说明
usage() {
    cat << EOF
用法: $0 [选项]

选项:
    -n, --dry-run         仅模拟执行，不实际修改
    -c, --component       指定回滚组件 (health|saga|hnsw|all)
                          可多次使用，如: -c health -c saga
    -h, --help            显示此帮助信息

示例:
    $0                           # 回滚所有组件
    $0 --dry-run                 # 模拟回滚所有组件
    $0 -c health -c saga         # 仅回滚健康检查和 Saga 模式
    $0 -c hnsw --dry-run         # 模拟回滚 HNSW 索引

功能:
    按顺序执行以下回滚操作:
    1. 回滚健康检查端点 (可选)
    2. 回滚 Saga 模式 (可选)
    3. 回滚 HNSW 索引 (可选)

    每个组件都会:
    - 创建备份
    - 执行回滚
    - 验证结果
    - 记录详细日志

EOF
    exit 1
}

# 解析参数
COMPONENTS=()
while [[ $# -gt 0 ]]; do
    case $1 in
        -n|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -c|--component)
            shift
            if [[ -z "$1" ]]; then
                log_error "组件名称不能为空"
                usage
            fi
            COMPONENTS+=("$1")
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

# 默认回滚所有组件
if [[ ${#COMPONENTS[@]} -eq 0 ]]; then
    COMPONENTS=("health" "saga" "hnsw")
fi

# 验证组件名称
VALID_COMPONENTS=("health" "saga" "hnsw" "all")
for comp in "${COMPONENTS[@]}"; do
    if [[ ! " ${VALID_COMPONENTS[*]} " =~ " ${comp} " ]]; then
        log_error "无效的组件: ${comp}"
        log_info "有效组件: health, saga, hnsw, all"
        exit 1
    fi
done

# 如果包含 "all"，则回滚所有组件
if [[ " ${COMPONENTS[*]} " =~ " all " ]]; then
    COMPONENTS=("health" "saga" "hnsw")
fi

# 去重
IFS=' ' read -r -a COMPONENTS <<< "$(echo "${COMPONENTS[@]}" | tr ' ' '\n' | sort -u | tr '\n' ' ')"

log_info "=========================================="
log_info "Weaver 主回滚脚本"
log_info "=========================================="
log_info "时间: $(date)"
log_info "模式: $([ "${DRY_RUN}" = true ] && echo 'DRY-RUN (模拟执行)' || echo 'LIVE (实际执行)')"
log_info "组件: ${COMPONENTS[*]}"
log_info "日志: ${LOG_FILE}"
log_info ""

# 检查回滚脚本是否存在
log_info "检查回滚脚本..."
for comp in "${COMPONENTS[@]}"; do
    script_name="rollback_${comp//health/health_endpoint}.sh"
    case $comp in
        health)
            script_name="rollback_health_endpoint.sh"
            ;;
        saga)
            script_name="rollback_saga_pattern.sh"
            ;;
        hnsw)
            script_name="rollback_hnsw_index.sh"
            ;;
    esac

    script_path="${ROLLBACK_DIR}/${script_name}"
    if [[ ! -f "${script_path}" ]]; then
        log_error "回滚脚本不存在: ${script_path}"
        exit 1
    fi
    log_info "  ✓ ${script_name}"
done
log_success "所有回滚脚本就绪"
log_info ""

# 确认执行
if [[ "${DRY_RUN}" = false ]]; then
    log_warning "警告: 此操作将修改以下组件:"
    for comp in "${COMPONENTS[@]}"; do
        case $comp in
            health)
                log_warning "  - 健康检查端点: 注释 /health 端点定义"
                ;;
            saga)
                log_warning "  - Saga 模式: 注释 persist_batch_saga() 方法"
                ;;
            hnsw)
                log_warning "  - HNSW 索引: 删除向量表索引"
                ;;
        esac
    done
    log_warning ""
    log_warning "建议:"
    log_warning "  1. 先在测试环境验证"
    log_warning "  2. 在低峰期执行"
    log_warning "  3. 确保已备份重要数据"
    log_warning ""
    read -p "$(echo -e ${RED}确认继续? [y/N]: ${NC})" -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        log_info "操作已取消"
        exit 0
    fi
fi

# 执行回滚
TOTAL=${#COMPONENTS[@]}
CURRENT=0

for comp in "${COMPONENTS[@]}"; do
    CURRENT=$((CURRENT + 1))
    log_step "=========================================="
    log_step "步骤 ${CURRENT}/${TOTAL}: 回滚 ${comp}"
    log_step "=========================================="

    script_name=""
    case $comp in
        health)
            script_name="rollback_health_endpoint.sh"
            ;;
        saga)
            script_name="rollback_saga_pattern.sh"
            ;;
        hnsw)
            script_name="rollback_hnsw_index.sh"
            ;;
    esac

    script_path="${ROLLBACK_DIR}/${script_name}"

    if [[ "${DRY_RUN}" = true ]]; then
        cmd="bash ${script_path} --dry-run"
    else
        cmd="bash ${script_path}"
    fi

    log_info "执行: ${cmd}"

    if ${cmd} 2>&1 | tee -a "${LOG_FILE}"; then
        log_success "组件 ${comp} 回滚成功"
        case $comp in
            health)
                HEALTH_ENDPOINT_ROLLED_BACK=true
                ;;
            saga)
                SAGA_PATTERN_ROLLED_BACK=true
                ;;
            hnsw)
                HNSW_INDEX_ROLLED_BACK=true
                ;;
        esac
    else
        log_error "组件 ${comp} 回滚失败"
        log_error "停止后续操作"
        exit 1
    fi

    log_info ""
done

# 汇总结果
log_info "=========================================="
log_info "回滚汇总"
log_info "=========================================="

if [[ "${DRY_RUN}" = true ]]; then
    log_info "[DRY-RUN] 模拟执行完成"
    log_info "未实际修改任何文件或数据库"
else
    log_info "回滚状态:"
    if [[ " ${COMPONENTS[*]} " =~ " health " ]]; then
        if [[ "${HEALTH_ENDPOINT_ROLLED_BACK}" = true ]]; then
            log_success "  ✓ 健康检查端点"
        else
            log_error "  ✗ 健康检查端点"
        fi
    fi

    if [[ " ${COMPONENTS[*]} " =~ " saga " ]]; then
        if [[ "${SAGA_PATTERN_ROLLED_BACK}" = true ]]; then
            log_success "  ✓ Saga 模式"
        else
            log_error "  ✗ Saga 模式"
        fi
    fi

    if [[ " ${COMPONENTS[*]} " =~ " hnsw " ]]; then
        if [[ "${HNSW_INDEX_ROLLED_BACK}" = true ]]; then
            log_success "  ✓ HNSW 索引"
        else
            log_error "  ✗ HNSW 索引"
        fi
    fi
fi

log_info ""
log_info "日志文件: ${LOG_FILE}"
log_info ""

# 后续步骤
if [[ "${DRY_RUN}" = false ]]; then
    log_warning "后续步骤:"
    log_warning "  1. 验证应用启动正常"
    log_warning "  2. 运行测试套件: pytest tests/"
    log_warning "  3. 检查应用日志: tail -f ${LOG_DIR}/app.log"
    log_warning "  4. 监控系统性能"
    log_warning "  5. 如需恢复，查看备份目录: ${PROJECT_ROOT}/.rollback_backups/"
fi

log_success "主回滚脚本执行完成"