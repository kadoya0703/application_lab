"""
初回作成日：2026/1/6
作成者：kadoya
ファイル名：receipt_store.py
"""
from __future__ import annotations

import csv
import re
import shutil
import json
from typing import Any
from datetime import datetime, date
from pathlib import Path
from PIL import Image
import pillow_heif

from ..tool import logger_module as log_mod
from . import type_def


# ==================================================
# CSV 出力定義（receiptサマリ）
# ==================================================
# レシートサマリCSVヘッダー
RECEIPT_SUMMARY_CSV_HEADERS: tuple[str, ...] = (
    "receipt_id",
    "date",
    "time",
    "merchant_name",
    "item_name",
    "item_tag",
    "item_tag_reason",
    "total_price_yen",
    "unit_price_yen",
    "quantity",
    "source_file",
    "json_file",
)
# ==================================================
# Image conversion settings (Azure Document Intelligence)
# ==================================================
MAX_IMAGE_EDGE_PX: int = 2000           # 画像の最大辺(px)
OUTPUT_IMAGE_FORMAT: str = "JPEG"       # 出力画像形式
OUTPUT_IMAGE_QUALITY: int = 85          # 出力画像品質（1-100）


# HEIF形式画像対応登録
pillow_heif.register_heif_opener()


def load_receipt_image(
    input_dir: Path,
    error_dir: Path,
    receipt_image_exts: tuple[str, ...],
) -> list[Path]:
    """
    入力ディレクトリ(data/input)を走査し、処理対象のレシート画像を収集する。

    Args:
        input_dir (Path): 入力ディレクトリパス
        error_dir (Path): errorディレクトリパス
        receipt_image_exts (tuple[str, ...]): 処理対象のレシート画像拡張子タプル

    Returns:
        list[Path]: 処理対象のレシート画像ファイルパスリスト
    """
    input_dir.mkdir(parents=True, exist_ok=True)
    error_dir.mkdir(parents=True, exist_ok=True)

    receipt_images: list[Path] = []

    for p in input_dir.iterdir():
        if not p.is_file():
            continue

        if p.suffix.lower() not in receipt_image_exts:
            log_mod.error(f"INVALID EXTENSION -> MOVE TO ERROR: {p.name}")
            move_to_error(p, error_dir)
            continue

        receipt_images.append(p)

    receipt_images.sort(key=lambda x: x.name)
    log_mod.info("ALL LOAD RECEIPT IMAGES")
    return receipt_images


def build_base_name(
    result: type_def.ReceiptResult,
    invalid_filename_chars: re.Pattern[str],
) -> str:
    """
    解析結果から保存用の basename を生成する。

    - date_iso / date が取れない場合は source_file の mtime を使用する
    - 必ず basename を返す（空文字は返さない）

    Args:
        result (ReceiptResult): レシート解析結果オブジェクト
        invalid_filename_chars (re.Pattern): ファイル名に使えない文字の正規表現パターン

    Returns:
        str: 生成したベースファイル名（拡張子なし）
    """
    summary = result.summary

    d: date | None = None

    # --------------------------------------------------
    # 1. date_iso 優先
    # --------------------------------------------------
    date_iso: str = summary.date_iso.strip()
    if date_iso:
        try:
            d = datetime.fromisoformat(date_iso).date()
        except ValueError:
            d = None

    # --------------------------------------------------
    # 2. raw date パース
    # --------------------------------------------------
    if d is None and summary.date.strip():
        d = _parse_date(summary.date)

    # --------------------------------------------------
    # 3. fallback: source_file の mtime
    # --------------------------------------------------
    if d is None:
        try:
            src = Path(result.source_file)
            if src.exists():
                d = datetime.fromtimestamp(src.stat().st_mtime).date()
                log_mod.debug(
                    f"USE FILE MTIME FOR BASENAME DATE: {result.source_file} -> {d}"
                )
        except Exception:
            d = None

    # --------------------------------------------------
    # 最終防衛ライン（それでも取れない場合）
    # --------------------------------------------------
    if d is None:
        d = datetime.now().date()
        log_mod.debug("USE CURRENT DATE FOR BASENAME")

    # --------------------------------------------------
    # time
    # --------------------------------------------------
    hhmmss: str = "000000"
    time_norm: str = summary.time_norm.strip()
    if time_norm:
        hhmmss = time_norm.replace(":", "")
    elif summary.time.strip():
        parts = summary.time.split(":")
        if len(parts) >= 2:
            hh = parts[0].zfill(2)
            mm = parts[1].zfill(2)
            ss = parts[2].zfill(2) if len(parts) >= 3 else "00"
            hhmmss = f"{hh}{mm}{ss}"

    # --------------------------------------------------
    # shop
    # --------------------------------------------------
    shop: str = summary.merchant_name.strip() or "UNKNOWN"
    shop = invalid_filename_chars.sub("_", shop)

    return f"{d:%Y%m%d}_{hhmmss}_{shop}"


def _parse_date(text: str) -> date | None:
    """
    日付文字列を date 型に変換する。

    Args:
        text (str): 日付文字列

    Returns:
        date | None: 変換した date オブジェクト（パース不可の場合は None）
    """
    s: str = text.strip()

    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        pass

    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    return None


def _parse_year_from_base_name(base: str) -> str:
    """
    basename(YYYYMMDD_...) から年(YYYY)を推定する。

    Args:
        base (str): ベースファイル名（拡張子なし）

    Returns:
        str: 年(YYYY)
    """
    s: str = (base or "").strip()
    if len(s) >= 4 and s[:4].isdigit():
        return s[:4]
    return "unknown"


def move_to_processed(src: Path, base: str, processed_dir: Path) -> Path:
    """
    入力ファイルを processed ディレクトリへ移動する。

    Args:
        src (Path): 移動元ファイルパス
        base (str): 保存用のベースファイル名（拡張子なし）
        processed_dir (Path): processed ディレクトリパス

    Returns:
        Path: 移動先ファイルパス
    """
    processed_dir.mkdir(parents=True, exist_ok=True)

    year = _parse_year_from_base_name(base)
    year_dir = processed_dir / year
    year_dir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        log_mod.error(f"SOURCE NOT FOUND -> SKIP MOVE TO PROCESSED: {src}")
        return src

    suffix = src.suffix.lower()
    dst = year_dir / f"{base}{suffix}"

    if not dst.exists():
        shutil.move(str(src), str(dst))
        return dst

    index = 1
    while True:
        candidate = year_dir / f"{base}_{index}{suffix}"
        if not candidate.exists():
            shutil.move(str(src), str(candidate))
            return candidate
        index += 1


def move_to_error(src: Path, error_dir: Path) -> None:
    """
    処理対象外/処理失敗のファイルを error ディレクトリへ移動する。

    Args:
        src (Path): 移動元ファイルパス
        error_dir (Path): error ディレクトリパス

    Returns:
        None
    """
    error_dir.mkdir(parents=True, exist_ok=True)

    if not src.exists():
        log_mod.error(f"SOURCE NOT FOUND -> SKIP MOVE TO ERROR: {src}")
        return

    dst = error_dir / src.name
    if not dst.exists():
        shutil.move(str(src), str(dst))
        return

    index = 1
    while True:
        candidate = error_dir / f"{src.stem}_{index}{src.suffix}"
        if not candidate.exists():
            shutil.move(str(src), str(candidate))
            return
        index += 1


def save_result_json(
    result: type_def.ReceiptResult,
    base: str,
    output_json_dir: Path,
) -> Path:
    """
    レシート解析結果を JSON として保存する。

    Args:
        result (ReceiptResult): レシート解析結果オブジェクト
        base (str): 保存用のベースファイル名（拡張子なし）
        output_json_dir (Path): 出力先ディレクトリパス

    Returns:
        Path: 保存先ファイルパス
    """
    output_json_dir.mkdir(parents=True, exist_ok=True)

    year = _safe_parse_year(result, base)
    year_dir = output_json_dir / year
    year_dir.mkdir(parents=True, exist_ok=True)

    out = year_dir / f"{base}.json"

    data: dict[str, Any] = {
        "source_file": result.source_file,
        "summary": {
            "merchant_name": result.summary.merchant_name,
            "merchant_address": result.summary.merchant_address,
            "merchant_phone": result.summary.merchant_phone,
            "date": result.summary.date_iso or "",
            "time": result.summary.time_norm or "",
            "total": result.summary.total_yen,
            "tax": result.summary.tax_yen,
        },
        "items": [
            {
                "name": item.name,
                "total_price": item.total_price_yen,
                "unit_price": item.unit_price_yen,
                "quantity": item.quantity,
                "tag": item.tag.value if item.tag else None,
                "tag_reason": item.tag_reason,
            }
            for item in result.items
        ],
    }

    return _save_json_dict(out, data)


def _save_json_dict(out: Path, data: dict[str, Any]) -> Path:
    """
    JSON辞書をファイルとして保存する（衝突回避あり）。

    Args:
        out (Path): 出力先ファイルパス
        data (dict[str, Any]): 保存するJSON辞書データ

    Returns:
        Path: 保存先ファイルパス
    """
    if not out.exists():
        with out.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return out

    index = 1
    while True:
        candidate = out.parent / f"{out.stem}_{index}{out.suffix}"
        if not candidate.exists():
            with candidate.open("w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return candidate
        index += 1


def get_monthly_receipt_csv_path(
    result: type_def.ReceiptResult,
    output_csv_root: Path,
    *,
    receipt_id: str,
) -> Path:
    """
    レシート結果から、月別CSVの出力先パスを生成する。

    Args:
        result (ReceiptResult): レシート解析結果オブジェクト
        output_csv_root (Path): 出力先ルートディレクトリパス
        receipt_id (str): レシートID（basename）

    Returns:
        Path: 月別CSVファイルのパス
    """
    date_iso = result.summary.date_iso.strip()

    if date_iso:
        try:
            d = datetime.fromisoformat(date_iso).date()
            return output_csv_root / f"{d:%Y}" / f"{d:%Y%m}_items.csv"
        except ValueError:
            pass

    # fallback: receipt_id (YYYYMMDD_...)
    m = re.match(r"(\d{4})(\d{2})\d{2}_", receipt_id)
    if m:
        yyyy, mm = m.group(1), m.group(2)
        log_mod.debug(
            f"USE BASENAME FOR CSV PATH: {receipt_id} -> {yyyy}{mm}"
        )
        return output_csv_root / yyyy / f"{yyyy}{mm}_items.csv"

    # 最終防衛ライン
    now = datetime.now()
    log_mod.debug("USE CURRENT MONTH FOR CSV PATH")
    return output_csv_root / f"{now:%Y}" / f"{now:%Y%m}_items.csv"


def build_receipt_summary_csv_row(
    result: type_def.ReceiptResult,
    receipt_id: str,
    saved_json_path: Path,
) -> dict[str, Any]:
    """
    レシートサマリ用のCSV 1行分のdictを生成する。

    Args:
        result (ReceiptResult): レシート解析結果オブジェクト
        receipt_id (str): レシートID（basename）
        saved_json_path (Path): 保存済みJSONファイルのパス

    Returns:
        dict[str, Any]: CSV 1行分のデータ辞書
    """
    rows: list[dict[str, Any]] = []

    for item in result.items:
        rows.append(
            {
                "receipt_id": receipt_id,
                "date": result.summary.date_iso,
                "time": result.summary.time_norm,
                "merchant_name": result.summary.merchant_name,
                "item_name": item.name,
                "item_tag": item.tag.value if hasattr(item, "tag") and item.tag else "",
                "item_tag_reason": getattr(item, "tag_reason", ""),
                "total_price_yen": item.total_price_yen,
                "unit_price_yen": item.unit_price_yen,
                "quantity": item.quantity,
                "source_file": result.source_file,
                "json_file": saved_json_path.name,
            }
        )

    return rows


def append_monthly_receipt_item_csv(
    csv_path: Path,
    rows: list[dict[str, Any]],
) -> None:
    """
    月別の商品CSVへ複数行追記する。

    Args:
        csv_path (Path): CSVファイルパス
        rows (list[dict]): 商品CSV行データ

    Returns:
        None
    """
    if not rows:
        return

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    file_exists = csv_path.exists()

    with csv_path.open("a", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RECEIPT_SUMMARY_CSV_HEADERS)
        if not file_exists:
            writer.writeheader()

        for row in rows:
            writer.writerow({k: row.get(k, "") for k in RECEIPT_SUMMARY_CSV_HEADERS})

    log_mod.debug(f"ITEM CSV APPEND OK: {csv_path.name} ({len(rows)} rows)")


def _convert_heic_to_jpg(src: Path) -> Path:
    """
    HEIC / HEIF 画像を JPG に変換する。

    Args:
        src (Path): HEIC/HEIF ファイルパス

    Returns:
        Path: 変換後の JPG ファイルパス
    """
    if src.suffix.lower() not in (".heic", ".heif"):
        return src

    dst = src.with_suffix(".jpg")

    try:
        with Image.open(src) as img:
            img = img.convert("RGB")

            # リサイズ
            w, h = img.size
            if max(w, h) > MAX_IMAGE_EDGE_PX:
                ratio = MAX_IMAGE_EDGE_PX / max(w, h)
                new_size = (int(w * ratio), int(h * ratio))
                img = img.resize(new_size, Image.LANCZOS)

            img.save(dst, OUTPUT_IMAGE_FORMAT, quality=OUTPUT_IMAGE_QUALITY, optimize=True)
        src.unlink()
        log_mod.info(f"HEIC CONVERTED & RESIZED -> JPG: {dst.name}")
        return dst

    except Exception as e:
        log_mod.error(f"HEIC CONVERT FAILED: {src.name} ({e})")
        raise


def import_from_cloud(
    cloud_inbox_dir: Path,
    cloud_error_dir: Path,
    input_dir: Path,
) -> int:
    """
    クラウド受信箱から input ディレクトリへレシート画像を取り込む。

    ※ 注意
    - この関数では「コピーのみ」を行う
    - クラウド側の processed / error への移動は行わない
    - 最終的な成功 / 失敗はアプリ側で判断する

    Args:
        cloud_inbox_dir (Path): クラウド受信箱ディレクトリ
        cloud_error_dir (Path): クラウド同期済みの error ディレクトリ
        input_dir (Path): input ディレクトリ

    Returns:
        int: 取り込んだファイル数
    """
    if not cloud_inbox_dir.exists():
        log_mod.info(f"CLOUD INBOX NOT FOUND -> SKIP: {cloud_inbox_dir}")
        return 0

    input_dir.mkdir(parents=True, exist_ok=True)
    cloud_error_dir.mkdir(parents=True, exist_ok=True)

    count = 0

    for p in cloud_inbox_dir.iterdir():
        if not p.is_file():
            continue

        try:
            dst = input_dir / p.name
            shutil.copy2(p, dst)

            # HEIC → JPG 変換 & リサイズ
            _convert_heic_to_jpg(dst)

            # ※ 成功してもクラウド側は動かさない
            count += 1

        except Exception as e:
            log_mod.error(f"CLOUD IMPORT FAILED: {p.name} ({e})")

            # 失敗時のみ cloud error へ
            try:
                shutil.move(str(p), str(cloud_error_dir / p.name))
            except Exception:
                pass

    if count > 0:
        log_mod.info(f"IMPORTED FROM CLOUD: {count} FILES")

    return count


def _safe_parse_year(
    result: type_def.ReceiptResult,
    base: str,
) -> str:
    """
    JSON / CSV 用の年(YYYY)を安全に取得する。

    優先順位:
        1. summary.date_iso
        2. basename(YYYYMMDD_...)
        3. 現在年

    Args:
        result (ReceiptResult): レシート解析結果オブジェクト
        base (str): 保存用のベースファイル名（拡張子なし）

    Returns:
        str: 年(YYYY)
    """
    date_iso = result.summary.date_iso.strip()
    if date_iso:
        try:
            return f"{datetime.fromisoformat(date_iso).date():%Y}"
        except ValueError:
            pass

    year_from_base = _parse_year_from_base_name(base)
    if year_from_base != "unknown":
        return year_from_base

    log_mod.debug("USE CURRENT YEAR FOR OUTPUT PATH")
    return f"{datetime.now().year}"
