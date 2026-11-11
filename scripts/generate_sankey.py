#!/usr/bin/env python3
"""Generate a publication-quality college-to-classification Sankey chart.

The input is a directory of monthly Chinese library workbooks exported with
the "文献分类借还统计" template, one workbook per college. The script validates
the exports, aggregates college-by-category flows, optionally recovers a single
empty export from a university-wide total workbook, and writes PNG, SVG, and CSV.
"""

from __future__ import annotations

import argparse
import re
import sys
import warnings
from dataclasses import dataclass
from pathlib import Path

import matplotlib.font_manager as fm
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.path import Path as MplPath
from matplotlib.patheffects import withStroke


# ============================================================
# 1. 可视配置
# ============================================================

DEFAULT_TITLE_SUFFIX = "各学院图书借阅桑基图"

warnings.filterwarnings(
    "ignore",
    message="Workbook contains no default style.*",
    category=UserWarning,
)


SOURCE_COLORS = [
    "#2F6CB3", "#EE7C22", "#34BF7F", "#8754B0", "#E74E4E",
    "#32B7A4", "#EDA321", "#2E84C3", "#694DAF", "#46B46E",
    "#D95E7E", "#E16C32", "#647D43", "#263D56", "#9AA0A6",
    "#7D55C7", "#F27E9F", "#2CB8A6", "#D65A4C", "#5A7FA8",
    "#373B41", "#A15F9E", "#E9C35A", "#C84C2E", "#6AA3D1",
    "#64778C", "#ABB1B7", "#B597DB", "#82CFC8", "#DDBB76",
]

CATEGORY_COLORS = [
    "#B43838", "#2F6CB3", "#34AE76", "#7E4FAF", "#DC6B1F",
    "#2AAE9A", "#E59823", "#006B46", "#B33B38", "#6F408F",
    "#2F6CB3", "#8B939A", "#34AE76", "#B43838", "#2F6CB3",
    "#34AE76", "#8B939A", "#B43838", "#2F6CB3", "#8B939A",
    "#34AE76", "#7E4FAF",
]

TEXT_MAIN = "#22272B"
TEXT_MUTED = "#66727C"


# ============================================================
# 2. 数据结构
# ============================================================

@dataclass(frozen=True)
class Category:
    row_index: int
    code: str
    name: str


@dataclass
class CollegeData:
    name: str
    path: Path
    category_totals: np.ndarray
    daily_total: int
    source: str


@dataclass
class ReferenceTotals:
    categories: tuple[str, ...]
    category_totals: np.ndarray
    detail_total: int
    collection_total: int | None


@dataclass
class SourceData:
    colleges: list[CollegeData]
    categories: list[Category]
    matrix: np.ndarray                  # 行：学院；列：分类
    month_label: str
    month_number: int | None
    detail_total: int
    collection_total: int | None
    recovered_colleges: list[str]
    recovered_total: int


# ============================================================
# 3. 读取、校验与缺失数据恢复
# ============================================================

DAY_COLUMN_PATTERN = re.compile(
    r"^(\d{1,2})日\s*[（(]\s*次数\s*[）)]$"
)


def _text(value: object) -> str:
    if pd.isna(value):
        return ""
    return str(value).strip()


def _is_summary_name(name: str) -> bool:
    return not name or "合计" in name or name == "借阅比率"


def _find_header_row(raw: pd.DataFrame) -> int:
    for idx, row in raw.iterrows():
        values = {_text(value) for value in row}
        if {"序号", "分类名称"}.issubset(values):
            return int(idx)
    raise ValueError(
        "未找到表头：同一行中必须同时存在“序号”和“分类名称”。"
    )


def _extract_month(raw: pd.DataFrame, header_row: int) -> tuple[str, int | None]:
    for pos in range(header_row):
        for value in raw.iloc[pos].tolist():
            match = re.search(
                r"借阅时间\s*[：:]\s*(\d{4})-(\d{1,2})",
                _text(value),
            )
            if match:
                year, month = int(match.group(1)), int(match.group(2))
                return f"{year}年{month}月", month
    return "", None


def _extract_college(raw: pd.DataFrame, header_row: int, fallback: str) -> str:
    for pos in range(header_row):
        for value in raw.iloc[pos].tolist():
            text = _text(value)
            match = re.search(r"(?:^|\s)院系[：:]\s*([^\s]+)", text)
            if match:
                return match.group(1).strip()
    return fallback


def _extract_summary_total(
    raw: pd.DataFrame,
    header_row: int,
    keyword: str,
) -> int | None:
    header_values = [_text(value) for value in raw.iloc[header_row]]
    try:
        category_col = header_values.index("分类名称")
        total_col = header_values.index("合计")
    except ValueError:
        return None

    for pos in range(header_row + 1, len(raw)):
        if _text(raw.iat[pos, category_col]) == keyword:
            value = raw.iat[pos, total_col]
            try:
                if isinstance(value, str):
                    value = value.replace(",", "").replace("次", "").strip()
                return int(round(float(value)))
            except (TypeError, ValueError):
                return None
    return None


def _read_table(
    path: Path,
    expected_categories: tuple[str, ...] | None = None,
) -> tuple[str, str, int | None, tuple[str, ...], tuple[str, ...], np.ndarray, int]:
    """读取一个学院文件，返回学院、月份、分类、分类号及分类×日期矩阵。"""
    raw = pd.read_excel(path, header=None)
    header_row = _find_header_row(raw)

    df = pd.read_excel(path, header=header_row)
    df.columns = [_text(column) for column in df.columns]
    df = df.dropna(axis=1, how="all")

    if "分类名称" not in df.columns:
        raise ValueError(f"{path.name}：表头缺少“分类名称”列。")

    names = df["分类名称"].map(_text)
    keep = (
        df["分类名称"].notna()
        & names.map(lambda value: not _is_summary_name(value))
    )
    detail = df.loc[keep].copy()
    detail["分类名称"] = names.loc[keep].values
    detail = detail.reset_index(drop=True)
    if detail.empty:
        raise ValueError(f"{path.name}：没有有效的分类明细。")

    categories = tuple(detail["分类名称"].tolist())
    if expected_categories is not None and categories != expected_categories:
        raise ValueError(
            f"{path.name}：分类名称或顺序与其他学院文件不一致。"
        )

    if "分类号" in detail.columns:
        codes = tuple(detail["分类号"].map(_text).tolist())
    else:
        codes = tuple("" for _ in categories)

    day_matrix = np.zeros((len(categories), 31), dtype=int)
    seen_days: set[int] = set()
    for column in detail.columns:
        match = DAY_COLUMN_PATTERN.fullmatch(_text(column))
        if not match:
            continue
        day = int(match.group(1))
        if not 1 <= day <= 31 or day in seen_days:
            raise ValueError(f"{path.name}：日期字段异常（{column}）。")
        seen_days.add(day)
        values = pd.to_numeric(detail[column], errors="raise").fillna(0)
        if (values < 0).any() or (values % 1 != 0).any():
            raise ValueError(f"{path.name}：借阅次数必须为非负整数。")
        day_matrix[:, day - 1] = values.astype(int).to_numpy()

    # 若源表带“合计”列，逐行核对日期明细，防止漏读日期列。
    if "合计" in detail.columns:
        declared = pd.to_numeric(detail["合计"], errors="coerce")
        calculated = day_matrix.sum(axis=1)
        valid = declared.notna().to_numpy()
        if not np.array_equal(
            declared.fillna(0).astype(int).to_numpy()[valid],
            calculated[valid],
        ):
            raise ValueError(
                f"{path.name}：日期明细之和与“合计”列不一致，"
                "可能存在未识别的日期字段。"
            )

    month_label, month_number = _extract_month(raw, header_row)
    college = _extract_college(raw, header_row, path.stem)
    return (
        college,
        month_label,
        month_number,
        categories,
        codes,
        day_matrix,
        header_row,
    )


def _read_reference_totals(
    path: Path,
    expected_categories: tuple[str, ...],
) -> ReferenceTotals:
    (
        _,
        _,
        _,
        categories,
        _,
        day_matrix,
        header_row,
    ) = _read_table(path, expected_categories)

    raw = pd.read_excel(path, header=None)
    total_col = next(
        (
            index
            for index, _ in enumerate(raw.columns)
            if _text(raw.iat[header_row, index]) == "合计"
        ),
        None,
    )
    collection_total = None
    if total_col is not None:
        header_values = [_text(value) for value in raw.iloc[header_row]]
        category_col = header_values.index("分类名称")
        for pos in range(header_row + 1, len(raw)):
            if _text(raw.iat[pos, category_col]) == "馆藏借阅合计":
                try:
                    collection_total = int(round(float(raw.iat[pos, total_col])))
                except (TypeError, ValueError):
                    collection_total = None
                break

    category_totals = day_matrix.sum(axis=1).astype(int)
    return ReferenceTotals(
        categories=categories,
        category_totals=category_totals,
        detail_total=int(category_totals.sum()),
        collection_total=collection_total,
    )


def load_source_data(
    data_dir: Path,
    reference_total_file: Path | None = None,
) -> SourceData:
    if not data_dir.exists():
        raise FileNotFoundError(f"找不到学院数据目录：{data_dir}")

    files = sorted(data_dir.glob("*.xlsx"))
    files = [path for path in files if not path.name.startswith("~$")]
    if not files:
        raise FileNotFoundError(f"{data_dir} 中没有 .xlsx 文件。")

    expected_categories: tuple[str, ...] | None = None
    expected_codes: tuple[str, ...] | None = None
    month_label = ""
    month_number: int | None = None
    colleges: list[CollegeData] = []
    category_totals: list[np.ndarray] = []
    seen_names: set[str] = set()

    for path in files:
        (
            college,
            file_month_label,
            file_month_number,
            categories,
            codes,
            day_matrix,
            _,
        ) = _read_table(path, expected_categories)

        if expected_categories is None:
            expected_categories = categories
            expected_codes = codes
            month_label = file_month_label
            month_number = file_month_number
        elif file_month_label and month_label and file_month_label != month_label:
            raise ValueError(
                f"{path.name}：统计月份为 {file_month_label}，"
                f"与其他文件的 {month_label} 不一致。"
            )

        if expected_codes is not None and codes != expected_codes:
            raise ValueError(f"{path.name}：分类号与其他学院文件不一致。")
        if college in seen_names:
            raise ValueError(f"学院名称重复：{college}（{path.name}）")
        seen_names.add(college)

        totals = day_matrix.sum(axis=1).astype(int)
        category_totals.append(totals)
        colleges.append(
            CollegeData(
                name=college,
                path=path,
                category_totals=totals,
                daily_total=int(totals.sum()),
                source=path.name,
            )
        )

    assert expected_categories is not None

    reference: ReferenceTotals | None = None
    if reference_total_file is not None and reference_total_file.exists():
        reference = _read_reference_totals(
            reference_total_file, expected_categories
        )
    elif any(college.daily_total == 0 for college in colleges):
        raise FileNotFoundError(
            "存在导出为空的学院文件，但找不到用于校验恢复的全校汇总表："
            f"{reference_total_file}"
        )

    matrix = np.vstack(category_totals).astype(int)
    empty_indices = [
        index for index, college in enumerate(colleges)
        if college.daily_total == 0
    ]
    recovered_colleges: list[str] = []
    recovered_total = 0

    if empty_indices:
        if len(empty_indices) > 1:
            names = "、".join(colleges[index].name for index in empty_indices)
            raise ValueError(
                f"有多个学院导出为空表（{names}），无法可靠确定各自数据，"
                "请重新导出这些学院后再生成。"
            )
        if reference is None:
            raise ValueError("空学院文件无法恢复：缺少全校汇总表。")

        empty_index = empty_indices[0]
        others_sum = matrix.sum(axis=0) - matrix[empty_index]
        residual = reference.category_totals - others_sum
        if (residual < 0).any():
            raise ValueError(
                "无法恢复空学院文件：其余学院合计已超过全校汇总，"
                "请检查是否有重复或错误数据。"
            )
        if int(residual.sum()) <= 0:
            raise ValueError("空学院文件的恢复差额为0，请确认源数据。")

        matrix[empty_index] = residual
        recovered_colleges.append(colleges[empty_index].name)
        recovered_total = int(residual.sum())
        colleges[empty_index].category_totals = residual
        colleges[empty_index].daily_total = recovered_total

    detail_total = int(matrix.sum())
    if reference is not None:
        if detail_total != reference.detail_total:
            raise ValueError(
                "学院数据合计与全校分类明细不一致："
                f"学院合计={detail_total}，全校={reference.detail_total}。"
            )
        if not np.array_equal(matrix.sum(axis=0), reference.category_totals):
            raise ValueError("学院分类汇总与全校各分类合计不一致。")

    return SourceData(
        colleges=colleges,
        categories=[
            Category(index, expected_codes[index], name)
            for index, name in enumerate(expected_categories)
        ],
        matrix=matrix,
        month_label=month_label,
        month_number=month_number,
        detail_total=detail_total,
        collection_total=reference.collection_total if reference else None,
        recovered_colleges=recovered_colleges,
        recovered_total=recovered_total,
    )


# ============================================================
# 4. 绘图辅助
# ============================================================

def _chinese_fonts() -> tuple[fm.FontProperties, fm.FontProperties]:
    candidates = [
        "Microsoft YaHei", "Microsoft JhengHei", "SimHei",
        "Noto Sans CJK SC", "Source Han Sans SC", "PingFang SC",
    ]
    available = {font.name for font in fm.fontManager.ttflist}
    family = next(
        (name for name in candidates if name in available),
        "sans-serif",
    )
    return (
        fm.FontProperties(family=family),
        fm.FontProperties(family=family, weight="bold"),
    )


def _allocate_nodes(
    totals: np.ndarray,
    top: float,
    bottom: float,
    gap: float,
) -> tuple[list[float], list[float], float]:
    positive_total = float(totals.sum())
    if positive_total <= 0:
        return [], [], 0.0

    usable = top - bottom - gap * max(len(totals) - 1, 0)
    scale = usable / positive_total
    tops: list[float] = []
    bottoms: list[float] = []
    cursor = top
    for total in totals:
        height = float(total) * scale
        tops.append(cursor)
        bottoms.append(cursor - height)
        cursor -= height + gap
    return tops, bottoms, scale


def _flow_path(
    source_x: float,
    target_x: float,
    source_top: float,
    source_bottom: float,
    target_top: float,
    target_bottom: float,
) -> MplPath:
    control_x = (source_x + target_x) / 2
    vertices = [
        (source_x, source_bottom),
        (control_x, source_bottom),
        (control_x, target_bottom),
        (target_x, target_bottom),
        (target_x, target_top),
        (control_x, target_top),
        (control_x, source_top),
        (source_x, source_top),
        (source_x, source_bottom),
    ]
    codes = [
        MplPath.MOVETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.LINETO,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CURVE4,
        MplPath.CLOSEPOLY,
    ]
    return MplPath(vertices, codes)


def _node_color(index: int, colors: list[str]) -> str:
    return colors[index % len(colors)]


# ============================================================
# 5. 生成图表
# ============================================================

def create_chart(
    data: SourceData,
    output_png: Path,
    output_svg: Path,
    min_college: int = 1,
    min_link: int = 1,
    title_suffix: str = DEFAULT_TITLE_SUFFIX,
    show_window: bool = False,
    dpi: int = 200,
) -> tuple[int, int, int]:
    font_regular, font_bold = _chinese_fonts()
    plt.rcParams["axes.unicode_minus"] = False
    plt.rcParams["svg.fonttype"] = "none"

    # 阈值应用于连接，节点总量随之只统计实际绘制的连接，保证桑基图守恒。
    displayed = np.where(
        (data.matrix > 0) & (data.matrix >= min_link),
        data.matrix,
        0,
    )
    college_totals_all = displayed.sum(axis=1)
    category_totals_all = displayed.sum(axis=0)

    college_order = sorted(
        range(len(data.colleges)),
        key=lambda index: (
            -int(college_totals_all[index]),
            data.colleges[index].name,
        ),
    )
    college_order = [
        index for index in college_order
        if int(college_totals_all[index]) >= min_college
    ]
    category_order = [
        index for index in range(len(data.categories))
        if int(category_totals_all[index]) > 0
    ]

    if not college_order or not category_order:
        raise ValueError("过滤后没有可绘制的学院—分类连接。")

    shown = displayed[np.ix_(college_order, category_order)]
    college_totals = shown.sum(axis=1).astype(int)
    category_totals = shown.sum(axis=0).astype(int)
    flow_count = int((shown > 0).sum())

    fig = plt.figure(figsize=(18.6, 12.6), facecolor="white")
    ax = fig.add_axes([0.045, 0.078, 0.91, 0.795])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.set_facecolor("white")
    ax.axis("off")

    title = (
        f"{data.month_label}{title_suffix}"
        if data.month_label
        else title_suffix
    )
    subtitle = (
        f"（展示 {len(college_order)} 个学院与 {len(category_order)} 个中图法分类；"
        f"流带宽度代表借阅次数，共 {flow_count} 条连接）"
    )
    fig.text(
        0.5, 0.962, title,
        ha="center", va="top",
        fontsize=19, color=TEXT_MAIN,
        fontproperties=font_bold,
    )
    fig.text(
        0.5, 0.934, subtitle,
        ha="center", va="top",
        fontsize=9, color=TEXT_MUTED,
        fontproperties=font_regular,
    )

    left_x, right_x, bar_width = 0.145, 0.790, 0.0095
    node_top, node_bottom = 0.957, 0.043

    college_tops, college_bottoms, college_scale = _allocate_nodes(
        college_totals.astype(float),
        node_top, node_bottom,
        gap=0.014,
    )
    category_tops, category_bottoms, category_scale = _allocate_nodes(
        category_totals.astype(float),
        node_top, node_bottom,
        gap=0.014,
    )

    source_cursor = list(college_tops)
    target_cursor = list(category_tops)

    # 连接先画，节点后画。
    for source_pos, college_index in enumerate(college_order):
        for target_pos, category_index in enumerate(category_order):
            value = int(displayed[college_index, category_index])
            if value <= 0:
                continue

            source_height = value * college_scale
            target_height = value * category_scale
            source_top = source_cursor[source_pos]
            source_bottom = source_top - source_height
            target_top = target_cursor[target_pos]
            target_bottom = target_top - target_height

            source_cursor[source_pos] = source_bottom
            target_cursor[target_pos] = target_bottom

            ax.add_patch(
                mpatches.PathPatch(
                    _flow_path(
                        left_x + bar_width,
                        right_x,
                        source_top,
                        source_bottom,
                        target_top,
                        target_bottom,
                    ),
                    facecolor=_node_color(college_index, SOURCE_COLORS),
                    edgecolor="none",
                    alpha=0.265,
                    antialiased=True,
                    zorder=1,
                )
            )

    # 左侧学院节点；名称完整取自 Excel 的“院系”字段。
    for position, college_index in enumerate(college_order):
        college = data.colleges[college_index]
        top, bottom = college_tops[position], college_bottoms[position]
        mid = (top + bottom) / 2
        color = _node_color(college_index, SOURCE_COLORS)

        ax.add_patch(
            mpatches.Rectangle(
                (left_x, bottom),
                bar_width,
                max(top - bottom, 0.0007),
                facecolor=color,
                edgecolor="white",
                linewidth=0.55,
                zorder=4,
            )
        )
        ax.plot(
            [left_x - 0.007, left_x],
            [mid, mid],
            color=color,
            linewidth=0.8,
            alpha=0.7,
            zorder=3,
        )
        ax.text(
            left_x - 0.010, mid,
            college.name,
            ha="right", va="center",
            fontsize=8.2, color=TEXT_MAIN,
            fontproperties=font_regular,
            zorder=5,
        )
        ax.text(
            left_x + bar_width + 0.004, mid,
            f"{int(college_totals[position]):,}",
            ha="left", va="center",
            fontsize=6.3, color="#4C555D",
            fontproperties=font_regular,
            path_effects=[withStroke(linewidth=1.8, foreground="white")],
            zorder=6,
        )

    # 右侧分类节点
    for position, category_index in enumerate(category_order):
        category = data.categories[category_index]
        top, bottom = category_tops[position], category_bottoms[position]
        mid = (top + bottom) / 2
        color = _node_color(category_index, CATEGORY_COLORS)

        ax.add_patch(
            mpatches.Rectangle(
                (right_x, bottom),
                bar_width,
                max(top - bottom, 0.0007),
                facecolor=color,
                edgecolor="white",
                linewidth=0.55,
                zorder=4,
            )
        )
        ax.plot(
            [right_x + bar_width, right_x + bar_width + 0.007],
            [mid, mid],
            color=color,
            linewidth=0.8,
            alpha=0.75,
            zorder=3,
        )
        ax.text(
            right_x - 0.004, mid,
            f"{int(category_totals[position]):,}",
            ha="right", va="center",
            fontsize=6.3, color="#4C555D",
            fontproperties=font_regular,
            path_effects=[withStroke(linewidth=1.8, foreground="white")],
            zorder=6,
        )
        code_prefix = f"{category.code}  " if category.code else ""
        ax.text(
            right_x + bar_width + 0.010, mid,
            f"{code_prefix}{category.name}",
            ha="left", va="center",
            fontsize=8.0, color=TEXT_MAIN,
            fontproperties=font_regular,
            zorder=5,
        )

    ax.text(
        left_x + bar_width / 2, 0.016, "学院",
        ha="center", va="center",
        fontsize=8.0, color=TEXT_MUTED,
        fontproperties=font_regular,
    )
    ax.text(
        right_x + bar_width / 2, 0.016, "分类号",
        ha="center", va="center",
        fontsize=8.0, color=TEXT_MUTED,
        fontproperties=font_regular,
    )

    notes = [
        f"共 {len(college_order)} 个学院、{len(category_order)} 个分类、"
        f"{flow_count} 条非零流向，合计 {data.detail_total:,} 次。"
    ]
    zero_categories = [
        category.name
        for category in data.categories
        if int(category_totals_all[category.row_index]) == 0
    ]
    if zero_categories:
        notes.append(
            "全月 0 次分类：" + "、".join(zero_categories)
            + "，无流向，未绘制节点。"
        )
    if data.recovered_colleges:
        names = "、".join(data.recovered_colleges)
        notes.append(
            f"数据说明：{names}原导出文件为空表，"
            f"已按全校分类汇总与其余学院差额恢复 {data.recovered_total:,} 次；"
            "恢复后合计与全校分类明细一致。"
        )
    if (
        data.collection_total is not None
        and data.collection_total != data.detail_total
    ):
        difference = data.collection_total - data.detail_total
        notes.append(
            f"馆藏借阅合计 {data.collection_total:,} 次，"
            f"较分类明细多 {difference:,} 次；差额未归入分类，未擅自分摊。"
        )

    fig.text(
        0.5, 0.047,
        "\n".join(notes),
        ha="center", va="top",
        fontsize=7.2, color=TEXT_MUTED,
        fontproperties=font_regular,
        linespacing=1.55,
    )

    output_png.parent.mkdir(parents=True, exist_ok=True)
    output_svg.parent.mkdir(parents=True, exist_ok=True)
    metadata = {
        "Title": title,
        "Description": "学院到中图法分类的图书借阅桑基图",
    }
    fig.savefig(
        output_png,
        dpi=dpi,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.12,
        metadata=metadata,
    )
    fig.savefig(
        output_svg,
        facecolor="white",
        bbox_inches="tight",
        pad_inches=0.12,
        metadata=metadata,
    )

    if show_window:
        plt.show()
    plt.close(fig)
    return flow_count, len(college_order), len(category_order)


# ============================================================
# 6. 流向明细与主流程
# ============================================================

def build_flow_table(data: SourceData) -> pd.DataFrame:
    college_order = sorted(
        range(len(data.colleges)),
        key=lambda index: (
            -int(data.matrix[index].sum()),
            data.colleges[index].name,
        ),
    )
    records: list[dict[str, object]] = []
    recovered = set(data.recovered_colleges)
    for college_index in college_order:
        college = data.colleges[college_index]
        college_total = int(data.matrix[college_index].sum())
        for category in data.categories:
            value = int(data.matrix[college_index, category.row_index])
            records.append({
                "月份": data.month_label,
                "学院": college.name,
                "分类号": category.code,
                "中图法分类": category.name,
                "借阅次数": value,
                "学院借阅总量": college_total,
                "数据状态": (
                    "按全校汇总差额恢复"
                    if college.name in recovered
                    else "源文件直读"
                ),
            })
    return pd.DataFrame(records)


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value).strip(" .")
    return cleaned or "sankey_output"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a college-to-classification book-borrowing Sankey chart "
            "from per-college Chinese library Excel exports."
        )
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Directory containing one .xlsx file per college.",
    )
    parser.add_argument(
        "--reference",
        type=Path,
        default=None,
        help=(
            "Optional university-wide export. It validates college totals and "
            "recovers a single empty college workbook."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path.cwd() / "sankey-output",
        help="Directory for PNG, SVG, and CSV outputs.",
    )
    parser.add_argument(
        "--output-prefix",
        default=None,
        help="Output filename stem; defaults to the detected month.",
    )
    parser.add_argument(
        "--title-suffix",
        default=DEFAULT_TITLE_SUFFIX,
        help=f"Chart title suffix (default: {DEFAULT_TITLE_SUFFIX}).",
    )
    parser.add_argument(
        "--min-college",
        type=int,
        default=1,
        help="Hide colleges with fewer than this many displayed borrowings.",
    )
    parser.add_argument(
        "--min-link",
        type=int,
        default=1,
        help="Hide college-to-category links below this value.",
    )
    parser.add_argument(
        "--dpi",
        type=int,
        default=200,
        help="PNG resolution (default: 200).",
    )
    parser.add_argument(
        "--show",
        action="store_true",
        help="Also open an interactive Matplotlib window.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.min_college < 1 or args.min_link < 1:
        raise ValueError("--min-college 和 --min-link 必须大于等于 1。")
    if args.dpi < 72:
        raise ValueError("--dpi 必须大于等于 72。")

    data = load_source_data(args.input, args.reference)
    flow_table = build_flow_table(data)

    stem = _safe_filename(
        args.output_prefix
        or f"各学院图书借阅桑基图_{data.month_label or '未知月份'}"
    )
    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    output_png = output_dir / f"{stem}.png"
    output_svg = output_dir / f"{stem}.svg"
    output_csv = output_dir / f"{stem}_流向明细.csv"

    flow_table.to_csv(output_csv, index=False, encoding="utf-8-sig")
    flow_count, college_count, category_count = create_chart(
        data=data,
        output_png=output_png,
        output_svg=output_svg,
        min_college=args.min_college,
        min_link=args.min_link,
        title_suffix=args.title_suffix,
        show_window=args.show,
        dpi=args.dpi,
    )

    # 逐院、逐分类复核节点与连接总量。
    if int(flow_table["借阅次数"].sum()) != data.detail_total:
        raise ValueError("流向明细 CSV 合计与数据矩阵不一致。")
    college_sums = flow_table.groupby("学院", sort=False)["借阅次数"].sum()
    if int(college_sums.sum()) != int(data.matrix.sum()):
        raise ValueError("CSV 中的学院合计与矩阵不一致。")

    print("Sankey chart generated:")
    print(f"  PNG: {output_png}")
    print(f"  SVG: {output_svg}")
    print(f"  CSV: {output_csv}")
    print(
        f"Validated: {college_count} colleges x {category_count} categories, "
        f"{flow_count} non-zero flows, total {data.detail_total:,}."
    )
    if data.recovered_colleges:
        print(
            "  Recovered empty workbook(s): "
            + ", ".join(data.recovered_colleges)
            + f" ({data.recovered_total:,})"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
