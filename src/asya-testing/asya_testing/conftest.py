"""
Pytest configuration for Asya framework tests.

Pytest hooks (diagnostics, etc) and shared configuration.
Fixtures are auto-discovered from asya_testing.fixtures submodules.
"""

import logging
import os
import re
from pathlib import Path

import pytest

from asya_testing.config import get_env
from asya_testing.fixtures.log_config import configure_logging
from asya_testing.utils.diagnostics import log_full_e2e_diagnostics, log_test_failure_diagnostics


configure_logging()
logger = logging.getLogger(__name__)


def _load_profile_env_file():
    """
    Auto-load environment variables from profile-specific .env file for E2E tests.

    This hook loads environment variables from testing/e2e/profiles/.env.{PROFILE}
    based on the PROFILE environment variable. This allows E2E tests to automatically
    get the correct localhost URLs without requiring manual environment variable
    passing in the Makefile.

    Only loads variables that are not already set (doesn't override existing values).
    """
    profile = os.getenv("PROFILE")
    if not profile:
        return

    project_root = Path(os.getenv("PROJECT_ROOT", Path.cwd()))
    env_file = project_root / "testing" / "e2e" / "profiles" / f".env.{profile}"

    if not env_file.exists():
        logger.warning(f"Profile env file not found: {env_file}")
        return

    logger.info(f"Loading environment from: {env_file}")

    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()

            if key and not os.getenv(key):
                os.environ[key] = value
                logger.debug(f"Loaded: {key}={value}")


def pytest_sessionstart(session):
    """Hook called at the start of the test session."""
    _load_profile_env_file()

    if get_env("ASYA_E2E_DIAGNOSTICS", "false").lower() == "true":
        logger.info("Running pre-test diagnostics...")
        try:
            log_full_e2e_diagnostics()
        except Exception as e:
            logger.warning(f"[!] Diagnostics failed: {e}")


# Store test failures per module for batch diagnostics
_failed_tests_by_module: dict[str, list[dict[str, str | list[str] | None]]] = {}
_last_module_seen: str | None = None


def _extract_actors_from_test(request) -> list[str]:
    """
    Extract actor names from test name, docstring, or fixtures.

    Returns list of actor names that are likely involved in the test.
    """
    actors = []

    # Extract from test name (e.g., test_echo_e2e, test_doubler_incrementer)
    test_name = request.node.name
    common_actors = [
        "test-echo",
        "test-doubler",
        "test-incrementer",
        "test-error",
        "test-timeout",
        "test-fanout",
        "test-nested",
        "test-empty",
        "test-unicode",
        "test-large-payload",
        "test-slow-boundary",
        "happy-end",
        "error-end",
    ]

    # Check test name for actor references
    for actor in common_actors:
        actor_pattern = actor.replace("test-", "").replace("-", "[_-]?")
        if re.search(actor_pattern, test_name, re.IGNORECASE):
            actors.append(actor)

    # Extract from docstring if available
    if request.node.function.__doc__:
        doc = request.node.function.__doc__.lower()
        for actor in common_actors:
            if (actor in doc or actor.replace("-", "_") in doc) and actor not in actors:
                actors.append(actor)

    # Check for multihop tests
    if "multihop" in test_name.lower():
        actors.extend([f"test-multihop-{i}" for i in range(15)])

    return actors


def _print_module_diagnostics(module_name: str):
    """Print diagnostics for all failures in a module."""
    if module_name not in _failed_tests_by_module:
        return

    namespace = os.getenv("NAMESPACE", "asya-e2e")
    failures = _failed_tests_by_module[module_name]

    logger.info(f"\n[!] Diagnostics for failed tests in {module_name} ({len(failures)} failures)")

    # Collect unique actors across all failures in this module
    all_actors: set[str] = set()
    test_names: list[str] = []
    for failure in failures:
        test_name = failure.get("test_name")
        if test_name and isinstance(test_name, str):
            test_names.append(test_name)
        actors = failure.get("actors")
        if actors and isinstance(actors, list):
            all_actors.update(actors)

    try:
        log_test_failure_diagnostics(
            test_name=f"{module_name}: {', '.join(test_names)}",
            actors=list(all_actors) if all_actors else None,
            namespace=namespace,
        )
    except Exception as e:
        logger.warning(f"[!] Failure diagnostics failed: {e}")

    # Remove this module from the dict
    del _failed_tests_by_module[module_name]


@pytest.fixture(autouse=True, scope="function")
def e2e_test_diagnostics(request):
    """
    Autouse fixture that collects test failures for batch diagnostics.

    Collects all failures from tests in the same file, then prints diagnostics
    once after all tests in the file complete.
    """
    global _last_module_seen

    # Before test: check if we've moved to a new module
    current_module = request.node.module.__name__
    if _last_module_seen is not None and _last_module_seen != current_module:
        # Print diagnostics for the previous module
        _print_module_diagnostics(_last_module_seen)

    _last_module_seen = current_module

    yield

    # Collect failure information
    if request.node.rep_call.failed if hasattr(request.node, "rep_call") else False:
        module_name = request.node.module.__name__
        if module_name not in _failed_tests_by_module:
            _failed_tests_by_module[module_name] = []

        actors = _extract_actors_from_test(request)
        _failed_tests_by_module[module_name].append(
            {
                "test_name": request.node.name,
                "actors": actors if actors else None,
            }
        )


def pytest_sessionfinish(session, exitstatus):  # noqa: vulture - required by pytest hookspec
    """
    Hook called at the end of the test session.

    Prints diagnostics for the last module if any failures remain.
    """
    global _last_module_seen

    # Print diagnostics for the last module if it has failures
    if _last_module_seen is not None:
        _print_module_diagnostics(_last_module_seen)

    # Clear any remaining failures
    _failed_tests_by_module.clear()
    _last_module_seen = None


@pytest.hookimpl(tryfirst=True, hookwrapper=True)
def pytest_runtest_makereport(item, call):  # noqa: vulture - call required by pytest hookspec
    """Pytest hook to store test result for use in fixtures."""
    outcome = yield
    rep = outcome.get_result()
    setattr(item, f"rep_{rep.when}", rep)
