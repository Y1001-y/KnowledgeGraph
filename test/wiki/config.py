# -*- coding: utf-8 -*-
"""测试项目配置。所有组件均为开源免费软件。"""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------- 目录结构 ----------
# web/      前端源码（graph.html + vendor 静态库），纳入版本管理
# mediawiki-1.43.1/、php/、mw-data/  运行时产物，可重新下载/安装，不入库
WEB_DIR = os.path.join(BASE_DIR, "web")
MW_ROOT = os.path.join(BASE_DIR, "mediawiki-1.43.1")

# ---------- MediaWiki ----------
# 本地便携 PHP 内置服务器
MW_SERVER = "http://127.0.0.1:8089"
MW_API = f"{MW_SERVER}/api.php"
MW_PAGE = f"{MW_SERVER}/index.php"
MW_USER = "admin"
MW_PASS = "Admin12345"

# ---------- 源数据库（业务数据） ----------
# SQLite：公有领域开源，零配置。模拟你归档项目里的课程/技能/岗位数据
SOURCE_DB = os.path.join(BASE_DIR, "data", "source.db")

# ---------- LLM（可选增强，不开也有规则模式兜底） ----------
# OpenAI 兼容接口：默认本地 Ollama（开源免费），也可指向 vLLM / LM Studio 等
# 未运行 Ollama 时自动降级为规则模式，图谱效果不受影响
LLM_ENABLED = True
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1")
LLM_API_KEY = os.environ.get("LLM_API_KEY", "ollama")
LLM_MODEL = os.environ.get("LLM_MODEL", "qwen2.5:7b")
LLM_TIMEOUT = 120

# ---------- 图谱输出（放在 MediaWiki 根目录，随站点直接访问） ----------
GRAPH_DATA = os.path.join(BASE_DIR, "mediawiki-1.43.1", "graph_data.json")
# 源码备份（不入库，便于核对）：实际由 build_graph.py 写入站点目录
GRAPH_DATA_SRC = os.path.join(BASE_DIR, "data", "graph_data.json")
