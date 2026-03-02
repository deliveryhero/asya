"""Tests for StateProxyConnector interface, KeyMeta and ListResult."""

import io
from typing import BinaryIO

import pytest
from asya_state_proxy.interface import KeyMeta, ListResult, StateProxyConnector


# ---------------------------------------------------------------------------
# Instantiation guard
# ---------------------------------------------------------------------------


def test_cannot_instantiate_abstract_connector():
    with pytest.raises(TypeError, match="abstract"):
        StateProxyConnector()  # type: ignore[abstract]


def test_partial_implementation_raises_type_error():
    class PartialConnector(StateProxyConnector):  # type: ignore[abstract]
        def read(self, key: str) -> BinaryIO:
            return io.BytesIO(b"")

        def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
            pass

        # Missing: exists, stat, list, delete

    with pytest.raises(TypeError):
        PartialConnector()


def test_complete_implementation_instantiates():
    class FullConnector(StateProxyConnector):
        def read(self, key: str) -> BinaryIO:
            return io.BytesIO(b"")

        def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
            pass

        def exists(self, key: str) -> bool:
            return False

        def stat(self, key: str) -> KeyMeta | None:
            return None

        def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
            return ListResult(keys=[], prefixes=[])

        def delete(self, key: str) -> None:
            pass

    connector = FullConnector()
    assert connector is not None


# ---------------------------------------------------------------------------
# KeyMeta
# ---------------------------------------------------------------------------


def test_key_meta_fields():
    meta = KeyMeta(size=1024, is_file=True)
    assert meta.size == 1024
    assert meta.is_file is True


def test_key_meta_is_file_false():
    meta = KeyMeta(size=0, is_file=False)
    assert meta.is_file is False
    assert meta.size == 0


def test_key_meta_named_tuple_unpacking():
    meta = KeyMeta(size=512, is_file=True)
    size, is_file = meta
    assert size == 512
    assert is_file is True


def test_key_meta_equality():
    assert KeyMeta(size=10, is_file=True) == KeyMeta(size=10, is_file=True)
    assert KeyMeta(size=10, is_file=True) != KeyMeta(size=20, is_file=True)


# ---------------------------------------------------------------------------
# ListResult
# ---------------------------------------------------------------------------


def test_list_result_fields():
    result = ListResult(keys=["a/b", "a/c"], prefixes=["a/sub/"])
    assert result.keys == ["a/b", "a/c"]
    assert result.prefixes == ["a/sub/"]


def test_list_result_empty():
    result = ListResult(keys=[], prefixes=[])
    assert result.keys == []
    assert result.prefixes == []


def test_list_result_named_tuple_unpacking():
    result = ListResult(keys=["k1"], prefixes=["p1/"])
    keys, prefixes = result
    assert keys == ["k1"]
    assert prefixes == ["p1/"]


def test_list_result_equality():
    assert ListResult(keys=["a"], prefixes=[]) == ListResult(keys=["a"], prefixes=[])
    assert ListResult(keys=["a"], prefixes=[]) != ListResult(keys=["b"], prefixes=[])


# ---------------------------------------------------------------------------
# Extended attributes (xattr)
# ---------------------------------------------------------------------------


def test_default_listxattr_returns_empty_list():
    class FullConnector(StateProxyConnector):
        def read(self, key: str) -> BinaryIO:
            return io.BytesIO(b"")

        def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
            pass

        def exists(self, key: str) -> bool:
            return False

        def stat(self, key: str) -> KeyMeta | None:
            return None

        def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
            return ListResult(keys=[], prefixes=[])

        def delete(self, key: str) -> None:
            pass

    connector = FullConnector()
    assert connector.listxattr("any_key") == []


def test_default_getxattr_raises_key_error():
    class FullConnector(StateProxyConnector):
        def read(self, key: str) -> BinaryIO:
            return io.BytesIO(b"")

        def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
            pass

        def exists(self, key: str) -> bool:
            return False

        def stat(self, key: str) -> KeyMeta | None:
            return None

        def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
            return ListResult(keys=[], prefixes=[])

        def delete(self, key: str) -> None:
            pass

    connector = FullConnector()
    with pytest.raises(KeyError):
        connector.getxattr("key", "url")


def test_default_setxattr_raises_key_error():
    class FullConnector(StateProxyConnector):
        def read(self, key: str) -> BinaryIO:
            return io.BytesIO(b"")

        def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
            pass

        def exists(self, key: str) -> bool:
            return False

        def stat(self, key: str) -> KeyMeta | None:
            return None

        def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
            return ListResult(keys=[], prefixes=[])

        def delete(self, key: str) -> None:
            pass

    connector = FullConnector()
    with pytest.raises(KeyError):
        connector.setxattr("key", "url", "value")
