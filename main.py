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

import json
import os
from pathlib import Path
from typing import Optional

import httpx

from astrbot.api import AstrBotConfig, logger
from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star




def _get_data_dir() -> Path:
    """获取 AstrBot data 目录路径（插件应在此目录下存储持久化数据）。"""
    data_dir = os.environ.get("ASTRBOT_DATA_DIR", "data")
    return Path(data_dir).resolve()


class AyabotStatsPlugin(Star):
    def __init__(self, context: Context, config: AstrBotConfig) -> None:
        super().__init__(context)
        self.config = config

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
                        "api_url": str(entry.get("api_url", "")).rstrip("/"),
                        "api_token": str(entry.get("api_token", "")),
                        "room_id": str(entry.get("room_id", "")),
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
                "room_id": cfg["room_id"],
            })
        self.config["groups"] = entries
        self.config.save_config()
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

    def _set_group_config(self, group_id: str, api_url: str, api_token: str, room_id: str) -> None:
        self._group_configs[group_id] = {
            "api_url": api_url.rstrip("/"),
            "api_token": api_token,
            "room_id": room_id,
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

        api_url = cfg["api_url"]
        api_token = cfg["api_token"]
        room_id = cfg["room_id"]

        if not api_url:
            logger.error("api_url 未配置")
            return None
        if not api_token:
            logger.error("api_token 未配置")
            return None

        params = {"uid": uid, "period": period, "token": api_token}
        if room_id:
            params["room_id"] = room_id

        url = f"{api_url}/api/external/user_stats"

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(url, params=params)
                if resp.status_code == 401:
                    logger.error("API 密钥认证失败，请检查配置")
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
        """查询并返回结果文本（根据消息来源群使用对应 API 配置）。"""
        qq_id = event.get_sender_id()
        group_id = event.get_group_id() if hasattr(event, "get_group_id") else ""

        if not qq_id:
            return "无法获取发送者信息。"

        bili_uid = self._get_bili_uid(qq_id)
        if bili_uid is None:
            return "❌ 你尚未绑定 B站 UID。\n请先使用 /绑定 <你的B站UID> 进行绑定。"

        data = await self._query_user_stats(bili_uid, period, group_id)
        if data is None:
            return (
                "❌ 查询失败。\n"
                "可能原因：该群未配置 API、API 配置错误或 Ayabot 服务未运行。\n"
                "请联系群管理员使用 /设置API 或前往 WebUI 插件配置页添加本群配置。"
            )

        return self._build_reply(data, label)

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
        """查询礼物/盲盒统计。后跟 today/week/month/all 指定范围，默认今天。根据当前群使用的 API 配置查询。"""
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

    # ═══════════════════════════════════════════
    #  指令：群 API 配置管理（仅管理员）
    # ═══════════════════════════════════════════

    @filter.command("设置API")
    @filter.permission_type(filter.PermissionType.ADMIN)
    async def set_group_api(self, event: AstrMessageEvent, api_url: str, api_token: str, room_id: str = "") -> None:
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
            f"房间号: {room_id or '(使用默认)'}\n"
            f"也可在 WebUI 插件配置页的「群配置」表格中管理所有群。"
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
                lines.append(f"房间: {cfg['room_id'] or '(空)'}")
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
