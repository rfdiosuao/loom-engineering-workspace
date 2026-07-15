# Security Policy

LOOM engineering repositories are private and may contain commercially sensitive source. Repository privacy is not a substitute for secret hygiene.

## Never Commit

- API keys, access tokens, passwords, cookies, QR login material, or private customer data
- Android signing keys, keystores, certificates, private keys, or local Gradle configuration
- license databases, installation identifiers, runtime state, or captured device content
- APK/AAB packages, logs, screenshots, recordings, or generated media

## Reporting

Stop the push, remove the material from the index, rotate the exposed credential, and document the incident in a private security Issue. Do not merely delete a secret in a later commit because Git history retains the earlier content.
