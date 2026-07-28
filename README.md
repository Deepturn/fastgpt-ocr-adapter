# FastGPT OCR Adapter

> A small HTTP adapter that connects FastGPT to official local document parsers.
> One instance uses one parser provider and exposes the fixed FastGPT PDF contract.

这个服务放在 FastGPT 和本地 OCR 服务之间。

FastGPT 只需要调用一个固定地址，不必知道后面跑的是 MinerU 还是 Marker，也不用跟着
OCR 服务的版本修改请求参数。适配器负责鉴权、PDF 检查、排队、调用上游、处理图片，
最后返回 FastGPT 能直接使用的 Markdown。

```text
FastGPT
  -> POST /v2/parse/file
  -> FastGPT OCR Adapter
  -> MinerU 或 Marker
```

这里没有修改 MinerU 或 Marker 的源码，也没有使用 FastGPT 仓库里改造过的 Marker。
上游 OCR 服务仍按官方方式部署。

## 支持范围

| OCR 服务 | API Profile | 支持版本 | 备注 |
|---|---|---|---|
| MinerU | `mineru-api-v3` | `3.4.4` | 调用官方 `/file_parse` |
| Marker | `marker-server-v1` | `>=1.8,<2.0` | 已验证 `1.10.2`，不发送 `mode` |
| Marker | `marker-server-v2` | `2.0.0` | 发送 `mode=balanced/fast` |

一个适配器实例只连接一个 OCR 服务。换 OCR 服务或版本时，需要修改环境变量并重启
适配器，不支持在单次请求里动态选择。

## 先准备 OCR 服务

如果你已经有可访问的 MinerU 或 Marker API，可以直接跳到下一节。

官方资料：

- MinerU：[Docker 部署教程](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)
- MinerU：[快速使用和 API 说明](https://opendatalab.github.io/MinerU/usage/quick_usage/)
- MinerU：[3.4.4 Release](https://github.com/opendatalab/MinerU/releases/tag/mineru-3.4.4-released)
- Marker 2.x：[官方 README](https://github.com/datalab-to/marker/blob/master/README.md)
- Marker 1.10：[v1.10.2 官方 README](https://github.com/datalab-to/marker/blob/v1.10.2/README.md)
- Marker 2.0.0：[PyPI 页面](https://pypi.org/project/marker-pdf/2.0.0/)

这些上游文档会继续变化。本项目的 Profile 只代表已经验证过的接口形状，不能因为
官方发布了新版本就只改版本号直接上线。

Marker 官方把 `marker_server` 定位为简单、小规模使用的 API 服务。高并发场景需要你
自己在 Marker 前面补进程管理、限流或任务系统；本适配器的队列只能控制进入 Marker
的请求数量。

## 启动适配器

要求 Docker Engine 和 Docker Compose v2。

```bash
cp .env.example .env
openssl rand -hex 32
```

把生成的随机字符串填入 `.env`：

```dotenv
FASTGPT_OCR_AUTH_TOKEN=刚才生成的随机字符串
```

不要把 `.env` 提交到 Git。

### 连接 MinerU 3.4.4

```dotenv
FASTGPT_OCR_PROVIDER=mineru
FASTGPT_OCR_API_PROFILE=mineru-api-v3
FASTGPT_OCR_PROVIDER_VERSION=3.4.4
MINERU_BASE_URL=http://host.docker.internal:8000
```

`MINERU_BASE_URL` 只写服务根地址，不要加 `/file_parse`。

### 连接 Marker 1.8-1.10

```dotenv
FASTGPT_OCR_PROVIDER=marker
FASTGPT_OCR_API_PROFILE=marker-server-v1
FASTGPT_OCR_PROVIDER_VERSION=1.10.2
MARKER_BASE_URL=http://host.docker.internal:8000
MARKER_FORCE_OCR=false
```

### 连接 Marker 2.0.0

```dotenv
FASTGPT_OCR_PROVIDER=marker
FASTGPT_OCR_API_PROFILE=marker-server-v2
FASTGPT_OCR_PROVIDER_VERSION=2.0.0
MARKER_BASE_URL=http://host.docker.internal:8000
MARKER_FORCE_OCR=false
MARKER_MODE=balanced
```

`balanced` 适合 GPU 和质量优先场景；`fast` 更偏向 CPU 和速度。适配器会在 readiness
中读取 Marker 的 `/openapi.json`，确认接口参数与所选 Profile 相符。

启动：

```bash
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f adapter
```

开发或离线构建时可以改用：

```bash
docker compose up -d --build
```

## docker-compose.yml 说明

根目录的 Compose 只运行适配器，不会偷偷启动 OCR 模型：

```yaml
name: fastgpt-ocr-adapter

services:
  adapter:
    image: ${FASTGPT_OCR_ADAPTER_IMAGE:-ghcr.io/deepturn/fastgpt-ocr-adapter:0.1.0}
    build:
      context: .
      dockerfile: Dockerfile
    restart: unless-stopped
    env_file:
      - path: .env
        required: false
    ports:
      - "${FASTGPT_OCR_BIND:-127.0.0.1}:${FASTGPT_OCR_PORT:-8001}:8001"
    extra_hosts:
      - "host.docker.internal:host-gateway"
    read_only: true
    tmpfs:
      - /tmp:size=256m,mode=1777
    cap_drop:
      - ALL
    security_opt:
      - no-new-privileges:true
    cpus: ${FASTGPT_OCR_CPU_LIMIT:-1}
    mem_limit: ${FASTGPT_OCR_MEMORY_LIMIT:-512m}
    healthcheck:
      test:
        - CMD
        - python
        - -c
        - >-
          import urllib.request;
          urllib.request.urlopen('http://127.0.0.1:8001/health/ready', timeout=3)
      interval: 15s
      timeout: 5s
      start_period: 10s
      retries: 4
```

几个关键点：

- 默认只监听 `127.0.0.1:8001`，不会直接暴露到公网。
- `host.docker.internal:host-gateway` 让 Linux 容器能访问宿主机上的 OCR 服务。
- 根文件系统只读，上传的 PDF 只写入 256 MiB 的临时目录，处理结束后删除。
- 容器固定一个 Uvicorn worker。多 worker 会各自创建一套队列，无法保证总并发。
- `healthcheck` 检查的是 readiness，上游 OCR 不可用时容器会显示 unhealthy。

如果 FastGPT 在另一台机器，把 `FASTGPT_OCR_BIND` 改成宿主机的私网地址或 `0.0.0.0`，
同时使用防火墙只允许 FastGPT 服务器访问 8001。不要把这个端口直接映射到公网。

## 一起部署 MinerU 3.4.4

仓库提供了完整的 NVIDIA GPU 示例：

```bash
docker compose -f deploy/mineru/docker-compose.yml up -d --build
docker compose -f deploy/mineru/docker-compose.yml logs -f mineru-core
```

这个 Compose 会启动：

- `mineru-core`：官方 `mineru[pipeline]==3.4.4`。
- `adapter`：只对外发布 8001。
- `mineru-models`：保存模型和 `mineru.json`，容器重建后不用重新下载。
- `/work/output`：有容量限制的临时文件系统，不长期保存解析结果。

第一次启动会从 ModelScope 下载 Pipeline 模型，时间取决于网络。模型下载完成之前，
readiness 不会通过。

建议的最低资源：

- Linux x86_64。
- 8 vCPU。
- 24 GiB 内存。
- 1 张至少 8 GiB 显存的 NVIDIA GPU。
- NVIDIA Container Toolkit，`docker run --gpus all` 能正常看到 GPU。

MinerU Core 基于锁定 digest 的 CUDA 12.9 vLLM 镜像。宿主机驱动必须支持对应 CUDA
运行时。适配器和 MinerU 默认都只允许一个执行请求。

停止容器不会删除模型：

```bash
docker compose -f deploy/mineru/docker-compose.yml down
```

只有明确需要重新下载模型时才删除卷：

```bash
docker volume rm fastgpt-ocr-mineru-models
```

## 连接外部 Marker

本项目不发布 Marker Core 镜像。先按照 Marker 官方 README 安装并启动
`marker_server`，确认下面两个地址可访问：

```text
GET  http://<marker-host>:8000/openapi.json
POST http://<marker-host>:8000/marker/upload
```

然后配置 `.env` 中的 Marker Profile，启动专用示例：

```bash
docker compose -f deploy/marker/docker-compose.yml up -d
```

如果 Marker 前面有反向代理鉴权，可以配置：

```dotenv
MARKER_AUTH_TOKEN=反向代理使用的BearerToken
```

这个 Token 只发给 Marker 上游，与 FastGPT 调用适配器使用的
`FASTGPT_OCR_AUTH_TOKEN` 不是一回事。

## 接入 FastGPT

FastGPT 的调用协议是：

```http
POST /v2/parse/file
Authorization: Bearer <token>
Content-Type: multipart/form-data

file=@document.pdf
```

成功响应：

```json
{
  "success": true,
  "message": "",
  "pages": 12,
  "markdown": "# 文档内容"
}
```

给 FastGPT 增加：

```dotenv
CUSTOM_PDF_PARSE_URL=http://<adapter-host>:8001/v2/parse/file
CUSTOM_PDF_PARSE_KEY=与FASTGPT_OCR_AUTH_TOKEN相同的值
```

重启 FastGPT，并在上传 PDF 时启用“增强解析”或 `customPdfParse=true`。

如果 FastGPT 和适配器不在同一个 Compose 网络，不要填写容器名；使用适配器宿主机的
私网 IP。FastGPT 的自定义 PDF 调用窗口是 600 秒，适配器默认上游超时为 540 秒。

先独立验证接口：

```bash
set -a
. ./.env
set +a

curl -fsS \
  -H "Authorization: Bearer $FASTGPT_OCR_AUTH_TOKEN" \
  -F file=@sample.pdf \
  http://127.0.0.1:8001/v2/parse/file
```

## 并发和排队

默认配置：

```dotenv
FASTGPT_OCR_MAX_CONCURRENT_REQUESTS=1
FASTGPT_OCR_MAX_QUEUED_REQUESTS=1
FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS=60
FASTGPT_OCR_TIMEOUT_SECONDS=540
```

含义是：一个请求正在调用 OCR 时，允许另一个请求排队。第三个请求会立即收到
`503 PARSER_BUSY`；排队超过 60 秒会收到 `503 QUEUE_TIMEOUT`。两种响应都带
`Retry-After: 5`。

并发数只控制适配器同时放行多少请求，不会增加 GPU 显存或计算能力。提高
`FASTGPT_OCR_MAX_CONCURRENT_REQUESTS` 前，需要先确认 OCR 服务本身能够安全并发。

默认的 60 秒排队加 540 秒解析已经贴近 FastGPT 的 600 秒上限。生产环境建议把
排队时间改为 15-30 秒，给网络传输和 FastGPT 处理结果留出余量。

## 健康检查

```bash
curl -fsS http://127.0.0.1:8001/health/live
curl -fsS http://127.0.0.1:8001/health/ready
curl -fsS http://127.0.0.1:8001/health
```

`live` 只说明适配器进程活着。`ready` 和 `/health` 还会检查：

- FastGPT Bearer Token 已配置。
- OCR 服务能访问。
- Provider、API Profile 和声明版本受支持。
- MinerU 健康接口版本为 3.4.4。
- Marker `/openapi.json` 与所选 v1/v2 Profile 匹配。

Marker 官方接口没有可靠的软件版本字段，所以健康响应中的 Marker 版本是部署者声明
的预期版本；接口结构仍会实时校验。

## 常见错误

| 状态码 | error | 含义 |
|---|---|---|
| 400 | `EMPTY_FILE` / `INVALID_PDF` / `ENCRYPTED_PDF` | PDF 为空、损坏或加密 |
| 401 | `UNAUTHORIZED` | FastGPT Token 不一致 |
| 413 | `FILE_TOO_LARGE` / `PAGE_LIMIT_EXCEEDED` | 超过大小或页数限制 |
| 415 | `UNSUPPORTED_MEDIA_TYPE` / `INVALID_PDF_TYPE` | 不是 PDF |
| 503 | `PARSER_BUSY` | 执行槽和等待位都满了 |
| 503 | `QUEUE_TIMEOUT` | 排队超过设置时间 |
| 503 | `CORE_UNAVAILABLE` | OCR 服务连接失败 |
| 502 | `CORE_PARSE_FAILED` | OCR 解析失败或返回结构不对 |
| 502 | `IMAGE_CONVERSION_FAILED` | Markdown 图片与图片数据对不上 |
| 504 | `CORE_TIMEOUT` | OCR 执行超过上游超时 |

日志只记录请求 ID、文件大小、页数、耗时、HTTP 状态和上游状态，不记录 Token、PDF
内容、Markdown 或图片 Base64。排查时可以用响应头 `X-Request-ID` 对应日志。

## 增加新的 OCR 服务

新的 OCR 服务不能靠环境变量拼请求字段。需要明确实现一个 Provider：

```python
class ParserProvider(Protocol):
    name: str
    api_profile: str
    version: str

    async def parse(self, path: Path) -> ProviderResult: ...
    async def health(self) -> ProviderHealth: ...
    async def close(self) -> None: ...
```

实现放在 `src/fastgpt_ocr_adapter/providers/`，然后在注册表中登记 Provider、Profile
和支持的版本范围。每个 Profile 自己负责：

- 固定上游请求字段。
- 校验响应 JSON。
- 转换 Markdown 和图片。
- 校验健康接口或 OpenAPI。
- 把上游错误归类成统一错误。

公共 FastGPT 路由不应该出现某个 OCR 服务的字段名，也不接受任意 JSONPath 或透传
规则。

## 本地开发

```bash
python3.11 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.lock

pytest
ruff check src tests
mypy src
docker compose config
```

测试覆盖率门槛为 90%。真实 OCR 验收需要另外准备 MinerU 3.4.4、Marker 1.10.2 或
Marker 2.0.0 服务。

## 镜像和版本

正式发布只使用语义版本和提交 SHA，不发布 `latest`：

```text
ghcr.io/deepturn/fastgpt-ocr-adapter:0.1.0
ghcr.io/deepturn/fastgpt-ocr-adapter:sha-<commit>
ghcr.io/deepturn/fastgpt-mineru-core:3.4.4-cu129
ghcr.io/deepturn/fastgpt-mineru-core:sha-<commit>
```

## 许可证

适配器代码使用 Apache-2.0。

MinerU、Marker、它们的模型权重和基础镜像有各自的许可证。本仓库不改变这些条款。
对外提供商业服务前，请按实际使用的版本检查上游代码和模型许可证。详情见
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。
