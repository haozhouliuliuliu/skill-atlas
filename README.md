# skill-atlas

**Turn GitHub search results into a replaceable capability-slot index.**

Most of the cost of starting a project is not writing code — it's not knowing what
already exists. `skill-atlas` organises candidate projects into **capability slots**
(a specific position in your stack that will be replaced), keeps several candidates
per slot, and ranks them by **verifiable metrics** so that "found something better,
swap it in" has somewhere to land.

Output is an [Obsidian](https://obsidian.md)-friendly markdown vault: one note per
capability slot, one note per repository, plus a retrieval entry point that maps
*"I want to build X"* to *"use these slots"*.

Zero runtime dependencies — standard library only.

---

## The problem this exists to solve

The obvious way to find a library is to sort GitHub by stars. Try it on the
"recently created" ranking and you get this:

| Window | Repos | Share that are SEO spam |
|---|---:|---:|
| Last 24 hours | 100 | **91 %** |
| Last 7 days | 100 | 23 % |
| Last 30 days | 100 | **1 %** |

The spam repos share a fingerprint: they impersonate commercial software
(`Adobe-Photoshop`, `Microsoft-Office`, `SolidWorks-CAD`), their descriptions are
templated AI prose, and **the repository contains a single `README.md`**. A typical
one: `KindStatesman/KMS-Pico` — 614 stars, **0 forks, 0 watchers, 0 issues, 2 KB,
no license, no code**. Four different accounts behind four of these repos were all
created on the same day, each with two repositories and zero followers.

Short windows are dominated by star farming because a genuine project cannot
accumulate meaningful stars in 24 hours while a farm can buy 300–600 cheaply.

### The judgement call, and why it is defensible

"It looks AI-written" is not evidence. The evidence is **repository size**: a
README-only repo is 2–4 KB, while a real project is rarely under 1 MB. Across 300
ranking entries the size distribution is cleanly **bimodal**:

```
   ≤ 8 KB : 115   ████████████████████████████████
 9–50 KB :   3
51–200 KB:   8   ██
201 KB–1MB: 16   ████
   ≥ 1 MB : 158   ███████████████████████████████████████████
```

The gap between the two modes is almost empty, which means the threshold is not
sensitive. Cross-validating the two independent criteria:

| | count |
|---|---:|
| flagged by both prose and evidence | 108 |
| **flagged by prose only (possible false positive)** | **0** |
| flagged by evidence only (prose missed them) | 7 |
| passed by both | 185 |

Zero false positives. Every repository the prose filter flagged was independently
confirmed by the size/engagement filter.

---

## How it works

Two non-overlapping pipelines feed one index.

**1. The ranking pipeline** discovers *new* things. `created:>N days` sorted by
stars, top 100 per window. Useful for spotting emerging clusters — the
`Jev`/`Laya` "System-1 decision model" family showed up here with a dozen repos
before it was on anyone's radar.

**2. The slot pipeline** fills in *mature* things. For every capability slot, a
curated query is run against **all** of GitHub (`stars:>200`, sorted by stars).
Without this, LangChain, pandoc and whisper never appear — the ranking pipeline
only ever sees repos created in the last 30 days.

Both pools are merged, quality-filtered, assigned to slots, scored, and rendered
into the vault.

---

## Scoring

### Quality score (0–100) — verifiable metrics only

| Component | Points | Formula |
|---|---:|---|
| Adoption · stars | 30 | `30 × min(1, log10(1+stars)/5.5)` |
| Adoption · forks | 25 | `25 × min(1, log10(1+forks)/4.6)` |
| License present | 10 | — |
| Code volume | 10 | `10 × min(1, size_kb/1000)` |
| Issue activity | 10 | 10 if ≥10 issues, 6 if ≥1 |
| Freshness | 15 | ≤7 d: 15 · ≤30 d: 12 · ≤90 d: 7.5 · ≤1 y: 3 · older: 0.75 |

### Rank score = quality + relevance bonus

Relevance is decided by **where the keyword hit**, because position strongly
predicts what a project is actually for:

| Relevance | Bonus | How it is decided |
|---|---:|---|
| manual | +100 | pinned by a human |
| name | +20 | keyword appears in the repo name (`langchain-ai/langchain`) |
| ranking | +20 | assigned from the new-repo ranking by keyword rules |
| topics | 0 | keyword appears in tags |
| description | −15 | keyword only mentioned in passing |

The +20 for name matches is load-bearing: `freeCodeCamp` genuinely has `d3` in its
topics (it teaches D3), and without the bonus its 100-point quality score would
outrank `d3/d3` itself.

---

## See it work — no network, no token

```bash
git clone https://github.com/haozhouliuliuliu/skill-atlas
cd skill-atlas
python examples/demo.py
```

The demo runs the whole pipeline against a small bundled sample whose metrics are
taken from real crawl results, so the scores are the same ones the live pipeline
produces:

```
1. 质量过滤：SEO 引流仓库
  KindStatesman/KMS-Pico
      ★614  fork0  2KB  语言=无  许可证=无
      -> 排除理由: 仅README(2KB)

2. 能力位排序（排序分 = 质量分 + 相关性加成）
  [本地推理引擎]  候选 3 个
    首选 排序分 117 (质量  97)  相关=名字   ollama/ollama
         排序分 115 (质量  95)  相关=名字   ggml-org/llama.cpp

  [浏览器与插件]  候选 2 个
    首选 排序分 102 (质量  82)  相关=名字   XIU2/UserScript
         排序分  86 (质量  66)  相关=名字   Tampermonkey/tampermonkey
      # Tampermonkey 已 558 天未推送 —— 活跃度惩罚起了作用

  [磁盘与文件管理] 的人工剔除:
    ✂ apache/ranger —— Hadoop 权限管理项目，与终端文件管理器 ranger 同名撞车

4. 空缺报告
  46 / 54 个能力位没有候选
  其中包含样本里刻意留空的: 笔记与编辑器 = 空缺
```

It renders a real vault to `examples/out/` you can open in Obsidian, then
demonstrates the retrieval entry point:

```
6. 检索入口：从「我要做什么」反查能力位
  需求: 我想给项目加日志监控和定时任务
    [1] 定时任务与调度  匹配度 10.8  命中词: 任务、定时
          （本样本中该能力位没有候选 —— 机会区）
    [2] 日志与监控  匹配度 7.3   命中词: 日志、监控
          grafana/grafana  (质量 94)
          prometheus/prometheus  (质量 93)
```

A matched slot with no candidates is reported as an opportunity rather than hidden —
that emptiness is the signal.

---

## Install and use

```bash
git clone https://github.com/haozhouliuliuliu/skill-atlas
cd skill-atlas

# Nothing to install for the library or the tests — standard library only.
python -m unittest discover -s tests -t .     # 152 tests
python examples/demo.py                       # full pipeline, offline
```

This is a `src/` layout, so the **CLI** needs the package to be importable —
either of these:

```bash
pip install -e .                              # gives you a `skill-atlas` command
export PYTHONPATH=src                         # Windows: set PYTHONPATH=src
```

The real-GitHub commands below assume one of them. Every command in this README is
exercised in CI, on Linux, macOS and Windows.

### Try the CLI without network or token

```bash
python examples/prepare_data.py --out data --force
PYTHONPATH=src python -m skill_atlas.cli build --data data --vault vault
PYTHONPATH=src python -m skill_atlas.cli query "我要加日志监控" --data data
```

```
[1] 日志与监控　（领域：数据基础设施，核心）
    匹配度 7.3　命中词：日志、监控
    候选 2 个
      首选 [ 94分] grafana/grafana          ★77221 fork14838
           [ 93分] prometheus/prometheus    ★66459 fork10905
```

### Against real GitHub

Four commands, in order:

```bash
# 1. Discover what is new:  created:>N days, sorted by stars, top 100 per window.
python -m skill_atlas.cli fetch
#    day    fetched=100  low-value= 91 ( 91%)  total=  391358

# 2. Fill in what is mature: one curated query per slot against all of GitHub.
#    Resumable — it caches per slot and skips what it already has.
python -m skill_atlas.cli enrich

# 3. Render the vault.
python -m skill_atlas.cli build --vault vault
#    candidates  4270
#    junk        92
#    slots       54
#    repos       621
#    logs        3

# 4. Ask it what to use. Chinese is matched with 2-grams, so plain prose works.
python -m skill_atlas.cli query "我要做一个能自动整理 Word 和 PDF 的 agent"
#    [1] Office 文档生成与解析
#        首选 [ 79分] storytold/wordcraft      ★2560 fork745
#             [ 77分] LibreOffice/core         ★4486 fork973
```

Two more:

```bash
python -m skill_atlas.cli inspect ollama/ollama   # quality-check one repository
python -m skill_atlas.cli slots                   # list all 54 slots + manual overrides
```

### The daily loop: finding something better

Building a snapshot is only half the job. The point of re-running the pipelines
every day is to notice when **a better candidate shows up for a slot you already
filled** — so there is a `diff`:

```bash
skill-atlas fetch && skill-atlas enrich && skill-atlas diff
```

`diff` compares the freshly crawled ranking against the snapshot from the last
`build`, and separates three different events that are easy to conflate:

```
基线 2026-10-10 22:53:34  ->  当前 2026-10-10 22:53:35
==========================================================================

🔼 出现更好的首选（1 个）—— 这是值得替换的信号
  [本地推理引擎]  +1 分
      换下  ollama/ollama
      换上  newlab/ollama-pro (排序分 118)

🔽 首位变弱（1 个）—— 值得确认原因
  [浏览器与插件]  -16 分
      原  XIU2/UserScript
      现  Tampermonkey/tampermonkey

✅ 新填上的空缺（1 个）: 笔记与编辑器

进入候选列表的新项目（前 10 个能力位）
  [笔记与编辑器] logseq/logseq
  [本地推理引擎] newlab/ollama-pro, newlab/ultra-engine
```

Three deliberate choices:

- **`diff` does not advance the baseline.** Only `build` does. So you can look at
  what changed, decide, and *then* commit to it.
- **A filled gap is not an upgrade.** "This slot had no candidate, now it has one"
  is a different event from "the top pick changed", and reporting both as an upgrade
  makes the actionable signal harder to see.
- **A new candidate entering near the bottom of a list is not a replacement signal.**
  Slots hold dozens of candidates and the tail churns constantly. Only a change at
  position one is reported as actionable.

Note in the example above: `newlab/ultra-engine` has **300,000 stars** but does not
take the top pick — it only mentions `ollama` in its description, so it gets the
description penalty rather than the name bonus. That is the intended trade-off, and
it is covered by a test.

### Library use

```python
from skill_atlas import Repo, is_low_value, quality_score, relevance, rank_score

repo = Repo.from_search_item(api_item)
if is_low_value(repo):
    ...                     # README-only / templated spam
score = quality_score(repo)
rel, why = relevance(repo, '"agent memory" OR mem0 OR "long-term memory"')
rank = rank_score(score, why)
```

### A note on language

The **code and documentation** are English. The **slot taxonomy is Chinese**,
because it is the author's own knowledge base and the slots are the words the
author actually thinks in. Slot names, queries and synonyms are plain data in
`slots.py` and `query.py` — replace them with your own vocabulary and the rest of
the pipeline is unchanged.

---

## Status

Version 0.1, **not yet published**.

| Module | State |
|---|---|
| `models.py` · `quality.py` · `scoring.py` · `slots.py` | 50 tests |
| `index.py` · `vault.py` · `query.py` · `snapshot.py` | 47 tests |
| `api.py` (HTTP layer stubbed) | 20 tests |
| `cli.py` wiring · end-to-end over the bundled sample | 26 tests |
| **regression on the committed real crawl** | 9 tests |

**152 tests, all passing, zero dependencies.** CI runs them on Linux, macOS and
Windows at Python 3.10 and 3.12, plus the offline demo and an offline CLI
walkthrough, so every command documented above is executed on every push.

### On verifiability

The numbers in this README come from a real crawl — and you can re-derive them:

```bash
python -m unittest tests.test_real_data -v
```

`tests/fixtures/real_crawl/` contains that crawl, trimmed to **1.1 MB**:

- the day/week/month rankings are **complete** (240 KB) — they are what the
  `91% / 23% / 1%` junk figures are computed from
- the per-slot search results are cut to **the top 25 candidates per slot**. A slot's
  top pick is necessarily among them, so the conclusions reproduce.

The test asserts that re-running the pipeline over that data yields **the same 54 top
picks with the same rank scores** — not merely that the numbers look plausible. It
doubles as the strongest regression test here: any change to scoring or relevance
ordering shows up against real data, not just against a synthetic sample.

What is *not* reproducible is the earlier comparison against the pre-rewrite scripts
(54 of 54 top picks; one benign difference of 621 vs 629 repository notes, documented
in [DESIGN.md](DESIGN.md)) — that reference implementation is not published.

See [DESIGN.md](DESIGN.md) for the design decisions and the fourteen defects that
shaped them — including two that were only found by cross-validating two
independent filters against each other, and two found by tests that no amount of
manual use would have caught.

---

## Limitations

Stated plainly, because they matter more than the feature list:

- **Recall is biased.** The two pipelines favour newly created and heavily starred
  projects. Small, stable, excellent libraries that nobody stars are invisible.
- **Slot assignment is keyword-based** and does suffer name collisions. The
  `ranger` query pulled in `apache/ranger` (Hadoop authorisation) instead of the
  terminal file manager. There is a manual calibration layer for exactly this.
- **Relevance is lexical, not semantic.** It will correctly rank `dify` above
  `markitdown` for an agent-orchestration query. It cannot tell you whether
  `dify` or `langgraph` suits your project better.
- **The quality score measures project health, not fit.** A healthy project can be
  entirely wrong for what you are building.

---

## License

MIT — see [LICENSE](LICENSE).
