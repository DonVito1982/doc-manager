"""Pandoc filter for math expression normalisation.

Reads a Pandoc JSON AST from stdin, walks it to find Math elements,
removes duplicate delimiter escapes, and writes the modified AST
back to stdout following the standard Pandoc filter protocol.

The filter runs during Pandoc conversion for all output formats and
is automatically invoked by ``converter.py`` via ``--filter``.
"""

from __future__ import annotations

import json
import sys


def _walk_blocks(blocks: list[dict]) -> None:
    """Recursively walk a list of Pandoc AST blocks."""
    for block in blocks:
        _walk_node(block)


def _walk_inlines(inlines: list[dict]) -> None:
    """Recursively walk a list of Pandoc AST inlines."""
    for inline in inlines:
        _walk_node(inline)


def _walk_node(node: dict) -> None:
    """Walk a single AST node and its children."""
    if not isinstance(node, dict):
        return

    node_type = node.get("t", "")
    node_content = node.get("c", [])

    if node_type == "Math":
        _normalize_math(node_content)
        return

    if isinstance(node_content, list):
        for item in node_content:
            if isinstance(item, dict):
                _walk_node(item)
            elif isinstance(item, list):
                for sub_item in item:
                    if isinstance(sub_item, dict):
                        _walk_node(sub_item)
    elif isinstance(node_content, dict):
        _walk_node(node_content)


def _normalize_math(math_content: list) -> None:
    """Strip leading/trailing whitespace from math content.

    Pandoc Math elements have the form ``[MathType, content]``
    where ``MathType`` is a dict like ``{"t": "DisplayMath"}``
    and ``content`` is the LaTeX expression string.
    """
    if len(math_content) >= 2 and isinstance(math_content[1], str):
        math_content[1] = math_content[1].strip()


def main() -> None:
    """Entry point for the Pandoc filter.

    Reads JSON from stdin, processes Math elements, writes JSON to stdout.
    """
    try:
        ast = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise RuntimeError("Failed to parse Pandoc AST JSON from stdin") from exc

    blocks = ast.get("blocks", [])
    _walk_blocks(blocks)

    json.dump(ast, sys.stdout)


if __name__ == "__main__":
    main()
