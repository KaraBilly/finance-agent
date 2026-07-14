#!/usr/bin/env bash

# setup_all.sh — 一键脚本：下载全部数据 + 启动 Milvus + 导入到向量库
#
# 用途:
#   一条命令完成从零到 Milvus 中全部数据就绪:
#     1) 下载 A 股股票日线 / 周线行情 (data/market/stocks/)
#     2) 下载财报 PDF / HTML       (data/financials/downloads/)
#     3) 启动 Milvus (docker compose)
#     4) 等待 Milvus 健康检查通过
#     5) 将全部本地数据分块 + 向量化 + 灌入 Milvus (--recreate)
#
# 使用:
#   ./setup_all.sh                    # 全流程 (若 Milvus 已有数据会交互确认)
#   ./setup_all.sh --skip-download    # 跳过下载, 只做 Milvus 启动 + 导入
#   ./setup_all.sh --skip-milvus      # 只下载数据, 不启动 Milvus / 不导入
#   ./setup_all.sh --skip-import      # 下载 + 启动 Milvus, 但不导入
#   ./setup_all.sh --recreate --yes   # 已有数据 → 直接丢弃并重建 (CI 用)
#   ./setup_all.sh --append           # 已有数据 → 追加插入 (会产生重复, 慎用)
#   ./setup_all.sh --skip-if-exists   # 已有数据 → 跳过导入, 保留旧数据

set -euo pipefail

# --- 定位到项目根目录 (脚本所在目录) ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 参数解析 ---
SKIP_DOWNLOAD=0
SKIP_MILVUS=0
SKIP_IMPORT=0
# EXIST_STRATEGY: prompt (默认) | recreate | append | skip
EXIST_STRATEGY="prompt"
ASSUME_YES=0

for arg in "$@"; do
    case "$arg" in
        --skip-download)    SKIP_DOWNLOAD=1 ;;
        --skip-milvus)      SKIP_MILVUS=1 ;;
        --skip-import)      SKIP_IMPORT=1 ;;
        --recreate)         EXIST_STRATEGY="recreate" ;;
        --append|--no-recreate) EXIST_STRATEGY="append" ;;
        --skip-if-exists)   EXIST_STRATEGY="skip" ;;
        --yes|-y)           ASSUME_YES=1 ;;
        -h|--help)
            grep '^#' "$0" | sed 's/^# \{0,1\}//'
            exit 0
            ;;
        *)
            echo "未知参数: $arg (使用 --help 查看用法)" >&2
            exit 2
            ;;
    esac
done

# --- 选择 python 解释器 (优先当前激活的 venv) ---
if [[ -n "${VIRTUAL_ENV:-}" ]] && [[ -x "${VIRTUAL_ENV}/bin/python" ]]; then
    PY="${VIRTUAL_ENV}/bin/python"
elif [[ -x "${SCRIPT_DIR}/.venv/bin/python" ]]; then
    PY="${SCRIPT_DIR}/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY="$(command -v python3)"
else
    PY="python"
fi

# --- docker compose v1/v2 兼容 ---
if docker compose version >/dev/null 2>&1; then
    DC="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    DC="docker-compose"
else
    DC=""
fi

banner() {
    echo ""
    echo "========================================"
    echo "$1"
    echo "========================================"
}

# ============================================================
# 步骤 1: 下载股票行情 + 财报
# ============================================================
if [[ "$SKIP_DOWNLOAD" -eq 0 ]]; then
    banner "[1/3] 下载数据"

    echo ">>> 下载 A 股日线 / 周线行情 (20 年)..."
    "$PY" -m scripts.download_stock_market_data

    echo ""
    echo ">>> 下载财报 (比亚迪 / 寒武纪 / 中际旭创 / 宁德时代)..."
    "$PY" scripts/download_financial_reports.py
else
    banner "[1/3] 跳过下载 (--skip-download)"
fi

# ============================================================
# 步骤 2: 启动 Milvus
# ============================================================
if [[ "$SKIP_MILVUS" -eq 0 ]]; then
    banner "[2/3] 启动 Milvus"

    if ! docker info >/dev/null 2>&1; then
        echo "错误: Docker 未运行, 请先启动 Docker Desktop." >&2
        exit 1
    fi
    if [[ -z "$DC" ]]; then
        echo "错误: 未找到 docker compose / docker-compose." >&2
        exit 1
    fi

    echo ">>> 启动容器 (etcd + minio + milvus)..."
    $DC -f docker-compose.milvus.yml up -d

    echo ">>> 等待 Milvus 健康检查 (最多 120s)..."
    ready=0
    for i in $(seq 1 60); do
        if curl -fsS http://localhost:9091/healthz >/dev/null 2>&1; then
            ready=1
            echo ""
            echo "  Milvus 已就绪!"
            break
        fi
        printf "."
        sleep 2
    done
    if [[ "$ready" -ne 1 ]]; then
        echo ""
        echo "错误: Milvus 在 120s 内未就绪, 请检查 'docker logs milvus-standalone'." >&2
        exit 1
    fi
else
    banner "[2/3] 跳过启动 Milvus (--skip-milvus)"
fi

# ============================================================
# 步骤 3: 灌入数据到 Milvus
# ============================================================
if [[ "$SKIP_IMPORT" -eq 0 && "$SKIP_MILVUS" -eq 0 ]]; then
    banner "[3/3] 导入数据到 Milvus"

    # ---- 3a. 探测 collection 现状 (存在? 多少行?) ----
    HOST="${FA_MILVUS_HOST:-localhost}"
    PORT="${FA_MILVUS_PORT:-19530}"
    COLL="${FA_MILVUS_COLLECTION:-finance_docs}"

    echo ">>> 探测 collection '${COLL}' @ ${HOST}:${PORT} ..."
    # 返回值: "missing" | "empty" | "<row_count>"
    EXISTING_ROWS="$(
        "$PY" - <<PYEOF
import os, sys
try:
    from pymilvus import connections, utility, Collection
    connections.connect(alias="probe", host="${HOST}", port="${PORT}")
    if not utility.has_collection("${COLL}", using="probe"):
        print("missing"); sys.exit(0)
    c = Collection("${COLL}", using="probe")
    c.flush()
    n = c.num_entities
    print(n if n > 0 else "empty")
except Exception as e:
    # 无 pymilvus 或连不上 → 走原始 --recreate 逻辑, 不阻断
    print("missing", file=sys.stdout)
    print(f"[warn] probe failed: {e}", file=sys.stderr)
PYEOF
    )"

    # ---- 3b. 根据策略决定 --recreate / 追加 / 跳过 ----
    RECREATE_FLAG=""
    DO_IMPORT=1
    case "$EXISTING_ROWS" in
        missing|empty)
            echo "  当前状态: 无数据 → 全量导入"
            RECREATE_FLAG="--recreate"   # 空表也 recreate, 保证 schema 一致
            ;;
        *)
            echo "  当前状态: 已有 ${EXISTING_ROWS} 行"
            case "$EXIST_STRATEGY" in
                recreate)
                    echo "  策略: --recreate → 丢弃后重建"
                    RECREATE_FLAG="--recreate"
                    ;;
                append)
                    echo "  策略: --append → 追加 (⚠️  会与已有数据形成重复)"
                    RECREATE_FLAG=""
                    ;;
                skip)
                    echo "  策略: --skip-if-exists → 跳过导入, 保留旧数据"
                    DO_IMPORT=0
                    ;;
                prompt)
                    if [[ "$ASSUME_YES" -eq 1 ]]; then
                        echo "  --yes 未指定明确策略 → 默认 recreate"
                        RECREATE_FLAG="--recreate"
                    else
                        echo ""
                        echo "  Milvus 已有 ${EXISTING_ROWS} 行数据, 请选择:"
                        echo "    [r] recreate — 丢弃并重建 (推荐)"
                        echo "    [a] append   — 追加 (会重复)"
                        echo "    [s] skip     — 保留旧数据, 不导入"
                        echo "    [q] quit     — 中止"
                        read -r -p "选择 [r/a/s/q] (默认 r): " choice
                        case "${choice:-r}" in
                            r|R) RECREATE_FLAG="--recreate" ;;
                            a|A) RECREATE_FLAG="" ;;
                            s|S) DO_IMPORT=0 ;;
                            q|Q) echo "已中止."; exit 0 ;;
                            *)   echo "无效选项."; exit 2 ;;
                        esac
                    fi
                    ;;
            esac
            ;;
    esac

    # ---- 3c. 执行 ----
    if [[ "$DO_IMPORT" -eq 1 ]]; then
        # shellcheck disable=SC2086
        "$PY" scripts/import_to_milvus.py $RECREATE_FLAG
    fi
else
    banner "[3/3] 跳过导入 (--skip-import 或 --skip-milvus)"
fi

banner "全部完成 ✅"
cat <<'EOF'
Milvus  : localhost:19530
MinIO   : http://localhost:9001  (minioadmin / minioadmin)

常用命令:
  停止 Milvus            : ./stop_milvus.sh
  仅重新导入 (不下载)    : ./setup_all.sh --skip-download
  查看容器日志           : docker logs -f milvus-standalone
EOF
