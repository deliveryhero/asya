"""Entry point: python -m asya_state_proxy.connectors.gcs_buffered_cas"""

import logging


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

from asya_state_proxy.connectors.gcs_buffered_cas.connector import GCSBufferedCAS  # noqa: E402
from asya_state_proxy.server import run_connector  # noqa: E402


run_connector(GCSBufferedCAS())
