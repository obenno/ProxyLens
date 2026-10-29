import argparse
import sys
import urllib.error
import urllib.request

import uvicorn

from proxylens.app import create_app


def main() -> None:
    parser = argparse.ArgumentParser(description="ProxyLens service entrypoints")
    parser.add_argument("command", choices=["api", "gateway", "worker", "healthcheck"])
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.command == "healthcheck":
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{args.port}/health/ready", timeout=4
            ) as response:
                sys.exit(0 if response.status == 200 else 1)
        except (OSError, urllib.error.URLError):
            sys.exit(1)
    uvicorn.run(create_app(args.command), host=args.host, port=args.port, access_log=False)


if __name__ == "__main__":
    main()
