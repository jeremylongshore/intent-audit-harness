const assert = require('node:assert/strict');
const { spawn } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { setTimeout: delay } = require('node:timers/promises');

const source = fs.readFileSync(path.resolve(__dirname, '../../bin/audit-harness.js'), 'utf8');
const posix = process.platform !== 'win32';

function fixture(t, script) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'harness-timeout-'));
  fs.mkdirSync(path.join(root, 'bin'));
  fs.mkdirSync(path.join(root, 'scripts'));
  fs.writeFileSync(path.join(root, 'bin/audit-harness.js'), source);
  fs.writeFileSync(path.join(root, 'scripts/harness-hash.sh'), script);
  t.after(() => {
    const pidFile = path.join(root, 'descendant.pid');
    if (fs.existsSync(pidFile)) {
      try { process.kill(Number(fs.readFileSync(pidFile, 'utf8')), 'SIGKILL'); }
      catch (error) { if (error.code !== 'ESRCH') throw error; }
    }
    fs.rmSync(root, { recursive: true, force: true });
  });
  return root;
}

async function run(root, timeout, args = [], interrupt) {
  const env = { ...process.env, BBB_TIMEOUT_FIXTURE: root };
  delete env.AUDIT_HARNESS_TIMEOUT;
  delete env.AUDIT_HARNESS_DISABLE;
  if (timeout !== undefined) env.AUDIT_HARNESS_TIMEOUT = timeout;
  const child = spawn(process.execPath, [path.join(root, 'bin/audit-harness.js'), 'verify', ...args], {
    env, stdio: ['ignore', 'pipe', 'pipe'],
  });
  let stdout = '', stderr = '';
  child.stdout.on('data', data => { stdout += data; });
  child.stderr.on('data', data => { stderr += data; });
  if (interrupt) setTimeout(() => child.kill(interrupt), 1000);
  const watchdog = setTimeout(() => child.kill('SIGKILL'), 10000);
  try {
    const code = await new Promise((resolve, reject) => {
      child.on('error', reject);
      child.on('exit', resolve);
    });
    return { code, stdout, stderr };
  } finally { clearTimeout(watchdog); }
}

for (const timeout of [undefined, '0', '5']) {
  test(`normal exit and exact arguments survive timeout=${timeout}`, { skip: !posix }, async t => {
    const root = fixture(t, 'printf "%s\\n" "$@"\nexit 7\n');
    const result = await run(root, timeout, ['two words', '']);
    assert.equal(result.code, 7);
    assert.equal(result.stdout, '--verify\ntwo words\n\n');
    assert.equal(result.stderr, '');
  });
}

test('timeout force-kills a direct child that ignores SIGTERM', { skip: !posix }, async t => {
  const root = fixture(t, "trap '' TERM\nwhile :; do sleep 1; done\n");
  const result = await run(root, '0.3');
  assert.equal(result.code, 124);
  assert.match(result.stderr, /exceeded AUDIT_HARNESS_TIMEOUT/);
});

test('timeout cleans a TERM-resistant descendant even after the shell exits', async t => {
  const root = fixture(t, 'node "$BBB_TIMEOUT_FIXTURE/descendant.cjs" >/dev/null 2>&1 &\nwait\n');
  fs.writeFileSync(path.join(root, 'descendant.cjs'), `
    const fs = require('node:fs');
    const root = process.env.BBB_TIMEOUT_FIXTURE;
    fs.writeFileSync(root + '/descendant.pid', String(process.pid));
    process.on('SIGTERM', () => {});
    setTimeout(() => fs.writeFileSync(root + '/survived', 'bad'), 4200);
    setInterval(() => {}, 1000);
  `);
  const start = Date.now();
  const result = await run(root, '1');
  assert.equal(result.code, 124);
  assert.ok(fs.existsSync(path.join(root, 'descendant.pid')), 'fixture descendant actually started');
  await delay(Math.max(0, 4600 - (Date.now() - start)));
  assert.equal(fs.existsSync(path.join(root, 'survived')), false, 'descendant kept operating after timeout');
});

test('operator cancellation cleans the isolated timeout group', { skip: !posix }, async t => {
  const root = fixture(t, 'node "$BBB_TIMEOUT_FIXTURE/descendant.cjs" >/dev/null 2>&1 &\nwait\n');
  fs.writeFileSync(path.join(root, 'descendant.cjs'), `
    const fs = require('node:fs');
    const root = process.env.BBB_TIMEOUT_FIXTURE;
    fs.writeFileSync(root + '/descendant.pid', String(process.pid));
    process.on('SIGTERM', () => {});
    setTimeout(() => fs.writeFileSync(root + '/survived', 'bad'), 4200);
    setInterval(() => {}, 1000);
  `);
  const start = Date.now();
  const result = await run(root, '8', [], 'SIGTERM');
  assert.equal(result.code, 143);
  assert.ok(fs.existsSync(path.join(root, 'descendant.pid')));
  await delay(Math.max(0, 4600 - (Date.now() - start)));
  assert.equal(fs.existsSync(path.join(root, 'survived')), false);
});

function windowsTimeout(taskkillResult) {
  const timers = [], calls = [], listeners = {}, errors = [];
  const sentinel = new Error('process exit');
  const child = { pid: 4321, on: (event, fn) => { listeners[event] = fn; } };
  let exitCode;
  const sandbox = {
    __dirname: '/fixture/bin',
    console: { log() {}, error(message) { errors.push(message); } },
    process: {
      argv: ['node', 'cli', 'verify'], platform: 'win32', env: { AUDIT_HARNESS_TIMEOUT: '1' },
      exit(code) { exitCode = code; throw sentinel; },
    },
    require(name) {
      if (name === 'node:child_process') return {
        spawn(...args) { calls.push(['spawn', ...args]); return child; },
        spawnSync(...args) { calls.push(['spawnSync', ...args]); return taskkillResult; },
      };
      if (name === 'node:path') return path;
      if (name === 'node:fs') return { existsSync: () => true };
      throw new Error('Unexpected import ' + name);
    },
    setTimeout(fn) { timers.push(fn); return { unref() {} }; }, clearTimeout() {},
  };
  vm.runInNewContext(source, sandbox);
  assert.throws(() => timers.shift()(), error => error === sentinel);
  return { calls, exitCode, errors };
}

test('Windows timeout requests taskkill for the exact PID and its tree', () => {
  const result = windowsTimeout({ status: 0 });
  assert.equal(result.exitCode, 124);
  const taskkill = result.calls.find(call => call[0] === 'spawnSync');
  assert.equal(taskkill[1], 'taskkill');
  assert.deepEqual(Array.from(taskkill[2]), ['/PID', '4321', '/T', '/F']);
  assert.equal(taskkill[3].timeout, 5000);
});

test('Windows taskkill failure remains a timeout with visible cleanup failure', () => {
  const result = windowsTimeout({ status: 1 });
  assert.equal(result.exitCode, 124);
  assert.match(result.errors.join('\n'), /process-tree cleanup failed/);
});
