import assert from 'node:assert/strict';
import test from 'node:test';

import { PhoneH264PacketParser, phoneVideoDecoderSupported } from './phoneVideoProtocol';

function packet(payload: number[], timestamp: bigint, flags = 1, sequence = 7): Uint8Array {
  const bytes = new Uint8Array(24 + payload.length);
  const view = new DataView(bytes.buffer);
  view.setUint32(0, 0x4c554d49);
  view.setUint8(4, 1);
  view.setUint8(5, flags);
  view.setUint16(6, 24);
  view.setBigUint64(8, timestamp);
  view.setUint32(16, payload.length);
  view.setUint32(20, sequence);
  bytes.set(payload, 24);
  return bytes;
}

test('parses length-delimited H264 access units across arbitrary HTTP chunks', () => {
  const parser = new PhoneH264PacketParser();
  const bytes = packet([0, 0, 0, 1, 0x65, 1, 2], 88_000n);
  assert.deepEqual(parser.push(bytes.slice(0, 9)), []);
  const frames = parser.push(bytes.slice(9));
  assert.equal(frames.length, 1);
  assert.equal(frames[0].type, 'key');
  assert.equal(frames[0].timestamp, 88_000);
  assert.equal(frames[0].sequence, 7);
  assert.deepEqual([...frames[0].data], [0, 0, 0, 1, 0x65, 1, 2]);
});

test('rejects oversized payload declarations before buffering attacker-controlled data', () => {
  const parser = new PhoneH264PacketParser(16);
  const bytes = packet(new Array(17).fill(1), 1n);
  assert.throws(() => parser.push(bytes), /payload length/i);
});

test('reports decoder support without throwing when WebCodecs is absent', () => {
  assert.equal(phoneVideoDecoderSupported({}), false);
  assert.equal(phoneVideoDecoderSupported({ VideoDecoder: class {}, EncodedVideoChunk: class {} }), true);
});
