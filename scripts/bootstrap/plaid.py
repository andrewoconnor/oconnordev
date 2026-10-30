from __future__ import annotations

import copy
import json


def metadata(bundle: dict) -> dict:
    return {
        "items": [
            {
                "alias": alias,
                "institution_name": item["institution_name"],
                "products": item["products"],
            }
            for alias, item in sorted(bundle["items"].items())
        ]
    }


def read_bundle(client, secret_id: str) -> dict:
    try:
        result = client.get_secret_value(SecretId=secret_id)
    except Exception as error:
        if (
            getattr(error, "response", {}).get("Error", {}).get("Code")
            != "ResourceNotFoundException"
        ):
            raise
        description = client.describe_secret(SecretId=secret_id)
        if any(
            "AWSCURRENT" in stages
            for stages in description.get("VersionIdsToStages", {}).values()
        ):
            raise ValueError("Existing secret version could not be read") from None
        return {}
    return json.loads(result["SecretString"])


def import_items(
    client,
    secret_id: str,
    items: list,
    client_id: str,
    secret: str,
    *,
    apply: bool = False,
) -> dict:
    bundle = build_bundle(items, client_id, secret)
    if not apply:
        return {**metadata(bundle), "applied": False}
    existing = read_bundle(client, secret_id)
    bundle = build_bundle(items, client_id, secret, existing)
    encoded = json.dumps(bundle, separators=(",", ":"))
    if len(encoded.encode()) > 65536:
        raise ValueError("Credential bundle exceeds Secrets Manager limit")
    if bundle != existing:
        client.put_secret_value(SecretId=secret_id, SecretString=encoded)
    if read_bundle(client, secret_id) != bundle:
        raise ValueError("Secret readback did not match")
    return {**metadata(bundle), "applied": True, "verified": True}


def build_bundle(
    items: list, client_id: str, secret: str, existing: dict | None = None
) -> dict:
    if existing:
        if (
            type(existing) is not dict
            or set(existing) != {"client_id", "secret", "items"}
            or type(existing["items"]) is not dict
        ):
            raise ValueError("Invalid existing credential bundle")
        for alias, record in existing["items"].items():
            if type(record) is not dict or set(record) != {
                "access_token",
                "institution_name",
                "products",
            }:
                raise ValueError("Invalid existing Item record")
            build_bundle([{"alias": alias, **record}], client_id, secret)
    bundle = (
        copy.deepcopy(existing)
        if existing
        else {"client_id": client_id, "secret": secret, "items": {}}
    )
    if bundle["client_id"] != client_id or bundle["secret"] != secret:
        raise ValueError("Existing application credentials differ")
    if not isinstance(items, list) or not items or len(items) > 100:
        raise ValueError("Expected a nonempty Item list")
    if not all(
        isinstance(value, str) and value and len(value) <= 4096
        for value in [client_id, secret]
    ):
        raise ValueError("Missing application credentials")
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("Invalid Item record")
        name = item.get("institution_name")
        token = item.get("access_token")
        products = item.get("products")
        if (
            not isinstance(name, str)
            or not name
            or len(name) > 200
            or not isinstance(token, str)
            or not token
            or len(token) > 4096
        ):
            raise ValueError("Invalid Item metadata or token")
        if (
            not isinstance(products, list)
            or not products
            or any(
                not isinstance(p, str)
                or p not in {"transactions", "investments", "liabilities"}
                for p in products
            )
            or len(products) != len(set(products))
        ):
            raise ValueError("Only existing read-product consent can be imported")
        alias = item.get("alias") or {
            "USAA": "usaa",
            "Capital One": "capital-one",
            "American Express": "amex",
            "Empower Retirement": "empower",
        }.get(name)
        if (
            not isinstance(alias, str)
            or alias not in {"usaa", "capital-one", "amex", "empower"}
            or alias in seen
        ):
            raise ValueError("Invalid or duplicate Item alias")
        seen.add(alias)
        bundle["items"][alias] = {
            "access_token": token,
            "institution_name": name,
            "products": products,
        }
    return bundle


def main(argv: list[str] | None = None) -> int:
    import argparse
    import os
    import stat
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description=(
            "Owner-only Plaid import and verification; --apply enables writes."
        )
    )
    parser.add_argument("command", choices=["import", "verify"])
    parser.add_argument("--secret-id", default="/hermes/plaid/credentials")
    parser.add_argument("--items-file", type=Path)
    parser.add_argument("--client-id")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "import":
            if not args.items_file or not args.client_id:
                parser.error("import requires --items-file and --client-id")
            if args.items_file.stat().st_mode & (stat.S_IRWXG | stat.S_IRWXO):
                raise ValueError("Item file must have owner-only permissions")
            if args.items_file.stat().st_size > 65536:
                raise ValueError("Item file exceeds credential size limit")
            items = json.loads(args.items_file.read_text())
            secret = os.environ.get("PLAID_CLIENT_SECRET", "")
            bundle = build_bundle(items, args.client_id, secret)
            if not args.apply:
                print(json.dumps({**metadata(bundle), "applied": False}, indent=2))
                return 0
        elif args.apply:
            parser.error("verify does not accept --apply")
        import boto3

        if (
            boto3.client("sts", region_name="us-east-1").get_caller_identity()[
                "Account"
            ]
            != "421680664125"
        ):
            raise ValueError("Bootstrap requires the TOOLS account identity")
        client = boto3.client("secretsmanager", region_name="us-east-1")
        if args.command == "import":
            output = import_items(
                client, args.secret_id, items, args.client_id, secret, apply=True
            )
        else:
            stored = read_bundle(client, args.secret_id)
            records = [
                {"alias": alias, **item} for alias, item in stored["items"].items()
            ]
            bundle = build_bundle(
                records, stored["client_id"], stored["secret"], stored
            )
            output = {**metadata(bundle), "credential_bundle_valid": True}
        print(json.dumps(output, indent=2))
        return 0
    except Exception as error:
        print(
            f"Plaid bootstrap failed ({type(error).__name__}); details suppressed.",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
