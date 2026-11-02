---
name: force-heredoc
description: Exactly one source edit via run_command. Use for the patch heredoc or the one verify edit. Do not use for a second edit.
---
Exactly one edit. Run this helper once. Do not call load_skill if the helper is already in the role prompt.

Write and run this helper with run_command. Replace PATH, OLD, NEW from the handoff. Keep OLD and NEW free of backslashes and triple quotes. A line break can be \n inside b\"...\". Non-ASCII bytes need \xNN.

```bash
cat > /tmp/line_fix.py <<'EOF'
path = "PATH"
name = path.replace("\\", "/").split("/")[-1]
parts = path.replace("\\", "/").split("/")
banned = name in {"conftest.py", "pytest.ini", "tox.ini"}
banned = banned or name.startswith("test_") or name.endswith("_test.py")
banned = banned or "tests" in parts or "test" in parts or "testing" in parts
if banned:
    raise SystemExit("protected path")
old = b'''OLD'''
new = b'''NEW'''
f = open(path, "rb")
s = f.read()
f.close()
assert s.count(old) == 1
s = s.replace(old, new, 1)
assert new in s
if path.endswith(".py"):
    import ast
    ast.parse(s.decode("utf-8"))
import shutil
backup = "/tmp/pre_" + path.replace("/", "_")
shutil.copyfile(path, backup)
f = open(path, "wb")
f.write(s)
f.close()
if path.endswith(".py"):
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
    except Exception:
        shutil.copyfile(backup, path)
        raise
print(backup)
EOF
python /tmp/line_fix.py
git diff
```

Exactly one edit. The helper rejects tests/, test/, and testing/, plus test_*.py, *_test.py, and conftest.py, before it reads the file. pyproject.toml and setup.cfg are allowed. pytest.ini and tox.ini stay rejected. It asserts and runs ast.parse before any write. If python /tmp/line_fix.py fails before the backup save, PATH was not written. Do not restore it. Do not run git checkout, except the one verify restore line test -s /tmp/best.diff && git diff > /tmp/repair.diff && git checkout -- . && (git apply /tmp/best.diff || git apply /tmp/repair.diff).

Scratch files go under /tmp only.
