"""Unit tests for try-except grouper support."""

from asya_lab.flow.grouper import OperationGrouper
from asya_lab.flow.ir import ActorCall, ExceptHandler, IROperation, Mutation, Return, TryExcept


class TestTryExceptRouterCreation:
    """Test basic router generation for try-except blocks."""

    def test_simple_try_except_creates_routers(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_enter_routers = [r for r in routers if r.is_try_enter]
        try_exit_routers = [r for r in routers if r.is_try_exit]
        except_dispatch_routers = [r for r in routers if r.is_except_dispatch]
        reraise_routers = [r for r in routers if r.is_reraise]

        assert len(try_enter_routers) == 1
        assert len(try_exit_routers) == 1
        assert len(except_dispatch_routers) == 1
        assert len(reraise_routers) == 1

    def test_try_except_with_bare_except_no_reraise(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=None,
                        body=[ActorCall(lineno=4, name="catch_all_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        reraise_routers = [r for r in routers if r.is_reraise]
        assert len(reraise_routers) == 0

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        assert except_dispatch.reraise_name is None

    def test_try_except_finally_creates_all_routers(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["RuntimeError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[ActorCall(lineno=5, name="cleanup_handler")],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_enter_routers = [r for r in routers if r.is_try_enter]
        try_exit_routers = [r for r in routers if r.is_try_exit]
        except_dispatch_routers = [r for r in routers if r.is_except_dispatch]
        reraise_routers = [r for r in routers if r.is_reraise]

        assert len(try_enter_routers) == 1
        assert len(try_exit_routers) == 1
        assert len(except_dispatch_routers) == 1
        assert len(reraise_routers) == 1

        # Verify finally actors are present
        try_exit = try_exit_routers[0]
        assert "cleanup_handler" in try_exit.finally_actors

        except_dispatch = except_dispatch_routers[0]
        assert "cleanup_handler" in except_dispatch.finally_actors


class TestTryEnterRouter:
    """Test try_enter router properties."""

    def test_try_enter_has_except_dispatch_name(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_enter = next(r for r in routers if r.is_try_enter)
        except_dispatch = next(r for r in routers if r.is_except_dispatch)

        assert try_enter.except_dispatch_name is not None
        assert try_enter.except_dispatch_name == except_dispatch.name

    def test_try_enter_body_actors(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[
                    ActorCall(lineno=2, name="step_one"),
                    ActorCall(lineno=3, name="step_two"),
                ],
                handlers=[
                    ExceptHandler(
                        lineno=4,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=5, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_enter = next(r for r in routers if r.is_try_enter)
        try_exit = next(r for r in routers if r.is_try_exit)

        assert "step_one" in try_enter.true_branch_actors
        assert "step_two" in try_enter.true_branch_actors
        assert try_exit.name in try_enter.true_branch_actors
        # Regression: try_exit must appear exactly once (not duplicated by convergence label + explicit append)
        assert try_enter.true_branch_actors.count(try_exit.name) == 1


class TestTryExitRouter:
    """Test try_exit router properties."""

    def test_try_exit_has_finally_actors(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[
                    ActorCall(lineno=5, name="cleanup_one"),
                    ActorCall(lineno=6, name="cleanup_two"),
                ],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_exit = next(r for r in routers if r.is_try_exit)
        assert "cleanup_one" in try_exit.finally_actors
        assert "cleanup_two" in try_exit.finally_actors

    def test_try_exit_has_continuation_actors(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            ActorCall(lineno=5, name="after_try"),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_exit = next(r for r in routers if r.is_try_exit)
        assert "after_try" in try_exit.continuation_actors

    def test_try_exit_without_finally(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_exit = next(r for r in routers if r.is_try_exit)
        assert try_exit.finally_actors == []


class TestExceptDispatchRouter:
    """Test except_dispatch router properties."""

    def test_except_dispatch_has_handlers(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="val_handler")],
                    ),
                    ExceptHandler(
                        lineno=5,
                        error_types=["TypeError"],
                        body=[ActorCall(lineno=6, name="type_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        assert except_dispatch.exception_handlers is not None
        assert len(except_dispatch.exception_handlers) == 2

    def test_except_dispatch_handler_error_types(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError", "KeyError"],
                        body=[ActorCall(lineno=4, name="val_key_handler")],
                    ),
                    ExceptHandler(
                        lineno=5,
                        error_types=["RuntimeError"],
                        body=[ActorCall(lineno=6, name="runtime_handler")],
                    ),
                    ExceptHandler(
                        lineno=7,
                        error_types=None,
                        body=[ActorCall(lineno=8, name="catch_all")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=9),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        handlers = except_dispatch.exception_handlers
        assert handlers is not None

        assert handlers[0].error_types == ["ValueError", "KeyError"]
        assert handlers[1].error_types == ["RuntimeError"]
        assert handlers[2].error_types is None

    def test_except_dispatch_handler_actors(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[
                            ActorCall(lineno=4, name="val_handler_step1"),
                            ActorCall(lineno=5, name="val_handler_step2"),
                        ],
                    ),
                    ExceptHandler(
                        lineno=6,
                        error_types=["TypeError"],
                        body=[ActorCall(lineno=7, name="type_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=8),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        handlers = except_dispatch.exception_handlers
        assert handlers is not None

        assert "val_handler_step1" in handlers[0].actors
        assert "val_handler_step2" in handlers[0].actors
        assert "type_handler" in handlers[1].actors

    def test_except_dispatch_has_reraise_for_typed_handlers(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="val_handler")],
                    ),
                    ExceptHandler(
                        lineno=5,
                        error_types=["TypeError"],
                        body=[ActorCall(lineno=6, name="type_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        reraise = next(r for r in routers if r.is_reraise)

        assert except_dispatch.reraise_name is not None
        assert except_dispatch.reraise_name == reraise.name

    def test_except_dispatch_no_reraise_for_bare_except(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="val_handler")],
                    ),
                    ExceptHandler(
                        lineno=5,
                        error_types=None,
                        body=[ActorCall(lineno=6, name="catch_all")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        assert except_dispatch.reraise_name is None

        reraise_routers = [r for r in routers if r.is_reraise]
        assert len(reraise_routers) == 0

    def test_except_dispatch_finally_actors(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[
                    ActorCall(lineno=5, name="finally_cleanup"),
                ],
            ),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        assert "finally_cleanup" in except_dispatch.finally_actors

    def test_except_dispatch_continuation_actors(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            ActorCall(lineno=5, name="post_try_actor"),
            Return(lineno=6),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        except_dispatch = next(r for r in routers if r.is_except_dispatch)
        assert "post_try_actor" in except_dispatch.continuation_actors


class TestTryExceptWithContinuation:
    """Test try-except interaction with continuation code."""

    def test_code_after_try_becomes_continuation(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            ActorCall(lineno=5, name="continuation_actor"),
            ActorCall(lineno=6, name="another_continuation"),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_exit = next(r for r in routers if r.is_try_exit)
        except_dispatch = next(r for r in routers if r.is_except_dispatch)

        assert "continuation_actor" in try_exit.continuation_actors
        assert "another_continuation" in try_exit.continuation_actors

        assert "continuation_actor" in except_dispatch.continuation_actors
        assert "another_continuation" in except_dispatch.continuation_actors

    def test_try_followed_by_return(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=5),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_exit = next(r for r in routers if r.is_try_exit)
        except_dispatch = next(r for r in routers if r.is_except_dispatch)

        assert "end_flow" in try_exit.continuation_actors
        assert "end_flow" in except_dispatch.continuation_actors


class TestTryExceptEdgeCases:
    """Test edge cases for try-except grouping."""

    def test_try_counter_increments(self):
        ops: list[IROperation] = [
            TryExcept(
                lineno=1,
                body=[ActorCall(lineno=2, name="risky_one")],
                handlers=[
                    ExceptHandler(
                        lineno=3,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=4, name="handler_one")],
                    ),
                ],
                finally_body=[],
            ),
            TryExcept(
                lineno=5,
                body=[ActorCall(lineno=6, name="risky_two")],
                handlers=[
                    ExceptHandler(
                        lineno=7,
                        error_types=["TypeError"],
                        body=[ActorCall(lineno=8, name="handler_two")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=9),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        try_enter_routers = [r for r in routers if r.is_try_enter]
        assert len(try_enter_routers) == 2
        assert try_enter_routers[0].name != try_enter_routers[1].name

        # Check that names contain different IDs (0 and 1)
        assert "_try_enter_0" in try_enter_routers[0].name
        assert "_try_enter_1" in try_enter_routers[1].name

    def test_try_except_with_mutations_before(self):
        ops: list[IROperation] = [
            Mutation(lineno=1, code='p["status"] = "starting"'),
            Mutation(lineno=2, code='p["retries"] = 0'),
            TryExcept(
                lineno=3,
                body=[ActorCall(lineno=4, name="risky_handler")],
                handlers=[
                    ExceptHandler(
                        lineno=5,
                        error_types=["ValueError"],
                        body=[ActorCall(lineno=6, name="error_handler")],
                    ),
                ],
                finally_body=[],
            ),
            Return(lineno=7),
        ]
        grouper = OperationGrouper("flow", ops)
        routers = grouper.group()

        # Mutations before try are merged into start
        start = routers[0]
        assert start.name == "start_flow"
        assert len(start.mutations) == 2
        assert start.mutations[0].code == 'p["status"] = "starting"'
        assert start.mutations[1].code == 'p["retries"] = 0'

        # The start router should route to the try_enter
        try_enter = next(r for r in routers if r.is_try_enter)
        assert try_enter.name in start.true_branch_actors
