# duck.ai 无浏览器 Python 客户端

结论先说：**可行**。不需要 Chrome、不需要过 Cloudflare（duck.ai 前面就是 nginx），
只要一个 JS 运行时（node + jsdom）来执行服务端下发的反滥用挑战脚本。

    python3 duckai_client.py "用一句话解释量子纠缠"        # 默认 gpt-6-luna
    python3 duckai_client.py "17*23=?" haiku              # 换模型

实测（本机，2026-10-22）：单次问答 3–6 秒，含 node 启动约 1.4 秒。

## 协议（从 entry.duckai.js 逆向 + 抓包验证）

    1. GET  https://duck.ai/                        200  HTML，取 data-version-tag / data-version-sha
                                                      -> x-fe-version = "<tag>-<sha>"
    2. GET  /duckchat/v1/status  (x-vqd-accept: 1)  200  响应头 x-vqd-hash-1 = base64(挑战 JS)
    3. 执行挑战 JS                                   -> {server_hashes, client_hashes, signals, meta}
    4. X-Vqd-Hash-1 = base64(JSON(...))              其中 client_hashes = base64(sha256(原始字符串))
    5. POST /duckchat/v1/chat                       200  SSE（data: {...message...}）

请求头（chat）：

    Content-Type: application/json
    Accept: text/event-stream
    Origin: https://duck.ai        Referer: https://duck.ai/
    x-fe-version: <tag>-<sha>      x-fe-signals: base64({"start":..,"events":[..],"end":..})
    X-Vqd-Hash-1: <第 4 步的 proof>

请求体（durableStream 会要求 RSA 公钥，直接不传即可）：

    {"model":"gpt-6-luna",
     "messages":[{"role":"user","content":[{"type":"text","text":"..."}]}],
     "canUseTools":false,"reasoningEffort":"none","canUseApproxLocation":null,
     "canDelegateImageGeneration":null,"canShowGreeting":false}

模型 id：gpt-6-luna / gpt-5.6-luna / gpt-5.4-nano / gpt-5.4-mini /
claude-haiku-4-5 / mistral-small-2603
（已实测可用：gpt-6-luna、gpt-5.4-nano、claude-haiku-4-5、mistral-small-2603；
`tinfoil/gpt-oss-120b`、`tinfoil/gemma4-31b` 这条路径上返回 400，未通）

## 挑战（X-Vqd-Hash-1 / "jsa"）到底是什么

- 每次 `/status` 返回一段混淆过的 `(async function(){...})()`，里面含
  随机基数和 `server_hashes`、`challenge_id`、`timestamp`。
- 脚本做三件事：读 `navigator.userAgent`；创建一个
  `display:inline-block;padding:8px;visibility:hidden` 的 div 量
  offsetWidth/offsetHeight/getBoundingClientRect/innerHTML 解析结果；
  读 `navigator.webdriver` 并做 iframe/proxy 探测。
  每项结果变成一个字符串（`<随机基数> + 若干布尔值`）。
- 外层（web 包里 35488 模块）把这三个字符串分别 sha256 再 base64，
  连同 `server_hashes` 和 `meta{origin,stack,duration}` 一起 base64(JSON)
  塞进 `X-Vqd-Hash-1`。
- **服务端会精确校验这些数值**：把其中一项 +1 重放，立刻 418
  (`overrideCode: 8e04` / `3501`)。所以必须真执行挑战脚本，不能瞎填。

`jsa_jsdom.js` 用 jsdom 执行它，并给 jsdom 补上缺失的排版指标
（offsetWidth=17 / offsetHeight=35 / 非零 getBoundingClientRect）。
实测与真实 Chrome 完全一致：同一份挑战，Chrome 得 `["<UA>","5510","7687"]`，
jsdom 得 `["<UA>","5510","7686"]` —— 只差 webdriver 那一位（Chrome 被 CDP
驱动时是 true，我们按普通浏览器填 false）。8/8 个不同挑战变体都能解。

## 会踩的坑

| 现象 | 原因 | 处理 |
|---|---|---|
| 418 `ERR_CHALLENGE` + 网页弹「选鸭子」验证码 | UA 含 `HeadlessChrome`、或 `navigator.webdriver=true` | 用普通 Chrome UA，webdriver 报 false |
| 418 `overrideCode 3501 / 8e04` | proof 数值不对（伪造/过期的挑战） | 每次请求重新取挑战并真解 |
| 418 `overrideCode d78d`（连续多次） | 短时间请求太多，风控冷却 | 退避重试（客户端已内建 4 次、2/4/6s） |
| 400 `ERR_BAD_REQUEST` | body 里带了缺公钥的 `durableStream` | 不要传 durableStream |
| 返回中文乱码 | SSE 无 charset，`iter_lines(decode_unicode=True)` 用 latin-1 | 按 bytes 读再 utf-8 解码（已处理） |

成功率实测约 3/4（突发多次会被冷却十几秒）。这是 DuckDuckGo 自家风控，
不是 Cloudflare，也不绑定 IP 段——同一台机器用正常 UA 的浏览器就能过。

## 文件

- `duckai_client.py`  — 主客户端（协议 + 重试 + 流式输出）
- `jsa_jsdom.js`      — jsdom 挑战求解器（输入挑战 JS，输出 proof 原料 JSON）
- `check_variants.py` — 连解 8 个挑战变体，验证求解器没退化
- `deob.js`           — 调试用：还原挑战脚本里的混淆字符串表
- `legacy/`           — 早期失败的尝试（chromedp / DOM stub / 抓包），留档

## 依赖

    pip install requests
    npm install jsdom          # node >= 18

## 和 benoitpetit/duckduckgo-chat-cli 的差别

它用 chromedp 打开真 Chrome，拦下真实请求把 `X-Vqd-Hash-1` 抄出来再重放
（所以它强制要求装 Chrome）。这里的做法是：同样抄协议，但挑战用 jsdom 自己算，
服务器上不需要任何浏览器；只有在 DDG 把挑战改成依赖 canvas/WebGL 之类的
真浏览器 API 时才需要退回 chromedp 方案。
