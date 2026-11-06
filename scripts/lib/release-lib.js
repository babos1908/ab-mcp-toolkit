'use strict';
/**
 * SemVer 2.0.0 and build-identity helpers shared by release-guard.js,
 * write-build-info.js and the tests. See docs/PUBLIC-API.md.
 */
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

// The regular expression published with the SemVer 2.0.0 specification.
const SEMVER = /^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$/;

/** '1.2.3-rc.1+abc' -> { major, minor, patch, pre: ['rc','1'], raw } or null. */
function parseSemver(v) {
  const m = SEMVER.exec(String(v));
  if (!m) return null;
  return { major: +m[1], minor: +m[2], patch: +m[3], pre: m[4] ? m[4].split('.') : [], raw: String(v) };
}

/** Precedence per SemVer section 11 (build metadata ignored). */
function compareSemver(a, b) {
  for (const k of ['major', 'minor', 'patch']) {
    if (a[k] !== b[k]) return a[k] < b[k] ? -1 : 1;
  }
  if (!a.pre.length && !b.pre.length) return 0;
  if (!a.pre.length) return 1;
  if (!b.pre.length) return -1;
  for (let i = 0; i < Math.max(a.pre.length, b.pre.length); i++) {
    if (i >= a.pre.length) return -1;
    if (i >= b.pre.length) return 1;
    const x = a.pre[i];
    const y = b.pre[i];
    const xn = /^\d+$/.test(x);
    const yn = /^\d+$/.test(y);
    if (xn && yn) { if (+x !== +y) return +x < +y ? -1 : 1; continue; }
    if (xn) return -1;
    if (yn) return 1;
    if (x !== y) return x < y ? -1 : 1;
  }
  return 0;
}

/**
 * Does going from release `from` to version `to` allow an API change of
 * `level` ('major' | 'minor' | 'none')? During initial development (0.y.z)
 * anything may change, so a breaking change only needs a MINOR bump there.
 */
function bumpSatisfies(from, to, level) {
  if (level === 'none') return true;
  if (level === 'major' && from.major > 0) return to.major > from.major;
  return to.major > from.major || (to.major === from.major && to.minor > from.minor);
}

/** The smallest version that `level` requires after release `from`. */
function requiredVersion(from, level) {
  if (level === 'major' && from.major > 0) return `${from.major + 1}.0.0`;
  return `${from.major}.${from.minor + 1}.0`;
}

function listFiles(dir) {
  const out = [];
  if (!fs.existsSync(dir)) return out;
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) {
      if (e.name === '__pycache__') continue;
      out.push(...listFiles(p));
    } else if (!e.name.endsWith('.pyc')) {
      out.push(p);
    }
  }
  return out;
}

/**
 * sha256 of what a build is made of: src/** and package.json. Line endings
 * are normalised so the same commit hashes the same on any checkout.
 */
function contentHash(root) {
  const h = crypto.createHash('sha256');
  const files = [...listFiles(path.join(root, 'src')), path.join(root, 'package.json')]
    .map((f) => path.relative(root, f).split(path.sep).join('/'))
    .sort();
  for (const rel of files) {
    const data = fs.readFileSync(path.join(root, rel)).toString('utf-8').replace(/\r\n/g, '\n');
    h.update(rel).update('\0').update(data).update('\0');
  }
  return h.digest('hex');
}

/** Run git in `root`; { ok, out } -- never throws. */
function git(root, args) {
  const r = spawnSync('git', args, { cwd: root, encoding: 'utf-8', stdio: ['ignore', 'pipe', 'pipe'] });
  return { ok: r.status === 0, out: (r.stdout || '').trim(), status: r.status };
}

module.exports = { parseSemver, compareSemver, bumpSatisfies, requiredVersion, contentHash, git };
