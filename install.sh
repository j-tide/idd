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

init_colors() {
    USE_COLOR=0
    USE_ERR_COLOR=0
    if [ -z "${NO_COLOR:-}" ]; then
        _forced=0
        if [ -n "${FORCE_COLOR:-}" ] && [ "${FORCE_COLOR:-}" != "0" ]; then
            _forced=1
        elif [ -n "${CLICOLOR_FORCE:-}" ] && [ "${CLICOLOR_FORCE:-}" != "0" ]; then
            _forced=1
        fi
        if [ "$_forced" = "1" ]; then
            USE_COLOR=1
            USE_ERR_COLOR=1
        elif [ "${TERM:-}" != "dumb" ]; then
            if [ -t 1 ]; then
                USE_COLOR=1
            fi
            if [ -t 2 ]; then
                USE_ERR_COLOR=1
            fi
        fi
    fi

    _esc="$(printf '\033')"
    if [ "$USE_COLOR" = "1" ]; then
        C_RESET="${_esc}[0m"
        C_BOLD="${_esc}[1m"
        C_DIM="${_esc}[2m"
        C_RED="${_esc}[31m"
        C_GREEN="${_esc}[32m"
        C_YELLOW="${_esc}[33m"
        C_MAGENTA="${_esc}[35m"
        C_CYAN="${_esc}[36m"
    else
        C_RESET=""
        C_BOLD=""
        C_DIM=""
        C_RED=""
        C_GREEN=""
        C_YELLOW=""
        C_MAGENTA=""
        C_CYAN=""
    fi

    if [ "$USE_ERR_COLOR" = "1" ]; then
        E_RESET="${_esc}[0m"
        E_BOLD="${_esc}[1m"
        E_DIM="${_esc}[2m"
        E_RED="${_esc}[31m"
        E_YELLOW="${_esc}[33m"
    else
        E_RESET=""
        E_BOLD=""
        E_DIM=""
        E_RED=""
        E_YELLOW=""
    fi
}

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

pretty_path() {
    _raw_p="$1"
    _home_raw="${HOME%/}"
    _home_canon="$(canonical_path "$_home_raw")"
    _home_canon="${_home_canon%/}"
    if [ "$_raw_p" = "$_home_raw" ] || [ "$_raw_p" = "$_home_canon" ]; then
        printf '~\n'
        return 0
    fi
    case "$_raw_p" in
        "$_home_raw"/*)
            printf '~/%s\n' "${_raw_p#"$_home_raw/"}"
            ;;
        "$_home_canon"/*)
            printf '~/%s\n' "${_raw_p#"$_home_canon/"}"
            ;;
        *)
            printf '%s\n' "$_raw_p"
            ;;
    esac
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
    _LINK_OK=1
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
        _LINK_OK=0
        printf '  %s!%s  跳过已存在的非软链路径：%s%s%s（未覆盖）\n' \
            "$E_YELLOW$E_BOLD" "$E_RESET" "$E_DIM" "$(pretty_path "$_dst")" "$E_RESET" >&2
        return 0
    fi
    ln -s "$_src" "$_dst"
}

print_banner() {
    _badge="$1"
    printf '\n'
    printf '  %s◆%s %sIDD%s  %s%s%s  %s·  Issue-Driven Development%s\n' \
        "$C_CYAN$C_BOLD" "$C_RESET" \
        "$C_BOLD" "$C_RESET" \
        "$C_CYAN" "$_badge" "$C_RESET" \
        "$C_DIM" "$C_RESET"
    printf '  %s──────────────────────────────────────────────%s\n' "$C_DIM" "$C_RESET"
}

err_exit() {
    printf '  %s✗%s  %s错误：%s%s\n' "$E_RED$E_BOLD" "$E_RESET" "$E_RED" "$1" "$E_RESET" >&2
    exit 1
}

fallback_uninstall() {
    _skill_canon="$(canonical_path "$SKILL_DIR")"
    _bin_link="$BIN_DIR/idd"
    _links_to_remove=""
    _link_count=0
    _dirs_to_remove=""
    _dir_count=0
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
                _link_count=$((_link_count + 1))
            else
                _warnings="${_warnings}  ${E_YELLOW}${E_BOLD}!${E_RESET}  跳过无关软链    ${E_DIM}$(pretty_path "$_path")${E_RESET}
"
            fi
        elif [ -e "$_path" ]; then
            _warnings="${_warnings}  ${E_YELLOW}${E_BOLD}!${E_RESET}  跳过非软链路径  ${E_DIM}$(pretty_path "$_path")${E_RESET}
"
        fi
    done

    if [ -d "$CACHE_DIR" ] || [ -L "$CACHE_DIR" ]; then
        if is_unsafe_delete_root "$CACHE_DIR"; then
            err_exit "拒绝删除受保护路径 \`$CACHE_DIR\`。"
        fi
        _dirs_to_remove="${_dirs_to_remove}缓存目录|$CACHE_DIR
"
        _dir_count=$((_dir_count + 1))
    fi

    if [ "$KEEP_CONFIG" = "1" ]; then
        if [ -e "$CONFIG_DIR" ] || [ -L "$CONFIG_DIR" ]; then
            _kept="${_kept}  ${C_CYAN}○${C_RESET}  ${C_DIM}保留配置${C_RESET}    $(pretty_path "$CONFIG_DIR")
"
        fi
    else
        if [ -d "$CONFIG_DIR" ] || [ -L "$CONFIG_DIR" ]; then
            if is_unsafe_delete_root "$CONFIG_DIR"; then
                err_exit "拒绝删除受保护路径 \`$CONFIG_DIR\`。"
            fi
            _dirs_to_remove="${_dirs_to_remove}配置目录|$CONFIG_DIR
"
            _dir_count=$((_dir_count + 1))
        fi
    fi

    if [ -d "$SKILL_DIR" ] || [ -L "$SKILL_DIR" ]; then
        if is_unsafe_delete_root "$SKILL_DIR"; then
            err_exit "拒绝删除受保护路径 \`$SKILL_DIR\`。"
        fi
        _dirs_to_remove="${_dirs_to_remove}技能仓库|$SKILL_DIR
"
        _dir_count=$((_dir_count + 1))
    fi

    if [ -z "$_links_to_remove" ] && [ -z "$_dirs_to_remove" ]; then
        if [ -n "$_warnings" ]; then
            printf '%s' "$_warnings" >&2
        fi
        if [ -n "$_kept" ]; then
            printf '%s' "$_kept"
        fi
        printf '  %si%s  未检测到可卸载的 idd 安装文件。\n' "$C_CYAN" "$C_RESET"
        exit 0
    fi

    print_banner "卸载"
    printf '  %s待移除清单（不影响业务仓库、分支与 Worktree）：%s\n\n' "$C_DIM" "$C_RESET"
    printf '%s' "$_links_to_remove" | while IFS= read -r _l; do
        if [ -n "$_l" ]; then
            printf '  %s×%s  软链        %s\n' "$C_RED$C_BOLD" "$C_RESET" "$(pretty_path "$_l")"
        fi
    done
    printf '%s' "$_dirs_to_remove" | while IFS='|' read -r _label _d; do
        if [ -n "$_d" ]; then
            printf '  %s×%s  %s    %s\n' "$C_RED$C_BOLD" "$C_RESET" "$_label" "$(pretty_path "$_d")"
        fi
    done
    if [ -n "$_kept" ]; then
        printf '%s' "$_kept"
    fi
    if [ -n "$_warnings" ]; then
        printf '%s' "$_warnings" >&2
    fi

    if [ "$DRY_RUN" = "1" ]; then
        printf '\n  %si%s  [dry-run] 仅预览，未删除任何文件。\n\n' "$C_CYAN" "$C_RESET"
        exit 0
    fi

    if [ "$YES" != "1" ]; then
        if [ ! -t 0 ]; then
            err_exit "当前为非交互环境，请传入 \`-y\` / \`--yes\` 或先用 \`--dry-run\` 预览。"
        fi
        printf '\n  %s?%s  确认完全卸载 idd？[y/N] ' "$C_YELLOW$C_BOLD" "$C_RESET"
        if ! IFS= read -r _ans; then
            printf '\n  %si%s  已取消卸载。\n' "$C_DIM" "$C_RESET"
            exit 1
        fi
        case "$_ans" in
            y|Y|yes|YES)
                ;;
            *)
                printf '  %si%s  已取消卸载。\n' "$C_DIM" "$C_RESET"
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

    printf '\n  %s✓%s  %s已完成 idd 卸载%s %s（共移除 %s 条软链、%s 个目录）%s\n\n' \
        "$C_GREEN$C_BOLD" "$C_RESET" "$C_BOLD" "$C_RESET" "$C_DIM" "$_link_count" "$_dir_count" "$C_RESET"
    exit 0
}

init_colors

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
            python3 -B "$SKILL_DIR/scripts/idd" uninstall ${1+"$@"}
    fi
    fallback_uninstall
fi

if ! command -v git >/dev/null 2>&1; then
    err_exit "未找到 \`git\`，请先安装 Git 后重试。"
fi
if ! command -v python3 >/dev/null 2>&1; then
    err_exit "未找到 \`python3\`，请先安装 Python 3 后重试。"
fi

REPO_STATUS="ok"
REPO_LABEL="技能仓库就绪"
REPO_NOTE=""

if [ -e "$SKILL_DIR/.git" ]; then
    _branch="$(git -C "$SKILL_DIR" branch --show-current 2>/dev/null || true)"
    _dirty="$(git -C "$SKILL_DIR" status --porcelain 2>/dev/null || true)"
    _has_origin=0
    if git -C "$SKILL_DIR" remote 2>/dev/null | grep -qx 'origin'; then
        _has_origin=1
    fi
    if [ "$_branch" = "main" ] && [ -z "$_dirty" ] && [ "$_has_origin" = "1" ]; then
        _before_sha="$(git -C "$SKILL_DIR" rev-parse --short HEAD 2>/dev/null || true)"
        if git -C "$SKILL_DIR" fetch origin main --quiet >/dev/null 2>&1; then
            git -C "$SKILL_DIR" merge --ff-only origin/main --quiet >/dev/null 2>&1 || true
        fi
        _after_sha="$(git -C "$SKILL_DIR" rev-parse --short HEAD 2>/dev/null || true)"
        if [ -n "$_before_sha" ] && [ -n "$_after_sha" ] && [ "$_before_sha" != "$_after_sha" ]; then
            REPO_LABEL="更新技能仓库"
            REPO_NOTE="(${_before_sha} → ${_after_sha})"
        else
            REPO_LABEL="技能仓库就绪"
            REPO_NOTE="(已是最新)"
        fi
    else
        REPO_STATUS="warn"
        REPO_LABEL="技能仓库就绪"
        REPO_NOTE="(保留本地状态)"
    fi
elif [ -e "$SKILL_DIR" ] || [ -L "$SKILL_DIR" ]; then
    err_exit "目标目录 \`$SKILL_DIR\` 已存在且不是 Git 仓库，为避免误覆盖已中止安装。"
else
    mkdir -p "$(dirname "$SKILL_DIR")"
    git clone --quiet "$REPO_URL" "$SKILL_DIR"
    REPO_LABEL="克隆技能仓库"
    REPO_NOTE=""
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
_claude_ok="$_LINK_OK"
link_target "$SKILL_DIR" "$HOME/.codex/skills/idd"
_codex_ok="$_LINK_OK"
link_target "$SKILL_DIR" "$HOME/.gemini/config/skills/idd"
_agy_ok="$_LINK_OK"
link_target "$SKILL_DIR/scripts/idd" "$BIN_DIR/idd"
_bin_ok="$_LINK_OK"

VERSION_STR="$(IDD_NO_AUTO_UPDATE=1 python3 -B "$SKILL_DIR/scripts/idd" --version 2>/dev/null || printf 'idd')"
case "$VERSION_STR" in
    "idd "*)
        BADGE_VER="v${VERSION_STR#idd }"
        ;;
    *)
        BADGE_VER="$VERSION_STR"
        ;;
esac

_tools_line=""
_tools_partial=0
_sep="${C_DIM} · ${C_RESET}"
if [ "$_claude_ok" = "1" ]; then
    _tools_line="${C_CYAN}Claude Code${C_RESET}"
else
    _tools_partial=1
fi
if [ "$_codex_ok" = "1" ]; then
    if [ -n "$_tools_line" ]; then
        _tools_line="${_tools_line}${_sep}"
    fi
    _tools_line="${_tools_line}${C_MAGENTA}Codex${C_RESET}"
else
    _tools_partial=1
fi
if [ "$_agy_ok" = "1" ]; then
    if [ -n "$_tools_line" ]; then
        _tools_line="${_tools_line}${_sep}"
    fi
    _tools_line="${_tools_line}${C_GREEN}Antigravity${C_RESET}"
else
    _tools_partial=1
fi
if [ -z "$_tools_line" ]; then
    _tools_line="${C_YELLOW}未挂载（已有非软链目录）${C_RESET}"
elif [ "$_tools_partial" = "1" ]; then
    _tools_line="${_tools_line}  ${C_YELLOW}(部分已跳过)${C_RESET}"
fi

print_banner "$BADGE_VER"

if [ "$REPO_STATUS" = "warn" ]; then
    _repo_icon="${C_YELLOW}${C_BOLD}!${C_RESET}"
else
    _repo_icon="${C_GREEN}${C_BOLD}✓${C_RESET}"
fi
if [ -n "$REPO_NOTE" ]; then
    printf '  %s  %s    %s  %s%s%s\n' \
        "$_repo_icon" "$REPO_LABEL" "$(pretty_path "$SKILL_DIR")" "$C_DIM" "$REPO_NOTE" "$C_RESET"
else
    printf '  %s  %s    %s\n' \
        "$_repo_icon" "$REPO_LABEL" "$(pretty_path "$SKILL_DIR")"
fi

if [ "$_tools_partial" = "1" ]; then
    _tools_icon="${C_YELLOW}${C_BOLD}!${C_RESET}"
else
    _tools_icon="${C_GREEN}${C_BOLD}✓${C_RESET}"
fi
printf '  %s  挂载 AI 工具    %s\n' "$_tools_icon" "$_tools_line"

if [ "$_bin_ok" = "1" ]; then
    printf '  %s  挂载全局命令    %s\n' "${C_GREEN}${C_BOLD}✓${C_RESET}" "$(pretty_path "$BIN_DIR/idd")"
else
    printf '  %s  挂载全局命令    %s  %s(已跳过冲突文件)%s\n' \
        "${C_YELLOW}${C_BOLD}!${C_RESET}" "$(pretty_path "$BIN_DIR/idd")" "$C_YELLOW" "$C_RESET"
fi

if ! bin_in_path "$RAW_BIN_DIR" "$BIN_DIR"; then
    printf '\n  %s!%s  %s`%s` 暂未加入 PATH，请将以下行添加到你的 shell 配置中：%s\n' \
        "${C_YELLOW}${C_BOLD}" "$C_RESET" "$C_YELLOW" "$(pretty_path "$RAW_BIN_DIR")" "$C_RESET"
    printf '     %sexport PATH="%s:$PATH"%s\n' "$C_BOLD" "$RAW_BIN_DIR" "$C_RESET"
fi

printf '\n  %s✓%s  %s已安装 %s%s\n\n' \
    "${C_GREEN}${C_BOLD}" "$C_RESET" "$C_BOLD" "$VERSION_STR" "$C_RESET"
printf '     %sidd status%s     %s查看全局 Issue / Worktree 进度%s\n' "$C_CYAN" "$C_RESET" "$C_DIM" "$C_RESET"
printf '     %sidd board%s      %s启动本地 Web 实时监控看板%s\n' "$C_CYAN" "$C_RESET" "$C_DIM" "$C_RESET"
printf '     %sidd uninstall%s  %s随时安全完全卸载%s\n\n' "$C_CYAN" "$C_RESET" "$C_DIM" "$C_RESET"
printf '  %si%s  %s零侵入安装：未修改任何 AGENTS.md / 全局规则；如需设为默认工作流，见 README 可选模板。%s\n\n' \
    "$C_CYAN" "$C_RESET" "$C_DIM" "$C_RESET"
