#!/usr/bin/env bash
export_credentials() {
  local account=$1 response=$2 value
  AWS_ACCESS_KEY_ID=$(jq -er .Credentials.AccessKeyId <<<"$response")
  AWS_SECRET_ACCESS_KEY=$(jq -er .Credentials.SecretAccessKey <<<"$response")
  AWS_SESSION_TOKEN=$(jq -er .Credentials.SessionToken <<<"$response")
  for value in "$AWS_ACCESS_KEY_ID" "$AWS_SECRET_ACCESS_KEY" "$AWS_SESSION_TOKEN"; do
    echo "::add-mask::$value"
  done
  export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN
  test "$(aws sts get-caller-identity --query Account --output text)" = "$account"
}

assume_with_github_oidc() {
  local role=$1 session=$2 account=$3 token
  token=$(curl -fsS -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
    "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=sts.amazonaws.com" | jq -er .value)
  echo "::add-mask::$token"
  export_credentials "$account" "$(aws sts assume-role-with-web-identity --role-arn "$role" \
    --role-session-name "$session" --web-identity-token "$token" --duration-seconds 900 --output json)"
}

assume_chained_role() {
  local role=$1 session=$2 account=$3
  export_credentials "$account" "$(aws sts assume-role --role-arn "$role" \
    --role-session-name "$session" --duration-seconds 900 --output json)"
}
