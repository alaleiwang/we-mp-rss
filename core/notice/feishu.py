import requests
import json
import time
import hmac
import hashlib
import base64

def send_feishu_message(webhook_url, title, text, secret=None):
    """
    发送飞书 Markdown 格式消息，支持签名校验

    参数:
    - webhook_url: 飞书机器人 Webhook 地址
    - title: 消息标题
    - text: Markdown 格式内容
    - secret: 签名密钥（可选）
    """
    headers = {'Content-Type': 'application/json'}
    data = {
        "msg_type": "interactive",
        "card": {
            "config": {
                "wide_screen_mode": True,
                "enable_forward": True
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "content": text,
                        "tag": "lark_md"
                    }
                }
            ],
            "header": {
                "template": "blue",
                "title": {
                    "content": title,
                    "tag": "plain_text"
                }
            }
        }
    }

    # 签名校验
    if secret:
        timestamp = str(int(time.time()))
        string_to_sign = timestamp + '\n' + secret
        sig = base64.b64encode(
            hmac.new(string_to_sign.encode('utf-8'), digestmod=hashlib.sha256).digest()
        ).decode('utf-8')
        data['timestamp'] = timestamp
        data['sign'] = sig

    try:
        response = requests.post(
            url=webhook_url,
            headers=headers,
            data=json.dumps(data)
        )
        print(response.text)
    except Exception as e:
        print('飞书通知发送失败', e)
