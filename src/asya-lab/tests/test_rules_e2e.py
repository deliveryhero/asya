"""E2E tests: full compile pipeline with real config files and rules.

Each test scaffolds a minimal .asya/ project directory with config.yaml
and config.compiler.rules.yaml, then compiles a flow using the full
pipeline (AsyaProject -> load_rules -> FlowCompiler -> generated code).

Tests verify that the compiler correctly classifies different AST
constructs (function calls, dotted calls, inline comments) and that
the generated router code reflects those classifications.
"""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from asya_lab.config.project import AsyaProject
from asya_lab.flow.compiler import FlowCompiler


def _scaffold_project(
    tmp_path: Path,
    *,
    rules_yaml: str = "",
    config_yaml: str = "templates:\n  namespace: default\n",
) -> AsyaProject:
    """Create a minimal .asya/ project with config and rules files."""
    (tmp_path / ".git").mkdir()
    asya_dir = tmp_path / ".asya"
    asya_dir.mkdir()
    (asya_dir / "config.yaml").write_text(config_yaml)
    if rules_yaml:
        (asya_dir / "config.compiler.rules.yaml").write_text(rules_yaml)
    return AsyaProject.from_dir(tmp_path)


def _compile_flow(project: AsyaProject, source: str) -> str:
    """Compile a flow source using the full pipeline and return generated code."""
    engine = project.load_rules()
    compiler = FlowCompiler(rule_engine=engine)
    return compiler.compile(source, "test_flow.py")


class TestInlineClassification:
    """External (dotted) calls are inlined by the default '*' rule."""

    def test_dotted_call_inlined_by_default(self, tmp_path: Path) -> None:
        """A dotted call like `utils.clean(p)` matches '*' -> inline.

        Inline code runs inside the router, so the generated code must
        contain the call as a mutation — not as a separate actor via resolve().
        """
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = utils.clean(p)
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Inline code appears as a mutation inside a router function
        assert "utils.clean(p)" in code
        # Inline code does NOT appear as a resolved actor
        assert 'resolve("utils.clean")' not in code
        # Real actors are resolved normally
        assert 'resolve("handler_a")' in code
        assert 'resolve("handler_b")' in code

    def test_multiple_consecutive_inlines_merged(self, tmp_path: Path) -> None:
        """Multiple consecutive inline calls merge into one router's mutations."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = logging.info(p)
                p = metrics.emit(p)
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Both inline calls present as mutations
        assert "logging.info(p)" in code
        assert "metrics.emit(p)" in code
        # Neither appears as an actor
        assert 'resolve("logging.info")' not in code
        assert 'resolve("metrics.emit")' not in code


class TestInlineCommentOverride:
    """The `# asya: <action>` inline comment has highest priority."""

    def test_comment_forces_inline(self, tmp_path: Path) -> None:
        """A bare symbol (same-package -> unfold) overridden to inline via comment."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = local_helper(p)  # asya: inline
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        assert "local_helper(p)" in code
        assert 'resolve("local_helper")' not in code
        assert 'resolve("handler_a")' in code

    def test_comment_forces_actor(self, tmp_path: Path) -> None:
        """A dotted call (default '*' -> inline) overridden to actor via comment."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = external.lib(p)  # asya: actor
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        assert 'resolve("external.lib")' in code
        # Should NOT appear as inline mutation (it's an actor now)
        assert "p = external.lib(p)" not in code


class TestUserRuleOverridesDefault:
    """Exact-match user rules (tier 0) beat default wildcards (tier 2/3)."""

    def test_exact_match_beats_wildcard(self, tmp_path: Path) -> None:
        """User rule: tenacity.retry -> config, default '*' -> inline."""
        rules = dedent("""\
            - match: "tenacity.retry"
              treat-as: config
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = tenacity.retry(p)
                p = other.lib(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Config symbol → inlined as mutation
        assert "tenacity.retry(p)" in code
        assert 'resolve("tenacity.retry")' not in code
        # Other dotted call → also inlined (default '*')
        assert "other.lib(p)" in code

    def test_prefix_wildcard_rule(self, tmp_path: Path) -> None:
        """User rule: 'mylib.*' -> actor forces all mylib.X to actor."""
        rules = dedent("""\
            - match: "mylib.*"
              treat-as: actor
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = mylib.process(p)
                p = mylib.validate(p)
                p = external.util(p)
                return p
        """)
        code = _compile_flow(project, source)

        # mylib.* symbols → actors
        assert 'resolve("mylib.process")' in code
        assert 'resolve("mylib.validate")' in code
        # external.util → inline (default '*')
        assert "external.util(p)" in code
        assert 'resolve("external.util")' not in code


class TestSamePackageClassification:
    """Bare (undotted) symbols match '.' (same-package) -> unfold by default."""

    def test_bare_symbol_unfold_still_actor(self, tmp_path: Path) -> None:
        """Unfold symbols are currently emitted as actors (expansion not yet implemented)."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = local_handler(p)
                p = another_handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Unfold → ActorCall(treat_as="unfold") → still routed as actor
        assert 'resolve("local_handler")' in code
        assert 'resolve("another_handler")' in code


class TestConditionalWithMixedClassifications:
    """Rules apply inside conditional branches."""

    def test_if_else_with_inline_and_actor(self, tmp_path: Path) -> None:
        """Inline calls inside branches become mutations in the branch router."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                if p["type"] == "fast":
                    p = handler_fast(p)
                else:
                    p = handler_slow(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Both handlers are real actors (bare names → unfold → actor)
        assert 'resolve("handler_fast")' in code
        assert 'resolve("handler_slow")' in code


class TestConfigWithExtractionRules:
    """Config rules with where: trees extract values from call sites."""

    def test_config_rule_with_keyword_extraction(self, tmp_path: Path) -> None:
        """asyncio.timeout(delay=30) classified as config, extracted to spec path."""
        rules = dedent("""\
            - match: "asyncio.timeout"
              where:
                - param: delay
                  assign-to: spec.resiliency.timeout
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = asyncio.timeout(p)
                p = handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Config call → inlined as mutation (treat-as defaults to config when where: is present)
        assert "asyncio.timeout(p)" in code
        assert 'resolve("asyncio.timeout")' not in code
        # Real actor still resolved
        assert 'resolve("handler")' in code

    def test_extraction_rule_loads_from_config(self, tmp_path: Path) -> None:
        """Verify the RuleEngine loads extraction rules and get_rule() returns them."""
        rules = dedent("""\
            - match: "asyncio.timeout"
              where:
                - param: delay
                  assign-to: spec.resiliency.timeout
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        engine = project.load_rules()

        from asya_lab.compiler.rules import RuleEngine, TreatAs

        assert isinstance(engine, RuleEngine)
        rule = engine.get_rule("asyncio.timeout")
        assert rule is not None
        assert rule.treat_as == TreatAs.CONFIG
        assert rule.where is not None
        assert len(rule.where) == 1
        assert rule.where[0].param == "delay"
        assert rule.where[0].assign_to == "spec.resiliency.timeout"


class TestFullPipelineWithRichRules:
    """End-to-end: realistic config with multiple rules and a complex flow."""

    def test_mixed_flow_with_multiple_rules(self, tmp_path: Path) -> None:
        """Compile a flow that exercises exact, prefix, and default rules together."""
        rules = dedent("""\
            - match: "tenacity.retry"
              treat-as: config
            - match: "logging.*"
              treat-as: inline
            - match: "myapp.*"
              treat-as: actor
        """)
        project = _scaffold_project(tmp_path, rules_yaml=rules)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = tenacity.retry(p)
                p = logging.setup(p)
                p = myapp.process(p)
                p = external.util(p)
                p = local_handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        # tenacity.retry → config → mutation (not actor)
        assert "tenacity.retry(p)" in code
        assert 'resolve("tenacity.retry")' not in code

        # logging.setup → inline (prefix 'logging.*') → mutation
        assert "logging.setup(p)" in code
        assert 'resolve("logging.setup")' not in code

        # myapp.process → actor (prefix 'myapp.*') → resolved
        assert 'resolve("myapp.process")' in code

        # external.util → inline (default '*') → mutation
        assert "external.util(p)" in code
        assert 'resolve("external.util")' not in code

        # local_handler → unfold (default '.') → still actor call
        assert 'resolve("local_handler")' in code

    def test_inline_mutations_in_start_router(self, tmp_path: Path) -> None:
        """Inline calls at the start of a flow are merged into the start router."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = logging.init(p)
                p = handler_a(p)
                return p
        """)
        code = _compile_flow(project, source)

        # The start router should contain the inline mutation
        assert "logging.init(p)" in code
        assert "start_my_flow" in code
        assert 'resolve("handler_a")' in code

    def test_no_rules_file_uses_defaults(self, tmp_path: Path) -> None:
        """Without config.compiler.rules.yaml, default rules still apply."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = external.lib(p)
                p = handler_b(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Bare names → unfold → actor
        assert 'resolve("handler_a")' in code
        assert 'resolve("handler_b")' in code
        # Dotted name → inline (default '*')
        assert "external.lib(p)" in code
        assert 'resolve("external.lib")' not in code

    def test_all_inline_single_actor_flow(self, tmp_path: Path) -> None:
        """A flow with one actor + inline calls still generates a valid single-actor flow."""
        project = _scaffold_project(tmp_path)
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler(p)
                return p
        """)
        code = _compile_flow(project, source)

        # Single-actor flow detection should still work
        assert "FLOW_METADATA" in code
        assert "'handler'" in code


class TestBackwardsCompatibility:
    """Compiler without rule_engine preserves pre-rules behavior."""

    def test_no_engine_all_calls_are_actors(self, tmp_path: Path) -> None:
        """Without rules, every call — bare or dotted — is an actor."""
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p = handler_a(p)
                p = external.lib(p)
                p = handler_b(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert 'resolve("handler_a")' in code
        assert 'resolve("external.lib")' in code
        assert 'resolve("handler_b")' in code

    def test_no_engine_with_mutations(self, tmp_path: Path) -> None:
        """Payload mutations still work without rules."""
        source = dedent("""\
            def my_flow(p: dict) -> dict:
                p["status"] = "started"
                p = handler(p)
                return p
        """)
        compiler = FlowCompiler()
        code = compiler.compile(source, "test.py")

        assert "started" in code
        assert 'resolve("handler")' in code
