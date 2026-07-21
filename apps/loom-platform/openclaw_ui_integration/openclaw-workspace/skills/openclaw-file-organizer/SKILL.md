---
name: openclaw-file-organizer
description: Organize desktop files, downloads, project folders, document archives, screenshots, reports, invoices, and office materials. Use for safe file classification, naming, folder plans, duplicate checks, and cleanup proposals.
---

# OpenClaw File Organizer

Use this skill when the user asks to organize files, clean the desktop, sort downloads, classify office documents, rename files, archive project materials, or find duplicates.

## Safety Rules

- Never delete files unless the user explicitly asks and the exact target paths are verified.
- Prefer a proposed folder plan before moving many files.
- Preserve original filenames unless the user asks to rename.
- For duplicates, compare size and hash before calling files duplicates.
- Keep moves inside the intended workspace or user-approved target directory.

## Workflow

1. Inventory files with names, paths, size, modified time, and extension.
2. Group by project, document type, date, and sensitivity.
3. Propose a folder plan.
4. Ask for confirmation before bulk moves or deletes.
5. After changes, report moved files and unresolved items.

## Folder Plan Template

```markdown
# File Organization Plan

## Proposed Folders
- 01-Reports
- 02-Spreadsheets
- 03-Contracts
- 04-Invoices
- 05-Screenshots
- 99-Review

## Move Plan
| File | Destination | Reason |
|---|---|---|

## Needs Review
- ...
```

## Naming Pattern

Use `YYYY-MM-DD-topic-owner.ext` for dated office documents when the user wants renaming.
