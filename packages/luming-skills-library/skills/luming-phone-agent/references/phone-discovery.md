# Phone Discovery

Discover after the real command catalog is available and before asking the user to restate work. For each phone record `deviceId`, online state, busy state, controllability, current App, page summary, lock/permission prompts, and whether it suits single-device work, matrix work, or isolation.

If there are no healthy controllable phones, return a concrete connection blocker and `resumeFrom: PHONE_DISCOVERY`. If exactly one is healthy, auto-select it. If several are healthy and the normalized request did not already choose a device count or matrix operation, present the discovery summary and ask for one single-device or matrix decision. If the original request already specifies a matrix, retain that intent.

After discovery, ask for the task. If the user supplied an initial task, confirm its normalized goal, App, expected result, device scope, and safe boundary rather than asking them to repeat it. Keep the selected device ID in every screenshot, screen read, fingerprint, task ID, and evidence record.
