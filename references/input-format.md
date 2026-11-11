# Input format and validation reference

## 1. Supported source workbooks

The generator expects Chinese library system exports titled
`文献分类借还统计1` or an equivalent sheet with the following layout:

| Row | Content |
|---|---|
| 1 | `文献分类借还统计` title |
| 2 | Statistics conditions, including `借阅时间：YYYY-MM` and `院系：...` |
| 3–4 | Blank spacer rows |
| 5 | Header: `序号`, `分类名称`, `分类号`, date fields, `合计`, `借阅比率` |
| 6… | One borrowing category per row |
| End | Optional `分类合计`, `馆藏借阅合计`, and `借阅比率` rows |

The implementation detects the header dynamically, so the physical header row
does not have to be row 5.

### Date columns

Accepted names match:

```text
1日(次数), 2日(次数), ..., 31日(次数)
```

Both ASCII and full-width parentheses are accepted. The exporter may omit date
columns that are entirely empty; missing dates are filled with zero.

### Category rules

- Read `分类名称` from the source workbook.
- Read `分类号` from the source workbook when present.
- Use the source row order for the right-hand classification nodes.
- Preserve punctuation and wording; do not translate category names.
- Treat any name containing `合计` and the literal `借阅比率` as a summary row,
  not a classification.
- Require the same category tuple and code tuple in every college workbook.

## 2. Aggregation

For each college workbook:

1. Parse the category × day matrix.
2. Sum each category row across all day fields.
3. Sum every category to obtain the college total.
4. Build one row of the college × category matrix.

The chart sorts colleges by displayed total descending. Categories retain their
source order on the right. Node totals are calculated from exactly the links
that are drawn, so the Sankey remains conservative when a threshold hides small
links.

## 3. Validation

The script performs these checks:

1. Locate a row containing both `序号` and `分类名称`.
2. Verify necessary columns and non-empty category rows.
3. Verify unique, valid day indices from 1 to 31.
4. Verify all counts are non-negative integers.
5. If the sheet has a `合计` column, compare every category's day sum with it.
6. Require identical category names/order/codes across all workbooks.
7. Require identical borrowing months across all workbooks.
8. Reject duplicate college names.
9. Sum all college category totals.
10. If a university reference workbook is supplied, compare each category total
    and the grand total with it.

Stop on the first validation error. Do not suppress inconsistencies or manually
alter the CSV to force totals to match.

## 4. Empty export recovery

A workbook with no date fields and no positive counts is treated as an empty
export.

Recovery is allowed only when all conditions hold:

- Exactly one college workbook is empty.
- A university-wide reference workbook is supplied.
- The reference categories match the college categories.
- The reference minus the sum of all non-empty colleges has no negative cell.

Recovery formula:

```text
recovered_college = reference_category_totals - sum(other_college_category_totals)
```

This recovers the college's category totals deterministically. The original
empty file is never modified. The chart footer and CSV mark the recovered
college, and the CLI prints its name and recovered count.

If more than one college is empty, stop. Multiple empty files cannot be
attributed safely without additional dimensions.

## 5. Reference workbook

The university-wide workbook uses the same category template and monthly export
format but omits `院系`. It supplies:

- A per-category total vector used for integrity checking and optional recovery.
- `馆藏借阅合计`, if present, for a disclosure note.

The difference between `馆藏借阅合计` and the classified detail total is reported
but never allocated. It may represent unclassified records.

## 6. Output schema

The CSV contains every college × category cell, including zeros:

| Column | Meaning |
|---|---|
| `月份` | Month parsed from the workbook metadata |
| `学院` | Exact value after `院系：` |
| `分类号` | Classification code from the source |
| `中图法分类` | Full source category name |
| `借阅次数` | Aggregated count |
| `学院借阅总量` | Total for the college |
| `数据状态` | `源文件直读` or `按全校汇总差额恢复` |

Output filenames default to the detected month. Use `--output-prefix` to
override the stem.

## 7. Privacy

Never commit real library workbooks, generated flow CSVs, or charts containing
institution-specific data to a public repository. Use synthetic data for tests
and documentation examples.
