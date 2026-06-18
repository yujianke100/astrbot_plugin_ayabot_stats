"""
Ayabot 礼物统计查询插件
━━━━━━━━━━━━━━━━━━━━
配合 Ayabot B站直播间机器人使用，让 QQ 群成员可以：
  - 绑定自己的 B站 UID
  - 查询本日/本周/本月/全部时间的礼物投喂、盲盒数量与盈亏
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register


def _get_data_dir() -> Path:
    """获取 AstrBot data 目录路径（插件应在此目录下存储持久化数据）。"""
    data_dir = os.environ.get("ASTRBOT_DATA_DIR", "data")
    return Path(data_dir).resolve()


@register("astrbot_plugin_ayabot_stats", "Ayabot", "Ayabot 直播间礼物统计查询插件", "1.0.0")
class AyabotStatsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

        # 读取配置
        self.api_url = str(config.get("api_url", "")).rstrip("/")
        self.api_token = str(config.get("api_token", ""))
        self.room_id = str(config.get("room_id", ""))
        bindings_rel = str(config.get("bindings_file", "ayabot_bindings.json"))

        # 绑定数据存储路径
        self.bindings_path = _get_data_dir() / bindings_rel
        self.bindings_path.parent.mkdir(parents=True, exist_ok=True)
        self._bindings: dict[str, int] = {}  # qq_id -> bili_uid
        self._load_bindings()

    # ── 绑定数据持久化 ──

    def _load_bindings(self) -> None:
        """从 JSON 文件加载 QQ-UID 绑定关系。"""
        if self.bindings_path.exists():
            try:
                raw = json.loads(self.bindings_path.read_text(encoding="utf-8"))
                self._bindings = {str(k): int(v) for k, v in raw.items()}
                logger.info(f"已加载 {len(self._bindings)} 条 QQ-UID 绑定记录")
            except Exception as e:
                logger.warning(f"加载绑定数据失败: {e}")
                self._bindings = {}

    def _save_bindings(self) -> None:
        """将 QQ-UID 绑定关系保存到 JSON 文件。"""
        try:
            self.bindings_path.write_text(
                json.dumps(self._bindings, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error(f"保存绑定数据失败: {e}")

    def _get_bili_uid(self, qq_id: str) -> Optional[int]:
        """根据 QQ 号查询绑定的 B站 UID。"""
        return self._bindings.get(str(qq_id))

    def _set_binding(self, qq_id: str, bili_uid: int) -> None:
        """绑定 QQ 号与 B站 UID。"""
        self._bindings[str(qq_id)] = bili_uid
        self._save_bindings()

    def _unset_binding(self, qq_id: str) -> bool:
        """解绑 QQ 号。"""
        key = str(qq_id)
        if key in self._bindings:
            del self._bindings[key]
            self._save_bindings()
            return True
        return False

    # ── API 调用 ──

    async def _query_user_stats(self, uid: int, period: str) -> Optional[dict]:
        """调用 Ayabot API 查询用户统计。"""
        if not self.api_url:
            logger.error("api_url 未配置")
            return None
        if not self.api_token:
            logger.error("api_token 未配置")
            return None

        params = {"uid": uid, "period": period, "token": self.api_token}
        if self.room_id:
            params["room_id"] = self.room_id

        url = f"{self.api_url}/api/external/user_stats"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 401:
                    logger.error("API Token 认证失败，请检查 api_token 配置")
                    return None
                if resp.status_code != 200:
                    logger.error(f"API 返回错误: {resp.status_code} {resp.text}")
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

    # ── 辅助：构建回复消息 ──

    def _build_reply(self, data: dict, label: str) -> str:
        """根据 API 返回数据构建回复文本。"""
        gift = data.get("gift", {})
        blind = data.get("blindbox", {})
        uname = data.get("uname", f"UID:{data.get('uid', '?')}")

        lines = [
            f"📊 {uname} 的{label}礼物数据",
            f"━━━━━━━━━━━━━━━━━━",
        ]

        total_events = gift.get("total_events", 0)
        total_gift_count = gift.get("total_gift_count", 0)
        total_value = gift.get("total_value_yuan", 0)
        if total_events > 0:
            lines.append(f"🎁 礼物投喂: {total_gift_count} 个（{total_events} 次）")
            lines.append(f"💰 总价值: {total_value} 元")
        else:
            lines.append("🎁 无送礼记录")

        blind_count = blind.get("count", 0)
        blind_cost = blind.get("cost_yuan", 0)
        blind_actual = blind.get("actual_yuan", 0)
        blind_profit = blind.get("profit_yuan", 0)

        if blind_count > 0:
            lines.append(f"━━━━━━━━━━━━━━━━━━")
            lines.append(f"📦 盲盒统计:")
            lines.append(f"  数量: {blind_count} 个")
            lines.append(f"  花费: {blind_cost} 元")
            lines.append(f"  价值: {blind_actual} 元")
            if blind_profit >= 0:
                lines.append(f"  盈亏: +{blind_profit} 元 ✅")
            else:
                lines.append(f"  盈亏: {blind_profit} 元 ❌")
        else:
            lines.append(f"━━━━━━━━━━━━━━━━━━")
            lines.append("📦 无盲盒记录")

        return "\n".join(lines)

    async def _query_and_reply(self, event: AstrMessageEvent, period: str, label: str) -> str:
        """查询并返回结果文本。"""
        qq_id = event.get_sender_id()
        if not qq_id:
            return "无法获取发送者信息。"

        bili_uid = self._get_bili_uid(qq_id)
        if bili_uid is None:
            return "❌ 你尚未绑定 B站 UID。\n请先使用 /绑定 <你的B站UID> 进行绑定。"

        if not self.api_url:
            return "❌ 插件未配置 Ayabot 服务地址（api_url），请联系管理员。"
        if not self.api_token:
            return "❌ 插件未配置 API Token（api_token），请联系管理员。"

        data = await self._query_user_stats(bili_uid, period)
        if data is None:
            return (
                "❌ 查询失败，请稍后重试。\n"
                "可能原因：Ayabot 服务未运行、API 配置错误或网络不通。"
            )

        return self._build_reply(data, label)

    # ── 指令：绑定 UID ──

    @filter.command("绑定")
    async def bind_uid(self, event: AstrMessageEvent, bili_uid: int) -> None:
        """绑定自己的 QQ 号到 B站 UID，例如：/绑定 12345678"""
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
            f"现在可以使用 /礼物查询 指令查看记录了。"
        )

    @filter.command("解绑")
    async def unbind_uid(self, event: AstrMessageEvent) -> None:
        """解除自己的 QQ 号与 B站 UID 的绑定。"""
        qq_id = event.get_sender_id()
        if not qq_id:
            yield event.plain_result("无法获取发送者信息。")
            return

        if self._unset_binding(qq_id):
            yield event.plain_result("✅ 已解除绑定。")
        else:
            yield event.plain_result("❌ 你尚未绑定任何 UID。")

    # ── 指令：礼物查询（手动解析参数，兼容 "/礼物查询 today" 和 "/礼物查询"）──

    @filter.command("礼物查询")
    async def query_gift(self, event: AstrMessageEvent) -> None:
        """查询礼物/盲盒统计。后跟 today/week/month/all 指定范围，默认今天。"""
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

        result = await self._query_and_reply(event, period, label_map.get(period, "本日"))
        yield event.plain_result(result)

    # ── 辅助：获取 B站 用户名 ──

    async def _fetch_uname(self, uid: int) -> Optional[str]:
        """通过 B站 API 获取用户昵称。"""
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
        """插件卸载/停用时的清理工作。"""
        logger.info("Ayabot 礼物统计插件已停用")
