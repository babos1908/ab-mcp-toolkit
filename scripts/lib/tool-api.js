'use strict';
/**
 * The MCP tool API, read straight from source.
 *
 * Every `s.tool(name, description, shape, handler)` registration in
 * src/server.ts becomes { name, description, params: [{ name, type,
 * required, values?, constraints, description }] }. It parses the source
 * with the TypeScript compiler API rather than importing the server, so it
 * needs no build and no running AB, and it works on any revision's source
 * text -- release-guard.js runs it on `git show vX.Y.Z:src/server.ts`.
 *
 * Shared by gen-tool-catalog.js (the published catalog), release-guard.js
 * (SemVer checks) and the tests. The public API this describes is declared
 * in docs/PUBLIC-API.md.
 */
const ts = require('typescript');

const REGISTRARS = new Set(['s', 'server']);

function literalText(node) {
  if (!node) return null;
  if (ts.isStringLiteralLike(node)) return node.text;
  if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
    const l = literalText(node.left);
    const r = literalText(node.right);
    return l !== null && r !== null ? l + r : null;
  }
  if (ts.isParenthesizedExpression(node)) return literalText(node.expression);
  return null;
}

/** z.number().int().describe('...').optional() -> calls innermost first. */
function zodChain(expr) {
  const calls = [];
  let e = expr;
  while (ts.isCallExpression(e) && ts.isPropertyAccessExpression(e.expression)) {
    calls.unshift({ name: e.expression.name.text, args: Array.from(e.arguments) });
    e = e.expression.expression;
  }
  return { root: ts.isIdentifier(e) ? e.text : null, calls };
}

function zodParam(expr, sf) {
  const { root, calls } = zodChain(expr);
  if (root !== 'z' || calls.length === 0) {
    return { type: 'unknown', required: true, constraints: [], description: null };
  }
  const base = calls[0];
  let type = base.name;
  let values;
  if (base.name === 'enum' && base.args[0] && ts.isArrayLiteralExpression(base.args[0])) {
    values = base.args[0].elements.map(literalText).filter((x) => x !== null);
  } else if (base.name === 'array' && base.args[0]) {
    type = `${zodParam(base.args[0], sf).type}[]`;
  } else if (base.name === 'union' && base.args[0] && ts.isArrayLiteralExpression(base.args[0])) {
    type = base.args[0].elements.map((el) => zodParam(el, sf).type).join(' | ');
  } else if (base.name === 'literal' && base.args[0]) {
    type = `literal ${base.args[0].getText(sf)}`;
  }
  let required = true;
  let description = null;
  const constraints = [];
  for (const c of calls.slice(1)) {
    if (c.name === 'optional' || c.name === 'nullish' || c.name === 'default') required = false;
    else if (c.name === 'describe') description = literalText(c.args[0]);
    else if (c.name === 'int' || c.name === 'positive' || c.name === 'nonnegative') constraints.push(c.name);
    else if (c.name === 'min' || c.name === 'max') constraints.push(`${c.name} ${c.args[0] ? c.args[0].getText(sf) : ''}`.trim());
  }
  const out = { type, required, constraints, description };
  if (values) out.values = values;
  return out;
}

/**
 * Every tool registered in the given server.ts source, sorted by name.
 * @param {string} sourceText
 */
function extractTools(sourceText) {
  const sf = ts.createSourceFile('server.ts', sourceText, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);

  // `const taskKnobs = { ... }` objects, so a shape that spreads one
  // (`{ projectFilePath, ...taskKnobs }`) lists its parameters too.
  const objectConsts = new Map();
  const collect = (node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name)
        && node.initializer && ts.isObjectLiteralExpression(node.initializer)) {
      objectConsts.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, collect);
  };
  collect(sf);

  const shapeParams = (obj, seen) => {
    const byName = new Map(); // later entries override earlier ones, as in JS
    for (const p of obj.properties) {
      if (ts.isPropertyAssignment(p)) {
        const pname = p.name.getText(sf).replace(/^['"`]|['"`]$/g, '');
        byName.delete(pname);
        byName.set(pname, { name: pname, ...zodParam(p.initializer, sf) });
      } else if (ts.isSpreadAssignment(p) && ts.isIdentifier(p.expression)
                 && objectConsts.has(p.expression.text) && !seen.has(p.expression.text)) {
        const inner = shapeParams(objectConsts.get(p.expression.text), new Set([...seen, p.expression.text]));
        for (const q of inner) { byName.delete(q.name); byName.set(q.name, q); }
      }
    }
    return [...byName.values()];
  };

  const tools = [];
  const visit = (node) => {
    if (ts.isCallExpression(node)
        && ts.isPropertyAccessExpression(node.expression)
        && node.expression.name.text === 'tool'
        && ts.isIdentifier(node.expression.expression)
        && REGISTRARS.has(node.expression.expression.text)) {
      const [nameArg, descArg, shapeArg] = node.arguments;
      const name = literalText(nameArg);
      if (name) {
        const params = shapeArg && ts.isObjectLiteralExpression(shapeArg)
          ? shapeParams(shapeArg, new Set())
          : [];
        const description = (literalText(descArg) || '').replace(/\s+/g, ' ').trim();
        tools.push({ name, description, params });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  tools.sort((a, b) => a.name.localeCompare(b.name));
  return tools;
}

function index(tools) {
  const out = {};
  for (const t of tools) {
    out[t.name] = {};
    for (const p of t.params) out[t.name][p.name] = p;
  }
  return out;
}

/**
 * What changed in the tool API between two revisions, classified by the
 * SemVer level it requires (docs/PUBLIC-API.md, "What counts as what").
 * Descriptions are not compared: wording is not API.
 */
function diffApi(oldTools, newTools) {
  const major = [];
  const minor = [];
  const o = index(oldTools);
  const n = index(newTools);
  for (const name of Object.keys(o)) {
    if (!n[name]) { major.push(`tool removed: ${name}`); continue; }
    for (const pn of Object.keys(o[name])) {
      const op = o[name][pn];
      const np = n[name][pn];
      if (!np) { major.push(`${name}: parameter removed: ${pn}`); continue; }
      if (op.type !== np.type) major.push(`${name}.${pn}: type ${op.type} -> ${np.type}`);
      if (!op.required && np.required) major.push(`${name}.${pn}: optional -> required`);
      if (op.required && !np.required) minor.push(`${name}.${pn}: required -> optional`);
      const ov = op.values || [];
      const nv = np.values || [];
      for (const v of ov) if (!nv.includes(v)) major.push(`${name}.${pn}: value removed: ${v}`);
      for (const v of nv) if (!ov.includes(v)) minor.push(`${name}.${pn}: value added: ${v}`);
    }
    for (const pn of Object.keys(n[name])) {
      if (o[name][pn]) continue;
      if (n[name][pn].required) major.push(`${name}: required parameter added: ${pn}`);
      else minor.push(`${name}: optional parameter added: ${pn}`);
    }
  }
  for (const name of Object.keys(n)) if (!o[name]) minor.push(`tool added: ${name}`);
  return { major, minor, level: major.length ? 'major' : minor.length ? 'minor' : 'none' };
}

module.exports = { extractTools, diffApi };
