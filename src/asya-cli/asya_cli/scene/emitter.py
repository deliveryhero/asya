"""
Code emitter for Scene DSL compiler.

Combines all generated code into final Python file.
"""

from asya_cli.scene.ir import ActorCall, Router, SceneIR
from asya_cli.scene.templates import get_file_header, get_resolve_function


class CodeEmitter:
    """Emit final Python code from Scene IR and generated routers."""

    def __init__(self, scene_ir: SceneIR, routers: list[tuple[str, str, str]], source_code: str):
        """
        Initialize code emitter.

        Args:
            scene_ir: Scene intermediate representation
            routers: List of (router_id, docstring, code) tuples
            source_code: Original source code
        """
        self.scene_ir = scene_ir
        self.routers = routers
        self.source_code = source_code

    def emit(self) -> str:
        """
        Generate complete Python file.

        Returns:
            Python source code as string
        """
        sections = []

        # File header
        sections.append(get_file_header(self.scene_ir.source_file))
        sections.append("")

        # Environment variable mappings documentation
        handler_mappings = self._generate_handler_mappings()
        if handler_mappings:
            sections.append("")
            sections.append("# " + "=" * 70)
            sections.append("# Required Environment Variables for Router Deployment")
            sections.append("# " + "=" * 70)
            sections.append('"""')
            sections.append("Set these environment variables when deploying router actors:")
            sections.append("")
            sections.extend(handler_mappings)
            sections.append("")
            sections.append("Example for Kubernetes:")
            sections.append("  env:")
            for mapping in handler_mappings:
                env_name = mapping.split("=")[0]
                env_value = mapping.split("=", 1)[1].strip('"')
                sections.append(f"    - name: {env_name}")
                sections.append(f'      value: "{env_value}"')
            sections.append('"""')
            sections.append("")

        # Generated routers (for kubernetes deployment)
        if self.routers:
            sections.append("")
            sections.append("# " + "=" * 70)
            sections.append("# Generated Routers (for kubernetes deployment)")
            sections.append("# " + "=" * 70)
            sections.append("")

            for _router_id, _docstring, code in self.routers:
                sections.append(code)
                sections.append("")

        # resolve() function
        sections.append("# " + "=" * 70)
        sections.append("# Handler Resolution")
        sections.append("# " + "=" * 70)
        sections.append("")
        sections.append(get_resolve_function())
        sections.append("")

        return "\n".join(sections)

    def _collect_handlers(self, steps: list[ActorCall | Router]) -> set[str]:
        """
        Collect all unique actor qualified names from scene steps.

        Args:
            steps: List of scene steps to scan

        Returns:
            Set of actor qualified names
        """
        handlers = set()

        for step in steps:
            if isinstance(step, ActorCall):
                handlers.add(step.qualified_name)
            elif isinstance(step, Router):
                # Collect ActorCalls from router operations
                for op in step.operations:
                    if isinstance(op, ActorCall):
                        handlers.add(op.qualified_name)

        return handlers

    def _generate_handler_mappings(self) -> list[str]:
        """
        Generate suggested environment variable mappings for all handlers and routers.

        Returns:
            List of env var assignment strings (e.g., 'ASYA_HANDLER_IMAGE_PROCESSOR="module.handler"')
        """
        handlers = self._collect_handlers(self.scene_ir.steps)

        all_names = set(handlers)
        for router_id, _, _ in self.routers:
            all_names.add(router_id)

        if not all_names:
            return []

        mappings = []
        for qualified_name in sorted(all_names):
            # Generate actor name from handler/router name (last component)
            handler_name = qualified_name.split(".")[-1]
            # Convert to UPPER_SNAKE_CASE
            actor_name_upper = handler_name.upper().replace("-", "_")
            env_var = f'ASYA_HANDLER_{actor_name_upper}="{qualified_name}"'
            mappings.append(env_var)

        return mappings
