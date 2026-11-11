---
name: book-borrowing-sankey
description: Create, validate, and export publication-quality Chinese library book-borrowing Sankey diagrams from per-college “文献分类借还统计” Excel workbooks. This skill should be used for requests mentioning 图书借阅桑基图, 学院借阅流向, 图书馆月度报表, college-to-classification flow charts, or regeneration of an existing book-borrowing Sankey with exact totals, Chinese labels, PNG, SVG, and CSV outputs.
agent_created: true
---

# Book Borrowing Sankey

## Purpose

Generate a single-panel, white-background Sankey chart from one monthly Chinese
library workbook per college. The left side contains colleges sorted by total
borrowings, the right side contains the source workbook's Zhongtu Fa
classification names, and stream width represents borrowing counts.

The script performs deterministic parsing, validation, optional recovery of one
empty college export, chart rendering, and CSV export. Do not redraw the chart
from visual estimation when the bundled script can handle the task.

## When to use

Use this skill when the user asks to:

- Build a 桑基图 from multiple college-level library Excel files.
- Regenerate a monthly 图书借阅桑基图 from a previous month's configuration.
- Validate college totals against a university-wide library export.
- Export the underlying college × classification flow table as CSV.
- Recover one college workbook that exported as an empty table.

Do not use this skill for unrelated Sankey diagrams, PDF extraction, or general
spreadsheet editing.

## Input contract

Require one directory containing one `.xlsx` workbook per college. Each workbook
should use the library's “文献分类借还统计” export with these features:

- A metadata preamble containing `统计方式：分类借阅统计` and `院系：<college>`.
- A header row containing at least `序号`, `分类名称`, and `分类号`.
- Date fields named like `1日(次数)` through `31日(次数)`; missing all-zero date
  columns are tolerated.
- One row per Zhongtu Fa category.
- Optional `合计` and `借阅比率` columns and summary rows.

Read `references/input-format.md` for exact parsing, validation, and recovery
rules before changing data-handling behavior.

## Workflow

1. Locate the input workbook directory and, if available, the university-wide
   monthly total workbook.
2. Inspect a small sample of one workbook with pandas to confirm the header and
   metadata are recognizable. Do not modify the original files.
3. Check the Python environment for `pandas`, `openpyxl`, and `matplotlib`.
   Install from the bundled `requirements.txt` if any are missing.
4. Run the generator with explicit input, reference, and output directories.
5. Read the command output and confirm college count, category count, non-zero
   flow count, total borrowings, and any recovered empty workbook.
6. Inspect the PNG for clipped labels or overlaps. Prefer the SVG when users
   need to zoom without quality loss.
7. Present the PNG first, then the SVG, CSV, and generated command information.

## Run the generator

Use the active Python interpreter and the absolute path to this skill directory.

```bash
python "<skill-dir>/scripts/generate_sankey.py" \
  --input "<college-workbook-directory>" \
  --reference "<university-total-workbook.xlsx>" \
  --output-dir "<output-directory>"
```

On Windows PowerShell, the same arguments work with the call operator:

```powershell
& python "<skill-dir>\scripts\generate_sankey.py" `
  --input "<college-workbook-directory>" `
  --reference "<university-total-workbook.xlsx>" `
  --output-dir "<output-directory>"
```

Useful options:

- `--output-prefix "<filename-stem>"`: set a custom output filename.
- `--title-suffix "<suffix>"`: change the chart title suffix.
- `--min-college 1`: hide colleges below a total threshold.
- `--min-link 1`: hide college–classification links below a value threshold.
- `--dpi 200`: set PNG resolution.
- `--show`: also open a Matplotlib window.

Omit `--reference` only when every college workbook contains data. A single empty
or unreadable workbook requires a reference total for deterministic recovery.

## Outputs

Generate these files in the chosen output directory:

- `<prefix>.png`: high-resolution chart.
- `<prefix>.svg`: editable vector chart.
- `<prefix>_流向明细.csv`: complete college × classification matrix, including
  zero cells and the `数据状态` column.

Use the PNG for quick viewing and the SVG for print or detailed inspection.

## Validation rules

- Preserve classification names and codes exactly as written in the source
  workbooks. Never silently normalize or rename categories.
- Require identical category names, category order, and category codes across
  all college files.
- Require a consistent borrowing month across workbooks.
- Reject negative, fractional, or non-numeric borrowing counts.
- Compare row-level date sums with the `合计` column when present.
- Compare the final college total with the university-wide reference when one is
  supplied.
- Recover an empty workbook only when exactly one empty college exists and the
  university total minus all other college matrices is non-negative.
- Disclose every recovered workbook and recovered amount in the chart footer,
  CSV `数据状态`, and final response.
- Never allocate missing or unclassified counts across colleges or categories.

## Reporting

After generation, state:

- Number of colleges and non-zero classifications.
- Number of non-zero college–classification flows.
- Total borrowings and the reference-total validation result.
- Any recovered empty workbook and recovered count.
- Any difference between the source `馆藏借阅合计` and classified detail total.
- Paths to PNG, SVG, CSV, and the command used.

Do not describe a zero category as missing. State that it has zero flow and was
not rendered.

## Troubleshooting

- If the header is not found, inspect row 1–10 for `序号` and `分类名称`.
- If all date fields are absent and the college total is zero, obtain the
  university-wide total workbook for recovery or request a fresh export.
- If multiple college workbooks are empty, stop and request fresh exports; the
  per-college split cannot be inferred reliably.
- If Chinese labels render as boxes, install Microsoft YaHei, SimHei, Noto Sans
  CJK SC, or Source Han Sans SC and rerun.
- If category/date fields fail validation, do not patch numbers manually; fix
  the source export and rerun.

## Resources

- `scripts/generate_sankey.py`: deterministic parser, validator, renderer, and
  CLI.
- `references/input-format.md`: workbook schema, validation order, and recovery
  algorithm.
- `requirements.txt`: Python dependencies.
- `scripts/smoke_test.py`: synthetic-data smoke test that verifies the installed
  skill without using private library data.
