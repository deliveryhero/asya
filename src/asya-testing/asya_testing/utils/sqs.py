"""SQS utilities for component and integration tests."""

import logging
import os
import time

import boto3
from botocore.exceptions import ClientError

from asya_testing.config import require_env


logger = logging.getLogger(__name__)


def _get_sqs_endpoint() -> str:
    """
    Get SQS endpoint URL with fallback logic.

    Tries AWS_ENDPOINT_URL first (standard AWS SDK var), then falls back to
    ASYA_SQS_ENDPOINT (Asya-specific var) for backward compatibility.

    Returns:
        SQS endpoint URL

    Raises:
        ConfigurationError: If neither variable is set
    """
    endpoint = os.getenv("AWS_ENDPOINT_URL") or os.getenv("ASYA_SQS_ENDPOINT")
    if not endpoint:
        from asya_testing.config import ConfigurationError

        raise ConfigurationError("AWS_ENDPOINT_URL or ASYA_SQS_ENDPOINT must be set for SQS operations")
    return endpoint


def create_test_queues(queues: list[str]) -> None:
    """
    Create SQS queues for testing.

    Args:
        queues: List of queue names to create

    Raises:
        ConfigurationError: If required AWS credentials are not set
    """
    endpoint_url = _get_sqs_endpoint()
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    access_key = require_env("AWS_ACCESS_KEY_ID")
    secret_key = require_env("AWS_SECRET_ACCESS_KEY")

    sqs = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    for queue in queues:
        try:
            sqs.create_queue(QueueName=queue)
            print(f"[+] Created SQS queue: {queue}")
        except Exception as e:
            print(f"[-] Failed to create queue {queue}: {e}")


def wait_for_sqs_queues(
    endpoint_url: str | None = None,
    required_queues: list[str] | None = None,
    timeout: int = 30,
) -> None:
    """
    Wait for SQS queues to be accessible and ready.

    Polls SQS endpoint until all required queues exist and are accessible.
    This ensures LocalStack SQS is ready and queues are created before tests start.

    Args:
        endpoint_url: SQS endpoint URL (defaults to AWS_ENDPOINT_URL env var)
        required_queues: List of queue names to check.
                        If None, skips queue waiting (just verifies SQS connectivity).
        timeout: Maximum time to wait in seconds (default: 30)

    Raises:
        RuntimeError: If SQS queues are not ready within timeout
        ConfigurationError: If required AWS environment variables are not set
    """
    endpoint_url = endpoint_url or _get_sqs_endpoint()
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    access_key = require_env("AWS_ACCESS_KEY_ID")
    secret_key = require_env("AWS_SECRET_ACCESS_KEY")

    if required_queues is None:
        logger.info("No required_queues specified, skipping SQS queue check")
        return

    start_time = time.time()
    poll_interval = 0.5

    while time.time() - start_time < timeout:
        try:
            sqs = boto3.client(
                "sqs",
                endpoint_url=endpoint_url,
                region_name=region,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
            )

            queue_urls = {}
            for queue_name in required_queues:
                try:
                    response = sqs.get_queue_url(QueueName=queue_name)
                    queue_urls[queue_name] = response["QueueUrl"]
                except ClientError as e:
                    if e.response["Error"]["Code"] == "AWS.SimpleQueueService.NonExistentQueue":
                        queue_urls[queue_name] = None
                    else:
                        raise

            all_ready = all(queue_urls.get(q) is not None for q in required_queues)

            if all_ready:
                logger.info(f"All SQS queues ready after {time.time() - start_time:.2f}s")
                return
            else:
                missing = [q for q in required_queues if queue_urls.get(q) is None]
                logger.info(f"Waiting for SQS queues: {missing}")

        except Exception as e:
            logger.info(f"SQS not ready: {e}")

        time.sleep(poll_interval)

    raise RuntimeError(f"SQS queues not ready after {timeout}s")


def purge_queue(queue_name: str, endpoint_url: str | None = None) -> None:
    """
    Purge all messages from an SQS queue.

    This removes both visible and in-flight (not visible) messages.
    Useful for cleaning up stuck messages before tests.

    Args:
        queue_name: Name of the queue to purge
        endpoint_url: SQS endpoint URL (defaults to AWS_ENDPOINT_URL env var)

    Raises:
        ConfigurationError: If required AWS environment variables are not set
    """
    endpoint_url = endpoint_url or _get_sqs_endpoint()
    region = os.getenv("AWS_DEFAULT_REGION", "us-east-1")
    access_key = require_env("AWS_ACCESS_KEY_ID")
    secret_key = require_env("AWS_SECRET_ACCESS_KEY")

    sqs = boto3.client(
        "sqs",
        endpoint_url=endpoint_url,
        region_name=region,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )

    try:
        response = sqs.get_queue_url(QueueName=queue_name)
        queue_url = response["QueueUrl"]
        sqs.purge_queue(QueueUrl=queue_url)
        logger.info(f"Purged SQS queue: {queue_name}")
    except ClientError as e:
        if e.response["Error"]["Code"] == "AWS.SimpleQueueService.NonExistentQueue":
            logger.warning(f"Queue {queue_name} does not exist, skipping purge")
        else:
            raise
