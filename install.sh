#!/usr/bin/env sh
# IDD (Issue-Driven Development) installer and fallback uninstaller.
set -eu

REPO_URL="${IDD_REPO_URL:-https://github.com/j-tide/idd.git}"
SKILL_DIR="${IDD_SKILL_DIR:-$HOME/.agents/skills/idd}"
BIN_DIR="${IDD_BIN_DIR:-$HOME/.local/bin}"
CONFIG_DIR="${IDD_CONFIG_DIR:-$HOME/.config/idd}"
CACHE_DIR="${IDD_CACHE_DIR:-$HOME/.cache/idd}"

UNINSTALL=0
YES=0
DRY_RUN=0
KEEP_CONFIG=0
FORCE=0

usage() {
    cat <<'EOF'
用法:
  install.sh                         安装或修复 idd 技能及全局 CLI 软链
  install.sh --uninstall [选项]      卸载 idd（优先调用 idd uninstall，缺失时使用 shell 兜底清理）

卸载选项:
  -y, --yes         跳过交互确认
  --dry-run         仅预览待移除路径，不实际删除
  --keep-config     保留 ~/.config/idd 配置目录（主机凭据与仓库索引）
  --force           强制卸载（即使技能仓库存在未提交改动或未推送提交）
  -h, --help        显示帮助
EOF
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --uninstall)
            UNINSTALL=1
            ;;
        -y|--yes)
            YES=1
            ;;
        --dry-run)
            DRY_RUN=1
            ;;
        --keep-config)
            KEEP_CONFIG=1
            ;;
        --force)
            FORCE=1
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            printf '错误：未知参数 `%s`\n' "$1" >&2
            usage >&2
            exit 1
            ;;
    esac
    shift
done

canonical_path() {
    _p="$1"
    if [ -d "$_p" ]; then
        CDPATH= cd -- "$_p" 2>/dev/null && pwd -P
        return 0
    fi
    _suffix=""
    _cur="$_p"
    while [ "$_cur" != "/" ] && [ "$_cur" != "." ] && [ ! -d "$_cur" ]; do
        _base="$(basename "$_cur")"
        _next="$(dirname "$_cur")"
        if [ "$_next" = "$_cur" ]; then
            break
        fi
        if [ -n "$_suffix" ]; then
            _suffix="$_base/$_suffix"
        else
            _suffix="$_base"
        fi
        _cur="$_next"
    done
    if [ -d "$_cur" ]; then
        _cur_canon="$(CDPATH= cd -- "$_cur" 2>/dev/null && pwd -P)"
        if [ -n "$_suffix" ]; then
            if [ "$_cur_canon" = "/" ]; then
                printf '/%s\n' "$_suffix"
            else
                printf '%s/%s\n' "$_cur_canon" "$_suffix"
            fi
        else
            printf '%s\n' "$_cur_canon"
        fi
        return 0
    fi
    printf '%s\n' "$_p"
}

is_unsafe_delete_root() {
    _cand="$(canonical_path "$1")"
    _home_canon="$(canonical_path "$HOME")"
    if [ "$_cand" = "/" ] || [ "$_cand" = "$_home_canon" ]; then
        return 0
    fi
    case "$_home_canon" in
        "$_cand"/*)
            return 0
            ;;
    esac
    return 1
}

symlink_points_to_idd() {
    _link="$1"
    _skill_canon="$2"
    _is_bin="$3"

    if [ ! -L "$_link" ]; then
        return 1
    fi

    _raw="$(readlink "$_link" 2>/dev/null || true)"
    if [ -z "$_raw" ]; then
        return 1
    fi

    case "$_raw" in
        /*)
            _resolved="$(canonical_path "$_raw")"
            ;;
        *)
            _link_dir="$(dirname "$_link")"
            _resolved="$(canonical_path "$_link_dir/$_raw")"
            ;;
    esac

    if [ "$_is_bin" = "1" ]; then
        case "$_resolved" in
            "$_skill_canon/scripts/idd"|"$_skill_canon/scripts/idd_cli.py"|"$SKILL_DIR/scripts/idd"|"$SKILL_DIR/scripts/idd_cli.py")
                return 0
                ;;
        esac
        return 1
    fi

    if [ "$_resolved" = "$_skill_canon" ] || [ "$_resolved" = "$SKILL_DIR" ]; then
        return 0
    fi
    return 1
}

bin_in_path() (
    _raw="$1"
    _canon="$2"
    set -f
    IFS=':'
    for _dir in ${PATH:-}; do
        if [ -n "$_dir" ] && { [ "$_dir" = "$_raw" ] || [ "$(canonical_path "$_dir")" = "$_canon" ]; }; then
            return 0
        fi
    done
    return 1
)

link_target() {
    _src="$1"
    _dst="$2"
    mkdir -p "$(dirname "$_dst")"
    if [ -L "$_dst" ]; then
        rm -f "$_dst"
        ln -s "$_src" "$_dst"
        return 0
    fi
    if [ -e "$_dst" ]; then
        _src_canon="$(canonical_path "$_src")"
        _dst_canon="$(canonical_path "$_dst")"
        if [ "$_src_canon" = "$_dst_canon" ]; then
            return 0
        fi
        printf '警告：跳过已存在的非软链路径 `%s`（未覆盖）。\n' "$_dst" >&2
        return 0
    fi
    ln -s "$_src" "$_dst"
}

fallback_uninstall() {
    _skill_canon="$(canonical_path "$SKILL_DIR")"
    _bin_link="$BIN_DIR/idd"
    _links_to_remove=""
    _dirs_to_remove=""
    _warnings=""
    _kept=""

    for _entry in \
        "0:$HOME/.claude/skills/idd" \
        "0:$HOME/.codex/skills/idd" \
        "0:$HOME/.gemini/config/skills/idd" \
        "1:$_bin_link"
    do
        _is_bin="${_entry%%:*}"
        _path="${_entry#*:}"
        if [ -L "$_path" ]; then
            if symlink_points_to_idd "$_path" "$_skill_canon" "$_is_bin"; then
                _links_to_remove="$_links_to_remove$_path
"
            else
                _warnings="$_warnings- 跳过无关软链：$_path
"
            fi
        elif [ -e "$_path" ]; then
            _warnings="$_warnings- 跳过非软链路径：$_path
"
        fi
    done

    if [ -d "$CACHE_DIR" ] || [ -L "$CACHE_DIR" ]; then
        if is_unsafe_delete_root "$CACHE_DIR"; then
            printf '错误：拒绝删除受保护路径 `%s`。\n' "$CACHE_DIR" >&2
            exit 1
        fi
        _dirs_to_remove="${_dirs_to_remove}缓存目录|$CACHE_DIR
"
    fi

    if [ "$KEEP_CONFIG" = "1" ]; then
        if [ -e "$CONFIG_DIR" ] || [ -L "$CONFIG_DIR" ]; then
            _kept="$_kept- 保留配置目录：$CONFIG_DIR
"
        fi
    else
        if [ -d "$CONFIG_DIR" ] || [ -L "$CONFIG_DIR" ]; then
            if is_unsafe_delete_root "$CONFIG_DIR"; then
                printf '错误：拒绝删除受保护路径 `%s`。\n' "$CONFIG_DIR" >&2
                exit 1
            fi
            _dirs_to_remove="${_dirs_to_remove}配置目录|$CONFIG_DIR
"
        fi
    fi

    if [ -d "$SKILL_DIR" ] || [ -L "$SKILL_DIR" ]; then
        if is_unsafe_delete_root "$SKILL_DIR"; then
            printf '错误：拒绝删除受保护路径 `%s`。\n' "$SKILL_DIR" >&2
            exit 1
        fi
        _dirs_to_remove="${_dirs_to_remove}技能仓库|$SKILL_DIR
"
    fi

    if [ -z "$_links_to_remove" ] && [ -z "$_dirs_to_remove" ]; then
        if [ -n "$_warnings" ]; then
            printf '%s' "$_warnings" >&2
        fi
        printf '未检测到可卸载的 idd 安装文件。\n'
        exit 0
    fi

    printf '将要移除以下 idd 文件：\n'
    printf '%s' "$_links_to_remove" | while IFS= read -r _l; do
        if [ -n "$_l" ]; then
            printf '  - 软链：%s\n' "$_l"
        fi
    done
    printf '%s' "$_dirs_to_remove" | while IFS='|' read -r _label _d; do
        if [ -n "$_d" ]; then
            printf '  - %s：%s\n' "$_label" "$_d"
        fi
    done
    if [ -n "$_kept" ]; then
        printf '%s' "$_kept"
    fi
    if [ -n "$_warnings" ]; then
        printf '%s' "$_warnings" >&2
    fi

    if [ "$DRY_RUN" = "1" ]; then
        printf '[dry-run] 仅预览，未删除任何文件。\n'
        exit 0
    fi

    if [ "$YES" != "1" ]; then
        if [ ! -t 0 ]; then
            printf '错误：当前为非交互环境，请传入 `-y` / `--yes` 或先用 `--dry-run` 预览。\n' >&2
            exit 1
        fi
        printf '确认完全卸载 idd？[y/N] '
        if ! IFS= read -r _ans; then
            printf '\n已取消卸载。\n'
            exit 1
        fi
        case "$_ans" in
            y|Y|yes|YES)
                ;;
            *)
                printf '已取消卸载。\n'
                exit 1
                ;;
        esac
    fi

    printf '%s' "$_links_to_remove" | while IFS= read -r _l; do
        if [ -n "$_l" ]; then
            rm -f "$_l"
        fi
    done
    printf '%s' "$_dirs_to_remove" | while IFS='|' read -r _label _d; do
        if [ -n "$_d" ]; then
            if [ -L "$_d" ]; then
                rm -f "$_d"
            else
                rm -rf "$_d"
            fi
        fi
    done

    printf '已完成 idd 卸载。\n'
    exit 0
}

if [ "$UNINSTALL" = "1" ]; then
    if [ -f "$SKILL_DIR/scripts/idd" ] && command -v python3 >/dev/null 2>&1; then
        set --
        if [ "$YES" = "1" ]; then
            set -- ${1+"$@"} "-y"
        fi
        if [ "$DRY_RUN" = "1" ]; then
            set -- ${1+"$@"} "--dry-run"
        fi
        if [ "$KEEP_CONFIG" = "1" ]; then
            set -- ${1+"$@"} "--keep-config"
        fi
        if [ "$FORCE" = "1" ]; then
            set -- ${1+"$@"} "--force"
        fi
        exec env \
            IDD_NO_AUTO_UPDATE=1 \
            IDD_SKILL_DIR="$SKILL_DIR" \
            IDD_BIN_DIR="$BIN_DIR" \
            IDD_CONFIG_DIR="$CONFIG_DIR" \
            IDD_CACHE_DIR="$CACHE_DIR" \
            python3 "$SKILL_DIR/scripts/idd" uninstall ${1+"$@"}
    fi
    fallback_uninstall
fi

if ! command -v git >/dev/null 2>&1; then
    printf '错误：未找到 `git`，请先安装 Git 后重试。\n' >&2
    exit 1
fi
if ! command -v python3 >/dev/null 2>&1; then
    printf '错误：未找到 `python3`，请先安装 Python 3 后重试。\n' >&2
    exit 1
fi

if [ -e "$SKILL_DIR/.git" ]; then
    _branch="$(git -C "$SKILL_DIR" branch --show-current 2>/dev/null || true)"
    _dirty="$(git -C "$SKILL_DIR" status --porcelain 2>/dev/null || true)"
    _has_origin=0
    if git -C "$SKILL_DIR" remote 2>/dev/null | grep -qx 'origin'; then
        _has_origin=1
    fi
    if [ "$_branch" = "main" ] && [ -z "$_dirty" ] && [ "$_has_origin" = "1" ]; then
        if git -C "$SKILL_DIR" fetch origin main --quiet >/dev/null 2>&1; then
            git -C "$SKILL_DIR" merge --ff-only origin/main --quiet >/dev/null 2>&1 || true
        fi
    else
        printf '提示：检测到本地 `%s` 存在自定义分支或未提交改动，已保留本地状态并继续刷新软链。\n' "$SKILL_DIR"
    fi
elif [ -e "$SKILL_DIR" ] || [ -L "$SKILL_DIR" ]; then
    printf '错误：目标目录 `%s` 已存在且不是 Git 仓库，为避免误覆盖已中止安装。\n' "$SKILL_DIR" >&2
    exit 1
else
    mkdir -p "$(dirname "$SKILL_DIR")"
    git clone --quiet "$REPO_URL" "$SKILL_DIR"
fi

SKILL_DIR="$(canonical_path "$SKILL_DIR")"
RAW_BIN_DIR="$BIN_DIR"
mkdir -p "$BIN_DIR"
BIN_DIR="$(canonical_path "$BIN_DIR")"

for _script in "$SKILL_DIR/scripts/idd" "$SKILL_DIR/scripts/task_status.py"; do
    if [ -f "$_script" ] && [ ! -x "$_script" ]; then
        chmod +x "$_script"
    fi
done

link_target "$SKILL_DIR" "$HOME/.claude/skills/idd"
link_target "$SKILL_DIR" "$HOME/.codex/skills/idd"
link_target "$SKILL_DIR" "$HOME/.gemini/config/skills/idd"
link_target "$SKILL_DIR/scripts/idd" "$BIN_DIR/idd"

VERSION_STR="$(IDD_NO_AUTO_UPDATE=1 python3 -B "$SKILL_DIR/scripts/idd" --version 2>/dev/null || printf 'idd')"
printf '已安装 %s\n' "$VERSION_STR"
printf '技能仓库：%s\n' "$SKILL_DIR"
printf '全局命令：%s/idd\n' "$BIN_DIR"
printf '已挂载工具：Claude Code / Codex / Antigravity\n'

if ! bin_in_path "$RAW_BIN_DIR" "$BIN_DIR"; then
    printf '提示：`%s` 暂未加入 PATH，请将以下行添加到你的 shell 配置中：\n' "$RAW_BIN_DIR"
    printf '  export PATH="%s:$PATH"\n' "$RAW_BIN_DIR"
fi
