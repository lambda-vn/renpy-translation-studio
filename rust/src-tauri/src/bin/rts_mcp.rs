//! Command line starting the server. Port of `mcp_server/__main__.py`.
//!
//! One server serves every game the application has set up: the client
//! asks for the list and picks one, so a user declares this command once
//! instead of once per project. `--project` pins it to a single one, for
//! a client that should reach nothing else.
//!
//! The two permissions are flags here and nowhere else. A client reads
//! the game's own text, which is written by someone other than the
//! person running this, so anything that destroys work has to be
//! granted from outside the protocol.

use std::path::PathBuf;
use std::process::ExitCode;

use rmcp::transport::stdio;
use rmcp::ServiceExt;
use rust_lib::mcp_server::{RtsServer, ServerState};

struct Args {
    project: Option<PathBuf>,
    allow_overwrite_validated: bool,
    allow_clear: bool,
}

fn parse_args() -> Result<Args, String> {
    let mut project = None;
    let mut allow_overwrite_validated = false;
    let mut allow_clear = false;

    let mut raw = std::env::args().skip(1);
    while let Some(arg) = raw.next() {
        match arg.as_str() {
            "--project" => {
                let value = raw.next().ok_or("--project requires a path")?;
                project = Some(PathBuf::from(value));
            }
            "--allow-overwrite-validated" => allow_overwrite_validated = true,
            "--allow-clear" => allow_clear = true,
            "-h" | "--help" => {
                println!(
                    "rts-mcp: serve the Ren'Py projects of this machine over MCP.\n\n\
                     Options:\n  \
                     --project <path>              Serve only this game folder, the one \
                     holding game/. Omitted, the client picks among the projects set up in \
                     the application.\n  \
                     --allow-overwrite-validated    Let a submission replace a line a human \
                     already validated. The replacement lands as a draft, never as validated.\n  \
                     --allow-clear                  Allow deleting translations in bulk."
                );
                std::process::exit(0);
            }
            other => return Err(format!("unrecognized argument: {other}")),
        }
    }

    Ok(Args {
        project,
        allow_overwrite_validated,
        allow_clear,
    })
}

#[tokio::main]
async fn main() -> ExitCode {
    let args = match parse_args() {
        Ok(args) => args,
        Err(message) => {
            eprintln!("rts-mcp: {message}");
            return ExitCode::FAILURE;
        }
    };

    let mut state = ServerState::new();
    state.allow_overwrite_validated = args.allow_overwrite_validated;
    state.allow_clear = args.allow_clear;

    if let Some(project) = &args.project {
        if let Err(error) = state.pin(project) {
            eprintln!("{error}");
            return ExitCode::FAILURE;
        }
    }

    let service = match RtsServer::new(state).serve(stdio()).await {
        Ok(service) => service,
        Err(error) => {
            eprintln!("rts-mcp: serving error: {error:?}");
            return ExitCode::FAILURE;
        }
    };

    if let Err(error) = service.waiting().await {
        eprintln!("rts-mcp: {error:?}");
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}
