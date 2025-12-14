"""Tests for the resolve() function in generated code."""

import os
import sys
import tempfile
from pathlib import Path

import pytest
from asya_cli.flow.compiler import FlowCompiler


@pytest.fixture
def sample_flow_code():
    """Sample flow with class methods and regular functions."""
    return """
class DataPreprocessor:
    def clean(self, p: dict) -> dict:
        return p

class MLModel:
    def predict(self, p: dict) -> dict:
        return p

def validate(p: dict) -> dict:
    return p

def test_flow(p: dict) -> dict:
    preprocessor = DataPreprocessor()
    model = MLModel()

    p = preprocessor.clean(p)
    p = model.predict(p)
    p = validate(p)
    return p
"""


@pytest.fixture
def compiled_module(sample_flow_code):
    """Compile the sample flow and import the generated module."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Write source flow file
        source_file = Path(tmpdir) / "test_flow.py"
        source_file.write_text(sample_flow_code)

        # Compile the flow
        output_dir = Path(tmpdir) / "output"
        compiler = FlowCompiler()
        compiler.compile_file(str(source_file), str(output_dir))

        # Import the compiled module
        sys.path.insert(0, str(output_dir))
        try:
            # Reload to ensure fresh import
            import importlib

            import routers

            importlib.reload(routers)

            yield routers
        finally:
            sys.path.remove(str(output_dir))
            if "routers" in sys.modules:
                del sys.modules["routers"]


class TestResolveFunction:
    """Test the resolve() function generated in compiled code."""

    def test_resolve_with_full_handler_name(self, compiled_module):
        """Test resolving with full qualified handler name."""
        os.environ["ASYA_HANDLER_TEST_FLOW_DATAPREPROCESSOR_CLEAN"] = "test_flow.DataPreprocessor.clean"
        os.environ["ASYA_HANDLER_TEST_FLOW_MLMODEL_PREDICT"] = "test_flow.MLModel.predict"
        os.environ["ASYA_HANDLER_VALIDATE"] = "validate"

        import importlib

        importlib.reload(compiled_module)

        # Test full name resolution
        assert compiled_module.resolve("test_flow.DataPreprocessor.clean") == "test-flow-datapreprocessor-clean"
        assert compiled_module.resolve("test_flow.MLModel.predict") == "test-flow-mlmodel-predict"
        assert compiled_module.resolve("validate") == "validate"

    def test_resolve_with_short_suffix(self, compiled_module):
        """Test resolving with shortest suffix (method name only)."""
        os.environ["ASYA_HANDLER_TEST_FLOW_DATAPREPROCESSOR_CLEAN"] = "test_flow.DataPreprocessor.clean"
        os.environ["ASYA_HANDLER_VALIDATE"] = "validate"

        import importlib

        importlib.reload(compiled_module)

        # Test short suffix resolution (unambiguous)
        assert compiled_module.resolve("clean") == "test-flow-datapreprocessor-clean"
        assert compiled_module.resolve("validate") == "validate"

    def test_resolve_with_class_method_suffix(self, compiled_module):
        """Test resolving with ClassName.method suffix."""
        os.environ["ASYA_HANDLER_TEST_FLOW_DATAPREPROCESSOR_CLEAN"] = "test_flow.DataPreprocessor.clean"
        os.environ["ASYA_HANDLER_TEST_FLOW_MLMODEL_PREDICT"] = "test_flow.MLModel.predict"

        import importlib

        importlib.reload(compiled_module)

        # Test ClassName.method suffix resolution
        assert compiled_module.resolve("DataPreprocessor.clean") == "test-flow-datapreprocessor-clean"
        assert compiled_module.resolve("MLModel.predict") == "test-flow-mlmodel-predict"

    def test_resolve_ambiguous_suffix_raises_error(self, compiled_module):
        """Test that ambiguous suffix raises ValueError."""
        os.environ["ASYA_HANDLER_A"] = "module1.Processor.process"
        os.environ["ASYA_HANDLER_B"] = "module2.Processor.process"

        import importlib

        importlib.reload(compiled_module)

        # Test ambiguous suffix
        with pytest.raises(ValueError, match="Handler suffix 'process' is ambiguous"):
            compiled_module.resolve("process")

        # But longer suffix should work
        assert compiled_module.resolve("module1.Processor.process") == "a"
        assert compiled_module.resolve("module2.Processor.process") == "b"

    def test_resolve_not_found_raises_error(self, compiled_module):
        """Test that unknown handler raises ValueError."""
        os.environ["ASYA_HANDLER_KNOWN"] = "known_handler"

        import importlib

        importlib.reload(compiled_module)

        with pytest.raises(ValueError, match="Handler 'unknown_handler' not found"):
            compiled_module.resolve("unknown_handler")

    def test_resolve_loads_on_module_import(self, compiled_module):
        """Test that resolve() loads environment variables at module import time."""
        os.environ["ASYA_HANDLER_TEST"] = "test_handler"

        import importlib

        importlib.reload(compiled_module)

        # Module constants are populated
        assert compiled_module._HANDLER_TO_ACTOR["test_handler"] == "test"
        assert compiled_module.resolve("test_handler") == "test"

        # Modify environment after module load
        os.environ["ASYA_HANDLER_NEW"] = "new_handler"

        # New handler should not be found (module-level constants already initialized)
        with pytest.raises(ValueError, match="Handler 'new_handler' not found"):
            compiled_module.resolve("new_handler")

    def test_resolve_handles_all_suffix_combinations(self, compiled_module):
        """Test all possible suffixes for a.b.c handler."""
        os.environ["ASYA_HANDLER_ABC"] = "a.b.c"

        import importlib

        importlib.reload(compiled_module)

        # All suffixes should resolve correctly
        assert compiled_module.resolve("c") == "abc"
        assert compiled_module.resolve("b.c") == "abc"
        assert compiled_module.resolve("a.b.c") == "abc"

    def test_resolve_actor_name_conversion(self, compiled_module):
        """Test that actor names are correctly converted to kebab-case."""
        os.environ["ASYA_HANDLER_MY_LONG_ACTOR_NAME"] = "my.long.handler.name"

        import importlib

        importlib.reload(compiled_module)

        # Underscores should become hyphens, lowercase
        assert compiled_module.resolve("my.long.handler.name") == "my-long-actor-name"

    def teardown_method(self):
        """Clean up environment variables after each test."""
        for key in list(os.environ.keys()):
            if key.startswith("ASYA_HANDLER_"):
                del os.environ[key]
