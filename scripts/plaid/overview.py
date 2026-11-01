from __future__ import annotations

from decimal import Decimal


def collect(call, start: str, end: str) -> dict:
    report = {"from": start, "to": end, "items": []}
    for item in call("listItems", {})["items"]:
        entry = {"alias": item["alias"], "institution": item["institution_name"]}
        report["items"].append(entry)
        try:
            accounts = call("getAccounts", {"item": item["alias"]})["accounts"]
            entry["accounts"] = [
                {
                    k: a[k]
                    for k in ["name", "mask", "type", "subtype", "balances"]
                    if k in a
                }
                for a in accounts
            ]
            rows = []
            offset = 0
            expected_total = None
            while True:
                page = call(
                    "getTransactions",
                    {
                        "item": item["alias"],
                        "startDate": start,
                        "endDate": end,
                        "count": 500,
                        "offset": offset,
                    },
                )
                total = page["total_transactions"]
                if (
                    type(total) is not int
                    or total < 0
                    or total > 100000
                    or (expected_total is not None and total != expected_total)
                ):
                    raise ValueError("Invalid or changed transaction total")
                expected_total = total
                batch = page["transactions"]
                rows.extend(batch)
                next_offset = page.get("next_offset")
                if next_offset is None:
                    if len(rows) != total:
                        raise ValueError("Incomplete transaction page")
                    break
                if (
                    type(next_offset) is not int
                    or not batch
                    or next_offset != offset + len(batch)
                    or not offset < next_offset < total
                ):
                    raise ValueError("Invalid transaction continuation")
                offset = next_offset
            unique = {t["transaction_id"]: t for t in rows}
            if len(unique) != page["total_transactions"]:
                raise ValueError("Transaction pagination was incomplete")
            totals = {}
            for t in unique.values():
                currency = (
                    t.get("iso_currency_code")
                    or t.get("unofficial_currency_code")
                    or "unknown"
                )
                group = totals.setdefault(
                    currency,
                    {
                        key: Decimal(0)
                        for key in [
                            "posted_credits",
                            "posted_debits",
                            "pending_credits",
                            "pending_debits",
                        ]
                    },
                )
                amount = Decimal(str(t["amount"]))
                key = ("pending" if t.get("pending") else "posted") + (
                    "_credits" if amount < 0 else "_debits"
                )
                group[key] += abs(amount)
            dates = [t["date"] for t in unique.values()]
            entry["transactions"] = {
                "count": len(unique),
                "earliest_returned": min(dates) if dates else None,
                "latest_returned": max(dates) if dates else None,
                "currencies": {
                    currency: {key: str(amount) for key, amount in group.items()}
                    for currency, group in totals.items()
                },
            }
            entry["item_status"] = call("getItemStatus", {"item": item["alias"]})
        except Exception:
            entry["error"] = (
                "Item collection failed; available results may be incomplete"
            )
    return report


class Gateway:
    def __init__(self, checkout):
        import json
        import os
        import subprocess
        import sys

        entry = checkout / "agents/hermes/adapter/hermes_agentcore_adapter.py"
        if not entry.is_file():
            raise ValueError("Checkout does not contain the gateway adapter")
        env = {
            key: os.environ[key]
            for key in ["PATH", "HOME", "LANG"]
            if key in os.environ
        }
        for suffix in [
            "GATEWAY_URL",
            "COGNITO_TOKEN_URL",
            "COGNITO_CLIENT_ID",
            "COGNITO_CLIENT_SECRET",
        ]:
            key = "HERMES_AGENTCORE_" + suffix
            if not os.environ.get(key):
                raise ValueError("Gateway environment is not configured")
            env[key] = os.environ[key]
        self.json = json
        self.counter = 0
        self.process = subprocess.Popen(
            [sys.executable, str(entry)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=env,
        )
        try:
            self.rpc(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "plaid-overview", "version": "1"},
                },
            )
        except Exception:
            self.close()
            raise
        assert self.process.stdin is not None
        notification = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        self.process.stdin.write((json.dumps(notification) + "\n").encode())
        self.process.stdin.flush()

    def rpc(self, method, params):
        import select

        self.counter += 1
        message = {
            "jsonrpc": "2.0",
            "id": self.counter,
            "method": method,
            "params": params,
        }
        assert self.process.stdin is not None and self.process.stdout is not None
        self.process.stdin.write((self.json.dumps(message) + "\n").encode())
        self.process.stdin.flush()
        if not select.select([self.process.stdout], [], [], 45)[0]:
            raise TimeoutError("Gateway response deadline exceeded")
        line = self.process.stdout.readline(2 * 1024 * 1024 + 1)
        if len(line) > 2 * 1024 * 1024:
            raise ValueError("Gateway response too large")
        response = self.json.loads(line)
        if response.get("id") != self.counter or response.get("error"):
            raise ValueError("Gateway request failed")
        return response["result"]

    def call(self, name, arguments):
        result = self.rpc(
            "tools/call", {"name": "plaid-" + name, "arguments": arguments}
        )
        if result.get("isError"):
            raise ValueError("Plaid tool failed")
        data = result.get("structuredContent")
        if data is None:
            texts = [
                part["text"]
                for part in result.get("content", [])
                if part.get("type") == "text"
            ]
            if len(texts) != 1:
                raise ValueError("Unexpected Plaid result")
            data = self.json.loads(texts[0])
        if not isinstance(data, dict) or data.get("isError") or data.get("error"):
            raise ValueError("Plaid tool failed")
        return data

    def close(self):
        import subprocess

        if self.process.stdin:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=3)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(timeout=3)
        if self.process.stdout:
            self.process.stdout.close()


def main(argv=None):
    import argparse
    import datetime
    import json
    import os
    import sys
    from pathlib import Path

    parser = argparse.ArgumentParser(
        description=(
            "Aggregate Plaid overview through AgentCore; no local Plaid credentials."
        )
    )
    parser.add_argument(
        "--checkout", type=Path, default=Path(__file__).resolve().parents[2]
    )
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    gateway = None
    try:
        if datetime.date.fromisoformat(args.start) > datetime.date.fromisoformat(
            args.end
        ):
            raise ValueError("Start date follows end date")
        gateway = Gateway(args.checkout.resolve())
        report = collect(gateway.call, args.start, args.end)
        report["as_of_utc"] = datetime.datetime.now(datetime.UTC).isoformat()
        encoded = json.dumps(report, indent=2)
        if args.output:
            with os.fdopen(
                os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), "w"
            ) as output:
                output.write(encoded + "\n")
        else:
            print(encoded)
        return 1 if any("error" in item for item in report["items"]) else 0
    except Exception as error:
        print(
            f"Plaid overview failed ({type(error).__name__}); details suppressed.",
            file=sys.stderr,
        )
        return 1
    finally:
        if gateway:
            gateway.close()


if __name__ == "__main__":
    raise SystemExit(main())
