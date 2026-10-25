"""Checks the string catalogs under src/i18n against the code and each other.

Fails on an `S.…` path that no longer resolves, a key missing from or extra to a
translation, a `{placeholder}` set that differs between languages, and a catalog
without its `_language` name. Unused keys are only a warning: a key can be waiting
to be wired.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from _output import fail, fatal, ok, pause, step, warn

ROOT = Path(__file__).resolve().parent.parent
CATALOGS = ROOT / "src" / "i18n"
SOURCE = ROOT / "src"
FALLBACK = "en"
NAME = "_language"

_USE = re.compile(r"\bS((?:\.[A-Za-z_][A-Za-z0-9_]*)+)")
_PLACEHOLDER = re.compile(r"\{(\w+)\}")


def _leaves(node: dict, prefix: str = "") -> dict[str, str]:
    """Flatten to {"a.b.c": "text"}."""
    flat: dict[str, str] = {}
    for key, value in node.items():
        path = f"{prefix}.{key}" if prefix else key
        if isinstance(value, dict):
            flat.update(_leaves(value, path))
        else:
            flat[path] = value
    return flat


def _resolve(catalog: dict, parts: list[str]) -> tuple[str, object, str]:
    """Walk a dotted path; return (matched path, what it landed on, error).

    Landing on a section is allowed: a caller may take a whole subtree and read its
    strings itself."""
    node, walked = catalog, []
    for part in parts:
        if not isinstance(node, dict):
            return ".".join(walked), node, ""  # on a string already: the rest is a method call
        if part not in node:
            return "", None, f"{'.'.join(walked + [part])} does not exist"
        node = node[part]
        walked.append(part)
    return ".".join(walked), node, ""


def main() -> int:
    step("Checking the string catalogs against the code (i18n)")
    catalogs = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(CATALOGS.glob("*.json"))}
    if FALLBACK not in catalogs:
        fatal(f"missing {CATALOGS / (FALLBACK + '.json')}")

    english = {k: v for k, v in catalogs[FALLBACK].items() if k != NAME}
    en_leaves = _leaves(english)
    errors: list[str] = []
    used: set[str] = set()
    sections: set[str] = set()

    for path in sorted(SOURCE.rglob("*.py")):
        if path.parent == CATALOGS:
            continue  # the module that defines S talks about S.__dict__
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in _USE.finditer(line):
                resolved, node, problem = _resolve(english, match.group(1).lstrip(".").split("."))
                if problem:
                    errors.append(f"{path.relative_to(ROOT)}:{line_no}  S.{problem}")
                elif isinstance(node, dict):
                    sections.add(resolved)
                    used.update(_leaves(node, resolved))
                elif resolved:
                    used.add(resolved)

    for code, catalog in catalogs.items():
        if code == FALLBACK:
            continue
        leaves = _leaves({k: v for k, v in catalog.items() if k != NAME})
        for key in sorted(en_leaves.keys() - leaves.keys()):
            errors.append(f"{code}.json  missing key {key}")
        for key in sorted(leaves.keys() - en_leaves.keys()):
            errors.append(f"{code}.json  key {key} absent from {FALLBACK}.json")
        for key in sorted(en_leaves.keys() & leaves.keys()):
            expected = set(_PLACEHOLDER.findall(en_leaves[key]))
            if set(_PLACEHOLDER.findall(leaves[key])) != expected:
                errors.append(f"{code}.json  {key}: placeholders do not match "
                              f"(expected {sorted(expected) or 'none'})")
        if not isinstance(catalog.get(NAME), str) or not catalog[NAME].strip():
            errors.append(f"{code}.json  missing {NAME} (the name shown in the menu)")

    if errors:
        fail("the string catalogs do not match the code", errors)
        return 1

    ok(f"{len(en_leaves)} strings, {len(catalogs)} languages"
       + (f", {len(sections)} taken as sections" if sections else ""))
    unused = sorted(en_leaves.keys() - used)
    if unused:
        warn(f"{len(unused)} unused strings", unused)
        pause()  # an unused string doesn't fail the build, so the build output would bury it
    return 0


if __name__ == "__main__":
    sys.exit(main())
