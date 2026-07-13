@echo off
chcp 65001 >nul
cd /d "%~dp0"
setlocal enabledelayedexpansion

echo ========================================
echo   星河 AI 短剧平台一键启动
echo ========================================
echo.

REM ===== 第1步：自动生成 .env 配置文件 =====
echo [1/6] 检查环境配置文件...

if not exist "backend\.env" (
    echo   backend .env not found, generating template...
    > "backend\.env" (
        echo # ========================= Base Config =========================
        echo # Default: SQLite (no extra database needed)
        echo # For PostgreSQL, uncomment and edit:
        echo # DATABASE_URL=postgresql://postgres:password@localhost:5432/xiaoyunque
        echo DATABASE_URL=sqlite:///./xiaoyunque.db
        echo DEBUG=true
        echo API_V1_PREFIX=/api/v1
        echo PROJECT_NAME=XingHe
        echo # JWT secret: change to random string in production
        echo SECRET_KEY=your-secret-key-change-in-production
        echo.
        echo # Public URL for local dev
        echo PUBLIC_BASE_URL=http://localhost:8000
        echo.
        echo # ========================= Tencent COS =========================
        echo # Leave empty to use local disk storage
        echo TENCENT_COS_SECRET_ID=
        echo TENCENT_COS_SECRET_KEY=
        echo TENCENT_COS_BUCKET=
        echo TENCENT_COS_REGION=
        echo.
        echo # ========================= DashScope (Aliyun) =========================
        echo DASHSCOPE_API_BASE_URL=
        echo DASHSCOPE_API_KEY=
        echo.
        echo # ========================= Volcengine Ark =========================
        echo VOLCENGINE_ARK_API_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
        echo VOLCENGINE_ARK_API_KEY=
        echo VOLCENGINE_ARK_MODEL_ID_STANDARD=
        echo VOLCENGINE_ARK_MODEL_ID_FAST=
        echo.
        echo # ========================= 91API =========================
        echo # Leave empty for mock demo data
        echo API91_BASE_URL=https://yunwu.ai
        echo API91_API_KEY=
        echo.
        echo # ========================= Model Config =========================
        echo # LLM model names are managed by database + code, NOT .env
        echo # .env only controls API provider and keys
        echo LLM_PROVIDER=api91
        echo IMAGE_MODEL_GPT_IMAGE_2=gpt-image-2
        echo IMAGE_MODEL_GEMINI_FLASH_IMAGE=gemini-3.1-flash-lite-image
        echo.
        echo # ========================= SMS (optional) =========================
        echo ALIYUN_SMS_ACCESS_KEY_ID=
        echo ALIYUN_SMS_ACCESS_KEY_SECRET=
        echo ALIYUN_SMS_SIGN_NAME=
        echo ALIYUN_SMS_TEMPLATE_CODE=
        echo.
        echo # ========================= Turnstile (optional) =========================
        echo TURNSTILE_SECRET_KEY=
        echo.
        echo # ========================= Admin Account =========================
        echo # Auto-created on first startup if no admin exists
        echo ADMIN_EMAIL=admin@xinghe.com
        echo ADMIN_PASSWORD=admin123456
    )
    echo   v backend .env template generated (SQLite default, zero config)
) else (
    echo   v backend .env exists
)

if not exist "frontend\.env" (
    echo   frontend .env not found, generating template...
    > "frontend\.env" (
        echo # Cloudflare Turnstile Site Key (public, leave empty to skip)
        echo VITE_TURNSTILE_SITE_KEY=
    )
    echo   v frontend .env template generated
) else (
    echo   v frontend .env exists
)
echo.

REM ===== 第2步：后端虚拟环境 =====
echo [2/6] 检查后端虚拟环境...
if not exist "backend\.venv\Scripts\activate.bat" (
    echo   虚拟环境不存在，正在创建...
    cd /d backend
    python -m venv .venv
    cd /d "%~dp0"
    echo   √ 虚拟环境创建完成
) else (
    echo   √ 虚拟环境已存在
)
echo.

REM ===== 第3步：安装后端依赖 =====
echo [3/6] 安装后端依赖...
cd /d backend
call .venv\Scripts\activate.bat
pip install -r requirements.txt -q
echo   √ 后端依赖安装完成
echo.

REM ===== 第4步：启动后端服务 =====
echo [4/6] 启动后端服务 (http://localhost:8000)...
start "星河后端" cmd /k "cd /d %~dp0backend && call .venv\Scripts\activate.bat && echo ======================================== && echo   星河后端服务启动中... && echo   API文档: http://localhost:8000/docs && echo ======================================== && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"
cd /d "%~dp0"
echo   √ 后端服务已启动
echo.

REM ===== 第5步：启动前端服务 =====
echo [5/6] 启动前端服务 (http://localhost:5173)...
cd /d frontend
if not exist node_modules (
    echo   node_modules 不存在，正在安装前端依赖...
    call npm install
    echo   √ 前端依赖安装完成
)
start "星河前端" cmd /k "cd /d %~dp0frontend && echo ======================================== && echo   星河前端服务启动中... && echo   访问地址: http://localhost:5173 && echo ======================================== && npm run dev"
cd /d "%~dp0"
echo   √ 前端服务已启动
echo.

REM ===== 第6步：等待服务就绪并打开浏览器 =====
echo [6/6] 等待服务就绪...
echo   正在等待后端启动...
set BACKEND_READY=0
for /l %%i in (1,1,30) do (
    if !BACKEND_READY! equ 0 (
        timeout /t 1 >nul
        curl -s -o nul http://localhost:8000/health 2>nul
        if !errorlevel! equ 0 (
            set BACKEND_READY=1
            echo   √ 后端已就绪
        ) else (
            echo   等待后端启动... %%i/30
        )
    )
)
echo   正在等待前端启动...
timeout /t 3 >nul
echo   √ 前端已就绪
echo.

echo ========================================
echo   全部启动完成！正在打开浏览器...
echo   后端: http://localhost:8000
echo   前端: http://localhost:5173
echo ========================================

start "" "http://localhost:5173"

echo.
echo   浏览器已打开，如未自动打开请手动访问 http://localhost:5173
echo.
echo   提示: 首次启动已自动生成 .env 配置文件
echo   如需配置 AI API 密钥，请编辑 backend/.env 后重启
echo.
pause
