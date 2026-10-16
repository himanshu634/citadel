"""The three packages keep their dependency direction: backend -> agents -> brain.

Why: the split only means something while brain stays free of the agents and the server. Plain
import greps miss imports inside functions and module paths written as strings (mock patch
targets, uvicorn targets), so this walks every syntax tree. It also checks that each package's
pyproject lists the workspace packages and the third-party libraries it imports directly.
"""

from __future__ import annotations

import ast
import sys
import tomllib

import pytest
from brain.config import REPO_ROOT

PACKAGES = {
    "brain": REPO_ROOT / "apps" / "brain",
    "agents": REPO_ROOT / "apps" / "agents",
    "backend": REPO_ROOT / "apps" / "backend",
}
WORKSPACE = set(PACKAGES)
FORBIDDEN_IMPORTS = {"brain": {"agents", "backend"}, "agents": {"backend"}, "backend": set()}
OLD_PATHS = ("brain.agents", "brain.api", "brain.work", "brain.sim")

# Import name -> distribution name, where they differ.
DISTRIBUTION = {
    "yaml": "pyyaml",
    "ruamel": "ruamel-yaml",
    "sse_starlette": "sse-starlette",
    "pydantic_settings": "pydantic-settings",
    "langchain_falkordb": "langchain-falkordb",
}
# Dependencies that are never imported: the server `make api` starts, with its extras.
RUN_ONLY = {"backend": {"uvicorn"}}


def sources(package: str):
    for path in sorted((PACKAGES[package] / package).rglob("*.py")):
        yield path, ast.parse(path.read_text(), filename=str(path))


def imported_modules(tree: ast.AST) -> set[str]:
    """Top-level names of every absolute import in the tree, inside functions too."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def declared(package: str) -> set[str]:
    data = tomllib.loads((PACKAGES[package] / "pyproject.toml").read_text())
    names = set()
    for spec in data["project"]["dependencies"]:
        name = spec.split("[")[0]
        for sep in ">=<~!; ":
            name = name.split(sep)[0]
        names.add(name.lower().replace("_", "-"))
    return names


@pytest.mark.parametrize("package", PACKAGES)
def test_no_import_points_up_the_stack(package):
    bad = [
        f"{path.relative_to(REPO_ROOT)} imports {name}"
        for path, tree in sources(package)
        for name in sorted(imported_modules(tree) & FORBIDDEN_IMPORTS[package])
    ]
    assert not bad, bad


@pytest.mark.parametrize("package", PACKAGES)
def test_no_module_path_names_the_old_layout(package):
    """Mock patch targets and uvicorn targets are strings; none may use a pre-split path."""
    bad = [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.value!r}"
        for path, tree in sources(package)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and node.value.startswith(OLD_PATHS)
    ]
    assert not bad, bad


@pytest.mark.parametrize("package", PACKAGES)
def test_pyproject_lists_what_the_package_imports(package):
    """Workspace packages and libraries imported directly are declared. The `testing.py`
    helpers import pytest, a dev dependency of the workspace root, so they are left out."""
    imports = set()
    for path, tree in sources(package):
        if path.name != "testing.py":
            imports |= imported_modules(tree)
    imports -= {package} | set(sys.stdlib_module_names)
    needed = {DISTRIBUTION.get(name, name).replace("_", "-") for name in imports}
    missing = needed - declared(package)
    assert not missing, f"{package}/pyproject.toml lacks {sorted(missing)}"


@pytest.mark.parametrize("package", PACKAGES)
def test_pyproject_lists_nothing_the_package_does_not_import(package):
    imports = set()
    for _, tree in sources(package):
        imports |= imported_modules(tree)
    used = {DISTRIBUTION.get(name, name).replace("_", "-") for name in imports}
    unused = declared(package) - used - RUN_ONLY.get(package, set())
    assert not unused, f"{package}/pyproject.toml lists {sorted(unused)} but never imports them"
