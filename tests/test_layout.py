"""Course files go through the course folders (config.COURSE_DIR, SOURCES, RESEARCH, DATA, BUILD, FEATURES, OUTPUT),
never through the repo root or the working directory, so two courses (and the test profile) never share a file."""
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "scripts").glob("*.py"))
# engine files that are shared by every course on purpose
SHARED = {("export_gspro.py", "unity/Editor"), ("readme_table.py", "README.md")}


def _strings(tree):
    """String constants that are not docstrings."""
    docs = {id(n.body[0].value) for n in ast.walk(tree)
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef)) and n.body
            and isinstance(n.body[0], ast.Expr) and isinstance(n.body[0].value, ast.Constant)}
    return [n for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs]


def test_no_script_reaches_course_files_through_the_repo_root():
    bad = []
    for p in SCRIPTS:
        for n in ast.walk(ast.parse(p.read_text())):
            if isinstance(n, ast.BinOp) and isinstance(n.op, ast.Div) and ast.unparse(n.left) in ("C.ROOT", "config.ROOT"):
                target = ast.unparse(n.right).strip("'\"")
                if not any(p.name == f and target.startswith(t) for f, t in SHARED):
                    bad.append(f"{p.name}:{n.lineno} {ast.unparse(n)}")
    assert not bad, bad


def test_no_script_uses_paths_relative_to_the_working_directory():
    bad = [f"{p.name}:{n.lineno} {n.value!r}" for p in SCRIPTS for n in _strings(ast.parse(p.read_text()))
           if n.value.startswith(("build/", "output/", "features/", "research/", "data/", "viewer/views"))]
    assert not bad, bad
