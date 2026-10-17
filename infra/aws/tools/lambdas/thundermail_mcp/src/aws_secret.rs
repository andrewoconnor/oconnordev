//! Runtime-only Secrets Manager adapter. No credential-chain or endpoint overrides.
use crate::{Result, SecretStore};
use aws_sdk_secretsmanager::Client;

pub struct AwsSecretStore {
    secret_arn: String,
    function_arn: String,
    client: Option<Client>,
}
impl AwsSecretStore {
    pub fn runtime(secret_arn: String, function_arn: String) -> Self {
        Self {
            secret_arn,
            function_arn,
            client: None,
        }
    }
}
impl SecretStore for AwsSecretStore {
    async fn get(&self) -> Result<String> {
        let region = validate_arn(&self.secret_arn, &self.function_arn)?;
        let client = match &self.client {
            Some(client) => client.clone(),
            None => runtime_client(region)?,
        };
        let output = tokio::time::timeout(
            std::time::Duration::from_secs(2),
            client
                .get_secret_value()
                .secret_id(&self.secret_arn)
                .version_stage("AWSCURRENT")
                .send(),
        )
        .await
        .map_err(|_| "SecretStoreGet unavailable".to_string())?
        .map_err(|_| "SecretStoreGet unavailable".to_string())?;
        if output.arn() != Some(self.secret_arn.as_str()) || output.secret_binary().is_some() {
            return Err("SecretStoreGet unavailable".into());
        }
        let secret = output.secret_string().ok_or("SecretStoreGet unavailable")?;
        if secret.len() > 16384 {
            return Err("SecretStoreGet unavailable".into());
        }
        let envelope: Envelope =
            serde_json::from_str(secret).map_err(|_| "SecretStoreGet unavailable".to_string())?;
        if envelope.version != 1
            || envelope.password.is_empty()
            || envelope.password.len() > 4096
            || envelope.password.chars().any(char::is_control)
        {
            return Err("SecretStoreGet unavailable".into());
        }
        Ok(envelope.password)
    }
}
#[derive(serde::Deserialize)]
#[serde(deny_unknown_fields)]
struct Envelope {
    version: u8,
    password: String,
}
/// Fixed owner credential path; IAM must additionally grant only this complete ARN.
pub const SECRET_PATH: &str = "/hermes/thundermail/app-password";
fn validate_arn<'a>(secret: &str, function: &'a str) -> Result<&'a str> {
    let bad = || "SecretStoreGet unavailable".to_string();
    let f: Vec<&str> = function.split(':').collect();
    if !(7..=8).contains(&f.len())
        || f[..3] != ["arn", "aws", "lambda"]
        || f[3].len() > 32
        || f[3].split('-').count() < 3
        || !f[3]
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'-')
        || f[4].len() != 12
        || !f[4].bytes().all(|b| b.is_ascii_digit())
        || f[5] != "function"
        || f[6].is_empty()
        || f[6].len() > 64
        || !f[6]
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
        || (f.len() == 8
            && (f[7].is_empty()
                || f[7].len() > 128
                || !f[7]
                    .bytes()
                    .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_' || b == b'$')))
    {
        return Err(bad());
    }
    let prefix = format!(
        "arn:aws:secretsmanager:{}:{}:secret:{SECRET_PATH}-",
        f[3], f[4]
    );
    let suffix = secret.strip_prefix(&prefix).ok_or_else(bad)?;
    if suffix.len() != 6 || !suffix.bytes().all(|b| b.is_ascii_alphanumeric()) {
        return Err(bad());
    }
    Ok(f[3])
}
fn runtime_client(region: &str) -> Result<Client> {
    use aws_sdk_secretsmanager::config::{
        BehaviorVersion, Credentials, Region, retry::RetryConfig, timeout::TimeoutConfig,
    };
    let unavailable = || "SecretStoreGet unavailable".to_string();
    // Lambda execution-role credentials only: no profile, IMDS, STS, web identity, or token request.
    let credentials = Credentials::new(
        std::env::var("AWS_ACCESS_KEY_ID").map_err(|_| unavailable())?,
        std::env::var("AWS_SECRET_ACCESS_KEY").map_err(|_| unavailable())?,
        Some(std::env::var("AWS_SESSION_TOKEN").map_err(|_| unavailable())?),
        None,
        "LambdaExecutionRole",
    );
    let http = aws_smithy_http_client::Builder::new()
        .tls_provider(aws_smithy_http_client::tls::Provider::Rustls(
            aws_smithy_http_client::tls::rustls_provider::CryptoMode::Ring,
        ))
        .build_https();
    Ok(Client::from_conf(
        aws_sdk_secretsmanager::Config::builder()
            .behavior_version(BehaviorVersion::latest())
            .region(Region::new(region.to_owned()))
            .credentials_provider(credentials)
            .http_client(http)
            .retry_config(RetryConfig::disabled())
            .timeout_config(
                TimeoutConfig::builder()
                    .operation_timeout(std::time::Duration::from_secs(2))
                    .build(),
            )
            .build(),
    ))
}
#[cfg(test)]
pub(crate) mod tests {
    use super::*;
    use aws_sdk_secretsmanager::config::{BehaviorVersion, Credentials, Region};
    use aws_smithy_http_client::test_util::capture_request;
    use aws_smithy_types::body::SdkBody;
    const ARN: &str = "arn:aws:secretsmanager:us-east-1:123456789012:secret:/hermes/thundermail/app-password-Ab12Cd";
    const FUNCTION: &str = "arn:aws:lambda:us-east-1:123456789012:function:thundermail";
    fn mock(
        body: serde_json::Value,
    ) -> (
        AwsSecretStore,
        aws_smithy_http_client::test_util::CaptureRequestReceiver,
    ) {
        let (http, rx) = capture_request(Some(
            http::Response::builder()
                .status(200)
                .body(SdkBody::from(body.to_string()))
                .unwrap(),
        ));
        let client = Client::from_conf(
            aws_sdk_secretsmanager::Config::builder()
                .behavior_version(BehaviorVersion::latest())
                .region(Region::new("us-east-1"))
                .credentials_provider(Credentials::new(
                    "synthetic",
                    "synthetic",
                    Some("synthetic".into()),
                    None,
                    "test",
                ))
                .http_client(http)
                .build(),
        );
        (
            AwsSecretStore {
                secret_arn: ARN.into(),
                function_arn: FUNCTION.into(),
                client: Some(client),
            },
            rx,
        )
    }
    pub(crate) fn synthetic() -> (
        AwsSecretStore,
        aws_smithy_http_client::test_util::CaptureRequestReceiver,
    ) {
        mock(
            serde_json::json!({"ARN":ARN,"SecretString":r#"{"version":1,"password":"synthetic-only"}"#}),
        )
    }
    pub(crate) fn assert_get(rx: aws_smithy_http_client::test_util::CaptureRequestReceiver) {
        let request = rx.expect_request();
        assert_eq!(
            request.uri(),
            "https://secretsmanager.us-east-1.amazonaws.com/"
        );
        let body: serde_json::Value =
            serde_json::from_slice(request.body().bytes().unwrap()).unwrap();
        assert_eq!(
            body,
            serde_json::json!({"SecretId":ARN,"VersionStage":"AWSCURRENT"})
        );
        assert_eq!(
            request.headers().get("x-amz-target"),
            Some("secretsmanager.GetSecretValue")
        );
    }
    fn event(
        tool: &str,
        args: serde_json::Value,
    ) -> lambda_runtime::LambdaEvent<serde_json::Value> {
        let mut context = lambda_runtime::Context::default();
        context.client_context = Some(
            serde_json::from_value(serde_json::json!({"custom":{"bedrockAgentCoreToolName":tool}}))
                .unwrap(),
        );
        lambda_runtime::LambdaEvent::new(args, context)
    }
    #[tokio::test]
    async fn invalid_dispatch_never_calls_production_sdk_adapter() {
        for (tool, args) in [
            ("thundermail___delete_message", serde_json::json!({})),
            (
                "thundermail___imap_list_mailboxes",
                serde_json::json!({"account":"evil"}),
            ),
            (
                "thundermail___imap_search_messages",
                serde_json::json!({"mailbox":"INBOX","host":"evil"}),
            ),
            (
                "thundermail___imap_get_message",
                serde_json::json!({"mailbox":"INBOX","uid":0,"uid_validity":1}),
            ),
        ] {
            let (store, rx) = synthetic();
            let output = crate::handle(event(tool, args), &store).await;
            assert_eq!(output["isError"], true);
            rx.expect_no_request();
        }
    }
    #[tokio::test]
    async fn sdk_service_error_is_redacted_at_provider_and_dispatch() {
        for dispatch in [false, true] {
            let (http,rx) = capture_request(Some(http::Response::builder().status(400)
                .header("x-amzn-errortype", "AccessDeniedException")
                .body(SdkBody::from(r#"{"__type":"AccessDeniedException","Message":"synthetic-provider-private-detail"}"#)).unwrap()));
            let client = Client::from_conf(
                aws_sdk_secretsmanager::Config::builder()
                    .behavior_version(BehaviorVersion::latest())
                    .region(Region::new("us-east-1"))
                    .credentials_provider(Credentials::new(
                        "synthetic",
                        "synthetic",
                        None,
                        None,
                        "test",
                    ))
                    .http_client(http)
                    .build(),
            );
            let store = AwsSecretStore {
                secret_arn: ARN.into(),
                function_arn: FUNCTION.into(),
                client: Some(client),
            };
            if dispatch {
                let output = crate::handle(
                    event("thundermail___imap_list_mailboxes", serde_json::json!({})),
                    &store,
                )
                .await;
                assert_eq!(output["content"][0]["text"], "SecretStoreGet unavailable");
                assert!(
                    !output
                        .to_string()
                        .contains("synthetic-provider-private-detail")
                );
            } else {
                assert_eq!(store.get().await, Err("SecretStoreGet unavailable".into()));
            }
            assert_get(rx);
        }
    }
    #[tokio::test]
    async fn sdk_rejects_invalid_envelopes_without_echoing_values() {
        for secret in [
            r#"{"version":2,"password":"synthetic-only"}"#.into(),
            r#"{"version":1,"password":"synthetic-only","host":"evil"}"#.into(),
            r#"{"version":1,"password":""}"#.into(),
            serde_json::json!({"version":1,"password":"synthetic\nonly"}).to_string(),
            serde_json::json!({"version":1,"password":"x".repeat(4097)}).to_string(),
            format!("{}{}", " ".repeat(16384), r#"{"version":1,"password":"x"}"#),
            r#"{"version":1,"version":1,"password":"synthetic-only"}"#.into(),
            r#"{"password":"synthetic-only"}"#.into(),
            "not JSON synthetic-only".into(),
        ] {
            let (store, _) = mock(serde_json::json!({"ARN":ARN,"SecretString":secret}));
            assert_eq!(store.get().await, Err("SecretStoreGet unavailable".into()));
        }
        for body in [
            serde_json::json!({"ARN":ARN,"SecretBinary":"c3ludGhldGlj"}),
            serde_json::json!({"ARN":"other","SecretString":r#"{"version":1,"password":"synthetic-only"}"#}),
            serde_json::json!({"SecretString":r#"{"version":1,"password":"synthetic-only"}"#}),
            serde_json::json!({"ARN":ARN,"SecretString":r#"{"version":1,"password":"synthetic-only"}"#,"SecretBinary":"eA=="}),
        ] {
            let (store, _) = mock(body);
            assert_eq!(store.get().await, Err("SecretStoreGet unavailable".into()));
        }
    }
    #[tokio::test]
    async fn wrong_arn_is_rejected_before_sdk_transport() {
        for arn in [
            ARN.replace("123456789012", "999999999999"),
            ARN.replace("us-east-1", "us-west-2"),
            ARN.replace("/hermes/thundermail/app-password", "other/credentials"),
            ARN.replace("-Ab12Cd", "-*"),
            ARN.replace("-Ab12Cd", ""),
            ARN.replace("arn:aws:", "arn:aws-cn:"),
            format!("{ARN}:extra"),
            String::new(),
        ] {
            let (mut store, rx) = mock(
                serde_json::json!({"ARN":ARN,"SecretString":r#"{"version":1,"password":"synthetic-only"}"#}),
            );
            store.secret_arn = arn;
            assert_eq!(store.get().await, Err("SecretStoreGet unavailable".into()));
            rx.expect_no_request();
        }
        for function in [
            "",
            "arn:aws:lambda:us-east-1:123:function:x",
            "arn:aws:lambda:us-east-1:123456789012:function:",
        ] {
            let (mut store, rx) = mock(
                serde_json::json!({"ARN":ARN,"SecretString":r#"{"version":1,"password":"synthetic-only"}"#}),
            );
            store.function_arn = function.into();
            assert_eq!(store.get().await, Err("SecretStoreGet unavailable".into()));
            rx.expect_no_request();
        }
    }
    #[tokio::test]
    async fn provider_deadline_bounds_mocked_sdk_transport() {
        let http = aws_smithy_http_client::test_util::NeverClient::new();
        let client = Client::from_conf(
            aws_sdk_secretsmanager::Config::builder()
                .behavior_version(BehaviorVersion::latest())
                .region(Region::new("us-east-1"))
                .credentials_provider(Credentials::new(
                    "synthetic",
                    "synthetic",
                    Some("synthetic".into()),
                    None,
                    "test",
                ))
                .http_client(http.clone())
                .build(),
        );
        let store = AwsSecretStore {
            secret_arn: ARN.into(),
            function_arn: FUNCTION.into(),
            client: Some(client),
        };
        let result =
            tokio::time::timeout(std::time::Duration::from_millis(2800), store.get()).await;
        assert_eq!(result, Ok(Err("SecretStoreGet unavailable".into())));
        assert_eq!(http.num_calls(), 1);
    }
    #[tokio::test]
    async fn sdk_get_uses_exact_arn_and_versioned_password_envelope() {
        let (store, rx) = synthetic();
        assert_eq!(store.get().await.unwrap(), "synthetic-only");
        assert_get(rx);
    }
}
