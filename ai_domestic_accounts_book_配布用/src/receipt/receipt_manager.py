"""
初回作成日：ごめん、忘れた笑
作成者：kadoya
ファイル名：receipt_manager.py
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import re
import json
import csv

from ..tool import logger_module as log_mod
from . import receipt_ai
from . import receipt_parser
from . import receipt_store
from . import receipt_grapher
from . import type_def
from ..generative_ai import generative_ai


class ReceiptManager:
    """
    レシートマネージャクラス
        - レシート画像の収集、解析、保存、管理を行う。
    """

    # --- Current month ---
    FORMAT_CURRENT_MONTH = (
        "In {year}-{month:02d}, spending on {tag} was {amount} JPY."
    )

    # --- Comparison patterns ---
    FORMAT_INCREASE = (
        "{tag} was {diff} JPY higher than the previous month."
    )

    FORMAT_DECREASE = (
        "{tag} was {diff} JPY lower than the previous month."
    )

    FORMAT_NEW = (
        "{tag} did not exist in the previous month, but was {amount} JPY this month."
    )

    FORMAT_DISAPPEARED = (
        "{tag} existed in the previous month, but did not appear this month."
    )

    FORMAT_NO_CHANGE = (
        "{tag} was the same as the previous month at {amount} JPY."
    )

    # レシートタグ英語マップ
    RECEIPT_TAG_EN_MAP: dict[type_def.ReceiptTag, str] = {
        type_def.ReceiptTag.FOOD: "food",
        type_def.ReceiptTag.EAT_OUT: "eating out",
        type_def.ReceiptTag.DAILY_NECESSITIES: "daily necessities",
        type_def.ReceiptTag.MEDICAL: "medical",
        type_def.ReceiptTag.TRANSPORTATION: "transportation",
        type_def.ReceiptTag.ENTERTAINMENT: "entertainment",
        type_def.ReceiptTag.CLOTHING: "clothing",
        type_def.ReceiptTag.HOUSING: "housing",
        type_def.ReceiptTag.UTILITIES: "utilities",
        type_def.ReceiptTag.COMMUNICATION: "communication",
        type_def.ReceiptTag.EDUCATION: "education",
        type_def.ReceiptTag.WORK: "work",
        type_def.ReceiptTag.OTHER: "other",
        type_def.ReceiptTag.UNKNOWN: "unknown",
    }

    # AIタグ -> ReceiptTag マップ
    AI_TAG_TO_RECEIPT_TAG: dict[str, type_def.ReceiptTag] = {
        "Food": type_def.ReceiptTag.FOOD,
        "Eating Out": type_def.ReceiptTag.EAT_OUT,
        "Daily Necessities": type_def.ReceiptTag.DAILY_NECESSITIES,
        "Medical": type_def.ReceiptTag.MEDICAL,
        "Transportation": type_def.ReceiptTag.TRANSPORTATION,
        "Entertainment": type_def.ReceiptTag.ENTERTAINMENT,
        "Clothing": type_def.ReceiptTag.CLOTHING,
        "Housing": type_def.ReceiptTag.HOUSING,
        "Utilities": type_def.ReceiptTag.UTILITIES,
        "Communication": type_def.ReceiptTag.COMMUNICATION,
        "Education": type_def.ReceiptTag.EDUCATION,
        "Work": type_def.ReceiptTag.WORK,
        "Other": type_def.ReceiptTag.OTHER,
        "Unknown": type_def.ReceiptTag.UNKNOWN,
    }

    def __init__(
        self,
        input_dir: Path,
        error_dir: Path,
        receipt_image_exts: tuple[str, ...],
        receipt_tags_prompt: str,
        monthly_expense_summary_prompt: str,
    ) -> None:
        """
        レシートマネージャ初期化

        Args:
            input_dir (Path): レシート画像入力ディレクトリパス
            error_dir (Path): エラーディレクトリパス
            receipt_image_exts (tuple[str, ...]): レシート画像拡張子タプル
            receipt_tags_prompt (str): レシートタグ判断用システムプロンプト
            monthly_expense_summary_prompt (str): 月次支出サマリ用システムプロンプト

        Returns:
            None
        """
        # Azure Document Intelligenceクライアント初期化
        receipt_ai.init()

        # レシート画像収集
        self._receipt_images: list[Path] = receipt_store.load_receipt_image(
            input_dir=input_dir,
            error_dir=error_dir,
            receipt_image_exts=receipt_image_exts,
        )

        # 生成AIクライアント初期化
        generative_ai.init()

        self._receipt_tags_prompt: str = receipt_tags_prompt                                # レシートタグ判断用システムプロンプト
        self._input_dir = input_dir                                                         # レシート画像入力ディレクトリパス
        self._error_dir = error_dir                                                         # エラーディレクトリパス
        self._receipt_image_exts = receipt_image_exts                                       # レシート画像拡張子タプル
        self._monthly_expense_summary_prompt: str = monthly_expense_summary_prompt          # 月次支出サマリ用システムプロンプト

        log_mod.info("RECEIPT MANAGER INITIALIZED")

    def process_receipt(
        self,
        src: Path,
        *,
        invalid_filename_chars: re.Pattern[str],
        output_json_dir: Path,
        output_csv_dir: Path,
        processed_dir: Path,
        error_dir: Path
    ) -> type_def.ReceiptProcessResult:
        """
        レシート1件分の処理をまとめて実行する Facade API。

        処理内容:
            1) レシート画像を AI 解析
            2) 解析結果をパース
            3) basename 生成
            4) JSON 保存
            5) 月別 CSV 追記
            6) processed へ移動
            ※ 失敗時は error へ移動

        Args:
            src (Path): レシート画像ファイルパス
            invalid_filename_chars (re.Pattern[str]): ファイル名使用不可文字パターン
            output_json_dir (Path): JSON 出力ディレクトリ
            output_csv_dir (Path): CSV 出力ディレクトリ
            processed_dir (Path): processed ディレクトリ
            error_dir (Path): error ディレクトリ

        Returns:
            ReceiptProcessResult:
                ok=True  : 正常完了
                ok=False : 処理失敗（error_reason に理由）
        """
        log_mod.info(f"RECEIPT PROCESS START: {src.name}")

        try:
            # ==================================================
            # 解析 + パース
            # ==================================================
            analyze_result = self.analyze_and_parse(str(src))
            if not analyze_result.ok:
                receipt_store.move_to_error(src, error_dir)
                return analyze_result

            result: type_def.ReceiptResult = analyze_result.result  # type: ignore

            # ==================================================
            # AI によるタグ判定
            # ==================================================
            self._judge_receipt_tags_by_ai(result)

            # ==================================================
            # basename 生成
            # ==================================================
            receipt_id: str = receipt_store.build_base_name(
                result,
                invalid_filename_chars,
            )
            if not receipt_id:
                msg = "FAILED TO BUILD BASENAME"
                log_mod.error(msg)
                receipt_store.move_to_error(src, error_dir)
                return type_def.ReceiptProcessResult.failed(msg)

            # ==================================================
            # JSON 保存
            # ==================================================
            saved_json: Path = receipt_store.save_result_json(
                result=result,
                base=receipt_id,
                output_json_dir=output_json_dir,
            )

            # ==================================================
            # CSV 追記
            # ==================================================
            csv_path: Path = receipt_store.get_monthly_receipt_csv_path(
                result=result,
                output_csv_root=output_csv_dir,
                receipt_id=receipt_id,
            )

            rows: list[dict[str, Any]] = receipt_store.build_receipt_summary_csv_row(
                result=result,
                receipt_id=receipt_id,
                saved_json_path=saved_json,
            )

            receipt_store.append_monthly_receipt_item_csv(
                csv_path=csv_path,
                rows=rows,
            )

            # ==================================================
            # processed へ移動（ローカルのみ）
            # ==================================================
            receipt_store.move_to_processed(
                src=src,
                base=receipt_id,
                processed_dir=processed_dir,
            )

            log_mod.info(f"RECEIPT PROCESS END: {receipt_id}")
            return type_def.ReceiptProcessResult.success(result)

        except ValueError as e:
            # レシート不成立（NOT A RECEIPT など）
            log_mod.info(f"RECEIPT SKIPPED: {src.name} ({e})")
            return type_def.ReceiptProcessResult.failed(str(e))

        except Exception as e:
            log_mod.error(f"RECEIPT ANALYZE FAILED: {src.name} ({e})")
            return type_def.ReceiptProcessResult.failed(str(e))

    def analyze_and_parse(self, receipt_path: str) -> type_def.ReceiptProcessResult:
        """
        レシート画像を解析し、処理結果を ReceiptProcessResult として返却する。

        本関数は以下の責務を持つ：
            - レシート画像を AI で解析する
            - 解析結果（raw dict）を parser に委譲して構造化する
            - 成功/失敗を ProcessResult にラップする

        Args:
            receipt_path (str): レシート画像ファイルのパス

        Returns:
            ReceiptProcessResult:
                ok=True  : result に ReceiptResult が格納される
                ok=False : error_reason に失敗理由が格納される
        """
        path: Path = Path(receipt_path)

        try:
            if not path.exists():
                msg = f"RECEIPT FILE NOT FOUND: {receipt_path}"
                log_mod.error(msg)
                return type_def.ReceiptProcessResult.failed(msg)

            raw: dict[str, Any] = receipt_ai.analyze_receipt(receipt_path)

            result: type_def.ReceiptResult = receipt_parser.parse_receipt_dict(
                raw=raw,
                source_file=path.name,
            )

            return type_def.ReceiptProcessResult.success(result)

        except Exception as e:
            log_mod.error(f"RECEIPT ANALYZE FAILED: {path.name} ({e})")
            return type_def.ReceiptProcessResult.failed(str(e))

    def get_receipt_images(self) -> list[Path]:
        """
        処理対象のレシート画像ファイルパスリストを取得する。

        Args:
            None

        Returns:
            list[Path]: レシート画像ファイルパスリスト
        """
        return self._receipt_images

    def get_latest_processed_year_month(self) -> tuple[int, int] | None:
        """
        output/csv 配下を走査し、
        最も新しい「YYYYMM_items.csv」から年月を取得する。

        想定構成:
            output/csv/
                2025/202512_items.csv
                2026/202601_items.csv

        Returns:
            tuple[int, int] | None:
                (year, month) or None（対象CSVなし）
        """
        csv_root = self._input_dir.parent / "output" / "csv"

        if not csv_root.exists():
            return None

        candidates: list[tuple[int, int]] = []

        for year_dir in csv_root.iterdir():
            if not year_dir.is_dir():
                continue

            try:
                int(year_dir.name)
            except ValueError:
                continue

            for csv_file in year_dir.glob("*_items.csv"):
                m = re.match(r"(\d{6})_items\.csv", csv_file.name)
                if not m:
                    continue

                yyyymm = m.group(1)
                y = int(yyyymm[:4])
                m_ = int(yyyymm[4:6])

                candidates.append((y, m_))

        if not candidates:
            return None

        # 年月で最大（＝最新）を返す
        return max(candidates)

    def get_existing_year_months(
            self,
            output_csv_dir: Path,
    ) -> list[tuple[int, int]]:
        """
        output/csv 配下から存在する年月（YYYY, MM）一覧を取得する。

        Args:
            output_csv_dir (Path): CSV出力ルートディレクトリ

        Returns:
            list[tuple[int, int]]: [(year, month), ...]
        """
        results: set[tuple[int, int]] = set()

        if not output_csv_dir.exists():
            return []

        for year_dir in output_csv_dir.iterdir():
            if not year_dir.is_dir():
                continue

            try:
                year = int(year_dir.name)
            except ValueError:
                continue

            for csv_file in year_dir.glob("*_items.csv"):
                m = re.match(r"(\d{6})_items\.csv", csv_file.name)
                if not m:
                    continue

                yyyymm = m.group(1)
                month = int(yyyymm[4:6])
                results.add((year, month))

        return sorted(results)

    def import_from_cloud(self, cloud_inbox_dir: Path, cloud_error_dir: Path,) -> int:
        """
        クラウド受信箱からレシート画像を input ディレクトリへ取り込む。

        Args:
            cloud_inbox_dir (Path): クラウド同期済みの受信箱ディレクトリ
            cloud_error_dir (Path): クラウド同期済みの error ディレクトリ

        Returns:
            int: 取り込んだファイル数
        """
        return receipt_store.import_from_cloud(
            cloud_inbox_dir=cloud_inbox_dir,
            cloud_error_dir=cloud_error_dir,
            input_dir=self._input_dir,
        )

    def reload_receipt_images(self) -> None:
        """
        input ディレクトリを再走査し、処理対象レシート画像一覧を更新する。

        Args:
            None

        Returns:
            None
        """
        log_mod.info("RELOAD RECEIPT IMAGES")
        self._receipt_images = receipt_store.load_receipt_image(
            input_dir=self._input_dir,
            error_dir=self._error_dir,
            receipt_image_exts=self._receipt_image_exts,
        )

    def generate_monthly_graph(
        self,
        *,
        year: int,
        month: int,
        output_csv_dir: Path,
        output_graph_dir: Path,
    ) -> Path:
        """
        指定した年月のカテゴリー別支出グラフを生成する。

        Args:
            year (int): 年（YYYY）
            month (int): 月（1-12）
            output_csv_dir (Path): CSV出力ルートディレクトリ
            output_graph_dir (Path): グラフ出力ルートディレクトリ

        Returns:
            Path: 生成したグラフPNGのパス
        """
        log_mod.info(f"GENERATE MONTHLY GRAPH START: {year}-{month:02d}")

        graph_path = receipt_grapher.generate_monthly_category_bar_graph(
            csv_root=output_csv_dir,
            graph_root=output_graph_dir,
            year=year,
            month=month,
        )

        log_mod.info(f"GENERATE MONTHLY GRAPH END: {graph_path.name}")
        return graph_path

    def generate_annual_graph(
        self,
        *,
        year: int,
        output_csv_dir: Path,
        output_graph_dir: Path,
    ) -> Path:
        """
        指定した年のカテゴリー別「年間支出グラフ」を生成する。

        - output/csv/YYYY 配下に存在する月別CSVをすべて集計する
        - 1〜12月が揃っていなくても、存在するCSVのみで作成する

        Args:
            year (int): 年（YYYY）
            output_csv_dir (Path): CSV出力ルートディレクトリ
            output_graph_dir (Path): グラフ出力ルートディレクトリ

        Returns:
            Path: 生成したグラフPNGのパス
        """
        log_mod.info(f"GENERATE ANNUAL GRAPH START: {year}")

        graph_path = receipt_grapher.generate_annual_category_bar_graph(
            csv_root=output_csv_dir,
            graph_root=output_graph_dir,
            year=year,
        )

        log_mod.info(f"GENERATE ANNUAL GRAPH END: {graph_path.name}")
        return graph_path

    def generate_monthly_ai_summary(
        self,
        *,
        year: int,
        month: int,
        output_csv_dir: Path,
        output_summary_dir: Path
    ) -> str:
        """
        指定した年月の月次支出AIサマリーを生成する。

        Args:
            year (int): 年
            month (int): 月
            output_csv_dir (Path): CSV出力ルートディレクトリ
            output_summary_dir (Path): サマリー出力ディレクトリ

        Returns:
            str: AI生成サマリー（失敗時は空文字）
        """
        log_mod.info(f"GENERATE MONTHLY AI SUMMARY START: {year}-{month:02d}")

        try:
            # ---- 集計 ----
            current_totals = self._aggregate_monthly_csv(
                year=year,
                month=month,
                output_csv_dir=output_csv_dir,
            )

            if not current_totals:
                log_mod.info("NO DATA FOR CURRENT MONTH SUMMARY")
                return ""

            prev_year, prev_month = self._get_previous_year_month(year, month)
            prev_totals = self._aggregate_monthly_csv(
                year=prev_year,
                month=prev_month,
                output_csv_dir=output_csv_dir,
            )

            # ---- user_prompt 作成（英語）----
            user_prompt = self._build_monthly_comparison_user_prompt(
                year=year,
                month=month,
                current_totals=current_totals,
                prev_year=prev_year,
                prev_month=prev_month,
                prev_totals=prev_totals,
            )

            log_mod.debug(f"MONTHLY AI SUMMARY USER PROMPT:\n{user_prompt}")

            # ---- AI 呼び出し ----
            response = generative_ai.request_generative_ai(
                system_prompt=self._monthly_expense_summary_prompt,
                user_prompt=user_prompt,
            )

            raw_content = response.content.strip()

            # ---- JSONパース ----
            try:
                summary_json = json.loads(raw_content)
            except json.JSONDecodeError as e:
                log_mod.error(f"FAILED TO PARSE AI SUMMARY JSON: ({e})")
                log_mod.error(f"RAW AI RESPONSE:\n{raw_content}")
                return ""

            # ---- 必須キー取得（安全）----
            monthly_summary = summary_json.get("monthly_summary", "")
            monthly_characteristics = summary_json.get("monthly_characteristics", "")
            positive_points = summary_json.get("positive_points", "")
            advice_for_next_month = summary_json.get("advice_for_next_month", "")

            # ---- 保存用テキスト整形（人が読む用）----
            summary_text = (
                f"今月の総評: {monthly_summary}\n"
                f"今月の特徴: {monthly_characteristics}\n"
                f"良かった点: {positive_points}\n"
                f"来月のアドバイス: {advice_for_next_month}"
            )

            # ---- summary ファイル保存 ----
            year_dir = output_summary_dir / f"{year}"
            year_dir.mkdir(parents=True, exist_ok=True)

            summary_path = year_dir / f"{year}{month:02d}_summary.txt"
            summary_path.write_text(summary_text, encoding="utf-8")

            log_mod.info(f"MONTHLY SUMMARY SAVED: {summary_path}")

            return summary_text

        except Exception as e:
            log_mod.error(f"FAILED TO GENERATE MONTHLY AI SUMMARY: ({e})")
            return ""

    # ==================================================
    # Private Methods（AIタグ判定用）
    # ==================================================
    def _judge_receipt_tags_by_ai(
        self,
        result: type_def.ReceiptResult,
    ) -> None:
        """
        レシート解析結果(JSON)を生成AIに渡し、
        商品ごとにタグ判定を行う。

        - 判定対象は result.items
        - 各 item に対して tag / tag_reason を1つずつ設定する
        - 判定不能な場合は UNKNOWN を設定する

        Args:
            result (ReceiptResult): パース済みレシート解析結果

        Returns:
            None
        """
        try:
            # ------------------------------
            # user_prompt 作成
            # ------------------------------
            user_prompt: str = json.dumps(
                {
                    "items": [
                        {
                            "name": item.name,
                            "total_price": item.total_price_yen,
                            "unit_price": item.unit_price_yen,
                            "quantity": item.quantity,
                        }
                        for item in result.items
                    ]
                },
                ensure_ascii=False,
                indent=2,
            )

            # ------------------------------
            # AI 呼び出し
            # ------------------------------
            response: generative_ai.GenerativeAIResponse = (
                generative_ai.request_generative_ai(
                    system_prompt=self._receipt_tags_prompt,
                    user_prompt=user_prompt,
                )
            )

            raw_content = response.content.strip()

            # ------------------------------
            # JSON パース
            # ------------------------------
            try:
                parsed = json.loads(raw_content)
            except json.JSONDecodeError as e:
                raise ValueError(f"FAILED TO PARSE TAGGING JSON: {e}")

            ai_items = parsed.get("items")
            if not isinstance(ai_items, list):
                raise ValueError("AI RESPONSE DOES NOT CONTAIN 'items' ARRAY")

            # ------------------------------
            # 件数チェック（最重要）
            # ------------------------------
            if len(ai_items) != len(result.items):
                raise ValueError(
                    f"ITEM COUNT MISMATCH: input={len(result.items)}, output={len(ai_items)}"
                )

            # ------------------------------
            # name -> ReceiptItem マップ
            # ------------------------------
            item_map = {item.name: item for item in result.items}

            # ------------------------------
            # タグ反映
            # ------------------------------
            for ai_item in ai_items:
                name = ai_item.get("name", "")
                tag_raw = ai_item.get("tag", "")
                reason = ai_item.get("reason", "")

                item = item_map.get(name)
                if not item:
                    log_mod.error(f"UNKNOWN ITEM NAME FROM AI: {name}")
                    continue

                # タグ変換(AIタグ -> ReceiptTag)
                tag_enum = self.AI_TAG_TO_RECEIPT_TAG.get(tag_raw)
                if tag_enum is None:
                    log_mod.error(f"UNKNOWN AI TAG: {tag_raw}")
                    item.tag = type_def.ReceiptTag.UNKNOWN
                else:
                    item.tag = tag_enum

                item.tag_reason = reason or ""

            log_mod.debug(
                "ITEM TAGGING RESULT: "
                + ", ".join(
                    f"{i.name}={i.tag.value if i.tag else 'None'}"
                    for i in result.items
                )
            )

        except Exception as e:
            log_mod.error(f"ITEM TAGGING FAILED: ({e})")

            # フェイルセーフ：全 UNKNOWN
            for item in result.items:
                item.tag = type_def.ReceiptTag.UNKNOWN
                item.tag_reason = ""

    def _build_monthly_comparison_user_prompt(
        self,
        *,
        year: int,
        month: int,
        current_totals: dict[str, int],
        prev_year: int,
        prev_month: int,
        prev_totals: dict[str, int],
    ) -> str:
        """
        今月と前月の支出情報から、英語の自然文 user_prompt を生成する。

        Returns:
            str: user_prompt
        """
        lines: list[str] = []

        # ---- This Month ----
        lines.append(f"[This Month ({year}-{month:02d})]")
        lines.extend(
            self._build_current_month_lines(
                year=year,
                month=month,
                current_totals=current_totals,
            )
        )

        # ---- Comparison ----
        comparison_lines = self._build_monthly_comparison_lines(
            current_totals=current_totals,
            prev_totals=prev_totals,
        )

        if comparison_lines:
            lines.append("")
            lines.append(f"[Comparison with Previous Month ({prev_year}-{prev_month:02d})]")
            lines.extend(comparison_lines)

        return "\n".join(lines)

    def _aggregate_monthly_csv(
        self,
        *,
        year: int,
        month: int,
        output_csv_dir: Path,
    ) -> dict[str, int]:
        """
        月次CSVからカテゴリ別支出額を集計する。

        Args:
            year (int): 年
            month (int): 月
            output_csv_dir (Path): CSV出力ルートディレクトリ

        Returns:
            dict[str, int]: {category: total_amount}
        """
        csv_path = (
            output_csv_dir
            / f"{year}"
            / f"{year}{month:02d}_items.csv"
        )

        if not csv_path.exists():
            return {}

        totals: dict[str, int] = {}

        with csv_path.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)

            for row in reader:
                tag = row.get("item_tag")
                price_raw = row.get("total_price_yen")

                if not tag or not price_raw:
                    continue

                try:
                    price = int(price_raw)
                except ValueError:
                    continue

                totals[tag] = totals.get(tag, 0) + price

        return totals

    def _get_previous_year_month(self, year: int, month: int) -> tuple[int, int]:
        """
        指定した年月の前月を返す。

        Args:
            year (int): 年
            month (int): 月

        Returns:
            tuple[int, int]: (prev_year, prev_month)
        """
        if month == 1:
            return year - 1, 12
        return year, month - 1

    def _build_current_month_lines(
        self,
        *,
        year: int,
        month: int,
        current_totals: dict[str, int],
    ) -> list[str]:
        """
        今月の支出一覧文を生成する。

        Args:
            year (int): 年
            month (int): 月
            current_totals (dict[str, int]): {category: total_amount}

        Returns:
            list[str]: 支出一覧文行リスト
        """
        lines: list[str] = []

        for tag, amount in sorted(current_totals.items()):
            if amount <= 0:
                continue

            lines.append(
                self.FORMAT_CURRENT_MONTH.format(
                    year=year,
                    month=month,
                    tag=self._tag_to_en(tag),
                    amount=amount,
                )
            )

        return lines

    def _build_monthly_comparison_lines(
        self,
        *,
        current_totals: dict[str, int],
        prev_totals: dict[str, int],
    ) -> list[str]:
        """
        今月と先月の支出を比較し、5パターンの比較文を生成する。

        Args:
            current_totals (dict[str, int]): 今月の {category: total_amount}
            prev_totals (dict[str, int]): 先月の {category: total_amount}

        Returns:
            list[str]: 比較文行リスト
        """
        lines: list[str] = []

        all_tags = set(current_totals.keys()) | set(prev_totals.keys())

        for tag in sorted(all_tags):
            current = current_totals.get(tag, 0)
            prev = prev_totals.get(tag, 0)

            # 両方0円は出さない
            if current == 0 and prev == 0:
                continue

            # ここで英語タグに変換
            tag_en = self._tag_to_en(tag)

            # ① 今月 > 先月（増加）
            if current > prev:
                if prev == 0:
                    lines.append(
                        self.FORMAT_NEW.format(
                            tag=tag_en,
                            amount=current,
                        )
                    )
                else:
                    lines.append(
                        self.FORMAT_INCREASE.format(
                            tag=tag_en,
                            diff=current - prev,
                        )
                    )

            # ② 今月 < 先月（減少）
            elif current < prev:
                if current == 0:
                    lines.append(
                        self.FORMAT_DISAPPEARED.format(
                            tag=tag_en,
                        )
                    )
                else:
                    lines.append(
                        self.FORMAT_DECREASE.format(
                            tag=tag_en,
                            diff=prev - current,
                        )
                    )

            # ⑤ 今月 = 先月（変化なし）
            else:
                lines.append(
                    self.FORMAT_NO_CHANGE.format(
                        tag=tag_en,
                        amount=current,
                    )
                )

        return lines

    def _tag_to_en(self, tag: str) -> str:
        """
        日本語タグ文字列を英語表現に変換する（AI用）

        Args:
            tag (str): 日本語タグ文字列

        Returns:
            str: 英語タグ文字列
        """
        try:
            tag_enum = type_def.ReceiptTag(tag)
        except ValueError:
            return "unknown"

        return self.RECEIPT_TAG_EN_MAP.get(tag_enum, "unknown")
