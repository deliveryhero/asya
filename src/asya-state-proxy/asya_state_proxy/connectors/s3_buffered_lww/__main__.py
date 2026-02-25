"""Entry point: python -m asya_state_proxy.connectors.s3_buffered_lww"""

import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from asya_state_proxy.connectors.s3_buffered_lww.connector import S3BufferedLWW  # noqa: E402
from asya_state_proxy.server import run_connector  # noqa: E402


run_connector(S3BufferedLWW())
