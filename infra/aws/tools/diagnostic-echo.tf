locals {
  echo_function_name = "hermes-gateway-echo"
  echo_handler       = <<-PYTHON
    import base64
    import json

    HIDDEN = {"authorization", "x-amz-security-token", "x-amz-date", "x-amz-content-sha256"}


    def handler(event, context):
        body = event.get("body") or ""
        if event.get("isBase64Encoded"):
            body = base64.b64decode(body).decode("utf-8", "replace")
        echoed = {
            "method": event.get("requestContext", {}).get("http", {}).get("method"),
            "path": event.get("rawPath"),
            "query": event.get("rawQueryString"),
            "headers": {k: v for k, v in (event.get("headers") or {}).items() if k.lower() not in HIDDEN},
            "body_length": len(body),
            "body": body[:500],
        }
        return {"statusCode": 200, "headers": {"content-type": "application/json"}, "body": json.dumps(echoed)}
  PYTHON
  echo_openapi = {
    openapi = "3.0.3"
    info    = { title = "Gateway request echo", version = "1.0.0" }
    servers = [{ url = trimsuffix(aws_lambda_function_url.echo.function_url, "/") }]
    paths = {
      "/marketdata/v1/quotes" = {
        get = {
          operationId = "echoGet"
          summary     = "Echo the request the gateway sends for a GET with query parameters."
          parameters = [
            { name = "symbols", in = "query", required = true, schema = { type = "string" } },
            { name = "fields", in = "query", schema = { type = "string" } },
          ]
          responses = local.schwab_json_response
        }
      }
    }
  }
}

data "archive_file" "echo" {
  type                    = "zip"
  source_content          = local.echo_handler
  source_content_filename = "echo.py"
  output_path             = "${path.module}/.terraform-archives/echo.zip"
}

resource "aws_iam_role" "echo" {
  name = "hermes-gateway-echo"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }]
  })
}

resource "aws_lambda_function" "echo" {
  # checkov:skip=CKV_AWS_116:Temporary diagnostic; synchronous Function URL calls only.
  # checkov:skip=CKV_AWS_117:Temporary diagnostic with no network dependencies.
  # checkov:skip=CKV_AWS_173:No environment variables.
  # checkov:skip=CKV_AWS_272:Code signing is not configured for this account.
  # checkov:skip=CKV_AWS_50:Temporary diagnostic.
  # checkov:skip=CKV_AWS_115:Reserved concurrency is set to 1.
  function_name                  = local.echo_function_name
  role                           = aws_iam_role.echo.arn
  handler                        = "echo.handler"
  runtime                        = "python3.13"
  architectures                  = ["arm64"]
  timeout                        = 5
  memory_size                    = 128
  reserved_concurrent_executions = 1
  filename                       = data.archive_file.echo.output_path
  source_code_hash               = data.archive_file.echo.output_base64sha256
}

resource "aws_lambda_function_url" "echo" {
  function_name      = aws_lambda_function.echo.function_name
  authorization_type = "AWS_IAM"
}

data "aws_iam_policy_document" "echo_gateway_invoke" {
  statement {
    actions   = ["lambda:InvokeFunctionUrl"]
    resources = [aws_lambda_function.echo.arn]
    condition {
      test     = "StringEquals"
      variable = "lambda:FunctionUrlAuthType"
      values   = ["AWS_IAM"]
    }
  }
  statement {
    actions   = ["lambda:InvokeFunction"]
    resources = [aws_lambda_function.echo.arn]
    condition {
      test     = "Bool"
      variable = "lambda:InvokedViaFunctionUrl"
      values   = ["true"]
    }
  }
}

resource "aws_iam_role_policy" "echo_gateway_invoke" {
  name   = "diagnostic-echo-function-url"
  role   = aws_iam_role.hermes_gateway.id
  policy = data.aws_iam_policy_document.echo_gateway_invoke.json
}

resource "aws_bedrockagentcore_gateway_target" "echo" {
  name               = "echo"
  gateway_identifier = aws_bedrockagentcore_gateway.hermes.gateway_id
  description        = "Temporary diagnostic: echoes the HTTP request the gateway builds for an OpenAPI GET."

  credential_provider_configuration {
    gateway_iam_role {
      service = "lambda"
      region  = "us-east-1"
    }
  }

  target_configuration {
    mcp {
      open_api_schema {
        inline_payload {
          payload = jsonencode(local.echo_openapi)
        }
      }
    }
  }

  depends_on = [aws_iam_role_policy.echo_gateway_invoke, aws_iam_role_policy.hermes_gateway_policy_authorization]
}

resource "aws_bedrockagentcore_policy" "echo" {
  name             = "HermesDiagnosticEcho"
  policy_engine_id = aws_bedrockagentcore_policy_engine.hermes.policy_engine_id
  description      = "Temporary diagnostic permit for echo___echoGet."
  validation_mode  = "FAIL_ON_ANY_FINDINGS"

  definition {
    cedar {
      statement = <<-CEDAR
        permit (
          principal is AgentCore::OAuthUser,
          action == AgentCore::Action::"echo___echoGet",
          resource == AgentCore::Gateway::"${aws_bedrockagentcore_gateway.hermes.gateway_arn}"
        )
        when {
          principal.hasTag("scope") &&
          principal.getTag("scope") like "*${aws_cognito_resource_server.hermes.scope_identifiers[0]}*"
        };
      CEDAR
    }
  }

  depends_on = [aws_bedrockagentcore_gateway_target.echo]
}
