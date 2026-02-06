"""
初回作成日：2026/1/5
作成者：kadoya
ファイル名：main.py
"""
from __future__ import annotations

import json
import re
import time
from typing import Any
from datetime import date
from pathlib import Path

from .tool import logger_module as log_mod
from .receipt import receipt_manager
from .receipt import type_def
from .notify import monthly_mailer


# ==================================================
# 定数定義
# ==================================================
CURRENT_PATH: Path = Path(__file__).resolve().parent                    # srcディレクトリ
REPO_ROOT: Path = CURRENT_PATH.parent                                   # リポジトリルートディレクトリ
APP_CONFIG_PATH: Path = CURRENT_PATH / "config" / "app_config.json"     # アプリ設定ファイルパス
DATA_DIR: Path = REPO_ROOT / "data"                                     # dataディレクトリ
INPUT_DIR: Path = DATA_DIR / "input"                                    # 入力ディレクトリ
OUTPUT_DIR: Path = DATA_DIR / "output"                                  # 出力ディレクトリ
OUTPUT_JSON_DIR: Path = OUTPUT_DIR / "json"                             # JSON出力ディレクトリ
OUTPUT_CSV_DIR: Path = OUTPUT_DIR / "csv"                               # CSV出力ディレクトリ
PROCESSED_DIR: Path = DATA_DIR / "processed"                            # 処理済みディレクトリ
ERROR_DIR: Path = DATA_DIR / "error"                                    # エラーディレクトリ
OUTPUT_SUMMARY_DIR: Path = OUTPUT_DIR / "summary"                       # サマリー出力ディレクトリ
# レシート画像拡張子
RECEIPT_IMAGE_EXTS: tuple[str, ...] = (
    ".jpg",
    ".jpeg",
    ".png",
    ".bmp",
    ".tif",
    ".tiff",
    ".pdf",
    ".heic",
    ".heif",
)
INVALID_FILENAME_CHARS: re.Pattern[str] = re.compile(r'[\\/:*?"<>|]+')                                                      # ファイル名使用不可文字パターン
RECEIPT_TAGS_PROMPT_PATH: Path = CURRENT_PATH / "prompt" / "receipt_tags_prompt_english.md"                                 # レシート画像のタグ判断用プロンプトファイルパス
MONTHLY_EXPENSE_SUMMARY_PROMPT_PATH: Path = CURRENT_PATH / "prompt" / "monthly_expense_summary_prompt_english.md"           # 月次支出サマリの出力用プロンプトファイルパス(英語版)
# ==================================================
# グローバル変数
# ==================================================
app_config: dict[str, Any] = {}                                         # アプリ設定データ
rcpt_mgr: receipt_manager.ReceiptManager | None = None                  # レシートマネージャ
receipt_tags_prompt: str = ""                                           # レシート画像のタグ判断用プロンプト
monthly_expense_summary_prompt: str = ""                                # 月次支出サマリの出力用プロンプト
mailer: monthly_mailer.MonthlyMailer | None = None                      # 月次メール送信クラス


def init() -> None:
    """
    アプリケーション初期化処理。

    Args:
        None

    Returns:
        None
    """
    global app_config
    global rcpt_mgr
    global receipt_tags_prompt
    global monthly_expense_summary_prompt
    global mailer

    install_config()
    load_system_prompt()

    log_mod.init(
        enable_console=app_config["LOG_CONFIG"]["ENABLE_OUTPUT_CONSOLE"],
        console_level=app_config["LOG_CONFIG"]["OUTPUT_CONSOLE_LEVEL"],
        enable_file=app_config["LOG_CONFIG"]["ENABLE_FILE_SAVE"],
        file_level=app_config["LOG_CONFIG"]["FILE_SAVE_LEVEL"],
        log_dir=app_config["LOG_CONFIG"]["FILE_SAVE_PATH"],
    )
    log_mod.info("APP START")

    # receipt_manager 初期化
    rcpt_mgr = receipt_manager.ReceiptManager(
        input_dir=INPUT_DIR,
        error_dir=ERROR_DIR,
        receipt_image_exts=RECEIPT_IMAGE_EXTS,
        receipt_tags_prompt=receipt_tags_prompt,
        monthly_expense_summary_prompt=monthly_expense_summary_prompt,
    )

    # 月次メール送信クラス初期化
    mailer = monthly_mailer.MonthlyMailer()

    # レシート画像が1件もない場合は警告ログを出す
    if not rcpt_mgr.get_receipt_images():
        log_mod.info("NO RECEIPT IMAGES IN INPUT DIR")


def delete() -> None:
    """
    アプリケーション終了処理。

    Args:
        None

    Returns:
        None
    """
    log_mod.info("APP DELETE")
    log_mod.delete()


# ==================================================
# メイン処理
# ==================================================
def main() -> None:
    """
    アプリケーションのメイン処理。

    - レシート画像を1件ずつ処理
    - 実際の解析・保存・移動は receipt_manager に完全委譲
    - main は制御とログのみを担当する

    Args:
        None

    Returns:
        None
    """
    global app_config
    global rcpt_mgr
    global mailer

    log_mod.info("APP MAIN START")
    start_time: float = time.perf_counter()

    # local src → cloud src 対応表
    cloud_src_map: dict[Path, Path] = {}

    try:
        # ==================================================
        # cloud → input 取り込み
        # ==================================================
        if app_config["CLOUD_SYNC"]["ENABLE_CLOUD_RECEIPT_IMPORT"]:
            cloud_inbox = Path(app_config["CLOUD_SYNC"]["CLOUD_INBOX_PATH"])
            cloud_error = Path(app_config["CLOUD_SYNC"]["CLOUD_ERROR_PATH"])

            for cloud_src in cloud_inbox.iterdir():
                if not cloud_src.is_file():
                    continue

                local_dst = INPUT_DIR / cloud_src.name
                try:
                    local_dst.parent.mkdir(parents=True, exist_ok=True)
                    local_dst.write_bytes(cloud_src.read_bytes())
                    cloud_src_map[local_dst] = cloud_src
                except Exception as e:
                    log_mod.error(f"CLOUD COPY FAILED: {cloud_src.name} ({e})")
                    try:
                        cloud_error.mkdir(parents=True, exist_ok=True)
                        cloud_src.replace(cloud_error / cloud_src.name)
                    except Exception:
                        pass

        # ==================================================
        # レシート画像リスト更新
        # ==================================================
        rcpt_mgr.reload_receipt_images()

        # ==================================================
        # レシート処理
        # ==================================================
        for src in rcpt_mgr.get_receipt_images():
            proc: type_def.ReceiptProcessResult = rcpt_mgr.process_receipt(
                src=src,
                invalid_filename_chars=INVALID_FILENAME_CHARS,
                output_json_dir=OUTPUT_JSON_DIR,
                output_csv_dir=OUTPUT_CSV_DIR,
                processed_dir=PROCESSED_DIR,
                error_dir=ERROR_DIR,
            )

            # cloud src 取得
            cloud_src: Path | None = cloud_src_map.get(src)

            # ------------------------------
            # cloud 側移動
            # ------------------------------
            if cloud_src:
                try:
                    if proc.ok:
                        cloud_processed = Path(
                            app_config["CLOUD_SYNC"]["CLOUD_PROCESSED_PATH"]
                        )
                        cloud_processed.mkdir(parents=True, exist_ok=True)
                        cloud_src.replace(cloud_processed / cloud_src.name)
                        log_mod.info(f"CLOUD MOVE TO PROCESSED: {cloud_src.name}")
                    else:
                        cloud_error = Path(
                            app_config["CLOUD_SYNC"]["CLOUD_ERROR_PATH"]
                        )
                        cloud_error.mkdir(parents=True, exist_ok=True)
                        cloud_src.replace(cloud_error / cloud_src.name)
                        log_mod.info(f"CLOUD MOVE TO ERROR: {cloud_src.name}")
                except Exception as e:
                    log_mod.error(
                        f"CLOUD MOVE FAILED: {cloud_src.name} ({e})"
                    )

            if proc.ok:
                log_mod.info(f"RECEIPT PROCESS SUCCESS: {src.name}")
            else:
                log_mod.error(
                    f"RECEIPT PROCESS FAILED: {src.name} ({proc.error_reason})"
                )

    except KeyboardInterrupt:
        log_mod.info("APP INTERRUPTED BY USER")

    finally:
        try:
            # ------------------------------
            # 既存年月一覧取得
            # ------------------------------
            existing_year_months = rcpt_mgr.get_existing_year_months(
                OUTPUT_CSV_DIR
            )

            # ------------------------------
            # 月次グラフ生成
            # ------------------------------
            for year, month in existing_year_months:
                # 月次グラフ生成
                rcpt_mgr.generate_monthly_graph(
                    year=year,
                    month=month,
                    output_csv_dir=OUTPUT_CSV_DIR,
                    output_graph_dir=OUTPUT_DIR / "graph",
                )

                # 月次AIサマリ生成
                rcpt_mgr.generate_monthly_ai_summary(
                    year=year,
                    month=month,
                    output_csv_dir=OUTPUT_CSV_DIR,
                    output_summary_dir=OUTPUT_SUMMARY_DIR
                )

            # ------------------------------
            # 月次メール送信
            # ------------------------------
            if app_config["MAIL"]["ENABLE_SEND"]:
                today: date = date.today()    # 今日の日付取得

                # 指定日に当月分を送信
                if today.day == app_config["MAIL"]["MONTHLY_REPORT_SEND_DAY"]:
                    year = today.year
                    month = today.month

                    summary_path = (
                        OUTPUT_SUMMARY_DIR
                        / str(year)
                        / f"{year}{month:02d}_summary.txt"
                    )
                    graph_path = (
                        OUTPUT_DIR
                        / "graph"
                        / str(year)
                        / f"{year}{month:02d}_graph.png"
                    )

                    if summary_path.exists() and graph_path.exists():
                        summary_text = summary_path.read_text(
                            encoding="utf-8"
                        )

                        mailer.send_monthly_report(
                            year=year,
                            month=month,
                            summary_text=summary_text,
                            graph_paths=[graph_path],
                        )
                        log_mod.debug(
                            f"MONTHLY MAIL SENT: {year}-{month:02d}"
                        )
                        log_mod.debug(
                            f"MONTHLY SUMMARY: {summary_text}"
                        )
                    else:
                        log_mod.error(
                            f"MONTHLY MAIL FILE NOT FOUND: {year}-{month:02d}"
                        )

            # ------------------------------
            # 年次グラフ生成
            # ------------------------------
            years = sorted({year for year, _ in existing_year_months})
            for year in years:
                rcpt_mgr.generate_annual_graph(
                    year=year,
                    output_csv_dir=OUTPUT_CSV_DIR,
                    output_graph_dir=OUTPUT_DIR / "graph",
                )

        except Exception as e:
            log_mod.error(f"GRAPH GENERATION FAILED: ({e})")

        elapsed_time = time.perf_counter() - start_time
        log_mod.info(f"APP MAIN END (ELAPSED: {elapsed_time:.4f} sec)")


def install_config() -> None:
    """
    アプリ設定ファイル(app_config.json)を読み込み、
    グローバル変数 app_config に反映する。

    Args:
        None

    Returns:
        None
    """
    global app_config
    with APP_CONFIG_PATH.open("r", encoding="utf-8") as f:
        app_config = json.load(f)


def load_system_prompt() -> None:
    """
    システムプロンプトファイルを読み込み

    Args:
        None

    Returns:
        None
    """
    global receipt_tags_prompt
    global monthly_expense_summary_prompt

    # タグ判断用プロンプト読み込み
    with RECEIPT_TAGS_PROMPT_PATH.open("r", encoding="utf-8") as f:
        receipt_tags_prompt = f.read()

    # 月次支出サマリ用プロンプト読み込み
    with MONTHLY_EXPENSE_SUMMARY_PROMPT_PATH.open("r", encoding="utf-8") as f:
        monthly_expense_summary_prompt = f.read()


# ==================================================
# エントリーポイント
# ==================================================
if __name__ == "__main__":
    init()
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        delete()
