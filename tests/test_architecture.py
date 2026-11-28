"""Architecture contracts for IDD's production entry points. Uses only the standard library."""

from __future__ import annotations

import ast
from graphlib import TopologicalSorter
from importlib.util import resolve_name
import os
from pathlib import Path
import subprocess
import sys
import unittest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"


class TestArchitecture(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        files = [SCRIPTS / "idd", *sorted(SCRIPTS.rglob("*.py"))]
        cls.trees = {}
        packages = {}
        for path in files:
            parts = path.relative_to(SCRIPTS).with_suffix("").parts
            is_package = parts[-1] == "__init__"
            name = ".".join(parts[:-1] if is_package else parts)
            cls.trees[name] = ast.parse(path.read_text(encoding="utf-8"))
            packages[name] = name if is_package else name.rpartition(".")[0]
        cls.graph = {}
        cls.private_access = []
        for module, tree in cls.trees.items():
            dependencies = set()
            aliases = {}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for name in node.names:
                        if name.name in cls.trees:
                            dependencies.add(name.name)
                            aliases[name.asname or name.name] = name.name
                elif isinstance(node, ast.ImportFrom):
                    base = resolve_name("." * node.level + (node.module or ""), packages[module])
                    if base not in cls.trees:
                        continue
                    if base != module:
                        dependencies.add(base)
                    for name in node.names:
                        child = f"{base}.{name.name}"
                        if child in cls.trees:
                            dependencies.add(child)
                            aliases[name.asname or name.name] = child
                        if name.name.startswith("_"):
                            cls.private_access.append(f"{module}:{node.lineno} imports {child}")
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    owner = aliases.get(node.value.id)
                    if owner and node.attr.startswith("_"):
                        cls.private_access.append(f"{module}:{node.lineno} reads {owner}.{node.attr}")
            cls.graph[module] = dependencies

    def test_dependency_direction_and_cycles(self) -> None:
        # Run the topological sort to completion so a reported cycle includes its path.
        tuple(TopologicalSorter(self.graph).static_order())
        entry_points = {"idd", "idd_cli", "release", "board_ui", "preview_ui"}
        for module, deps in self.graph.items():
            if module not in entry_points:
                self.assertFalse(deps & entry_points, f"{module} depends on an entry point: {deps & entry_points}")
        for module in (
            "command_runner", "delivery_summary", "git_worktrees", "local_http", "local_state",
            "naming", "repo_registry", "repository_lock", "task_status", "version", "worktree_cleanup",
        ):
            self.assertFalse(self.graph[module] & {"forge", "monitor"}, f"{module} depends on a platform or monitor")
        self.assertEqual(self.graph["idd"], {"idd_cli"})

    def test_production_callers_use_public_module_interfaces(self) -> None:
        self.assertEqual(self.private_access, [])

    def test_worktree_inventory_has_one_owner(self) -> None:
        owners = []
        for module, tree in self.trees.items():
            for node in ast.walk(tree):
                if isinstance(node, (ast.List, ast.Tuple)):
                    words = [v.value if isinstance(v, ast.Constant) else None for v in node.elts]
                    if any(words[i:i+2] == ["worktree", "list"] for i in range(len(words) - 1)):
                        owners.append(module)
        self.assertEqual(owners, ["git_worktrees"])

    def test_supported_branch_types_across_entry_points(self) -> None:
        sys.path.insert(0, str(SCRIPTS))
        self.addCleanup(sys.path.remove, str(SCRIPTS))
        from idd_cli import build_parser
        from naming import ALLOWED_TYPES, validate_branch_name
        from worktree_cleanup import cleanup_scope_error

        kinds = ("feat", "fix", "refactor", "perf", "docs", "test", "ci", "chore")
        self.assertEqual(ALLOWED_TYPES, kinds)
        parser = build_parser()
        for kind in kinds:
            with self.subTest(kind=kind):
                branch = f"{kind}/42-work"
                validate_branch_name(branch, 42)
                validate_branch_name(f"{kind}/local")
                self.assertEqual(parser.parse_args(["start", "42", "--prefix", kind]).prefix, kind)
                self.assertEqual(parser.parse_args(["issue", "create", "--title", "name", "--type", kind]).issue_type, kind)
                self.assertFalse(cleanup_scope_error(Path("/main"), Path("/else/path"), branch, Path("/managed")))

    def test_cli_metadata_does_not_load_ui_modules(self) -> None:
        code = """
import runpy, sys
sys.argv = [sys.argv[1], '--version']
try:
    runpy.run_path(sys.argv[0], run_name='__main__')
except SystemExit as exc:
    if exc.code:
        raise
if {'board_ui', 'preview_ui'} & sys.modules.keys():
    raise AssertionError('CLI metadata loaded a web application')
"""
        proc = subprocess.run(
            [sys.executable, "-B", "-c", code, str(SCRIPTS / "idd")],
            env=dict(os.environ, IDD_NO_AUTO_UPDATE="1"), capture_output=True, text=True, check=True,
        )
        self.assertRegex(proc.stdout.strip(), r"^idd [0-9]+\.")
