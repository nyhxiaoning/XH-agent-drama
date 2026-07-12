# 星河 (XingHe) — AI 漫剧创作平台

基于 AI 的短剧/漫剧创作平台，内置 3D 导演台、画布节点编辑器、AI 图像/视频生成流水线。

## ✨ 核心功能

- **3D 导演台**：3D 场景搭建、多机位管理、运镜预设、影视级参数控制
- **画布编辑器**：节点式创作流程，支持图像生成、视频生成、预设等节点类型
- **AI 生成**：可自定义接入多模型，支持图像生成、视频生成
- **Prompt 模板引擎**：可自定义模板，自动注入景别/焦距/运镜/角色/场景/台词等变量
- **一键启动**：Windows 双击 `start.bat` 即可运行，自动安装依赖、生成配置

- **感谢极光大佬开源的3D导演台功能：https://github.com/jiguang132/storyai-3d-director-desk

<img width="1896" height="822" alt="image" src="https://github.com/user-attachments/assets/bdfb7de1-6ae4-469d-9944-abeefe0f0de7" />

<img width="1920" height="810" alt="image" src="https://github.com/user-attachments/assets/2969f791-c80c-49cc-bdb3-9d389ce47ba8" />
<img width="1884" height="709" alt="image" src="https://github.com/user-attachments/assets/40b8d694-ffcb-4834-8b78-11f679b31792" />
<img width="1604" height="889" alt="image" src="https://github.com/user-attachments/assets/754c332b-1920-42ee-95ac-65624d4e8547" />

<img width="1596" height="904" alt="image" src="https://github.com/user-attachments/assets/e8bac020-e26b-450a-96d5-2a41a47281e6" />

<img width="1555" height="917" alt="image" src="https://github.com/user-attachments/assets/7925d911-048a-4176-9eff-a3500952958f" />










## 🚀 快速开始（本地开发）

### 环境要求

- Python 3.10+
- Node.js 18+
- npm 9+

### Windows 一键启动

```bash
# 双击运行
start.bat
```

脚本会自动完成：
1. 生成 `.env` 配置模板（默认 SQLite，零配置）
2. 创建 Python 虚拟环境
3. 安装后端依赖
4. 启动后端服务 (http://localhost:8000)
5. 启动前端服务 (http://localhost:5173)
6. 自动打开浏览器

### 手动启动

#### 后端

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
# Linux/Mac
source .venv/bin/activate

cp .env.example .env  # 编辑配置
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

#### 前端

```bash
cd frontend
cp .env.example .env
npm install
npm run dev
```

## 📁 项目结构

```
├── backend/              # FastAPI 后端
│   ├── app/
│   │   ├── api/          # API 路由
│   │   ├── core/         # 配置、安全、数据库
│   │   ├── crud/         # 数据库操作
│   │   ├── models/       # SQLAlchemy 模型
│   │   ├── schemas/      # Pydantic 模型
│   │   ├── services/     # 业务逻辑
│   │   ├── workers/      # AI 任务处理
│   │   └── main.py       # 应用入口
│   ├── requirements.txt
│   └── .env.example
├── frontend/             # React + Vite 前端
│   ├── src/
│   │   ├── components/   # 通用组件
│   │   ├── director-desk/# 3D 导演台
│   │   ├── pages/        # 页面
│   │   ├── store/        # Zustand 状态管理
│   │   └── utils/        # 工具函数
│   ├── package.json
│   └── .env.example
├── deploy/               # 部署脚本
├── start.bat             # Windows 一键启动
└── .gitignore
```

## ⚙️ 配置说明

编辑 `backend/.env` 配置 AI 模型和存储：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `DATABASE_URL` | 数据库连接 | `sqlite:///./xiaoyunque.db` |
| `TENCENT_COS_*` | 腾讯云 COS（留空则用本地存储） | 空 |
| `DASHSCOPE_API_KEY` | 阿里云 DashScope API Key | 空 |
| `VOLCENGINE_ARK_API_KEY` | 火山引擎 Ark API Key | 空 |
| `ADMIN_EMAIL` / `ADMIN_PASSWORD` | 管理员账号（首次启动自动创建） | `admin@xinghe.com` / `admin123456` |

## 📄 License

MIT License
