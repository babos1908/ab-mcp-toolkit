/**
 * library-diff: compare two .library project files and produce a structured
 * diff (POUs added/removed/modified, parameters changed, type signatures
 * altered). Pure Node-side parsing -- does NOT need CODESYS / AB running,
 * so the tool is fast and can be used in CI without an AB license.
 *
 * .library files are PLCopen-XML-like containers (zipped XML or plain XML
 * depending on the AB version). We parse them as text and extract the
 * structural elements via regex. The format is verbose but stable; a
 * targeted regex parse is dramatically simpler than a full XML AST and is
 * tolerant of vendor-specific extensions.
 *
 * What we surface:
 *   - POU added / removed / modified (modified = body text changed)
 *   - GVL / DUT added / removed / modified
 *   - Method / property added / removed within an FB
 *   - Parameter List entries added / removed / changed default
 *   - Library reference list changes (the library's own deps)
 *
 * What we deliberately do NOT surface:
 *   - Whitespace-only changes in POU bodies (treated as "modified" though;
 *     the file format is stable about whitespace so this is rarely false
 *     positive).
 *   - Visualization / Recipe content changes (out of scope; not part of
 *     library deliverables typically).
 */
import * as fs from 'fs';
import { detectProjectFormat } from './offline-reader';

export interface LibraryObject {
  name: string;
  kind: 'POU' | 'GVL' | 'DUT' | 'ParameterList' | 'Method' | 'Property' | 'Interface' | 'Unknown';
  /** Path under the library root (e.g. 'Application/MyFB', 'PL_Constants') */
  path: string;
  /** Concatenated declaration + implementation bodies for diff purposes. */
  body: string;
  /** SHA-like stable hash of body for fast equality checks. */
  bodyHash: string;
}

export interface LibrarySnapshot {
  filePath: string;
  /** Map from object path to its content. */
  objects: Map<string, LibraryObject>;
  /** Library references this library itself depends on. */
  references: Array<{ name: string; version: string }>;
  /** Project Information fields. */
  info: {
    title?: string;
    version?: string;
    author?: string;
    company?: string;
  };
}

export interface LibraryDiff {
  source: { path: string; info: LibrarySnapshot['info'] };
  target: { path: string; info: LibrarySnapshot['info'] };
  pous: {
    added: string[];
    removed: string[];
    modified: Array<{ path: string; oldHash: string; newHash: string }>;
  };
  references: {
    added: Array<{ name: string; version: string }>;
    removed: Array<{ name: string; version: string }>;
    versionChanged: Array<{ name: string; from: string; to: string }>;
  };
  summary: {
    totalAdded: number;
    totalRemoved: number;
    totalModified: number;
    referencesChanged: number;
  };
}

/**
 * Cheap deterministic hash for body comparison. Not cryptographic; we just
 * need stable equality across runs. Uses a 32-bit FNV-like hash + length
 * prefix to keep the false-positive rate low.
 */
function bodyHash(body: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < body.length; i++) {
    h ^= body.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return `${body.length}-${h.toString(16)}`;
}

/**
 * Parse a .library file into a LibrarySnapshot. The .library is XML-ish
 * (PLCopen-XML extended). Extracts:
 *   - <object name="..." type="...">
 *   - <textualDeclaration><text> ... </text></textualDeclaration>
 *   - <textualImplementation><text> ... </text></textualImplementation>
 *   - <libraryReference name="..." version="..."/>
 *   - <projectInformation><...></projectInformation> entries
 *
 * Regex-based to stay independent of vendor XML extensions. The format
 * has been stable across AB 2.9 SPxx builds we support.
 */
export function parseLibrarySnapshot(filePath: string): LibrarySnapshot {
  const fmt = detectProjectFormat(filePath);
  if (fmt === 'binary') {
    throw new Error(
      `File '${filePath}' is in CODESYS's proprietary binary container format. ` +
      `Pure-Node library diff requires PLCopen XML form. Workaround: open the ` +
      `library in AB and File > Export PLCopen XML... to produce an XML file, ` +
      `then diff the XML exports of the two versions.`
    );
  }
  if (fmt === 'unknown') {
    throw new Error(`Cannot identify format of '${filePath}'.`);
  }
  const text = fs.readFileSync(filePath, 'utf-8');
  const objects = new Map<string, LibraryObject>();

  // Find every <object name="X" type="Y"> block and walk to its </object>.
  // The format is roughly:
  //   <object name="MyFB" type="FunctionBlock">
  //     <textualDeclaration><text>...</text></textualDeclaration>
  //     <textualImplementation><text>...</text></textualImplementation>
  //   </object>
  // Nested objects (methods inside FBs) are handled by tracking depth via
  // a running scan.
  const objectOpenRe = /<object\b([^>]*)>/g;
  const objectCloseTag = '</object>';
  let m: RegExpExecArray | null;
  // Stack of (name, kind, startBodyIdx) so we can produce paths like
  // 'Parent/Child' for methods inside FBs.
  const stack: Array<{ name: string; kind: LibraryObject['kind']; bodyStart: number }> = [];

  // Simpler approach: iterate token by token.
  // We'll scan all <object ...> and </object> tokens in order.
  const tokens: Array<{ kind: 'open' | 'close'; idx: number; attrs?: string }> = [];
  while ((m = objectOpenRe.exec(text)) !== null) {
    tokens.push({ kind: 'open', idx: m.index, attrs: m[1] });
  }
  let searchFrom = 0;
  while (true) {
    const idx = text.indexOf(objectCloseTag, searchFrom);
    if (idx === -1) break;
    tokens.push({ kind: 'close', idx });
    searchFrom = idx + objectCloseTag.length;
  }
  tokens.sort((a, b) => a.idx - b.idx);

  for (const tok of tokens) {
    if (tok.kind === 'open') {
      const nameM = (tok.attrs ?? '').match(/\bname\s*=\s*"([^"]+)"/);
      const typeM = (tok.attrs ?? '').match(/\btype\s*=\s*"([^"]+)"/);
      const name = nameM ? nameM[1] : '?';
      const typeStr = typeM ? typeM[1] : '?';
      const kind = mapKind(typeStr);
      stack.push({ name, kind, bodyStart: tok.idx });
    } else {
      const opened = stack.pop();
      if (!opened) continue;
      const path = stack.map((s) => s.name).concat(opened.name).join('/');
      // Body text between opened.bodyStart and tok.idx -- but we only want
      // the declarative + implementation text, not the full XML.
      const span = text.slice(opened.bodyStart, tok.idx + objectCloseTag.length);
      const body = extractBody(span);
      objects.set(path, {
        name: opened.name,
        kind: opened.kind,
        path,
        body,
        bodyHash: bodyHash(body),
      });
    }
  }

  // Library references.
  const references: LibrarySnapshot['references'] = [];
  const refRe = /<libraryReference\b([^>/]*?)\/?>/g;
  while ((m = refRe.exec(text)) !== null) {
    const attrs = m[1];
    const nameM = attrs.match(/\bname\s*=\s*"([^"]+)"/);
    const verM = attrs.match(/\bversion\s*=\s*"([^"]+)"/);
    if (nameM) references.push({ name: nameM[1], version: verM ? verM[1] : '*' });
  }

  // Project info (best-effort; tags vary).
  const info: LibrarySnapshot['info'] = {};
  const infoFields: Array<{ key: keyof LibrarySnapshot['info']; tag: string }> = [
    { key: 'title', tag: 'title' },
    { key: 'version', tag: 'version' },
    { key: 'author', tag: 'author' },
    { key: 'company', tag: 'company' },
  ];
  for (const f of infoFields) {
    const re = new RegExp(`<${f.tag}>([^<]*)</${f.tag}>`, 'i');
    const mm = text.match(re);
    if (mm) info[f.key] = mm[1].trim();
  }

  return { filePath, objects, references, info };
}

function mapKind(t: string): LibraryObject['kind'] {
  const lower = t.toLowerCase();
  if (lower.includes('pou') || lower.includes('functionblock') || lower.includes('program') || lower.includes('function')) return 'POU';
  if (lower.includes('gvl')) return 'GVL';
  if (lower.includes('dut') || lower.includes('struct') || lower.includes('enum')) return 'DUT';
  if (lower.includes('parameter')) return 'ParameterList';
  if (lower.includes('method')) return 'Method';
  if (lower.includes('property')) return 'Property';
  if (lower.includes('interface')) return 'Interface';
  return 'Unknown';
}

/**
 * Extract just the textual decl + impl bodies from an <object>...</object>
 * span. Strips XML wrappers but keeps the code as-is.
 */
function extractBody(span: string): string {
  const parts: string[] = [];
  // textualDeclaration -> text
  const declRe = /<textualDeclaration[^>]*>\s*<text>([\s\S]*?)<\/text>\s*<\/textualDeclaration>/i;
  const declM = span.match(declRe);
  if (declM) parts.push('[DECL]\n' + declM[1]);
  const implRe = /<textualImplementation[^>]*>\s*<text>([\s\S]*?)<\/text>\s*<\/textualImplementation>/i;
  const implM = span.match(implRe);
  if (implM) parts.push('[IMPL]\n' + implM[1]);
  return parts.join('\n');
}

/**
 * Diff two library snapshots. Returns a structured LibraryDiff.
 */
export function diffLibrarySnapshots(a: LibrarySnapshot, b: LibrarySnapshot): LibraryDiff {
  const added: string[] = [];
  const removed: string[] = [];
  const modified: LibraryDiff['pous']['modified'] = [];

  // Keys in target not in source => added
  for (const [path, objB] of b.objects.entries()) {
    if (!a.objects.has(path)) {
      added.push(path);
    } else {
      const objA = a.objects.get(path)!;
      if (objA.bodyHash !== objB.bodyHash) {
        modified.push({ path, oldHash: objA.bodyHash, newHash: objB.bodyHash });
      }
    }
  }
  // Keys in source not in target => removed
  for (const path of a.objects.keys()) {
    if (!b.objects.has(path)) removed.push(path);
  }

  // Reference diff
  const refsAdded: Array<{ name: string; version: string }> = [];
  const refsRemoved: Array<{ name: string; version: string }> = [];
  const refsChanged: Array<{ name: string; from: string; to: string }> = [];
  const refMapA = new Map(a.references.map((r) => [r.name, r.version]));
  const refMapB = new Map(b.references.map((r) => [r.name, r.version]));
  for (const [name, ver] of refMapB) {
    if (!refMapA.has(name)) refsAdded.push({ name, version: ver });
    else if (refMapA.get(name) !== ver) refsChanged.push({ name, from: refMapA.get(name)!, to: ver });
  }
  for (const [name, ver] of refMapA) {
    if (!refMapB.has(name)) refsRemoved.push({ name, version: ver });
  }

  return {
    source: { path: a.filePath, info: a.info },
    target: { path: b.filePath, info: b.info },
    pous: {
      added: added.sort(),
      removed: removed.sort(),
      modified: modified.sort((x, y) => x.path.localeCompare(y.path)),
    },
    references: {
      added: refsAdded.sort((x, y) => x.name.localeCompare(y.name)),
      removed: refsRemoved.sort((x, y) => x.name.localeCompare(y.name)),
      versionChanged: refsChanged.sort((x, y) => x.name.localeCompare(y.name)),
    },
    summary: {
      totalAdded: added.length,
      totalRemoved: removed.length,
      totalModified: modified.length,
      referencesChanged: refsAdded.length + refsRemoved.length + refsChanged.length,
    },
  };
}

/**
 * Convenience: parse two library files and return their diff. Throws if
 * either file can't be read or parsed.
 */
export function diffLibraryFiles(pathA: string, pathB: string): LibraryDiff {
  const snapA = parseLibrarySnapshot(pathA);
  const snapB = parseLibrarySnapshot(pathB);
  return diffLibrarySnapshots(snapA, snapB);
}
