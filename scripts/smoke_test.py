#!/usr/bin/env python3
"""Run a self-contained smoke test with synthetic library workbooks."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import pandas as pd
from openpyxl import Workbook


CATEGORIES = [
    ("A", "马克思主义、列宁主义、毛泽东思想、邓小平理论"),
    ("B", "哲学、宗教"),
    ("C", "社会科学总论"),
]
DAYS = 3


def write_workbook(
    path: Path,
    college: str | None,
    values: list[list[int]],
) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "文献分类借还统计1"
    ws.append(["文献分类借还统计"])
    metadata = (
        "已选条件：统计方式：分类借阅统计 统计维度：按借阅次数 "
        "借阅时间：2026-10 分类模板：中图法分类模板 "
        "统计借还为0的数据：否 限定入藏日期：无"
    )
    if college:
        metadata += f" 院系：{college}"
    ws.append([metadata])
    ws.append([])
    ws.append([])

    if college and not any(any(row) for row in values):
        ws.append(["序号", "分类名称", "分类号", "借阅比率"])
        for index, (code, name) in enumerate(CATEGORIES, start=1):
            ws.append([index, name, code, "0.00%"])
    else:
        ws.append(
            ["序号", "分类名称", "分类号"]
            + [f"{day}日(次数)" for day in range(1, DAYS + 1)]
            + ["合计", "借阅比率"]
        )
        for index, (code, name) in enumerate(CATEGORIES, start=1):
            row = values[index - 1]
            ws.append([index, name, code] + row + [sum(row), ""])
        column_totals = [
            sum(values[row][col] for row in range(len(CATEGORIES)))
            for col in range(DAYS)
        ]
        ws.append([len(CATEGORIES) + 1, "分类合计", ""] + column_totals + [sum(column_totals), ""])
    wb.save(path)


def main() -> int:
    script = Path(__file__).with_name("generate_sankey.py")
    with tempfile.TemporaryDirectory(prefix="sankey-skill-test-") as temp:
        root = Path(temp)
        data_dir = root / "data"
        data_dir.mkdir()
        out_dir = root / "output"

        fake_a = [[6, 2, 0], [0, 0, 5], [0, 0, 0]]
        fake_b = [[1, 0, 0], [0, 2, 0], [0, 0, 4]]
        recovered = [[3, 0, 0], [0, 0, 0], [0, 1, 0]]
        reference = [
            [fake_a[row][col] + fake_b[row][col] + recovered[row][col]
             for col in range(DAYS)]
            for row in range(len(CATEGORIES))
        ]

        write_workbook(data_dir / "college_a.xlsx", "示例学院甲", fake_a)
        write_workbook(data_dir / "college_b.xlsx", "示例学院乙", fake_b)
        write_workbook(
            data_dir / "college_c.xlsx",
            "示例学院丙",
            [[0] * DAYS for _ in CATEGORIES],
        )
        reference_file = root / "reference.xlsx"
        write_workbook(reference_file, None, reference)

        result = subprocess.run(
            [
                sys.executable,
                str(script),
                "--input",
                str(data_dir),
                "--reference",
                str(reference_file),
                "--output-dir",
                str(out_dir),
                "--output-prefix",
                "smoke-test",
                "--dpi",
                "120",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        print(result.stdout.strip())

        png = out_dir / "smoke-test.png"
        svg = out_dir / "smoke-test.svg"
        csv = out_dir / "smoke-test_流向明细.csv"
        for path in (png, svg, csv):
            assert path.exists() and path.stat().st_size > 0, path

        frame = pd.read_csv(csv)
        assert len(frame) == 3 * len(CATEGORIES)
        assert frame["学院"].nunique() == 3
        assert int(frame["借阅次数"].sum()) == sum(map(sum, reference))
        recovered_rows = frame[frame["数据状态"] == "按全校汇总差额恢复"]
        assert recovered_rows["学院"].unique().tolist() == ["示例学院丙"]
        assert int(recovered_rows["借阅次数"].sum()) == sum(map(sum, recovered))
        print("Smoke test passed: PNG, SVG, CSV, totals, and empty-workbook recovery.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
