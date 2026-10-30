# KG Wiki 模块 

> 位置：`KnowledgeGraph\test\wiki`
> 一句话：**用 MediaWiki 承载 LLM 生成的知识页面，页面之间的 `[[双链]]` 自动涌现成知识图谱。**

## 这个模块做了什么

```
课程/技能/岗位种子数据 (SQLite)
        │ seed_data.py
        ▼
LLM 两步摄取（分析 → 生成）        ← ingest.py，无 Ollama 时自动降级规则模式
        │  为每个实体写一个 Wiki 页面：
        │  页面正文用 [[双链]] 标注关系，[[Category:xx]] 标注类型
        ▼
MediaWiki 1.43.1 站点（80+ 页面）   ← 便携 PHP 8.3 内置服务器托管，127.0.0.1:8080
        │ build_graph.py 调 MediaWiki API 拉取全部页面及内部链接
        ▼
graph_data.json → graph.html       ← Vue3 + Element Plus + ECharts 力导向图
```

**图谱不是手工录入的**：`[[双链]]` 就是边，分类就是节点颜色，数据变了重跑脚本即可刷新。

## 快速开始

```cmd
cd D:\study\KnowledgeGraph\test\wiki

:: 1. 启动站点（或双击 start_wiki.bat）
php\php.exe -S 127.0.0.1:8080 -t mediawiki-1.43.1 mediawiki-1.43.1\router.php

:: 2. 重建数据与图谱（首次或数据变更时）
python seed_data.py
python ingest.py
python build_graph.py

:: 3. 浏览
::    知识图谱  http://127.0.0.1:8080/graph.html
::    Wiki 首页 http://127.0.0.1:8080/
::    后台      admin / Admin12345
```

## 文件一览

| 文件/目录 | 作用 |
|---|---|
| `seed_data.py` | 22 课程 / 42 技能 / 14 岗位种子数据写入 SQLite |
| `ingest.py` | 两步摄取：LLM 分析 + 生成带双链的 Wiki 页面（含同名消歧、陈旧页清理） |
| `build_graph.py` | 拉取全站页面链接，生成图谱数据并自动部署前端 |
| `mw_client.py` | MediaWiki API 客户端（登录/建页/查询，纯 Python 标准库） |
| `config.py` | 站点地址、账号、LLM 配置、目录约定 |
| `web/graph.html` | **图谱前端源码**（唯一需要改的页面文件） |
| `web/vendor/` | Vue3 / Element Plus / ECharts 本地静态库（离线可用） |
| `deploy_static.py` | 把 `web/` 部署到 MediaWiki 站点根目录（启动/构图时自动调用） |
| `start_wiki.bat` | 一键启动（先部署前端再起站点） |
| `说明文档.md` | 完整说明：技术选型、实现逻辑、上线衔接方案 |

> 运行时目录 `php/`、`mediawiki-1.43.1/`、`mw-data/`、`data/` 已写入 `.gitignore`，
> 它们可以由脚本重新装出来，不入库——仓库只保留约 3MB 源码。

## 提交到 GitHub

`.gitignore` 已配好（只提交源码），在仓库根目录执行：

```cmd
cd D:\study\KnowledgeGraph
git add test/wiki
git commit -m "feat: MediaWiki + LLM Wiki 知识图谱测试项目"
git push
```

⚠️ 不要用 `git add .`：根目录下的 `归档/vue+springboot/pcscp`、`pcscp-web`
是各自带 `.git` 的嵌套仓库，直接 add 会变成 gitlink 引用而不是代码。


## 图谱页面交互

- **左右/上下滚动条**：图谱画布 2400×1700，只有图谱展示区滚动，顶栏和左栏固定
- 顶栏切换视图（课程-技能 / 岗位-技能 / 全部）、刷新、导出图片
- 左栏：统计卡片、图例点击过滤、搜索聚焦子图、节点详情
- 点击节点「查看 Wiki 页面」→ 抽屉实时预览 MediaWiki 页面内容

## 技术栈（全部开源免费）

MediaWiki 1.43.1 (GPL) · PHP 8.3 便携版 (PHP-3.0) · SQLite (公有领域) ·
Vue 3 / Element Plus (MIT) · Apache ECharts (Apache-2.0) · Python 标准库 (PSF) ·
可选 Ollama + Qwen 开源模型 (MIT / Apache-2.0)

详细设计思路与上线方案见 **[说明文档.md](说明文档.md)**。
