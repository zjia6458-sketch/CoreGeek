from __future__ import annotations

import argparse
import logging

from fortress_agent.application.bootstrap import build_runtime
from .http import run_http_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description='FortressAgent HTTP server'
    )
    parser.add_argument(
        'port',
        type=int,
        help='port passed by the judger',
    )
    args = parser.parse_args()

    # Do not configure logging here.  The official competition entrypoint is
    # main3.py, which owns the single stdout root logger.  If this module is
    # invoked directly during local development, it simply uses the process'
    # existing root logger configuration.
    runtime = build_runtime(
        logger=logging.getLogger()
    )

    run_http_server(
        args.port,
        host='0.0.0.0',
        runtime=runtime,
    )


if __name__ == '__main__':
    main()
