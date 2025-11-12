# asya_testing

Shared test library for Asya🎭 framework integration and E2E tests.

## Structure

```
asya_testing/
├── clients/          # Transport client implementations (RabbitMQ, SQS, PubSub)
├── fixtures/         # Pytest fixtures for common test setup
├── handlers/         # Test actor handler implementations
├── scenarios/        # Reusable test scenario functions
└── utils/            # Test utilities (RabbitMQ mgmt, S3, assertions)
```

## Installation

From tests directory:
```bash
pip install -e asya_testing/
```

## Usage

```python
from asya_testing.utils.rabbitmq import wait_for_rabbitmq_consumers
from asya_testing.utils.s3 import wait_for_envelope_in_s3
from asya_testing.utils.gateway import GatewayTestHelper
from asya_testing.clients.rabbitmq import RabbitMQClient
```
