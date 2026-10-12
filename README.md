# Skill Atlas

Skill Atlas 用来整理 GitHub 上可供复用的开源项目，帮助开发者查找某项功能有哪些现成工具，并对候选项目做初步比较。

它不是另一个聊天机器人，也不试图替人直接决定技术选型。它把仓库信息、匹配依据和可核对的指标整理出来，减少每次从头搜索的工作。

![能力位总表](docs/images/01-slots.png)

## 它能做什么

- 按预先定义的功能分类检索 GitHub 项目。
- 综合仓库名称、主题标签和描述判断候选项目与需求的相关程度。
- 汇总星标、分支、许可证、代码规模和近期活跃情况等指标。
- 按相关性和项目质量排序候选，并保留排序依据。
- 将结果整理成 Markdown 文件，方便在 Obsidian 中查看和继续维护。
- 对比前后两次结果，查看候选变化。

## 一个使用例子

输入一个需求：

```bash
skill-atlas query "我要做一个能自动整理 Word 和 PDF 的工具"
```

程序会把需求匹配到相关功能分类，并列出候选仓库、匹配原因和可核对的指标。结果用于缩小搜索范围，最终选型仍需要结合项目本身的代码、许可证和实际需求判断。

![候选项目查询示例](docs/images/03-query.png)

## 快速试用

需要 Python 3.10 或更高版本。项目核心代码使用 Python 标准库。

```bash
git clone https://github.com/haozhouliuliuliu/skill-atlas
cd skill-atlas
python examples/demo.py
python -m unittest discover -s tests -t .
```

上面的演示使用本地样例，不需要 GitHub 账号或网络请求。

如需运行命令行并检索 GitHub 数据，可以安装项目：

```bash
pip install -e .
skill-atlas update
skill-atlas build
skill-atlas query "我要加日志监控"
```

`update` 用于获取和比较候选数据；`build` 用于生成整理后的笔记；`query` 用于按需求查找功能分类。具体参数以命令行帮助为准。

## 输出内容

生成的笔记库包含功能分类总表、项目蓝图、各分类候选列表、项目条目和检索记录。可以用 Obsidian 打开，也可以直接阅读 Markdown 文件。

## 排序方法与限制

项目会综合多项仓库指标进行排序，并优先考虑与需求直接相关的候选。具体公式和取舍记录在 [DESIGN.md](DESIGN.md) 中。

需要注意：

- 星标和活跃度只能作为参考，不能证明项目适合所有场景。
- 相关性判断主要依赖关键词和标签，并不是真正的语义理解。
- 功能分类、关键词和检索式是当前项目的一套配置，使用者可以按自己的技术栈调整。
- 选型前仍应检查实际代码、许可证、维护情况和安全风险。

## 项目结构

```text
src/skill_atlas/
  models.py    项目数据结构
  quality.py   仓库质量检查
  scoring.py   指标计算和排序
  slots.py     功能分类与检索规则
  index.py     检索结果索引
  vault.py     Markdown 笔记生成
  snapshot.py  快照与差异比较
  query.py     中文需求匹配
  store.py     数据读写
  api.py       GitHub 检索
  cli.py       命令行入口
```

## 更多文档

- [DESIGN.md](DESIGN.md)：排序规则、设计取舍和问题记录。
- [README.en.md](README.en.md)：英文说明。
- [LICENSE](LICENSE)：开源许可。
