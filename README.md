# FastGPT OCR Adapter

A small HTTP adapter that connects FastGPT to a separately deployed OCR API.

FastGPT 把 PDF 发到 `POST /v2/parse/file`，适配器按配置调用 OCR API，再把页数、Markdown 和图片整理成 FastGPT 能读的结果。**镜像里只有适配器，没有 OCR 程序和模型，也不需要 GPU。** OCR 服务要另外部署。

## 1. 选一个 OCR 后端

| Provider | API Profile | OCR 版本 | 验证范围 | 官方部署说明 |
| --- | --- | --- | --- | --- |
| `mineru` | `mineru-api-v3` | `3.4.4`, `3.4.5` | 逐版 CPU Pipeline 驱动实测 | [官方 Docker 教程（3.4.4）](https://github.com/opendatalab/MinerU/blob/mineru-3.4.4-released/docs/zh/quick_start/docker_deployment.md) · [API 使用说明](https://github.com/opendatalab/MinerU/blob/mineru-3.4.4-released/docs/zh/usage/quick_usage.md) |
| `mineru` | `mineru-tasks-v1` | `4.1.0`, `4.1.1`, `4.1.2`, `4.1.3`, `4.1.4`, `4.1.5`, `4.1.6`, `4.1.7`, `4.2.0`, `4.2.1`, `4.2.2`, `4.2.3` | 逐版 CPU Basic 驱动实测；`4.2.3` 另通过 FastGPT `4.17.3` 上传入库验收 | [官方 Docker 教程（4.2.3）](https://github.com/opendatalab/MinerU/blob/mineru-4.2.3-released/docs/zh/quick_start/docker_deployment.md) · [Tasks API](https://github.com/opendatalab/MinerU/blob/mineru-4.2.3-released/docs/zh/usage/tasks.md) |
| `marker` | `marker-server-v1` | `>=1.8,<2.0` | 协议验证 | [Marker 1.10.2 API server](https://github.com/datalab-to/marker/blob/v1.10.2/README.md#api-server) |
| `marker` | `marker-server-v2` | `==2.0.0` | 协议验证 | [Marker 2.0.0 API server](https://pypi.org/project/marker-pdf/2.0.0/#api-server) |

一个适配器实例连接一个后端。MinerU 3.4.x 表中版本使用 `mineru-api` 的 `/file_parse`（Pipeline）；表中的 4.x 版本用 `mineru-kit api-server` 的 `/v1/tasks`，不需要另启 `file-parse-server`。Tasks 返回的上传和下载地址必须与 `MINERU_BASE_URL` 同源。Marker 用官方 `marker_server`，不支持 FastGPT 改造版 Marker。

“协议验证”指核对接口并运行契约测试；“驱动实测”指用官方服务实际识别同一份中文扫描 PDF，检查正文和图片。`4.2.3` 的接口实测返回 1 页、中文 Markdown 和 1 张 JPEG；首次请求含模型下载耗时 40.34 秒，MinerU 进程峰值 RSS 约 1.06 GiB。单页样例不能用来估算长文档或多并发的资源。

用 `0.1.3` 适配器（`auto` 模式）和单独部署的 MinerU `4.2.3`，在 FastGPT `4.17.3` 开启增强 PDF 解析后上传同一份文件，读回了知识库里的中文正文，也从 FastGPT 下载到了入库后的 JPEG。测试使用本地向量模型替身，没有评估检索效果。

`4.0.0`–`4.0.11` 使用 Jobs API，`4.0.12` 另有过渡版 Tasks API。这 13 个版本都用原生 Jobs API 跑通了同一份扫描件，但不兼容本适配器的 `mineru-tasks-v1`，因此不在支持表内。

## 2. 启动适配器

在 Linux x86_64 上，用 Docker 和 Compose 启动。下载这份 [docker-compose.yml](docker-compose.yml)，不需要克隆仓库或准备 `.env`。

先改 YAML，再启动：

| 参数 | 怎么填 |
| --- | --- |
| `FASTGPT_OCR_AUTH_TOKEN` | 换成自己的访问密钥，可用 `openssl rand -hex 32` 生成。 |
| `FASTGPT_OCR_PROVIDER`、`FASTGPT_OCR_API_PROFILE`、`FASTGPT_OCR_PROVIDER_VERSION` | 对照上表填写，版本号填实际安装的版本。 |
| `MINERU_BASE_URL` / `MARKER_BASE_URL` | 填选中后端的地址，例如 `http://192.0.2.10:8000`。不用加 `/file_parse`、`/v1/tasks` 或 `/marker/upload`。 |
| `MINERU_AUTH_TOKEN` | 用于 MinerU Tasks API。若 MinerU 启用了 API Key，就填它的 Key；它不是 FastGPT 调用适配器的密钥。 |
| `MARKER_FORCE_OCR`、`MARKER_MODE`、`MARKER_AUTH_TOKEN` | 分别用于强制 OCR、v2 的 `balanced` / `fast` 模式、Marker 上游的 Bearer Token。没有特殊要求可保留默认值。 |

端口默认只绑定宿主机的 `127.0.0.1:8001`。如果 FastGPT 跑在 Docker 容器内或另一台机器上，可以把端口绑定改成宿主机私网 IP，并在网络侧限制只有 FastGPT 能访问。也可以把 FastGPT 和适配器接到同一个 Docker 网络，用 `http://adapter:8001` 访问。容器里的 `127.0.0.1` 不是宿主机；OCR 跑在宿主机时，可以用 `host.docker.internal` 前提是 OCR 已监听容器能访问的地址。

```bash
docker compose config --quiet
docker compose pull
docker compose up -d
curl -fsS http://127.0.0.1:8001/health/ready
```

如果改了端口绑定，最后一行也要用改后的地址。`/health/live` 只检查适配器进程；`/health/ready` 返回 `ready` 才说明鉴权已配置、上游 API 能连通且通过协议检查。Marker 的版本来自配置，接口结构通过 OpenAPI 检查。密钥写在 YAML 里，别提交部署后的文件。

**自动识别（可选）：** 可以把 `FASTGPT_OCR_API_PROFILE` 和 `FASTGPT_OCR_PROVIDER_VERSION` 都设成 `auto`，让适配器启动时从 MinerU 的健康接口识别；识别出的版本仍须在上表里。生产环境也可以保留明确的 Profile 和版本号，避免上游升级后配置含义发生变化。

`auto` 只用于 MinerU。上游还没启动或暂时无法识别时，适配器会在后台重试，间隔从 1 秒逐步增加到最多 30 秒。这期间 `/health/ready` 和解析接口返回 `503`，不会用上传的 PDF 试探上游。识别成功后自动恢复；如果之后 MinerU 临时掉线，适配器仍使用已选的驱动。更换上游版本或协议后，重新创建适配器容器才会重新识别。

## 3. 接入 FastGPT

先拿一份 PDF 测试。把地址和 Token 换成你的配置：

```bash
curl -fsS http://127.0.0.1:8001/v2/parse/file \
  -H 'Authorization: Bearer YOUR_ADAPTER_TOKEN' \
  -F 'file=@sample.pdf;type=application/pdf'
```

成功示例：`{"success":true,"message":"","pages":12,"markdown":"..."}`。

FastGPT 若随文件发送页眉页脚、附录、图片分析或图表分析开关，适配器会接收这些开关，但不会把它们转发给 OCR，也不会据此改变解析结果。

在 FastGPT 中选择自定义 PDF 解析，URL 填 FastGPT 容器能访问的完整地址，例如 `http://adapter:8001/v2/parse/file`，Key 填 `FASTGPT_OCR_AUTH_TOKEN`。使用环境变量配置的版本（例如 [4.15.3](https://github.com/labring/FastGPT/blob/v4.15.3/packages/service/common/file/read/utils.ts)），填写 `CUSTOM_PDF_PARSE_URL` 和 `CUSTOM_PDF_PARSE_KEY` 后重启 FastGPT。导入 PDF 时打开增强 PDF 解析；`customPdfParse` 是导入选项，不是环境变量。

## 排队和排错

- 默认同时解析 1 份、再排 1 份。用 `FASTGPT_OCR_MAX_CONCURRENT_REQUESTS`、`FASTGPT_OCR_MAX_QUEUED_REQUESTS` 和 `FASTGPT_OCR_QUEUE_TIMEOUT_SECONDS` 调整。等待位设为 `0` 就不排队。只有 OCR 服务扛得住时才提高并发。
- 默认排队最多 60 秒、上游解析最多 540 秒（`FASTGPT_OCR_TIMEOUT_SECONDS`）。如果 FastGPT 的超时是 600 秒，可先把排队时间调到 15–30 秒，给上传和返回结果留出时间。PDF 默认最多 50 MiB、500 页，可改 `FASTGPT_OCR_MAX_FILE_BYTES` 和 `FASTGPT_OCR_MAX_PAGES`。
- `401`：核对 FastGPT 的 Key。 `503 PARSER_BUSY` / `QUEUE_TIMEOUT`：队列满了或等太久。 `503 CORE_UNAVAILABLE`：先检查 OCR 地址和网络。 `504 CORE_TIMEOUT`：上游超时。容器日志用 `docker compose logs --tail=100 adapter` 查看。

## 参与开发

新增 OCR 后端、运行测试或维护镜像，请看 [贡献指南](CONTRIBUTING.md)。

适配器使用 Apache-2.0。OCR 服务和模型权重遵循各自的[上游许可证](THIRD_PARTY_NOTICES.md)。
