"""
Pytest configuration for asya-testing unit tests.

Sets up sys.path so example flow modules (routing_classifier, etc.) can be
imported directly, and loads the run_handler fixture by file path to avoid
triggering asya_testing's heavy package __init__ (google-cloud, aio-pika).
"""

import importlib.util
import sys
from pathlib import Path

import pytest


# Repo root: src/asya-testing/tests -> src/asya-testing -> src -> repo root
_REPO_ROOT = Path(__file__).parent.parent.parent.parent

# Agentic example flow modules (routing_classifier.py, parallel_sectioning.py, …)
_AGENTIC_DIR = _REPO_ROOT / "examples" / "flows" / "agentic"
sys.path.insert(0, str(_AGENTIC_DIR))

# Load handler.py by file path, bypassing asya_testing/__init__ which pulls
# in heavy optional deps (google-cloud, aio-pika) not needed for unit tests.
_handler_spec = importlib.util.spec_from_file_location(
    "asya_testing.fixtures.handler",
    str(Path(__file__).parent.parent / "asya_testing" / "fixtures" / "handler.py"),
)
_handler_mod = importlib.util.module_from_spec(_handler_spec)  # type: ignore[arg-type]
_handler_spec.loader.exec_module(_handler_mod)  # type: ignore[union-attr]

HandlerResult = _handler_mod.HandlerResult
run_handler = _handler_mod.run_handler


@pytest.fixture
def load_routers():
    """Load a compiled routers module by flow name, isolated from stub modules.

    Compiled routers share their base name with stub modules (e.g. both are
    called ``routing_classifier``), so a plain import would be ambiguous.
    This fixture loads by absolute file path, bypassing sys.path resolution.

    Usage::

        def test_something(run_handler, monkeypatch, load_routers):
            routers = load_routers("routing_classifier")
            monkeypatch.setattr(routers, "resolve", lambda name: f"actor-{name}")
    """
    compiled_dir = _AGENTIC_DIR / "compiled"

    def _load(flow_name: str):
        routers_path = compiled_dir / flow_name / "routers.py"
        spec = importlib.util.spec_from_file_location(f"compiled_{flow_name}_routers", routers_path)
        module = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        return module

    return _load
