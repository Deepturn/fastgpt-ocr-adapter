# 单容器部署

这个目录里的 `docker-compose.yml` 只启动 FastGPT OCR Adapter。
它不包含 OCR 模型，也不会帮你启动 MinerU 或 Marker。

## 支持哪些后端

| Provider | API Profile | 支持版本 | 需要配置 |
| --- | --- | --- | --- |
| `mineru` | `mineru-api-v3` | `==3.4.4` | `MINERU_BASE_URL` |
| `marker` | `marker-server-v1` | `>=1.8,<2.0` | `MARKER_BASE_URL`、`MARKER_FORCE_OCR` |
| `marker` | `marker-server-v2` | `==2.0.0` | v1 配置加 `MARKER_MODE` |

新增 Provider 时，这张表要和代码注册表一起更新。

## 先改配置

打开 `docker-compose.yml`，至少改这几处：

1. `FASTGPT_OCR_AUTH_TOKEN`

   Adapter 对外的访问 Token。FastGPT 里也要填同一个值。

2. `FASTGPT_OCR_PROVIDER` / `FASTGPT_OCR_API_PROFILE` / `FASTGPT_OCR_PROVIDER_VERSION`

   - MinerU 3.4.4：`mineru` + `mineru-api-v3`
   - Marker 1.x：`marker` + `marker-server-v1`
   - Marker 2.0.0：`marker` + `marker-server-v2`

3. OCR 服务地址

   - MinerU：改 `MINERU_BASE_URL`
   - Marker：改 `MARKER_BASE_URL`
   - OCR 跑在同一台机器上，可以用 `http://host.docker.internal:8000`
   - OCR 跑在别的机器上，填那台机器的私网 IP

4. Marker 额外参数

   - `MARKER_FORCE_OCR`：一般先用 `false`
   - `MARKER_MODE`：Marker v2 使用，常用 `balanced`
   - `MARKER_AUTH_TOKEN`：只有上游 Marker 自己需要 Bearer Token 时才填

## 启动

```bash
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f adapter
```

`docker compose ps` 里显示 `healthy`，说明 Adapter 已经能连上你配置的 OCR 服务。
如果你把镜像地址换成了私有仓库，先执行对应仓库的 `docker login`。

## 接入 FastGPT

```dotenv
CUSTOM_PDF_PARSE_URL=http://<Adapter服务器私网IP>:8001/v2/parse/file
CUSTOM_PDF_PARSE_KEY=YAML 里的 FASTGPT_OCR_AUTH_TOKEN
customPdfParse=true
```

## 测试一下

```bash
curl -fS -X POST http://127.0.0.1:8001/v2/parse/file \
  -H "Authorization: Bearer REPLACE_WITH_RANDOM_TOKEN" \
  -F "file=@sample.pdf"
```

成功时会返回：

```json
{
  "success": true,
  "message": "",
  "pages": 12,
  "markdown": "..."
}
```

## 常见坑

- `127.0.0.1` 只代表当前容器或当前机器。OCR 在另一台机器上时，填私网 IP。
- 不同 OCR 版本要选对应的 API Profile，不能只改版本号。
- `503` 通常是队列满了，或者上游 OCR 正忙。
- `415` 通常是传了非 PDF 文件。

## OCR 官方资料

- MinerU：[Docker 部署教程](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)
- MinerU：[快速使用和 API 说明](https://opendatalab.github.io/MinerU/usage/quick_usage/)
- Marker 2.x：[官方 README](https://github.com/datalab-to/marker/blob/master/README.md)
- Marker 1.10：[v1.10.2 官方 README](https://github.com/datalab-to/marker/blob/v1.10.2/README.md)
- Marker 2.0.0：[PyPI 页面](https://pypi.org/project/marker-pdf/2.0.0/)

## 停止

```bash
docker compose down
```

这只会停止 Adapter，不会影响你自己部署的 OCR 服务。
