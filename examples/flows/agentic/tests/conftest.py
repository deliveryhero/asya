"""
Pytest configuration for agentic flow handler tests.

Adds the necessary paths so flow modules and asya_testing can be imported
without installation, matching how users would write tests against their
own handler code.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

# Flow modules (routing_classifier.py, sequential_pipeline.py, …)
_AGENTIC_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(_AGENTIC_DIR))

# asya_testing source (not installed, referenced directly from the monorepo)
# _AGENTIC_DIR = examples/flows/agentic  →  .parent³ = repo worktree root
_ASYA_TESTING_SRC = _AGENTIC_DIR.parent.parent.parent / "src" / "asya-testing"
sys.path.insert(0, str(_ASYA_TESTING_SRC))

# Import just handler.py by path to avoid triggering asya_testing's heavy
# package __init__ (which pulls in google-cloud, aio-pika, etc.).
_handler_spec = importlib.util.spec_from_file_location(
    "asya_testing.fixtures.handler",
    str(_ASYA_TESTING_SRC / "asya_testing" / "fixtures" / "handler.py"),
)
_handler_mod = importlib.util.module_from_spec(_handler_spec)  # type: ignore[arg-type]
_handler_spec.loader.exec_module(_handler_mod)  # type: ignore[union-attr]
HandlerResult = _handler_mod.HandlerResult
run_handler = _handler_mod.run_handler

__all__ = ["HandlerResult", "load_routers", "run_handler"]


@pytest.fixture
def load_routers():
    """Load a compiled routers module by flow name, isolated from stub modules.

    Compiled routers live at compiled/<flow_name>/routers.py.  They share their
    base name with the stub module (e.g. both are called ``routing_classifier``)
    so a plain import would be ambiguous.  This fixture loads the routers module
    via its absolute file path, bypassing sys.path name resolution entirely.

    Usage::

        def test_something(run_handler, monkeypatch, load_routers):
            routers = load_routers("routing_classifier")
            monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")
            result = await run_handler(routers.start_routing_classifier(payload))
    """
    compiled_dir = _AGENTIC_DIR / "compiled"

    def _load(flow_name: str):
        routers_path = compiled_dir / flow_name / "routers.py"
        spec = importlib.util.spec_from_file_location(
            f"compiled_{flow_name}_routers", routers_path
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    return _load
