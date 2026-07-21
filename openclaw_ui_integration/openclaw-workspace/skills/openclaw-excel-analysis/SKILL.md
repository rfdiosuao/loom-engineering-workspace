---
name: openclaw-excel-analysis
description: Analyze spreadsheets, CSV files, KPI tables, expense sheets, sales reports, budgets, and operations data. Use for Excel cleanup, formulas, pivot-style summaries, charts, anomalies, and management reports.
---

# OpenClaw Excel Analysis

Use this skill when the user asks to analyze Excel, CSV, expenses, sales data, KPI data, budgets, operations sheets, or tabular business data.

## Workflow

1. Inspect columns, row count, sheet names, missing values, and obvious data types.
2. Confirm the business question before producing charts or formulas.
3. Clean data conservatively:
   - do not delete rows unless the user asks;
   - keep an audit trail of assumptions;
   - normalize dates, amounts, categories, and duplicate rows.
4. Produce spreadsheet-ready outputs:
   - formulas;
   - calculated columns;
   - pivot-style summaries;
   - anomaly list;
   - management summary.
5. When writing or modifying files, keep the original file unchanged unless the user explicitly asks to overwrite it.

## Analysis Template

```markdown
# Spreadsheet Analysis

## Data Overview
- Rows:
- Columns:
- Sheets:

## Findings
- ...

## Anomalies
| Row/Key | Issue | Evidence | Suggested action |
|---|---|---|---|

## Recommended Formulas
- ...

## Management Summary
...
```

## Chart Guidance

Use charts only when they clarify a decision: trend line for time series, bar chart for category comparison, scatter plot for relationship, table for exact values.
