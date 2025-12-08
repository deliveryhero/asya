"""
Router code generator for Flow DSL.

Generates router functions from Flow IR.
"""

from asya_cli.scene.ir import (
    Assignment,
    Break,
    ClassInstantiation,
    Continue,
    SceneIR,
    HandlerCall,
    IfBlock,
    Operation,
    WhileLoop,
)


class RouterGenerator:
    """Generate router functions from Flow IR."""

    def __init__(self, flow_ir: SceneIR):
        self.flow_ir = flow_ir
        self.routers: list[tuple[str, str, str]] = []  # (router_id, docstring, code)
        self.inline_block_counter = 0  # Counter for generated inline operation actors

    def generate(self) -> list[tuple[str, str, str]]:
        """
        Generate all router functions.

        Returns:
            List of (router_id, docstring, code) tuples
        """
        self._generate_entrypoint_router()
        self._generate_routers_for_ops(self.flow_ir.operations)
        return self.routers

    def _generate_entrypoint_router(self):
        """Generate entrypoint router for the flow."""
        entrypoint_id = self.flow_ir.name  # entrypoint = same as flow name
        lines = []

        lines.append(f"def {entrypoint_id}(envelope: dict) -> dict:")

        docstring = f"Entrypoint for flow '{self.flow_ir.name}'"
        lines.append(f'    """{docstring}"""')

        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("")

        first_actors = self._collect_actors(self.flow_ir.operations)
        if first_actors:
            actors_list = ", ".join(self._format_actor(a) for a in first_actors)
            lines.append(f"    r['actors'][c+1:c+1] = [{actors_list}]")
        else:
            lines.append("    pass")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((entrypoint_id, docstring, code))

    def _generate_routers_for_ops(self, ops: list[Operation]):
        """Recursively generate routers for all operations."""
        for op in ops:
            if isinstance(op, IfBlock):
                self._generate_if_router(op)
                # Recurse into branches
                self._generate_routers_for_ops(op.then_ops)
                for _, _, elif_ops in op.elif_blocks:
                    self._generate_routers_for_ops(elif_ops)
                self._generate_routers_for_ops(op.else_ops)

            elif isinstance(op, WhileLoop):
                self._generate_while_router(op)
                # Recurse into body
                self._generate_routers_for_ops(op.body_ops)

    def _generate_if_router(self, if_op: IfBlock):
        """Generate router for if statement."""
        assert if_op.router_id is not None  # Should be set by analyzer
        param_name = self.flow_ir.param_name
        lines = []

        # Function signature
        lines.append(f"def {if_op.router_id}(envelope: dict) -> dict:")

        # Docstring
        docstring = self._generate_if_docstring(if_op)
        lines.append(f'    """{docstring}"""')

        # Extract envelope components
        lines.append(f"    {param_name} = envelope['payload']")
        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("")

        # Generate if/elif/else logic
        lines.append(f"    if {if_op.condition_str}:")
        then_actors = self._collect_actors(if_op.then_ops)
        if then_actors:
            actors_list = ", ".join(self._format_actor(a) for a in then_actors)
            lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
        else:
            lines.append("        pass")

        # Generate elif branches
        for _elif_cond_ast, elif_cond_str, elif_ops in if_op.elif_blocks:
            lines.append(f"    elif {elif_cond_str}:")
            elif_actors = self._collect_actors(elif_ops)
            if elif_actors:
                actors_list = ", ".join(self._format_actor(a) for a in elif_actors)
                lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
            else:
                lines.append("        pass")

        # Generate else branch (if exists)
        if if_op.else_ops:
            lines.append("    else:")
            else_actors = self._collect_actors(if_op.else_ops)
            if else_actors:
                actors_list = ", ".join(self._format_actor(a) for a in else_actors)
                lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
            else:
                lines.append("        pass")

        # Add continuation (what comes after this if block)
        continuation_actors = self._collect_actors(if_op.continuation)
        if continuation_actors:
            lines.append("")
            actors_list = ", ".join(self._format_actor(a) for a in continuation_actors)
            lines.append(f"    r['actors'] += [{actors_list}]")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((if_op.router_id, docstring, code))

    def _generate_while_router(self, while_op: WhileLoop):
        """Generate router for while loop."""
        assert while_op.router_id is not None  # Should be set by analyzer
        param_name = self.flow_ir.param_name
        lines = []

        # Function signature
        lines.append(f"def {while_op.router_id}(envelope: dict) -> dict:")

        # Docstring
        docstring = self._generate_while_docstring(while_op)
        lines.append(f'    """{docstring}"""')

        # Extract envelope components
        lines.append(f"    {param_name} = envelope['payload']")
        lines.append("    r = envelope['route']")
        lines.append("    c = r['current']")
        lines.append("")

        # Generate while condition check
        lines.append(f"    if {while_op.condition_str}:")

        # Loop body actors + loop back to self
        body_actors = self._collect_actors(while_op.body_ops)
        if body_actors:
            # Add body actors + self-loop
            actors_list = ", ".join(self._format_actor(a) for a in body_actors)
            lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}, resolve('{while_op.router_id}')]")
        else:
            # Just loop back
            lines.append(f"        r['actors'][c+1:c+1] = [resolve('{while_op.router_id}')]")

        lines.append("    else:")

        # Exit loop, jump to continuation
        continuation_actors = self._collect_actors(while_op.continuation)
        if continuation_actors:
            actors_list = ", ".join(self._format_actor(a) for a in continuation_actors)
            lines.append(f"        r['actors'][c+1:c+1] = [{actors_list}]")
        else:
            # No continuation, empty route (will go to happy-end)
            lines.append("        pass")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        self.routers.append((while_op.router_id, docstring, code))

    def _collect_actors(self, ops: list[Operation]) -> list[str]:
        """
        Collect actor names from operations.

        Groups consecutive inline operations (assignments, class instantiations) into actors.
        Returns list of actor names (either handler names, router IDs, or inline actors).
        Stops at control flow (if/while) since they have their own routers.
        """
        actors = []
        inline_buffer: list[Assignment | ClassInstantiation] = []

        def flush_inline_ops():
            """Generate actor for buffered inline operations and add to actors list."""
            if inline_buffer:
                inline_actor_id = self._generate_inline_actor(inline_buffer[:])
                actors.append(inline_actor_id)
                inline_buffer.clear()

        for op in ops:
            if isinstance(op, Assignment | ClassInstantiation):
                # Buffer inline operation for grouping
                inline_buffer.append(op)

            elif isinstance(op, HandlerCall):
                # Flush any pending inline ops first
                flush_inline_ops()
                # Add handler call
                actors.append(f'resolve("{op.qualified_name}")')

            elif isinstance(op, IfBlock | WhileLoop):
                # Flush any pending inline ops first
                flush_inline_ops()
                # Add router for this control flow
                assert op.router_id is not None  # Should be set by analyzer
                actors.append(op.router_id)
                # Don't recurse - the router will handle branching
                break

            elif isinstance(op, Break):
                # Flush any pending inline ops first
                flush_inline_ops()
                # Break handled by parent router
                break

            elif isinstance(op, Continue):
                # Flush any pending inline ops first
                flush_inline_ops()
                # Continue handled by parent router
                break

            # Skip Return - doesn't generate actors

        # Flush any remaining inline ops
        flush_inline_ops()

        return actors

    def _generate_inline_actor(self, operations: list[Assignment | ClassInstantiation]) -> str:
        """
        Generate an actor that executes a block of inline operations.

        Args:
            operations: List of inline operations (Assignment, ClassInstantiation) to execute

        Returns:
            Actor ID (router name) for this inline block
        """
        import ast

        self.inline_block_counter += 1
        actor_id = f"{self.flow_ir.name}_inline_{self.inline_block_counter}"
        param_name = self.flow_ir.param_name

        lines = []
        lines.append(f"def {actor_id}(envelope: dict) -> dict:")

        # Docstring
        op_count = len(operations)
        first_line = operations[0].line
        last_line = operations[-1].line
        docstring = (
            f"Inline block {self.inline_block_counter} in flow '{self.flow_ir.name}'\n    \n    "
            f"Lines {first_line}-{last_line}: {op_count} operation(s)"
        )
        lines.append(f'    """{docstring}"""')

        # Extract payload
        lines.append(f"    {param_name} = envelope['payload']")
        lines.append("")

        # Generate operation statements
        for op in operations:
            if isinstance(op, Assignment):
                # Assignment: payload["key"] = value
                if op.key:
                    lines.append(f"    {param_name}[{op.key!r}] = {op.value_str}")

            elif isinstance(op, ClassInstantiation):
                # Class instantiation: var = ClassName(args, kwargs)
                args_str = ", ".join(ast.unparse(arg) for arg in op.args)
                kwargs_str = ", ".join(f"{k}={ast.unparse(v)}" for k, v in op.kwargs.items())
                all_args = ", ".join(filter(None, [args_str, kwargs_str]))
                lines.append(f"    {op.var_name} = {op.class_name}({all_args})")

        lines.append("")
        lines.append("    return envelope")

        code = "\n".join(lines)
        docstring_summary = f"Inline block {self.inline_block_counter} ({op_count} operation(s))"
        self.routers.append((actor_id, docstring_summary, code))

        return actor_id

    def _format_actor(self, actor: str) -> str:
        """
        Format actor for inclusion in route list.

        Args:
            actor: Actor string, either already wrapped in resolve() or a router_id

        Returns:
            Formatted actor string with resolve() call
        """
        if actor.startswith("resolve("):
            return actor
        else:
            return f"resolve('{actor}')"

    def _generate_if_docstring(self, if_op: IfBlock) -> str:
        """Generate docstring for if router."""
        lines = [""]
        lines.append(f"Router for if statement in flow '{self.flow_ir.name}' at line {if_op.line}")
        lines.append("")
        lines.append(f"Absolute line: {if_op.line} (from top of {self.flow_ir.source_file})")
        lines.append(f"Nesting level: {if_op.depth}")
        lines.append("")
        lines.append(f"Condition: {if_op.condition_str}")
        lines.append("")
        return "\n    ".join(lines)

    def _generate_while_docstring(self, while_op: WhileLoop) -> str:
        """Generate docstring for while router."""
        lines = [""]
        lines.append(f"Router for while loop at line {while_op.line} in flow '{self.flow_ir.name}'")
        lines.append("")
        lines.append(f"Absolute line: {while_op.line} (from top of {self.flow_ir.source_file})")
        lines.append(f"Nesting level: {while_op.depth}")
        lines.append("")
        lines.append(f"Condition: {while_op.condition_str}")

        if while_op.has_break:
            lines.append("Contains break statement")
        if while_op.has_continue:
            lines.append("Contains continue statement")

        lines.append("")
        return "\n    ".join(lines)
