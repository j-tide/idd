"""Subprocess execution and expected failures reported by IDD commands."""

from __future__ import annotations

from pathlib import Path
import subprocess


class IddError(Exception):
    """Expected CLI error carrying an explicit exit code."""

    def __init__(self, message: str, exit_code: int = 1) -> None:
        super().__init__(message)
        self.exit_code = exit_code


def run_cmd(
    args: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    input_text: str | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Run a subprocess capturing UTF-8 output; raise IddError on failure when check=True."""
    try:
        proc = subprocess.run(
            args,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            input=input_text,
            env=env,
        )
    except FileNotFoundError as exc:
        raise IddError(f"找不到可执行文件 `{args[0]}`，请确认已安装并在 PATH 中。") from exc
    if check and proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"退出码 {proc.returncode}"
        raise IddError(f"命令 `{' '.join(args)}` 执行失败：{detail}")
    return proc
