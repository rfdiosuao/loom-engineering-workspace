---
name: openclaw-pdf-ocr
description: Extract, summarize, and analyze PDFs, screenshots, scanned documents, invoices, contracts, forms, tables, and OCR text. Use for PDF reading, document QA, key field extraction, table extraction, and scanned office materials.
---

# OpenClaw PDF And OCR Reader

Use this skill when the user asks to read, extract, summarize, compare, or analyze PDFs, screenshots, scanned files, invoices, forms, or image-based documents.

## Workflow

1. Determine the document type: PDF, image, screenshot, invoice, contract, receipt, form, table, or mixed.
2. Prefer structured extraction over free-form guessing:
   - preserve page numbers;
   - preserve headings;
   - preserve tables as Markdown tables when possible;
   - keep key fields explicit.
3. For scanned or low-quality images, report OCR uncertainty and avoid fabricating unreadable text.
4. For invoices, receipts, and contracts, extract key fields first, then summarize.
5. For long PDFs, summarize by section and page range before producing a final executive summary.

## Output Patterns

### Key Field Extraction

```markdown
| Field | Value | Evidence |
|---|---|---|
| Document type | ... | page ... |
| Date | ... | page ... |
| Amount | ... | page ... |
| Counterparty | ... | page ... |
```

### PDF Summary

```markdown
# Document Summary

## Executive Summary
...

## Key Points By Section
- ...

## Tables / Numbers
- ...

## Questions Or Risks
- ...
```

## Safety

For legal, finance, medical, or compliance documents, provide risk flags and evidence, not professional legal/financial conclusions.
