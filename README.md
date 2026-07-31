# FastGPT OCR Adapter

这个仓库只做一件事：把 FastGPT 的 PDF 解析请求转给你自己部署的 OCR 服务。
它不改上游 OCR 源码，也不自带 OCR 模型。

## 支持哪些后端

当前支持 2 个 Provider、3 个 API Profile。
一个实例只选一个 Provider / Profile，换 OCR 服务或版本就改配置再重启。

| Provider | API Profile | 支持版本 | 上游接口 | 主要配置 |
| --- | --- | --- | --- | --- |
| `mineru` | `mineru-api-v3` | `==3.4.4` | 官方 `/file_parse` | `MINERU_BASE_URL` |
| `marker` | `marker-server-v1` | `>=1.8,<2.0` | 官方 `/marker/upload` | `MARKER_BASE_URL`、`MARKER_FORCE_OCR` |
| `marker` | `marker-server-v2` | `==2.0.0` | 官方 `/marker/upload` | v1 配置加 `MARKER_MODE` |

## 最快上手

如果你只是想先跑起来，直接用 `deploy/customer/docker-compose.yml`。
这份文件不需要 `.env`，把里面的占位符换掉就行。

1. 先把 OCR 服务单独跑起来。

   - MinerU：[Docker 部署教程](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)
   - MinerU：[快速使用和 API 说明](https://opendatalab.github.io/MinerU/usage/quick_usage/)
   - Marker 2.x：[官方 README](https://github.com/datalab-to/marker/blob/master/README.md)
   - Marker 1.10：[v1.10.2 官方 README](https://github.com/datalab-to/marker/blob/v1.10.2/README.md)
   - Marker 2.0.0：[PyPI 页面](https://pypi.org/project/marker-pdf/2.0.0/)

2. 启动 Adapter。

   ```bash
   docker compose -f deploy/customer/docker-compose.yml up -d
   ```

3. 改好这几个值。

   - `FASTGPT_OCR_AUTH_TOKEN`：对外 Token，FastGPT 也要填同一个
   - `FASTGPT_OCR_PROVIDER`：`mineru` 或 `marker`
   - `FASTGPT_OCR_API_PROFILE`：对应的 API Profile
   - `FASTGPT_OCR_PROVIDER_VERSION`：对应版本
   - `MINERU_BASE_URL` 或 `MARKER_BASE_URL`：OCR 服务地址
   - `MARKER_MODE`：只给 Marker v2 用

4. 在 FastGPT 里填这两个值。

   ```dotenv
   CUSTOM_PDF_PARSE_URL=http://<adapter-ip>:8001/v2/parse/file
   CUSTOM_PDF_PARSE_KEY=和 YAML 里的 Token 一样
   customPdfParse=true
   ```

5. 简单测一下。

   ```bash
   curl -fS -H "Authorization: Bearer <token>" \
     -F "file=@sample.pdf" \
     http://127.0.0.1:8001/v2/parse/file
   ```

## 你要知道的几件事

- Adapter 只负责鉴权、排队、转请求、整理结果。
- OCR 服务自己部署，自己管资源。
- Adapter 不下载模型，也不接管 GPU。
- `127.0.0.1` 只能给同一台机器用；OCR 在别的机器上时，请填私网 IP。
- `503 PARSER_BUSY` 或 `503 QUEUE_TIMEOUT` 说明队列满了，等一会儿或调大并发。

## 官方 OCR 资料

- [MinerU 3.4.4 Release](https://github.com/opendatalab/MinerU/releases/tag/mineru-3.4.4-released)
- [MinerU 官方部署文档](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)
- [MinerU 官方使用文档](https://opendatalab.github.io/MinerU/usage/quick_usage/)
- [Marker 官方 README](https://github.com/datalab-to/marker/blob/master/README.md)
- [Marker 1.10.2 README](https://github.com/datalab-to/marker/blob/v1.10.2/README.md)
- [Marker 2.0.0 PyPI](https://pypi.org/project/marker-pdf/2.0.0/)

## 出问题先看

- `health/ready` 不通过，先看 OCR 地址和版本是不是对的。
- 解析时报 `415`，多半是上传的不是 PDF。
- 解析时报 `503`，通常是队列满了，或者上游 OCR 不可用。

## 单文件交付

如果你要直接给客户一份文件，就看 [`deploy/customer/docker-compose.yml`](deploy/customer/docker-compose.yml) 和 [`deploy/customer/README.md`](deploy/customer/README.md)。

## 许可证

适配器代码使用 Apache-2.0。MinerU、Marker 以及它们的模型权重各自遵循上游许可证。
