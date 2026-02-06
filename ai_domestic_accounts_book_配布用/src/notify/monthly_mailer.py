"""
初回作成日：2026/1/19
作成者：kadoya
ファイル名：monthly_mailer.py

月次家計簿レポートのメール送信を担当するモジュール。

責務:
- 月次サマリー（テキスト）のメール本文生成
- 月次グラフ（PNG 等）の添付
- メール送信処理（SMTP）

設計方針:
- Receipt 系モジュールには依存しない
- main.py からは send() のみを呼び出す
- 設定値（from / to 等）は初期化時に注入する
- 将来の HTML 化・通知手段追加を考慮し、クラス構成とする

備考:
- 現段階ではプレーンテキストメールを想定
- SMTP 実装は後続対応
"""
from __future__ import annotations

import os
import smtplib
from email.message import EmailMessage
from pathlib import Path
from dotenv import load_dotenv

from ..tool import logger_module as log_mod


class MonthlyMailer:
    """月次サマリー＋グラフをメール送信するクラス"""

    # SMTPサーバーホスト名(固定)
    SMTP_HOST = "smtp.gmail.com"

    # ポート番号(固定)
    SMTP_PORT = 587

    # メール件名テンプレート
    SUBJECT_TEMPLATE = ("【家計簿レポート】{year}年{month:02d}月｜月次支出サマリー")

    # メール本文テンプレート
    BODY_TEMPLATE = (
        "{year}年{month:02d}月の家計簿レポートをお送りします。\n\n"
        "■ 月次サマリー\n"
        "{summary}\n\n"
        "■ 補足\n"
        "・カテゴリー別の支出グラフを添付しています\n"
        "・前月との比較をもとにAIが要約しています\n\n"
        "このメールは自動送信されています。"
    )

    def __init__(self) -> None:
        """
        MonthlyMailer 初期化

        Args:
            None

        Returns:
            None
        """
        # .envファイルの内容を環境変数として読み込む
        load_dotenv()

        self._from_addr: str = os.getenv("MAIL_FROM_ADDR")
        self._to_addrs: list[str] = os.getenv("MAIL_TO_ADDRS", "").split(",")
        self._smtp_user: str = os.getenv("GMAIL_SMTP_ID")
        self._smtp_password: str = os.getenv("GMAIL_SMTP_PASSWORD")

        log_mod.info("MONTHLY MAILER INITIALIZED")

    # ==================================================
    # Public API
    # ==================================================
    def send_monthly_report(self, *, year: int, month: int, summary_text: str, graph_paths: list[Path]) -> None:
        """
        月次レポートメール送信

        Args:
            year(int): 対象年
            month(int): 対象月
            summary_text(str): 月次サマリーテキスト
            graph_paths(list[Path]): 添付するグラフファイルパス一覧

        Returns:
            None
        """
        log_mod.info(f"SEND MONTHLY MAIL START: {year}-{month:02d}")

        subject: str = self.SUBJECT_TEMPLATE.format(year=year, month=month)
        body: str = self.BODY_TEMPLATE.format(year=year, month=month, summary=summary_text)

        msg = EmailMessage()
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)
        msg["Subject"] = subject
        msg.set_content(body)

        # 添付ファイル追加
        for path in graph_paths:
            if not path.exists():
                log_mod.error(f"ATTACHMENT NOT FOUND: {path}")
                continue

            data = path.read_bytes()
            msg.add_attachment(
                data,
                maintype="image",
                subtype=path.suffix.lstrip("."),
                filename=path.name,
            )

        log_mod.debug(
            f"MAIL ATTACHMENTS: {[p.name for p in graph_paths]}"
        )

        # SMTP送信
        try:
            with smtplib.SMTP(self.SMTP_HOST, self.SMTP_PORT) as server:
                server.starttls()
                server.login(self._smtp_user, self._smtp_password)
                server.send_message(msg)

            log_mod.info(
                f"SEND MONTHLY MAIL SUCCESS: {year}-{month:02d}"
            )

        except Exception as e:
            log_mod.error(
                f"SEND MONTHLY MAIL FAILED: {year}-{month:02d} ({e})"
            )
            raise
