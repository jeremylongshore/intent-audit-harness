// ESLint flat config (ESLint 9+) for the audit-harness Node dispatcher.
//
// Scope: the CommonJS CLI entrypoint(s) under bin/. The deterministic gates
// themselves are polyglot shell + Python (linted by shellcheck + ruff in CI) —
// JS lint covers only the thin dispatcher.
//
// Ruleset: the official @eslint/js "recommended" set (catches real bugs:
// undeclared vars, unreachable code, duplicate keys, etc.) tuned for Node
// CommonJS globals. Deliberately permissive — this lane is a correctness floor,
// not a style enforcer (formatting is out of scope here).
const js = require('@eslint/js');

module.exports = [
  js.configs.recommended,
  {
    files: ['bin/**/*.js'],
    languageOptions: {
      ecmaVersion: 2022,
      sourceType: 'commonjs',
      globals: {
        // Node CommonJS runtime globals used by the dispatcher.
        require: 'readonly',
        module: 'readonly',
        process: 'readonly',
        console: 'readonly',
        __dirname: 'readonly',
        __filename: 'readonly',
        setTimeout: 'readonly',
        clearTimeout: 'readonly',
        Buffer: 'readonly',
      },
    },
  },
  {
    // Never lint dependencies or build output.
    ignores: ['node_modules/**', 'dist/**', 'build/**', 'coverage/**'],
  },
];
