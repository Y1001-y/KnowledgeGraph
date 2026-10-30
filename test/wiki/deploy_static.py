# -*- coding: utf-8 -*-
"""把 web/ 下的图谱前端与 vendor 静态库部署到 MediaWiki 站点根目录。

为什么需要这一步：
    MediaWiki 站点（mediawiki-1.43.1/）是第三方发行包，属于「运行时可重建」的产物，
    不纳入 Git。真正需要版本管理的前端源码放在 web/ 下，启动/构图时再复制进站点目录。
"""
import os
import shutil

import config

WEB_DIR = config.WEB_DIR              # test/wiki/web
MW_ROOT = config.MW_ROOT              # test/wiki/mediawiki-1.43.1


def deploy(verbose: bool = True) -> int:
    """复制 web/graph.html、web/vendor/* 到站点根目录，返回复制的文件数。"""
    if not os.path.isdir(MW_ROOT):
        if verbose:
            print(f"[跳过] MediaWiki 站点目录不存在：{MW_ROOT}（先完成 mediawiki 初始化）")
        return 0
    n = 0
    for name in ("graph.html",):
        src = os.path.join(WEB_DIR, name)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(MW_ROOT, name))
            n += 1
    vendor = os.path.join(WEB_DIR, "vendor")
    if os.path.isdir(vendor):
        for name in os.listdir(vendor):
            shutil.copy2(os.path.join(vendor, name), os.path.join(MW_ROOT, name))
            n += 1
    if verbose:
        print(f"前端资源已部署到站点：{n} 个文件 -> {MW_ROOT}")
    return n


if __name__ == "__main__":
    deploy()
