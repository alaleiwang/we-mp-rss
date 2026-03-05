# 环境异常统计功能使用说明

## 功能概述

当微信公众号文章获取器遇到"当前环境异常，完成验证后即可继续访问"的情况时，系统会自动记录统计信息到 Redis，方便后续分析和排查。

**重要提示**: Redis 是可选功能，如果未配置或连接失败，不影响系统的核心功能正常运行。

## 配置要求

### 1. Redis 配置

在 `config.yaml` 中配置 Redis 连接：

```yaml
redis:
  url: ${REDIS_URL:-}
```

或者通过环境变量配置：

```bash
# Windows
set REDIS_URL=redis://localhost:6379/0

# Linux/Mac
export REDIS_URL=redis://localhost:6379/0
```

### 2. 依赖安装

确保已安装 Redis 依赖：

```bash
pip install redis==7.2.1
```

### 3. 启动 Redis 服务

**Windows:**
```bash
redis-server.exe
```

**Linux:**
```bash
sudo systemctl start redis
```

**Mac:**
```bash
brew services start redis
```

**Docker:**
```bash
docker run -d -p 6379:6379 --name redis redis:7-alpine
```

## 连接问题排查

### 快速诊断

运行诊断工具：

```bash
python diagnose_redis.py
```

或快速测试：

```bash
python quick_test_redis.py
```

### 常见问题

#### 1. Redis 服务未启动
```
✗ 连接失败: Error 10061
```
**解决**: 启动 Redis 服务（见上文）

#### 2. Redis URL 未配置
```
Redis URL未配置，统计功能将禁用
```
**解决**: 在 config.yaml 中配置或设置环境变量

#### 3. 认证失败
```
✗ 认证失败: Authentication failed
```
**解决**: 检查 Redis 密码配置

详细排查指南请查看: `docs/redis-troubleshooting.md`

## 统计数据结构

系统会在 Redis 中记录以下维度的统计信息：

### 1. 总计数器
- **键名**: `werss:env_exception:total:{日期}`
- **类型**: String
- **说明**: 记录当日环境异常的总次数
- **过期时间**: 30天

### 2. URL 维度统计
- **键名**: `werss:env_exception:url:{日期}`
- **类型**: Hash
- **字段**: URL -> 时间戳
- **说明**: 记录每个 URL 出现异常的时间
- **过期时间**: 30天

### 3. 公众号维度统计
- **键名**: `werss:env_exception:mp:{日期}`
- **类型**: Hash
- **字段**: 公众号ID -> 计数
- **说明**: 记录每个公众号出现异常的次数
- **过期时间**: 30天

### 4. 详细日志
- **键名**: `werss:env_exception:logs`
- **类型**: List
- **说明**: 最近 1000 条异常记录
- **过期时间**: 7天

## API 接口

### 1. 获取指定日期统计

**请求**:
```
GET /api/env-exception/stats?date=2024-01-01
```

**参数**:
- `date`: 可选，格式为 YYYY-MM-DD，默认为今天

**响应示例**:
```json
{
  "code": 200,
  "data": {
    "date": "2024-01-01",
    "total": 10,
    "urls": {
      "https://mp.weixin.qq.com/s/xxx": "2024-01-01 10:30:00"
    },
    "mp_stats": {
      "MP_WXS_xxx": "5"
    },
    "recent_logs": [
      "{\"url\": \"...\", \"mp_name\": \"...\", \"mp_id\": \"...\", \"timestamp\": \"...\"}"
    ]
  }
}
```

### 2. 获取今日统计

**请求**:
```
GET /api/env-exception/today
```

**响应**: 与上述格式相同

## 使用场景

### 1. 监控异常频率

通过定时查询 API，监控环境异常的发生频率：

```python
import requests

response = requests.get(
    "http://localhost:8001/api/env-exception/today",
    headers={"Authorization": "Bearer YOUR_TOKEN"}
)

data = response.json()
if data["data"]["total"] > 10:
    print(f"警告：今日环境异常次数过多: {data['data']['total']}")
```

### 2. 分析异常模式

通过 Redis 直接查询统计数据：

```python
import redis
from datetime import datetime

# 连接 Redis
r = redis.from_url("redis://localhost:6379/0")

# 获取今日统计
today = datetime.now().strftime("%Y-%m-%d")
total = r.get(f"werss:env_exception:total:{today}")
print(f"今日异常次数: {total}")

# 获取公众号维度统计
mp_stats = r.hgetall(f"werss:env_exception:mp:{today}")
for mp_id, count in mp_stats.items():
    print(f"公众号 {mp_id}: {count} 次")
```

### 3. 集成到监控告警

可以结合 Prometheus、Grafana 等监控工具，实现实时告警：

```python
from prometheus_client import Counter
from core.redis_client import get_env_exception_stats

# 定义 Prometheus 指标
env_exception_counter = Counter(
    'werss_env_exception_total',
    'Total environment exception count'
)

# 定时更新指标
def update_metrics():
    stats = get_env_exception_stats()
    env_exception_counter._value._value = stats["total"]
```

## 注意事项

1. **Redis 未配置时的行为**: 如果 Redis 未配置或连接失败，系统会跳过统计记录，不影响正常功能
2. **数据保留**: 统计数据会自动过期清理，无需手动维护
3. **性能影响**: 统计记录使用 Redis Pipeline 批量操作，对性能影响极小
4. **并发安全**: 使用 Redis 事务确保统计数据的原子性

## 故障排查

### 1. 统计数据未记录

检查 Redis 连接状态：
```bash
redis-cli ping
```

检查配置：
```python
from core.config import cfg
print(cfg.get("redis.url"))
```

### 2. API 返回错误

检查用户认证：
- 确保请求包含有效的 `Authorization` 头
- 可以使用 JWT Token 或 AK-SK 认证

### 3. 统计数据异常

检查 Redis 中的数据：
```bash
redis-cli keys "werss:env_exception:*"
```

查看具体数据：
```bash
redis-cli get "werss:env_exception:total:2024-01-01"
redis-cli hgetall "werss:env_exception:mp:2024-01-01"
```
