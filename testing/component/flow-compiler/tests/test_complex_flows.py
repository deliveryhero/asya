"""Test complex real-world flow patterns."""

import textwrap
import pytest

from asya_lab.flow import FlowCompiler


class TestCodeQuality:
    """Test that generated code meets quality standards."""

    def test_no_syntax_errors_in_complex_flow(self):
        source = textwrap.dedent("""
            @flow
            def flow(p: dict) -> dict:
                p["init"] = True
                p = setup(p)

                if p["type"] == "A":
                    p["branch"] = "A"
                    if p["subtype"] == "1":
                        p = handler_a1(p)
                    else:
                        p = handler_a2(p)
                elif p["type"] == "B":
                    p["branch"] = "B"
                    p = handler_b(p)
                else:
                    p["branch"] = "default"

                p = finalize(p)
                p["complete"] = True
                return p

            def setup(p: dict) -> dict:
                return p
            def handler_a1(p: dict) -> dict:
                return p
            def handler_a2(p: dict) -> dict:
                return p
            def handler_b(p: dict) -> dict:
                return p
            def finalize(p: dict) -> dict:
                return p
        """)

        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        try:
            compile(code, "test.py", "exec")
        except SyntaxError as e:
            pytest.fail(f"Generated code has syntax errors: {e}")
