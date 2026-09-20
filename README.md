# 🌍 观审 · 广告宣传审核平台

使用 Dify 执行海报生成、实际画面识别、法规审核、自动修改和复审，提供中文操作界面。

## 功能

- **生成并审核**：填写产品事实及设计需求，生成海报并审核，最多自动修改两次。
- **上传海报审核**：上传 PNG/JPG/WebP 原图，返回风险、法条及修改建议，不自动改图。
- **任务记录**：保存进度、各轮图片、审核报告；通过后下载海报。
- **严格放行**：无法读取、需人工核实、接口失败或未通过时，不提供通过版下载。

## 运行要求

- Python 3.12 或更新版本、Pillow。
- 可访问的 Dify 实例（已在 Dify 1.17.0 实测）。
- Dify 中配置 DeepSeek 模型以及 APIMart 服务密钥，账户需有调用额度。

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp platform/.env.example platform/.env
```

1. 将 `workflows/ad-review.yml` 导入 Dify。
2. 配置 DeepSeek 模型，填写工作流环境变量 `APIMART_API_KEY`，发布工作流。
3. 在该应用的 API 访问点创建专用密钥。
4. 编辑 `platform/.env`，填写 `DIFY_API_BASE`（以 `/v1` 结尾）及 `DIFY_API_KEY`。
5. 启动：

```bash
python platform/server.py
```

打开 **http://127.0.0.1:8790**。需保持后台及 Dify 运行。

本地 Docker Dify 常用 API 地址为 `http://127.0.0.1:8080/v1`，请按实际部署修改。

## 系统结构

浏览器 → Python 后台 → Dify Service API → 生图/视觉识别/法规判断 → 本地任务与图片归档 → 页面展示与下载。

前端不持有 Dify 或模型密钥。后端调用 `POST /v1/workflows/run`，通过 SSE 同步进度。任务保存在 `platform/data/tasks.sqlite3`，图片在同目录的任务文件夹内。

上传原图限制为5MB、2000万像素，支持静态PNG/JPG/WebP。当前生图归档只允许已验证的 `getapib.org` 图像来源；更换服务商时需调整可信来源及测试。

## 测试

```bash
python -m unittest discover -s platform -p 'test_*.py'
```

已覆盖严格审核结果解析、提前断流、归档失败、错误脱敏、图片验证等22项测试。开发环境已完成正常生图、风险自动修改、正常上传通过、风险上传拦截等真实联调。新环境需要重新验收模型连接与调用结果。

## 使用边界

本仓库提供可运行的**本地单用户版本**，不是已上线的公网服务。上传GitHub不会自动部署Python后台或Dify；GitHub Pages也不能运行本项目后台。

若向公众提供服务，需要另行部署后台和Dify，并增加登录权限、调用限额、持久任务队列、HTTPS和存储备份。当前后台仅监听127.0.0.1并限制同源访问。

法规依据为工作流内嵌的《中华人民共和国广告法》文本。自动结果表示基于提供的信息未发现风险，不构成法律保证。行业专项法规、资质、授权及事实仍可能需要人工核实。

## 凭据与隐私

复制源码不会携带模型或应用密钥。`.env`、运行数据、历史任务和测试海报均不纳入版本控制。请不要把凭据放入HTML、截图、Issue或提交记录。
