import type { PreviewSettings } from '../store/appStore';
import { requestBridgeData } from './adapters';

export function stripAnsi(text: string): string {
  return text.replace(/\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])/g, '');
}

function visibleAnsiQrBlocks(text: string): string {
  return text
    .replace(/\x1B\[(?:\d+;)*(?:47|46|107|106)m( +)\x1B\[0m/g, (_, spaces: string) => '█'.repeat(spaces.length))
    .replace(/\x1B\[(?:\d+;)*(?:40|100)m( +)\x1B\[0m/g, (_, spaces: string) => ' '.repeat(spaces.length))
    .replace(/\x1B\[7m( +)\x1B\[0m/g, (_, spaces: string) => '█'.repeat(spaces.length));
}

export function normalizeCommandOutput(data: unknown): string {
  const text = data instanceof Uint8Array
    ? new TextDecoder('utf-8').decode(data)
    : String(data ?? '');
  return stripAnsi(visibleAnsiQrBlocks(text));
}

function isWindowsRoot(root: string): boolean {
  return /^[a-zA-Z]:[\\/]/.test(root) || root.includes('\\');
}

function joinRuntimePath(root: string, ...segments: string[]): string {
  const separator = isWindowsRoot(root) ? '\\' : '/';
  const cleanRoot = root.replace(/[\\/]+$/, '');
  return [cleanRoot, ...segments.map((segment) => segment.replace(/^[\\/]+|[\\/]+$/g, ''))].join(separator);
}

function runtimePathDelimiter(root: string): string {
  return isWindowsRoot(root) ? ';' : ':';
}

function systemPathEntries(root: string): string[] {
  if (isWindowsRoot(root)) {
    return [
      'C:\\Windows\\System32',
      'C:\\Windows',
      'C:\\Windows\\System32\\WindowsPowerShell\\v1.0',
    ];
  }
  return ['/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin'];
}

export function makeCommandOptions(cwd?: string) {
  const base = { encoding: 'utf-8' as const };
  if (!cwd) return base;

  const portablePath = [
    joinRuntimePath(cwd, 'node'),
    joinRuntimePath(cwd, 'SystemData', '.core', 'node'),
    joinRuntimePath(cwd, 'node_modules', '.bin'),
    joinRuntimePath(cwd, 'SystemData', '.core', 'node_modules', '.bin'),
    ...systemPathEntries(cwd),
  ].join(runtimePathDelimiter(cwd));
  const dataDir = joinRuntimePath(cwd, 'data');
  const stateDir = joinRuntimePath(dataDir, '.openclaw');
  const configPath = joinRuntimePath(stateDir, 'openclaw.json');
  return {
    ...base,
    cwd,
    env: {
      PATH: portablePath,
      Path: portablePath,
      OPENCLAW_STATE_DIR: stateDir,
      OPENCLAW_CONFIG_PATH: configPath,
      OPENCLAW_HOME: dataDir,
      OPENCLAW_GATEWAY_PORT: '18790',
      NO_COLOR: '1',
    },
  };
}

export async function resolvePortableBasePath(settings: PreviewSettings): Promise<string | undefined> {
  const response = await requestBridgeData<any>(settings, '/api/system/info').catch(() => null);
  return response?.data?.base_path || undefined;
}
