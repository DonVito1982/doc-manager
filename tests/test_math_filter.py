"""Unit tests for the math_filter module."""

from __future__ import annotations

import json
import sys
from io import StringIO
from unittest.mock import patch

import pytest

from documentos.build.math_filter import (
    _normalize_math,
    _walk_blocks,
    _walk_inlines,
    _walk_node,
    main,
)


class TestNormalizeMath:
    """Tests for the _normalize_math helper."""

    def test_strips_leading_whitespace(self) -> None:
        math_content = [{"t": "InlineMath"}, "  x^2  "]
        _normalize_math(math_content)
        assert math_content[1] == "x^2"

    def test_strips_trailing_newlines(self) -> None:
        math_content = [{"t": "DisplayMath"}, "E=mc^2\n\n"]
        _normalize_math(math_content)
        assert math_content[1] == "E=mc^2"

    def test_no_change_when_stripped(self) -> None:
        math_content = [{"t": "DisplayMath"}, "a + b"]
        _normalize_math(math_content)
        assert math_content[1] == "a + b"

    def test_empty_string(self) -> None:
        math_content = [{"t": "InlineMath"}, "   "]
        _normalize_math(math_content)
        assert math_content[1] == ""

    def test_short_content_list(self) -> None:
        math_content = [{"t": "InlineMath"}]
        _normalize_math(math_content)
        assert len(math_content) == 1

    def test_no_second_string_element(self) -> None:
        math_content = [{"t": "InlineMath"}, 42]
        _normalize_math(math_content)
        assert math_content[1] == 42


class TestWalkNode:
    """Tests for the _walk_node function."""

    def test_math_inline_node(self) -> None:
        node = {"t": "Math", "c": [{"t": "InlineMath"}, "  x^2  "]}
        _walk_node(node)
        assert node["c"][1] == "x^2"

    def test_math_display_node(self) -> None:
        node = {"t": "Math", "c": [{"t": "DisplayMath"}, "  E=mc^2  "]}
        _walk_node(node)
        assert node["c"][1] == "E=mc^2"

    def test_para_with_inline_math(self) -> None:
        para = {
            "t": "Para",
            "c": [
                {"t": "Str", "c": "Hello "},
                {"t": "Math", "c": [{"t": "InlineMath"}, "  x^2  "]},
                {"t": "Space", "c": []},
                {"t": "Str", "c": "world"},
            ],
        }
        _walk_node(para)
        assert para["c"][1]["c"][1] == "x^2"

    def test_nested_block_in_blockquote(self) -> None:
        node = {
            "t": "BlockQuote",
            "c": [
                {
                    "t": "Para",
                    "c": [
                        {"t": "Math", "c": [{"t": "DisplayMath"}, "  E  "]},
                    ],
                }
            ],
        }
        _walk_node(node)
        assert node["c"][0]["c"][0]["c"][1] == "E"

    def test_header_with_math(self) -> None:
        header = {
            "t": "Header",
            "c": [
                2,
                ["header-id", [], []],
                [
                    {"t": "Str", "c": "The "},
                    {
                        "t": "Math",
                        "c": [{"t": "InlineMath"}, "  \\alpha  "],
                    },
                ],
            ],
        }
        _walk_node(header)
        assert header["c"][2][1]["c"][1] == "\\alpha"

    def test_non_dict_node(self) -> None:
        _walk_node("string")  # type: ignore[arg-type]
        _walk_node(None)  # type: ignore[arg-type]
        _walk_node(42)  # type: ignore[arg-type]

    def test_node_without_t_key(self) -> None:
        node = {"c": [{"t": "Str", "c": "content"}]}  # type: ignore[typeddict-unknown-key]
        _walk_node(node)

    def test_node_content_is_dict(self) -> None:
        node = {
            "t": "Div",
            "c": {"inner": {"t": "Math", "c": [{"t": "InlineMath"}, "  x  "]}},
        }
        _walk_node(node)

    def test_node_with_dict_in_c(self) -> None:
        node = {
            "t": "TableCell",
            "c": [
                {"t": "AlignDefault"},
                [
                    {
                        "t": "Plain",
                        "c": [
                            {"t": "Math", "c": [{"t": "InlineMath"}, "  y  "]},
                        ],
                    },
                ],
            ],
        }
        _walk_node(node)
        assert node["c"][1][0]["c"][0]["c"][1] == "y"


class TestWalkBlocks:
    """Tests for the _walk_blocks function."""

    def test_walks_multiple_blocks(self) -> None:
        blocks = [
            {"t": "Para", "c": [{"t": "Str", "c": "Hello"}]},
            {
                "t": "Para",
                "c": [
                    {"t": "Math", "c": [{"t": "InlineMath"}, "  x  "]},
                ],
            },
        ]
        _walk_blocks(blocks)
        assert blocks[1]["c"][0]["c"][1] == "x"

    def test_empty_blocks(self) -> None:
        _walk_blocks([])

    def test_blocks_with_math_at_root(self) -> None:
        blocks = [
            {"t": "Math", "c": [{"t": "DisplayMath"}, "  E=mc^2  "]},
        ]
        _walk_blocks(blocks)
        assert blocks[0]["c"][1] == "E=mc^2"


class TestWalkInlines:
    """Tests for the _walk_inlines function."""

    def test_walks_multiple_inlines(self) -> None:
        inlines = [
            {"t": "Str", "c": "Hello "},
            {"t": "Math", "c": [{"t": "InlineMath"}, "  x^2  "]},
            {"t": "Space", "c": []},
        ]
        _walk_inlines(inlines)
        assert inlines[1]["c"][1] == "x^2"

    def test_empty_inlines(self) -> None:
        _walk_inlines([])


class TestMain:
    """Tests for the main() entry point."""

    def _build_ast(self, blocks: list[dict]) -> dict:
        return {
            "pandoc-api-version": [1, 23],
            "meta": {},
            "blocks": blocks,
        }

    def test_simple_passthrough(self) -> None:
        ast = self._build_ast(
            [
                {"t": "Para", "c": [{"t": "Str", "c": "Hello world"}]},
            ]
        )
        input_json = json.dumps(ast)

        with patch.object(sys, "stdin", StringIO(input_json)):
            with patch.object(sys, "stdout", StringIO()) as mock_stdout:
                main()

        output = json.loads(mock_stdout.getvalue())
        assert output["blocks"] == ast["blocks"]

    def test_normalizes_math_in_para(self) -> None:
        ast = self._build_ast(
            [
                {
                    "t": "Para",
                    "c": [
                        {"t": "Math", "c": [{"t": "InlineMath"}, "  x^2  "]},
                    ],
                },
            ]
        )
        input_json = json.dumps(ast)

        with patch.object(sys, "stdin", StringIO(input_json)):
            with patch.object(sys, "stdout", StringIO()) as mock_stdout:
                main()

        output = json.loads(mock_stdout.getvalue())
        math_elem = output["blocks"][0]["c"][0]
        assert math_elem["c"][1] == "x^2"

    def test_normalizes_display_math(self) -> None:
        ast = self._build_ast(
            [
                {"t": "Math", "c": [{"t": "DisplayMath"}, "  E=mc^2\n  "]},
            ]
        )
        input_json = json.dumps(ast)

        with patch.object(sys, "stdin", StringIO(input_json)):
            with patch.object(sys, "stdout", StringIO()) as mock_stdout:
                main()

        output = json.loads(mock_stdout.getvalue())
        assert output["blocks"][0]["c"][1] == "E=mc^2"

    def test_empty_ast_blocks(self) -> None:
        ast = {"pandoc-api-version": [1, 23], "meta": {}, "blocks": []}
        input_json = json.dumps(ast)

        with patch.object(sys, "stdin", StringIO(input_json)):
            with patch.object(sys, "stdout", StringIO()) as mock_stdout:
                main()

        output = json.loads(mock_stdout.getvalue())
        assert output["blocks"] == []

    def test_malformed_json(self) -> None:
        with patch.object(sys, "stdin", StringIO("not valid json")):
            with pytest.raises(RuntimeError, match="Failed to parse Pandoc AST"):
                main()


class TestIntegration:
    """Integration-style tests for the complete filter pipeline."""

    def test_full_document_with_math(self) -> None:
        ast = {
            "pandoc-api-version": [1, 23],
            "meta": {},
            "blocks": [
                {
                    "t": "Header",
                    "c": [
                        1,
                        ["intro", [], []],
                        [
                            {"t": "Str", "c": "About "},
                            {"t": "Math", "c": [{"t": "InlineMath"}, "  E  "]},
                        ],
                    ],
                },
                {
                    "t": "Para",
                    "c": [
                        {"t": "Str", "c": "The equation "},
                        {
                            "t": "Math",
                            "c": [{"t": "InlineMath"}, "  a^2 + b^2 = c^2  "],
                        },
                        {"t": "Str", "c": " is fundamental."},
                    ],
                },
                {
                    "t": "Math",
                    "c": [{"t": "DisplayMath"}, "  \\int_0^\\infty e^{-x} dx = 1  "],
                },
                {
                    "t": "Para",
                    "c": [
                        {"t": "Str", "c": "Newton's law: "},
                        {
                            "t": "Math",
                            "c": [{"t": "InlineMath"}, "  F = m a  "],
                        },
                    ],
                },
            ],
        }
        input_json = json.dumps(ast)

        with patch.object(sys, "stdin", StringIO(input_json)):
            with patch.object(sys, "stdout", StringIO()) as mock_stdout:
                main()

        output = json.loads(mock_stdout.getvalue())
        blocks = output["blocks"]

        assert blocks[0]["c"][2][1]["c"][1] == "E"
        assert blocks[1]["c"][1]["c"][1] == "a^2 + b^2 = c^2"
        assert blocks[2]["c"][1] == "\\int_0^\\infty e^{-x} dx = 1"
        assert blocks[3]["c"][1]["c"][1] == "F = m a"

    def test_ast_remains_unchanged_without_math(self) -> None:
        ast = {
            "pandoc-api-version": [1, 23],
            "meta": {},
            "blocks": [
                {"t": "Para", "c": [{"t": "Str", "c": "No math here"}]},
                {
                    "t": "CodeBlock",
                    "c": [["python", [], []], "print('hello')"],
                },
            ],
        }
        input_json = json.dumps(ast)

        with patch.object(sys, "stdin", StringIO(input_json)):
            with patch.object(sys, "stdout", StringIO()) as mock_stdout:
                main()

        output = json.loads(mock_stdout.getvalue())
        assert output == ast
