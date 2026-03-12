"""
微信公众号 Cookie 续期管理

职责：
1. 定时检查 cookie 有效期（每小时一次）
2. 到期前 N 天/小时发飞书提醒（可配置）
3. 过期后自动触发二维码扫码续期流程
4. 续期结果通知飞书管理群

配置（config.yaml 或环境变量）：
    cookie_renew:
        warn_days: 3          # 提前几天告警，默认 3 天
        auto_renew: true      # 到期后是否自动触发扫码，默认 true
        scan_timeout: 120     # 扫码等待秒数，默认 120s
        check_cron: "0 * * * *"  # 检查频率，默认每小时
"""

import os
import sys
import time
import logging

logger = logging.getLogger(__name__)

# ── 飞书通知 ────────────────────────────────────────────────────────────────

def _load_feishu_secret(agent="tron"):
    """从环境变量或 openclaw.json 读取飞书 App Secret（优先环境变量）"""
    import json, os
    if os.environ.get("FEISHU_APP_SECRET"):
        return os.environ["FEISHU_APP_SECRET"]
    try:
        cfg = json.load(open(os.path.expanduser("~/.openclaw/openclaw.json")))
        return cfg["channels"]["feishu"]["accounts"][agent]["appSecret"]
    except Exception:
        return ""

FEISHU_APP_ID = os.environ.get("FEISHU_APP_ID", "cli_a927325a1f79dbdf")
FEISHU_APP_SECRET = _load_feishu_secret("tron")
FEISHU_CHAT_ID = os.environ.get("FEISHU_CHAT_ID", "oc_0d007efed8a107b8d645a664aa203911")


def _feishu_token() -> str:
    import requests
    r = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={"app_id": FEISHU_APP_ID, "app_secret": FEISHU_APP_SECRET},
        timeout=10,
    )
    return r.json()["tenant_access_token"]


def _feishu_send(msg_type: str, content: dict) -> dict:
    import requests, json
    fs_token = _feishu_token()
    r = requests.post(
        "https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=chat_id",
        headers={"Authorization": f"Bearer {fs_token}", "Content-Type": "application/json"},
        json={
            "receive_id": FEISHU_CHAT_ID,
            "msg_type": msg_type,
            "content": json.dumps(content),
        },
        timeout=10,
    )
    return r.json()


def _notify_text(text: str):
    try:
        result = _feishu_send("text", {"text": text})
        logger.info(f"[cookie_renew] 飞书通知: {text[:60]}")
        return result
    except Exception as e:
        logger.warning(f"[cookie_renew] 飞书通知失败: {e}")


def _notify_with_qr(text: str, img_path: str) -> bool:
    """发文字提醒 + 二维码图片"""
    import requests
    try:
        fs_token = _feishu_token()
        # 文字
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
        logger.info("[cookie_renew] 二维码图片已发送到飞书")
        return True
    except Exception as e:
        logger.warning(f"[cookie_renew] 飞书推图失败: {e}")
        return False


# ── 核心状态检测 ─────────────────────────────────────────────────────────────

def get_cookie_status() -> dict:
    """
    获取当前 cookie 状态摘要。

    Returns:
        {
            "status": "valid" | "expiring_soon" | "expired" | "no_data",
            "expiry_time": "2026-03-14 08:00:00",
            "remaining_seconds": 90000,
            "remaining_days": 1.04,
            "warn_days": 3,
        }
    """
    try:
        from driver.token import get_expiry_info, _get_token_data
    except ImportError:
        return {"status": "no_data"}

    from core.config import cfg
    warn_days = int(cfg.get("cookie_renew.warn_days", 3))
    warn_seconds = warn_days * 86400

    token_data = _get_token_data()
    if not token_data or not token_data.get("token"):
        return {"status": "no_data", "warn_days": warn_days}

    expiry = token_data.get("expiry") or {}
    ts = expiry.get("expiry_timestamp", 0)
    if not ts:
        return {"status": "no_data", "warn_days": warn_days}

    try:
        remaining = float(ts) - time.time()
        expiry_time = expiry.get("expiry_time", "")
        token_prefix = (token_data.get("token") or "")[:8] + "..."

        if remaining <= 0:
            status = "expired"
        elif remaining <= warn_seconds:
            status = "expiring_soon"
        else:
            status = "valid"

        return {
            "status": status,
            "expiry_time": expiry_time,
            "expiry_timestamp": ts,
            "remaining_seconds": int(remaining),
            "remaining_days": round(remaining / 86400, 2),
            "warn_days": warn_days,
            "token_prefix": token_prefix,
        }
    except (TypeError, ValueError):
        return {"status": "no_data", "warn_days": warn_days}


# ── 续期流程 ─────────────────────────────────────────────────────────────────

def do_qr_renew(timeout: int = 120) -> bool:
    """
    触发微信二维码续期全流程：
      1. 调用 WX_API.GetCode → 后台线程启动 playwright 生成二维码
      2. 等二维码文件出现 → 推飞书图
      3. 轮询等待用户扫码完成
      4. 登录成功后 token 自动由 driver/token.set_token 存储

    Returns:
        True  = 续期成功
        False = 超时或失败
    """
    from driver.wx import WX_API
    from driver.success import Success

    login_done = {"ok": False, "account": ""}

    def on_success(session_data, ext_data):
        login_done["ok"] = True
        name = (ext_data or {}).get("wx_app_name", "未知账号")
        login_done["account"] = name
        logger.info(f"[cookie_renew] 续期成功，账号: {name}")
        _notify_text(f"✅ 微信公众号 Cookie 续期成功\n账号: {name}\n到期时间: {session_data.get('expiry', {}).get('expiry_time', '-')}")

    def on_notice(msg=None):
        """二维码就绪时推飞书"""
        qr_path = os.path.abspath("static/wx_qrcode.png")
        if msg and isinstance(msg, str) and "扫描" in msg:
            _notify_text(f"📱 {msg}")
            return
        if os.path.exists(qr_path) and os.path.getsize(qr_path) > 364:
            _notify_with_qr(
                "⚠️ 微信公众号 Cookie 即将过期，请用微信扫下方二维码续期（60秒内有效，扫后在手机点确认）",
                qr_path,
            )

    result = WX_API.GetCode(CallBack=on_success, Notice=on_notice)
    logger.info(f"[cookie_renew] GetCode 返回: {result}")

    # 等待二维码文件出现后推图（GetCode 是异步的）
    qr_path = os.path.abspath("static/wx_qrcode.png")
    for _ in range(20):
        if os.path.exists(qr_path) and os.path.getsize(qr_path) > 364:
            break
        time.sleep(1)

    if os.path.exists(qr_path) and os.path.getsize(qr_path) > 364:
        _notify_with_qr(
            "⚠️ 微信公众号 Cookie 即将过期，请用微信扫下方二维码续期（60秒内有效，扫后在手机点确认）",
            qr_path,
        )
    else:
        _notify_text("⚠️ 微信公众号 Cookie 续期：二维码生成失败，请手动登录")
        logger.warning("[cookie_renew] 二维码文件未生成，放弃续期")
        return False

    # 轮询等待扫码完成
    deadline = time.time() + timeout
    logger.info(f"[cookie_renew] 等待扫码，超时 {timeout}s ...")
    while time.time() < deadline:
        if login_done["ok"] or WX_API.HasLogin():
            login_done["ok"] = True
            break
        time.sleep(3)

    if not login_done["ok"]:
        msg = f"⏰ 微信公众号 Cookie 续期二维码超时（{timeout}s），请手动处理"
        logger.warning(f"[cookie_renew] {msg}")
        _notify_text(msg)
        return False

    return True


# ── 定时检查入口 ─────────────────────────────────────────────────────────────

# 防重入：避免并发触发多次续期
_renew_running = False


def check_and_renew():
    """
    定时检查入口（每小时由 APScheduler 调用）

    逻辑：
      - valid          → 无动作
      - expiring_soon  → 仅发提醒（不自动续期，让人决定）
                         但如果 remaining_days < 1，则直接触发续期
      - expired        → 若 auto_renew=True，触发 do_qr_renew
      - no_data        → 记录 warning，不自动续期
    """
    global _renew_running
    if _renew_running:
        logger.info("[cookie_renew] 续期任务正在运行，跳过本次检查")
        return

    from core.config import cfg
    auto_renew = str(cfg.get("cookie_renew.auto_renew", True)).lower() != "false"
    scan_timeout = int(cfg.get("cookie_renew.scan_timeout", 120))

    status = get_cookie_status()
    s = status.get("status")
    remaining_days = status.get("remaining_days", 0)
    expiry_time = status.get("expiry_time", "-")

    logger.info(f"[cookie_renew] 状态检查: status={s}, remaining_days={remaining_days}, expiry={expiry_time}")

    if s == "valid":
        # 正常，无动作
        return

    if s == "no_data":
        logger.warning("[cookie_renew] 未找到 cookie 数据，跳过")
        return

    if s == "expiring_soon":
        warn_days = status.get("warn_days", 3)
        if remaining_days > 1.0:
            # 距到期还有 > 1 天：只发提醒
            _notify_text(
                f"⚠️ 微信公众号 Cookie 即将到期\n"
                f"到期时间: {expiry_time}\n"
                f"剩余时间: {remaining_days:.1f} 天\n"
                f"请及时扫码续期（到期前 1 天将自动推送二维码）"
            )
            logger.info(f"[cookie_renew] 发送预警通知，剩余 {remaining_days:.1f} 天")
            return
        else:
            # 距到期 ≤ 1 天：直接触发续期（不管 auto_renew 配置）
            logger.info(f"[cookie_renew] 距到期不足 1 天，触发续期流程")
            _trigger_renew(scan_timeout)
            return

    if s == "expired":
        if auto_renew:
            logger.info("[cookie_renew] Cookie 已过期，auto_renew=True，触发续期")
            _trigger_renew(scan_timeout)
        else:
            _notify_text(
                f"❌ 微信公众号 Cookie 已过期（{expiry_time}），auto_renew 已关闭，请手动续期"
            )
        return


def _trigger_renew(timeout: int):
    global _renew_running
    _renew_running = True
    try:
        ok = do_qr_renew(timeout=timeout)
        if not ok:
            logger.error("[cookie_renew] 续期失败")
    except Exception as e:
        logger.error(f"[cookie_renew] 续期异常: {e}")
        _notify_text(f"❌ 微信公众号 Cookie 续期发生异常: {e}")
    finally:
        _renew_running = False


# ── 手动触发（供 API 调用）─────────────────────────────────────────────────

def manual_renew(timeout: int = 120) -> dict:
    """
    手动触发续期，供 API 端点调用。
    Returns: {"ok": bool, "msg": str}
    """
    global _renew_running
    if _renew_running:
        return {"ok": False, "msg": "续期任务正在运行中，请稍候"}
    
    status = get_cookie_status()
    logger.info(f"[cookie_renew] 手动触发续期，当前状态: {status}")
    
    ok = False
    try:
        _trigger_renew(timeout)
        ok = True
    except Exception as e:
        return {"ok": False, "msg": f"续期异常: {e}"}
    
    return {"ok": ok, "msg": "续期流程已启动，请在飞书扫码" if ok else "续期失败"}


# ── 注册到调度器 ─────────────────────────────────────────────────────────────

def register_cookie_renew_job(scheduler):
    """
    注册 cookie 续期定时检查任务到已有 TaskScheduler 实例。
    在 main.py 启动时调用。
    """
    from core.config import cfg
    cron = str(cfg.get("cookie_renew.check_cron", "0 * * * *"))
    job_id = scheduler.add_cron_job(
        check_and_renew,
        cron_expr=cron,
        job_id="cookie_renew_check",
        tag="Cookie续期检查",
    )
    logger.info(f"[cookie_renew] 已注册定时检查，cron={cron}，job_id={job_id}")
    return job_id


if __name__ == "__main__":
    # 直接运行：立即执行一次检查（调试用）
    import argparse
    PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    if PROJECT_ROOT not in sys.path:
        sys.path.insert(0, PROJECT_ROOT)

    logging.basicConfig(
        level=logging.INFO,
        format="[%(asctime)s][cookie_renew] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="微信 Cookie 续期检查")
    parser.add_argument("--force", action="store_true", help="强制触发续期（跳过有效性判断）")
    parser.add_argument("--status", action="store_true", help="只查看状态，不触发续期")
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()

    status = get_cookie_status()
    print(f"Cookie 状态: {status}")

    if args.status:
        sys.exit(0)

    if args.force:
        print("强制触发续期...")
        ok = do_qr_renew(timeout=args.timeout)
        sys.exit(0 if ok else 1)

    check_and_renew()
