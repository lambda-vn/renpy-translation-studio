//! Second entry point onto the same core, serving an MCP client (an
//! assistant, an agent) instead of the desktop UI. Port of
//! `src/mcp_server/`. The binary entry point lives in
//! `src/bin/rts_mcp.rs`, mirroring the Python package's separate
//! `rts-mcp` executable.

pub mod dto;
pub mod server;
pub mod session;

pub use server::RtsServer;
pub use session::ServerState;
