//! Native Lambda: no SDK request, credential lookup, or secret retrieval at bootstrap.
use lambda_runtime::{Error, LambdaEvent, run, service_fn};
use serde_json::Value;
use thundermail_native_read::{aws_secret::AwsSecretStore, handle};

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Error> {
    run(service_fn(|event: LambdaEvent<Value>| async move {
        let store = AwsSecretStore::runtime(
            std::env::var("THUNDERMAIL_CREDENTIAL_SECRET_ARN").unwrap_or_default(),
            event.context.invoked_function_arn.clone(),
        );
        Ok::<_, Error>(handle(event, &store).await)
    }))
    .await
}
