#!/usr/bin/env node
/** Optional TypeScript compiler API provider. No bundled npm dependencies.
 * Function complexity v1: 1 + if/ternary/loops/catch/non-default case,
 * &&/||/?? and their assignments, and each optional access/call.
 * Nested functions and class bodies are independent; type syntax is excluded.
 * Module/class initializer expressions are not claimed as functions.
 */
import { createHash } from 'node:crypto';
import { readFileSync, realpathSync } from 'node:fs';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
const hash = (bytes) => createHash('sha256').update(bytes).digest('hex');

try {
  const request = JSON.parse(readFileSync(0, 'utf8'));
  const parserPath = realpathSync(resolve(request.root, 'node_modules/typescript/lib/typescript.js'));
  const parserHash = hash(readFileSync(parserPath));
  const ts = createRequire(import.meta.url)(parserPath);
  if (typeof ts.version !== 'string') throw new Error('invalid TypeScript version');
  const decisions = new Set(['IfStatement', 'ConditionalExpression', 'ForStatement', 'ForInStatement',
    'ForOfStatement', 'WhileStatement', 'DoStatement', 'CatchClause', 'CaseClause'].map(k => ts.SyntaxKind[k]));
  const logical = new Set(['AmpersandAmpersandToken', 'BarBarToken', 'QuestionQuestionToken',
    'AmpersandAmpersandEqualsToken', 'BarBarEqualsToken', 'QuestionQuestionEqualsToken'].map(k => ts.SyntaxKind[k]));
  const functionKinds = new Set(['FunctionDeclaration', 'FunctionExpression', 'ArrowFunction',
    'MethodDeclaration', 'Constructor', 'GetAccessor', 'SetAccessor'].map(k => ts.SyntaxKind[k]));
  const files = {};
  for (const entry of request.files) {
    const bytes = readFileSync(resolve(request.root, entry.path));
    if (hash(bytes) !== entry.sha256) throw new Error('source changed before parsing');
    const text = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
    const source = ts.createSourceFile(entry.path, text, ts.ScriptTarget.Latest, true,
      entry.path.endsWith('.tsx') ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
    if (source.parseDiagnostics.length) throw new Error(`TypeScript parse diagnostics: ${entry.path}`);
    const nodes = [];
    function inventory(node) {
      if (functionKinds.has(node.kind) && node.body) nodes.push(node);
      ts.forEachChild(node, inventory);
    }
    inventory(source);
    const identities = nodes.map(node => {
      const start = node.getStart(source), end = node.end;
      return { id: `${start}:${end}`, start, end,
        line: source.getLineAndCharacterOfPosition(start).line + 1,
        name: node.name?.getText(source) || `<${ts.SyntaxKind[node.kind]}@${start}>`,
        kind: ts.SyntaxKind[node.kind] };
    });
    const methods = nodes.map((node, index) => {
      let complexity = 1;
      function visit(child) {
        if (child !== node && (ts.isFunctionLike(child) || ts.isClassLike(child))) return;
        if (ts.isTypeNode(child)) return;
        if (decisions.has(child.kind)) complexity++;
        if (ts.isBinaryExpression(child) && logical.has(child.operatorToken.kind)) complexity++;
        if ((ts.isPropertyAccessExpression(child) || ts.isElementAccessExpression(child)
          || ts.isCallExpression(child)) && child.questionDotToken) complexity++;
        ts.forEachChild(child, visit);
      }
      visit(node);
      return { id: identities[index].id, complexity };
    });
    // Conservative syntactic proof: never exempt runtime imports, re-exports,
    // variable initializers, enums, classes or namespace bodies from coverage.
    const typeOnly = nodes.length === 0 && source.statements.every(node =>
      ts.isInterfaceDeclaration(node) || ts.isTypeAliasDeclaration(node) || ts.isEmptyStatement(node)
      || (ts.isImportDeclaration(node) && node.importClause?.isTypeOnly === true)
      || (ts.isExportDeclaration(node) && node.isTypeOnly === true)
      || ((ts.isVariableStatement(node) || ts.isFunctionDeclaration(node)
        || ts.isClassDeclaration(node) || ts.isEnumDeclaration(node) || ts.isModuleDeclaration(node))
        && node.modifiers?.some(modifier => modifier.kind === ts.SyntaxKind.DeclareKeyword)));
    files[entry.path] = { sha256: entry.sha256, type_only: typeOnly, inventory: identities, methods };
  }
  if (hash(readFileSync(parserPath)) !== parserHash) throw new Error('parser changed during measurement');
  process.stdout.write(JSON.stringify({ schema_version: 'crap-typescript/v1', files,
    provider: { name: 'typescript', version: ts.version, path: parserPath, sha256: parserHash },
    complexity_definition: 'typescript-function-decisions/v1' }));
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 2;
}
