import shutil
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def template_tree(tmp_path: Path) -> Path:
    """Return a throwaway copy of the template repo (no .git, .venv, node_modules)."""
    dest = tmp_path / "repo"
    shutil.copytree(
        REPO_ROOT,
        dest,
        ignore=shutil.ignore_patterns(
            ".git",
            ".venv",
            "node_modules",
            "__pycache__",
            "*.pyc",
            "dist",
            "htmlcov",
            "worktrees",
        ),
    )
    return dest
