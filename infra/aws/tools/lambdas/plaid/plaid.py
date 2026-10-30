import datetime
import json
import os
import re
import urllib.error
import urllib.request

MAX_RESPONSE = 1024 * 1024
UPSTREAM = "https://production.plaid.com"


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError
        result[key] = value
    return result


def invalid_constant(value):
    raise ValueError


def decode(raw):
    return json.loads(
        raw, object_pairs_hook=strict_object, parse_constant=invalid_constant
    )


def sanitize(value, secrets):
    if isinstance(value, dict):
        return {
            sanitize(k, secrets): sanitize(v, secrets)
            for k, v in value.items()
            if not re.search(r"token|secret|client.?id|authorization|password", k, re.I)
            and k
            not in {
                "error_message",
                "display_message",
                "documentation_url",
                "suggested_action",
            }
        }
    if isinstance(value, list):
        return [sanitize(v, secrets) for v in value]
    if isinstance(value, str):
        for secret in sorted(secrets, key=len, reverse=True):
            value = value.replace(secret, "[REDACTED]")
    return value


def post(path, payload, opener):
    if path not in set(PATHS.values()) - {None}:
        raise ValueError
    body = json.dumps(payload, allow_nan=False).encode()
    if len(body) > MAX_INPUT:
        raise ValueError
    request = urllib.request.Request(
        UPSTREAM + path,
        data=body,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    try:
        response = opener(request, timeout=10)
    except urllib.error.HTTPError as error:
        response = error
    with response as opened:
        status = opened.status
        raw = opened.read(MAX_RESPONSE + 1)
    if len(raw) > MAX_RESPONSE:
        raise ValueError
    data = decode(raw)
    if type(data) is not dict:
        raise ValueError
    return status, data


ALIASES = frozenset({"capital-one", "usaa", "amex", "empower"})
PATHS = {
    "listItems": None,
    "getAccounts": "/accounts/get",
    "getTransactions": "/transactions/get",
    "getItemStatus": "/item/get",
    "getRecurringTransactions": "/transactions/recurring/get",
    "getLiabilities": "/liabilities/get",
    "getHoldings": "/investments/holdings/get",
}
MAX_INPUT = 16384
MAX_SECRET = 65536


def failure(message):
    return {"isError": True, "content": [{"type": "text", "text": message}]}


def validate(event, tool_name):
    if not isinstance(tool_name, str) or not tool_name.startswith("plaid___"):
        raise ValueError
    name = tool_name.removeprefix("plaid___")
    if name not in PATHS or type(event) is not dict:
        raise ValueError
    if len(json.dumps(event, allow_nan=False).encode()) > MAX_INPUT:
        raise ValueError
    required = set() if name == "listItems" else {"item"}
    allowed = set(required)
    if name == "getTransactions":
        required |= {"startDate", "endDate"}
        allowed |= required | {"count", "offset"}
    if set(event) - allowed or required - set(event):
        raise ValueError
    if name != "listItems" and (
        type(event["item"]) is not str or event["item"] not in ALIASES
    ):
        raise ValueError
    if name == "getTransactions":
        dates = []
        for key in ["startDate", "endDate"]:
            value = event[key]
            if type(value) is not str or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
                raise ValueError
            dates.append(datetime.date.fromisoformat(value))
        if dates[0] > dates[1]:
            raise ValueError
        for key, default, minimum, maximum in [
            ("count", 100, 1, 500),
            ("offset", 0, 0, 2147483647),
        ]:
            value = event.get(key, default)
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError
    return name


def credentials(store, env):
    raw = store.get_secret_value(SecretId=env["SECRETS_ARN"])["SecretString"]
    if type(raw) is not str or len(raw.encode()) > MAX_SECRET:
        raise ValueError
    secret = decode(raw)
    if type(secret) is not dict or set(secret) != {"client_id", "secret", "items"}:
        raise ValueError
    if any(
        type(secret[k]) is not str or not 1 <= len(secret[k]) <= 4096
        for k in ["client_id", "secret"]
    ):
        raise ValueError
    items = secret["items"]
    if type(items) is not dict or not items or set(items) - ALIASES:
        raise ValueError
    for item in items.values():
        if type(item) is not dict or set(item) != {
            "access_token",
            "institution_name",
            "products",
        }:
            raise ValueError
        if any(
            type(item[k]) is not str or not 1 <= len(item[k]) <= 4096
            for k in ["access_token", "institution_name"]
        ):
            raise ValueError
        products = item["products"]
        if (
            type(products) is not list
            or not products
            or any(
                type(p) is not str
                or p not in {"transactions", "liabilities", "investments"}
                for p in products
            )
            or len(products) != len(set(products))
        ):
            raise ValueError
    return secret


def handle(event, tool_name, store, env, opener):
    try:
        name = validate(event, tool_name)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return failure("Invalid Plaid tool arguments")
    try:
        secret = credentials(store, env)
    except Exception:
        return failure("Plaid credentials unavailable or invalid")
    values = [secret["client_id"], secret["secret"]] + [
        i["access_token"] for i in secret["items"].values()
    ]
    if name == "listItems":
        return sanitize(
            {
                "items": [
                    {
                        "alias": alias,
                        "institution_name": item["institution_name"],
                        "products": item["products"],
                    }
                    for alias, item in secret["items"].items()
                ]
            },
            values,
        )
    item = secret["items"].get(event["item"])
    if item is None:
        return failure("Plaid Item is not configured")
    product = {
        "getTransactions": "transactions",
        "getLiabilities": "liabilities",
        "getHoldings": "investments",
        "getRecurringTransactions": "transactions",
    }.get(name)
    if product and product not in item["products"]:
        return failure(
            "Plaid Item has not consented to the required product: " + product
        )
    payload = {
        "client_id": secret["client_id"],
        "secret": secret["secret"],
        "access_token": item["access_token"],
    }
    recurring_note = (
        " Recurring transactions may require additional Plaid entitlement."
        if name == "getRecurringTransactions"
        else ""
    )
    if name == "getTransactions":
        payload.update(
            start_date=event["startDate"],
            end_date=event["endDate"],
            options={
                "count": event.get("count", 100),
                "offset": event.get("offset", 0),
            },
        )
    try:
        status, data = post(PATHS[name], payload, opener)
        data = sanitize(data, values)
        if not 200 <= status < 300:
            safe = {
                key: value
                for key in ["error_code", "request_id"]
                if type(value := data.get(key)) is str
                and re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value)
            }
            return failure("Plaid request failed " + json.dumps(safe) + recurring_note)
        if name == "getTransactions":
            transactions, total = (
                data.get("transactions"),
                data.get("total_transactions"),
            )
            offset, count = event.get("offset", 0), event.get("count", 100)
            if type(transactions) is not list or type(total) is not int or total < 0:
                raise ValueError
            if (
                len(transactions) > count
                or (transactions and offset + len(transactions) > total)
                or (not transactions and offset < total)
            ):
                raise ValueError
            next_offset = offset + len(transactions)
            data.update(
                offset=offset,
                count=count,
                next_offset=next_offset if next_offset < total else None,
            )
        if name == "getItemStatus":
            data["configured_products"] = item["products"]
        if name == "getRecurringTransactions":
            data["recurring_note"] = (
                "Requires Plaid recurring transactions entitlement in addition to "
                "transactions consent; no products are initialized by this tool."
            )
        if len(json.dumps(data, allow_nan=False).encode()) > MAX_RESPONSE:
            raise ValueError
        return data
    except Exception:
        return failure(
            "Plaid request failed or response exceeded limits" + recurring_note
        )


def handler(event, context):
    import boto3
    from botocore.config import Config

    custom = getattr(getattr(context, "client_context", None), "custom", None) or {}
    return handle(
        event,
        custom.get("bedrockAgentCoreToolName", ""),
        boto3.client(
            "secretsmanager",
            config=Config(
                connect_timeout=1, read_timeout=1, retries={"total_max_attempts": 1}
            ),
        ),
        os.environ,
        urllib.request.build_opener(NoRedirect()).open,
    )
