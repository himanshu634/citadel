"""The three packages keep their dependency direction: backend -> agents -> brain.

Why: the split only means something while brain stays free of the agents and the server. Plain
import greps miss imports inside functions and module paths written as strings (mock patch
targets, uvicorn targets), so this walks every syntax tree. It also checks that each package's
pyproject lists the workspace packages and the third-party libraries it imports directly.
The import and string checks cover each package's tests too, and production code never
imports the pytest helpers (`<package>.testing`).
"""

from __future__ import annotations

import ast
import re
import sys
import tomllib
from pathlib import Path

import pytest

# Not brain.config.REPO_ROOT: the test must not depend on the code it guards.
REPO_ROOT = Path(__file__).resolve().parents[3]
THIS_FILE = Path(__file__).resolve()

PACKAGES = {
    "brain": REPO_ROOT / "apps" / "brain",
    "agents": REPO_ROOT / "apps" / "agents",
    "backend": REPO_ROOT / "apps" / "backend",
}
WORKSPACE = set(PACKAGES)
FORBIDDEN_IMPORTS = {"brain": {"agents", "backend"}, "agents": {"backend"}, "backend": set()}
# Module paths from before the split, and strings that point up the stack (`backend:app`).
OLD_PATHS = re.compile(r"^brain\.(agents|api|work|sim|acl|llm|registry|jobs|onboard|config_diff)\b")
UP_STRINGS = {
    "brain": re.compile(r"^(agents|backend)[.:]"),
    "agents": re.compile(r"^backend[.:]"),
    "backend": None,
}
TESTING_MODULES = {f"{name}.testing" for name in PACKAGES}

# Import name -> distribution name, where they differ.
DISTRIBUTION = {
    "yaml": "pyyaml",
    "dotenv": "python-dotenv",
    "ruamel": "ruamel-yaml",
    "sse_starlette": "sse-starlette",
    "pydantic_settings": "pydantic-settings",
    "langchain_falkordb": "langchain-falkordb",
}
# Dependencies that are never imported: the server `make api` starts, with its extras.
RUN_ONLY = {"backend": {"uvicorn"}}


def parse_all(root: Path):
    paths = sorted(p for p in root.rglob("*.py") if p.resolve() != THIS_FILE)
    assert paths, f"no .py files under {root}: the scan would pass vacuously"
    return [(path, ast.parse(path.read_text(), filename=str(path))) for path in paths]


def sources(package: str):
    """The package's production modules."""
    return parse_all(PACKAGES[package] / package)


def scan_tests(package: str):
    """The package's tests."""
    return parse_all(PACKAGES[package] / "tests")


def everything(package: str):
    return sources(package) + scan_tests(package)


def imported_names(tree: ast.AST) -> set[str]:
    """Dotted names of every import in the tree, inside functions too; relative imports are
    written with a leading dot."""
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found |= {alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            found.add(base)
            joiner = "" if base.endswith(".") or not base else "."
            found |= {f"{base}{joiner}{alias.name}" for alias in node.names}
    return found


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
        for path, tree in everything(package)
        for name in sorted(imported_modules(tree) & FORBIDDEN_IMPORTS[package])
    ]
    assert not bad, bad


@pytest.mark.parametrize("package", PACKAGES)
def test_production_code_never_imports_the_test_helpers(package):
    bad = [
        f"{path.relative_to(REPO_ROOT)} imports {name}"
        for path, tree in sources(package)
        if path.name != "testing.py"
        for name in sorted(imported_names(tree))
        if name in TESTING_MODULES or name.lstrip(".") == "testing"
    ]
    assert not bad, bad


@pytest.mark.parametrize("package", PACKAGES)
def test_no_module_path_names_the_old_layout(package):
    """Mock patch targets and uvicorn targets are strings; none may use a pre-split path or
    name a package above this one."""
    up = UP_STRINGS[package]
    bad = [
        f"{path.relative_to(REPO_ROOT)}:{node.lineno} {node.value!r}"
        for path, tree in everything(package)
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and (OLD_PATHS.match(node.value) or (up and up.match(node.value)))
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
