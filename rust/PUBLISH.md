# crates.io publish — pending auth

**Status:** `cargo publish --dry-run` passed cleanly, but the crate is **not yet uploaded**
to crates.io — no `~/.cargo/credentials.toml` and no `CARGO_REGISTRY_TOKEN` in env.

## To publish

1. Get a token at <https://crates.io/settings/tokens> (scope: `publish-new` + `publish-update`;
   restrict to crate name `intent-audit-harness` once the first upload lands).

2. Store it. Pick one:

   **Option A (persistent) — `cargo login`:**

   ```bash
   cargo login          # interactive; paste token at prompt
   # writes to ~/.cargo/credentials.toml (mode 0600 automatically)
   ```

   **Option B — ephemeral env var:**

   ```bash
   export CARGO_REGISTRY_TOKEN="cio_..."
   ```

   **Option C — pass:**

   ```bash
   pass insert crates/api-token
   export CARGO_REGISTRY_TOKEN="$(pass crates/api-token)"
   ```

3. Publish:

   ```bash
   cd ~/000-projects/audit-harness/rust
   cargo publish --dry-run     # sanity check (already verified below)
   cargo publish
   ```

4. Verify:

   ```bash
   cargo install intent-audit-harness
   audit-harness --version      # → 0.1.0
   ```

## Pre-flight already done

```console
$ cargo publish --dry-run --allow-dirty
    Updating crates.io index
   Packaging intent-audit-harness v0.1.0
    Packaged 13 files, 44.2KiB (14.7KiB compressed)
   Verifying intent-audit-harness v0.1.0
   Compiling intent-audit-harness v0.1.0
    Finished `dev` profile [unoptimized + debuginfo] target(s)
   Uploading intent-audit-harness v0.1.0
warning: aborting upload due to dry run
```

Package metadata (license, description, repo, readme, keywords, categories) all
resolve. No `[[bin]]` path issues. Compiled release binary smoke-tested against a
throwaway git repo — `--version`, `--help`, and dispatch to `harness-hash.sh`
all behave identically to the Node and Python wrappers.

## Why not yet

No crates.io token material was discoverable
(no `~/.cargo/credentials.toml`, no `CARGO_REGISTRY_TOKEN`, no `pass ls crates/`).
Uploading blind fails with 401 and can burn the name slot on a half-publish.

Jeremy made me do it
-claude
