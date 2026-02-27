"""Typed handler examples for testing typed signatures feature."""

import dataclasses


# Pydantic is optional
try:
    from pydantic import BaseModel

    HAS_PYDANTIC = True
except ImportError:
    BaseModel = None
    HAS_PYDANTIC = False


# Simple typed handlers


def simple_int(value: int) -> dict:
    """Simple typed handler with int input."""
    return {"doubled": value * 2}


def simple_str(text: str) -> dict:
    """Simple typed handler with string input."""
    return {"upper": text.upper()}


def multi_params(x: int, y: int, z: int = 10) -> dict:
    """Typed handler with multiple params, one optional."""
    return {"sum": x + y + z}


def scalar_return(value: int) -> int:
    """Typed handler returning scalar."""
    return value * 2


def list_return(values: list) -> list:
    """Typed handler returning list."""
    return [v * 2 for v in values]


# Dataclass handlers


@dataclasses.dataclass
class Point:
    """Point dataclass."""

    x: int
    y: int


def dataclass_input(point: Point) -> dict:
    """Handler with dataclass input."""
    return {"distance": (point.x**2 + point.y**2) ** 0.5}


def dataclass_output(x: int, y: int) -> Point:
    """Handler with dataclass output."""
    return Point(x=x, y=y)


# Pydantic handlers (if available)

if HAS_PYDANTIC and BaseModel is not None:

    class User(BaseModel):
        """User Pydantic model."""

        name: str
        age: int

    def pydantic_input(user: User) -> dict:
        """Handler with Pydantic input."""
        return {"greeting": f"Hello, {user.name}! You are {user.age} years old."}

    def pydantic_output(name: str, age: int) -> User:
        """Handler with Pydantic output."""
        return User(name=name, age=age)


# Class handlers


class Counter:
    """Stateful counter handler."""

    def __init__(self, start: int = 0):
        self.value = start

    def increment(self, amount: int) -> dict:
        """Increment counter and return new value."""
        self.value += amount
        return {"value": self.value}


# Async handlers


async def async_typed(value: int) -> dict:
    """Async typed handler."""
    return {"result": value * 3}


async def async_generator(count: int):
    """Async generator typed handler."""
    for i in range(count):
        yield {"index": i, "value": i * 2}


# Nested path handlers (for ASYA_PARAMS_AT/ASYA_RESULT_AT testing)


def nested_input_output(value: int) -> dict:
    """Handler for testing nested input/output paths."""
    return {"computed": value * 2}
