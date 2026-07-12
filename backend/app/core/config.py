from pydantic_settings import BaseSettings
from dotenv import load_dotenv
import os

load_dotenv()


class Settings(BaseSettings):
    PROJECT_NAME: str = os.getenv("PROJECT_NAME", "小云雀后端")
    API_V1_PREFIX: str = os.getenv("API_V1_PREFIX", "/api/v1")
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "sqlite:///./xiaoyunque.db"
    )
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")

    # 腾讯云 COS 配置
    TENCENT_COS_SECRET_ID: str = os.getenv("TENCENT_COS_SECRET_ID", "")
    TENCENT_COS_SECRET_KEY: str = os.getenv("TENCENT_COS_SECRET_KEY", "")
    TENCENT_COS_BUCKET: str = os.getenv("TENCENT_COS_BUCKET", "")
    TENCENT_COS_REGION: str = os.getenv("TENCENT_COS_REGION", "")

    # 阿里云百炼（DashScope）配置
    DASHSCOPE_API_BASE_URL: str = os.getenv(
        "DASHSCOPE_API_BASE_URL", "https://dashscope.aliyuncs.com/api/v1"
    )
    DASHSCOPE_API_KEY: str = os.getenv("DASHSCOPE_API_KEY", "")

    # 火山引擎 Ark 配置
    VOLCENGINE_ARK_API_BASE_URL: str = os.getenv(
        "VOLCENGINE_ARK_API_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"
    )
    VOLCENGINE_ARK_API_KEY: str = os.getenv("VOLCENGINE_ARK_API_KEY", "")
    VOLCENGINE_ARK_MODEL_ID_STANDARD: str = os.getenv(
        "VOLCENGINE_ARK_MODEL_ID_STANDARD", "doubao-seedance-2-0-260128"
    )
    VOLCENGINE_ARK_MODEL_ID_FAST: str = os.getenv(
        "VOLCENGINE_ARK_MODEL_ID_FAST", "doubao-seedance-2-0-fast-260128"
    )

    # 91API 配置（gpt-image-2 / gemini 图片通道）
    API91_BASE_URL: str = os.getenv("API91_BASE_URL", "https://api.91api.com")
    API91_API_KEY: str = os.getenv("API91_API_KEY", "")

    # Modelink 配置（Vidu Q3 Turbo 等视频模型）
    MODELINK_API_BASE_URL: str = os.getenv(
        "MODELINK_API_BASE_URL", "https://api.qnaigc.com"
    )
    MODELINK_API_KEY: str = os.getenv("MODELINK_API_KEY", "")
    MODELINK_VIDEO_MODEL_ID: str = os.getenv(
        "MODELINK_VIDEO_MODEL_ID", "viduq3-turbo"
    )

    # 默认 LLM 与图片模型
    LLM_MODEL_NAME: str = os.getenv("LLM_MODEL_NAME", "gpt-5.6-terra")
    # LLM 提供商：ark（火山方舟）或 api91（91API）
    LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "ark")
    IMAGE_MODEL_GPT_IMAGE_2: str = os.getenv("IMAGE_MODEL_GPT_IMAGE_2", "gpt-image-2")
    IMAGE_MODEL_GEMINI_FLASH_IMAGE: str = os.getenv(
        "IMAGE_MODEL_GEMINI_FLASH_IMAGE", "gemini-3.1-flash-lite-image"
    )
    # 豆包 Seedream 文生图模型（火山方舟 Ark API /api/v3/images/generations）
    IMAGE_MODEL_DOUBAO_SEEDREAM: str = os.getenv(
        "IMAGE_MODEL_DOUBAO_SEEDREAM", "doubao-seedream-5-0-pro-260628"
    )

    # 服务公网地址，用于把 /uploads 本地相对地址转成绝对 URL
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "http://localhost:8000")

    # 支付配置
    ALIPAY_APP_ID: str = os.getenv("ALIPAY_APP_ID", "")
    ALIPAY_PRIVATE_KEY: str = os.getenv("ALIPAY_PRIVATE_KEY", "")
    ALIPAY_PUBLIC_KEY: str = os.getenv("ALIPAY_PUBLIC_KEY", "")
    ALIPAY_NOTIFY_URL: str = os.getenv("ALIPAY_NOTIFY_URL", "")
    ALIPAY_RETURN_URL: str = os.getenv("ALIPAY_RETURN_URL", "")
    ALIPAY_GATEWAY: str = os.getenv("ALIPAY_GATEWAY", "")
    ALIPAY_DEBUG: bool = os.getenv("ALIPAY_DEBUG", "false").lower() == "true"

    WECHAT_APP_ID: str = os.getenv("WECHAT_APP_ID", "")
    WECHAT_MCH_ID: str = os.getenv("WECHAT_MCH_ID", "")
    WECHAT_API_V3_KEY: str = os.getenv("WECHAT_API_V3_KEY", "")
    WECHAT_CERT_SERIAL_NO: str = os.getenv("WECHAT_CERT_SERIAL_NO", "") or os.getenv("WECHAT_MCH_SERIAL", "")
    WECHAT_PRIVATE_KEY: str = os.getenv("WECHAT_PRIVATE_KEY", "") or os.getenv("WECHAT_MCH_KEY", "")
    WECHAT_NOTIFY_URL: str = os.getenv("WECHAT_NOTIFY_URL", "")

    # 阿里云短信配置
    ALIYUN_SMS_ACCESS_KEY_ID: str = os.getenv("ALIYUN_SMS_ACCESS_KEY_ID", "")
    ALIYUN_SMS_ACCESS_KEY_SECRET: str = os.getenv("ALIYUN_SMS_ACCESS_KEY_SECRET", "")
    ALIYUN_SMS_SIGN_NAME: str = os.getenv("ALIYUN_SMS_SIGN_NAME", "")
    ALIYUN_SMS_TEMPLATE_CODE: str = os.getenv("ALIYUN_SMS_TEMPLATE_CODE", "")

    # Cloudflare Turnstile 人机验证
    TURNSTILE_SECRET_KEY: str = os.getenv("TURNSTILE_SECRET_KEY", "")

    # CORS 配置：逗号分隔的域名列表，留空则开发模式回退到 localhost
    CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")

    # Agent / Task 重试次数（LLM 偶发抖动时可调高）
    DRAMA_BRAIN_MAX_RETRIES: int = int(os.getenv("DRAMA_BRAIN_MAX_RETRIES", "3"))
    TASK_MAX_RETRIES: int = int(os.getenv("TASK_MAX_RETRIES", "2"))

    # P7: Token 预算管控
    LLM_TOKEN_BUDGET_PER_SESSION: int = int(os.getenv("LLM_TOKEN_BUDGET_PER_SESSION", "50000"))
    LLM_TOKEN_BUDGET_HARD_LIMIT: int = int(os.getenv("LLM_TOKEN_BUDGET_HARD_LIMIT", "200000"))

    # P5: WebSocket 心跳间隔（秒）
    WS_HEARTBEAT_INTERVAL: int = int(os.getenv("WS_HEARTBEAT_INTERVAL", "30"))

    # 内存缓存（memory_cache）配置
    MEMORY_CACHE_MAX_SIZE: int = int(os.getenv("MEMORY_CACHE_MAX_SIZE", "500"))
    MEMORY_CACHE_TTL: int = int(os.getenv("MEMORY_CACHE_TTL", "1800"))

    # ── #6 模型分级策略 ──────────────────────────────
    # 轻量模型：路由决策、参数提取、简单审核（快速、低成本）
    LLM_MODEL_LITE: str = os.getenv("LLM_MODEL_LITE", "gpt-5.6-terra")
    # 标准模型：质检审核、中等复杂度任务
    LLM_MODEL_STANDARD: str = os.getenv("LLM_MODEL_STANDARD", "gpt-5.6-terra")
    # 旗舰模型：剧本创作、分镜设计等高复杂度创意任务
    LLM_MODEL_CREATIVE: str = os.getenv("LLM_MODEL_CREATIVE", "gpt-5.6-terra")

    # ── #8 动态并发控制 ──────────────────────────────
    # 全局 LLM 并发上限（同时进行的 LLM HTTP 请求）
    LLM_MAX_CONCURRENCY: int = int(os.getenv("LLM_MAX_CONCURRENCY", "5"))
    # 每分钟最大请求数（RPM 限制，0=不限制）
    LLM_RPM_LIMIT: int = int(os.getenv("LLM_RPM_LIMIT", "0"))
    # 每分钟最大 token 数（TPM 限制，0=不限制）
    LLM_TPM_LIMIT: int = int(os.getenv("LLM_TPM_LIMIT", "0"))

    # ── #3 跨会话记忆系统 ────────────────────────────
    # 记忆向量库存储路径
    MEMORY_STORE_PATH: str = os.getenv("MEMORY_STORE_PATH", "./data/memory_store")
    # 记忆检索 top-k
    MEMORY_RETRIEVE_TOP_K: int = int(os.getenv("MEMORY_RETRIEVE_TOP_K", "5"))

    class Config:
        case_sensitive = True


settings = Settings()


# ── 启动时安全校验 ──────────────────────────────────────────
_INSECURE_KEYS = {"", "change-me-in-production", "secret", "your-secret-key"}
if not settings.DEBUG and settings.SECRET_KEY in _INSECURE_KEYS:
    raise RuntimeError(
        "[config] 生产环境（DEBUG=false）必须设置 SECRET_KEY 环境变量，"
        "当前使用的是不安全的默认值。"
    )
if not settings.SECRET_KEY:
    # 开发模式下也生成一个临时密钥并警告
    import secrets as _secrets
    settings.SECRET_KEY = "dev-only-" + _secrets.token_hex(32)
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "[config] SECRET_KEY 未设置，已生成临时开发密钥。生产环境必须通过环境变量配置。"
    )

# CORS 默认回退源（开发模式）
_DEV_CORS_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:5174",
    "http://localhost:3000",
    "http://127.0.0.1:5173",
    "http://127.0.0.1:3000",
]
