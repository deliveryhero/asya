"""
Intermediate Representation (IR) for Scene DSL.

Terminology:
- Actor: Individual handler function
- Scene: Partial interconnection of actors (compiled from Python DSL)
- Play: Complete interconnection formed from connected scenes or actors

Two-level hierarchy:
1. Scene level (SceneIR.steps): ActorCall | Router
2. Router level (Router.operations): PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall

ActorCall can appear at both levels:
- At scene level: unconditional actor call
- Inside router: conditional actor call (router adds to route based on control flow)

Routers are non-recursive - cannot contain other routers.
"""

import ast
from dataclasses import dataclass, field


@dataclass
class Operation:
    """Base class for all operations."""

    line: int
    col: int


# ======================================================================
# Router-level operations (ONLY inside Router.operations)
# ======================================================================


@dataclass
class PayloadMutation(Operation):
    """
    Mutate payload: p["key"] = value

    Can ONLY appear inside Router.operations.

    Attributes:
        key: Payload key being mutated
        value_str: String representation of value expression
        value_ast: AST node of value expression (for analysis)
    """

    key: str
    value_str: str
    value_ast: ast.expr

    def __str__(self) -> str:
        """Serialize back to parsed syntax (right-hand side only)."""
        return self.value_str


@dataclass
class ClassInstantiation(Operation):
    """
    Class instantiation: var = ClassName(args)

    Can ONLY appear inside Router.operations.

    Attributes:
        var_name: Variable name
        class_name: Class name from code
        qualified_name: Full qualified name
        args: Constructor arguments (AST nodes)
        kwargs: Constructor keyword arguments (AST nodes)
    """

    var_name: str
    class_name: str
    qualified_name: str
    args: list[ast.expr] = field(default_factory=list)
    kwargs: dict[str, ast.expr] = field(default_factory=dict)

    def __str__(self) -> str:
        """Serialize back to parsed syntax."""
        return f'{self.var_name} = {self.class_name}()'


@dataclass
class Label(Operation):
    """
    Label for goto targets.

    Can ONLY appear inside Router.operations.

    Attributes:
        name: Label identifier
    """

    name: str


@dataclass
class ConditionalGoto(Operation):
    """
    Conditional jump: if condition goto true_target else goto false_target

    Can ONLY appear inside Router.operations.

    Attributes:
        condition_str: Condition expression
        condition_ast: AST node of condition (for analysis)
        true_target: Label name to jump to if condition is true
        false_target: Label name to jump to if condition is false (None for fall-through)
    """

    condition_str: str
    condition_ast: ast.expr
    true_target: str
    false_target: str | None = None


@dataclass
class Goto(Operation):
    """
    Unconditional jump to label.

    Can ONLY appear inside Router.operations.

    Attributes:
        target: Target label name
        target_router_id: Resolved router ID to jump to (filled by optimizer)
    """

    target: str
    target_router_id: str | None = None


# ======================================================================
# Flow-level operations (ONLY in SceneIR.operations)
# ======================================================================


@dataclass
class ActorCall(Operation):
    """
    Call an actor - adds actor to the route.

    Can appear in:
    - SceneIR.operations (unconditional actor call)
    - Router.operations (conditional actor call based on control flow)

    Attributes:
        qualified_name: Full qualified name for resolve() (e.g., "my_module.handler")
        display_name: Name for display in diagrams (e.g., "handler")
        continuation_router_id: Optional router to route to after this actor completes
                                (used when there are mutations/operations after actor call)
    """

    qualified_name: str
    display_name: str
    continuation_router_id: str | None = None

    def __str__(self) -> str:
        """Serialize back to parsed syntax (without param context)."""
        return self.display_name


@dataclass
class Router(Operation):
    """
    Router actor - contains control flow, payload mutations, and conditional actor calls.

    Can ONLY appear in SceneIR.operations.

    Represents a generated actor function that can:
    - Perform payload mutations
    - Instantiate helper classes
    - Make routing decisions (if/goto)
    - Conditionally add actors to the route

    Attributes:
        router_id: Unique router identifier
        operations: Flat sequence of router-level operations
        depth: Nesting depth (for display purposes)
    """

    router_id: str
    operations: list[PayloadMutation | ClassInstantiation | Label | ConditionalGoto | Goto | ActorCall]
    depth: int = 0


@dataclass
class SceneIR:
    """
    Complete scene representation.

    A scene is a partial interconnection of actors compiled from Python DSL.

    Attributes:
        name: Scene function name
        param_name: Parameter name (usually "p")
        steps: Sequence of actors (ActorCall | Router)
        source_file: Source file path
        lineno: Function definition line number
        imports: Import statements (AST nodes)
        class_instances: Map of variable names to qualified class names
    """

    name: str
    param_name: str
    steps: list[ActorCall | Router]
    source_file: str
    lineno: int
    imports: list[ast.Import | ast.ImportFrom] = field(default_factory=list)
    class_instances: dict[str, str] = field(default_factory=dict)
