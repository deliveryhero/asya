"""SQS client implementation for component and integration tests."""

import json
import logging
import time

import boto3
from botocore.exceptions import ClientError

from .base import TransportClient


logger = logging.getLogger(__name__)


class SQSClient(TransportClient):
    """
    SQS client for test operations.

    Provides methods for publishing, consuming, and purging queues.
    Compatible with LocalStack for local testing.
    """

    def __init__(
        self,
        endpoint_url: str = "http://localstack:4566",
        region: str = "us-east-1",
        access_key: str = "test",
        secret_key: str = "test",
    ):
        self.sqs = boto3.client(
            "sqs",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
        )
        self.queue_urls: dict[str, str] = {}

    def _get_queue_url(self, queue: str) -> str:
        """Get or create queue URL."""
        if queue not in self.queue_urls:
            try:
                response = self.sqs.get_queue_url(QueueName=queue)
                self.queue_urls[queue] = response["QueueUrl"]
            except ClientError as e:
                if e.response["Error"]["Code"] == "AWS.SimpleQueueService.NonExistentQueue":
                    response = self.sqs.create_queue(QueueName=queue)
                    self.queue_urls[queue] = response["QueueUrl"]
                else:
                    raise
        return self.queue_urls[queue]

    def publish(self, queue: str, message: dict, exchange: str = "") -> None:
        """Publish message to queue."""
        queue_url = self._get_queue_url(queue)
        body = json.dumps(message)
        self.sqs.send_message(QueueUrl=queue_url, MessageBody=body)
        logger.debug(f"Published to {queue}: {message.get('id', 'N/A')}")

    def consume(self, queue: str, timeout: int = 10) -> dict | None:
        """Consume message from queue with timeout."""
        queue_url = self._get_queue_url(queue)
        start = time.time()
        poll_interval = 0.1

        while time.time() - start < timeout:
            response = self.sqs.receive_message(
                QueueUrl=queue_url,
                MaxNumberOfMessages=1,
                WaitTimeSeconds=1,
            )

            messages = response.get("Messages", [])
            if messages:
                message = messages[0]
                self.sqs.delete_message(QueueUrl=queue_url, ReceiptHandle=message["ReceiptHandle"])
                logger.debug(f"Consumed from {queue}")
                return json.loads(message["Body"])

            time.sleep(poll_interval)

        logger.debug(f"Timeout waiting for message in {queue}")
        return None

    def purge(self, queue: str) -> None:
        """Purge all messages from queue."""
        queue_url = self._get_queue_url(queue)
        try:
            self.sqs.purge_queue(QueueUrl=queue_url)
            logger.debug(f"Purged {queue}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "AWS.SimpleQueueService.PurgeQueueInProgress":
                raise

    def delete_queue(self, queue: str) -> None:
        """Delete a queue."""
        try:
            queue_url = self._get_queue_url(queue)
            self.sqs.delete_queue(QueueUrl=queue_url)
            if queue in self.queue_urls:
                del self.queue_urls[queue]
            logger.debug(f"Deleted queue {queue}")
        except ClientError as e:
            if e.response["Error"]["Code"] != "AWS.SimpleQueueService.NonExistentQueue":
                raise
            logger.debug(f"Queue {queue} does not exist, skipping deletion")

    def create_queue(self, queue: str) -> None:
        """Create a queue."""
        try:
            response = self.sqs.create_queue(QueueName=queue)
            self.queue_urls[queue] = response["QueueUrl"]
            logger.debug(f"Created queue {queue}")
        except ClientError as e:
            if e.response["Error"]["Code"] == "QueueAlreadyExists":
                response = self.sqs.get_queue_url(QueueName=queue)
                self.queue_urls[queue] = response["QueueUrl"]
                logger.debug(f"Queue {queue} already exists")
            else:
                raise

    def list_queues(self) -> list[str]:
        """List all queue names."""
        queue_names = []
        next_token = None

        while True:
            response = self.sqs.list_queues(NextToken=next_token) if next_token else self.sqs.list_queues()

            urls = response.get("QueueUrls", [])
            for url in urls:
                queue_name = url.split("/")[-1]
                queue_names.append(queue_name)

            next_token = response.get("NextToken")
            if not next_token:
                break

        logger.debug(f"Listed {len(queue_names)} queues")
        return queue_names
