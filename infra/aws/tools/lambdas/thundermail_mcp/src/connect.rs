//! Password/TLS branch adapted from pinned upstream connect_authenticated, lines 124–162/195–210.
//! No account config, home files, environment selectors, OAuth or plaintext production branch.
use crate::{
    Endpoint, Result,
    budget::Budget,
    upstream_imap::{ImapSession, ImapStream},
};
use std::sync::Arc;
pub const HOST: &str = "mail.thundermail.com";
pub const OWNER: &str = "oconnor@thundermail.com";
pub const PORT: u16 = 993;
pub async fn connect(endpoint: Endpoint, password: String) -> Result<ImapSession> {
    if password.is_empty() || password.len() > 4096 {
        return Err("Invalid stored credential".into());
    }
    let stream = match endpoint {
        Endpoint::Production => {
            let tcp = tokio::net::TcpStream::connect((HOST, PORT))
                .await
                .map_err(|_| "IMAP connection failed")?;
            let mut roots = rustls::RootCertStore::empty();
            roots.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());
            let config = rustls::ClientConfig::builder_with_provider(Arc::new(
                rustls::crypto::ring::default_provider(),
            ))
            .with_safe_default_protocol_versions()
            .map_err(|_| "TLS configuration failed")?
            .with_root_certificates(roots)
            .with_no_client_auth();
            let connector = tokio_rustls::TlsConnector::from(Arc::new(config));
            let name =
                rustls_pki_types::ServerName::try_from(HOST).map_err(|_| "TLS name invalid")?;
            ImapStream::Tls(
                connector
                    .connect(name, tcp)
                    .await
                    .map_err(|_| "TLS handshake failed")?,
            )
        }
        #[cfg(test)]
        Endpoint::Loopback(addr) => {
            assert!(addr.ip().is_loopback());
            ImapStream::Plain(
                tokio::net::TcpStream::connect(addr)
                    .await
                    .map_err(|_| "Fixture connect failed")?,
            )
        }
    };
    let mut client = async_imap::Client::new(Budget::new(stream));
    if client
        .read_response()
        .await
        .map_err(|_| "IMAP greeting failed")?
        .is_none()
    {
        return Err("IMAP closed before greeting".into());
    }
    client
        .login(OWNER, password.as_str())
        .await
        .map_err(|_| "IMAP authentication failed".into())
}
