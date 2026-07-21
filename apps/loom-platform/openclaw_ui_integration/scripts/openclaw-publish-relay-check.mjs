#!/usr/bin/env node

const DEFAULT_CHANNEL_ID = `relay-check-${Date.now()}`;
const DEFAULT_CLIENT_ID = 'relay-check-client';
const DEFAULT_WAIT_MS = 0;
const DEFAULT_LEASE_MS = 30_000;

function usage() {
  return `
OpenClaw publish relay public check

Usage:
  node scripts/openclaw-publish-relay-check.mjs --base-url https://relay.example.com --relay-token ...
  node scripts/openclaw-publish-relay-check.mjs --relay-url https://relay.example.com/api/lumi/publish/packet --relay-token ...

Options:
  --base-url <url>           Relay service base URL
  --relay-url <url>          Relay packet endpoint URL
  --relay-token <token>      Shared relay token. Env: OPENCLAW_PUBLISH_RELAY_TOKEN
  --channel-id <id>          Smoke channel. Default: relay-check-<timestamp>
  --channel <id>             Alias for --channel-id
  --client-id <id>           Poll client id. Default: ${DEFAULT_CLIENT_ID}
  --allow-open               Do not require unauthenticated packet requests to fail
  --json                     Print machine-readable JSON
  -h, --help                 Show help
`.trim();
}

function normalizeString(value) {
  return String(value == null ? '' : value).trim();
}

function parseArgs(argv) {
  const args = {
    baseUrl: '',
    relayUrl: '',
    relayToken: normalizeString(process.env.OPENCLAW_PUBLISH_RELAY_TOKEN),
    channelId: DEFAULT_CHANNEL_ID,
    clientId: DEFAULT_CLIENT_ID,
    allowOpen: false,
    json: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    const next = () => {
      const value = argv[i + 1];
      if (!value || value.startsWith('--')) throw new Error(`Missing value for ${arg}`);
      i += 1;
      return value;
    };

    switch (arg) {
      case '-h':
      case '--help':
        args.help = true;
        break;
      case '--base-url':
        args.baseUrl = next();
        break;
      case '--relay-url':
        args.relayUrl = next();
        break;
      case '--relay-token':
        args.relayToken = next();
        break;
      case '--channel-id':
      case '--channel':
        args.channelId = next();
        break;
      case '--client-id':
        args.clientId = next();
        break;
      case '--allow-open':
        args.allowOpen = true;
        break;
      case '--json':
        args.json = true;
        break;
      default:
        throw new Error(`Unknown option: ${arg}`);
    }
  }

  args.baseUrl = normalizeBaseUrl(args.baseUrl);
  args.relayUrl = normalizeString(args.relayUrl);
  args.relayToken = normalizeString(args.relayToken);
  args.channelId = normalizeString(args.channelId) || DEFAULT_CHANNEL_ID;
  args.clientId = normalizeString(args.clientId) || DEFAULT_CLIENT_ID;

  if (!args.baseUrl && !args.relayUrl) {
    throw new Error('Missing --base-url or --relay-url');
  }
  if (!args.relayUrl) {
    args.relayUrl = `${args.baseUrl}/api/lumi/publish/packet`;
  }
  if (!args.baseUrl) {
    args.baseUrl = relayBaseFromPacketUrl(args.relayUrl);
  }
  return args;
}

function normalizeBaseUrl(value) {
  return normalizeString(value).replace(/\/+$/, '');
}

function relayBaseFromPacketUrl(relayUrl) {
  const url = new URL(relayUrl);
  url.pathname = '';
  url.search = '';
  url.hash = '';
  return url.toString().replace(/\/+$/, '');
}

function endpoint(baseUrl, pathname) {
  return `${normalizeBaseUrl(baseUrl)}${pathname}`;
}

function relayAuthHeaders(relayToken, headers = {}) {
  if (!relayToken) return headers;
  return {
    ...headers,
    Authorization: `Bearer ${relayToken}`,
    'X-OpenClaw-Relay-Token': relayToken,
  };
}

async function readJsonResponse(response) {
  const text = await response.text();
  if (!text.trim()) return null;
  try {
    return JSON.parse(text);
  } catch {
    return { raw: text };
  }
}

async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  const body = await readJsonResponse(response);
  return { status: response.status, body };
}

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

async function runCheck(args) {
  const health = await requestJson(endpoint(args.baseUrl, '/api/lumi/relay/health'), {
    headers: relayAuthHeaders(args.relayToken, { Accept: 'application/json' }),
  });
  assert(health.status === 200, `health expected 200, got ${health.status}`);
  assert(health.body?.data?.configured !== false, 'relay token is not configured on server');

  const packet = {
    schema: 'openclaw.publish.packet.v1',
    channelId: args.channelId,
    platformId: 'custom',
    platformLabel: 'Relay Check',
    title: 'relay public check',
    body: 'relay public check',
    hashtags: [],
    media: [],
    createdAt: new Date().toISOString(),
  };

  let unauthPacketStatus = null;
  if (args.relayToken && !args.allowOpen) {
    const unauth = await requestJson(args.relayUrl, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(packet),
    });
    unauthPacketStatus = unauth.status;
    assert(unauth.status === 401, `unauthenticated packet expected 401, got ${unauth.status}`);
  }

  const ingest = await requestJson(args.relayUrl, {
    method: 'POST',
    headers: relayAuthHeaders(args.relayToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify(packet),
  });
  assert(ingest.status === 202, `packet ingest expected 202, got ${ingest.status}`);
  const packetId = ingest.body?.data?.packetId;
  assert(packetId, 'relay did not return packetId');

  const pollUrl = new URL(endpoint(args.baseUrl, '/api/lumi/relay/poll'));
  pollUrl.searchParams.set('channelId', args.channelId);
  pollUrl.searchParams.set('clientId', args.clientId);
  pollUrl.searchParams.set('waitMs', String(DEFAULT_WAIT_MS));
  pollUrl.searchParams.set('leaseMs', String(DEFAULT_LEASE_MS));
  const poll = await requestJson(pollUrl.toString(), {
    headers: relayAuthHeaders(args.relayToken, { Accept: 'application/json' }),
  });
  assert(poll.status === 200, `poll expected 200, got ${poll.status}`);
  assert(poll.body?.data?.packetId === packetId, `poll returned unexpected packet id: ${poll.body?.data?.packetId}`);

  const complete = await requestJson(endpoint(args.baseUrl, '/api/lumi/relay/complete'), {
    method: 'POST',
    headers: relayAuthHeaders(args.relayToken, { 'Content-Type': 'application/json' }),
    body: JSON.stringify({
      packetId,
      leaseId: poll.body.data.leaseId,
      clientId: args.clientId,
      success: true,
      result: { ok: true, checkedAt: new Date().toISOString() },
    }),
  });
  assert(complete.status === 200, `complete expected 200, got ${complete.status}`);

  const statusUrl = new URL(endpoint(args.baseUrl, '/api/lumi/relay/status'));
  statusUrl.searchParams.set('id', packetId);
  const status = await requestJson(statusUrl.toString(), {
    headers: relayAuthHeaders(args.relayToken, { Accept: 'application/json' }),
  });
  assert(status.status === 200, `status expected 200, got ${status.status}`);
  assert(status.body?.data?.status === 'done', `final status expected done, got ${status.body?.data?.status}`);

  return {
    ok: true,
    baseUrl: args.baseUrl,
    relayUrl: args.relayUrl,
    channelId: args.channelId,
    packetId,
    unauthPacketStatus,
    finalStatus: status.body.data.status,
    health: health.body?.data || health.body,
  };
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    console.log(usage());
    return;
  }
  const result = await runCheck(args);
  if (args.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    console.log(`relay ok: ${result.baseUrl}`);
    console.log(`packet: ${result.packetId}`);
    console.log(`status: ${result.finalStatus}`);
    if (result.unauthPacketStatus != null) {
      console.log(`unauthenticated packet status: ${result.unauthPacketStatus}`);
    }
  }
}

main().catch((error) => {
  console.error(error?.stack || error?.message || error);
  process.exit(1);
});
