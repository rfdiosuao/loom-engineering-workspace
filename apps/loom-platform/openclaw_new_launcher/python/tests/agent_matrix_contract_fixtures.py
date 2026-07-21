from __future__ import annotations


REALTIME_EVENT = {
    "schema": "loom.realtime.event.v1",
    "eventId": "evt_001",
    "seq": 128,
    "timestamp": "2026-07-15T14:30:00+08:00",
    "topic": "matrix.assignment",
    "entityId": "dt_001",
    "type": "matrix.assignment.started",
    "data": {
        "campaignId": "cmp_001",
        "assignmentId": "asg_001",
        "deviceTaskId": "dt_001",
        "deviceId": "LUMI-P01",
        "jobId": "job_001",
        "attempt": 1,
        "status": "running",
    },
}

MATRIX_DISPATCH = {
    "schema": "loom.matrix.dispatch.v2",
    "campaignId": "cmp_001",
    "concurrency": 2,
    "mode": "safe",
    "profile": "standard",
    "deviceAssignments": [
        {
            "assignmentId": "asg_001",
            "deviceId": "LUMI-P01",
            "prompt": "Read the current screen and return a structured result.",
            "templateId": "screen_read_v1",
            "input": {"candidateId": "candidate_001"},
            "timeoutSec": 180,
            "retryBudget": 1,
        }
    ],
}

MATRIX_CAMPAIGN = {
    "schema": "loom.matrix.campaign.v2",
    "campaignId": "cmp_001",
    "status": "queued",
    "concurrency": 2,
    "counts": {
        "total": 1,
        "queued": 1,
        "running": 0,
        "completed": 0,
        "failed": 0,
        "needsHuman": 0,
    },
    "deviceTasks": [
        {
            "assignmentId": "asg_001",
            "deviceTaskId": "dt_001",
            "deviceId": "LUMI-P01",
            "jobId": None,
            "status": "queued",
            "attempt": 0,
        }
    ],
}

MATRIX_SCREEN = {
    "schema": "loom.matrix.screen.v1",
    "deviceId": "LUMI-P01",
    "capturedAt": "2026-07-15T14:30:00+08:00",
    "screenHash": "sha256:fixture",
    "mime": "image/jpeg",
    "width": 1080,
    "height": 2400,
    "image": "ZmFrZQ==",
    "notModified": False,
}

DEVICE_LEASE = {
    "schema": "loom.matrix.device_lease.v1",
    "leaseId": "lease_001",
    "deviceId": "LUMI-P01",
    "holderType": "agent",
    "holderId": "run_001",
    "mode": "control",
    "expiresAt": "2026-07-15T14:30:30+08:00",
}

AGENT_SESSION = {
    "schema": "loom.agent.session.v1",
    "sessionId": "session_001",
    "title": "Read three phones",
    "status": "active",
    "runtimeProfileId": "default",
    "createdAt": "2026-07-15T14:30:00+08:00",
    "updatedAt": "2026-07-15T14:30:00+08:00",
    "activeRunId": "run_001",
}

AGENT_MESSAGE = {
    "schema": "loom.agent.message.v1",
    "messageId": "message_001",
    "sessionId": "session_001",
    "role": "user",
    "status": "completed",
    "blocks": [{"type": "text", "data": {"text": "Read three phones."}}],
    "createdAt": "2026-07-15T14:30:00+08:00",
    "completedAt": "2026-07-15T14:30:00+08:00",
}

AGENT_RUN = {
    "schema": "loom.agent.run.v1",
    "runId": "run_001",
    "sessionId": "session_001",
    "status": "running",
    "campaignIds": ["cmp_001"],
    "startedAt": "2026-07-15T14:30:00+08:00",
}

AGENT_APPROVAL = {
    "schema": "loom.agent.approval.v1",
    "approvalId": "approval_001",
    "sessionId": "session_001",
    "runId": "run_001",
    "toolCallId": "tool_call_001",
    "capability": "loom.phone.publish",
    "inputHash": "sha256:0000000000000000000000000000000000000000000000000000000000000000",
    "actionSummary": "Publish one post",
    "targets": {"deviceIds": ["LUMI-P01"]},
    "inputSummary": {"platform": "douyin"},
    "risk": "outbound",
    "riskReason": "External write requires approval",
    "status": "pending",
    "requestedAt": "2026-07-15T14:30:00+08:00",
    "expiresAt": "2026-07-15T14:35:00+08:00",
}

CONTRACT_FIXTURES = (
    REALTIME_EVENT,
    MATRIX_DISPATCH,
    MATRIX_CAMPAIGN,
    MATRIX_SCREEN,
    DEVICE_LEASE,
    AGENT_SESSION,
    AGENT_MESSAGE,
    AGENT_RUN,
    AGENT_APPROVAL,
)
