"""
初回作成日：2026/1/5
作成者：kadoya
ファイル名：receipt_ai.py
"""
# Azure Document Intelligenceへのリクエストを行うモジュール
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from azure.ai.formrecognizer import DocumentAnalysisClient
from azure.core.credentials import AzureKeyCredential

from ..tool import logger_module as log_mod

# ==================================================
# グローバル変数定義
# ==================================================
client: DocumentAnalysisClient | None = None        # Azure Document Intelligenceクライアント


def init() -> None:
    """
    生成AIクライアントを初期化する

    Args:
        None

    Returns:
        None
    """
    global client

    load_dotenv()

    endpoint: str = os.getenv("AZURE_DI_ENDPOINT", "").strip()
    key: str = os.getenv("AZURE_DI_KEY", "").strip()

    if not endpoint or not key:
        log_mod.error("AZURE_DI_ENDPOINT or AZURE_DI_KEY is empty")

    client = DocumentAnalysisClient(endpoint=endpoint, credential=AzureKeyCredential(key))
    log_mod.info("RECEIPT AI INITIALIZED")


def analyze_receipt(receipt_path: str) -> dict[str, Any]:
    """
    レシート画像をAzure Document Intelligenceで解析

    Args:
        receipt_path (str): レシート画像ファイルのパス

    Returns:
        dict[str, Any]: 解析結果の辞書データ
    """
    global client

    if client is None:
        log_mod.error("RECEIPT AI NOT INITIALIZED")

    path: Path = Path(receipt_path)
    if not path.exists():
        log_mod.error(f"RECEIPT FILE NOT FOUND: {receipt_path}")

    with path.open("rb") as f:
        poller: Any = client.begin_analyze_document(model_id="prebuilt-receipt", document=f)
        result: Any = poller.result()

    data: dict[str, Any] = result.to_dict()
    # このログは出すぎるので注意！
    # log_mod.debug(f"RECEIPT AI ANALYZE RESULT: {data}")
    return data
