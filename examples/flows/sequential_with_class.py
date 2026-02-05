"""
Class instantiation example.

Tests instantiating classes and calling their methods.
"""


def class_instantiation_flow(p: dict) -> dict:
    # Instantiate processors
    preprocessor = DataPreprocessor()
    model = MLModel()

    # Use instances
    p = preprocessor.clean(p)
    p = transformation(p)
    p = model.predict(p)

    return p


def transformation(p: dict) -> dict:
    return p


class DataPreprocessor:
    def __init__(self, config: str = "default"):
        self.config = config

    def clean(self, p: dict) -> dict:
        """Clean the data."""
        return p


class MLModel:
    def __init__(self):
        pass

    def predict(self, p: dict) -> dict:
        """Run prediction."""
        return p
