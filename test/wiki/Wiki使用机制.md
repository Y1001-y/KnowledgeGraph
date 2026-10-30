# MediaWiki 在本项目中的使用机制

> 一句话概括：**MediaWiki 既是给人看的知识库，也是给程序读的图数据库**——  
> 写页面就是建图，读页面内部链接就是取图，页面本身还是可编辑的知识文档。

本文说明三个问题：**怎么把数据写成页面**、**怎么把页面读成图谱**、**前端怎么用页面**。  
所有调用都封装在 `mw_client.py`（纯 Python 标准库，零第三方依赖）。

---

## 零、站点与端点

| 项      | 值                                            |
| ------ | -------------------------------------------- |
| 站点根    | `http://127.0.0.1:8089`                      |
| API 端点 | `http://127.0.0.1:8089/api.php`              |
| 页面地址   | `http://127.0.0.1:8089/index.php?title=页面标题` |
| 账号     | `admin` / `Admin12345`（配置见 `config.py`）      |

客户端所有请求强制带 `format=json&formatversion=2`：

```python
params = {**params, "format": "json", "formatversion": "2"}
```

> 坑：不传 `format=json` 时，MediaWiki 会返回 HTML 包装页而不是 JSON。  
> `formatversion=2` 让 `query.pages` 变成数组（而非以 pageid 为键的对象），解析更简单。

---

## 一、写：把数据库「编译」成页面

`ingest.py` 不写任何图数据库，而是通过 API 生成 Wiki 页面。一次完整的写入会话包含 3 类调用：

```text
GET  api.php?action=query&meta=tokens&type=login          → logintoken
POST api.php?action=login&lgname=..&lgpassword=..&lgtoken=..  → 建立 Cookie 会话
GET  api.php?action=query&meta=tokens                     → csrftoken
POST api.php?action=edit&title=..&text=..&summary=..&token=..  → 建页 / 改页
```

对应代码：

```python
from mw_client import MediaWikiClient

mw = MediaWikiClient()
mw.login()                                   # 内部完成 logintoken + login
mw.edit_page("Java", """'''Java''' 属于「后端开发」方向（层级 2）。

== 开设课程 ==
* [[Java程序设计]]

== 岗位要求 ==
* [[Java开发工程师]]

[[Category:技能]] [[Category:后端开发]]""")
```

**页面正文就是图谱的源代码**：

| wikitext 写法         | 在图谱中的含义                 |
| ------------------- | ----------------------- |
| `[[Java程序设计]]`      | 一条边：Java — Java程序设计     |
| `[[Category:技能]]`   | 节点类型 = 技能（决定颜色、图例、视图过滤） |
| `[[Category:后端开发]]` | 分类名，显示在节点详情的「分类」字段      |
| 页面标题 `Java`         | 节点 id（唯一标识）             |

> 因此：**我写页面时就在决定图谱形状**。想让两个实体产生关系，不是去改图数据，  
> 而是在页面里加一条双链。

删除页面（陈旧数据清理）用：

```text
POST api.php?action=delete&title=..&reason=..&token=..
```

---

## 二、读：把页面「编译」成图（关键一步）

`build_graph.py` 只用一个查询就拿到全站拓扑：

```text
GET api.php?action=query
    &generator=allpages&gaplimit=500      # 枚举全部页面，每批 500
    &prop=links|categories                # 同时取出边与分类
    &pllimit=max&plnamespace=0            # 只看主命名空间的链接
    &cllimit=max
    &format=json&formatversion=2
    (+ continue 参数循环翻页)
```

客户端实现要点（`mw_client.py: all_pages_with_links`）：

```python
cont = {}
while True:
    params = {...}; params.update(cont)
    data = self._http(params)
    for p in data["query"]["pages"]:      # formatversion=2 → 数组
        entry = pages.setdefault(p["pageid"], {...})
        for lk in p.get("links", []):
            if lk["ns"] == 0:             # 只保留主命名空间，忽略分类/文件页
                entry["links"].append(lk["title"])
    cont = data.get("continue", {})
    if not cont:
        break
```

字段映射关系：

| MediaWiki 返回         | 图谱 JSON                       | 前端表现               |
| -------------------- | ----------------------------- | ------------------ |
| 页面标题 `title`         | `nodes[].name`                | 节点名称、跳转参数          |
| `links[].title`      | `links[].source/target`       | 连线（去重后）            |
| `categories[].title` | `nodes[].type`                | 颜色、图例、类型过滤         |
| 该节点的边数               | `nodes[].degree`、`symbolSize` | 球大小、标签是否默认显示       |
| —                    | `nodes[].url`                 | 详情卡片里的「查看 Wiki 页面」 |

> **中心度不用算**：一个页面被引用得越多，球自然越大——重要性是内容写出来的。

---

## 三、用：前端把 Wiki 当内容源

点击节点时的预览不是弹静态字段，而是实时调 MediaWiki 的解析接口：

```text
GET api.php?action=parse&page=Java&prop=text&formatversion=2&format=json
```

返回 `parse.text` 是 MediaWiki 渲染好的 HTML（含目录、样式），直接塞进 Element Plus 抽屉，  
所见即 Wiki 页面本身；同时给出 `index.php?title=Java` 链接，可进站点直接编辑。

另一个可用接口是取原始 wikitext（调试用）：

```text
GET api.php?action=parse&page=Java&prop=wikitext
```

---

## 四、为什么用 Wiki 承载，而不是直接写图数据库

| 好处                            | 代价                             |
| ----------------------------- | ------------------------------ |
| 页面人可读、可编辑、有版本历史；人改和机器改的是同一份数据 | 一个标题只能对应一个页面 → 必须处理同名实体        |
| 双链是写作的副产品，写完就有图，不用维护两套数据      | 关系没有属性（只有「谁连谁」），权重/时间要靠分类或模板补充 |
| 换数据库（SQLite → MariaDB）不影响内容   | 十万级边需要换渲染引擎（如 sigma.js）        |
| 天然带权限、历史、搜索、导出（API/XML dump）  | 页面标题是主键，改名会断链                  |

---

## 五、由此产生的两条硬约束

**1. 同名实体冲突**  
MediaWiki 里一个标题只有一个页面，课程「机器学习」和技能「机器学习」会互相覆盖。  
处理方式（`ingest.py: build_titles`）：

- 课程与技能重名时 → 课程页标题自动加「（课程）」后缀
- 同名岗位（华为/中兴/工商银行的「Java开发工程师」）→ 合并为一页，公司列表化

**2. 标题首字母被规范化**  
`uni-app` 存入后变成 `Uni-app`。清理陈旧页面时若直接比较标题，会把这类页面误判为  
「已删除的实体」并反复删除重建。处理方式：比较前先做同样的首字母大写规范化。

---

## 六、常用 API 速查（可直接粘到浏览器）

```text
# 站点信息
/api.php?action=query&meta=siteinfo&format=json

# 某个页面的双链与分类
/api.php?action=query&titles=Java&prop=links|categories&format=json&formatversion=2

# 某页面渲染后的 HTML
/api.php?action=parse&page=Java&prop=text&format=json&formatversion=2

# 某页面原始 wikitext
/api.php?action=parse&page=Java&prop=wikitext&format=json&formatversion=2

# 全站页面标题
/api.php?action=query&list=allpages&aplimit=50&format=json&formatversion=2
```

---

## 七、想扩展图谱维度怎么做

图谱的维度不由前端决定，由 **wikitext 的写法**决定。常见扩展：

| 想加的效果    | 改法                                                      |
| -------- | ------------------------------------------------------- |
| 增加「难度」维度 | 页面加 `[[Category:难度-高]]`，`build_graph.py` 里把该分类映射成新的节点属性 |
| 前置课程依赖方向 | 正文写 `* 先修：[[数据结构]]` 并加 `[[Category:先修]]`，构图时按分类判定边类型    |
| 同上位技能关系  | 加 `[[Category:上位技能:编程语言]]`，构图时按前缀解析出层级                  |
| 节点带权重    | 加 `[[Category:热度-高]]`，映射到 `symbolSize`                  |

改完页面模板后重跑：

```cmd
python ingest.py         :: 重新生成页面（双链变化）
python build_graph.py    :: 重新解析链接 → 新图谱
```

前端点「刷新图谱」即可看到效果，无需改 `graph.html`。

---

## 八、相关文件

| 文件               | 职责                                            |
| ---------------- | --------------------------------------------- |
| `mw_client.py`   | 上面所有 API 调用的封装（登录/编辑/删除/查询）                   |
| `ingest.py`      | 用 `action=edit` 把实体写成带双链的页面                   |
| `build_graph.py` | 用 `action=query&prop=links` 把页面读成 nodes/links |
| `web/graph.html` | 用 `action=parse` 做页面预览，用 graph_data.json 渲染图谱 |
| `config.py`      | 端点、账号、LLM 配置                                  |
