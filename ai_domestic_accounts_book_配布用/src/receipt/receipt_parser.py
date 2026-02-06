"""
初回作成日：2026/1/7
作成者：kadoya
ファイル名：receipt_parser.py
"""
from __future__ import annotations

from datetime import datetime, date
from typing import Any
import re

from ..tool import logger_module as log_mod
from . import type_def


# ==================================================
# Public API
# ==================================================
def parse_receipt_dict(raw: dict[str, Any], source_file: str) -> type_def.ReceiptResult:
    """
    レシート解析の生dictデータを ReceiptResult オブジェクトに変換する。

    Args:
        raw (dict[str, Any]): Azure Document Intelligence の解析結果（to_dict）
        source_file (str): 元のレシート画像ファイル名

    Returns:
        ReceiptResult: パース・正規化済みのレシート解析結果
    """
    docs: list[dict[str, Any]] = raw.get("documents") or []
    doc0: dict[str, Any] = docs[0] if docs else {}
    fields: dict[str, Any] = doc0.get("fields") or {}

    # サマリ情報抽出
    summary: type_def.ReceiptSummary = type_def.ReceiptSummary(
        merchant_name=_pick_str_field(fields, ("MerchantName", "VendorName", "StoreName")),
        merchant_address=_pick_str_field(fields, ("MerchantAddress", "Address", "VendorAddress", "StoreAddress")),
        merchant_phone=_pick_str_field(fields, ("MerchantPhoneNumber", "PhoneNumber", "Tel", "Telephone")),
        date=_pick_str_field(fields, ("TransactionDate", "Date")),
        time=_pick_str_field(fields, ("TransactionTime", "Time")),
        total=_pick_num_field(fields, ("Total", "Amount", "TotalAmount")),
        tax=_pick_num_field(fields, ("TotalTax", "Tax", "TaxAmount")),
    )

    summary.merchant_phone = summary.merchant_phone.lstrip(":").strip()

    # 合計金額が取れなかった場合、本文テキストから抽出を試みる
    if summary.total is None:
        text = raw.get("content") or ""
        summary.total = _extract_total_from_text(text)
        if summary.total is not None:
            log_mod.info(f"TOTAL FALLBACK FROM TEXT: {summary.total}")

    # 正規化
    summary.date_iso = _normalize_date_iso(summary.date)
    summary.time_norm = _normalize_time_norm(summary.time)
    summary.total_yen = _to_yen_int(summary.total)
    summary.tax_yen = _to_yen_int(summary.tax)

    # DEBUGログ
    log_mod.debug(f"merchant_name: {summary.merchant_name}")
    log_mod.debug(f"date: {summary.date}")
    log_mod.debug(f"date_iso: {summary.date_iso}")
    log_mod.debug(f"time: {summary.time}")
    log_mod.debug(f"time_norm: {summary.time_norm}")
    log_mod.debug(f"total: {summary.total}")
    log_mod.debug(f"total_yen: {summary.total_yen}")

    items: list[type_def.ReceiptItem] = _parse_items(fields)

    # レシート成立判定
    if (summary.total_yen is None and len(items) == 0):
        log_mod.info(
            "NOT A RECEIPT DETECTED"
            f"(merchant_name='{summary.merchant_name}', "
            f"total_yen={summary.total_yen}, items=0)"
        )
        raise ValueError("NOT A RECEIPT")

    # 明細が一切取れなかった場合、合計金額から疑似明細を生成する
    if not items and summary.total_yen is not None:
        log_mod.info("CREATE PSEUDO ITEM (NO LINE ITEMS)")
        pseudo = type_def.ReceiptItem(
            name=summary.merchant_name or "UNKNOWN",
            total_price=summary.total,
            quantity=1,
            unit_price=summary.total,
        )
        pseudo.total_price_yen = summary.total_yen
        pseudo.unit_price_yen = summary.total_yen
        pseudo.tag = type_def.ReceiptTag.UNKNOWN
        pseudo.tag_reason = ""
        items.append(pseudo)

    # 明細の有無フラグ設定
    summary.has_items = len(items) > 0
    if not summary.has_items:
        log_mod.info("NO RECEIPT ITEMS DETECTED")

    return type_def.ReceiptResult(
        source_file=source_file,
        summary=summary,
        items=items,
        raw=raw,
    )


# ==================================================
# Internal helpers
# ==================================================
def _parse_items(fields: dict[str, Any]) -> list[type_def.ReceiptItem]:
    """
    レシート明細データを解析して ReceiptItem オブジェクトのリストを生成する。

    Args:
        fields (dict[str, Any]): Azure Document Intelligence の解析結果の fields 部分

    Returns:
        list[ReceiptItem]: 解析・正規化済みのレシート明細リスト
    """
    node: Any = None

    for key in ("Items", "LineItems", "PurchasedItems"):
        if key in fields:
            node = fields.get(key)
            break

    if node is None:
        return []

    value_array: list[Any] = _extract_value_array(node)
    if not value_array:
        return []

    items: list[type_def.ReceiptItem] = []
    for elem in value_array:
        obj: dict[str, Any] = _extract_value_object(elem)
        if not obj:
            continue

        name: str = _pick_str_field(obj, ("Description", "Name", "ProductName", "ItemName"))
        total_price: float | None = _pick_num_field(obj, ("TotalPrice", "Amount", "Price", "LineTotal"))
        quantity: float | None = _pick_num_field(obj, ("Quantity", "Qty"))
        unit_price: float | None = _pick_num_field(obj, ("UnitPrice", "UnitCost", "Price"))

        item: type_def.ReceiptItem = type_def.ReceiptItem(
            name=name,
            total_price=total_price,
            quantity=quantity,
            unit_price=unit_price,
        )

        item.tag = type_def.ReceiptTag.UNKNOWN
        item.tag_reason = ""

        # 正規化（円は int に寄せる）
        item.total_price_yen = _to_yen_int(item.total_price)
        item.unit_price_yen = _to_yen_int(item.unit_price)

        # どれも取れないゴミ要素は捨てる
        if (item.name.strip() == "") and (item.total_price is None) and (item.unit_price is None):
            continue

        # 明細が取れているかの確認ログ（DEBUG）
        log_mod.debug(f"item.name: {item.name}")
        log_mod.debug(f"item.total_price: {item.total_price}")
        log_mod.debug(f"item.total_price_yen: {item.total_price_yen}")
        log_mod.debug(f"item.quantity: {item.quantity}")
        log_mod.debug(f"item.unit_price: {item.unit_price}")
        log_mod.debug(f"item.unit_price_yen: {item.unit_price_yen}")

        items.append(item)

    return items


def _extract_value_array(node: Any) -> list[Any]:
    """
    Itemsノードから配列を取り出す（返却形式の揺れを吸収）

    Args:
        node (Any): Itemsノード

    Returns:
        list[Any]: 明細要素の配列
    """
    if node is None:
        return []

    if isinstance(node, list):
        return node

    if isinstance(node, dict):
        va: Any = node.get("valueArray")
        if isinstance(va, list):
            return va

        v: Any = node.get("value")
        if isinstance(v, list):
            return v

        if isinstance(v, dict):
            va2: Any = v.get("valueArray")
            if isinstance(va2, list):
                return va2

    return []


def _extract_value_object(elem: Any) -> dict[str, Any]:
    """
    明細要素から valueObject 相当の dict を取り出す（返却形式の揺れを吸収）

    Args:
        elem (Any): 明細要素ノード

    Returns:
        dict[str, Any]: 明細要素の valueObject 部分（存在しない場合は空dict）
    """
    if not isinstance(elem, dict):
        return {}

    vo: Any = elem.get("valueObject")
    if isinstance(vo, dict):
        return vo

    v: Any = elem.get("value")
    if isinstance(v, dict):
        return v

    return {}


def _pick_str_field(fields: dict[str, Any], candidates: tuple[str, ...]) -> str:
    """
    候補フィールド名から文字列フィールドを抽出する。

    Args:
        fields (dict[str, Any]): フィールド辞書
        candidates (tuple[str, ...]): 候補フィールド名タプル

    Returns:
        str: 抽出した文字列フィールド（見つからない場合は空文字列）
    """
    for key in candidates:
        if key not in fields:
            continue
        v: Any = fields.get(key)
        text: str = _extract_text_value(v)
        if text.strip():
            return text
    return ""


def _pick_num_field(fields: dict[str, Any], candidates: tuple[str, ...]) -> float | None:
    """
    候補フィールド名から数値フィールドを抽出する。

    Args:
        fields (dict[str, Any]): フィールド辞書
        candidates (tuple[str, ...]): 候補フィールド名タプル

    Returns:
        float | None: 抽出した数値フィールド（見つからない場合は None）
    """
    for key in candidates:
        if key not in fields:
            continue
        v: Any = fields.get(key)
        n: float | None = _extract_number_value(v)
        if n is not None:
            return n
    return None


def _extract_text_value(node: Any) -> str:
    """
    ノードから文字列値を抽出する。

    Args:
        node (Any): 抽出対象ノード

    Returns:
        str: 抽出した文字列値（見つからない場合は空文字列）
    """
    if node is None:
        return ""
    if isinstance(node, str):
        return node
    if isinstance(node, dict):
        if "valueString" in node and isinstance(node["valueString"], str):
            return node["valueString"]
        if "content" in node and isinstance(node["content"], str):
            return node["content"]
        if "value" in node and isinstance(node["value"], str):
            return node["value"]
        if "valueDate" in node and isinstance(node["valueDate"], str):
            return node["valueDate"]
        if "valueTime" in node and isinstance(node["valueTime"], str):
            return node["valueTime"]
    return ""


def _extract_number_value(node: Any) -> float | None:
    """
    ノードから数値値を抽出する。

    Args:
        node (Any): 抽出対象ノード

    Returns:
        float | None: 抽出した数値値（見つからない場合は None）
    """
    if node is None:
        return None

    if isinstance(node, (int, float)):
        return float(node)

    if isinstance(node, dict):
        if "valueNumber" in node and isinstance(node["valueNumber"], (int, float)):
            return float(node["valueNumber"])

        if "valueCurrency" in node and isinstance(node["valueCurrency"], dict):
            cur: dict[str, Any] = node["valueCurrency"]
            amt: Any = cur.get("amount")
            if isinstance(amt, (int, float)):
                return float(amt)

        v: Any = node.get("value")
        if isinstance(v, (int, float)):
            return float(v)

    return None


def _normalize_date_iso(text: str) -> str:
    """
    日付文字列を "YYYY-MM-DD" に正規化する。

    Args:
        text (str): 日付文字列

    Returns:
        str: 正規化済み日付文字列（パース不可の場合は空文字列）
    """
    s: str = (text or "").strip()
    if s == "":
        return ""

    try:
        return datetime.fromisoformat(s).date().strftime("%Y-%m-%d")
    except ValueError:
        pass

    m = re.search(r"(\d{4})\D+(\d{1,2})\D+(\d{1,2})", s)
    if m:
        try:
            yyyy: int = int(m.group(1))
            mm: int = int(m.group(2))
            dd: int = int(m.group(3))
            return date(yyyy, mm, dd).strftime("%Y-%m-%d")
        except ValueError:
            return ""

    return ""


def _normalize_time_norm(text: str) -> str:
    """
    時刻文字列を "HH:MM:SS" に正規化する。

    Args:
        text (str): 時刻文字列

    Returns:
        str: 正規化済み時刻文字列（パース不可の場合は空文字列）
    """
    s: str = (text or "").strip()
    if s == "":
        return ""

    m = re.search(r"(\d{1,2})\D+(\d{1,2})(?:\D+(\d{1,2}))?", s)
    if m:
        try:
            hh = int(m.group(1))
            mm = int(m.group(2))
            ss = int(m.group(3)) if m.group(3) is not None else 0
            return datetime(2000, 1, 1, hh, mm, ss).time().strftime("%H:%M:%S")
        except ValueError:
            pass

    digits = re.sub(r"\D+", "", s)
    if len(digits) in (4, 6):
        try:
            hh = int(digits[0:2])
            mm = int(digits[2:4])
            ss = int(digits[4:6]) if len(digits) == 6 else 0
            return datetime(2000, 1, 1, hh, mm, ss).time().strftime("%H:%M:%S")
        except ValueError:
            return ""

    return ""


def _to_yen_int(v: Any) -> int | None:
    """
    金額を「円のint」に寄せるための変換関数。

    Args:
        v (Any): 変換対象の金額値

    Returns:
        int | None: 円のintに変換した値（変換不可の場合は None）
    """
    if v is None:
        return None
    try:
        return int(round(float(v)))
    except (TypeError, ValueError):
        return None


def _extract_total_from_text(text: str) -> float | None:
    """
    レシート本文テキストから合計金額を抽出する（交通系・領収書対策）

    Args:
        text (str): レシート本文テキスト

    Returns:
        float | None: 抽出した合計金額（見つからない場合は None）
    """
    if not text:
        return None

    patterns = [
        r"金額[:：]?\s*([0-9,]+)\s*円",
        r"合計[:：]?\s*¥?\s*([0-9,]+)",
        r"¥\s*([0-9,]+)",
    ]

    for p in patterns:
        m = re.search(p, text)
        if m:
            try:
                return float(m.group(1).replace(",", ""))
            except ValueError:
                pass

    return None
