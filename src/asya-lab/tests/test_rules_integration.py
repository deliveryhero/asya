"""Integration test: full compile pipeline with rules engine."""

from pathlib import Path
from textwrap import dedent

from asya_lab.compiler.rules import RuleEngine, TreatAs
from asya_lab.config.project import AsyaProject
from asya_lab.flow.compiler import FlowCompiler
from asya_lab.flow.ir import InlineCode
from asya_lab.flow.parser import FlowParser


class TestCompileWithRules:
    def test_inline_comment_excludes_from_actors(self) -> None:
        source = """\
def my_flow(p: dict) -> dict:
    p = handler_a(p)
    p = uuid4(p)  # asya: inline
    p = handler_b(p)
    return p
"""
        engine = RuleEngine.with_defaults()
        compiler = FlowCompiler(rule_engine=engine)
        code = compiler.compile(source, "test.py")
        assert "handler_a" in code
        assert "handler_b" in code

    def test_default_rules_classify_external_as_inline(self) -> None:
        source = """\
def my_flow(p: dict) -> dict:
    p = handler_a(p)
    return p
"""
        engine = RuleEngine.with_defaults()
        compiler = FlowCompiler(rule_engine=engine)
        code = compiler.compile(source, "test.py")
        assert "handler_a" in code

    def test_compile_without_rules_backwards_compatible(self) -> None:
        source = """\
def my_flow(p: dict) -> dict:
    p = handler_a(p)
    p = handler_b(p)
    return p
"""
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")
        assert "handler_a" in code
        assert "handler_b" in code


class TestLoadRulesFromConfig:
    def test_load_rules_from_project(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("templates:\n  namespace: default\n")
        (asya_dir / "config.compiler.rules.yaml").write_text('- match: "my_lib.helper"\n  treat-as: inline\n')
        project = AsyaProject.from_dir(tmp_path)
        engine = project.load_rules()
        result = engine.classify("my_lib.helper")
        assert result == TreatAs.INLINE

    def test_load_rules_with_extraction(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        (asya_dir / "config.compiler.rules.yaml").write_text(
            '- match: "asyncio.timeout"\n  where:\n    - param: delay\n      assign-to: spec.resiliency.timeout\n'
        )
        project = AsyaProject.from_dir(tmp_path)
        engine = project.load_rules()
        rule = engine.get_rule("asyncio.timeout")
        assert rule is not None
        assert rule.where is not None
        assert rule.treat_as == TreatAs.CONFIG

    def test_load_rules_empty_config(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        project = AsyaProject.from_dir(tmp_path)
        engine = project.load_rules()
        # Bare symbol matches "." (same-package) → unfold
        assert engine.classify("something") == TreatAs.UNFOLD
        # Dotted external symbol matches "*" → inline
        assert engine.classify("external.lib") == TreatAs.INLINE

    def test_user_rule_overrides_default(self, tmp_path: Path) -> None:
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        (asya_dir / "config.compiler.rules.yaml").write_text('- match: "tenacity.retry"\n  treat-as: config\n')
        project = AsyaProject.from_dir(tmp_path)
        engine = project.load_rules()
        # User rule: exact match beats wildcard default
        assert engine.classify("tenacity.retry") == TreatAs.CONFIG
        # Default still works for unmatched external
        assert engine.classify("external.lib") == TreatAs.INLINE

    def test_config_extraction_carried_through_parser(self, tmp_path: Path) -> None:
        """Config rule with where: tree produces InlineCode with extracted_values.

        Uses keyword arg ``timeout=30`` which doesn't collide with the
        mandatory ``p`` positional arg.
        """
        (tmp_path / ".git").mkdir()
        asya_dir = tmp_path / ".asya"
        asya_dir.mkdir()
        (asya_dir / "config.yaml").write_text("{}")
        (asya_dir / "config.compiler.rules.yaml").write_text(
            dedent("""\
                - match: "my_lib.configure"
                  where:
                    - param: timeout
                      assign-to: spec.resiliency.timeout
            """)
        )
        project = AsyaProject.from_dir(tmp_path)
        engine = project.load_rules()

        source = dedent("""\
            async def my_flow(p: dict) -> dict:
                p = my_lib.configure(p, timeout=30)
                p = handler(p)
                return p
        """)
        parser = FlowParser(source, "test.py", rule_engine=engine)
        _, operations = parser.parse()

        inline_ops = [op for op in operations if isinstance(op, InlineCode)]
        assert len(inline_ops) == 1, f"Expected 1 InlineCode, got {len(inline_ops)}: {operations}"
        assert inline_ops[0].extracted_values == {"spec.resiliency.timeout": 30}, inline_ops[0].extracted_values
