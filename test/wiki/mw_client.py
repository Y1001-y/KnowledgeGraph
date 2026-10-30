# -*- coding: utf-8 -*-
"""MediaWiki API 客户端（纯 Python 标准库，零第三方依赖）。

负责：登录、批量建页、查询全站页面/内部链接/分类。
图谱数据完全来自 MediaWiki 的 [[内部链接]]——这正是 llm_wiki 模式
在 MediaWiki 上的落地方式。
"""
import json
import urllib.parse
import urllib.request
from http.cookiejar import CookieJar

import config


class MediaWikiClient:
    def __init__(self) -> None:
        self.api = config.MW_API
        self._logged = False
        self.jar = CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}),           # 本机回环直连，绕过沙箱代理
            urllib.request.HTTPCookieProcessor(self.jar))

    # ---------------- HTTP ----------------
    def _http(self, params: dict, method: str = "GET") -> dict:
        params = {**params, "format": "json", "formatversion": "2"}
        data = None
        url = self.api
        if method == "GET":
            url = f"{self.api}?{urllib.parse.urlencode(params)}"
        else:
            data = urllib.parse.urlencode(params).encode("utf-8")
        req = urllib.request.Request(url, data=data, method=method, headers={
            "User-Agent": "KG-Test-Bot/1.0 (test project; local)",
        })
        with self.opener.open(req, timeout=60) as resp:
            result = json.loads(resp.read().decode("utf-8"))
        if "error" in result:
            raise RuntimeError(f"MediaWiki API 错误: {result['error'].get('info')}")
        return result

    # ---------------- 认证 ----------------
    def login(self, user: str | None = None, password: str | None = None) -> None:
        user = user or config.MW_USER
        password = password or config.MW_PASS
        login_token = self._http({"action": "query", "meta": "tokens",
                                  "type": "login"})["query"]["tokens"]["logintoken"]
        resp = self._http({
            "action": "login", "lgname": user, "lgpassword": password,
            "lgtoken": login_token,
        }, method="POST")
        if resp.get("login", {}).get("result") != "Success":
            raise RuntimeError(f"MediaWiki 登录失败: {resp.get('login')}")
        self._logged = True
        print(f"[mw] 已登录: {user}")

    # ---------------- 编辑 ----------------
    def edit_page(self, title: str, text: str, summary: str = "LLM Wiki ingest") -> None:
        if not self._logged:
            self.login()
        csrf = self._http({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
        resp = self._http({
            "action": "edit", "title": title, "text": text,
            "summary": summary, "token": csrf,
        }, method="POST")
        edit = resp.get("edit", {})
        if edit.get("result") != "Success":
            raise RuntimeError(f"编辑页面 [{title}] 失败: {edit}")
        return edit

    def delete_page(self, title: str, reason: str = "陈旧数据清理") -> None:
        """删除页面（需管理员权限，登录账号已有）。"""
        if not self._logged:
            self.login()
        csrf = self._http({"action": "query", "meta": "tokens"})["query"]["tokens"]["csrftoken"]
        resp = self._http({
            "action": "delete", "title": title, "reason": reason, "token": csrf,
        }, method="POST")
        if "error" in resp:
            raise RuntimeError(resp["error"].get("info"))

    # ---------------- 查询 ----------------
    def all_pages_with_links(self) -> list[dict]:
        """拉取全部主命名空间页面及其内部链接、分类（图谱数据源）。"""
        pages: dict[int, dict] = {}
        cont: dict = {}
        while True:
            params = {
                "action": "query",
                "generator": "allpages", "gaplimit": 500,
                "prop": "links|categories",
                "pllimit": "max", "plnamespace": 0,
                "cllimit": "max",
            }
            params.update(cont)
            data = self._http(params)
            for p in data.get("query", {}).get("pages", []):
                entry = pages.setdefault(p["pageid"], {
                    "title": p["title"], "links": [], "categories": []})
                for lk in p.get("links", []):
                    if lk["ns"] == 0:
                        entry["links"].append(lk["title"])
                for c in p.get("categories", []):
                    entry["categories"].append(
                        c["title"].replace("Category:", "").replace("分类:", ""))
            cont = data.get("continue", {})
            if not cont:
                break
        return list(pages.values())

    def get_page_text(self, title: str) -> str | None:
        try:
            data = self._http({"action": "parse", "page": title, "prop": "wikitext"})
            return data["parse"]["wikitext"]
        except RuntimeError:
            return None

    def page_url(self, title: str) -> str:
        return f"{config.MW_PAGE}?title={urllib.parse.quote(title)}"


if __name__ == "__main__":
    mw = MediaWikiClient()
    mw.login()
    print("MediaWiki 连接与登录成功:", config.MW_API)
