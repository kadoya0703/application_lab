"""
初回作成日：2025/12/28
ファイル名：generative_ai.py
"""
import os
import time
from dotenv import load_dotenv
from openai import AzureOpenAI, APIError, APITimeoutError
from ..tool import logger_module as log_mod


# ==================================================
# グローバル変数定義
# ==================================================
client: AzureOpenAI = None      # 生成AIクライアント
model: str = 'gpt-4.1'          # 使用するモデル名


class GenerativeAIResponse:
    """生成AIからのレスポンスを格納するクラス"""
    def __init__(self, content: str = '', error_msg: str = '') -> None:
        """
        GenerativeAIResponseコンストラクタ

        Args:
            content (str): 生成AIからの応答内容
            error_msg (str): エラーメッセージ

        Returns:
            None
        """
        self.content: str = content
        self.error_msg: str = error_msg


def init() -> None:
    """
    生成AIクライアントの初期化

    Args:
        None

    Returns:
        None
    """
    global client

    # .envファイルの内容を環境変数として読み込む
    load_dotenv()

    # 環境変数から値を取得
    AZURE_ENDPOINT = os.getenv("AZURE_ENDPOINT")
    AZURE_API_KEY = os.getenv("AZURE_API_KEY")

    client = AzureOpenAI(
        api_version="2024-12-01-preview",
        azure_endpoint=AZURE_ENDPOINT,
        api_key=AZURE_API_KEY,
    )

    log_mod.info("GENERATIVE AI INITIALIZED")


def request_generative_ai(
        *,
        system_prompt: str = 'あなたは有能なアシスタントです。',
        user_prompt: str = ''
) -> GenerativeAIResponse:
    """
    生成AIにリクエストを送信する

    Args:
        system_prompt (str): システムプロンプト
        user_prompt (str): ユーザープロンプト

    Returns:
        GenerativeAIResponse: 生成AIからのレスポンスを格納(クラス)
    """
    global client
    global model

    response: GenerativeAIResponse = GenerativeAIResponse()
    log_mod.debug('SYSTEM PROMPT: ' + system_prompt)
    log_mod.debug('USER PROMPT: ' + user_prompt)
    messages: list[dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt}
    ]

    try:
        log_mod.info('REQUEST TO GENERATIVE AI')
        start_time: float = time.perf_counter()
        result = client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=1024,
            temperature=0.7,
        )

        ai_content: str = result.choices[0].message.content

        if not ai_content:
            log_mod.error('EMPTY RESPONSE FROM GENERATIVE AI')
            response.error_msg = 'EMPTY_RESPONSE_FROM_GENERATIVE_AI'
        elif ai_content.strip() == '':
            log_mod.error('BLANK RESPONSE FROM GENERATIVE AI')
            response.error_msg = 'BLANK_RESPONSE_FROM_GENERATIVE_AI'
        else:
            log_mod.info('RECEIVED RESPONSE FROM GENERATIVE AI')
            response.content = ai_content
            log_mod.debug('AI RESPONSE CONTENT: ' + ai_content)
            end_time: float = time.perf_counter()
            log_mod.debug(f'Time to receive response from Generative AI: {end_time - start_time} seconds.')

    except APITimeoutError as e:
        log_mod.info('API TIMEOUT ERROR')
        log_mod.error('error message:', str(e))
        response.error_msg = 'API_TIMEOUT_ERROR'

    except APIError as e:
        log_mod.info('API ERROR')
        log_mod.error('error message:', str(e))
        response.error_msg = 'API_ERROR'

    except Exception as e:
        log_mod.info('UNEXPECTED ERROR')
        log_mod.error('error message:', str(e))
        response.error_msg = 'UNEXPECTED_ERROR'

    return response
