# 01 — 架构与契约

> 本文件中的目录结构、文档模型、数据库表、API 路径与字段、LLM 网关接口均为**契约**。修改须走 `CHANGE_REQUESTS.md`。  
> 标注"初始值"的数字是可调配置项，必须放入 `backend/app/config.py`，不得写死在业务代码里。

---

## 1. 目录结构

```
research-agent/
├─ AGENTS.md  PROGRESS.md  QUESTIONS.md  CHANGE_REQUESTS.md  DEPENDENCIES.md
├─ docker-compose.yml  .env.example  Makefile
├─ spec/                          # 本规格书
├─ backend/
│  ├─ app/
│  │  ├─ main.py  config.py  deps.py  errors.py
│  │  ├─ api/                     # 路由层，只做参数校验与编排，不写业务逻辑
│  │  │  ├─ documents.py  jobs.py  qa.py  reading.py  discover.py
│  │  │  ├─ graphs.py  writing.py  figures.py  data.py
│  │  ├─ models/                  # Pydantic 模型 + SQLAlchemy 表
│  │  ├─ llm/gateway.py           # 唯一的 LLM 出入口
│  │  ├─ ingest/                  # 解析流水线各阶段
│  │  ├─ dedup/
│  │  ├─ rag/                     # chunk / retrieve / answer / verify
│  │  ├─ translate/
│  │  ├─ discover/                # 搜索、下载、含金量、arXiv 追踪、推荐
│  │  ├─ graph/                   # 引用匹配、图算法、综述、future work
│  │  ├─ writing/                 # 框架、引用校验、图脚本、数据出图、caption
│  │  ├─ sandbox/                 # 脚本沙箱
│  │  └─ workers/                 # arq 任务定义
│  ├─ tests/  fixtures/           # fixtures 放小样本 PDF，不放大文件
│  └─ pyproject.toml
├─ frontend/
│  ├─ src/
│  │  ├─ app/ (router, shell, providers)
│  │  ├─ design/ (tokens.css, components/)
│  │  ├─ features/ library | reader | qa | discover | graph | writing
│  │  ├─ api/ (由 OpenAPI 生成的类型与 client)
│  │  ├─ mocks/
│  │  └─ lib/
│  └─ e2e/
├─ data/  (gitignore)  pdf/ (官方测试集，gitignore)
└─ openapi.yaml                   # 契约的机器可读版本
```

---

## 2. 环境变量（`.env.example` 必须包含）

```
DEEPSEEK_API_KEY=
LLM_BASE_URL=https://api.deepseek.com
LLM_FAST=deepseek-flash
LLM_STRONG=deepseek-v4-pro
LLM_VISION_ENABLED=false
DATABASE_URL=postgresql+psycopg://...
REDIS_URL=redis://...
EMBED_MODEL=BAAI/bge-m3
RERANK_MODEL=BAAI/bge-reranker-v2-m3
SEMANTIC_SCHOLAR_API_KEY=
GITHUB_TOKEN=
UPLOAD_MAX_MB=200
QA_MIN_SCORE=0.35
```

---

## 3. 统一文档模型（Document Model）

所有模块只读这一份结构。每个文本类块必须带 `page` 与 `bbox`（PDF 点坐标，原点左上，单位 pt）。

```json
{
  "doc_id": "uuid",
  "sha256": "...",
  "arxiv_id": "1706.03762",
  "version": "v7",
  "page_count": 15,
  "source_kind": "vector|scanned|mixed",
  "meta": {
    "title": "", "authors": [{"name": "", "affiliation": "", "anchor": {}}],
    "abstract": {"text": "", "anchor": {}}, "year": 2017, "venue": null
  },
  "outline": [{"id": "s1", "level": 1, "title": "", "page": 1, "block_id": ""}],
  "blocks": [{
    "id": "b123", "type": "heading|paragraph|table|figure|formula|caption|reference|footnote|list_item",
    "page": 3, "bbox": [x0, y0, x1, y1], "reading_order": 57,
    "section_id": "s3", "text": "", "latex": null, "html": null,
    "asset_id": null, "lang": "en", "confidence": 0.98
  }],
  "references": [{"id": "r11", "index": 11, "raw": "", "title": null, "authors": [], "year": null,
                  "doi": null, "arxiv_id": null, "block_id": "", "bbox": []}],
  "citations": [{"id": "c1", "marker": "[11]", "ref_ids": ["r11"], "block_id": "b123",
                 "bbox": [], "method": "link_annotation|regex"}],
  "assets": [{"id": "a1", "kind": "figure|table|formula", "page": 3, "bbox": [], "path": ""}]
}
```

约束：

- `blocks` 必须按 `reading_order` 排好，双栏文档需正确还原阅读顺序（先左栏后右栏）。
- 表格同时输出 `html`（结构）与 `asset_id`（裁剪图）；公式同时输出 `latex` 与裁剪图；解析不确定时 `confidence < 0.6`，前端以裁剪图为准展示。
- `citations.method` 优先用 PDF 内部链接注释（PyMuPDF `get_links`），失败才用正则兜底。

---

## 4. 数据库表（最小集合）

| 表                                     | 关键字段                                                                                                             |
| ------------------------------------- | ---------------------------------------------------------------------------------------------------------------- |
| `users`                               | id, name, created_at（首版 `X-User-Id` 头识别，无需密码）                                                                    |
| `documents`                           | id, sha256, arxiv_id, version, title, status, source_kind, page_count, tags[], file_path, created_by, created_at |
| `doc_fingerprints`                    | doc_id, minhash, title_abs_embedding(vector), first_pages_text_hash                                              |
| `blocks`                              | doc_id, id, type, page, bbox, reading_order, section_id, text, latex, html, asset_id                             |
| `chunks`                              | id, doc_id, block_ids[], section_id, page_start, page_end, text, embedding(vector), tsv                          |
| `references` / `citations` / `assets` | 同文档模型                                                                                                            |
| `jobs`                                | id, kind, status, progress, stage, error, payload, result, created_at                                            |
| `papers_ext`                          | id, source, ext_id, title, authors, year, abstract, pdf_url, github_url, stars, fetched_at（外部发现的论文，未必入库）         |
| `recommendations`                     | id, user_id, paper_id, score, reasons(json), created_at                                                          |
| `feedback`                            | user_id, paper_id, value(1/-1), created_at                                                                       |
| `user_profiles`                       | user_id, interest_vector(vector), updated_at                                                                     |
| `tracking_config`                     | user_id, categories[], keywords[], cron                                                                          |
| `graphs`                              | id, doc_ids[], nodes(json), edges(json), metrics(json), survey(text), future_work(json)                          |
| `translations`                        | doc_id, block_id, lang, text, cache_key                                                                          |
| `drafts`                              | id, idea, outline(json), references(json), bibtex                                                                |
| `datasets` / `figures`                | id, 原始文件或脚本、渲染产物路径、caption、stats(json)                                                                           |

---

## 5. API 契约（前缀 `/api/v1`）

通用：ID 为 uuid；时间为 ISO8601 UTC；分页 `?page=&page_size=`；错误格式见 AGENTS.md H17；流式接口用 `text/event-stream`，事件类型 `token | anchor | progress | done | error`。

### 5.1 文档与任务

| 方法 路径                                              | 说明                                                                        |           |                           |
| -------------------------------------------------- | ------------------------------------------------------------------------- | --------- | ------------------------- |
| `POST /documents`（multipart，多文件）                   | 返回 `[{upload_id, doc_id, job_id, status, dedup?}]`；`dedup` 为命中的重复信息（见 §8） |           |                           |
| `GET /documents?query&tag&status&page`             | 列表                                                                        |           |                           |
| `GET /documents/{id}`                              | 元信息、状态、解析统计（页数、图表数、公式数、参考文献数）                                             |           |                           |
| `PATCH /documents/{id}` / `DELETE /documents/{id}` | 改标题/标签；删除（同时清理索引与文件）                                                      |           |                           |
| `GET /documents/{id}/file`                         | PDF 流，必须支持 HTTP Range                                                     |           |                           |
| `GET /documents/{id}/structure`                    | meta + outline + references 概览                                            |           |                           |
| `GET /documents/{id}/pages/{n}/blocks`             | 某页全部 blocks                                                               |           |                           |
| `GET /documents/{id}/assets/{asset_id}`            | 图/表/公式裁剪图                                                                 |           |                           |
| `POST /documents/{id}/dedup/resolve`               | \`{action: "keep_existing"                                                | "replace" | "keep_both", target_id}\` |
| `GET /documents/{id}/versions/diff?other={id}`     | 章节级差异 + 摘要                                                                |           |                           |
| `GET /jobs/{id}`、`GET /jobs/stream`                | 任务状态；SSE 推送 `progress/stage`                                              |           |                           |

### 5.2 问答与锚点

| 方法 路径                     | 说明                                |       |                              |                                                                                     |
| ------------------------- | --------------------------------- | ----- | ---------------------------- | ----------------------------------------------------------------------------------- |
| `POST /qa`（SSE）           | 入参 \`{question, scope:{type:"doc" | "set" | "all", doc_ids[]}, mode:"qa" | "compare"}`；事件流输出 token 与 `anchor`；compare 模式最终返回 `table\`（行=对比维度，列=论文，单元格含 anchor） |
| `GET /anchors/{block_id}` | 返回 block 文本、页码、bbox、所属文档（供悬停预览）   |       |                              |                                                                                     |

### 5.3 阅读与翻译

| 方法 路径                             | 说明                                    |            |
| --------------------------------- | ------------------------------------- | ---------- |
| `GET /documents/{id}/citations`   | 引用标记 ↔ 参考文献的 bbox 映射（双向跳转）            |            |
| `POST /translate/selection`       | \`{text, block_id?, direction:"en2zh" | "zh2en"}\` |
| `POST /documents/{id}/translate`  | 创建全文翻译任务，\`{format:"md"               | "html"}\`  |
| `GET /documents/{id}/translation` | 按 block 对齐的译文（供对照与联动）                 |            |

### 5.4 发现、追踪、推荐

| 方法 路径                                           | 说明                                                 |       |
| ----------------------------------------------- | -------------------------------------------------- | ----- |
| `POST /discover/search`                         | `{query}` → 外部论文候选（标题、作者、年份、摘要、pdf_url、github_url） |       |
| `POST /discover/fetch`                          | `{source, ext_id}` → 下载并入库，返回 `job_id`             |       |
| `POST /discover/references/import`              | `{doc_id, min_score?}` → 为该文献的参考文献批量抓取，返回 `job_id` |       |
| `GET /documents/{id}/references`                | 参考文献列表，含 `worth_score`(0–100) 与 `worth_reasons[]`  |       |
| `GET /recommendations`                          | 推荐流，含 `score`、`reasons[]`、`github_url`、`stars`     |       |
| `POST /recommendations/{paper_id}/feedback`     | \`{value: 1                                        | -1}\` |
| `GET/PUT /tracking/config`、`POST /tracking/run` | 追踪配置与手动触发                                          |       |

### 5.5 图谱与综述

| 方法 路径                           | 说明                                                                                    |                  |        |               |
| ------------------------------- | ------------------------------------------------------------------------------------- | ---------------- | ------ | ------------- |
| `POST /graphs`                  | `{doc_ids[]}` → `job_id`                                                              |                  |        |               |
| `GET /graphs/{id}`              | nodes（含 role=cornerstone/middle/peripheral、pagerank、in_degree、betweenness、year）、edges |                  |        |               |
| `POST /graphs/{id}/survey`（SSE） | 生成综述，论断带 anchor                                                                       |                  |        |               |
| `POST /graphs/{id}/future-work` | 返回条目数组，含 \`status: open                                                               | partially_solved | solved | unknown\` 与证据 |

### 5.6 写作与可视化

| 方法 路径                             | 说明                                                        |                        |        |                                   |                                               |
| --------------------------------- | --------------------------------------------------------- | ---------------------- | ------ | --------------------------------- | --------------------------------------------- |
| `POST /writing/outline`（SSE）      | `{idea}` → Abstract/Introduction/Related Work 框架 + 候选参考文献 |                        |        |                                   |                                               |
| `POST /writing/references/verify` | 校验候选文献真实性，返回 \`verified                                   | unverified\` 及证据来源 URL |        |                                   |                                               |
| `GET /writing/drafts/{id}/bibtex` | 仅含 verified 条目                                            |                        |        |                                   |                                               |
| `POST /figures/generate`          | \`{kind:"mermaid"                                         | "graphviz"             | "tikz" | "matplotlib", description}\` → 脚本 |                                               |
| `POST /figures/run`               | `{kind, script}` → 渲染结果（SVG/PNG）或结构化报错                    |                        |        |                                   |                                               |
| `POST /data/upload`（CSV）          | 返回列信息与预览                                                  |                        |        |                                   |                                               |
| `POST /data/{id}/chart`           | \`{type:"table"                                           | "line"                 | "bar"  | "radar"                           | "radar3d", x, y[]}`→ 图表规格 +`stats`+`caption\` |
| `POST /translate/zh2en`           | 中文摘要/全文 → 学术英文                                            |                        |        |                                   |                                               |

---

## 6. LLM 网关规范（`llm/gateway.py`）

必须提供的接口：

```python
async def chat(messages, *, tier: Literal["fast","strong"]="fast",
               json_schema: dict|None=None, temperature: float=0.0,
               stream: bool=False, tools: list|None=None,
               cache_prefix: str|None=None) -> ...
async def vision(image_bytes, prompt, *, json_schema=None) -> ...   # LLM_VISION_ENABLED=false 时抛 FeatureDisabled
```

约束：

- 模型名、地址只读环境变量；业务代码只传 `tier`。
- 提示词中**固定内容（系统提示、文档前缀）放最前**，变化内容放最后，以利用上下文缓存降低成本。
- 结构化输出必须走 JSON 模式并用 Pydantic 校验；校验失败重试一次，再失败返回可读错误。
- 内置：超时、重试、速率限制、请求/响应缓存（key = hash(模型, 消息, 参数)）、token 与耗时日志。
- 模型分工：`fast` 用于翻译、字段抽取、caption、摘要；`strong` 用于多文对比、综述、Future Work 判定、论文框架。
- 提供 `FakeLLM`（测试用，返回固定输出），所有单元测试不得真实调用外部 LLM。

---

## 7. 解析流水线规范

阶段顺序（每阶段独立可重跑，状态写入 `jobs.stage`）：

1. **入库校验**：MIME、大小、页数、sha256；解析文件名/首页中的 arXiv ID；**快速指纹**（前 3 页文本 MinHash + 标题摘要向量）→ 触发早期去重预警。
2. **页面探测**：逐页统计文本字符数，低于阈值（初始值 30）视为扫描页。
3. **版面解析**：输出 blocks 与阅读顺序，正确处理单/双栏。
4. **OCR**：仅对扫描页执行；保留 bbox；置信度写入 `confidence`。
5. **元信息抽取**：标题、作者、机构、摘要（首页规则 + LLM JSON，均需锚点）。
6. **标题树**：优先 PDF bookmarks，其次字号 + 编号规则（`1`、`1.1`、`A.`）。
7. **图表公式抽取**：裁剪图存 assets；表格输出 HTML；公式输出 LaTeX。
8. **参考文献与引用标记**：解析 references；建立 citations（见 §3）。
9. **正式去重判定**：见 §8。
10. **切块、嵌入、索引**：按 20 页窗口增量写入，窗口处理完即可检索。

失败策略：某阶段失败只标记该阶段 `failed` 并记录原因，已完成阶段保留，前端显示"部分可用"，可单阶段重试。

---

## 8. 语义去重规范

三层判定，任一层命中即返回 `dedup` 信息：

| 层     | 规则                                            | 结果                                                       |
| ----- | --------------------------------------------- | -------------------------------------------------------- |
| L1 精确 | `sha256` 相同                                   | `exact_duplicate`                                        |
| L2 版本 | arXiv ID 相同、版本号不同                             | `same_paper_other_version`                               |
| L3 内容 | 标题+摘要向量余弦 ≥ 0.95 且 前若干块 MinHash Jaccard ≥ 0.8 | `content_duplicate`；余弦在 0.85–0.95 为 `possible_duplicate` |

返回结构：`{level, matched_doc_id, similarity, existing_version, new_version, suggestion: "keep_existing"|"replace"|"ask", reason}`。

规则：

- 判定**不得只看文件名**；扫描版必须在 OCR 出文本后重新做 L3 判定。
- 版本比较：能解析出版本号时，建议保留较新版本；否则按发布时间/页数/内容变化给出理由。
- 内容相同但格式不同（矢量 vs 扫描）：提示"内容相同、格式不同"，**必须允许用户选择保留两者**。
- 差异摘要：先做章节级文本 diff（difflib/段落对齐），统计新增/删除/修改的章节、表格、图、参考文献数量，再由 LLM 基于 diff 结果生成不超过 200 字的修订摘要；摘要中的数字必须来自 diff 统计。

---

## 9. RAG 规范

**切块**：以 block 为单位聚合；目标 300–600 tokens，重叠 ≤ 15%，**不跨章节**；表格、公式、图注各自独立成块；每个 chunk 保存 `block_ids[]`，用于还原锚点。

**检索**：BM25 取 30 + 向量取 30 → RRF 融合 → bge-reranker 重排取前 8。范围由 `scope` 过滤。


**元数据型问题**（作者机构、超参数、GPU 型号数量、BLEU、指定引用的完整信息）：先走"定向抽取"——在相关章节 chunk 内用 JSON 模式抽取字段，并强制返回 anchor；抽不到则返回 `null`。

**回答生成**：

1. 提示词只含检索到的证据块，每块带编号；
2. 要求每个论断后标注证据编号；
3. 后处理：编号映射回 anchor；对数字/术语做 H04 回验；
4. 最高重排分 < `QA_MIN_SCORE` → 拒答（H03）。

**多文对比**：对每篇论文分别检索同一组维度（例如参数量、层数、上下文窗口、LN 位置、使用的组件），汇总成表格，单元格内容与 anchor 一一对应；某论文该维度找不到证据则写"未在原文找到"。

**评测**：`backend/tests/golden_qa.json` 至少 30 条（单篇 20 + 跨文 10），每条含问题、期望要点、期望锚点所在页；`make eval-qa` 输出命中率、锚点准确率、拒答正确率。

---

## 10. 其他核心算法规范

**含金量打分（0–100）**：对每条参考文献计算，并附 `reasons[]`：

- 正文被引次数；是否出现在方法/实验章节（加分）；
- 引用上下文含"we use / follow / based on / extend / compared with"等（加分）；
- 是否出现在基线对比表中（加分）；
- 仅出现在 Related Work 的"连续 ≥4 篇合并引用"（扣分，视为应付式引用）；
- 是否自引（轻微扣分，不剔除）；
- 外部"高影响力引用"标记（有则加分）。  
  权重放配置文件；`min_score` 由用户在前端调节。

**推荐评分**：`score = 0.5·相关性 + 0.2·可复现(有 GitHub) + 0.15·新鲜度 + 0.15·偏好`，权重可配置。相关性 = 论文向量与本地库的最大相似度和质心相似度加权。点赞/踩更新用户兴趣向量（Rocchio：`q' = q + 0.3·mean(liked) − 0.2·mean(disliked)`，系数可配置）。每条推荐必须有 `reasons[]`（例如"与你库中《X》相似度 0.82""附带开源代码，⭐1.2k"）。

**arXiv 追踪**：使用 Sickle 访问 OAI-PMH，按 `tracking_config` 的类别与关键词定时增量拉取（APScheduler 或 arq cron），记录水位线避免重复；GitHub 链接来源依次尝试：摘要/评论字段 → 论文源信息 → GitHub 搜索，找到后查询 stars。

**引用图谱**：节点=所选文献；边 u→v 表示 u 引用 v。引用匹配顺序：DOI → arXiv ID → 标题规范化后模糊匹配（token-set 相似度 ≥ 0.92 且年份一致）。指标：入度、PageRank（阻尼 0.85）、介数。基石=PageRank 前 20% 且入度 ≥ 2；边缘=入度为 0 且出度 > 0。图中无法匹配的参考文献不进入图。

**Future Work 过滤**：从 Conclusion/Discussion/Future Work 章节抽取条目（带 anchor）；对每条，在库内时间更晚的论文及外部检索（近 N 年）中找证据，由 `strong` 模型判定 `solved|partially_solved|open|unknown`，**必须附证据论文与 anchor**；证据不足一律 `unknown`，不得当作 `open` 展示为"值得探索"。

**论文框架与参考文献**：候选文献只能来自检索结果；经外部数据库查询匹配（标题相似 ≥ 0.9 且年份/作者吻合）才标记 `verified` 并进入 BibTeX；正文引用键必须存在于 verified 列表；未验证项以 `[待补充]` 显示。

**图脚本与沙箱**：脚本在沙箱运行（H09 限制）；失败时把报错回传模型自动修复，最多 3 次，仍失败则展示报错与最后一版脚本；Mermaid 语法在前端用 Mermaid 解析校验；TikZ：服务端若有 `tectonic`/`pdflatex` 则编译预览，否则只输出源码并提示"未检测到 LaTeX 环境"。

**Figure Caption**：先用 pandas 计算统计量（最大/最小/均值、起止变化率、趋势斜率、峰值位置）写入 `stats` JSON，再让模型据此写 caption；后处理校验 caption 中每个数字都在 `stats` 中出现，否则重写。caption 需符合学术规范（"Figure N. 主题 + 关键趋势 + 条件/单位"）。

**翻译**：按 block 翻译；行内公式与代码用占位符保护，翻译后回填；缓存键 = hash(原文, 方向, 术语表版本)；对照模式按 block id 对齐，联动滚动基于 block 可见性，不得按像素比例滚动。
