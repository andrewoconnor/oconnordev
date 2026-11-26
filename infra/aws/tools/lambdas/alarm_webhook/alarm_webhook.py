import hashlib
import hmac
import json
import os
import time
import urllib.request

TIMEOUT_SECONDS = 10


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def alarm_payload(event):
    detail = event["detail"]
    return {
        "AlarmName": detail["alarmName"],
        "NewStateValue": detail["state"]["value"],
        "OldStateValue": detail["previousState"]["value"],
        "NewStateReason": detail["state"]["reason"],
        "AWSAccountId": event["account"],
        "Region": event["region"],
    }


def signature(secret, timestamp, body):
    message = timestamp.encode() + b"." + body
    return hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()


def handle(event, url, secret, opener, now):
    if not url.startswith("https://"):
        raise ValueError("The webhook URL must use HTTPS")
    body = json.dumps(alarm_payload(event), separators=(",", ":")).encode()
    timestamp = str(int(now))
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Request-ID": event["id"],
            "X-Webhook-Timestamp": timestamp,
            "X-Webhook-Signature-V2": signature(secret, timestamp, body),
        },
    )
    with opener.open(request, timeout=TIMEOUT_SECONDS) as response:
        return response.status


def handler(event, context):
    import boto3

    parameter = boto3.client("ssm").get_parameter(
        Name=os.environ["SECRET_PARAMETER_NAME"], WithDecryption=True
    )
    return handle(
        event,
        os.environ["WEBHOOK_URL"],
        parameter["Parameter"]["Value"],
        urllib.request.build_opener(NoRedirect),
        time.time(),
    )
