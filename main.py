# -*- coding: utf-8 -*-
"""SauceNAO 搜图插件。

指令：
    #&搜图      然后 30 秒内发一张图

修正点：
1. 不再把图片地址直接丢给 SauceNAO（群图多为本地缓存路径，公网抓不到），
   改成读取文件后 multipart 上传。
2. 检查 SauceNAO 返回的 header.status，额度用完/图片过大都会明确提示。
3. 等待用户发图用后台任务计时，不阻塞事件处理。
"""
import asyncio
import base64
import os
import time
import tempfile

import aiohttp

from astrbot.api.all import *
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.message_components import Image, Plain
from astrbot.api.star import Context, Star, register

SAUCENAO_ENDPOINT = "https://saucenao.com/search.php"

USER_STATES = {}   # uid -> 发起时间戳
MAX_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------- 图片处理

def _local_path(comp: Image):
    """拿 Image 组件对应的本地文件路径，没有就返回 None。"""
    for attr in ("path", "file"):
        p = getattr(comp, attr, None)
        if isinstance(p, str) and p and not p.startswith(("http://", "https://", "base64://")):
            if os.path.exists(p):
                return p
    return None


async def _read_image(comp: Image, session: aiohttp.ClientSession):
    """把图片读成 bytes，返回 (bytes, 文件名)。失败抛异常。"""
    p = _local_path(comp)
    if p:
        with open(p, "rb") as f:
            return f.read(), os.path.basename(p)

    url = getattr(comp, "url", None) or ""
    if url.startswith("base64://"):
        raw = base64.b64decode(url[len("base64://"):])
        return raw, "image.png"
    if url.startswith(("http://", "https://")):
        async with session.get(url, timeout=30) as r:
            r.raise_for_status()
            return await r.read(), "image.png"
    raise RuntimeError("拿不到图片内容")


# ---------------------------------------------------------------- 查询

async def search_bytes(raw: bytes, filename: str, api_key: str, numres: int = 5):
    """上传图片到 SauceNAO，返回 (status, message, results)。"""
    if len(raw) > MAX_BYTES:
        return (-2, "图片太大了（超过 10MB）", [])
    form = aiohttp.FormData()
    form.add_field("file", raw, filename=filename or "image.png",
                   content_type="application/octet-stream")
    form.add_field("output_type", "2")
    form.add_field("numres", str(numres))
    form.add_field("api_key", api_key)

    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(SAUCENAO_ENDPOINT, data=form) as resp:
            text = await resp.text()
            if resp.status == 403:
                return (-1, "API Key 不对，或者这个 key 没权限", [])
            if resp.status == 429:
                return (-2, "请求太频繁，被限流了，等一会儿再来", [])
            if resp.status != 200:
                return (resp.status, "接口返回 HTTP %d" % resp.status, [])
            import json
            try:
                data = json.loads(text)
            except Exception:
                return (-3, "返回的不是 JSON，可能被限流了", [])
    header = data.get("header", {})
    status = header.get("status", 0)
    if status == -1:
        return (-1, "API Key 不对", [])
    if status == -2:
        return (-2, "额度用完了（今天的次数或 30 秒内的次数超了）", [])
    if status == -3:
        return (-3, "图片传不上去，换个格式试试", [])
    if status != 0:
        return (status, header.get("message") or "未知错误", [])

    results = sorted(data.get("results") or [],
                     key=lambda x: float(x.get("header", {}).get("similarity", 0) or 0),
                     reverse=True)
    return (0, "", results)


def format_results(results, limit: int = 5):
    """把结果整理成消息组件。"""
    chain = [Plain("搜到了（可能性从高到低）：\n")]
    for idx, res in enumerate(results[:limit], 1):
        header = res.get("header", {})
        data = res.get("data", {})
        sim = header.get("similarity", "?")
        author = (data.get("member_name") or data.get("creator")
                  or data.get("author_name") or "未知")
        title = data.get("title") or data.get("source") or ""
        urls = data.get("ext_urls") or []
        thumb = header.get("thumbnail") or ""

        line = "\n#%d 相似度 %s%%\n作者：%s" % (idx, sim, author)
        if title:
            line += "\n标题：%s" % str(title)[:60]
        line += "\n原图：%s\n" % (urls[0] if urls else "无原链接")
        chain.append(Plain(line))
        if thumb:
            chain.append(Image.fromURL(thumb))
    return chain


# ---------------------------------------------------------------- 插件

@register("sauceno_search", "Hazellol", "SauceNAO 搜图", "1.0.1")
class SauceNAOSearch(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        self.api_key = str(self.config.get("saucenao_api", "")).strip()
        try:
            self.wait_seconds = int(self.config.get("wait_seconds", 30))
        except Exception:
            self.wait_seconds = 30

    @filter.command("搜图")
    async def cmd_search(self, event: AstrMessageEvent):
        if not self.api_key:
            yield event.plain_result("还没配 SauceNAO API Key，去插件配置里填一下。")
            return
        uid = str(event.get_sender_id())
        t0 = time.time()
        USER_STATES[uid] = t0
        yield event.plain_result("%d 秒内把图发上来。" % self.wait_seconds)

        async def _expire():
            await asyncio.sleep(self.wait_seconds)
            if USER_STATES.get(uid) == t0:
                USER_STATES.pop(uid, None)
                try:
                    await event.send(event.plain_result("等太久了，作废。"))
                except Exception:
                    pass

        asyncio.create_task(_expire())

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_image(self, event: AstrMessageEvent):
        uid = str(event.get_sender_id())
        if uid not in USER_STATES:
            return

        images = [c for c in event.message_obj.message if isinstance(c, Image)]
        if not images:
            return

        USER_STATES.pop(uid, None)
        yield event.plain_result("找一下……")

        try:
            timeout = aiohttp.ClientTimeout(total=90)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                raw, name = await _read_image(images[0], session)
            status, msg, results = await search_bytes(raw, name, self.api_key)
        except Exception as e:
            logger.error("[sauceno] 搜索失败: %r" % (e,))
            yield event.plain_result("挂了：%s" % str(e)[:100])
            return

        if status != 0:
            yield event.plain_result("搜不了：%s" % msg)
            return
        if not results:
            yield event.plain_result("没找到匹配的。")
            return

        try:
            yield event.chain_result(format_results(results))
        except Exception:
            yield event.plain_result(format_results(results)[0].text if hasattr(
                format_results(results)[0], "text") else "结果发不出来")
