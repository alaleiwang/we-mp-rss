"""
WeRSS 微信二维码飞书通知工具
由 failauth.CallBackNotice 调用，此时二维码图片已由 WX_API.GetCode() 生成完毕
"""
import requests
import time
import hmac
import hashlib
import base64
import json

FEISHU_APP_ID = 'cli_a927325a1f79dbdf'
FEISHU_APP_SECRET = 'FEISHU_APP_SECRET_REDACTED'
FEISHU_WEBHOOK = 'https://open.feishu.cn/open-apis/bot/v2/hook/dc696355-314d-476f-b27a-0fd84e065dfe'
FEISHU_WEBHOOK_SECRET = 'FEISHU_WEBHOOK_SECRET_REDACTED'
QR_IMAGE_PATH = './static/wx_qrcode.png'


def _feishu_token():
    r = requests.post('https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        json={'app_id': FEISHU_APP_ID, 'app_secret': FEISHU_APP_SECRET})
    return r.json()['tenant_access_token']


def _upload_image(img_path, fs_token):
    with open(img_path, 'rb') as f:
        r = requests.post('https://open.feishu.cn/open-apis/im/v1/images',
            headers={'Authorization': f'Bearer {fs_token}'},
            files={'image': ('qr.png', f, 'image/png')},
            data={'image_type': 'message'})
    return r.json()['data']['image_key']


def _signed_payload(secret, payload):
    timestamp = str(int(time.time()))
    sig = base64.b64encode(
        hmac.new((timestamp + '\n' + secret).encode(), digestmod=hashlib.sha256).digest()
    ).decode()
    payload['timestamp'] = timestamp
    payload['sign'] = sig
    return payload


def send_wx_qrcode_to_feishu(img_path=QR_IMAGE_PATH):
    """
    直接上传已生成的二维码图片并发飞书通知
    调用方须确保 img_path 已存在（由 WX_API.GetCode 生成）
    """
    import os
    if not os.path.exists(img_path):
        print(f'[feishu_qrcode_notify] 二维码图片不存在: {img_path}')
        return False

    try:
        fs_token = _feishu_token()
        image_key = _upload_image(img_path, fs_token)

        # 发文字提示
        r1 = requests.post(FEISHU_WEBHOOK, json=_signed_payload(FEISHU_WEBHOOK_SECRET, {
            'msg_type': 'text',
            'content': {'text': '⚠️ WeRSS 授权过期，请用微信扫下方二维码，扫后在手机点确认（有效期60秒）'}
        }))

        # 发图片
        r2 = requests.post(FEISHU_WEBHOOK, json=_signed_payload(FEISHU_WEBHOOK_SECRET, {
            'msg_type': 'image',
            'content': {'image_key': image_key}
        }))

        ok = r2.json().get('code') == 0
        print(f'[feishu_qrcode_notify] 发送{"成功" if ok else "失败"}: {r2.text}')
        return ok
    except Exception as e:
        print(f'[feishu_qrcode_notify] 异常: {e}')
        return False


if __name__ == '__main__':
    send_wx_qrcode_to_feishu()
