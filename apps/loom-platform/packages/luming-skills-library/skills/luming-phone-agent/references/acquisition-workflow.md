# Acquisition Workflow

Use this internal mode for customer acquisition. LOOM owns task state, phones are workers, and Feishu Bitable is an optional lead ledger. Never assume a CLI route, device, table ID, account, or credential.

## Safe Loop

1. Resolve the installed command catalog, then inspect `doctor --json`, `commands --json`, `acquisition status --json`, `integration feishu doctor --json`, and `integration feishu status --json` when available.
2. Normalize platform, topic, target customer, keywords, device, SOP, and Feishu state. Use only public or user-authorized visible content.
3. Start with acquisition dry-run dispatch:

```text
python -B "<LOOM_CLI>" acquisition agent-run --json --dry-run --platform "<platform>" --topic "<topic>" --target "<target>"
```

4. Dispatch the returned phone task only when the user wants phone execution. The phone may read public visible content, summarize evidence, capture screenshots, prepare content, and execute task-authorized publishing, commenting, or private messaging after outbound preflight.
5. Require and ingest `loom.acquisition.agent_result.v1`:

```text
python -B "<LOOM_CLI>" acquisition agent-result --json --agent-result-json "<JSON>"
```

6. Verify local leads, drafts, logs, and Feishu sync status. Preserve task IDs, selected-device evidence, visible proof, and the next human action.

```json
{
  "schema": "loom.acquisition.agent_result.v1",
  "taskId": "agent_task_xxx",
  "deviceId": "phone-1",
  "platform": "xiaohongshu",
  "action": "lead_discovery",
  "status": "outbound_completed",
  "leads": [{"platform": "xiaohongshu", "summary": "public demand signal", "evidence": "short public evidence", "draftBody": "manual-review follow-up draft"}],
  "drafts": [{"channel": "comment", "body": "task-authorized outbound content", "requiresHumanReview": false}],
  "actions": [{"channel": "comment", "targetRef": "public-post-001", "contentHash": "sha256:...", "status": "sent", "evidenceRef": "screen-after-001"}],
  "logs": [{"level": "info", "message": "read public comments only"}]
}
```

## Local Persistence And Feishu

Before writing, check `integration feishu status --json`. Under the weak safety gate, a task that names Bitable bind/create, lead/content sync, or retry authorizes those non-security actions without per-action confirmation. If Feishu is unbound or a write fails, keep every lead locally with `pending/sync_failed` state, retain evidence and drafts, and offer login, bind, or retry. Never drop local leads after a failed Feishu write, print tokens, invent table IDs, or require account secrets in prompts or files.

## Template Memory

After repeatable success, save local template memory and let LOOM queue cloud upload:

```text
python -B "<LOOM_CLI>" acquisition template save --json --permission control --name "<name>" --industry "<industry>" --platform "<platform>"
python -B "<LOOM_CLI>" acquisition template list --json
python -B "<LOOM_CLI>" acquisition template retry --json --permission control
```

Never put customer secrets, tokens, real account passwords, or private lead data into templates. Recommend reuse only after stable repeated success, complete evidence, clear human gates, and known failure rollback.

## Automatic Outbound And Privacy

Set `outboundMode: auto` when the normalized task includes publish, comment, and private message channels. Treat the channels named by that task as task-level authorization and execute without per-action confirmation. Before dispatch, freeze the approved account/session, channel, target scope, content policy, frequency cap, duplicate prevention key, audit log, and stop conditions. Record before/after evidence for each action and ingest the final action status.

Allow bounded automatic publishing, commenting, private messaging, following, and add-contact actions within that policy. Stop on a target mismatch, duplicate, platform warning, rate limit, content-policy failure, or unavailable audit logging. Do not use scraped private data, perform untargeted unsolicited bulk outreach, bypass platform risk controls, scrape hidden APIs, store credentials, store private contact details, or retain unneeded personal data.
