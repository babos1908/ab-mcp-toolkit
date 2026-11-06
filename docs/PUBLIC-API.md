# Public API

This project follows [Semantic Versioning 2.0.0](https://semver.org/spec/v2.0.0.html) ([in italiano](https://semver.org/lang/it/)). Version 1.0.0 (2026-11-06) is the first release with this declared public API. Every release gets a new `MAJOR.MINOR.PATCH` number -- three integers, no leading zeros, never a fourth -- and a release never changes afterwards.

The version is in `package.json`, the git tag of each release is `vMAJOR.MINOR.PATCH`, and the running server reports the build it loaded through the `get_mcp_version` tool.

## What is public

These are what callers -- agents, scripts, people -- may rely on. Changing them follows the rules in the next section.

1. **The MCP tools.** Tool names; parameter names, types, required-ness and allowed values; what each tool is documented to do. The authoritative list is [TOOL-CATALOG.md](TOOL-CATALOG.md), generated from the source, so it always matches the code.
2. **Tool results.** A failure is a result with `isError: true` whose text starts with `[ERR_CODE]`. The codes are the `MCPErrorCode` values in `src/types.ts`, and their meaning is stable. Structured results -- the JSON a tool returns, or prints between `### RESULT_JSON ###` and `### END_RESULT_JSON ###` -- are public by field name and type.
3. **The `codesys-mcp-persistent` command line.** Its options: `--codesys-path`, `--codesys-profile`, `--workspace`, `--mode`, `--no-auto-launch`, `--no-auto-backup`, `--backup-retention`, `--fallback-headless`, `--keep-alive`, `--kill-existing-codesys`, `--timeout`, `--ready-timeout-ms`, `--log-file`, `--verbose`, `--debug`, `--detect`.
4. **The session folder protocol.** `%TEMP%\codesys-mcp-persistent\<session>` with `commands\`, `results\`, `ready.signal`, `heartbeat.signal`, `terminate.signal` and `owner.json`, plus the command and result file formats. Servers of different versions share these folders on one machine, so an incompatible change would break sessions of other servers.
5. **Auto-backup files.** Named `<file>.backup-YYYYMMDDTHHMMSSZ` next to the source file. `cleanup_backups` deletes only files with exactly this name pattern.

## What is not public

These may change in any release:

- the Python script names in `src/scripts/` and their `{PLACEHOLDER}`s;
- helper functions and internal TypeScript modules;
- the wording of messages and logs (only the error code is stable);
- the patch list in `get_mcp_version`;
- the `codesys-ab` skill text.

One compatibility rule applies to them anyway. Scripts are re-read from disk on every call, while a running server keeps its TypeScript until Claude Code restarts. So a new placeholder must fall back to the old behaviour when an older handler does not pass it, which is what `opt_placeholder()` in `_text_utils.py` does.

## What counts as what

| Change | Level |
|---|---|
| Remove or rename a tool, a parameter, a result field or a CLI option | **MAJOR** |
| Make an optional parameter required, add a required parameter, change a parameter's type, remove an allowed value | **MAJOR** |
| Change what an error code means, or change the session folder protocol incompatibly | **MAJOR** |
| Add a tool, an optional parameter, an allowed value, a result field, an error code or a CLI option | **MINOR** |
| Relax a parameter (required to optional), or deprecate something -- still working, marked in its description and in the CHANGELOG | **MINOR** |
| Fix a tool so it does what it is documented to do -- including turning a false success into the documented error, as the read-back checks did | **PATCH** |
| Documentation and description wording | not a release by itself |

Something deprecated keeps working until the next MAJOR.

## How a release is made

On this project **a build is a release**. The package is installed with `npm link`, so the moment `dist/` is rebuilt, every Claude session on the machine serves it: the Python scripts at once, and the TypeScript after its next restart. Between 2026-05-09 and 2026-10-18 that happened 77 times while the version stayed `0.6.2` (see the CHANGELOG). `npm run build` now refuses to do it again.

1. Pick the level from the table above and set the version: `npm version <patch|minor|major> --no-git-tag-version`. A build handed to other sessions to test gets a pre-release version, such as `npm version 1.1.0-rc.1 --no-git-tag-version`.
2. Test from source, without building: `npm test`. Live tests drive a separate headless AB from `src/` through `ScriptManager`.
3. Regenerate the catalog with `npm run docs`, update `CHANGELOG.md`, and commit.
4. Release with `npm run build`. First, `scripts/release-guard.js` checks:
   - the version is valid SemVer;
   - `src/` and `package.json` are committed;
   - the version is not lower than the last release tag;
   - the version is not already tagged, or already built on this machine, with different content;
   - the tool API changed since the last release tag no more than the version allows (it names the changes and the minimum version).
   Then `scripts/write-build-info.js` stamps `dist/build-info.json`, which is what `get_mcp_version` reports.
5. Tag the release and push the tag: `git tag -a vX.Y.Z -m "..."`, then `git push origin main vX.Y.Z`.
