"""Static checks for the scripts that can't be imported here (the Kokoro server needs its venv)."""
import ast
import builtins
import pathlib
import unittest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"


def undefined_names(path):
    """Names read somewhere in the file but never bound anywhere in it (a coarse NameError check)."""
    tree = ast.parse(path.read_text())
    bound = set(dir(builtins))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound.add(node.name)
        elif isinstance(node, ast.Import):
            bound |= {a.asname or a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            bound |= {a.asname or a.name for a in node.names}
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            bound.add(node.id)
        elif isinstance(node, ast.arg):
            bound.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
    used = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load)}
    return sorted(used - bound)


class Static(unittest.TestCase):
    def test_no_undefined_names(self):
        for script in sorted(SCRIPTS.glob("*.py")):
            with self.subTest(script=script.name):
                self.assertEqual(undefined_names(script), [])


if __name__ == "__main__":
    unittest.main()
