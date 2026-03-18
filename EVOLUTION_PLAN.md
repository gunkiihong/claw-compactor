# Claw Compactor v7.0 — Evolution Plan

**Date:** 2026-03-17
**Baseline:** 919 tests, ~7,300 lines Python, 12 Node.js proxy modules
**Goal:** 从 "workspace memory compressor" 进化为 "universal LLM context optimizer"
**原则:** 所有代码独立实现，不复制任何第三方代码，只借鉴架构思路

---

## 能力矩阵 — 当前 vs 目标

| 能力 | 当前 CC v6 | 目标 CC v7 | CC v7 命名 |
|------|-----------|-----------|-----------|
| 文本压缩 | 规则引擎 + 字典 + RLE | + ML token 分类器 | **Crunch** (token-level ML compressor) |
| 代码压缩 | 正则 minify (有 bug) | AST-aware, 多语言 | **CodeCrunch** (AST compressor) |
| JSON/结构化数据 | 无 | 统计采样 + schema 发现 | **ShellCracker** (structured data crusher) |
| 可逆压缩 | 无 | hash 标记 + 原文存储 + tool 注入 | **SnapBack** (reversible retrieval) |
| 内容路由 | 手动指定 | 自动分类 + 路由 | **Claw Router** (content dispatcher) |
| 代理模式 | 无 (嵌入式) | 零代码 HTTP proxy | **Claw Proxy** (transparent proxy) |
| KV Cache 优化 | 无 | system prompt 稳定化 | **PrefixLock** (cache alignment) |
| 图片压缩 | 无 | 智能降分辨率 | **PixelCrunch** (image optimizer) |
| 学习能力 | Engram (观察式) | + 失败分析 + 自动规则生成 | **Engram v2** (learn from failures) |
| 管道架构 | 线性 cmd_full | 可配置 transform pipeline | **Pipeline** (transform chain) |
| 压缩反馈 | 无 | 追踪哪些被 LLM 取回 | **FeedbackLoop** |
| 日志压缩 | 无 | 构建/测试日志专用 | **LogCrunch** |
| 搜索结果压缩 | 无 | grep/ripgrep 输出专用 | **SearchCrunch** |
| Diff 压缩 | 无 | git diff 专用 | **DiffCrunch** |
| 评估框架 | benchmark (基本) | 多维度精度+压缩率 | **CrunchBench** |

---

## Phase 1 — 基础架构重构 (Transform Pipeline + SnapBack)

**目标:** 建立可扩展的 pipeline 架构 + 实现可逆压缩
**预计改动:** 8 个文件, 3 个新文件
**依赖:** 无外部新依赖

### 1.1 Transform 基类 + Pipeline 引擎

创建 `scripts/lib/transforms/` 子包:

```
scripts/lib/transforms/
  __init__.py          # 导出 Transform, Pipeline
  base.py              # Transform 抽象基类
  pipeline.py          # Pipeline 引擎 (顺序执行, 计时, 跳过门控)
```

**Transform 基类设计:**
```python
class Transform:
    name: str                          # 显示名
    order: int                         # 执行顺序 (越小越先)

    def should_apply(self, ctx: CompressContext) -> bool
    def apply(self, ctx: CompressContext) -> TransformResult
```

**CompressContext (不可变):**
```python
@dataclass(frozen=True)
class CompressContext:
    content: str                       # 当前文本
    content_type: str                  # "text" | "code" | "json" | "log" | "diff" | "search"
    language: str | None               # 代码语言
    role: str                          # "system" | "user" | "assistant" | "tool"
    model: str | None                  # 目标模型
    token_budget: int | None           # token 上限
    query: str | None                  # 用户当前 query (用于相关性)
    metadata: dict                     # 透传元数据
```

**TransformResult (不可变):**
```python
@dataclass(frozen=True)
class TransformResult:
    content: str                       # 压缩后文本
    original_tokens: int
    compressed_tokens: int
    markers: list[str]                 # SnapBack hash 标记
    warnings: list[str]
    timing_ms: float
    skipped: bool                      # should_apply 返回 False
```

**Pipeline 引擎:**
```python
class Pipeline:
    transforms: list[Transform]        # 按 order 排序

    def run(self, ctx: CompressContext) -> PipelineResult
    # 顺序执行每个 transform
    # 前一个的 output 是后一个的 input
    # 收集 timing, markers, warnings
    # 任何 transform 可以改变 content_type (路由器)
```

### 1.2 SnapBack — 可逆压缩引擎

创建 `scripts/lib/snapback/`:

```
scripts/lib/snapback/
  __init__.py
  store.py             # 原文存储 (内存 LRU + 可选文件持久化)
  marker.py            # hash 生成 + 标记嵌入/提取
  retriever.py         # tool 定义生成 + 检索执行
```

**核心设计:**

```python
# store.py
class SnapBackStore:
    """LRU 原文存储, TTL 过期"""
    _cache: OrderedDict[str, CacheEntry]  # hash -> original
    max_entries: int = 500
    ttl_seconds: int = 600                # 10 分钟

    def store(self, original: str, compressed: str) -> str
        # 返回 24-char hex hash (SHA256 截断)

    def retrieve(self, hash_id: str) -> str | None
        # 取回原文, 命中时更新 LRU

    def search(self, hash_id: str, keywords: list[str]) -> str | None
        # 在原文中搜索关键词, 返回相关片段

# marker.py
MARKER_PATTERN = r'\[(\d+) items? compressed to (\d+)\. Retrieve: hash=([a-f0-9]{24})\]'

def embed_marker(compressed: str, original_count: int, compressed_count: int, hash_id: str) -> str
def extract_markers(text: str) -> list[MarkerInfo]
def has_markers(text: str) -> bool

# retriever.py — 生成 provider-specific tool 定义
def snapback_tool_def(provider: str) -> dict
    # provider: "anthropic" | "openai" | "google"
    # 返回对应格式的 tool/function 定义

def handle_retrieval(store: SnapBackStore, tool_call: dict) -> dict
    # 处理 LLM 的 snapback_retrieve tool call
    # 返回 tool_result
```

**SnapBack 工作流:**
1. 任何 Transform 压缩时，如果压缩率 > 20%，调用 `store.store(original, compressed)` 获取 hash
2. 在压缩文本末尾嵌入标记: `[150 items compressed to 15. Retrieve: hash=abc123...]`
3. Proxy 层在发请求前扫描所有 message，如果有标记，注入 `snapback_retrieve` tool
4. LLM 可以调用 tool 取回原文
5. Proxy 层拦截 tool call，从 store 取回，构造 tool_result，继续对话

### 1.3 迁移现有压缩器到 Transform 接口

将现有模块包装为 Transform:

```
scripts/lib/transforms/
  rule_engine.py       # 包装 compress_memory.py
  dictionary.py        # 包装 lib/dictionary.py
  dedup.py             # 包装 lib/dedup.py
  rle.py               # 包装 lib/rle.py
  tokenizer_opt.py     # 包装 lib/tokenizer_optimizer.py
  markdown_opt.py      # 包装 lib/markdown.py
```

每个 Transform wrapper:
- 实现 `should_apply()` 门控 (基于 content_type, role, token count)
- 实现 `apply()` 调用底层函数
- 返回 `TransformResult` 含 timing 和 token 统计
- **不改动底层函数** — 纯包装

**执行顺序:**
```
order=10  RuleEngine         # 结构清理
order=20  MarkdownOptimizer  # Markdown 格式优化
order=30  TokenizerOptimizer # tokenizer-aware 优化
order=40  RLE                # 路径/IP/枚举压缩
order=50  Dictionary         # 字典别名压缩
order=60  Dedup              # 去重 (最后, 因为前面的步骤可能产生新的重复)
```

### 1.4 测试

- Pipeline 引擎单元测试: 顺序执行、跳过、计时
- SnapBack store: 存储/取回/过期/LRU 淘汰
- SnapBack marker: 嵌入/提取/正则
- 现有 919 测试不回归

---

## Phase 2 — 智能内容路由 + 代码压缩 (Claw Router + CodeCrunch)

**目标:** 自动识别内容类型 + AST-based 代码压缩
**预计改动:** 5 个新文件
**新依赖:** `tree-sitter-language-pack` (可选)

### 2.1 Claw Router — 内容分类与路由

```
scripts/lib/transforms/
  router.py            # 内容路由 Transform
  content_detector.py  # 内容类型检测器
```

**ContentDetector 检测策略 (纯正则, 无 ML 依赖):**

```python
class ContentDetector:
    def detect(self, text: str) -> DetectionResult:
        # 返回 (content_type, language, confidence)

    # 检测规则优先级:
    # 1. Markdown 代码围栏 → 提取语言标记
    # 2. Shebang 行 (#!/usr/bin/python) → 代码
    # 3. JSON 首字符 [ 或 { + 有效 parse → json
    # 4. import/from/def/class/function 关键词密度 → 代码
    # 5. 时间戳 + 日志级别模式 (INFO/WARN/ERROR) → log
    # 6. diff 头部 (--- a/ +++ b/ @@ ) → diff
    # 7. 文件路径:行号 模式 → search (grep 输出)
    # 8. 默认 → text
```

**Router Transform (order=5, 最先执行):**
```python
class ClawRouter(Transform):
    """分析 content_type, 设置到 ctx 上供下游 transform 使用"""
    order = 5

    def apply(self, ctx):
        detection = self.detector.detect(ctx.content)
        # 如果是混合内容 (代码围栏内嵌代码):
        #   拆分为 sections, 各自标记 type
        #   后续 transform 对每个 section 独立处理
        return ctx.replace(content_type=detection.type, language=detection.language)
```

**混合内容处理:**
- 检测 markdown 代码围栏 (```)
- 拆分为 (text_section, code_section, text_section, ...)
- 每个 section 独立走 pipeline
- 最后按原始顺序拼接

### 2.2 CodeCrunch — AST-Based 代码压缩

```
scripts/lib/transforms/
  code_crunch.py       # AST 代码压缩 Transform
```

**核心设计 (独立实现, tree-sitter 驱动):**

```python
class CodeCrunch(Transform):
    """AST-aware 代码压缩"""
    order = 25  # 在 MarkdownOptimizer 之后

    SUPPORTED_LANGS = {
        "python": LangProfile(imports="import_statement", func="function_definition", ...),
        "javascript": LangProfile(imports="import_statement", func="function_declaration", ...),
        "typescript": LangProfile(...),
    }

    def should_apply(self, ctx):
        return ctx.content_type == "code" and ctx.language in self.SUPPORTED_LANGS

    def apply(self, ctx):
        tree = self._parse(ctx.content, ctx.language)
        profile = self.SUPPORTED_LANGS[ctx.language]

        # 1. 保留: imports, 函数/类签名, 类型注解, 错误处理
        # 2. 压缩: 函数体 (保留首行注释 + return 语句)
        # 3. 删除: 纯注释块, 空行, docstring (可配置保留首行)
        # 4. 排序函数: 被调用次数多的保留更多 body

        compressed = self._rebuild(tree, profile, ctx)
        # SnapBack: 存储原文
        hash_id = self.store.store(ctx.content, compressed)
        return TransformResult(
            content=embed_marker(compressed, ...),
            markers=[hash_id],
        )
```

**无 tree-sitter 降级方案 (order=25, 同一 Transform):**
```python
    def _fallback_compress(self, text, language):
        """正则降级: 不做 identifier shortening, 只做安全操作"""
        # 1. 删除纯注释行 (保留 type: ignore 等)
        # 2. 删除空行
        # 3. 折叠连续 import 为单行
        # 4. 折叠 docstring 为首行
        # 5. 不改标识符名 (教训: identifier shortening 是最大杀手)
```

### 2.3 测试

- ContentDetector: 每种类型 5+ 样本
- CodeCrunch: Python/JS/TS 各 3 个真实代码文件
- 降级路径: 无 tree-sitter 时的行为
- 压缩后代码仍可被 LLM 理解 (E2E)

---

## Phase 3 — 结构化数据压缩 (ShellCracker + LogCrunch + SearchCrunch)

**目标:** JSON 数组智能采样 + 日志/搜索结果专用压缩
**预计改动:** 4 个新文件
**新依赖:** 无

### 3.1 ShellCracker — JSON/结构化数据压缩

```
scripts/lib/transforms/
  shell_cracker.py     # JSON 数组压缩
```

**核心算法 (独立实现):**

```python
class ShellCracker(Transform):
    """JSON 数组统计采样压缩"""
    order = 15  # Router 之后, 其他之前

    def should_apply(self, ctx):
        return ctx.content_type == "json"

    def apply(self, ctx):
        data = json.loads(ctx.content)
        if not isinstance(data, list) or len(data) < 5:
            return TransformResult(content=ctx.content, skipped=True)

        if all(isinstance(item, dict) for item in data):
            return self._compress_dict_array(data, ctx)
        elif all(isinstance(item, str) for item in data):
            return self._compress_string_array(data, ctx)
        else:
            return self._compress_mixed(data, ctx)
```

**字典数组压缩策略:**
1. **Schema 发现** — 收集所有 key, 计算每个 field 的:
   - unique_ratio (唯一值占比)
   - 类型分布 (str/int/float/bool/null)
   - 对于数值: min/max/mean/std
2. **ID 字段检测** — UUID 格式 OR unique_ratio > 0.9 OR 连续递增
3. **错误项保护** — 含 "error"/"exception"/"failed" 的项永不丢弃
4. **采样策略:**
   - 前 K + 后 K 项必保留 (K = max(2, len//20))
   - 如果有 query, 用关键词匹配保留高相关项
   - 剩余空间均匀采样
5. **输出:** 采样后的 JSON 数组 + SnapBack 标记

### 3.2 LogCrunch — 日志压缩

```
scripts/lib/transforms/
  log_crunch.py        # 构建/测试日志压缩
```

**策略:**
1. 识别重复模式 (相同前缀的连续行)
2. 保留: 首次出现 + 最后出现 + 计数
3. 保留: 所有 ERROR/WARN/FATAL 行
4. 保留: 所有包含 "failed"/"error"/"exception" 的行
5. 保留: 所有 stack trace (缩进行块)
6. 压缩: 重复的 INFO/DEBUG 行 → `[... 重复 N 次 ...]`
7. 时间戳归一化: 保留相对时间差而非绝对时间

### 3.3 SearchCrunch — 搜索结果压缩

```
scripts/lib/transforms/
  search_crunch.py     # grep/ripgrep 输出压缩
```

**策略:**
1. 解析 `文件:行号:内容` 格式
2. 按文件分组
3. 去重完全相同的匹配行
4. 同文件连续行合并为范围 (e.g., lines 10-15)
5. 超过 N 个文件时, 按匹配次数排序, 保留 top-N
6. SnapBack 存原文

### 3.4 DiffCrunch — Diff 压缩

```
scripts/lib/transforms/
  diff_crunch.py       # git diff 压缩
```

**策略:**
1. 保留: 文件头 (`--- a/` / `+++ b/`)
2. 保留: hunk 头 (`@@ ... @@`)
3. 保留: 所有 `+` 和 `-` 行
4. 压缩: context 行 (不变的行) — 只保留首尾各 1 行
5. 大文件 diff (>200 行) → 统计摘要 + SnapBack

### 3.5 测试

- ShellCracker: 5 种 JSON 结构 (dict array, string array, nested, mixed, empty)
- LogCrunch: 真实构建日志 + 测试日志
- SearchCrunch: ripgrep 输出样本
- DiffCrunch: 真实 git diff 样本

---

## Phase 4 — ML Token 分类器 (Crunch)

**目标:** 用 fine-tuned ModernBERT 做 token-level 保留/丢弃决策
**预计改动:** 3 个新文件
**新依赖:** `torch`, `transformers` (可选)

### 4.1 Crunch — ML Token 压缩器

```
scripts/lib/transforms/
  crunch.py            # ML token compressor
  crunch_model.py      # 模型定义 + 推理
```

**模型架构 (独立训练):**
```python
class CrunchModel(nn.Module):
    """双头 ModernBERT token 分类器"""
    def __init__(self):
        self.backbone = AutoModel.from_pretrained("answerdotai/ModernBERT-base")
        # Token head: 每个 token 二分类 (keep/discard)
        self.token_head = nn.Linear(768, 2)
        # Span head: 1D CNN 判断区域重要性
        self.span_head = nn.Sequential(
            nn.Conv1d(768, 256, kernel_size=5, padding=2),
            nn.GELU(),
            nn.Conv1d(256, 1, kernel_size=3, padding=1),
            nn.Sigmoid(),
        )

    def forward(self, input_ids, attention_mask):
        hidden = self.backbone(input_ids, attention_mask).last_hidden_state
        token_logits = self.token_head(hidden)         # (B, L, 2)
        span_scores = self.span_head(hidden.transpose(1,2)).squeeze(1)  # (B, L)
        return token_logits, span_scores
```

**融合逻辑:**
- token_prob = softmax(token_logits)[:, :, 1]
- keep = (token_prob > 0.5) OR (0.3 < token_prob < 0.5 AND span_score > 0.6)
- 即: token head 确定保留 OR (token head 犹豫但 span head 认为重要)

**训练数据来源 (利用 SIGMA v2 已有标注):**
- 复用 OpenCompress SIGMA 的标注数据
- 补充: CC 自己的 benchmark 测试集
- 目标: 5,000+ 标注样本

**Transform 集成:**
```python
class CrunchTransform(Transform):
    order = 35  # CodeCrunch 之后

    def should_apply(self, ctx):
        return (ctx.content_type == "text"
                and len(ctx.content.split()) >= 20
                and TORCH_AVAILABLE)

    def apply(self, ctx):
        compressed = self.model.compress(ctx.content)
        # SnapBack
        hash_id = self.store.store(ctx.content, compressed)
        return TransformResult(content=embed_marker(compressed, ...), ...)
```

**无 torch 降级:** 跳过此 Transform, 完全依赖规则引擎

### 4.2 测试

- 模型推理: mock weights 验证 forward pass
- 融合逻辑: 边界条件
- 降级路径: 无 torch 时的行为

---

## Phase 5 — Proxy 层集成 (Claw Proxy + PrefixLock)

**目标:** 透明 HTTP proxy + KV cache 对齐
**预计改动:** proxy/ 下 4 个文件
**新依赖:** 无 (Node.js 已有)

### 5.1 Claw Proxy — 透明压缩代理

在现有 `proxy/server.mjs` 上增加压缩中间件:

```javascript
// proxy/compression-middleware.mjs
export function createCompressionMiddleware(config) {
    return async (messages, model, tools) => {
        // 1. 遍历所有 tool role messages
        // 2. 调用 Python pipeline (subprocess 或 HTTP)
        // 3. 扫描压缩后的 messages 是否有 SnapBack 标记
        // 4. 如果有, 注入 snapback_retrieve tool 定义
        // 5. 返回压缩后的 messages + 增强后的 tools
    }
}
```

**Python pipeline 调用方式:**
- 选项 A: subprocess `python3 -m scripts.pipeline --stdin --json` (简单, 无常驻进程)
- 选项 B: 内嵌 FastAPI server on unix socket (性能好, 适合高 QPS)
- **推荐: 选项 A 起步, 后续按需升级**

**SnapBack Response 拦截:**
```javascript
// proxy/snapback-handler.mjs
export function createSnapBackHandler(store) {
    return {
        // 检测 LLM response 中的 snapback_retrieve tool call
        detectToolCall(response) { ... },
        // 执行检索, 构造 tool_result, 继续对话
        handleRetrieval(toolCall) { ... },
        // 流式响应: buffer 检测 tool call
        createStreamHandler() { ... },
    }
}
```

### 5.2 PrefixLock — KV Cache 对齐

```javascript
// proxy/prefix-lock.mjs
export function createPrefixLock() {
    return {
        // 从 system message 中提取动态内容 (日期, UUID, API key, JWT)
        extractDynamic(systemMessage) { ... },
        // 将动态内容移到 system message 末尾
        // 保持前缀稳定 → 最大化 KV cache 命中
        stabilize(systemMessage) { ... },
        // 返回稳定前缀的 hash (用于监控 cache 命中率)
        getPrefixHash(systemMessage) { ... },
    }
}
```

**动态内容检测模式:**
- ISO 日期/时间 (`2026-03-17`, `10:30:00`)
- UUID (`[a-f0-9]{8}-[a-f0-9]{4}-...`)
- Unix 时间戳 (10位/13位数字)
- JWT (`eyJ...`)
- API Key (`sk-...`, `pk_...`)
- 请求/追踪 ID (高 entropy 字符串)

### 5.3 测试

- Compression middleware: mock Python subprocess
- SnapBack handler: tool call 检测 + 检索
- PrefixLock: 动态内容提取 + 前缀稳定性
- E2E: 完整请求流 (压缩 → LLM → SnapBack 取回)

---

## Phase 6 — 图片压缩 + 学习引擎 (PixelCrunch + Engram v2)

**目标:** 图片 token 节省 + 从失败中学习
**预计改动:** 4 个新文件
**新依赖:** `Pillow` (可选)

### 6.1 PixelCrunch — 图片优化

```
scripts/lib/transforms/
  pixel_crunch.py      # 图片压缩
```

**策略 (不用 ML, 纯规则):**
1. 检测 message 中的 base64 图片 (OpenAI/Anthropic/Google 三种格式)
2. 规则路由:
   - 图片 > 1MB → 降到 512px 宽, JPEG quality=85
   - 图片 > 2MB → 降到 384px 宽, JPEG quality=75
   - PNG 截图 → 转 JPEG (通常节省 60%+)
   - OpenAI 格式: 设 `detail: "low"` (最简单, 87% 节省)
3. Token 估算: (width/512) * (height/512) * 85 + 170

**无 Pillow 降级:**
- OpenAI 格式: 仍可设 `detail: "low"`
- 其他格式: 跳过

### 6.2 Engram v2 — 失败学习引擎

增强现有 Engram:

```
scripts/lib/
  engram_learner.py    # 从 session 失败中学习
```

**学习流程:**
1. 扫描 session JSONL 日志
2. 提取失败事件: tool call 错误, 用户打断, 超时, 构建失败
3. 分类 (14 种错误模式: FILE_NOT_FOUND, MODULE_NOT_FOUND, PERMISSION_DENIED, ...)
4. 需要 evidence_count >= 2 才生成规则 (避免一次性错误)
5. 调用 LLM 生成压缩建议 (哪些 context 可以安全丢弃)
6. 输出到 MEMORY.md 的 `<!-- claw-compactor:learn:start -->` 区域

**与 Engram v1 的区别:**
- v1: 观察对话 → 生成长期记忆
- v2: 分析失败 → 生成压缩规则 (互补, 不替代)

### 6.3 测试

- PixelCrunch: base64 图片降质 + token 估算
- Engram learner: 错误分类 + 规则生成

---

## Phase 7 — 评估框架 + 压缩反馈 (CrunchBench + FeedbackLoop)

**目标:** 量化压缩质量 + 闭环反馈
**预计改动:** 3 个新文件

### 7.1 CrunchBench — 多维评估

```
benchmark/
  crunch_bench.py      # 评估引擎
  datasets/            # 测试数据集
```

**评估维度:**
1. **压缩率** — 原始 tokens / 压缩 tokens
2. **精度保持** — 压缩后 LLM 回答质量 vs 原文 (LLM-as-judge)
3. **可逆性** — SnapBack 取回后与原文的完全匹配率
4. **延迟** — 每个 transform 的执行时间
5. **成本节省** — 按模型定价计算实际美元节省

**数据集:**
- 真实 OpenClaw session (已有)
- SWE-bench 样本 (已有)
- 合成代码/JSON/日志 混合样本

### 7.2 FeedbackLoop — 压缩反馈

```
scripts/lib/
  feedback.py          # 追踪 SnapBack 取回事件
```

**设计:**
- 每次 SnapBack 取回记录: hash, 原始 transform, 压缩率, 是否被取回
- 统计: 哪些 transform 的输出最常被 LLM 取回 → 说明压缩太激进
- 自动调整: 被频繁取回的 transform 降低压缩率

---

## 执行时间线

| Phase | 内容 | 预计文件数 | 新测试数 |
|-------|------|-----------|---------|
| **Phase 1** | Pipeline + SnapBack + 迁移现有 | 11 | 60+ |
| **Phase 2** | Router + CodeCrunch | 5 | 40+ |
| **Phase 3** | ShellCracker + LogCrunch + SearchCrunch + DiffCrunch | 4 | 50+ |
| **Phase 4** | Crunch (ML) | 3 | 20+ |
| **Phase 5** | Proxy 集成 + PrefixLock | 4 | 30+ |
| **Phase 6** | PixelCrunch + Engram v2 | 4 | 25+ |
| **Phase 7** | CrunchBench + FeedbackLoop | 3 | 15+ |

**总计:** ~34 个新文件, 240+ 新测试, 现有 919 测试不回归

---

## 命名体系总结

| 原概念 | CC v7 命名 | 灵感来源 |
|--------|-----------|----------|
| Reversible compression | **SnapBack** | 弹回原文 |
| Content routing | **Claw Router** | 蟹钳分拣 |
| AST code compression | **CodeCrunch** | 咬碎代码 |
| JSON array sampling | **ShellCracker** | 破壳取肉 |
| ML token compression | **Crunch** | 核心压碎 |
| Cache alignment | **PrefixLock** | 锁定前缀 |
| Image optimization | **PixelCrunch** | 像素压缩 |
| Log compression | **LogCrunch** | 日志压缩 |
| Search result compression | **SearchCrunch** | 搜索压缩 |
| Diff compression | **DiffCrunch** | 差异压缩 |
| Failure learning | **Engram v2** | 延续品牌 |
| Evaluation suite | **CrunchBench** | 压测基准 |
| Compression feedback | **FeedbackLoop** | 反馈闭环 |
| Transform base | **Transform** | 通用变换 |
| Transform chain | **Pipeline** | 管道 |

所有命名保持 "Claw/Crunch/Shell" 系列, 符合龙虾/蟹 品牌一致性。

---

## 风险与缓解

| 风险 | 概率 | 影响 | 缓解 |
|------|------|------|------|
| tree-sitter 安装困难 | 中 | 低 | 正则降级, 可选依赖 |
| ML 模型训练数据不足 | 中 | 中 | 复用 SIGMA 标注, 规则引擎兜底 |
| Pipeline 引入延迟 | 低 | 中 | 每个 transform 计时, 超时跳过 |
| SnapBack store 内存溢出 | 低 | 高 | LRU + TTL + max_entries 硬上限 |
| 现有测试回归 | 低 | 高 | 现有模块纯包装, 不改内部逻辑 |
| Proxy subprocess 延迟 | 中 | 中 | 起步用 subprocess, 后续切 unix socket |

---

## 不做的事

1. **不做图片 ML 路由** — 纯规则足够, 避免 torch 依赖膨胀
2. **不做 SharedContext (多 agent 共享压缩)** — OpenClaw 已有自己的 agent 通信
3. **不做 MCP server** — 优先 proxy 模式
4. **不做 semantic cache** — proxy 已有 L1+L2 cache
5. **不做 TOIN (tool 学习网络)** — 过于复杂, Engram v2 的失败学习已够用
