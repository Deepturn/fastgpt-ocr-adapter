# 客户部署文件

这份 Compose 只启动 FastGPT OCR Adapter，不启动、不内嵌 MinerU 或 Marker。

客户先按官方方式部署自己的 OCR 服务，再通过 YAML 中的 `Provider + API Profile + 上游地址`
选择对应驱动。一个 Adapter 实例只连接一种 OCR 服务；切换后需要重启容器。

```text
FastGPT -> Adapter:8001 -> 客户自己的 MinerU / Marker
```

## 当前 Provider 清单

| Provider | API Profile | 支持版本 | 客户需要配置 |
| --- | --- | --- | --- |
| `mineru` | `mineru-api-v3` | `==3.4.4` | `MINERU_BASE_URL` |
| `marker` | `marker-server-v1` | `>=1.8,<2.0` | `MARKER_BASE_URL`、`MARKER_FORCE_OCR` |
| `marker` | `marker-server-v2` | `==2.0.0` | v1 配置加 `MARKER_MODE` |

这张表与代码注册表保持一致。以后新增 Provider 或 API Profile 时，必须在同一个提交中
更新这张表、下面的配置示例和官方部署资料；CI 会检查是否遗漏表格记录。

## 1. 下载 YAML

```bash
curl -fsSLo docker-compose.yml \
  https://raw.githubusercontent.com/Deepturn/fastgpt-ocr-adapter/main/deploy/customer/docker-compose.yml
```

不需要 `.env` 文件。

## 2. 修改 Token

生成一个随机 Token：

```bash
openssl rand -hex 32
```

把 YAML 中的占位符替换成生成结果：

```yaml
FASTGPT_OCR_AUTH_TOKEN: REPLACE_WITH_RANDOM_TOKEN
```

这个值还需要配置到 FastGPT 的 `CUSTOM_PDF_PARSE_KEY`。

## 3. 选择 OCR 驱动

### MinerU 3.4.4

```yaml
FASTGPT_OCR_PROVIDER: mineru
FASTGPT_OCR_API_PROFILE: mineru-api-v3
FASTGPT_OCR_PROVIDER_VERSION: "3.4.4"
MINERU_BASE_URL: http://实际MinerU地址:8000
```

`MINERU_BASE_URL` 只写服务根地址，不要加 `/file_parse`。

### Marker 1.8-1.10

```yaml
FASTGPT_OCR_PROVIDER: marker
FASTGPT_OCR_API_PROFILE: marker-server-v1
FASTGPT_OCR_PROVIDER_VERSION: "1.10.2"
MARKER_BASE_URL: http://实际Marker地址:8000
MARKER_FORCE_OCR: "false"
```

### Marker 2.0.0

```yaml
FASTGPT_OCR_PROVIDER: marker
FASTGPT_OCR_API_PROFILE: marker-server-v2
FASTGPT_OCR_PROVIDER_VERSION: "2.0.0"
MARKER_BASE_URL: http://实际Marker地址:8000
MARKER_FORCE_OCR: "false"
MARKER_MODE: balanced
```

Marker 的 `balanced` 更偏向质量，`fast` 更偏向速度。不同 OCR 版本不能只改版本号，
必须同时选择匹配的 API Profile。

OCR 服务部署在 Adapter 宿主机时，可以使用：

```yaml
MINERU_BASE_URL: http://host.docker.internal:8000
```

OCR 服务部署在其他服务器时，改成那台服务器的私网 IP。不要填写 `127.0.0.1`，
因为容器里的 `127.0.0.1` 指向 Adapter 容器自己。

## 4. 启动

阿里云 ACR 是私有仓库时先登录：

```bash
docker login crpi-g79ks4g398u6l56b.cn-hangzhou.personal.cr.aliyuncs.com
```

然后启动：

```bash
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f adapter
```

`docker compose ps` 中显示 `healthy`，说明 Adapter 已连接到所选 OCR 服务且接口结构匹配。

## 5. 接入 FastGPT

在 FastGPT 中配置：

```dotenv
CUSTOM_PDF_PARSE_URL=http://<Adapter服务器私网IP>:8001/v2/parse/file
CUSTOM_PDF_PARSE_KEY=YAML中的FASTGPT_OCR_AUTH_TOKEN
customPdfParse=true
```

测试 Adapter：

```bash
curl -fS -X POST http://127.0.0.1:8001/v2/parse/file \
  -H "Authorization: Bearer REPLACE_WITH_RANDOM_TOKEN" \
  -F "file=@sample.pdf"
```

成功响应格式：

```json
{
  "success": true,
  "message": "",
  "pages": 12,
  "markdown": "..."
}
```

## 参数说明

| 参数 | 默认值 | 作用 |
| --- | --- | --- |
| `adapter.image` | ACR `adapter:0.1.0` | 中间件镜像地址。它不包含 OCR 模型。 |
| `FASTGPT_OCR_AUTH_TOKEN` | 占位符 | 必填。必须与 FastGPT 的 `CUSTOM_PDF_PARSE_KEY` 相同。 |
| `FASTGPT_OCR_PROVIDER` | `mineru` | 驱动名称，目前支持 `mineru`、`marker`。 |
| `FASTGPT_OCR_API_PROFILE` | `mineru-api-v3` | 具体接口处理逻辑，必须与 OCR 版本匹配。 |
| `FASTGPT_OCR_PROVIDER_VERSION` | `3.4.4` | 预期 OCR 版本，用于健康检查和版本约束。 |
| `MINERU_BASE_URL` | 宿主机 8000 | MinerU 服务根地址，仅 MinerU 驱动使用。 |
| `MARKER_BASE_URL` | 宿主机 8000 | Marker 服务根地址，仅 Marker 驱动使用。 |
| `MARKER_FORCE_OCR` | `false` | 是否强制 Marker 使用 OCR。 |
| `MARKER_MODE` | `balanced` | Marker 2.0.0 模式，可选 `balanced`、`fast`。 |
| `MARKER_AUTH_TOKEN` | 空 | Marker 上游存在 Bearer 鉴权时填写。 |
| `FASTGPT_OCR_TIMEOUT_SECONDS` | `540` | 调用 OCR 服务的超时时间，必须小于 600 秒。 |
| `FASTGPT_OCR_MAX_FILE_BYTES` | `52428800` | PDF 大小上限，即 50 MiB。 |
| `FASTGPT_OCR_MAX_PAGES` | `500` | PDF 页数上限。 |
| `FASTGPT_OCR_MAX_CONCURRENT_REQUESTS` | `1` | 同时调用上游 OCR 的请求数。 |
| `FASTGPT_OCR_MAX_QUEUED_REQUESTS` | `1` | 执行槽满时允许等待的请求数。 |
| `FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS` | `60` | 最长排队时间；生产环境建议调为 15-30 秒。 |
| `ports` | `8001:8001` | Adapter 对外端口。应通过防火墙限制为 FastGPT 可访问。 |
| `cpus` / `mem_limit` | `1` / `512m` | Adapter 自身资源限制，不代表 OCR 服务资源。 |

## 健康检查

```bash
curl -fsS http://127.0.0.1:8001/health/ready
```

返回内容包含：

```json
{
  "status": "ready",
  "provider": "mineru",
  "api_profile": "mineru-api-v3",
  "version": "3.4.4"
}
```

如果 Adapter 显示 `unhealthy`，先检查上游地址：

```bash
docker compose logs --tail=200 adapter
curl http://<OCR服务器地址>:8000/health
```

Marker 的就绪检查使用 `/openapi.json`。MinerU 和 Marker 都由客户独立维护，Adapter
不会下载模型，也不需要 GPU。

## 官方 OCR 部署资料

- MinerU Docker：https://opendatalab.github.io/MinerU/quick_start/docker_deployment/
- MinerU 使用说明：https://opendatalab.github.io/MinerU/usage/quick_usage/
- Marker 2.x：https://github.com/datalab-to/marker/blob/master/README.md
- Marker 1.10：https://github.com/datalab-to/marker/blob/v1.10.2/README.md

## 停止

```bash
docker compose down
```

这只停止 Adapter，不会影响客户自己的 OCR 服务。
