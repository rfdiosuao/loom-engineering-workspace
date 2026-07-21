import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import fs from 'node:fs/promises';
import http from 'node:http';
import os from 'node:os';
import path from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const execFileAsync = promisify(execFile);
const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);
const scriptPath = path.join(__dirname, 'openclaw-media-phone.mjs');

async function listen(server) {
  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(0, '127.0.0.1', resolve);
  });
  return server.address().port;
}

async function close(server) {
  await new Promise((resolve, reject) => server.close((error) => (error ? reject(error) : resolve())));
}

test('upload-only media CLI imports images and videos without Agent task requests', async () => {
  const requests = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => { chunks.push(Buffer.from(chunk)); });
    request.on('end', () => {
      const body = Buffer.concat(chunks);
      requests.push({
        method: request.method,
        path: request.url,
        body,
        contentType: request.headers['content-type'],
        signed: Boolean(request.headers['x-lumi-signature']),
      });
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { relativePath: `Pictures/LOOM/${requests.length}` } }));
    });
  });
  const port = await listen(server);
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-media-phone-'));
  const imagePath = path.join(tempDir, 'sample.png');
  const videoPath = path.join(tempDir, 'sample.mp4');
  const phoneToken = 'NODE_TEST_PHONE_TOKEN';

  try {
    await fs.writeFile(imagePath, Buffer.from('image'));
    await fs.writeFile(videoPath, Buffer.from('video'));
    const runtimeConfig = {
      selectedDeviceId: 'phone-a',
      devices: [{
        id: 'phone-a',
        baseUrl: `http://127.0.0.1:${port}`,
        token: phoneToken,
        launcherId: 'launcher-id',
        launcherSecret: 'launcher-secret',
        album: 'LOOM',
      }],
    };
    const args = [
      scriptPath,
      '--device-id',
      'phone-a',
      '--image',
      imagePath,
      '--video',
      videoPath,
      '--json',
    ];
    const { stdout, stderr } = await execFileAsync(process.execPath, args, {
      env: {
        ...process.env,
        LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(runtimeConfig),
      },
    });
    const result = JSON.parse(stdout);

    assert.equal(result.ok, true);
    assert.equal(result.uploadedCount, 2);
    assert.equal(requests.length, 2);
    assert.match(requests[0].path, /^\/api\/lumi\/media\/import_file\?kind=image&/);
    assert.match(requests[1].path, /^\/api\/lumi\/media\/import_file\?kind=video&/);
    assert.ok(requests.every((request) => request.method === 'POST' && request.signed));
    assert.ok(requests.every((request) => request.contentType === 'application/octet-stream'));
    assert.equal(requests[0].body.toString('utf8'), 'image');
    assert.equal(requests[1].body.toString('utf8'), 'video');
    assert.ok(requests.every((request) => request.path.includes('album=LOOM')));
    assert.ok(requests.every((request) => !request.body.toString('utf8').includes('base64')));
    assert.equal(requests.filter((request) => /agent|task/i.test(request.path)).length, 0);
    assert.equal(args.includes(phoneToken), false);
    assert.equal(stdout.includes(phoneToken), false);
    assert.equal(stderr.includes(phoneToken), false);
  } finally {
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('partial upload failure reports safe counts and basenames without paths or secrets', async () => {
  const requests = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => { chunks.push(Buffer.from(chunk)); });
    request.on('end', () => {
      requests.push({ path: request.url, body: Buffer.concat(chunks) });
      if (request.url.includes('kind=video')) {
        response.writeHead(500, { 'Content-Type': 'application/json' });
        response.end(JSON.stringify({ success: false, error: 'NODE_TEST_PHONE_TOKEN rejected' }));
        return;
      }
      response.writeHead(200, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: true, data: { relativePath: 'Pictures/LOOM/sample.png' } }));
    });
  });
  const port = await listen(server);
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-media-phone-partial-'));
  const imagePath = path.join(tempDir, 'first.png');
  const videoPath = path.join(tempDir, 'second.mp4');
  const phoneToken = 'NODE_TEST_PHONE_TOKEN';

  try {
    await fs.writeFile(imagePath, Buffer.from('image'));
    await fs.writeFile(videoPath, Buffer.from('video'));
    const runtimeConfig = {
      selectedDeviceId: 'phone-a',
      devices: [{
        id: 'phone-a',
        baseUrl: `http://127.0.0.1:${port}`,
        token: phoneToken,
        launcherId: 'launcher-id',
        launcherSecret: 'launcher-secret',
        album: 'LOOM',
      }],
    };
    let failure;
    try {
      await execFileAsync(process.execPath, [
        scriptPath,
        '--device-id',
        'phone-a',
        '--image',
        imagePath,
        '--video',
        videoPath,
        '--json',
      ], {
        env: {
          ...process.env,
          LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(runtimeConfig),
        },
      });
      assert.fail('partial upload must exit non-zero');
    } catch (error) {
      failure = JSON.parse(String(error.stdout || '').trim());
      assert.equal(String(error.stderr || '').includes(phoneToken), false);
    }

    assert.equal(failure.ok, false);
    assert.equal(failure.errorCode, 'media_upload_partial_failure');
    assert.equal(failure.uploadedCount, 1);
    assert.equal(failure.totalCount, 2);
    assert.deepEqual(failure.uploaded, [{ kind: 'image', filename: 'first.png' }]);
    assert.deepEqual(failure.failed, [{
      kind: 'video',
      filename: 'second.mp4',
      errorCode: 'phone_media_import_failed',
      message: '[redacted] rejected',
    }]);
    const serialized = JSON.stringify(failure);
    assert.equal(serialized.includes(tempDir), false);
    assert.equal(serialized.includes(phoneToken), false);
    assert.equal(requests.length, 2);
    assert.ok(requests[0].path.includes('kind=image'));
    assert.ok(requests[1].path.includes('kind=video'));
  } finally {
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('interrupted media stream keeps an actionable transfer error instead of reporting the phone offline', async () => {
  const server = http.createServer((request) => {
    request.socket.destroy();
  });
  const port = await listen(server);
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-media-phone-reset-'));
  const videoPath = path.join(tempDir, 'large-video.mp4');

  try {
    await fs.writeFile(videoPath, Buffer.alloc(1024 * 1024, 7));
    const runtimeConfig = {
      selectedDeviceId: 'phone-a',
      devices: [{
        id: 'phone-a',
        baseUrl: `http://127.0.0.1:${port}`,
        token: 'phone-token',
        launcherId: 'launcher-id',
        launcherSecret: 'launcher-secret',
        album: 'LOOM',
      }],
    };
    let failure;
    try {
      await execFileAsync(process.execPath, [
        scriptPath,
        '--device-id',
        'phone-a',
        '--video',
        videoPath,
        '--json',
      ], {
        env: {
          ...process.env,
          LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(runtimeConfig),
        },
      });
      assert.fail('interrupted upload must exit non-zero');
    } catch (error) {
      failure = JSON.parse(String(error.stdout || '').trim());
    }

    assert.equal(failure.ok, false);
    assert.equal(failure.errorCode, 'phone_media_transfer_interrupted');
    assert.match(failure.message, /传输中断/);
    assert.deepEqual(failure.failed, [{
      kind: 'video',
      filename: 'large-video.mp4',
      errorCode: 'phone_media_transfer_interrupted',
      message: '媒体文件传输中断，请保持手机端 APKClaw 在前台或允许后台运行后重试。',
    }]);
    assert.equal(JSON.stringify(failure).includes(tempDir), false);
  } finally {
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('older phone builds receive small media through the signed JSON compatibility endpoint', async () => {
  const requests = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(Buffer.from(chunk)));
    request.on('end', () => {
      const body = Buffer.concat(chunks);
      requests.push({ path: request.url, body, contentType: request.headers['content-type'] });
      response.writeHead(request.url.startsWith('/api/lumi/media/import_file') ? 404 : 200, {
        'Content-Type': 'application/json',
      });
      response.end(JSON.stringify(
        request.url.startsWith('/api/lumi/media/import_file')
          ? { success: false, error: 'not found' }
          : { success: true, data: { relativePath: 'Movies/LOOM/legacy.mp4' } },
      ));
    });
  });
  const port = await listen(server);
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-media-phone-legacy-'));
  const videoPath = path.join(tempDir, 'legacy.mp4');

  try {
    await fs.writeFile(videoPath, Buffer.from('small-video'));
    const runtimeConfig = {
      selectedDeviceId: 'phone-a',
      devices: [{
        id: 'phone-a',
        baseUrl: `http://127.0.0.1:${port}`,
        token: 'phone-token',
        launcherId: 'launcher-id',
        launcherSecret: 'launcher-secret',
        album: 'LOOM',
      }],
    };
    const { stdout } = await execFileAsync(process.execPath, [
      scriptPath,
      '--device-id', 'phone-a',
      '--video', videoPath,
      '--json',
    ], {
      env: { ...process.env, LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(runtimeConfig) },
    });

    assert.equal(JSON.parse(stdout).ok, true);
    assert.equal(requests.length, 2);
    assert.ok(requests[0].path.startsWith('/api/lumi/media/import_file?kind=video'));
    assert.equal(requests[0].contentType, 'application/octet-stream');
    assert.equal(requests[1].path, '/api/lumi/media/import_video');
    assert.equal(requests[1].contentType, 'application/json; charset=utf-8');
    assert.match(JSON.parse(requests[1].body.toString('utf8')).dataUrl, /^data:video\/mp4;base64,/);
  } finally {
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});

test('older phone builds reject large legacy JSON fallback with an upgrade instruction', async () => {
  const requests = [];
  const server = http.createServer((request, response) => {
    request.resume();
    request.on('end', () => {
      requests.push(request.url);
      response.writeHead(404, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ success: false, error: 'not found' }));
    });
  });
  const port = await listen(server);
  const tempDir = await fs.mkdtemp(path.join(os.tmpdir(), 'loom-media-phone-upgrade-'));
  const videoPath = path.join(tempDir, 'large-legacy.mp4');

  try {
    await fs.writeFile(videoPath, Buffer.alloc((8 * 1024 * 1024) + 1, 3));
    const runtimeConfig = {
      selectedDeviceId: 'phone-a',
      devices: [{
        id: 'phone-a',
        baseUrl: `http://127.0.0.1:${port}`,
        token: 'phone-token',
        launcherId: 'launcher-id',
        launcherSecret: 'launcher-secret',
        album: 'LOOM',
      }],
    };
    let failure;
    try {
      await execFileAsync(process.execPath, [
        scriptPath,
        '--device-id', 'phone-a',
        '--video', videoPath,
        '--json',
      ], {
        env: { ...process.env, LOOM_PHONE_RUNTIME_CONFIG_JSON: JSON.stringify(runtimeConfig) },
      });
      assert.fail('large legacy fallback must fail');
    } catch (error) {
      failure = JSON.parse(String(error.stdout || '').trim());
    }

    assert.equal(failure.errorCode, 'phone_media_streaming_update_required');
    assert.match(failure.message, /升级手机端/);
    assert.equal(requests.length, 1);
    assert.ok(requests[0].startsWith('/api/lumi/media/import_file?kind=video'));
  } finally {
    await close(server);
    await fs.rm(tempDir, { recursive: true, force: true });
  }
});
