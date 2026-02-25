"""Entry point: python -m asya_state_proxy.connectors.s3_passthrough"""

import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from asya_state_proxy.connectors.s3_passthrough.connector import S3Passthrough  # noqa: E402
from asya_state_proxy.server import run_connector  # noqa: E402


run_connector(S3Passthrough())
