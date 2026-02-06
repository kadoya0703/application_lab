"""
初回作成日：2026/1/6
作成者：kadoya
ファイル名：type_def.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from enum import Enum


@dataclass
class ReceiptItem:
    """
    レシート明細データクラス

    Attributes:
        name (str): 商品名
        total_price (float | None): 合計金額（raw）
        quantity (float | None): 数量（raw）
        unit_price (float | None): 単価（raw）
        total_price_yen (int | None): 合計金額（円・正規化後）
        unit_price_yen (int | None): 単価（円・正規化後）
        tag (ReceiptTag | None): 商品に対する判定タグ
        tag_reason (str): タグ判定理由
    """
    name: str = ""
    total_price: float | None = None
    quantity: float | None = None
    unit_price: float | None = None
    total_price_yen: int | None = None
    unit_price_yen: int | None = None

    # --- 商品単位タグ判定 ---
    tag: Optional["ReceiptTag"] = None
    tag_reason: str = ""


@dataclass
class ReceiptSummary:
    """
    レシートサマリデータクラス

    Attributes:
        merchant_name (str): 店舗名
        merchant_address (str): 店舗住所
        merchant_phone (str): 店舗電話番号
        date (str): 購入日（raw）
        time (str): 購入時間（raw）
        total (float | None): 合計金額（raw）
        tax (float | None): 税金（raw）
        date_iso (str): 購入日（ISOフォーマット・正規化後）
        time_norm (str): 購入時間（正規化後）
        total_yen (int | None): 合計金額（円・正規化後）
        tax_yen (int | None): 税金（円・正規化後）
        tags (list[ReceiptTag]): レシート全体に対する判定タグリスト
        used_fallback_date (bool): 日付をfallback生成したか
        has_items (bool): 明細が取得できたか
    """
    merchant_name: str = ""
    merchant_address: str = ""
    merchant_phone: str = ""
    date: str = ""
    time: str = ""
    total: float | None = None
    tax: float | None = None

    # 正規化済み（CSV/JSONの基本はこちらを使用）
    date_iso: str = ""
    time_norm: str = ""
    total_yen: int | None = None
    tax_yen: int | None = None
    tags: list["ReceiptTag"] = field(default_factory=list)

    # ==================================================
    # 解析信頼度・フォールバック情報
    # ==================================================
    used_fallback_date: bool = False   # 日付をfallback生成したか
    has_items: bool = True             # 明細が取得できたか


@dataclass
class ReceiptResult:
    """
    レシート解析結果データクラス

    Attributes:
        source_file (str): 元ファイル名
        summary (ReceiptSummary): レシートサマリ情報
        items (list[ReceiptItem]): レシート明細リスト
        raw (dict[str, Any]): AI 解析の生データ
    """
    source_file: str = ""
    summary: ReceiptSummary = field(default_factory=ReceiptSummary)
    items: list[ReceiptItem] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class ReceiptProcessResult:
    """
    レシート処理結果クラス（receipt_manager の戻り値用）

    - main.py は本クラスのみを見て処理結果を判断する
    - 成功時は result に ReceiptResult が入る
    - 失敗時は error_reason に理由を入れる

    Attributes:
        ok (bool): 処理成功フラグ
        result (ReceiptResult | None): 成功時の解析結果
        error_reason (str): 失敗理由（ログ・UI表示用）
    """
    ok: bool
    result: Optional[ReceiptResult] = None
    error_reason: str = ""

    @classmethod
    def success(cls, result: ReceiptResult) -> "ReceiptProcessResult":
        """
        成功結果を生成する。

        Args:
            result (ReceiptResult): レシート解析結果

        Returns:
            ReceiptProcessResult: 成功結果
        """
        return cls(ok=True, result=result, error_reason="")

    @classmethod
    def failed(cls, reason: str) -> "ReceiptProcessResult":
        """
        失敗結果を生成する。

        Args:
            reason (str): 失敗理由

        Returns:
            ReceiptProcessResult: 失敗結果
        """
        return cls(ok=False, result=None, error_reason=reason)


class ReceiptTag(Enum):
    """レシートタグ列挙型"""
    FOOD = "食費"
    EAT_OUT = "外食"
    DAILY_NECESSITIES = "日用品"
    MEDICAL = "医療"
    TRANSPORTATION = "交通"
    ENTERTAINMENT = "娯楽"
    CLOTHING = "衣類"
    HOUSING = "住居"
    UTILITIES = "公共料金"
    COMMUNICATION = "通信"
    EDUCATION = "教育"
    WORK = "仕事"
    OTHER = "その他"
    UNKNOWN = "不明"
