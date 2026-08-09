export interface PhoneH264AccessUnit {
  type: 'key' | 'delta';
  timestamp: number;
  sequence: number;
  data: Uint8Array;
}

const MAGIC = 0x4c554d49;
const VERSION = 1;
const HEADER_SIZE = 24;
const KEY_FRAME_FLAG = 1;
const DEFAULT_MAX_PAYLOAD = 8 * 1024 * 1024;

export class PhoneH264PacketParser {
  private buffered = new Uint8Array(0);

  constructor(private readonly maxPayloadBytes = DEFAULT_MAX_PAYLOAD) {}

  push(chunk: Uint8Array): PhoneH264AccessUnit[] {
    if (chunk.byteLength) {
      const combined = new Uint8Array(this.buffered.byteLength + chunk.byteLength);
      combined.set(this.buffered);
      combined.set(chunk, this.buffered.byteLength);
      this.buffered = combined;
    }
    const packets: PhoneH264AccessUnit[] = [];
    let offset = 0;
    while (this.buffered.byteLength - offset >= HEADER_SIZE) {
      const view = new DataView(
        this.buffered.buffer,
        this.buffered.byteOffset + offset,
        this.buffered.byteLength - offset,
      );
      if (view.getUint32(0) !== MAGIC || view.getUint8(4) !== VERSION || view.getUint16(6) !== HEADER_SIZE) {
        throw new Error('Invalid LUMI H264 frame header');
      }
      const payloadLength = view.getUint32(16);
      if (payloadLength <= 0 || payloadLength > this.maxPayloadBytes) {
        throw new Error(`Invalid H264 payload length: ${payloadLength}`);
      }
      const packetLength = HEADER_SIZE + payloadLength;
      if (this.buffered.byteLength - offset < packetLength) break;
      const timestamp = Number(view.getBigUint64(8));
      if (!Number.isSafeInteger(timestamp)) throw new Error('Invalid H264 presentation timestamp');
      packets.push({
        type: view.getUint8(5) & KEY_FRAME_FLAG ? 'key' : 'delta',
        timestamp,
        sequence: view.getUint32(20),
        data: this.buffered.slice(offset + HEADER_SIZE, offset + packetLength),
      });
      offset += packetLength;
    }
    if (offset) this.buffered = this.buffered.slice(offset);
    return packets;
  }
}

export function phoneVideoDecoderSupported(scope: Record<string, unknown> = globalThis as unknown as Record<string, unknown>): boolean {
  return typeof scope.VideoDecoder === 'function' && typeof scope.EncodedVideoChunk === 'function';
}
