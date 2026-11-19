# 贡献指南

## 本地检查

用 Python 3.11。在仓库根目录运行：

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.lock
ruff check src tests
mypy src
pytest
docker compose config --quiet
docker compose config --services
```

最后一条命令应只输出 `adapter`。单元和契约测试不用启动 OCR 或 FastGPT。

## 新增 OCR 后端

在 `src/fastgpt_ocr_adapter/providers/` 下实现驱动，在同目录的 `registry.py` 声明 Provider、API Profile 和支持版本。不同上游协议用不同 Profile；接口一致的版本复用同一个 Profile。保持对 FastGPT 的接口、字段和响应不变，不要把 OCR 程序或模型加入适配器镜像。

提交前补齐请求映射、健康检查和异常响应的测试，并更新 README 支持表及官方部署链接。区分契约测试、真 OCR 和 FastGPT 入库三种结果。没有跑过真服务的版本不要标成实测。

## 发布镜像（维护者）

发布工作流从 Git 标签构建 GHCR 镜像。需要同步到阿里云时，运行 **Mirror a released adapter image to Alibaba ACR**，填已有的 GHCR 版本号。同步流程不重建，推送后会回拉并核对 `linux/amd64` 的镜像 ID；来源证明和 SBOM 以 GHCR 为准。不要覆盖已发布的版本标签。
