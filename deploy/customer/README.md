# 客户部署文件

这套 Compose 用来在一台有 NVIDIA GPU 的 Linux 服务器上启动：

- `mineru-core`：官方 MinerU 3.4.4 Pipeline 服务，第一次启动会下载模型。
- `adapter`：给 FastGPT 使用的固定接口，只对外暴露 8001 端口。

适配器不会把 MinerU 的 8000 端口发布到宿主机，两个容器通过 Docker 内网通信。

## 1. 准备文件

把 `docker-compose.yml` 和 `.env.example` 放到同一个目录，然后执行：

```bash
cp .env.example .env
openssl rand -hex 32
```

把随机字符串填到 `.env` 的 `FASTGPT_OCR_AUTH_TOKEN`。`.env` 只保存在服务器，不要提交到 Git。

## 2. 登录镜像仓库

适配器示例镜像在阿里云 ACR，MinerU Core 默认在 GHCR。按客户实际镜像地址登录：

```bash
docker login crpi-g79ks4g398u6l56b.cn-hangzhou.personal.cr.aliyuncs.com
docker login ghcr.io
```

如果客户不能访问 GHCR，先把 MinerU Core 镜像复制到客户自己的仓库，然后把 `.env` 中的
`MINERU_CORE_IMAGE` 改成新地址。不要把仓库密码写进 YAML 或 `.env` 并提交到代码仓库。

## 3. 启动和检查

```bash
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f mineru-core
```

第一次启动会下载 Pipeline 模型，可能需要较长时间。模型保存在名为
`fastgpt-ocr-mineru-models` 的 Docker volume 中，重启和升级适配器不会重复下载。

确认适配器就绪：

```bash
curl -fsS http://127.0.0.1:8001/health/ready
```

测试接口：

```bash
curl -fS -X POST http://127.0.0.1:8001/v2/parse/file \
  -H "Authorization: Bearer ${FASTGPT_OCR_AUTH_TOKEN}" \
  -F "file=@sample.pdf"
```

## 4. FastGPT 配置

在 FastGPT 的环境变量中填写：

```dotenv
CUSTOM_PDF_PARSE_URL=http://<适配器服务器私网IP>:8001/v2/parse/file
CUSTOM_PDF_PARSE_KEY=与 .env 中 FASTGPT_OCR_AUTH_TOKEN 完全相同
customPdfParse=true
```

如果 FastGPT 与适配器在同一台服务器，可以把 `FASTGPT_OCR_BIND` 保持为
`127.0.0.1`，并通过宿主机或本机网络访问；如果 FastGPT 在另一台服务器，
将它改为适配器服务器私网 IP，并在防火墙中只允许 FastGPT 的 IP 访问 8001。

## 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `FASTGPT_OCR_ADAPTER_IMAGE` | ACR `adapter:0.1.0` | 适配器镜像地址和版本。升级时改明确版本，不使用 `latest`。 |
| `MINERU_CORE_IMAGE` | GHCR `3.4.4-cu129` | MinerU Core 镜像。客户可替换成自己的镜像仓库地址。 |
| `FASTGPT_OCR_AUTH_TOKEN` | 无 | 适配器 Bearer Token；必须与 FastGPT 的 `CUSTOM_PDF_PARSE_KEY` 相同。 |
| `FASTGPT_OCR_REQUIRE_AUTH` | `true` | 是否强制校验 Token，生产环境保持 `true`。 |
| `FASTGPT_OCR_TIMEOUT_SECONDS` | `540` | 单个文件调用上游的最长时间，单位秒。 |
| `FASTGPT_OCR_MAX_FILE_BYTES` | `52428800` | 上传文件大小上限，单位字节，即 50 MiB。 |
| `FASTGPT_OCR_MAX_PAGES` | `500` | PDF 页数上限。 |
| `FASTGPT_OCR_MAX_CONCURRENT_REQUESTS` | `1` | 同时执行的 OCR 请求数；不会增加 GPU 能力。 |
| `FASTGPT_OCR_MAX_QUEUED_REQUESTS` | `1` | 执行槽满时允许等待的请求数；再多返回 `503 PARSER_BUSY`。 |
| `FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS` | `60` | 请求在队列中最长等待时间，超时返回 `503 QUEUE_TIMEOUT`。建议 15-30 秒。 |
| `FASTGPT_OCR_PROVIDER` | `mineru` | 当前适配器使用的 Provider。本文件只配置 MinerU。 |
| `FASTGPT_OCR_API_PROFILE` | `mineru-api-v3` | Provider 的接口版本配置。必须与 Provider 版本匹配。 |
| `FASTGPT_OCR_PROVIDER_VERSION` | `3.4.4` | readiness 展示和校验的预期版本。 |
| `FASTGPT_OCR_BIND` | `127.0.0.1` | 适配器宿主机监听地址；跨主机调用时改为私网 IP。 |
| `FASTGPT_OCR_PORT` | `8001` | 宿主机映射端口，容器内固定为 8001。 |
| `MINERU_API_MAX_CONCURRENT_REQUESTS` | `1` | MinerU Core 自身并发上限，建议与适配器执行并发一致。 |
| `MINERU_API_TASK_RETENTION_SECONDS` | `900` | MinerU Core 任务临时信息保留时间。 |
| `MINERU_PROCESSING_WINDOW_SIZE` | `1` | MinerU Pipeline 处理窗口；显存紧张时保持 1。 |
| `MINERU_CORE_CPU_LIMIT` | `8` | MinerU Core CPU 限制。 |
| `MINERU_CORE_MEMORY_LIMIT` | `24g` | MinerU Core 内存限制。 |
| `MINERU_SHM_SIZE` | `16gb` | Core 的共享内存大小；文档较大时不要随意调小。 |
| `MINERU_OUTPUT_TMPFS_SIZE` | `8g` | 解析输出临时空间上限，容器重启后清空。 |
| `MINERU_MODELS_VOLUME` | `fastgpt-ocr-mineru-models` | 模型持久化卷名称。不要在运行中随意修改，否则会重新下载模型。 |

## 常见问题

### `mineru-core` 一直 unhealthy

先看日志：

```bash
docker compose logs --tail=200 mineru-core
```

常见原因是 GPU 不可用、模型仍在下载、显存或内存不足。宿主机先确认：

```bash
nvidia-smi
docker run --rm --gpus all nvidia/cuda:12.9.0-base-ubuntu24.04 nvidia-smi
```

### 返回 `503 PARSER_BUSY` 或 `503 QUEUE_TIMEOUT`

这表示适配器正在保护上游服务。只有在确认 MinerU 能承受并发、并且显存足够时，
才提高 `FASTGPT_OCR_MAX_CONCURRENT_REQUESTS` 和 `MINERU_API_MAX_CONCURRENT_REQUESTS`。

### FastGPT 连接不上

确认 FastGPT 使用的是：

```text
http://<适配器服务器私网IP>:8001/v2/parse/file
```

并检查服务器防火墙、`FASTGPT_OCR_BIND` 和 Token 是否一致。不要把 URL 写成
`/file_parse`，那是 MinerU Core 的内部接口。

## 停止和回退

```bash
docker compose down
```

这不会删除模型卷。需要重新启用时直接执行 `docker compose up -d`。
只有确认要重新下载模型才删除卷：

```bash
docker volume rm fastgpt-ocr-mineru-models
```
