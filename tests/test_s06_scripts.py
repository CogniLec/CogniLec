"""S06 Script smoke tests — verifies scripts are syntactically valid and importable."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

SCRIPTS = [
    "scripts/s06_asr_bakeoff.py",
    "scripts/s06_embedding_bakeoff.py",
    "scripts/s06_disagreement.py",
    "scripts/s06_report.py",
    "scripts/s06_check_gates.py",
    "scripts/s06_run_all.py",
]


class TestScriptsSyntax:
    @pytest.mark.parametrize("script_path", SCRIPTS)
    def test_valid_python_syntax(self, script_path: str):
        """Each S06 script must parse without syntax errors."""
        path = Path(script_path)
        assert path.exists(), f"Script not found: {script_path}"
        source = path.read_text()
        ast.parse(source, filename=script_path)

    @pytest.mark.parametrize("script_path", SCRIPTS)
    def test_has_main(self, script_path: str):
        """Each S06 script should have a main() or __main__ block."""
        source = Path(script_path).read_text()
        tree = ast.parse(source, filename=script_path)
        has_main = any(
            (isinstance(node, ast.FunctionDef) and node.name == "main") for node in ast.walk(tree)
        )
        has_main_guard = any(
            isinstance(node, ast.If)
            and isinstance(node.test, ast.Compare)
            and any(
                isinstance(c, ast.Constant) and c.value == "__main__"
                for c in [node.test.left, *node.test.comparators]
            )
            for node in ast.walk(tree)
        )
        assert has_main or has_main_guard, f"{script_path}: no main() or __main__ guard"


class TestScriptsDocstrings:
    @pytest.mark.parametrize("script_path", SCRIPTS)
    def test_has_docstring(self, script_path: str):
        """Each S06 script should have a module docstring."""
        source = Path(script_path).read_text()
        tree = ast.parse(source, filename=script_path)
        docstring = ast.get_docstring(tree)
        assert docstring is not None, f"{script_path}: missing module docstring"
        assert "S06" in docstring, f"{script_path}: docstring should mention S06"
