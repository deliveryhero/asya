"""StateProxyConnector interface -- contract for all state proxy connectors."""

from abc import ABC, abstractmethod
from typing import BinaryIO, NamedTuple


class KeyMeta(NamedTuple):
    size: int
    is_file: bool


class ListResult(NamedTuple):
    keys: list[str]
    prefixes: list[str]


class StateProxyConnector(ABC):
    @abstractmethod
    def read(self, key: str) -> BinaryIO:
        """GET /keys/{key} -> 200 + body stream. Raises FileNotFoundError on 404."""

    @abstractmethod
    def write(self, key: str, data: BinaryIO, size: int | None = None) -> None:
        """PUT /keys/{key}. Raises FileExistsError on 409 (CAS conflict)."""

    @abstractmethod
    def exists(self, key: str) -> bool:
        """HEAD /keys/{key} -> True/False."""

    @abstractmethod
    def stat(self, key: str) -> KeyMeta | None:
        """HEAD /keys/{key} -> KeyMeta or None."""

    @abstractmethod
    def list(self, key_prefix: str, delimiter: str = "/") -> ListResult:
        """GET /keys/?prefix={p}&delimiter=/ -> ListResult."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """DELETE /keys/{key}. Raises FileNotFoundError on 404."""
