from core.print import print_warning
from driver.base import WX_API
from core.config import cfg
from jobs.notice import sys_notice
from driver.success import Success

def send_wx_code(title: str = "", url: str = ""):
    if cfg.get("server.send_code", False):
        WX_API.GetCode(Notice=CallBackNotice, CallBack=Success)

def CallBackNotice(data=None, ext_data=None):
    if data is not None:
        print_warning(data)
        return

    # 优先用飞书二维码推送（支持手机直接扫码）
    try:
        from tools.feishu_qrcode_notify import send_wx_qrcode_to_feishu
        send_wx_qrcode_to_feishu()
        return
    except Exception as e:
        print_warning(f'飞书二维码推送失败，降级为文字通知: {e}')

    # 降级：原始文字通知
    import time
    from tools.base64_tools import image_to_base64
    img_path = WX_API.QRcode().get('code', '')
    rss_domain = str(cfg.get("rss.base_url", ""))
    url = image_to_base64("./static/wx_qrcode.png")
    text = f"- 服务名：{cfg.get('server.name', '')}\n"
    text += f"- 发送时间： {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}"
    if WX_API.GetHasCode():
        text += f"![描述]({url})"
        text += f"\n- 请使用微信扫描二维码进行授权"
    sys_notice(text, str(cfg.get("server.code_title", "WeRss授权过期,扫码授权")))
