"""
初回作成日：2026/1/11
作成者：kadoya
ファイル名：receipt_grapher.py

月別レシートCSVから、カテゴリー別支出の横棒グラフを生成するモジュール
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Dict

import matplotlib.pyplot as plt

from . import type_def
from ..tool import logger_module as log_mod
from matplotlib import rcParams


# ==================================================
# 定数定義
# ==================================================
# 日本語フォント設定
rcParams["font.family"] = "Meiryo"
# カテゴリー別カラー設定
CATEGORY_COLOR_MAP: dict[str, str] = {
    "食費": "#4CAF50",
    "外食": "#FF9800",
    "日用品": "#2196F3",
    "交通": "#9C27B0",
    "医療": "#F44336",
    "娯楽": "#00BCD4",
    "衣類": "#E91E63",
    "住居": "#795548",
    "公共料金": "#607D8B",
    "通信": "#3F51B5",
    "教育": "#8BC34A",
    "仕事": "#FFC107",
    "その他": "#9E9E9E",
    "不明": "#BDBDBD",
}


# ==================================================
# Public API
# ==================================================
def generate_monthly_category_bar_graph(
    *,
    csv_root: Path,
    graph_root: Path,
    year: int,
    month: int,
) -> Path:
    """
    指定した年月のCSVから、カテゴリー別支出の横棒グラフを生成しPNG保存する。

    Args:
        csv_root (Path): CSVルートディレクトリ（data/output/csv）
        graph_root (Path): グラフ出力ルートディレクトリ（data/output/graph）
        year (int): 年（YYYY）
        month (int): 月（1-12）

    Returns:
        Path: 生成したPNGファイルのパス
    """
    ym = f"{year:04d}{month:02d}"
    csv_path = csv_root / f"{year:04d}" / f"{ym}_items.csv"

    if not csv_path.exists():
        msg = f"MONTHLY CSV NOT FOUND: {csv_path}"
        log_mod.error(msg)
        raise FileNotFoundError(msg)

    # --------------------------------------------------
    # CSV読み込み & カテゴリー別集計
    # --------------------------------------------------
    totals: Dict[str, int] = _aggregate_by_category(csv_path)

    if not totals:
        msg = f"NO DATA TO PLOT: {csv_path.name}"
        log_mod.error(msg)
        raise ValueError(msg)

    # --------------------------------------------------
    # 金額降順にソート
    # --------------------------------------------------
    sorted_items = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    categories = [k for k, _ in sorted_items]
    amounts = [v for _, v in sorted_items]

    # --------------------------------------------------
    # 出力パス生成
    # --------------------------------------------------
    out_dir = graph_root / f"{year:04d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{ym}_graph.png"

    # --------------------------------------------------
    # グラフ生成（横棒）
    # --------------------------------------------------
    _plot_horizontal_bar(
        categories=categories,
        amounts=amounts,
        title=f"{year}年{month}月 カテゴリー別支出",
        out_path=out_path,
    )

    log_mod.info(f"MONTHLY GRAPH GENERATED: {out_path}")
    return out_path


def generate_annual_category_bar_graph(
    *,
    csv_root: Path,
    graph_root: Path,
    year: int,
) -> Path:
    """
    指定した年のCSV（月別）をすべて集計し、
    カテゴリー別「年間支出」の横棒グラフを生成する。

    ※ 1〜12月が揃っていなくても、存在するCSVのみで作成する。

    Args:
        csv_root (Path): CSVルートディレクトリ（data/output/csv）
        graph_root (Path): グラフ出力ルートディレクトリ（data/output/graph）
        year (int): 年（YYYY）

    Returns:
        Path: 生成したPNGファイルのパス
    """
    year_dir = csv_root / f"{year:04d}"

    if not year_dir.exists():
        msg = f"ANNUAL CSV DIR NOT FOUND: {year_dir}"
        log_mod.error(msg)
        raise FileNotFoundError(msg)

    # --------------------------------------------------
    # 月別CSVをすべて集計（存在する分だけ）
    # --------------------------------------------------
    annual_totals: Dict[str, int] = defaultdict(int)

    csv_files = sorted(year_dir.glob("*_items.csv"))
    if not csv_files:
        msg = f"NO CSV FILES FOR YEAR: {year}"
        log_mod.error(msg)
        raise ValueError(msg)

    for csv_path in csv_files:
        monthly_totals = _aggregate_by_category(csv_path)
        for tag, amount in monthly_totals.items():
            annual_totals[tag] += amount

    if not annual_totals:
        msg = f"NO DATA TO PLOT (ANNUAL): {year}"
        log_mod.error(msg)
        raise ValueError(msg)

    # --------------------------------------------------
    # 金額降順ソート
    # --------------------------------------------------
    sorted_items = sorted(
        annual_totals.items(),
        key=lambda x: x[1],
        reverse=True,
    )

    categories = [k for k, _ in sorted_items]
    amounts = [v for _, v in sorted_items]

    # --------------------------------------------------
    # 出力パス
    # --------------------------------------------------
    out_dir = graph_root / f"{year:04d}"
    out_dir.mkdir(parents=True, exist_ok=True)

    out_path = out_dir / f"{year:04d}_annual_graph.png"

    # --------------------------------------------------
    # グラフ生成
    # --------------------------------------------------
    _plot_horizontal_bar(
        categories=categories,
        amounts=amounts,
        title=f"{year}年 年間カテゴリー別支出",
        out_path=out_path,
    )

    log_mod.info(f"ANNUAL GRAPH GENERATED: {out_path}")
    return out_path


# ==================================================
# Internal helpers
# ==================================================
def _aggregate_by_category(csv_path: Path) -> Dict[str, int]:
    """
    月別CSVからカテゴリー別に支出金額を集計する。

    Args:
        csv_path (Path): 月別CSVパス

    Returns:
        dict[str, int]: {カテゴリー名: 合計金額}
    """
    totals: Dict[str, int] = defaultdict(int)

    with csv_path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)

        for row in reader:
            tag = (row.get("item_tag") or "").strip()
            price_raw = row.get("total_price_yen")

            if not tag:
                tag = type_def.ReceiptTag.UNKNOWN.value

            try:
                price = int(price_raw)
            except (TypeError, ValueError):
                continue

            totals[tag] += price

    return dict(totals)


def _plot_horizontal_bar(
    *,
    categories: list[str],
    amounts: list[int],
    title: str,
    out_path: Path,
) -> None:
    """
    横棒グラフを生成してPNG保存する。

    Args:
        categories (list[str]): カテゴリー名リスト
        amounts (list[int]): 金額リスト
        title (str): グラフタイトル
        out_path (Path): 保存先PNGパス

    Returns:
        None
    """
    plt.figure(figsize=(10, max(4, len(categories) * 0.5)))

    y_pos = range(len(categories))

    # 棒グラフ生成&色設定
    colors = [
        CATEGORY_COLOR_MAP.get(cat, "#BDBDBD")
        for cat in categories
    ]

    plt.barh(y_pos, amounts, color=colors)
    plt.yticks(y_pos, categories)
    plt.xlabel("支出金額（円）")
    plt.title(title)

    # 金額ラベル表示
    for i, value in enumerate(amounts):
        plt.text(value, i, f" {value:,}円", va="center")

    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()
