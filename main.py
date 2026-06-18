"""
Ayabot 礼物统计查询插件
━━━━━━━━━━━━━━━━━━━━
配合 Ayabot B站直播间机器人使用，让 QQ 群成员可以：
  - 绑定自己的 B站 UID
  - 查询本日/本周/本月/全部时间的礼物投喂、盲盒数量与盈亏

指令列表:
  /绑定 <B站UID>          绑定自己的 QQ 号到 B站 UID
  /解绑                   解除绑定
  /礼物查询 [today|week|month|all]  查询礼物/盲盒统计（默认今天）
  /设置API <URL> <密钥> [房间号]    群管理员设置本群的 API 配置
  /查看API                查看当前群的 API 配置状态
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star
import astrbot.api.message_components as Comp


# ═══════════════════════════════════════════
#  HTML 渲染模板
# ═══════════════════════════════════════════

GIFT_CARD_HTML = '''<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
*{margin:0;padding:0;box-sizing:border-box;font-family:'PingFang SC','Microsoft YaHei',sans-serif;}
body{background:#fff;display:flex;justify-content:center;padding:0;}
.card{width:340px;background:#fff;padding:14px 16px;}
/* 顶部用户信息 */
.user-header{display:flex;align-items:center;gap:12px;margin-bottom:14px;}
.avatar-wrap{position:relative;width:48px;height:48px;flex-shrink:0;}
.avatar-wrap img.face{width:48px;height:48px;border-radius:50%;object-fit:cover;display:block;}
.avatar-wrap .guard-frame{position:absolute;top:-4px;left:-4px;width:56px;height:56px;pointer-events:none;}
.user-info{flex:1;min-width:0;}
.user-info .uname{font-size:17px;font-weight:700;color:#2d1b69;line-height:1.3;}
.user-info .meta{font-size:12px;color:#8b7dad;margin-top:1px;}
.badge{display:inline-block;background:linear-gradient(135deg,#7c3aed,#a855f7);color:#fff;font-size:12px;font-weight:600;padding:3px 12px;border-radius:20px;flex-shrink:0;align-self:flex-start;margin-top:2px;}
.divider{height:1px;background:linear-gradient(90deg,transparent,rgba(120,80,200,0.12),transparent);margin:10px 0;}
/* 统计网格 2列 */
.stats-grid{display:grid;grid-template-columns:1fr 1fr;gap:6px;margin-bottom:6px;}
.stat-item{background:rgba(120,80,200,0.04);border-radius:8px;padding:8px;text-align:center;}
.stat-item .s-label{font-size:10px;color:#8b7dad;margin-bottom:1px;}
.stat-item .s-value{font-size:16px;font-weight:700;color:#2d1b69;}
.section-title{font-size:14px;font-weight:700;color:#2d1b69;margin:10px 0 6px;}
/* 礼物网格 - 2列 */
.gift-grid{display:grid;grid-template-columns:1fr 1fr;gap:4px;}
.gift-item{display:flex;align-items:center;gap:6px;padding:6px 8px;background:rgba(120,80,200,0.02);border-radius:6px;}
.gift-item .gift-icon{width:22px;height:22px;border-radius:4px;object-fit:contain;flex-shrink:0;}
.gift-item .gift-info{flex:1;min-width:0;}
.gift-item .gift-info .gift-name{color:#4a3580;font-weight:500;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.gift-item .gift-info .gift-meta{display:flex;justify-content:space-between;font-size:11px;color:#8b7dad;margin-top:1px;}
.gift-item .gift-info .gift-meta .gift-value{color:#7c3aed;font-weight:600;}
/* 盲盒 */
.box-header{display:flex;justify-content:space-between;align-items:center;padding:7px 10px;background:rgba(124,58,237,0.07);border-radius:6px;margin:4px 0 2px;}
.box-header .box-title{font-size:13px;font-weight:600;color:#2d1b69;}
.box-header .box-profit{font-size:12px;font-weight:600;}
.box-item{display:flex;align-items:center;gap:6px;padding:4px 10px 4px 14px;}
.box-item .box-icon{width:18px;height:18px;border-radius:3px;object-fit:contain;flex-shrink:0;}
.box-item .box-name{flex:1;font-size:12px;color:#5a4570;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.box-item .box-num{font-size:11px;color:#8b7dad;text-align:right;white-space:nowrap;}
.box-item .box-profit{font-size:12px;text-align:right;min-width:44px;}
.profit-plus{color:#10b981;}
.profit-minus{color:#ef4444;}
.footer{text-align:center;font-size:10px;color:#c0b0d8;margin-top:12px;padding-top:8px;border-top:1px solid rgba(120,80,200,0.08);}
</style></head><body><div class="card">
<div class="user-header">
  <div class="avatar-wrap">
    {% if avatar %}<img class="face" src="{{ avatar }}" alt="" onerror="this.style.display='none'">{% endif %}
    <svg class="guard-frame" viewBox="0 0 64 64" fill="none" xmlns="http://www.w3.org/2000/svg">
      <circle cx="32" cy="32" r="30" stroke="#c084fc" stroke-width="2" fill="none" opacity="0.6"/>
      <circle cx="32" cy="32" r="28" stroke="#a78bfa" stroke-width="1" fill="none" opacity="0.3"/>
    </svg>
  </div>
  <div class="user-info">
    <div class="uname">{{ uname }}</div>
    <div class="meta">UID {{ uid }}</div>
  </div>
  <span class="badge">{{ label }}</span>
</div>
<div class="stats-grid">
  <div class="stat-item"><div class="s-label">总投喂</div><div class="s-value">{{ total_value }}</div></div>
  <div class="stat-item"><div class="s-label">礼物数</div><div class="s-value">{{ gift_count }}</div></div>
  {% if danmaku_count >= 0 %}<div class="stat-item"><div class="s-label">弹幕</div><div class="s-value">{{ danmaku_count }}</div></div>{% endif %}
  {% if blind_count > 0 %}
  <div class="stat-item"><div class="s-label">盲盒</div><div class="s-value">{{ blind_count }}个</div></div>
  <div class="stat-item"><div class="s-label">盈亏</div><div class="s-value" style="color:{{ 'rgb(16,185,129)' if blind_profit >= 0 else 'rgb(239,68,68)' }}">{{ '%+d'|format(blind_profit) }}</div></div>
  <div class="stat-item"><div class="s-label">成本</div><div class="s-value" style="font-size:14px;">{{ blind_cost }}</div></div>
  <div class="stat-item"><div class="s-label">产出</div><div class="s-value" style="font-size:14px;">{{ blind_actual }}</div></div>
  {% endif %}
</div>
{% if gift_details %}<div class="divider"></div><div class="section-title">🎀 礼物明细</div>
<div class="gift-grid">
{% for d in gift_details %}
<div class="gift-item">
  {% if d.icon %}<img class="gift-icon" src="{{ d.icon }}" alt="" onerror="this.style.display='none'">{% else %}<div style="width:22px"></div>{% endif %}
  <div class="gift-info">
    <div class="gift-name">{{ d.name }}</div>
    <div class="gift-meta"><span>×{{ d.count }}</span><span class="gift-value">{{ d.value }}</span></div>
  </div>
</div>
{% endfor %}</div>{% endif %}
{% if blind_details %}<div class="divider"></div><div class="section-title">📦 盲盒明细</div>
{% for bd in blind_details %}
<div class="box-header">
  <span class="box-title">{{ bd.box_name }} ×{{ bd.count }}</span>
  <span class="box-profit {{ 'profit-plus' if bd.profit >= 0 else 'profit-minus' }}">{{ '%+d'|format(bd.profit) }}</span>
</div>
{% for item in bd.get('items',[]) %}
<div class="box-item">
  {% if item.icon %}<img class="box-icon" src="{{ item.icon }}" alt="" onerror="this.style.display='none'">{% else %}<div style="width:18px"></div>{% endif %}
  <span class="box-name">{{ item.name }}</span>
  <span class="box-num">×{{ item.count }}</span>
  <span class="box-profit {{ 'profit-plus' if item.profit >= 0 else 'profit-minus' }}">{{ '%+d'|format(item.profit) }}</span>
</div>
{% endfor %}{% endfor %}{% endif %}
<div class="footer">Ayabot 礼物统计 · {{ label }}</div>
</div></body></html>'''


def _get_data_dir() -> Path:
    """获取 AstrBot data 目录路径（插件应在此目录下存储持久化数据）。"""
    data_dir = os.environ.get("ASTRBOT_DATA_DIR", "data")
    return Path(data_dir).resolve()


class AyabotStatsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config
        self.render_mode = str(config.get("render_mode", "text"))

        # 按群配置列表（来自 _conf_schema.json template_list）
        self._group_configs: dict[str, dict] = {}
        self._load_groups_from_config()

        # 绑定数据
        bindings_rel = str(config.get("bindings_file", "ayabot_bindings.json"))
        self.bindings_path = _get_data_dir() / bindings_rel
        self.bindings_path.parent.mkdir(parents=True, exist_ok=True)
        self._bindings: dict[str, int] = {}
        self._load_bindings()

    def _load_groups_from_config(self) -> None:
        """从插件配置加载群配置列表。"""
        raw = self.config.get("groups", [])
        if isinstance(raw, list):
            self._group_configs = {}
            for entry in raw:
                gid = str(entry.get("group_id", "")).strip()
                if gid:
                    self._group_configs[gid] = {
                        "api_url": str(entry.get("api_url", "")),
                        "api_token": str(entry.get("api_token", "")),
                    }
            logger.info(f"已加载 {len(self._group_configs)} 个群的 API 配置")
        else:
            self._group_configs = {}

    def _save_groups_to_config(self) -> None:
        """将群配置列表写回插件配置并持久化。"""
        entries = []
        for gid, cfg in self._group_configs.items():
            entries.append({
                "__template_key": "group_config",
                "group_id": gid,
                "api_url": cfg["api_url"],
                "api_token": cfg["api_token"],
            })
        self.config["groups"] = entries
        self.config.save_config()

    def _load_bindings(self) -> None:
        if self.bindings_path.exists():
            try:
                raw = json.loads(self.bindings_path.read_text(encoding="utf-8"))
                self._bindings = {str(k): int(v) for k, v in raw.items()}
                logger.info(f"已加载 {len(self._bindings)} 条 QQ-UID 绑定记录")
            except Exception as e:
                logger.warning(f"加载绑定数据失败: {e}")
                self._bindings = {}

    def _save_bindings(self) -> None:
        try:
            self.bindings_path.write_text(
                json.dumps(self._bindings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存绑定数据失败: {e}")

    def _get_bili_uid(self, qq_id: str) -> Optional[int]:
        return self._bindings.get(str(qq_id))

    def _set_binding(self, qq_id: str, bili_uid: int) -> None:
        self._bindings[str(qq_id)] = bili_uid
        self._save_bindings()

    def _unset_binding(self, qq_id: str) -> bool:
        key = str(qq_id)
        if key in self._bindings:
            del self._bindings[key]
            self._save_bindings()
            return True
        return False

    # ═══════════════════════════════════════════
    #  按群 API 配置
    # ═══════════════════════════════════════════

    def _get_group_config(self, group_id: str) -> Optional[dict]:
        """获取指定群的 API 配置，找不到返回 None。"""
        return self._group_configs.get(group_id)

    def _set_group_config(self, group_id: str, api_url: str, api_token: str, room_id: str = "") -> None:
        self._group_configs[group_id] = {
            "api_url": api_url,
            "api_token": api_token,
        }
        self._save_groups_to_config()

    # ═══════════════════════════════════════════
    #  API 调用
    # ═══════════════════════════════════════════

    async def _query_user_stats(self, uid: int, period: str, group_id: str = "") -> Optional[dict]:
        """调用 Ayabot API 查询（按群配置）。"""
        cfg = self._get_group_config(group_id) if group_id else None
        if not cfg:
            logger.error(f"群 {group_id} 未配置 API")
            return None

        # api_url 是 WebUI 复制的完整地址（含 /api/external/user_stats?room_id=xxx）
        base_url = cfg["api_url"].rstrip("?&")
        api_token = cfg["api_token"]

        if not base_url or not api_token:
            logger.error(f"群 {group_id} API 配置不完整")
            return None

        separator = "&" if "?" in base_url else "?"
        url = f"{base_url}{separator}uid={uid}&period={period}&token={api_token}"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url)
                if resp.status_code == 401:
                    logger.error("API 密钥认证失败")
                    return None
                if resp.status_code != 200:
                    logger.error(f"API 返回错误: {resp.status_code}")
                    return None
                data = resp.json()
                if not data.get("ok"):
                    logger.error(f"API 返回异常: {data}")
                    return None
                return data
        except httpx.TimeoutException:
            logger.error(f"请求 Ayabot API 超时: {url}")
            return None
        except httpx.RequestError as e:
            logger.error(f"请求 Ayabot API 失败: {e}")
            return None

    @staticmethod
    def _fmt(val: int) -> str:
        """格式化电池数"""
        if val >= 10000:
            return f"{val / 10000:.1f}万"
        elif val >= 1000:
            return f"{val / 1000:.1f}k"
        return str(val)

    def _build_text_reply(self, data: dict, label: str) -> str:
        gift = data.get("gift", {})
        blind = data.get("blindbox", {})
        uname = data.get("uname", f"UID:{data.get('uid', '?')}")
        uid = data.get("uid", "?")
        danmaku_count = data.get("danmaku_count", -1)

        lines = [
            f"📊 {uname} 的{label}礼物数据",
            f"━━━━━━━━━━━━━━━━━━",
            f"UID：{uid}",
        ]

        total_events = gift.get("total_events", 0)
        total_gift_count = gift.get("total_gift_count", 0)
        total_value = gift.get("total_value", 0)

        if total_events > 0:
            lines.append(f"总投喂：{self._fmt(total_value)} 电池")
            if danmaku_count >= 0:
                lines.append(f"弹幕数：{danmaku_count}")
            lines.append(f"礼物数：{total_gift_count}")
        else:
            lines.append("暂无投喂记录")

        # 盲盒摘要
        blind_count = blind.get("count", 0)
        blind_cost = blind.get("cost", 0)
        blind_actual = blind.get("actual", 0)
        blind_profit = blind.get("profit", 0)

        if blind_count > 0:
            profit_str = f"{'' if blind_profit < 0 else '+'}{self._fmt(blind_profit)}"
            lines.append(f"盲盒：{self._fmt(blind_cost)} 电池({profit_str}) 共{blind_count}个 盈亏：成本 {self._fmt(blind_cost)}/产出 {self._fmt(blind_actual)}")
        else:
            lines.append("盲盒：无")

        # 礼物详情
        lines.append(f"")
        lines.append(f"礼物详情：")
        gift_details = gift.get("details", [])
        if gift_details:
            for d in gift_details:
                lines.append(f"  {d['name']} x {d['count']} {self._fmt(d['value'])} 电池")
        else:
            lines.append(f"  （无）")

        # 盲盒详情
        blind_details = blind.get("details", [])
        if blind_details:
            for bd in blind_details:
                box_profit_str = f"{'' if bd['profit'] < 0 else '+'}{self._fmt(bd['profit'])}"
                lines.append(f"")
                lines.append(f"{bd['box_name']} x {bd['count']} {box_profit_str}：")
                for item in bd.get("items", []):
                    item_profit = f"{'' if item['profit'] < 0 else '+'}{self._fmt(item['profit'])}"
                    lines.append(f"  {item['name']} x {item['count']} {self._fmt(item['cost'])} 电池({item_profit})")

        return "\n".join(lines)


    # ═══════════════════════════════════════════
    #  指令：绑定 UID（全局）
    # ═══════════════════════════════════════════

    @filter.command("绑定")
    async def bind_uid(self, event: AstrMessageEvent, bili_uid: int):
        """绑定自己的 QQ 号到 B站 UID，例如：/绑定 12345678。绑定后可在任何已配置的群中查询。"""
        qq_id = event.get_sender_id()
        if not qq_id:
            yield event.plain_result("无法获取发送者信息，请私聊机器人绑定。")
            return

        self._set_binding(qq_id, bili_uid)
        uname = await self._fetch_uname(bili_uid)
        name_str = f"（{uname}）" if uname else ""
        yield event.plain_result(
            f"✅ 绑定成功！\n"
            f"QQ: {qq_id}\n"
            f"B站 UID: {bili_uid}{name_str}\n"
            f"现在可以在已配置的群中使用 /礼物查询 指令查看记录了。"
        )

    @filter.command("解绑")
    async def unbind_uid(self, event: AstrMessageEvent):
        """解除自己的 QQ 号与 B站 UID 的绑定。"""
        qq_id = event.get_sender_id()
        if not qq_id:
            yield event.plain_result("无法获取发送者信息。")
            return

        if self._unset_binding(qq_id):
            yield event.plain_result("✅ 已解除绑定。")
        else:
            yield event.plain_result("❌ 你尚未绑定任何 UID。")

    # ═══════════════════════════════════════════
    #  指令：礼物查询（按群使用对应 API）
    # ═══════════════════════════════════════════

    @filter.command("礼物查询")
    async def query_gift(self, event: AstrMessageEvent):
        """查询礼物/盲盒统计。后跟 today/week/month/all 指定范围，默认今天。根据 render_mode 配置决定发送方式。"""
        text = event.message_str.strip()
        parts = text.split()
        period_map = {
            "today": "today", "本日": "today", "今天": "today",
            "week": "week", "本周": "week",
            "month": "month", "本月": "month",
            "all": "all", "全部": "all", "记录以来": "all",
        }
        if len(parts) >= 2:
            p = parts[1].lower()
            period = period_map.get(p, "today")
        else:
            period = "today"
        label_map = {"today": "本日", "week": "本周", "month": "本月", "all": "全部记录"}
        label = label_map.get(period, "本日")

        # 获取数据
        data, err = await self._query_data(event, period, label)
        if err:
            yield event.plain_result(err)
            return

        # 根据 render_mode 发送
        mode = self.render_mode
        if mode == "image":
            # 仅图片
            try:
                url = await self._render_image(data, label)
                yield event.image_result(url)
            except Exception as e:
                logger.warning(f"图片渲染失败，回退到文字: {e}")
                yield event.plain_result(self._build_text_reply(data, label))
        elif mode == "both":
            # 文字 + 图片
            yield event.plain_result(self._build_text_reply(data, label))
            try:
                url = await self._render_image(data, label)
                yield event.image_result(url)
            except Exception as e:
                logger.warning(f"图片渲染失败: {e}")
        else:
            # 纯文字
            yield event.plain_result(self._build_text_reply(data, label))

    async def _query_data(self, event: AstrMessageEvent, period: str, label: str) -> tuple[Optional[dict], str]:
        """查询数据，返回 (data, error_msg)。data 为 None 时 error_msg 有值。"""
        qq_id = event.get_sender_id()
        group_id = event.get_group_id() if hasattr(event, "get_group_id") else ""

        if not qq_id:
            return None, "无法获取发送者信息。"

        bili_uid = self._get_bili_uid(qq_id)
        if bili_uid is None:
            return None, "❌ 你尚未绑定 B站 UID。\n请先使用 /绑定 <你的B站UID> 进行绑定。"

        data = await self._query_user_stats(bili_uid, period, group_id)
        if data is None:
            return None, (
                "❌ 查询失败。\n"
                "可能原因：该群未配置 API、API 配置错误或 Ayabot 服务未运行。\n"
                "请联系群管理员使用 /设置API 或前往 WebUI 插件配置页添加本群配置。"
            )

        return data, ""

    def _build_image_data(self, data: dict, label: str) -> dict:
        """构建图片渲染用的数据。"""
        gift = data.get("gift", {})
        blind = data.get("blindbox", {})

        total_value = gift.get("total_value", 0)
        gift_details = []
        for d in gift.get("details", []):
            gift_details.append({
                "name": d["name"],
                "count": d["count"],
                "value": self._fmt(d.get("value", 0)),
                "icon": d.get("icon", ""),
            })

        blind_details = []
        for bd in blind.get("details", []):
            items = []
            for item in bd.get("items", []):
                items.append({
                    "name": item["name"],
                    "count": item["count"],
                    "profit": item.get("profit", 0),
                    "icon": item.get("icon", ""),
                })
            blind_details.append({
                "box_name": bd["box_name"],
                "count": bd["count"],
                "profit": bd.get("profit", 0),
                "items": items,
            })

        return {
            "uname": data.get("uname", f"UID:{data.get('uid', '?')}"),
            "uid": str(data.get("uid", "?")),
            "avatar": data.get("avatar", ""),
            "label": label,
            "total_value": self._fmt(total_value),
            "danmaku_count": data.get("danmaku_count", -1),
            "gift_count": str(gift.get("total_gift_count", 0)),
            "blind_count": blind.get("count", 0),
            "blind_cost": self._fmt(blind.get("cost", 0)),
            "blind_actual": self._fmt(blind.get("actual", 0)),
            "blind_profit": blind.get("profit", 0),
            "gift_details": gift_details,
            "blind_details": blind_details,
        }

    async def _render_image(self, data: dict, label: str) -> str:
        """渲染图片，根据 t2i_mode 选择本地或网络服务。"""
        t2i_mode = str(self.config.get("t2i_mode", "network"))
        img_data = self._build_image_data(data, label)
        from jinja2 import Template
        html = Template(GIFT_CARD_HTML).render(**img_data)

        if t2i_mode == "local":
            # 本地 T2I：直接 POST 到本地服务
            local_url = str(self.config.get("t2i_local_url", "http://t2i-local:6199/text2img"))
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(local_url, data={"html": html})
                resp.raise_for_status()
                img_bytes = resp.content
            # 保存到临时文件
            cache_dir = _get_data_dir() / "ayabot_stats_cache"
            cache_dir.mkdir(parents=True, exist_ok=True)
            ts = int(time.time())
            fp = cache_dir / f"gift_{data.get('uid','?')}_{ts}.png"
            fp.write_bytes(img_bytes)
            return str(fp)
        else:
            # 网络 T2I：使用 AstrBot 内置 html_render
            url = await asyncio.wait_for(
                self.html_render(GIFT_CARD_HTML, img_data), timeout=15
            )
            return url

    # ═══════════════════════════════════════════
    #  指令：群 API 配置管理（仅管理员）
    # ═══════════════════════════════════════════

    @filter.command("设置API")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def set_group_api(self, event: AstrMessageEvent, api_url: str, api_token: str, room_id: str = ""):
        """设置当前群的 Ayabot API 配置。需要群管理员权限。
        用法：/设置API <API地址> <API密钥> [房间号]
        例如：/设置API http://192.168.1.100:19810 xxxxxxxx 1992696442"""
        group_id = event.get_group_id() if hasattr(event, "get_group_id") else ""
        if not group_id:
            yield event.plain_result("❌ 请在群聊中使用此命令。")
            return

        api_url = api_url.rstrip("/")
        self._set_group_config(group_id, api_url, api_token, room_id)
        yield event.plain_result(
            f"✅ 当前群 API 配置已保存！\n"
            f"API 地址: {api_url}\n"
            f"密钥: {api_token[:6]}...{api_token[-4:]}\n"
            f"也可在 WebUI 插件配置页的「群配置」表格中管理所有群。\n"
            f"配置方法：从 Ayabot WebUI → 数据管理 → 复制「API 地址」和「密钥」填入即可。"
        )

    @filter.command("查看API")
    async def show_group_api(self, event: AstrMessageEvent):
        """查看当前群的 API 配置状态（密钥脱敏显示）。"""
        group_id = event.get_group_id() if hasattr(event, "get_group_id") else ""

        if group_id:
            cfg = self._get_group_config(group_id)
            lines = [f"📡 当前群 API 配置", f"━━━━━━━━━━━━━━━━━━"]
            if cfg:
                lines.append(f"状态: ✅ 已配置")
                lines.append(f"地址: {cfg['api_url'] or '❌ 未设置'}")
                t = cfg["api_token"]
                masked = t[:6] + "*" * (len(t) - 10) + t[-4:] if len(t) > 12 else "****"
                lines.append(f"密钥: {masked if t else '❌ 未设置'}")
            else:
                lines.append(f"状态: ❌ 未配置")
                lines.append(f"")
                lines.append(f"管理员可输入 /设置API <地址> <密钥> [房间号] 配置")
                lines.append(f"或前往 WebUI 插件配置页添加本群配置。")
            yield event.plain_result("\n".join(lines))
        else:
            yield event.plain_result("📡 请在群聊中使用此命令查看当前群配置。")

    # ═══════════════════════════════════════════
    #  辅助：获取 B站 用户名
    # ═══════════════════════════════════════════

    async def _fetch_uname(self, uid: int) -> Optional[str]:
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                resp = await client.get(
                    f"https://api.bilibili.com/x/web-interface/card?mid={uid}",
                    headers={
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                        "Referer": "https://www.bilibili.com/",
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        return data.get("data", {}).get("card", {}).get("name")
        except Exception:
            pass
        return None

    async def terminate(self) -> None:
        logger.info("Ayabot 礼物统计插件已停用")
