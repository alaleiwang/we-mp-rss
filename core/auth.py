from datetime import datetime, timedelta
import jwt
import bcrypt
from functools import wraps
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
from typing import Optional
from core.models import User as DBUser
from core.config import  cfg,API_BASE
from sqlalchemy.orm import Session
from core.models import User, AccessKey
import core.db  as db
from passlib.context import CryptContext
import json
import secrets
import hashlib
from core.models.cascade_node import CascadeNode

DB=db.Db(tag="用户连接")
SECRET_KEY = cfg.get("secret","csol2025")  # 生产环境应使用更安全的密钥
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(cfg.get("token_expire_minutes",30))

class PasswordHasher:
    """自定义密码哈希器，替代passlib的CryptContext"""
    
    @staticmethod
    def verify(plain_password: str, hashed_password: str) -> bool:
        """验证密码是否匹配哈希"""
        try:
            return bcrypt.checkpw(
                plain_password.encode('utf-8'),
                hashed_password.encode('utf-8')
            )
        except (ValueError, TypeError):
            return False
    
    @staticmethod
    def hash(password: str) -> str:
        """生成密码哈希"""
        return bcrypt.hashpw(
            password.encode('utf-8'),
            bcrypt.gensalt()
        ).decode('utf-8')

# 密码哈希上下文
pwd_context = PasswordHasher()
oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{API_BASE}/auth/token",auto_error=False)

# 用户缓存字典
_user_cache = {}
# 登录失败次数记录
_login_attempts = {}
MAX_LOGIN_ATTEMPTS = 5


# ===== Access Key (AK) 认证相关功能 =====

def generate_access_key() -> tuple[str, str]:
    """
    生成 Access Key 和 Secret Key
    返回: (access_key, secret_key)
    """
    # Access Key: 前缀 WK + 32位随机字符
    access_key = "WK" + secrets.token_urlsafe(32)[:32]
    # Secret Key: 前缀 SK + 32位随机字符
    secret_key = "SK" + secrets.token_urlsafe(32)[:32]
    return access_key, secret_key


def hash_secret_key(secret_key: str) -> str:
    """对 Secret Key 进行哈希处理"""
    return hashlib.sha256(secret_key.encode()).hexdigest()


def verify_secret_key(plain_secret: str, hashed_secret: str) -> bool:
    """验证 Secret Key 是否匹配"""
    return hashlib.sha256(plain_secret.encode()).hexdigest() == hashed_secret

def get_login_attempts(username: str) -> int:
    """获取用户登录失败次数"""
    return _login_attempts.get(username, 0)

def get_user(username: str) -> Optional[dict]:
    """从数据库获取用户，带缓存功能"""
    # 先检查缓存
    if username in _user_cache:
        return _user_cache[username]

    session = DB.get_session()
    try:
        user = session.query(DBUser).filter(DBUser.username == username).first()
        if user:
            # 转换为字典并存入缓存
            user_dict = user.__dict__.copy()
            # 移除 SQLAlchemy 内部属性（如 _sa_instance_state）
            user_dict.pop('_sa_instance_state', None)
            user_dict=User(**user_dict)
            _user_cache[username] = user_dict
            return user_dict
        return None
    except Exception as e:
        from core.print import print_error
        print_error(f"获取用户错误: {str(e)}")
        return None

def get_user_by_id(user_id: str) -> Optional[dict]:
    """从数据库通过用户ID获取用户，带缓存功能"""
    # 缓存键使用 id: 前缀
    cache_key = f"id:{user_id}"
    if cache_key in _user_cache:
        return _user_cache[cache_key]

    session = DB.get_session()
    try:
        user = session.query(DBUser).filter(DBUser.id == user_id).first()
        if user:
            # 转换为字典并存入缓存
            user_dict = user.__dict__.copy()
            # 移除 SQLAlchemy 内部属性（如 _sa_instance_state）
            user_dict.pop('_sa_instance_state', None)
            user_dict=User(**user_dict)
            _user_cache[cache_key] = user_dict
            return user_dict
        return None
    except Exception as e:
        from core.print import print_error
        print_error(f"通过ID获取用户错误: {str(e)}")
        return None
        
def clear_user_cache(username: str):
    """清除指定用户的缓存"""
    if username in _user_cache:
        del _user_cache[username]

from apis.base import error_response
def authenticate_user(username: str, password: str) -> Optional[DBUser]:
    """验证用户凭据"""
    # 检查是否超过最大尝试次数
    if _login_attempts.get(username, 0) >= MAX_LOGIN_ATTEMPTS:
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail=error_response(
                code=40101,
                message="用户名或密码错误，您的帐号已锁定，请稍后再试"
            )
        )
    
    user = get_user(username)

    if not user or not pwd_context.verify(password, user.password_hash):
        # 增加失败次数
        _login_attempts[username] = _login_attempts.get(username, 0) + 1
        remaining_attempts = MAX_LOGIN_ATTEMPTS - _login_attempts[username]
        raise HTTPException(
            status_code=status.HTTP_202_ACCEPTED,
            detail=error_response(
                code=40101,
                message=f"用户名或密码错误，您还有{remaining_attempts}次机会"
            )
        )
    
    # 登录成功，清除失败记录
    if username in _login_attempts:
        del _login_attempts[username]
    return user

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """创建JWT Token"""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_current_user(token: str = Depends(oauth2_scheme)):
    """获取当前用户"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    user = get_user(username)
    if user is None:
        raise credentials_exception
        
    return {
        "username": user.username,
        "role": user.role,
        "permissions": user.permissions,
        "original_user": user
    }

def requires_role(role: str):
    """检查用户角色的装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            current_user = kwargs.get('current_user')
            if not current_user or current_user.get('role') != role:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Insufficient permissions"
                )
            return await func(*args, **kwargs)
        return wrapper
    return decorator

def create_ak(
    user_id: str,
    name: str,
    permissions: list = None,
    description: str = "",
    expires_in_days: Optional[int] = None
) -> dict:
    """
    为用户创建 Access Key
    
    参数:
        user_id: 用户ID
        name: AK名称
        permissions: 权限列表
        description: 描述
        expires_in_days: 过期天数(None表示不过期)
    
    返回: 包含AK信息的字典
    """
    from uuid import uuid4
    
    session = DB.get_session()
    try:
        access_key, secret_key = generate_access_key()
        hashed_secret = hash_secret_key(secret_key)
        
        ak_id = str(uuid4())
        expires_at = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)
        
        ak = AccessKey(
            id=ak_id,
            user_id=user_id,
            key=access_key,
            secret=hashed_secret,
            name=name,
            description=description,
            permissions=json.dumps(permissions or []),
            is_active=True,
            expires_at=expires_at
        )
        
        session.add(ak)
        session.commit()
        session.refresh(ak)
        
        return {
            "id": ak.id,
            "key": access_key,
            "secret": secret_key,  # 只在创建时返回一次
            "name": name,
            "description": description,
            "permissions": permissions or [],
            "is_active": True,
            "created_at": ak.created_at.isoformat() if ak.created_at else None,
            "expires_at": ak.expires_at.isoformat() if ak.expires_at else None
        }
    except Exception as e:
        session.rollback()
        from core.print import print_error
        print_error(f"创建Access Key错误: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="创建Access Key失败"
        )
    finally:
        session.close()


def get_ak_by_key(access_key: str) -> Optional[AccessKey]:
    """通过 AK 值获取 AK 记录"""
    session = DB.get_session()
    try:
        ak = session.query(AccessKey).filter(
            AccessKey.key == access_key,
            AccessKey.is_active == True
        ).first()
        return ak
    except Exception as e:
        from core.print import print_error
        print_error(f"获取Access Key错误: {str(e)}")
        return None
    finally:
        session.close()


def authenticate_ak(access_key: str, secret_key: str) -> Optional[dict]:
    """
    验证 AK/SK 凭证
    
    参数:
        access_key: Access Key
        secret_key: Secret Key
    
    返回: 用户信息或 None
    """
    ak = get_ak_by_key(access_key)
    
    if not ak or not ak.is_valid():
        return None
    
    if not verify_secret_key(secret_key, ak.secret):
        return None
    
    # 获取关联的用户信息
    user = get_user_by_id(ak.user_id)
    
    if not user:
        return None
    
    # 更新最后使用时间
    session = DB.get_session()
    try:
        ak_record = session.query(AccessKey).filter(AccessKey.id == ak.id).first()
        if ak_record:
            ak_record.last_used_at = datetime.utcnow()
            session.commit()
    except:
        session.rollback()
    finally:
        session.close()
    
    # 解析权限
    try:
        ak_permissions = json.loads(ak.permissions) if ak.permissions else []
    except:
        ak_permissions = []
    
    return {
        "username": user.username,
        "user_id": ak.user_id,
        "access_key_id": ak.id,
        "access_key_name": ak.name,
        "role": user.role,
        "permissions": ak_permissions or user.permissions,  # 使用AK的权限或用户权限
        "original_user": user,
        "auth_type": "ak"  # 标记为 AK 认证
    }


async def get_current_user_or_ak(request: Request, token: str = Depends(oauth2_scheme)):
    """
    通用认证函数，支持 JWT Token、AK/SK 认证和级联节点认证
    
    优先级:
    1. Authorization 头中的 AK/SK (格式: "AK-SK ak_value:sk_value") - 用户AK或级联节点AK
    2. Bearer Token (JWT)
    """
    # 检查 AK/SK 认证
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("AK-SK "):
        try:
            credentials = auth_header[6:].strip()
            if ':' in credentials:
                ak, sk = credentials.split(':', 1)
                
                # 1. 尝试级联节点认证
                node = authenticate_cascade_node(ak, sk)
                if node:
                    return {
                        "username": f"node_{node['name']}",
                        "node_id": node['id'],
                        "role": "cascade_node",
                        "auth_type": "cascade_node"
                    }
                
                # 2. 尝试用户AK认证
                user_info = authenticate_ak(ak, sk)
                if user_info:
                    return user_info
        except:
            pass
    
    # 回退到 JWT Token 认证
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except jwt.PyJWTError:
        raise credentials_exception
    
    user = get_user(username)
    
    if user is None:
        raise credentials_exception
        
    return {
        "username": user.username,
        "role": user.role,
        "permissions": user.permissions,
        "original_user": user,
        "auth_type": "jwt"  # 标记为 JWT 认证
    }


def list_user_aks(user_id: str) -> list:
    """获取用户的所有 Access Keys"""
    session = DB.get_session()
    try:
        aks = session.query(AccessKey).filter(
            AccessKey.user_id == user_id
        ).all()
        
        result = []
        for ak in aks:
            ak_permissions = []
            try:
                ak_permissions = json.loads(ak.permissions) if ak.permissions else []
            except:
                pass
            
            result.append({
                "id": ak.id,
                "name": ak.name,
                "key": ak.key,  # 返回完整的key供复制
                "description": ak.description,
                "permissions": ak_permissions,
                "is_active": ak.is_active,
                "is_expired": ak.is_expired(),
                "created_at": ak.created_at.isoformat() if ak.created_at else None,
                "updated_at": ak.updated_at.isoformat() if ak.updated_at else None,
                "last_used_at": ak.last_used_at.isoformat() if ak.last_used_at else None,
                "expires_at": ak.expires_at.isoformat() if ak.expires_at else None
            })
        
        return result
    except Exception as e:
        from core.print import print_error
        print_error(f"获取用户Access Keys错误: {str(e)}")
        return []
    finally:
        session.close()


def deactivate_ak(ak_id: str) -> bool:
    """停用 Access Key"""
    session = DB.get_session()
    try:
        ak = session.query(AccessKey).filter(AccessKey.id == ak_id).first()
        if ak:
            ak.is_active = False
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        from core.print import print_error
        print_error(f"停用Access Key错误: {str(e)}")
        return False
    finally:
        session.close()


def delete_ak(ak_id: str) -> bool:
    """删除 Access Key"""
    session = DB.get_session()
    try:
        ak = session.query(AccessKey).filter(AccessKey.id == ak_id).first()
        if ak:
            session.delete(ak)
            session.commit()
            return True
        return False
    except Exception as e:
        session.rollback()
        from core.print import print_error
        print_error(f"删除Access Key错误: {str(e)}")
        return False
    finally:
        session.close()


def update_ak(ak_id: str, **kwargs) -> bool:
    """更新 Access Key 信息"""
    session = DB.get_session()
    try:
        ak = session.query(AccessKey).filter(AccessKey.id == ak_id).first()
        if not ak:
            return False
        
        # 允许更新的字段
        allowed_fields = ['name', 'description', 'is_active', 'permissions', 'expires_at']
        for field, value in kwargs.items():
            if field in allowed_fields:
                if field == 'permissions' and isinstance(value, list):
                    value = json.dumps(value)
                setattr(ak, field, value)
        
        ak.updated_at = datetime.utcnow()
        session.commit()
        return True
    except Exception as e:
        session.rollback()
        from core.print import print_error
        print_error(f"更新Access Key错误: {str(e)}")
        return False
    finally:
        session.close()


def authenticate_cascade_node(api_key: str, secret_key: str) -> Optional[dict]:
    """
    验证级联节点 AK/SK 凭证
    
    参数:
        api_key: 级联节点的 API Key
        secret_key: 级联节点的 Secret Key
    
    返回: 级联节点信息字典或 None
    """
    from core.print import print_info, print_error
    session = DB.get_session()
    try:
        secret_hash = hashlib.sha256(secret_key.encode()).hexdigest()
        
        print_info(f"[级联认证] AK: {api_key}")
        print_info(f"[级联认证] SK Hash: {secret_hash}")
        
        node = session.query(CascadeNode).filter(
            CascadeNode.api_key == api_key,
            CascadeNode.api_secret_hash == secret_hash,
            CascadeNode.is_active == True
        ).first()
        
        if node:
            print_info(f"[级联认证] 找到节点: {node.name}")
            # 更新最后心跳时间
            node.last_heartbeat_at = datetime.utcnow()
            session.commit()
            
            # 在 session 关闭前提取数据
            return {
                "id": node.id,
                "name": node.name,
                "node_type": node.node_type
            }
        else:
            print_error(f"[级联认证] 未找到匹配节点")
            # 调试：列出所有节点
            all_nodes = session.query(CascadeNode).filter(
                CascadeNode.api_key == api_key
            ).all()
            print_info(f"[级联认证] AK 匹配的节点数: {len(all_nodes)}")
            for n in all_nodes:
                print_info(f"[级联认证] 节点: {n.name}, active={n.is_active}, hash={n.api_secret_hash}")
        
        return None
    except Exception as e:
        from core.print import print_error
        print_error(f"验证级联节点凭证错误: {str(e)}")
        import traceback
        traceback.print_exc()
        return None
    finally:
        session.close()
