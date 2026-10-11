#!/usr/bin/env python3
"""Discover SocialQuery operations or make one explicitly budgeted request."""
import argparse
import json
import sys
from socialquery_client import SocialQueryClient, SocialQueryError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    discover = commands.add_parser("discover")
    discover.add_argument("--platform", default="hackernews")
    inspect = commands.add_parser("inspect")
    inspect.add_argument("endpoint_id")
    call = commands.add_parser("call")
    call.add_argument("endpoint_id")
    call.add_argument("--params", required=True, help="JSON object with endpoint parameters; never include API keys")
    call.add_argument("--max-credits", type=int, required=True)
    call.add_argument("--idempotency-key")
    call.add_argument("--allow-mutation", action="store_true", help="Permit a user-requested POST/PATCH/DELETE; requires --idempotency-key")
    commands.add_parser("balance")
    args = parser.parse_args()
    client = SocialQueryClient()
    try:
        if args.command == "discover":
            result = [{key: endpoint.get(key) for key in ("id", "title", "method", "creditCost", "launchStatus")} for endpoint in client.endpoints() if endpoint["platformSlug"] == args.platform]
        elif args.command == "inspect":
            result = next((endpoint for endpoint in client.endpoints() if endpoint["id"] == args.endpoint_id), None)
            if result is None:
                raise SocialQueryError("Unknown endpoint ID.")
        elif args.command == "balance":
            result = client.get("/v1/credits/balance")
        else:
            try:
                parameters = json.loads(args.params)
            except ValueError:
                raise SocialQueryError("--params must contain valid JSON.") from None
            result = client.call_endpoint(args.endpoint_id, parameters, args.max_credits, args.idempotency_key, args.allow_mutation)
        print(json.dumps(result, indent=2))
    except SocialQueryError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
