#!/usr/bin/env node
/**
 * Release guard -- the first step of `npm run build`.
 *
 * On this project a build IS a release: the package is npm-linked, so the
 * moment dist/ is rebuilt every Claude session on the machine serves it
 * (Python scripts at once, TypeScript at its next restart). Between
 * 2026-05-09 and 2026-10-18 that happened 77 times under one number, 0.6.2,
 * which was upstream's. This refuses a build that would break Semantic
 * Versioning 2.0.0 (docs/PUBLIC-API.md):
 *
 *   - package.json "version" is not MAJOR.MINOR.PATCH[-pre][+build];
 *   - src/ or package.json has uncommitted changes (every build must be a
 *     commit, so get_mcp_version can name it);
 *   - the version is lower than the last release tag;
 *   - the version is already tagged, or was already built here, with
 *     different content;
 *   - the MCP tool API changed since the last release tag more than the
 *     version bump allows.
 *
 * Without git (an unpacked archive) only the format and local-build checks
 * run. Usage: node scripts/release-guard.js [repoRoot]
 */
const fs = require('fs');
const path = require('path');
const { parseSemver, compareSemver, bumpSatisfies, requiredVersion, contentHash, git } = require('./lib/release-lib');
const { extractTools, diffApi } = require('./lib/tool-api');

const root = path.resolve(process.argv[2] || path.join(__dirname, '..'));

function refuse(reason, fix) {
  process.stderr.write(`\nrelease-guard: BUILD REFUSED -- ${reason}\n`);
  if (fix) process.stderr.write(`  ${fix.split('\n').join('\n  ')}\n`);
  process.stderr.write('  A build is a release on this project (npm link serves it to every session). See docs/PUBLIC-API.md.\n\n');
  process.exit(1);
}

const pkg = JSON.parse(fs.readFileSync(path.join(root, 'package.json'), 'utf-8'));
const version = parseSemver(pkg.version);
if (!version) {
  refuse(`package.json version "${pkg.version}" is not a SemVer 2.0.0 version`,
    'Use MAJOR.MINOR.PATCH -- three integers, no leading zeros, no fourth number -- optionally -pre.release and +build.');
}

const hash = contentHash(root);

// Local: never serve two different builds under one number on this machine.
const infoPath = path.join(root, 'dist', 'build-info.json');
if (fs.existsSync(infoPath)) {
  try {
    const prev = JSON.parse(fs.readFileSync(infoPath, 'utf-8'));
    if (prev.version === pkg.version && prev.contentHash && prev.contentHash !== hash) {
      refuse(`version ${pkg.version} was already built here from different content (commit ${prev.commit || 'unknown'}, ${prev.builtAt || 'unknown time'})`,
        'Bump the version first: npm version <patch|minor|major|X.Y.Z-rc.N> --no-git-tag-version');
    }
  } catch { /* unreadable build-info: nothing to compare with */ }
}

const inRepo = git(root, ['rev-parse', '--is-inside-work-tree']);
if (!inRepo.ok || inRepo.out !== 'true') {
  process.stderr.write(`release-guard: not a git checkout -- only format and local-build checks ran. Building ${pkg.version}.\n`);
  process.exit(0);
}

const dirty = git(root, ['status', '--porcelain', '--', 'src', 'package.json']);
if (dirty.ok && dirty.out) {
  refuse('src/ or package.json has uncommitted changes',
    `Commit first, so the build is a commit get_mcp_version can name:\n${dirty.out.split('\n').slice(0, 8).join('\n')}`);
}

// Same number already released with different content?
const tag = `v${pkg.version}`;
const tagged = git(root, ['rev-parse', '-q', '--verify', `refs/tags/${tag}`]);
if (tagged.ok) {
  const same = git(root, ['diff', '--quiet', tag, '--', 'src', 'package.json']);
  if (!same.ok) {
    refuse(`${tag} is already released with different content`,
      'A released version never changes. Bump: npm version <patch|minor|major> --no-git-tag-version');
  }
}

// The last release reachable from here: versions only go up, and the tool
// API may only change as much as the bump allows.
const merged = git(root, ['tag', '--merged', 'HEAD', '-l', 'v*']);
const releases = (merged.ok ? merged.out.split('\n') : [])
  .map((t) => ({ tag: t.trim(), v: parseSemver(t.trim().replace(/^v/, '')) }))
  .filter((r) => r.v && r.v.pre.length === 0)
  .sort((a, b) => compareSemver(a.v, b.v));
const last = releases[releases.length - 1];

if (last) {
  const cmp = compareSemver(version, last.v);
  if (cmp < 0) {
    refuse(`version ${pkg.version} is lower than the last release ${last.tag}`, 'Versions only go up.');
  }
  if (cmp > 0) {
    const oldSrc = git(root, ['show', `${last.tag}:src/server.ts`]);
    if (oldSrc.ok) {
      const d = diffApi(extractTools(oldSrc.out), extractTools(fs.readFileSync(path.join(root, 'src', 'server.ts'), 'utf-8')));
      if (!bumpSatisfies(last.v, version, d.level)) {
        const changes = [...d.major.map((c) => `MAJOR  ${c}`), ...d.minor.map((c) => `MINOR  ${c}`)];
        refuse(`the tool API changed since ${last.tag} (${d.level}) but ${pkg.version} does not allow it`,
          `Needs at least ${requiredVersion(last.v, d.level)}. Changes:\n${changes.slice(0, 20).join('\n')}`);
      }
      if (d.level !== 'none') {
        process.stderr.write(`release-guard: tool API ${d.level} change since ${last.tag} (${d.major.length + d.minor.length} item(s)) -- covered by ${pkg.version}.\n`);
      }
    }
  }
} else {
  process.stderr.write('release-guard: no release tag yet -- first release, no API baseline to compare.\n');
}

const head = git(root, ['rev-parse', '--short', 'HEAD']);
process.stderr.write(`release-guard: OK -- building ${pkg.version} from ${head.ok ? head.out : 'unknown commit'}.\n`);
