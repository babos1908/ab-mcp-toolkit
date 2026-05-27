/**
 * offline-reader: read POU/GVL/DUT code from .project / .library files
 * WITHOUT going through CODESYS. Bypasses the single-instance lock that
 * prevents MCP from accessing a project the user has open in their UI.
 *
 * Reuses the same regex-based XML parsing approach as library-diff.ts.
 * The .project format is verbose XML; we extract <object> blocks with
 * their <textualDeclaration><text>...</text></textualDeclaration> and
 * <textualImplementation><text>...</text></textualImplementation>.
 *
 * Trade-offs vs the in-AB scripting approach:
 *
 *   PRO:
 *     - Works while user has the project open in AB UI (no lock conflict)
 *     - No CODESYS launch needed -- instant, no resource cost
 *     - Safe for read-only ops on shared/CI projects
 *     - Survives MCP "stalled" state -- you can keep reading code even
 *       when force_reset_watcher is needed
 *
 *   CON:
 *     - Always shows the on-disk state -- if the user has unsaved
 *       changes in AB, those are NOT visible until they save
 *     - Cannot resolve dynamic library content (library code is in
 *       installed library files, not in the consumer's .project)
 *     - Cannot trigger compile, edit, or any other write op
 *     - Path semantics are best-effort (we infer from <object name="..."
 *       type="..."> nesting; complex layouts may surprise)
 */
import * as fs from 'fs';

export interface OfflineObject {
  /** Short name of the object (e.g. 'PLC_PRG'). */
  name: string;
  /** Inferred kind. */
  kind: 'POU' | 'GVL' | 'DUT' | 'ParameterList' | 'Method' | 'Property' | 'Interface' | 'Unknown';
  /** Path under the project root (slash-separated). */
  path: string;
  /** Declaration text (VAR...END_VAR). May be empty for some objects. */
  declaration: string;
  /** Implementation text. May be empty for GVL/DUT/etc. */
  implementation: string;
}

export interface OfflineProjectSnapshot {
  filePath: string;
  objects: OfflineObject[];
}

/**
 * Detect whether a file looks like XML (open-angle-bracket prefix) vs the
 * binary CODESYS .project format (starts with '#' + 3 random bytes on AB
 * 2.9 / CODESYS V3.5 SPxx). Returns 'xml' / 'binary' / 'unknown'.
 *
 * Empirical 2026-05-26: NexoPlcExample.project starts with bytes
 * 23 89 ED 33 -- a proprietary container we cannot parse without
 * CODESYS itself. Pure-Node offline parsing only works on PLCopen
 * XML exports or .library files saved in XML form on some AB versions.
 */
export function detectProjectFormat(filePath: string): 'xml' | 'binary' | 'unknown' {
  try {
    const fd = fs.openSync(filePath, 'r');
    try {
      const buf = Buffer.alloc(16);
      const bytesRead = fs.readSync(fd, buf, 0, 16, 0);
      if (bytesRead === 0) return 'unknown';
      // Skip leading whitespace + BOM.
      let i = 0;
      while (i < bytesRead && (buf[i] === 0xef || buf[i] === 0xbb || buf[i] === 0xbf
        || buf[i] === 0x20 || buf[i] === 0x09 || buf[i] === 0x0a || buf[i] === 0x0d)) {
        i++;
      }
      if (i >= bytesRead) return 'unknown';
      if (buf[i] === 0x3c /* '<' */) return 'xml';
      // CODESYS binary format starts with '#' on AB 2.9.
      if (buf[i] === 0x23 /* '#' */) return 'binary';
      return 'unknown';
    } finally {
      fs.closeSync(fd);
    }
  } catch {
    return 'unknown';
  }
}

/**
 * Parse a .project / .library file into an OfflineProjectSnapshot.
 *
 * THROWS if the file is in CODESYS's proprietary binary container format
 * (most .project files on AB 2.9 are binary). The error message points
 * the caller at the workaround: export PLCopen XML from AB once, then
 * use this tool against the exported .xml file. Or use the regular
 * get_all_pou_code which goes through CODESYS scripting and handles
 * the binary format natively.
 */
export function parseProjectOffline(filePath: string): OfflineProjectSnapshot {
  const fmt = detectProjectFormat(filePath);
  if (fmt === 'binary') {
    throw new Error(
      `File '${filePath}' is in CODESYS's proprietary binary container format ` +
      `(starts with 0x23 + binary bytes). Pure-Node offline parsing only works ` +
      `on PLCopen XML exports or .library files saved in XML form. ` +
      `Workarounds: (1) call export_plcopenxml from CODESYS first, then use this ` +
      `tool against the XML output; (2) use get_all_pou_code / search_code ` +
      `(non-offline versions) which go through CODESYS scripting and handle the ` +
      `binary format natively.`
    );
  }
  if (fmt === 'unknown') {
    throw new Error(
      `Cannot identify format of '${filePath}'. Expected XML (first non-whitespace ` +
      `byte is '<') or CODESYS binary (first byte is '#'). File may be corrupt or ` +
      `from an unsupported CODESYS version.`
    );
  }
  const text = fs.readFileSync(filePath, 'utf-8');
  const objects: OfflineObject[] = [];

  // Token scan: <object ...> ... </object>, allowing nesting.
  const openRe = /<object\b([^>]*)>/g;
  const closeTag = '</object>';
  const tokens: Array<{ kind: 'open' | 'close'; idx: number; attrs?: string }> = [];
  let m: RegExpExecArray | null;
  while ((m = openRe.exec(text)) !== null) {
    tokens.push({ kind: 'open', idx: m.index, attrs: m[1] });
  }
  let searchFrom = 0;
  while (true) {
    const idx = text.indexOf(closeTag, searchFrom);
    if (idx === -1) break;
    tokens.push({ kind: 'close', idx });
    searchFrom = idx + closeTag.length;
  }
  tokens.sort((a, b) => a.idx - b.idx);

  const stack: Array<{ name: string; kind: OfflineObject['kind']; bodyStart: number }> = [];
  for (const tok of tokens) {
    if (tok.kind === 'open') {
      const nameM = (tok.attrs ?? '').match(/\bname\s*=\s*"([^"]+)"/);
      const typeM = (tok.attrs ?? '').match(/\btype\s*=\s*"([^"]+)"/);
      stack.push({
        name: nameM ? nameM[1] : '?',
        kind: mapKind(typeM ? typeM[1] : '?'),
        bodyStart: tok.idx,
      });
    } else {
      const opened = stack.pop();
      if (!opened) continue;
      const path = stack.map((s) => s.name).concat(opened.name).join('/');
      const span = text.slice(opened.bodyStart, tok.idx + closeTag.length);
      const decl = extractTextual(span, 'textualDeclaration');
      const impl = extractTextual(span, 'textualImplementation');
      if (decl || impl) {
        objects.push({
          name: opened.name,
          kind: opened.kind,
          path,
          declaration: decl,
          implementation: impl,
        });
      }
    }
  }

  return { filePath, objects };
}

function mapKind(t: string): OfflineObject['kind'] {
  const lower = t.toLowerCase();
  if (lower.includes('functionblock') || lower.includes('program') || lower.includes('function')) return 'POU';
  if (lower.includes('gvl')) return 'GVL';
  if (lower.includes('dut') || lower.includes('struct') || lower.includes('enum')) return 'DUT';
  if (lower.includes('parameter')) return 'ParameterList';
  if (lower.includes('method')) return 'Method';
  if (lower.includes('property')) return 'Property';
  if (lower.includes('interface')) return 'Interface';
  return 'Unknown';
}

function extractTextual(span: string, tagBase: string): string {
  const re = new RegExp(`<${tagBase}[^>]*>\\s*<text>([\\s\\S]*?)<\\/text>\\s*<\\/${tagBase}>`, 'i');
  const m = span.match(re);
  if (!m) return '';
  // Unescape common XML entities so the body reads naturally.
  return m[1]
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&')
    .replace(/&quot;/g, '"')
    .replace(/&apos;/g, "'");
}

export interface OfflineSearchHit {
  path: string;
  kind: OfflineObject['kind'];
  /** 'decl' or 'impl' -- which section matched. */
  section: 'decl' | 'impl';
  /** 1-based line number within the section. */
  line: number;
  /** Trimmed line content (or the matched substring's containing line). */
  text: string;
}

/**
 * Search every POU body for a pattern. Pattern is interpreted as a regex
 * unless `literal` is true. Returns one hit per matching line.
 */
export function searchProjectOffline(
  filePath: string,
  pattern: string,
  opts?: { regex?: boolean; caseSensitive?: boolean; maxHits?: number }
): OfflineSearchHit[] {
  const snap = parseProjectOffline(filePath);
  const maxHits = opts?.maxHits ?? 500;
  const flags = opts?.caseSensitive ? 'g' : 'gi';
  const re = opts?.regex ?? false ? new RegExp(pattern, flags) : new RegExp(escapeRegex(pattern), flags);
  const hits: OfflineSearchHit[] = [];

  const scanSection = (obj: OfflineObject, sectionKey: 'decl' | 'impl'): void => {
    const text = sectionKey === 'decl' ? obj.declaration : obj.implementation;
    if (!text) return;
    const lines = text.split(/\r?\n/);
    for (let i = 0; i < lines.length; i++) {
      // Reset regex's lastIndex for global pattern.
      re.lastIndex = 0;
      if (re.test(lines[i])) {
        hits.push({
          path: obj.path,
          kind: obj.kind,
          section: sectionKey,
          line: i + 1,
          text: lines[i].trim(),
        });
        if (hits.length >= maxHits) return;
      }
    }
  };

  for (const obj of snap.objects) {
    if (hits.length >= maxHits) break;
    scanSection(obj, 'decl');
    if (hits.length >= maxHits) break;
    scanSection(obj, 'impl');
  }
  return hits;
}

function escapeRegex(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
