"""
微信公众号 token 自动续期脚本
- 检测 token/cookie 是否过期
- 过期则触发二维码重登录流程，推图到飞书
- 等待扫码确认，成功/超时均发通知
- 可直接运行，也可被 cron 调起

用法：
    python3 tools/wx_auth_check.py [--force] [--timeout 120]

    --force    跳过有效性检测，强制重新登录
    --timeout  等待扫码最大秒数，默认 120
"""
import os
import sys
import time
import argparse
import logging

# 确保项目根目录在 path 中（cron 环境下尤其需要）
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s][wx_auth_check] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# ── 飞书通知 ──────────────────────────────────────────────────────────────────

def _feishu_token():
    import json, requests
    cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
    FEISHU_APP_ID = "cli_a927325a1f79dbdf"        # Tron bot
    FEISHU_APP_SECRET = cfg["channels"]["feishu"]["accounts"]["tron"]["appSecret"]
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    return r.json()["tenant_access_token"]


def _feishu_send(msg_type: str, content: dict, chat_id: str = None):
    """发消息到飞书群或私信"""
    import requests, json
    FEISHU_CHAT_ID = "oc_0d007efed8a107b8d645a664aa203911"  # 管理通知群
    fs_token = _feishu_token()
    r = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {fs_token}", "Content-Type": "application/json"},
        json={
            "receive_id": chat_id or FEISHU_CHAT_ID,
            "msg_type": msg_type,
            "content": json.dumps(content),
        },
        timeout=10,
    )
    return r.json()


def notify(text: str):
    """发文字通知到管理群"""
    try:
        _feishu_send("text", {"text": text})
        logger.info(f"飞书通知: {text}")
    except Exception as e:
        logger.warning(f"飞书通知失败: {e}")


def notify_with_image(text: str, img_path: str):
    """先发文字，再发图片"""
    import requests
    try:
        fs_token = _feishu_token()
        # 发文字
        _feishu_send("text", {"text": text})
        # 上传图片
        with open(img_path, "rb") as f:
            r = requests.post(
                "https://open.feishu.cn/open-apis/im/v1/images",
                headers={"Authorization": f"Bearer {fs_token}"},
                files={"image": ("qr.png", f, "image/png")},
                data={"image_type": "message"},
                timeout=15,
            )
        image_key = r.json()["data"]["image_key"]
        _feishu_send("image", {"image_key": image_key})
        logger.info("飞书图片已发送")
        return True
    except Exception as e:
        logger.warning(f"飞书推图失败: {e}")
        return False

# ── 核心逻辑 ──────────────────────────────────────────────────────────────────

def check_token_valid() -> bool:
    """检测 token 是否有效（先检 expiry，再验 HTTP）"""
    from driver.token import is_expired, get_expiry_info
    info = get_expiry_info()
    logger.info(f"token 状态: {info}")

    if is_expired(buffer_seconds=300):
        return False

    # expiry 未过期，但再做一次 HTTP 验证（防止 token 被踢）
    try:
        from driver.wx_api import WeChat_api
        result = WeChat_api.login_with_token()
        logger.info(f"HTTP 验证结果: {result}")
        return bool(result)
    except Exception as e:
        logger.warning(f"HTTP 验证异常: {e}")
        return False


def do_qr_login(timeout: int = 120) -> bool:
    """
    触发二维码登录全流程：
    1. 生成二维码
    2. 推图到飞书
    3. 轮询等待扫码
    4. 登录成功后 token 已由 WeChatAPI 内部 set_token 存储
    """
    from driver.wx_api import WeChat_api

    login_done = {"ok": False}

    def on_login_success(session_data, account_info):
        login_done["ok"] = True
        name = (account_info or {}).get("wx_app_name", "未知账号")
        logger.info(f"登录成功: {name}")
        notify(f"✅ 微信公众号授权刷新成功\n账号: {name}")

    def on_notice(msg=None):
        """二维码就绪时推飞书图"""
        qr_path = os.path.abspath(os.path.join(PROJECT_ROOT, "static/wx_qrcode.png"))
        logger.info(f"notice 回调触发，msg={msg}，推图: {qr_path}")
        if msg and isinstance(msg, str) and "扫描" in msg:
            # 扫码确认中间态，只发文字
            notify(f"📱 {msg}")
            return
        if os.path.exists(qr_path):
            notify_with_image(
                "⚠️ 微信公众号授权过期，请用微信扫码（60秒有效，扫后在手机点确认）",
                qr_path,
            )
        else:
            notify("⚠️ 微信公众号授权过期，正在生成二维码，稍候...")

    # 触发二维码生成（后台线程轮询）
    result = WeChat_api.GetCode(CallBack=on_login_success, Notice=on_notice)
    logger.info(f"GetCode 返回: {result}")

    # 等二维码文件出现再推图（GetCode 是异步的，稍等片刻）
    qr_path = os.path.abspath(os.path.join(PROJECT_ROOT, "static/wx_qrcode.png"))
    for _ in range(15):  # 最多等 15s
        if os.path.exists(qr_path):
            break
        time.sleep(1)

    if os.path.exists(qr_path):
        notify_with_image(
            "⚠️ 微信公众号授权过期，请用微信扫码（60秒有效，扫后在手机点确认）",
            qr_path,
        )
    else:
        notify("⚠️ 微信公众号授权过期，二维码生成失败，请检查服务")
        return False

    # 轮询等待登录完成
    deadline = time.time() + timeout
    logger.info(f"等待扫码，超时 {timeout}s ...")
    while time.time() < deadline:
        if login_done["ok"] or WeChat_api.HasLogin():
            login_done["ok"] = True
            break
        time.sleep(3)

    if not login_done["ok"]:
        msg = f"⏰ 微信公众号二维码超时（{timeout}s），请手动处理"
        logger.warning(msg)
        notify(msg)
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="微信公众号 token 自动续期")
    parser.add_argument("--force", action="store_true", help="强制重新登录（跳过有效性检测）")
    parser.add_argument("--timeout", type=int, default=120, help="等待扫码最大秒数（默认 120）")
    args = parser.parse_args()

    logger.info("=== 微信公众号 token 续期检测 开始 ===")

    if not args.force:
        if check_token_valid():
            from driver.token import get_expiry_info
            info = get_expiry_info()
            logger.info(f"token 有效，无需续期。到期: {info.get('expiry_time')}，剩余: {info.get('remaining_seconds')}s")
            return 0
        logger.info("token 无效或即将过期，触发二维码续期流程")
    else:
        logger.info("--force 模式，强制重新登录")

    ok = do_qr_login(timeout=args.timeout)
    logger.info(f"=== 续期结果: {'成功' if ok else '失败'} ===")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
