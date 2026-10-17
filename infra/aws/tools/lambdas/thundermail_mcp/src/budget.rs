//! Decrypted per-connection transfer budget, enforced before async-imap parsing.
use std::{
    pin::Pin,
    task::{Context, Poll},
};
use tokio::io::{AsyncRead, AsyncWrite, ReadBuf};
#[derive(Debug)]
pub struct Budget<T> {
    inner: T,
    read_left: usize,
    write_left: usize,
}
impl<T> Budget<T> {
    pub fn new(inner: T) -> Self {
        Self {
            inner,
            read_left: 262144,
            write_left: 16384,
        }
    }
}
fn exceeded() -> std::io::Error {
    std::io::Error::other("IMAP transfer budget exceeded")
}
impl<T: AsyncRead + Unpin> AsyncRead for Budget<T> {
    fn poll_read(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        buf: &mut ReadBuf<'_>,
    ) -> Poll<std::io::Result<()>> {
        let this = self.get_mut();
        if this.read_left == 0 {
            return Poll::Ready(Err(exceeded()));
        }
        let n = buf.remaining().min(this.read_left);
        let mut sub = ReadBuf::new(buf.initialize_unfilled_to(n));
        match Pin::new(&mut this.inner).poll_read(cx, &mut sub) {
            Poll::Ready(Ok(())) => {
                let n = sub.filled().len();
                this.read_left -= n;
                buf.advance(n);
                Poll::Ready(Ok(()))
            }
            x => x,
        }
    }
}
impl<T: AsyncWrite + Unpin> AsyncWrite for Budget<T> {
    fn poll_write(
        self: Pin<&mut Self>,
        cx: &mut Context<'_>,
        b: &[u8],
    ) -> Poll<std::io::Result<usize>> {
        let this = self.get_mut();
        if b.len() > this.write_left {
            return Poll::Ready(Err(exceeded()));
        }
        match Pin::new(&mut this.inner).poll_write(cx, b) {
            Poll::Ready(Ok(n)) => {
                this.write_left -= n;
                Poll::Ready(Ok(n))
            }
            x => x,
        }
    }
    fn poll_flush(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_flush(cx)
    }
    fn poll_shutdown(self: Pin<&mut Self>, cx: &mut Context<'_>) -> Poll<std::io::Result<()>> {
        Pin::new(&mut self.get_mut().inner).poll_shutdown(cx)
    }
}
