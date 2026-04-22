//! audit-harness — deterministic test-enforcement toolkit (Rust binary).
//!
//! Thin dispatcher around the canonical shell/python scripts maintained at
//! <https://github.com/jeremylongshore/audit-harness>. The scripts are embedded
//! into the binary at compile time via `include_bytes!`, extracted into
//! `$XDG_CACHE_HOME/audit-harness/<version>/scripts/` on first run, and invoked
//! via `bash` / `python3`.
//!
//! Design goals:
//! - Zero runtime deps (std only) — mirrors the project's minimal-dependency rule.
//! - Identical CLI surface as the Node and Python packages.
//! - Version-scoped cache so upgrades don't stomp an in-flight run.

use std::env;
use std::fs;
use std::io::Write as _;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{self, Command};

const VERSION: &str = env!("CARGO_PKG_VERSION");

/// Compile-time embed of every script shipped with the canonical toolkit.
/// Tuple: (on-disk filename, contents).
const SCRIPTS: &[(&str, &[u8])] = &[
    ("harness-hash.sh", include_bytes!("../scripts/harness-hash.sh")),
    ("escape-scan.sh",  include_bytes!("../scripts/escape-scan.sh")),
    ("arch-check.sh",   include_bytes!("../scripts/arch-check.sh")),
    ("bias-count.sh",   include_bytes!("../scripts/bias-count.sh")),
    ("gherkin-lint.sh", include_bytes!("../scripts/gherkin-lint.sh")),
    ("crap-score.py",   include_bytes!("../scripts/crap-score.py")),
];

/// Maps a CLI command to (script filename, default args).
fn resolve_command(cmd: &str) -> Option<(&'static str, &'static [&'static str])> {
    match cmd {
        "verify"       => Some(("harness-hash.sh", &["--verify"])),
        "init"         => Some(("harness-hash.sh", &["--init"])),
        "list"         => Some(("harness-hash.sh", &["--list"])),
        "escape-scan"  => Some(("escape-scan.sh",  &[])),
        "arch"         => Some(("arch-check.sh",   &[])),
        "bias"         => Some(("bias-count.sh",   &[])),
        "gherkin-lint" => Some(("gherkin-lint.sh", &[])),
        "crap"         => Some(("crap-score.py",   &[])),
        _              => None,
    }
}

fn usage() {
    println!(
        "audit-harness — deterministic test-enforcement toolkit (Rust)

Usage:
  audit-harness <command> [args...]

Commands:
  verify                   Verify hash-pinned artifacts (exit 2 = HARNESS_TAMPERED)
  init                     Initialize or re-init the .harness-hash manifest
  list                     List currently pinned files
  escape-scan <source>     Scan a diff for escape attempts
                           source: --staged | --range A..B | - (stdin) | path.patch
  arch                     Run architecture-rule checks (Wall 7)
  bias                     Count test-bias patterns (tautology, smoke-only, etc.)
  gherkin-lint             Advisory Gherkin quality check
  crap [args...]           CRAP complexity x coverage scorer (multi-language)

Options:
  --version, -v            Print version
  --help, -h               Print this help

Exit codes (escape-scan):
  0 = clean
  1 = CHALLENGE (engineer-approved comment required)
  2 = REFUSE (pipeline halted)"
    );
}

/// Resolve the cache dir for the current user: `$XDG_CACHE_HOME/audit-harness/<version>`
/// or `$HOME/.cache/audit-harness/<version>`. Falls back to `/tmp` if neither exists.
fn cache_dir() -> PathBuf {
    let base = env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .or_else(|| env::var_os("HOME").map(|h| PathBuf::from(h).join(".cache")))
        .unwrap_or_else(|| PathBuf::from("/tmp"));
    base.join("audit-harness").join(VERSION)
}

/// Extract every embedded script into `cache_dir/scripts/` if missing or stale.
/// We use "missing" as the only signal — the cache dir is version-scoped, so the
/// binary's own version bump naturally invalidates the previous extraction.
fn ensure_scripts_extracted() -> Result<PathBuf, String> {
    let target = cache_dir().join("scripts");
    fs::create_dir_all(&target)
        .map_err(|e| format!("failed to create {}: {e}", target.display()))?;

    for (name, contents) in SCRIPTS {
        let path = target.join(name);
        if path.exists() {
            continue;
        }
        let mut f = fs::File::create(&path)
            .map_err(|e| format!("failed to write {}: {e}", path.display()))?;
        f.write_all(contents)
            .map_err(|e| format!("failed to write {}: {e}", path.display()))?;
        // 0o755 for scripts so bash/python3 can exec them directly
        let mut perms = fs::metadata(&path)
            .map_err(|e| format!("failed to stat {}: {e}", path.display()))?
            .permissions();
        perms.set_mode(0o755);
        fs::set_permissions(&path, perms)
            .map_err(|e| format!("chmod {} failed: {e}", path.display()))?;
    }

    Ok(target)
}

fn interpreter_for(script: &str) -> &'static str {
    if script.ends_with(".py") {
        "python3"
    } else {
        "bash"
    }
}

fn dispatch(cmd: &str, rest: &[String]) -> i32 {
    let Some((script_name, default_args)) = resolve_command(cmd) else {
        eprintln!("audit-harness: unknown command '{cmd}'");
        usage();
        return 2;
    };

    let scripts_dir = match ensure_scripts_extracted() {
        Ok(p) => p,
        Err(e) => {
            eprintln!("audit-harness: {e}");
            return 2;
        }
    };

    let script_path: &Path = &scripts_dir.join(script_name);
    if !script_path.exists() {
        eprintln!(
            "audit-harness: script not found at {} (extraction failed?)",
            script_path.display()
        );
        return 2;
    }

    let interp = interpreter_for(script_name);
    let mut command = Command::new(interp);
    command.arg(script_path);
    command.args(default_args.iter().copied());
    command.args(rest);

    match command.status() {
        Ok(status) => status.code().unwrap_or(128),
        Err(e) => {
            eprintln!("audit-harness: failed to spawn {interp}: {e}");
            2
        }
    }
}

fn main() {
    let args: Vec<String> = env::args().skip(1).collect();
    let rc = match args.first().map(String::as_str) {
        None | Some("--help") | Some("-h") => {
            usage();
            0
        }
        Some("--version") | Some("-v") => {
            println!("{VERSION}");
            0
        }
        Some(cmd) => dispatch(cmd, &args[1..]),
    };
    process::exit(rc);
}
