__package__ = "driver"
from core.config import Config,cfg
# 确保data目录和wx.lic文件存在
import os
import json

from core.print import print_success, print_warning
from core.redis_client import redis_client

REDIS_TOKEN_PREFIX = "werss:token:"

lic_path="./data/wx.lic"
os.makedirs(os.path.dirname(lic_path), exist_ok=True)
if not os.path.exists(lic_path):
    with open(lic_path, "w") as f:
        f.write("{}")
wx_cfg = Config(lic_path)

def set_token(data:any,ext_data:any=None):

    """
    设置微信登录的Token和Cookie信息
    :param data: 包含Token和Cookie信息的字典
    """
    if data.get("token", "") == "":
        return

    token_data = {
        "token": data.get("token", ""),
        "cookie": data.get("cookies_str", ""),
        "fingerprint": data.get("fingerprint", ""),
        "expiry": data.get("expiry", {}),
    }
    if ext_data is not None:
        token_data["ext_data"] = ext_data

    # 优先存储到Redis
    if redis_client.is_connected:
        try:
            for key, value in token_data.items():
                redis_client._client.set(f"{REDIS_TOKEN_PREFIX}{key}", json.dumps(value) if isinstance(value, dict) else value)
            print_success("Token已存储到Redis")
        except Exception as e:
            print_warning(f"Redis存储失败，回退到本地文件: {e}")
            # 回退到本地文件存储
            _save_to_local(token_data)
    else:
        _save_to_local(token_data)

    print_success(f"Token:{data.get('token')} \n到期时间:{data.get('expiry')['expiry_time']}\n")
    from jobs.notice import sys_notice

#     sys_notice(f"""WeRss授权成功
# - Token: {data.get("token")}
# - Expiry: {data.get("expiry")['expiry_time']}
# """, str(cfg.get("server.code_title","WeRss授权成功")))


def _save_to_local(token_data: dict):
    """保存到本地文件"""
    for key, value in token_data.items():
        wx_cfg.set(key, value)
    wx_cfg.save_config()
    wx_cfg.reload()


def get(key:str,default:str="")->str:
    # 优先从Redis获取
    if redis_client.is_connected:
        try:
            value = redis_client._client.get(f"{REDIS_TOKEN_PREFIX}{key}")
            if value is not None:
                # 尝试解析JSON，如果是简单字符串则直接返回
                try:
                    parsed = json.loads(value)
                    return str(parsed) if not isinstance(parsed, dict) else json.dumps(parsed)
                except (json.JSONDecodeError, TypeError):
                    return str(value)
        except Exception as e:
            print_warning(f"Redis读取失败，回退到本地文件: {e}")
    # 回退到本地文件
    return str(wx_cfg.get(key, default))