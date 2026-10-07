"""Read a recorded range from a remote data service, with no server of ours.

    uv run python modules/remote-history/examples/read_remote.py --url http://127.0.0.1:8100
    REMOTE_URL=http://127.0.0.1:8100 uv run python modules/remote-history/examples/read_remote.py

The service speaks the remote data contract (doc/remote-data-integration-contract.md);
core/examples/remote_data_stub is one to try this against. ``read`` is the
synchronous form: it drives the source's async code on a private event loop.
"""

from __future__ import annotations

import argparse
import os
import sys

from pswamp_modules.remote_history import RemoteHistory


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default=os.environ.get("REMOTE_URL"), help="the service's base URL (default: $REMOTE_URL)")
    parser.add_argument("--limit", type=int, default=10, help="how many frames to print")
    args = parser.parse_args()
    if not args.url:
        sys.exit("give --url, or set REMOTE_URL")

    source = RemoteHistory(url=args.url)
    try:
        coverage = source.coverage()
    except ConnectionError as error:
        sys.exit(str(error))
    if coverage is None:
        sys.exit("the service holds nothing")
    print(f"{args.url} holds [{coverage.start}, {coverage.end})")
    for number, frame in enumerate(source.read(coverage.start, coverage.end)):
        if number >= args.limit:
            print("  ...")
            break
        print(f"  {frame.timestamp}  {len(frame.values)} values")


if __name__ == "__main__":
    main()
