//! How a running application tells whoever else writes its project, and
//! how it hears back. Port of `core/live.py` and `app/live_server.py`.
//!
//! The MCP server writes a project whether or not the application is open,
//! so the notification is a bonus and never a dependency: it is sent when
//! somebody is listening and dropped otherwise. Nothing waits for it and
//! nothing fails without it.
//!
//! The application is the one that listens, the MCP server being spawned
//! by its client on demand and dying with it, so it has no address
//! anybody could keep. It publishes where it listens in the project
//! itself, beside the database it is showing, in the same
//! `.rts/live.json` the Python application writes.
//!
//! The token is what a browser cannot have. A server bound to 127.0.0.1 is
//! reachable by any page open in a browser, a plain POST not being held
//! back by a preflight, so the endpoint asks for a value only something
//! with access to the disk can read. It stops nothing else: a program
//! running as the user could read the file, or simply write the database
//! itself.
//!
//! One route, one job: take the identifiers of the lines somebody else just
//! wrote and hand them to the view. Nothing is read back over it, the
//! database staying the one source of truth; the notification only says
//! where to look.

use std::path::{Path, PathBuf};
use std::sync::Arc;
use std::time::Duration;

use serde::{Deserialize, Serialize};
use tokio::io::{AsyncReadExt, AsyncWriteExt};
use tokio::net::{TcpListener, TcpStream};
use tokio::task::JoinHandle;

pub const AUTH_HEADER: &str = "X-Rts-Token";

const FILE_NAME: &str = "live.json";
const NOTIFY_TIMEOUT: Duration = Duration::from_millis(500);
const REQUEST_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_HEAD: usize = 16 * 1024;
const MAX_BODY: usize = 1024 * 1024;

/// Where a running application listens for change notifications.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LiveEndpoint {
    pub port: u16,
    pub token: String,
}

/// Where a project's live endpoint is published.
pub fn endpoint_path(project: &Path) -> PathBuf {
    project.join(".rts").join(FILE_NAME)
}

/// A fresh token for one application session: 24 random bytes in hex.
pub fn new_token() -> String {
    let mut bytes = [0u8; 24];
    getrandom::fill(&mut bytes).expect("the operating system has a source of randomness");
    bytes.iter().map(|byte| format!("{byte:02x}")).collect()
}

/// Announce where this application is listening.
pub fn publish(project: &Path, endpoint: &LiveEndpoint) -> std::io::Result<()> {
    let path = endpoint_path(project);
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)?;
    }
    let text = serde_json::to_string(endpoint).map_err(std::io::Error::other)?;
    std::fs::write(path, text)
}

/// Where the application of a project listens, if it says.
///
/// `None` when no application published one or the file cannot be
/// understood. A stale file left by a crash reads fine and simply fails to
/// answer later.
pub fn read(project: &Path) -> Option<LiveEndpoint> {
    let text = std::fs::read_to_string(endpoint_path(project)).ok()?;
    serde_json::from_str(&text).ok()
}

/// Withdraw the announcement, on the way out.
pub fn clear(project: &Path) {
    let _ = std::fs::remove_file(endpoint_path(project));
}

/// Tell the application which lines just changed, if it is listening.
///
/// Never fails. A refused connection is the ordinary case, the application
/// being closed, and a caller that had to handle it would make the
/// notification a dependency rather than a bonus. Returns whether the
/// application acknowledged.
pub async fn notify(project: &Path, block_ids: &[String]) -> bool {
    if block_ids.is_empty() {
        return false;
    }
    post(project, serde_json::json!({ "block_ids": block_ids })).await
}

/// Tell the application that too much changed to name it.
///
/// A bulk action answers with a count rather than identifiers, and a whole
/// project rewritten is a reload rather than a row update. Sending every
/// touched line instead would be a list of thousands describing a page of
/// fifty.
pub async fn notify_reload(project: &Path) -> bool {
    post(project, serde_json::json!({ "reload": true })).await
}

async fn post(project: &Path, payload: serde_json::Value) -> bool {
    let Some(endpoint) = read(project) else {
        return false;
    };
    let Ok(client) = reqwest::Client::builder().timeout(NOTIFY_TIMEOUT).build() else {
        return false;
    };
    client
        .post(format!("http://127.0.0.1:{}/changed", endpoint.port))
        .header(AUTH_HEADER, endpoint.token)
        .json(&payload)
        .send()
        .await
        .is_ok_and(|response| response.status() == reqwest::StatusCode::NO_CONTENT)
}

/// Called with the identifiers of the changed lines, or with `None` when
/// too much changed to name it and the view should reload.
pub type OnChanged = Arc<dyn Fn(Option<Vec<String>>) + Send + Sync>;

/// A local endpoint telling one view which lines changed under it.
pub struct LiveServer {
    project: PathBuf,
    task: JoinHandle<()>,
}

impl LiveServer {
    /// Open the socket, publish the endpoint, and serve.
    ///
    /// The socket is opened here, so the port is known before the server
    /// runs and can be published without waiting for it. Port 0 asks the
    /// system for a free one: a fixed port would collide with a second
    /// window, and choosing one badly would collide with whatever else
    /// runs on this machine.
    ///
    /// An error here costs live refresh and nothing else: a caller should
    /// log it and carry on, refusing to open a project over it would cost
    /// the session.
    pub async fn start(project: &Path, on_changed: OnChanged) -> std::io::Result<Self> {
        let listener = TcpListener::bind(("127.0.0.1", 0)).await?;
        let port = listener.local_addr()?.port();
        let token = new_token();
        publish(
            project,
            &LiveEndpoint {
                port,
                token: token.clone(),
            },
        )?;
        let task = tokio::spawn(async move {
            loop {
                let Ok((stream, _)) = listener.accept().await else {
                    continue;
                };
                let token = token.clone();
                let on_changed = Arc::clone(&on_changed);
                tokio::spawn(async move {
                    let _ = tokio::time::timeout(
                        REQUEST_TIMEOUT,
                        handle(stream, &token, on_changed.as_ref()),
                    )
                    .await;
                });
            }
        });
        Ok(Self {
            project: project.to_path_buf(),
            task,
        })
    }

    /// Withdraw the endpoint and shut the server down.
    pub fn stop(self) {
        clear(&self.project);
        self.task.abort();
    }
}

/// What a request asked for, once it has been read.
struct Request {
    method: String,
    path: String,
    token: Option<String>,
    body: Vec<u8>,
}

enum ReadError {
    TooLarge,
    Malformed,
}

async fn read_request(stream: &mut TcpStream) -> Result<Request, ReadError> {
    let mut buffer: Vec<u8> = Vec::new();
    let mut chunk = [0u8; 4096];
    let head_end = loop {
        if let Some(position) = buffer.windows(4).position(|window| window == b"\r\n\r\n") {
            break position;
        }
        if buffer.len() > MAX_HEAD {
            return Err(ReadError::TooLarge);
        }
        let read = stream
            .read(&mut chunk)
            .await
            .map_err(|_| ReadError::Malformed)?;
        if read == 0 {
            return Err(ReadError::Malformed);
        }
        buffer.extend_from_slice(&chunk[..read]);
    };

    let head = String::from_utf8_lossy(&buffer[..head_end]).into_owned();
    let mut lines = head.split("\r\n");
    let mut request_line = lines.next().unwrap_or("").split_whitespace();
    let method = request_line.next().unwrap_or("").to_string();
    let path = request_line.next().unwrap_or("").to_string();

    let mut token = None;
    let mut length = 0usize;
    for line in lines {
        let Some((name, value)) = line.split_once(':') else {
            continue;
        };
        let value = value.trim();
        if name.eq_ignore_ascii_case(AUTH_HEADER) {
            token = Some(value.to_string());
        } else if name.eq_ignore_ascii_case("content-length") {
            length = value.parse().map_err(|_| ReadError::Malformed)?;
        }
    }
    if length > MAX_BODY {
        return Err(ReadError::TooLarge);
    }

    let mut body = buffer[head_end + 4..].to_vec();
    while body.len() < length {
        let read = stream
            .read(&mut chunk)
            .await
            .map_err(|_| ReadError::Malformed)?;
        if read == 0 {
            return Err(ReadError::Malformed);
        }
        body.extend_from_slice(&chunk[..read]);
    }
    body.truncate(length);
    Ok(Request {
        method,
        path,
        token,
        body,
    })
}

/// Constant-time comparison, so that the time taken says nothing about how
/// much of a guessed token was right.
fn same_token(left: &str, right: &str) -> bool {
    left.len() == right.len()
        && left
            .bytes()
            .zip(right.bytes())
            .fold(0u8, |acc, (a, b)| acc | (a ^ b))
            == 0
}

async fn respond(stream: &mut TcpStream, status: &str, body: &str) {
    let response = format!(
        "HTTP/1.1 {status}\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\
         Connection: close\r\n\r\n{body}",
        body.len()
    );
    let _ = stream.write_all(response.as_bytes()).await;
    let _ = stream.shutdown().await;
}

async fn handle(
    mut stream: TcpStream,
    token: &str,
    on_changed: &(dyn Fn(Option<Vec<String>>) + Send + Sync),
) {
    let request = match read_request(&mut stream).await {
        Ok(request) => request,
        Err(ReadError::TooLarge) => {
            return respond(
                &mut stream,
                "413 Payload Too Large",
                r#"{"error":"too large"}"#,
            )
            .await;
        }
        Err(ReadError::Malformed) => {
            return respond(&mut stream, "400 Bad Request", r#"{"error":"malformed"}"#).await;
        }
    };
    if request.path != "/changed" {
        return respond(&mut stream, "404 Not Found", r#"{"error":"not found"}"#).await;
    }
    if request.method != "POST" {
        return respond(
            &mut stream,
            "405 Method Not Allowed",
            r#"{"error":"POST expected"}"#,
        )
        .await;
    }
    if !request
        .token
        .as_deref()
        .is_some_and(|given| same_token(given, token))
    {
        return respond(&mut stream, "403 Forbidden", r#"{"error":"forbidden"}"#).await;
    }
    let Ok(serde_json::Value::Object(payload)) = serde_json::from_slice(&request.body) else {
        return respond(
            &mut stream,
            "400 Bad Request",
            r#"{"error":"object expected"}"#,
        )
        .await;
    };
    if payload.get("reload") == Some(&serde_json::Value::Bool(true)) {
        on_changed(None);
        return respond(&mut stream, "204 No Content", "").await;
    }
    let Some(serde_json::Value::Array(block_ids)) = payload.get("block_ids") else {
        return respond(
            &mut stream,
            "400 Bad Request",
            r#"{"error":"block_ids expected"}"#,
        )
        .await;
    };
    let block_ids = block_ids
        .iter()
        .map(|id| match id {
            serde_json::Value::String(text) => text.clone(),
            other => other.to_string(),
        })
        .collect();
    on_changed(Some(block_ids));
    respond(&mut stream, "204 No Content", "").await;
}

#[cfg(test)]
mod tests {
    use std::sync::Mutex;

    use super::*;

    fn project(name: &str) -> PathBuf {
        let nanos = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .unwrap()
            .as_nanos();
        let dir = std::env::temp_dir().join(format!("rts-live-{name}-{nanos}"));
        std::fs::create_dir_all(&dir).unwrap();
        dir
    }

    type Seen = Arc<Mutex<Vec<Option<Vec<String>>>>>;

    async fn serve(project: &Path) -> (LiveServer, Seen) {
        let seen: Seen = Arc::new(Mutex::new(Vec::new()));
        let sink = Arc::clone(&seen);
        let server =
            LiveServer::start(project, Arc::new(move |ids| sink.lock().unwrap().push(ids)))
                .await
                .unwrap();
        (server, seen)
    }

    #[test]
    fn publish_then_read_round_trip() {
        let dir = project("round-trip");
        let endpoint = LiveEndpoint {
            port: 4242,
            token: "secret".into(),
        };
        publish(&dir, &endpoint).unwrap();
        assert_eq!(read(&dir), Some(endpoint));
    }

    #[test]
    fn the_published_file_has_the_shape_python_writes() {
        let dir = project("shape");
        publish(
            &dir,
            &LiveEndpoint {
                port: 7,
                token: "t".into(),
            },
        )
        .unwrap();
        let raw: serde_json::Value =
            serde_json::from_str(&std::fs::read_to_string(endpoint_path(&dir)).unwrap()).unwrap();
        assert_eq!(raw, serde_json::json!({"port": 7, "token": "t"}));
    }

    #[test]
    fn reading_without_an_application_or_from_a_damaged_file_gives_none() {
        let dir = project("damaged");
        assert_eq!(read(&dir), None);
        std::fs::create_dir_all(dir.join(".rts")).unwrap();
        std::fs::write(endpoint_path(&dir), "{not json").unwrap();
        assert_eq!(read(&dir), None);
        std::fs::write(endpoint_path(&dir), r#"{"port": "x"}"#).unwrap();
        assert_eq!(read(&dir), None);
    }

    #[test]
    fn clearing_withdraws_the_announcement() {
        let dir = project("clear");
        publish(
            &dir,
            &LiveEndpoint {
                port: 1,
                token: "t".into(),
            },
        )
        .unwrap();
        clear(&dir);
        assert_eq!(read(&dir), None);
        clear(&dir);
    }

    #[test]
    fn tokens_are_long_and_never_repeat() {
        let (first, second) = (new_token(), new_token());
        assert_eq!(first.len(), 48);
        assert_ne!(first, second);
    }

    #[tokio::test]
    async fn notifying_without_a_listener_is_silent() {
        let dir = project("silent");
        assert!(!notify(&dir, &["a".to_string()]).await);
        assert!(!notify_reload(&dir).await);
        publish(
            &dir,
            &LiveEndpoint {
                port: 1,
                token: "t".into(),
            },
        )
        .unwrap();
        assert!(!notify(&dir, &["a".to_string()]).await);
    }

    #[tokio::test]
    async fn nothing_to_say_sends_nothing() {
        let dir = project("nothing");
        let (server, seen) = serve(&dir).await;
        assert!(!notify(&dir, &[]).await);
        assert!(seen.lock().unwrap().is_empty());
        server.stop();
    }

    #[tokio::test]
    async fn a_notification_reaches_the_listener() {
        let dir = project("reaches");
        let (server, seen) = serve(&dir).await;

        assert!(notify(&dir, &["a".to_string(), "b".to_string()]).await);
        assert!(notify_reload(&dir).await);

        assert_eq!(
            *seen.lock().unwrap(),
            vec![Some(vec!["a".to_string(), "b".to_string()]), None]
        );
        server.stop();
    }

    async fn raw_post(port: u16, head_extra: &str, path: &str, body: &str) -> String {
        let mut stream = TcpStream::connect(("127.0.0.1", port)).await.unwrap();
        let request = format!(
            "POST {path} HTTP/1.1\r\nHost: x\r\n{head_extra}Content-Length: {}\r\n\r\n{body}",
            body.len()
        );
        stream.write_all(request.as_bytes()).await.unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).await.unwrap();
        response
    }

    #[tokio::test]
    async fn a_wrong_or_missing_token_is_refused_and_tells_nobody() {
        let dir = project("token");
        let (server, seen) = serve(&dir).await;
        let endpoint = read(&dir).unwrap();

        let wrong = raw_post(
            endpoint.port,
            "X-Rts-Token: nope\r\n",
            "/changed",
            r#"{"reload":true}"#,
        )
        .await;
        let missing = raw_post(endpoint.port, "", "/changed", r#"{"reload":true}"#).await;

        assert!(wrong.starts_with("HTTP/1.1 403"), "{wrong}");
        assert!(missing.starts_with("HTTP/1.1 403"), "{missing}");
        assert!(seen.lock().unwrap().is_empty());
        server.stop();
    }

    #[tokio::test]
    async fn bad_requests_are_answered_not_obeyed() {
        let dir = project("bad");
        let (server, seen) = serve(&dir).await;
        let endpoint = read(&dir).unwrap();
        let auth = format!("X-Rts-Token: {}\r\n", endpoint.token);

        let invalid = raw_post(endpoint.port, &auth, "/changed", "{not json").await;
        let not_object = raw_post(endpoint.port, &auth, "/changed", "[1]").await;
        let no_ids = raw_post(endpoint.port, &auth, "/changed", r#"{"other":1}"#).await;
        let elsewhere = raw_post(endpoint.port, &auth, "/other", "{}").await;

        assert!(invalid.starts_with("HTTP/1.1 400"));
        assert!(not_object.starts_with("HTTP/1.1 400"));
        assert!(no_ids.starts_with("HTTP/1.1 400"));
        assert!(elsewhere.starts_with("HTTP/1.1 404"));
        assert!(seen.lock().unwrap().is_empty());
        server.stop();
    }

    #[tokio::test]
    async fn an_oversized_body_is_refused_without_being_read() {
        let dir = project("large");
        let (server, seen) = serve(&dir).await;
        let endpoint = read(&dir).unwrap();
        let mut stream = TcpStream::connect(("127.0.0.1", endpoint.port))
            .await
            .unwrap();
        let head = format!(
            "POST /changed HTTP/1.1\r\nX-Rts-Token: {}\r\nContent-Length: {}\r\n\r\n",
            endpoint.token,
            MAX_BODY + 1
        );
        stream.write_all(head.as_bytes()).await.unwrap();
        let mut response = String::new();
        stream.read_to_string(&mut response).await.unwrap();
        assert!(response.starts_with("HTTP/1.1 413"), "{response}");
        assert!(seen.lock().unwrap().is_empty());
        server.stop();
    }

    #[tokio::test]
    async fn stopping_withdraws_the_endpoint() {
        let dir = project("stop");
        let (server, _) = serve(&dir).await;
        assert!(read(&dir).is_some());
        server.stop();
        assert_eq!(read(&dir), None);
    }

    #[test]
    fn token_comparison_is_exact() {
        assert!(same_token("abc", "abc"));
        assert!(!same_token("abc", "abd"));
        assert!(!same_token("abc", "abcd"));
    }
}
