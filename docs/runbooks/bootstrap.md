# Bootstrap and dependency ordering

1. Apply `infra/spacelift` first to create the stack graph and AWS integration. The account bootstrap roles must already exist because each account stack assumes its own role.
2. Apply `infra/aws/general` before `infra/aws/security` so Organizations and delegated-administrator registrations exist.
3. Apply the security account's central audit buckets before enabling the management-account CloudTrail and Config writers. The general-account recorder and trail are gated to avoid creation before their destination buckets exist.
4. Apply `infra/aws/security` before `infra/aws/hermes`; the Hermes AWS target consumes the generated security gateway URL and ARN through Spacelift references.
5. Apply `infra/aws/hermes` before `infra/aws/production`; the CloudFront endpoint consumes the generated Hermes Gateway origin hostname.
6. For each refactor PR, inspect each speculative plan and confirm only address moves/in-place or no-op changes are present before applying. A merge does not itself apply infrastructure.

## Existing audit migration state

The management-account trail is currently represented in the General Spacelift state at `aws_cloudtrail.organization[0]`; the corresponding address is present in live state. Do not repeat the historical `state rm`/`import` migration described in old notes. The latest inspected Spacelift entity list shows this address already managed in General. If that live fact changes before applying, stop and reconcile state rather than allowing either stack to destroy or recreate the trail.

## State-preserving Spacelift refactor

The Spacelift stack and integration-attachment resources are being consolidated with `for_each`. `infra/spacelift/moved.tf` maps each existing singleton address to its keyed instance. Review the speculative plan and require Terraform to report address moves, not destroys/recreates, for the existing stack objects and attachments.