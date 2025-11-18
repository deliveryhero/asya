"""Base transport client interface for Asya framework tests."""

from abc import ABC, abstractmethod


class TransportClient(ABC):
    """
    Abstract base class for transport client implementations.

    Provides interface for publishing and consuming messages from transport queues.
    Implementations: RabbitMQ, SQS, PubSub.
    """

    @abstractmethod
    def publish(self, queue: str, message: dict) -> None:
        """
        Publish message to queue.

        Args:
            queue: Queue name
            message: Message dict (will be JSON-serialized)
        """
        pass

    @abstractmethod
    def consume(self, queue: str, timeout: int = 10) -> dict | None:
        """
        Consume message from queue with timeout.

        Args:
            queue: Queue name
            timeout: Timeout in seconds

        Returns:
            Message dict or None if timeout
        """
        pass

    @abstractmethod
    def purge(self, queue: str) -> None:
        """
        Purge all messages from queue.

        Args:
            queue: Queue name
        """
        pass

    @abstractmethod
    def list_queues(self) -> list[str]:
        """
        List all queue names.

        Returns:
            List of queue names
        """
        pass


class ActorTransportClient(TransportClient):
    """
    Wrapper that converts actor names to queue names before delegating to transport client.

    This wrapper implements the Asya queue naming convention: asya-{actor_name}.
    Tests use actor names (e.g. "test-echo"), which are transformed to queue names
    (e.g. "asya-test-echo") before calling the underlying transport client.
    """

    def __init__(self, transport: TransportClient):
        """Initialize wrapper with underlying transport client."""
        self._transport = transport

    def _resolve_queue_name(self, actor_name: str) -> str:
        """Convert actor name to queue name using Asya naming convention."""
        return f"asya-{actor_name}"

    def publish(self, queue: str, message: dict) -> None:
        """Publish message to actor queue."""
        queue_name = self._resolve_queue_name(queue)
        self._transport.publish(queue_name, message)

    def consume(self, queue: str, timeout: int = 10) -> dict | None:
        """Consume message from actor queue."""
        queue_name = self._resolve_queue_name(queue)
        return self._transport.consume(queue_name, timeout)

    def purge(self, queue: str) -> None:
        """Purge all messages from actor queue."""
        queue_name = self._resolve_queue_name(queue)
        self._transport.purge(queue_name)

    def list_queues(self) -> list[str]:
        """List all queue names (delegates to underlying transport)."""
        return self._transport.list_queues()
