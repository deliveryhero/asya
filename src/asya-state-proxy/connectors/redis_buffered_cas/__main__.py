"""Entry point: python -m connectors.redis_buffered_cas"""

import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from asya_state_proxy.server import run_connector  # noqa: E402

from connectors.redis_buffered_cas.connector import RedisBufferedCAS  # noqa: E402


run_connector(RedisBufferedCAS())
