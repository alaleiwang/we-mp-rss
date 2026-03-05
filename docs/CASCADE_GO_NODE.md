# WeRSS Go 子节点使用指南

## 概述

WeRSS Go 子节点是一个使用 Go 语言实现的级联子节点，可以：

- ✅ 连接到 Python 版本的父节点
- ✅ 使用 Playwright 进行浏览器自动化采集
- ✅ 执行消息任务（采集、推送）
- ✅ 上报任务执行结果
- ✅ 定期心跳保持连接

## 优势

相比 Python 版本：

1. **性能更好** - Go 的并发性能和编译型语言优势
2. **部署简单** - 单个可执行文件，无需 Python 环境
3. **内存占用低** - 更适合资源受限的环境
4. **跨平台** - 支持编译到多个平台

## 快速开始

### 1. 准备环境

```bash
# 安装 Go 1.21+
go version

# 安装 Playwright 浏览器
go install github.com/playwright-community/playwright-go/cmd/playwright@latest
playwright install
```

### 2. 获取父节点凭证

在父节点运行：

```bash
python jobs/cascade_init.py --child "Go子节点" --api-url "http://go-node:8001"
```

保存输出的 `api_key` 和 `api_secret`。

### 3. 配置 Go 子节点

编辑 `cascade-go/config.yaml`:

```yaml
parent:
  url: "http://parent-server:8001"
  api_key: "CNxxxxxxxx"  # 从父节点获取
  api_secret: "CSxxxxxxxx"  # 从父节点获取

sync:
  interval: 300
  heartbeat_interval: 60

browser:
  headless: false  # 开发时设为false，生产环境设为true
```

### 4. 运行

```bash
cd cascade-go

# 安装依赖
make init

# 运行
make run
```

## 项目结构

```
cascade-go/
├── main.go                 # 主程序入口
├── go.mod                  # Go 依赖管理
├── Makefile                # 构建脚本
├── config.yaml             # 配置文件
├── config/                 # 配置加载
│   └── config.go
├── client/                 # 父节点客户端
│   └── parent_client.go
├── sync/                   # 同步服务
│   └── sync_service.go
├── crawler/                # 采集器
│   └── article_crawler.go
├── models/                 # 数据模型
│   ├── feed.go
│   ├── message_task.go
│   └── response.go
├── test/                   # 测试工具
│   └── test.go
├── DEPLOYMENT.md           # 部署指南
└── README.md               # 项目说明
```

## 工作流程

```
Go子节点启动
    ↓
连接父节点（AK/SK认证）
    ↓
发送心跳
    ↓
拉取公众号数据
    ↓
拉取消息任务
    ↓
使用Playwright采集文章
    ↓
执行webhook推送
    ↓
上报执行结果
    ↓
循环（按配置的间隔）
```

## 测试连接

运行测试工具验证连接：

```bash
cd cascade-go

# 运行测试
cd test
go run test.go
```

测试内容：
- ✅ 发送心跳
- ✅ 拉取公众号数据
- ✅ 拉取消息任务
- ✅ 上报测试结果

## 配置说明

### 环境变量

可以通过环境变量覆盖配置：

```bash
export PARENT_URL="http://parent:8001"
export API_KEY="CNxxxxxxxx"
export API_SECRET="CSxxxxxxxx"

./werss-go-node
```

### 同步配置

```yaml
sync:
  interval: 300           # 数据同步间隔（秒）
  heartbeat_interval: 60  # 心跳间隔（秒）
```

建议值：
- 开发环境: interval=60, heartbeat_interval=30
- 生产环境: interval=300-600, heartbeat_interval=60

### 浏览器配置

```yaml
browser:
  headless: false  # 是否无头模式
  timeout: 30000  # 页面超时（毫秒）
```

- 开发调试: headless=false（可以看到浏览器界面）
- 生产环境: headless=true（后台运行）

## 编译和部署

### 编译

```bash
# 编译当前平台
make build

# 交叉编译（Linux）
GOOS=linux GOARCH=amd64 go build -o werss-go-node-linux main.go

# 交叉编译（Windows）
GOOS=windows GOARCH=amd64 go build -o werss-go-node.exe main.go

# 交叉编译（macOS）
GOOS=darwin GOARCH=amd64 go build -o werss-go-node-mac main.go
```

### Docker 部署

参见 `cascade-go/DEPLOYMENT.md` 中的 Docker 部署章节。

### systemd 服务

创建服务文件：

```ini
[Unit]
Description=WeRSS Go Child Node
After=network.target

[Service]
Type=simple
User=werss
WorkingDirectory=/opt/werss-go-node
ExecStart=/opt/werss-go-node/werss-go-node
Restart=always
Environment="PARENT_URL=http://parent:8001"
Environment="API_KEY=CNxxxxxxxx"
Environment="API_SECRET=CSxxxxxxxx"

[Install]
WantedBy=multi-user.target
```

## API 交互

Go 子节点使用与 Python 子节点相同的 API 接口：

| 操作 | 接口 | 方法 |
|------|------|------|
| 发送心跳 | `/cascade/heartbeat` | POST |
| 拉取公众号 | `/cascade/feeds` | GET |
| 拉取任务 | `/cascade/message-tasks` | GET |
| 上报结果 | `/cascade/report-result` | POST |

## 监控和日志

### 查看日志

```bash
# 如果使用 systemd
journalctl -u werss-go-node -f

# 直接运行
./werss-go-node  # 日志直接输出到控制台
```

### 日志内容

- 配置加载信息
- 连接状态
- 采集进度
- 错误信息
- 上报结果

## 故障排查

### 连接失败

1. 检查父节点是否运行
2. 确认网络连通性
3. 验证 API Key 和 Secret
4. 检查防火墙设置

### 浏览器启动失败

```bash
# 重新安装浏览器
playwright install

# 检查依赖（Alpine）
apk add chromium nss freetype harfbuzz

# 检查依赖（Ubuntu）
apt-get install chromium-browser
```

### 采集失败

1. 检查微信公众号页面结构
2. 增加超时时间
3. 尝试启用非无头模式调试
4. 检查网络代理设置

## 性能对比

| 指标 | Python 版本 | Go 版本 |
|------|-------------|---------|
| 内存占用 | ~150MB | ~50MB |
| 启动时间 | ~2s | ~0.1s |
| 并发能力 | 中等 | 高 |
| 部署复杂度 | 需要Python环境 | 单个可执行文件 |

## 混合部署

可以同时部署 Python 和 Go 子节点：

```
        ┌─────────────┐
        │   父节点     │
        │  (Python)   │
        └──────┬──────┘
               │
       ┌───────┼───────┐
       ▼       ▼       ▼
  ┌────────┐ ┌──────┐ ┌──────┐
  │Python  │ │ Go   │ │Go    │
  │子节点   │ │子节点 │ │子节点 │
  └────────┘ └──────┘ └──────┘
```

优势：
- 根据场景选择合适的语言
- Go 节点适合大规模采集
- Python 节点适合复杂任务

## 下一步

- 阅读 `cascade-go/DEPLOYMENT.md` 了解部署详情
- 运行 `test/test.go` 测试连接
- 配置 systemd 服务实现自启动
- 监控节点运行状态

## 支持

如遇问题：
1. 查看日志文件
2. 运行测试工具
3. 参考 `DEPLOYMENT.md` 故障排查章节
4. 提交 Issue 到 GitHub
