# 无限滚动重写规划

状态：已批准（2026-10-12），按里程碑实施，每阶段：主模型出详规 → 副手模型实现 → 主模型复核 → git 提交。

## 总方针

- 三层一次性重写：数据层（排序语义）、渲染层（虚拟化）、交互与体验层；单一路径，不留"顺序加载"旧分支。
- 顺序：先修数据层（当前即为错误行为），再换渲染层，再补交互/体验。
- 硬约束：**卡片等宽等高**（列宽由容器宽推导、行高 = 卡高 + rowGap）。占位尺寸、拖拽槽位公式、骨架屏全部依赖此约束，改卡片样式前必须先评估。
- 依赖：`virtua`（MIT，`virtua/vue`）。不用 `VGrid`（依赖 CSS subgrid），采用"行级 Virtualizer + 自行行切分"。
- 保留 `#meme-grid` 外层节点（拖拽引擎与 `test_startup.py` 契约引用它），虚拟行渲染在其内部。
- 不运行构建/typecheck/测试（工作区约定）；每阶段静态复核 + CI 兜底；e2e/契约更新随阶段完成。

## 里程碑

### S1 数据层：排序置换语义（后端）

问题：`reorder_memes` / `reorder_collection_members` 将传入 id 按数组序重编号 `sort_order = 0..N-1`。前端在无限滚动下只传"已加载窗口"，未加载项保持默认 0 值，导致全局顺序被破坏（0 值项抢占头部）。

目标语义（置换语义）：
1. 读取当前全序（`ORDER BY sort_order ASC, updated_at DESC, id ASC` 以确定性）；
2. 传入 id 集合在序列中的**位置集合保持不变**，按传入顺序回填这些位置；
3. 对整个作用域重编号 `sort_order = 0..N-1`（全局：全部 memes；分组：该分组全部 `meme_collections` 成员）；
4. 单事务提交（沿用 `self._lock` + `conn.executemany` / 循环 execute 现有模式）；
5. 全量传入时与现状完全等价（向后兼容）。

边界：空数组、重复 id、不存在 id、单元素、并发（锁内完成读+写）。

测试（`tests/test_core.py` 增补）：部分子集置换后全局顺序正确、未传项相对顺序不变、子集在全局的位置集合不变、全量等价、幂等（重复提交同序不变）。

### S2 渲染层：页缓存 + 虚拟化

`useMemes` 重写为页缓存模型：
- 状态：`total`、`pages: Map<页号, Meme[]>`（每页 200）、LRU 上限 ≈10 页（2000 项）、`queryGen`（替代 `searchGen`）、`selectedIds`（id Set，与缓存无关）。
- `search()`：重置 pages/选择/滚动，拉第 0 页。
- `ensurePages(rowStart, rowEnd)`：换算所需页集合，并发拉缺失页，gen 校验丢弃过期响应；LRU 淘汰最旧页。
- `slot(i)` 访问；删除 `loadMore`、顺序追加、`.grid-spacer`、`ensureFilled` 整套占位逻辑。
- 失败策略沿用：失败保留旧缓存 + 退避重试。

渲染（MainWindow.vue + style.css）：
- `#grid-wrap` 保持滚动容器：加 `overflow-anchor: none`（virtua 要求）。
- 内部 `<Virtualizer>`（行级）：`rows = chunk(slots, cols)`，`cols` 由 ResizeObserver 实测（容器宽 - padding / (卡宽 + gap)），行高固定。
- 已加载槽渲染现有真卡（DOM/事件原样）；未加载槽渲染骨架卡（`.`meme-card.skeleton`，静态灰块，同尺寸）。
- 行 key 用行锚元素 id / 占位 token（禁纯行号 key）。
- folder-grid 不虚拟化，作头块（`startMargin`）；`#empty`、`#organize-bar` 保持。
- footer 语义改「共 N 项」（"已加载"在窗口淘汰下不再有意义）；加载中/失败状态保留。

测试：vitest 新增页缓存单测（ensurePages/LRU 淘汰/gen 取消）；`test_startup.py` 契约断言映射到新结构（`#meme-grid`、folder-card 顺序、`sort-enabled` 绑定、`onCardClick`/`toggleSelected`、`grid-wrap` overflow-anchor）。

### S3 交互层

- 点选/点击：`onCardClick`/`toggleSelected` 不变。
- 框选：弃用 `@coleqiu/vue-drag-select`，自研"可见区框选"（空白 pointerdown 画框，选与框相交的已渲染卡；槽位数学已有）。
- 拖拽（整理模式，方案 B）：拖动操作已渲染行；拖到视口上下边缘触发自动滚动 + 按需 `ensurePages`；目标 index 用公式槽位算全局 index；drop 时提交"当前缓存窗口新顺序"给 S1 置换语义（全局正确）。跨窗口自由拖拽列为后续可选。
- FLIP 动画自然只作用于可见行。

### S4 体验与文档

- footer 失败态「加载失败，点击重试」；footer `aria-live="polite"`。
- 「回到顶部」浮动按钮（滚过两屏显示，`scrollToIndex(0)`）。
- AGENTS.md / README.md 无限滚动段落整体重写 + 卡片尺寸约束入档。

## 验收策略

- 静态复核（每阶段）：`git diff` 对照设计 + 契约一致性；不运行脚本。
- 自动化（CI）：vitest 单测、pytest 单测、test_startup 契约、e2e。
- 手工验收清单（交付前）：5k/20k 测试库——任意跳转、拖动+边缘自动滚动、框选、全选/批量、内存对比旧版、视觉走查。

## 风险与回滚

- 最高风险：拖拽 × 虚拟化整合（缓解：方案 B + 手工走查）。
- 次风险：自研框选行为回归（对照现库行为列清单）。
- 每里程碑独立提交；S2 若中途不可行整体 revert 回当前"顺序加载版"。

## 委派流程（本计划执行方式）

1. 主模型（roy/gpt-6.1-sol）出该阶段详细实施规划；
2. 副手模型（deepseek/deepseek-flash）按详规实现；
3. 主模型复核 diff；
4. 提交（conventional 中文提交信息）。
