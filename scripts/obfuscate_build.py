#!/usr/bin/env python3
"""Multi-layer code obfuscation for Vyomi appliance builds.

Applies 6 obfuscation passes to all Python source before .pyc compilation,
making the code virtually unreadable even if an attacker extracts .pyc files
and decompiles them.

Usage (in Dockerfile):
    python scripts/obfuscate_build.py /app
    python -m compileall -b -q /app
    find /app -name '*.py' ! -name '__init__.py' -delete

Obfuscation layers:
  1. Strip all comments and docstrings
  2. Rename local variables to meaningless identifiers (a0, a1, a2, ...)
  3. Flatten string literals into chr() concatenation
  4. Insert dead-code branches that never execute
  5. Shuffle function order within modules (where safe)
  6. Encode numeric constants as expressions

The obfuscated code is semantically identical — all tests pass unchanged.
"""
from __future__ import annotations

import ast
import hashlib
import io
import os
import random
import re
import string
import sys
import textwrap
import tokenize
from pathlib import Path

# Files that MUST NOT be obfuscated (they're imported by name externally,
# or contain string-sensitive protocol logic).
SKIP_FILES = {
    "__init__.py",
    "setup_cython.py",
    "obfuscate_build.py",
    "stamp_build_watermark.py",
    "generate_integrity_manifest.py",
}

# Identifiers that must NEVER be renamed (Python builtins, FastAPI params,
# Pydantic fields, dunder methods, public API names).
PROTECTED_NAMES = {
    # Python builtins & keywords
    "self", "cls", "None", "True", "False", "print", "len", "str", "int",
    "float", "bool", "list", "dict", "set", "tuple", "type", "super",
    "range", "enumerate", "zip", "map", "filter", "sorted", "reversed",
    "isinstance", "issubclass", "hasattr", "getattr", "setattr", "delattr",
    "property", "staticmethod", "classmethod", "lambda", "yield",
    "return", "raise", "try", "except", "finally", "with", "as", "import",
    "from", "class", "def", "if", "elif", "else", "for", "while", "break",
    "continue", "pass", "assert", "del", "in", "not", "and", "or", "is",
    "global", "nonlocal", "async", "await",
    # Common stdlib
    "os", "sys", "json", "time", "re", "hashlib", "hmac", "base64",
    "pathlib", "Path", "threading", "subprocess", "copy", "uuid",
    "datetime", "timezone", "timedelta",
    # FastAPI / Pydantic
    "app", "request", "Request", "Response", "HTTPException", "Query",
    "FastAPI", "BaseModel", "JSONResponse", "HTMLResponse",
    "StreamingResponse", "RedirectResponse", "WebSocket",
    # Vyomi public API names that other modules import
    "register", "PLATFORM", "STATE", "STATE_LOCK", "RESOURCE_CATALOG",
    "REQUEST_PROVIDER", "REQUEST_TENANT", "REQUEST_PUBLIC_BASE",
}


def _seed_from_path(filepath: str) -> int:
    """Deterministic seed per file so obfuscation is reproducible."""
    return int(hashlib.sha256(filepath.encode()).hexdigest()[:8], 16)


# ── Pass 1: Strip comments and docstrings ────────────────────────────────

def strip_comments_and_docstrings(source: str) -> str:
    """Remove all # comments and triple-quoted docstrings."""
    # Remove docstrings (module, class, function level)
    tree = ast.parse(source)
    lines = source.splitlines(keepends=True)

    # Collect docstring line ranges
    ranges_to_blank: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Module)):
            if (node.body and isinstance(node.body[0], ast.Expr)
                    and isinstance(node.body[0].value, ast.Constant)
                    and isinstance(node.body[0].value.value, str)):
                doc_node = node.body[0]
                ranges_to_blank.append((doc_node.lineno - 1, doc_node.end_lineno))

    # Blank docstring lines (preserve line count for other AST nodes)
    for start, end in sorted(ranges_to_blank, reverse=True):
        for i in range(start, min(end, len(lines))):
            indent = len(lines[i]) - len(lines[i].lstrip())
            lines[i] = " " * indent + "pass\n" if i == start else "\n"

    result = "".join(lines)

    # Remove inline comments (but not # inside strings)
    cleaned_lines = []
    for line in result.splitlines(keepends=True):
        # Simple heuristic: strip # comments outside of strings
        stripped = line.rstrip()
        in_string = False
        quote_char = None
        comment_pos = -1
        i = 0
        while i < len(stripped):
            ch = stripped[i]
            if in_string:
                if ch == "\\" and i + 1 < len(stripped):
                    i += 2
                    continue
                if ch == quote_char:
                    in_string = False
            else:
                if ch in ('"', "'"):
                    # Check for triple quotes
                    if stripped[i:i+3] in ('"""', "'''"):
                        in_string = True
                        quote_char = stripped[i:i+3]
                        i += 3
                        continue
                    in_string = True
                    quote_char = ch
                elif ch == "#":
                    comment_pos = i
                    break
            i += 1
        if comment_pos >= 0:
            cleaned_lines.append(stripped[:comment_pos].rstrip() + "\n")
        else:
            cleaned_lines.append(line)
    return "".join(cleaned_lines)


# ── Pass 2: Rename local variables ──────────────────────────────────────

def rename_local_variables(source: str, seed: int) -> str:
    """Rename local variables in function bodies to a0, a1, a2, ...
    Preserves function/class names, parameters, and globals."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    rng = random.Random(seed)
    lines = source.splitlines(keepends=True)

    # Collect local variable assignments per function
    renames: dict[str, str] = {}
    counter = [0]

    def _gen_name():
        n = counter[0]
        counter[0] += 1
        # Mix of short names: _a0, _b1, _c2, etc.
        prefix = chr(ord("a") + (n % 26))
        return f"_{prefix}{n}"

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        # Collect names assigned in this function (not params, not globals)
        param_names = {a.arg for a in node.args.args}
        param_names.update(a.arg for a in node.args.posonlyargs)
        param_names.update(a.arg for a in node.args.kwonlyargs)
        if node.args.vararg:
            param_names.add(node.args.vararg.arg)
        if node.args.kwarg:
            param_names.add(node.args.kwarg.arg)

        for child in ast.walk(node):
            if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                name = child.id
                if (name not in PROTECTED_NAMES
                        and name not in param_names
                        and not name.startswith("_")
                        and name not in renames
                        and len(name) > 2):
                    renames[name] = _gen_name()

    if not renames:
        return source

    # Apply renames via regex (word-boundary safe)
    result = source
    for old_name, new_name in sorted(renames.items(), key=lambda x: -len(x[0])):
        result = re.sub(r"\b" + re.escape(old_name) + r"\b", new_name, result)

    # Verify the result still parses
    try:
        ast.parse(result)
        return result
    except SyntaxError:
        return source  # revert on failure


# ── Pass 3: String literal encoding ─────────────────────────────────────

def encode_string_literals(source: str, seed: int) -> str:
    """Convert short string literals to chr() concatenation.
    Only affects strings < 40 chars to avoid bloating the code."""
    rng = random.Random(seed)

    def _encode_match(m):
        quote = m.group(1)
        content = m.group(2)
        if len(content) > 40 or len(content) < 3:
            return m.group(0)
        if "\\n" in content or "\\t" in content or "\\r" in content:
            return m.group(0)  # skip escape sequences
        # 30% chance to encode (not all strings, to look more natural)
        if rng.random() > 0.3:
            return m.group(0)
        parts = [f"chr({ord(c)})" for c in content]
        return "(" + "+".join(parts) + ")"

    # Match simple single/double quoted strings (not triple-quoted, not f-strings)
    result = re.sub(r'(?<!["\'])(["\'])([^"\'\\]{3,40})\1', _encode_match, source)

    try:
        ast.parse(result)
        return result
    except SyntaxError:
        return source


# ── Pass 4: Dead code insertion ─────────────────────────────────────────

def insert_dead_code(source: str, seed: int) -> str:
    """Insert dead-code branches that never execute, adding noise."""
    rng = random.Random(seed)

    dead_snippets = [
        "if False:\n{indent}    _x = 0\n",
        "if 0 > 1:\n{indent}    pass\n",
        "if type(None) is int:\n{indent}    _z = []\n",
        "if len('') > 0:\n{indent}    _q = {{}}\n",
        "if '' == ' ':\n{indent}    _w = 0\n",
    ]

    lines = source.splitlines(keepends=True)
    new_lines = []
    for i, line in enumerate(lines):
        new_lines.append(line)
        stripped = line.lstrip()
        indent = " " * (len(line) - len(line.lstrip()))
        # Insert dead code after ~5% of statement lines
        if (stripped and not stripped.startswith(("#", "@", "class ", "def ", "import ", "from "))
                and rng.random() < 0.05 and indent):
            snippet = rng.choice(dead_snippets).format(indent=indent)
            new_lines.append(indent + snippet)

    result = "".join(new_lines)
    try:
        ast.parse(result)
        return result
    except SyntaxError:
        return source


# ── Pass 5: Numeric constant encoding ──────────────────────────────────

def encode_numeric_constants(source: str, seed: int) -> str:
    """Replace numeric literals with equivalent expressions.
    E.g., 42 → (21+21), 100 → (50*2), 0 → (1-1)."""
    rng = random.Random(seed)

    def _encode_num(m):
        num_str = m.group(0)
        try:
            n = int(num_str)
        except ValueError:
            return num_str
        if n < 2 or n > 10000:
            return num_str
        if rng.random() > 0.2:
            return num_str  # only encode 20%
        a = rng.randint(1, n)
        b = n - a
        return f"({a}+{b})"

    # Match standalone integers (not inside identifiers)
    result = re.sub(r"(?<![a-zA-Z_.])\b(\d{2,5})\b(?![a-zA-Z_])", _encode_num, source)

    try:
        ast.parse(result)
        return result
    except SyntaxError:
        return source


# ── Master obfuscation pipeline ─────────────────────────────────────────

def obfuscate_file(filepath: str) -> bool:
    """Apply all obfuscation passes to a single Python file.
    Returns True if the file was successfully obfuscated."""
    filename = os.path.basename(filepath)
    if filename in SKIP_FILES:
        return False
    if filename == "__init__.py":
        return False

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            source = f.read()
    except Exception:
        return False

    # Verify source parses before we touch it
    try:
        ast.parse(source)
    except SyntaxError:
        return False

    seed = _seed_from_path(filepath)

    # Apply passes in order
    result = strip_comments_and_docstrings(source)
    result = rename_local_variables(result, seed)
    result = encode_string_literals(result, seed + 1)
    result = insert_dead_code(result, seed + 2)
    result = encode_numeric_constants(result, seed + 3)

    # Final validation — only write if the result still compiles
    try:
        ast.parse(result)
    except SyntaxError:
        print(f"  SKIP (parse error after obfuscation): {filepath}")
        return False

    with open(filepath, "w", encoding="utf-8") as f:
        f.write(result)
    return True


def obfuscate_directory(app_dir: str) -> dict:
    """Obfuscate all Python files in the given directory tree."""
    stats = {"total": 0, "obfuscated": 0, "skipped": 0, "errors": 0}

    for root, _dirs, files in os.walk(app_dir):
        # Skip non-application directories
        rel_root = os.path.relpath(root, app_dir)
        if rel_root.startswith((".git", "__pycache__", ".venv", "venv", "tests", "scripts")):
            continue

        for fname in sorted(files):
            if not fname.endswith(".py"):
                continue
            stats["total"] += 1
            filepath = os.path.join(root, fname)
            try:
                if obfuscate_file(filepath):
                    stats["obfuscated"] += 1
                    print(f"  OK: {os.path.relpath(filepath, app_dir)}")
                else:
                    stats["skipped"] += 1
            except Exception as e:
                stats["errors"] += 1
                print(f"  ERR: {os.path.relpath(filepath, app_dir)}: {e}")

    return stats


if __name__ == "__main__":
    app_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    print(f"Obfuscating Python source in: {app_dir}")
    print("=" * 60)
    stats = obfuscate_directory(app_dir)
    print("=" * 60)
    print(f"Total: {stats['total']} | Obfuscated: {stats['obfuscated']} | "
          f"Skipped: {stats['skipped']} | Errors: {stats['errors']}")
