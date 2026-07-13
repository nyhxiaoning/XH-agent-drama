"""
列出 API 服务商支持的模型列表。

用法：
    cd backend
    python3 test_models.py
"""
import json
import os
import urllib.request
import urllib.error


def parse_env():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if not os.path.exists(env_path):
        return
    with open(env_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if value and value not in os.environ:
                    os.environ[key] = value


def main():
    parse_env()

    base_url = os.getenv("API91_BASE_URL", "").strip()
    api_key = os.getenv("API91_API_KEY", "").strip()
    provider = os.getenv("LLM_PROVIDER", "ark").strip().lower()

    if provider == "ark":
        base_url = os.getenv("VOLCENGINE_ARK_API_BASE_URL", "").strip()
        api_key = os.getenv("VOLCENGINE_ARK_API_KEY", "").strip()

    if not base_url or not api_key:
        print("❌ API base_url 或 api_key 为空")
        return

    url = f"{base_url.rstrip('/')}/v1/models"
    print(f"请求 URL: {url}")
    print(f"LLM_PROVIDER: {provider}")
    print()

    req = urllib.request.Request(
        url,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="GET",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            models = data.get("data", [])

            print(f"共 {len(models)} 个可用模型：")
            print("=" * 60)

            # 找所有包含 deepseek 或 gpt 的模型
            deepseek_models = []
            gpt_models = []
            other_models = []

            for m in models:
                mid = m.get("id", "")
                if "deepseek" in mid.lower():
                    deepseek_models.append(mid)
                elif "gpt" in mid.lower():
                    gpt_models.append(mid)
                else:
                    other_models.append(mid)

            if gpt_models:
                print(f"\n📋 GPT 系列模型 ({len(gpt_models)} 个):")
                for m in sorted(gpt_models):
                    print(f"  - {m}")

            if deepseek_models:
                print(f"\n📋 DeepSeek 系列模型 ({len(deepseek_models)} 个):")
                for m in sorted(deepseek_models):
                    print(f"  - {m}")

            if other_models:
                print(f"\n📋 其他模型 ({len(other_models)} 个):")
                for m in sorted(other_models):
                    print(f"  - {m}")

            # 检查 gpt-5.6-terra 是否在列表中
            print()
            print("=" * 60)
            terra_exists = any(m.get("id") == "gpt-5.6-terra" for m in models)
            if terra_exists:
                print("✅ gpt-5.6-terra 在可用模型列表中")
            else:
                print("❌ gpt-5.6-terra 不在可用模型列表中！")
                print("   这说明 yunwu.ai 不支持这个模型名，")
                print("   它可能被自动路由到了 deepseek-v4-flash。")
                print()
                print("   请从上面的列表中选择一个真实的模型名，")
                print("   然后修改 .env 中的 LLM_MODEL_NAME。")

    except urllib.error.HTTPError as exc:
        resp_text = exc.read().decode("utf-8", errors="replace")
        print(f"❌ HTTP 错误: {exc.code}")
        print(f"响应: {resp_text[:1000]}")
    except Exception as exc:
        print(f"❌ 请求失败: {type(exc).__name__}: {exc}")


if __name__ == "__main__":
    main()
