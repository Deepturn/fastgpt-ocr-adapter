# 客户部署文件

这份 `docker-compose.yml` 只启动 FastGPT OCR Adapter，不带 OCR 模型，也不需要 `.env`。
把里面的占位符换成你自己的值，就能直接用。

## 现在支持什么

| Provider | API Profile | 支持版本 | 你要填的东西 |
| --- | --- | --- | --- |
| `mineru` | `mineru-api-v3` | `==3.4.4` | `MINERU_BASE_URL` |
| `marker` | `marker-server-v1` | `>=1.8,<2.0` | `MARKER_BASE_URL`、`MARKER_FORCE_OCR` |
| `marker` | `marker-server-v2` | `==2.0.0` | v1 配置加 `MARKER_MODE` |

这张表和代码是一一对应的。以后如果要加新的 Provider，表和代码要一起改。

## 你只需要改这几处

1. `FASTGPT_OCR_AUTH_TOKEN`

   这是 Adapter 对外的密码。随便生成一个 32 位左右的随机串就行，FastGPT 里也要填同一个值。

2. `FASTGPT_OCR_PROVIDER` / `FASTGPT_OCR_API_PROFILE` / `FASTGPT_OCR_PROVIDER_VERSION`

   - 用 MinerU 就选 `mineru` + `mineru-api-v3`
   - 用 Marker 1.x 就选 `marker` + `marker-server-v1`
   - 用 Marker 2.0.0 就选 `marker` + `marker-server-v2`

3. OCR 服务地址

   - MinerU：填 `MINERU_BASE_URL`
   - Marker：填 `MARKER_BASE_URL`
   - 如果 OCR 跑在同一台机器上，可以用 `http://host.docker.internal:8000`
   - 如果 OCR 跑在别的机器上，就填那台机器的私网 IP

4. Marker 额外参数

   - `MARKER_FORCE_OCR`：一般先用 `false`
   - `MARKER_MODE`：只给 Marker v2 用，常用 `balanced`
   - `MARKER_AUTH_TOKEN`：上游 Marker 自己还要鉴权时再填

## 怎么启动

如果你是直接拿这个文件用：

```bash
docker login crpi-g79ks4g398u6l56b.cn-hangzhou.personal.cr.aliyuncs.com
docker compose config
docker compose pull
docker compose up -d
docker compose ps
docker compose logs -f adapter
```

如果 `docker compose ps` 里显示 `healthy`，就说明 Adapter 已经连上你选的 OCR 服务了。

## FastGPT 里怎么填

```dotenv
CUSTOM_PDF_PARSE_URL=http://<Adapter服务器私网IP>:8001/v2/parse/file
CUSTOM_PDF_PARSE_KEY=YAML 里的 FASTGPT_OCR_AUTH_TOKEN
customPdfParse=true
```

## 先测一下

```bash
curl -fS -X POST http://127.0.0.1:8001/v2/parse/file \
  -H "Authorization: Bearer REPLACE_WITH_RANDOM_TOKEN" \
  -F "file=@sample.pdf"
```

成功的话，会返回：

```json
{
  "success": true,
  "message": "",
  "pages": 12,
  "markdown": "..."
}
```

## 常见坑

- `127.0.0.1` 只能给同一台机器用，别拿去填另一台机器的 OCR 地址。
- 如果 OCR 在别的机器上，别写容器名，要写那台机器的私网 IP。
- `503` 一般是队列满了，或者上游 OCR 忙了。
- `415` 一般是传了不是 PDF 的文件。

## 官方 OCR 资料

- MinerU：[Docker 部署教程](https://opendatalab.github.io/MinerU/quick_start/docker_deployment/)
- MinerU：[快速使用和 API 说明](https://opendatalab.github.io/MinerU/usage/quick_usage/)
- Marker 2.x：[官方 README](https://github.com/datalab-to/marker/blob/master/README.md)
- Marker 1.10：[v1.10.2 官方 README](https://github.com/datalab-to/marker/blob/v1.10.2/README.md)
- Marker 2.0.0：[PyPI 页面](https://pypi.org/project/marker-pdf/2.0.0/)

## 停止

```bash
docker compose down
```

这只会停 Adapter，不会动你自己部署的 OCR 服务。
