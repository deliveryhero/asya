"""
Intermediate Representation (IR) for Flow DSL.

Lower-level IR focused on actor routing primitives rather than Python constructs.
"""

import ast
from dataclasses import dataclass, field


@dataclass
class Operation:
    """Base class for all flow operations."""

    line: int
    col: int


@dataclass
class ActorCall(Operation):
    """
    Call an actor - adds actor to the route.

    Attributes:
        qualified_name: Full qualified name for resolve() (e.g., "my_module.handler")
        display_name: Name for display in diagrams (e.g., "handler")
    """

    qualified_name: str
    display_name: str


@dataclass
class PayloadMutation(Operation):
    """
    Mutate payload: p["key"] = value

    Attributes:
        key: Payload key being mutated
        value_str: String representation of value expression
        value_ast: AST node of value expression (for analysis)
    """

    key: str
    value_str: str
    value_ast: ast.expr


@dataclass
class ClassInstantiation(Operation):
    """
    Class instantiation: var = ClassName(args)

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


@dataclass
class ConditionalGoto(Operation):
    """
    Conditional jump: if condition goto label_true else goto label_false

    Attributes:
        condition_str: Condition expression
        condition_ast: AST node of condition (for analysis)
        true_target: Label to jump to if condition is true
        false_target: Label to jump to if condition is false (None for fall-through)
    """

    condition_str: str
    condition_ast: ast.expr
    true_target: str
    false_target: str | None = None


@dataclass
class Label(Operation):
    """
    Label for goto targets.

    Attributes:
        name: Label identifier
    """

    name: str


@dataclass
class Goto(Operation):
    """
    Unconditional jump to label.

    Attributes:
        target: Target label name
    """

    target: str


@dataclass
class ReturnPayload(Operation):
    """Return from flow (ends routing)."""

    pass


@dataclass
class Router(Operation):
    """
    Router actor - contains operations and control flow.

    Represents a generated actor function that can:
    - Perform payload mutations
    - Make routing decisions (if/goto)
    - Call other actors

    Attributes:
        router_id: Unique router identifier
        operations: Sequence of operations (mutations, calls, gotos, labels)
        continuation: Operations that come after this router
        depth: Nesting depth
    """

    router_id: str
    operations: list[Operation]
    continuation: list[Operation] = field(default_factory=list)
    depth: int = 0


@dataclass
class FlowIR:
    """
    Complete flow representation.

    Attributes:
        name: Flow function name
        param_name: Parameter name (usually "p")
        operations: Sequential operations
        source_file: Source file path
        lineno: Function definition line number
        imports: Import statements (AST nodes)
        class_instances: Map of variable names to qualified class names
    """

    name: str
    param_name: str
    operations: list[Operation]
    source_file: str
    lineno: int
    imports: list[ast.Import | ast.ImportFrom] = field(default_factory=list)
    class_instances: dict[str, str] = field(default_factory=dict)
