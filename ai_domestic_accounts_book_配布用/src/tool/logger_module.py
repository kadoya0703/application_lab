"""
初回作成日：2025/12/27
ファイル名：logger_module.py
"""
from __future__ import annotations

import inspect
import logging
import os
from datetime import datetime
from pathlib import Path
from threading import Lock
from typing import Literal


# =========================
# 定数定義
# =========================
LOG_LEVEL = Literal["DEBUG", "INFO", "ERROR"]
LOG_LEVEL_MAP: dict[LOG_LEVEL, int] = {
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "ERROR": logging.ERROR,
}


class _CustomFormatter(logging.Formatter):
    """
    ログ出力形式を定義するカスタムフォーマッタ

    - 日時、ログレベル、呼び出し元ファイル名、メッセージを表示する
    - ログの表示形式をアプリ全体で統一する
    """

    def format(self, record: logging.LogRecord) -> str:
        """
        LogRecord を独自フォーマットの文字列に変換する

        Args:
            record(logging.LogRecord): logging モジュールが生成するログ情報

        Returns:
            str: フォーマット済みのログ文字列
        """
        # logging が保持している UNIX 時刻から表示用日時を生成
        dt: datetime = datetime.fromtimestamp(record.created)
        ts: str = dt.strftime("%Y年%m月%d日 %H時%M分%S秒")

        level: str = record.levelname
        src_file: str = os.path.basename(getattr(record, "src_file", record.filename))
        msg: str = record.getMessage()

        return f"[{ts}]：[{level}]：[{src_file}]：{msg}"


class _LoggerCore:
    """
    ログ出力処理の中核クラス（内部使用）

    - コンソール出力／ファイル出力の制御
    - ログレベルの管理
    - ログファイルの遅延生成（初回ログ出力時）
    """

    def __init__(
        self,
        *,
        enable_console: bool,
        console_level: LOG_LEVEL,
        enable_file: bool,
        file_level: LOG_LEVEL,
        log_dir: str,
    ) -> None:
        """
        ログ設定に基づいてロガーを初期化する

        Args:
            enable_console(bool): コンソール出力を有効にするか
            console_level(LOG_LEVEL): コンソールに出力する最小ログレベル
            enable_file(bool): ファイル出力を有効にするか
            file_level(LOG_LEVEL): ファイルに出力する最小ログレベル
            log_dir(str): ログファイルの保存先ディレクトリ

        Returns:
            None
        """
        self.enable_console: bool = enable_console
        self.enable_file: bool = enable_file
        self.console_level: LOG_LEVEL = console_level
        self.file_level: LOG_LEVEL = file_level
        self.log_dir: str = log_dir
        logger: logging.Logger = logging.getLogger("app_logger")
        logger.setLevel(logging.DEBUG)
        logger.propagate = False
        logger.handlers.clear()
        self._logger: logging.Logger = logger

        self._formatter: _CustomFormatter = _CustomFormatter()
        # ファイルハンドラは初回ログ出力時に生成
        self._file_handler: logging.FileHandler | None = None

        # ファイル生成競合防止用ロック
        self._file_lock: Lock = Lock()

        if self.enable_console:
            ch: logging.StreamHandler = logging.StreamHandler()
            ch.setLevel(LOG_LEVEL_MAP[self.console_level])
            ch.setFormatter(self._formatter)
            self._logger.addHandler(ch)

    def _ensure_file_handler(self) -> None:
        """
        ファイル出力用ハンドラを必要に応じて生成する

        Args:
            None

        Returns:
            None
        """
        if not self.enable_file or self._file_handler is not None:
            return

        # 複数スレッドからの同時生成を防止
        with self._file_lock:
            if self._file_handler is not None:
                return

            log_dir_path: Path = Path(self.log_dir)
            log_dir_path.mkdir(parents=True, exist_ok=True)

            ts: str = datetime.now().strftime("%Y%m%d_%H%M%S")
            log_path: Path = log_dir_path / f"{ts}.log"

            fh: logging.FileHandler = logging.FileHandler(log_path, encoding="utf-8")
            fh.setLevel(LOG_LEVEL_MAP[self.file_level])
            fh.setFormatter(self._formatter)

            self._logger.addHandler(fh)
            self._file_handler = fh

    def _caller_file(self) -> str:
        """
        ログ呼び出し元のファイル名を取得する

        Args:
            None

        Returns:
            str: 呼び出し元ファイルのパス
        """
        stack: list[inspect.FrameInfo] = inspect.stack()
        caller: str = stack[3].filename if len(stack) > 3 else ""
        return caller

    def _log(self, level: int, message: str) -> None:
        """
        指定されたログレベルでログを出力する

        Args:
            level(int): logging モジュールのログレベル
            message(str): 出力するログメッセージ

        Returns:
            None
        """
        if self.enable_file:
            self._ensure_file_handler()

        src_file: str = self._caller_file()
        self._logger.log(level, message, extra={"src_file": src_file})

    def close(self) -> None:
        """
        ファイルハンドラをクローズし、ログ出力を終了する

        Args:
            None

        Returns:
            None
        """
        if self._file_handler is None:
            return

        with self._file_lock:
            if self._file_handler is None:
                return

            fh: logging.FileHandler = self._file_handler
            fh.flush()
            fh.close()
            self._logger.removeHandler(fh)
            self._file_handler = None


# ----- Public API -----
# グローバル変数定義
_core: _LoggerCore | None = None
_core_lock: Lock = Lock()


def init(
    *,
    enable_console: bool = True,
    console_level: LOG_LEVEL = "INFO",
    enable_file: bool = True,
    file_level: LOG_LEVEL = "DEBUG",
    log_dir: str = "logs",
) -> None:
    """
    ロガーを初期化する

    Args:
        enable_console(bool): コンソール出力を有効にするか
        console_level(LOG_LEVEL): コンソール出力のログレベル
        enable_file(bool): ファイル出力を有効にするか
        file_level(LOG_LEVEL): ファイル出力のログレベル
        log_dir(str): ログファイルの保存先ディレクトリ

    Returns:
        None
    """
    global _core

    with _core_lock:
        if _core is not None:
            _core.close()

        core: _LoggerCore = _LoggerCore(
            enable_console=enable_console,
            console_level=console_level,
            enable_file=enable_file,
            file_level=file_level,
            log_dir=log_dir,
        )
        _core = core


def debug(message: str) -> None:
    """
    DEBUG レベルのログを出力する

    Args:
        message(str): 出力するログメッセージ

    Returns:
        None
    """
    level: int = logging.DEBUG
    _core._log(level, message)


def info(message: str) -> None:
    """
    INFO レベルのログを出力する

    Args:
        message(str): 出力するログメッセージ

    Returns:
        None
    """
    level: int = logging.INFO
    _core._log(level, message)


def error(message: str) -> None:
    """
    ERROR レベルのログを出力する

    Args:
        message(str): 出力するログメッセージ

    Returns:
        None
    """
    level: int = logging.ERROR
    _core._log(level, message)


def delete() -> None:
    """
    ロガーを破棄する

    Args:
        None

    Returns:
        None
    """
    global _core
    with _core_lock:
        if _core is not None:
            _core.close()
            _core = None
# ----- Public API -----
