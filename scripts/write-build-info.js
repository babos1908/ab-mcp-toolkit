#!/usr/bin/env node
/**
 * Stamp dist/build-info.json -- the last step of `npm run build`.
 *
 * The server reads it once at startup, so get_mcp_version can say which
 * build the running process loaded (version, commit, build time) and whether
 * the scripts on disk are newer. Until 1.0.0 it reported package.json's
 * version and the repository HEAD at the moment of the call, which named
 * neither the running build nor anything else in particular.
 * Usage: node scripts/write-build-info.js [repoRoot]
 */
const fs = require('fs');
const path = require('path');
const { contentHash, git } = require('./lib/release-lib');

const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));
const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf-8'));
const head = git(root, ['rev-parse', 'HEAD']);
const dirty = git(root, ['status', '--porcelain', '--', 'src', 'package.json']);

const info = {
  version: pkg.version,
  commit: head.ok ? head.out : null,
  dirty: dirty.ok ? dirty.out.length > 0 : null,
  contentHash: contentHash(root),
  builtAt: new Date().toISOString(),
};
fs.mkdirSync(path.join(root, 'dist'), { recursive: true });
fs.writeFileSync(path.join(root, 'dist', 'build-info.json'), JSON.stringify(info, null, 2) + '\n', 'utf-8');
process.stderr.write(`write-build-info: ${info.version} @ ${info.commit ? info.commit.slice(0, 7) : 'unknown'}${info.dirty ? ' (dirty)' : ''}\n`);
