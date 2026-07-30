import assert from 'node:assert/strict';
import { File } from 'node:buffer';
import { test } from 'node:test';

import { prepareAgentAttachments } from './agentAttachments.ts';

test('image attachments are encoded for secure server-side materialization', async () => {
  const file = new File(
    [Uint8Array.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00])],
    'cover.png',
    { type: 'image/png', lastModified: 7 },
  );

  const [attachment] = await prepareAgentAttachments([file as unknown as globalThis.File]);

  assert.equal(attachment.kind, 'image');
  assert.equal(attachment.name, 'cover.png');
  assert.equal(attachment.type, 'image/png');
  assert.match(attachment.dataUrl || '', /^data:image\/png;base64,/);
});

test('text attachments retain bounded readable content', async () => {
  const file = new File(['hello LOOM'], 'brief.md', {
    type: 'text/markdown',
    lastModified: 8,
  });

  const [attachment] = await prepareAgentAttachments([file as unknown as globalThis.File]);

  assert.equal(attachment.kind, 'text');
  assert.equal(attachment.content, 'hello LOOM');
  assert.equal(attachment.truncated, false);
});

test('unsupported documents fail visibly instead of being silently ignored', async () => {
  const file = new File(['pdf'], 'brief.pdf', {
    type: 'application/pdf',
    lastModified: 9,
  });

  await assert.rejects(
    prepareAgentAttachments([file as unknown as globalThis.File]),
    /暂不支持 brief\.pdf/,
  );
});
