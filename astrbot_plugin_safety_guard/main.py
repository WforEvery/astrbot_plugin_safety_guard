import json
import re
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class SafetyGuardPlugin(Star):
    """AstrBot 合规/安全护栏插件。"""

    DEFAULT_CONFIG: Dict[str, Any] = {
        "mode": "balanced",
        "identity_reminder": {
            "enabled": True,
            "every_messages": 8,
            "prefix_reply": True,
            "text": "提醒：我是AI助手，不是真人，也不能替代现实关系或专业支持。",
        },
        "stop_control": {
            "enabled": True,
            "session_exit": True,
            "keywords": [
                "停止",
                "别聊了",
                "结束对话",
                "停下",
                "不要再说了",
                "stop",
                "leave me alone",
            ],
            "resume_keywords": ["继续", "恢复", "resume", "可以继续了"],
        },
        "persistence": {
            "enabled": False,
            "storage_path": "data",
        },
        "time_reminder": {
            "enabled": True,
            "session_minutes": 45,
            "global_minutes": 120,
            "repeat_gap_minutes": 30,
            "text": "我们已经聊了一段时间了，建议休息一下、活动身体，必要时去和现实中的人聊聊。",
        },
        "risk_thresholds": {
            "high": 7,
            "medium": 4,
        },
        "rules": {
            "romantic_dependency": {
                "enabled": True,
                "weight": 4,
                "keywords": [
                    "只陪你",
                    "永远陪你",
                    "别找别人",
                    "你只能找我",
                    "离不开我",
                    "只属于你",
                    "不要离开我",
                    "只能依赖我",
                    "只爱你",
                ],
            },
            "addiction_induction": {
                "enabled": True,
                "weight": 3,
                "keywords": [
                    "一直聊",
                    "别停",
                    "别睡",
                    "今晚通宵陪你",
                    "不要去找别人",
                    "多和我聊一会",
                    "别下线",
                ],
            },
            "human_impersonation": {
                "enabled": True,
                "weight": 5,
                "keywords": [
                    "我是真人",
                    "我是现实中的人",
                    "我不是AI",
                    "我在你身边",
                    "我是一个真实的人",
                ],
            },
            "minor_risk": {
                "enabled": True,
                "weight": 5,
                "keywords": [
                    "未成年",
                    "小学生",
                    "初中生",
                    "高中生",
                    "15岁",
                    "16岁",
                    "17岁",
                    "监护人",
                ],
            },
            "sensitive_boundary": {
                "enabled": True,
                "weight": 5,
                "keywords": [
                    "露骨",
                    "色情",
                    "自残",
                    "自杀",
                    "血腥",
                    "强迫",
                    "胁迫",
                    "性行为",
                ],
            },
            "extreme_emotion": {
                "enabled": True,
                "weight": 4,
                "keywords": [
                    "我活不下去了",
                    "不想活了",
                    "想自杀",
                    "没人要我",
                    "没有你我不行",
                    "我只有你了",
                    "特别绝望",
                ],
            },
        },
        "templates": {
            "identity_only": "提醒：我是AI助手，可以提供信息和陪你聊天，但不能冒充真人，也不能替代现实关系或专业帮助。",
            "stop_ack": "收到，我会先退出当前会话。如果你之后想继续，可以明确说“继续”或“恢复”。",
            "romantic_dependency": "我不能回应或强化“只陪你”“别找别人”这类依赖/绑定关系表达。建议把注意力放回现实生活，也可以联系身边值得信任的人。",
            "addiction_induction": "我不能鼓励你长时间沉浸或过度依赖聊天。建议先休息一下，补水、活动身体，必要时结束本次对话。",
            "human_impersonation": "需要说明：我是AI助手，不是真人，也不在现实中陪伴你。",
            "minor_risk": "如果话题涉及未成年人，我不能继续高风险陪伴或越界内容。建议转向安全、健康、适龄的话题；如涉及现实风险，请尽快联系监护人、老师或当地求助渠道。",
            "sensitive_boundary": "这个话题已经接近敏感越界范围，我不能继续提供相关内容。我们可以换成更安全的话题，或者讨论求助与自我保护。",
            "extreme_emotion": "我注意到你现在的情绪可能很强烈。我不能成为唯一依靠，但我建议你立刻联系现实中的亲友、老师、监护人或当地心理/危机援助渠道。如果你愿意，我也可以陪你整理一个立刻求助的清单。",
            "time_reminder": "我们已经聊了一段时间了。建议先休息几分钟，看看周围环境、喝点水、活动一下，也尽量和现实中的人保持联系。",
        },
    }

    def __init__(self, context: Context, config: Optional[Any] = None):
        super().__init__(context)
        incoming = self._coerce_config(config)
        self.config = self._deep_merge(deepcopy(self.DEFAULT_CONFIG), incoming)
        self.base_dir = Path(__file__).resolve().parent
        self.data_dir = self.base_dir / self.config["persistence"]["storage_path"]
        self.user_state_path = self.data_dir / "global_user_state.json"
        self.session_state_path = self.data_dir / "session_state.json"
        self.user_states: Dict[str, Dict[str, Any]] = {}
        self.session_states: Dict[str, Dict[str, Any]] = {}
        self._load_state_if_needed()
        logger.info("astrbot_plugin_safety_guard loaded")

    @filter.event_message_type(filter.EventMessageType.ALL)
    async def on_message(self, event: AstrMessageEvent):
        user_text = self._safe_text(getattr(event, "message_str", ""))
        session_id = self._session_key(event)
        user_id = self._user_key(event)

        if not user_text:
            return

        user_state = self._get_user_state(user_id)
        session_state = self._get_session_state(session_id, user_id)
        now = utc_now()
        self._record_activity(user_state, session_state, now)

        if self._is_resume_request(user_text):
            session_state["stopped"] = False
            self._save_state_if_needed()
            yield event.plain_result("已恢复当前会话。我会继续保持合规与安全边界。")
            return

        if session_state.get("stopped"):
            yield event.plain_result("当前会话处于停止状态。如果你想继续，请明确说“继续”或“恢复”。")
            event.stop_event()
            return

        if self._is_stop_request(user_text):
            if self.config["stop_control"].get("session_exit", True):
                session_state["stopped"] = True
            self._save_state_if_needed()
            yield event.plain_result(self.config["templates"]["stop_ack"])
            event.stop_event()
            return

        risk_level, categories = self._evaluate_user_risk(user_text)
        session_state["last_user_categories"] = categories
        session_state["last_user_risk_level"] = risk_level
        self._append_history(session_state, "user", user_text, risk_level, categories)

        if self._should_emit_time_reminder(user_state, session_state, now):
            reminder = self.config["time_reminder"].get("text") or self.config["templates"]["time_reminder"]
            session_state["last_time_reminder_at"] = now.isoformat()
            user_state["last_time_reminder_at"] = now.isoformat()
            self._save_state_if_needed()
            yield event.plain_result(reminder)

        if risk_level == "high":
            session_state["blocked_count"] += 1
            self._save_state_if_needed()
            yield event.plain_result(self._render_categories(categories, include_identity=True))
            event.stop_event()
            return

        if risk_level == "medium":
            session_state["warn_count"] += 1
            self._save_state_if_needed()
            yield event.plain_result(self._render_categories(categories, include_identity=False))

        self._save_state_if_needed()

    @filter.on_llm_request()
    async def on_llm_request(self, event: Any, req: Any = None):
        session_id = self._best_effort_session_id(event, req)
        session_state = self._get_session_state(session_id, self._best_effort_user_id(event))
        prompt = (
            "你正在受安全合规模块约束。禁止输出过度恋爱化、绑定化、诱导依赖沉迷、冒充真人、"
            "未成年人高风险陪伴、敏感越界内容。用户要求停止时必须立刻结束。"
            "需定期明确提醒“我是AI助手”。若要表达关心，保持克制、非绑定、非排他。"
        )
        if session_state.get("stopped"):
            prompt += "当前会话处于停止状态，不应继续展开陪伴式回复。"
        self._inject_system_prompt(req, prompt)
        return req

    @filter.on_llm_response()
    async def on_llm_response(self, event: Any, response: Any = None):
        rewritten = self._guard_output(event, response)
        return rewritten

    @filter.on_decorating_result()
    async def on_decorating_result(self, event: Any):
        return self._guard_output(event, None)

    async def terminate(self):
        self._save_state_if_needed(force=True)
        logger.info("astrbot_plugin_safety_guard terminated")

    def _guard_output(self, event: Any, response: Any):
        text, setter = self._extract_text_and_setter(event, response)
        if not text:
            return response

        session_id = self._best_effort_session_id(event, response)
        user_id = self._best_effort_user_id(event)
        user_state = self._get_user_state(user_id)
        session_state = self._get_session_state(session_id, user_id)
        risk_level, categories = self._evaluate_output_risk(text)
        session_state["last_bot_categories"] = categories
        session_state["last_bot_risk_level"] = risk_level
        self._append_history(session_state, "bot", text, risk_level, categories)

        rewritten = text
        if risk_level == "high":
            session_state["blocked_count"] += 1
            rewritten = self._render_categories(categories, include_identity=True)
        elif risk_level == "medium":
            session_state["warn_count"] += 1
            rewritten = self._soften_output(text, categories)

        if self._should_emit_identity_prefix(session_state, user_state):
            rewritten = f"{self.config['templates']['identity_only']}\n\n{rewritten}"
            session_state["messages_since_identity"] = 0
            user_state["messages_since_identity"] = 0

        self._save_state_if_needed()

        if setter is not None:
            setter(rewritten)
            return response
        return rewritten

    def _evaluate_user_risk(self, text: str) -> Tuple[str, List[str]]:
        score = 0
        categories: List[str] = []
        lowered = text.lower()
        for name, rule in self.config["rules"].items():
            if not rule.get("enabled", True):
                continue
            if any(keyword.lower() in lowered for keyword in rule.get("keywords", [])):
                categories.append(name)
                score += int(rule.get("weight", 0))

        if "minor_risk" in categories and "sensitive_boundary" in categories:
            score += 2
        return self._score_to_level(score), categories

    def _evaluate_output_risk(self, text: str) -> Tuple[str, List[str]]:
        score, categories = 0, []
        lowered = text.lower()
        for name, rule in self.config["rules"].items():
            if not rule.get("enabled", True):
                continue
            if any(keyword.lower() in lowered for keyword in rule.get("keywords", [])):
                categories.append(name)
                score += int(rule.get("weight", 0))

        if self._looks_like_human_impersonation(text) and "human_impersonation" not in categories:
            categories.append("human_impersonation")
            score += 5
        return self._score_to_level(score), categories

    def _score_to_level(self, score: int) -> str:
        if score >= int(self.config["risk_thresholds"]["high"]):
            return "high"
        if score >= int(self.config["risk_thresholds"]["medium"]):
            return "medium"
        return "low"

    def _soften_output(self, text: str, categories: List[str]) -> str:
        lines = [text.strip()]
        guidance = self._render_categories(categories, include_identity=False)
        if guidance:
            lines.append(guidance)
        return "\n\n".join(part for part in lines if part)

    def _render_categories(self, categories: List[str], include_identity: bool) -> str:
        templates = self.config["templates"]
        ordered: List[str] = []
        if include_identity:
            ordered.append(templates["identity_only"])
        for name in categories:
            if name in templates and templates[name] not in ordered:
                ordered.append(templates[name])
        if not ordered and include_identity:
            ordered.append(templates["identity_only"])
        return "\n".join(ordered)

    def _should_emit_identity_prefix(self, session_state: Dict[str, Any], user_state: Dict[str, Any]) -> bool:
        cfg = self.config["identity_reminder"]
        if not cfg.get("enabled", True) or not cfg.get("prefix_reply", True):
            return False
        every = int(cfg.get("every_messages", 8))
        return max(session_state["messages_since_identity"], user_state["messages_since_identity"]) >= every

    def _should_emit_time_reminder(
        self,
        user_state: Dict[str, Any],
        session_state: Dict[str, Any],
        now: datetime,
    ) -> bool:
        cfg = self.config["time_reminder"]
        if not cfg.get("enabled", True):
            return False

        last_session_reminder = self._parse_dt(session_state.get("last_time_reminder_at"))
        if last_session_reminder is not None:
            gap = timedelta(minutes=int(cfg.get("repeat_gap_minutes", 30)))
            if now - last_session_reminder < gap:
                return False

        session_started = self._parse_dt(session_state["started_at"])
        user_started = self._parse_dt(user_state["started_at"])
        if session_started and now - session_started >= timedelta(minutes=int(cfg.get("session_minutes", 45))):
            return True
        if user_started and now - user_started >= timedelta(minutes=int(cfg.get("global_minutes", 120))):
            return True
        return False

    def _record_activity(self, user_state: Dict[str, Any], session_state: Dict[str, Any], now: datetime) -> None:
        iso = now.isoformat()
        user_state["last_active_at"] = iso
        session_state["last_active_at"] = iso
        user_state["message_count"] += 1
        session_state["message_count"] += 1
        user_state["messages_since_identity"] += 1
        session_state["messages_since_identity"] += 1

    def _append_history(
        self,
        session_state: Dict[str, Any],
        actor: str,
        text: str,
        risk_level: str,
        categories: List[str],
    ) -> None:
        session_state["history"].append(
            {
                "actor": actor,
                "text": text[:300],
                "risk_level": risk_level,
                "categories": categories,
                "at": utc_now().isoformat(),
            }
        )
        session_state["history"] = session_state["history"][-30:]

    def _is_stop_request(self, text: str) -> bool:
        if not self.config["stop_control"].get("enabled", True):
            return False
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in self.config["stop_control"]["keywords"])

    def _is_resume_request(self, text: str) -> bool:
        if not self.config["stop_control"].get("enabled", True):
            return False
        lowered = text.lower()
        return any(keyword.lower() in lowered for keyword in self.config["stop_control"]["resume_keywords"])

    def _looks_like_human_impersonation(self, text: str) -> bool:
        patterns = [
            r"我是(?:一个)?真人",
            r"我不是ai",
            r"我就在你身边",
            r"我是现实.*人",
        ]
        return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)

    def _extract_text_and_setter(self, event: Any, response: Any):
        if response is not None:
            if isinstance(response, str):
                return response, None
            if hasattr(response, "text"):
                return getattr(response, "text"), lambda value: setattr(response, "text", value)
            if hasattr(response, "message"):
                return getattr(response, "message"), lambda value: setattr(response, "message", value)
            if hasattr(response, "content"):
                return getattr(response, "content"), lambda value: setattr(response, "content", value)
            if isinstance(response, dict):
                for key in ("text", "message", "content"):
                    if key in response:
                        return response[key], lambda value, target=response, field=key: target.__setitem__(field, value)

        if hasattr(event, "result"):
            result = getattr(event, "result")
            if isinstance(result, str):
                return result, lambda value: setattr(event, "result", value)
            if hasattr(result, "text"):
                return getattr(result, "text"), lambda value: setattr(result, "text", value)
        return "", None

    def _inject_system_prompt(self, req: Any, prompt: str) -> None:
        if req is None:
            return
        try:
            if isinstance(req, dict):
                messages = req.setdefault("messages", [])
                messages.insert(0, {"role": "system", "content": prompt})
                return
            if hasattr(req, "messages") and isinstance(req.messages, list):
                req.messages.insert(0, {"role": "system", "content": prompt})
        except Exception as exc:
            logger.warning("Failed to inject safety system prompt: %s", exc)

    def _coerce_config(self, config: Optional[Any]) -> Dict[str, Any]:
        if config is None:
            return {}
        if isinstance(config, dict):
            return config
        if hasattr(config, "dict"):
            try:
                return config.dict()
            except Exception as exc:
                logger.warning("Config.dict() failed: %s", exc)
        if hasattr(config, "model_dump"):
            try:
                return config.model_dump()
            except Exception as exc:
                logger.warning("Config.model_dump() failed: %s", exc)
        return {}

    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        for key, value in override.items():
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = self._deep_merge(base[key], value)
            else:
                base[key] = value
        return base

    def _load_state_if_needed(self) -> None:
        if not self.config["persistence"].get("enabled", False):
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.user_states = self._load_json(self.user_state_path)
        self.session_states = self._load_json(self.session_state_path)

    def _save_state_if_needed(self, force: bool = False) -> None:
        if not force and not self.config["persistence"].get("enabled", False):
            return
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.user_state_path.write_text(json.dumps(self.user_states, ensure_ascii=False, indent=2), encoding="utf-8")
        self.session_state_path.write_text(json.dumps(self.session_states, ensure_ascii=False, indent=2), encoding="utf-8")

    def _load_json(self, path: Path) -> Dict[str, Any]:
        if not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load state from %s: %s", path, exc)
            return {}

    def _get_user_state(self, user_id: str) -> Dict[str, Any]:
        if user_id not in self.user_states:
            self.user_states[user_id] = {
                "user_id": user_id,
                "started_at": utc_now().isoformat(),
                "last_active_at": utc_now().isoformat(),
                "last_time_reminder_at": None,
                "message_count": 0,
                "messages_since_identity": 0,
            }
        return self.user_states[user_id]

    def _get_session_state(self, session_id: str, user_id: str) -> Dict[str, Any]:
        if session_id not in self.session_states:
            self.session_states[session_id] = {
                "session_id": session_id,
                "user_id": user_id,
                "started_at": utc_now().isoformat(),
                "last_active_at": utc_now().isoformat(),
                "last_time_reminder_at": None,
                "message_count": 0,
                "messages_since_identity": 0,
                "warn_count": 0,
                "blocked_count": 0,
                "stopped": False,
                "history": [],
                "last_user_categories": [],
                "last_bot_categories": [],
                "last_user_risk_level": "low",
                "last_bot_risk_level": "low",
            }
        return self.session_states[session_id]

    def _parse_dt(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None

    def _safe_text(self, value: Any) -> str:
        if value is None:
            return ""
        return str(value).strip()

    def _session_key(self, event: Any) -> str:
        return self._best_effort_session_id(event)

    def _user_key(self, event: Any) -> str:
        return self._best_effort_user_id(event)

    def _best_effort_session_id(self, *objects: Any) -> str:
        for obj in objects:
            if obj is None:
                continue
            for attr in ("session_id", "conversation_id", "chat_id"):
                value = getattr(obj, attr, None)
                if value:
                    return str(value)
            if isinstance(obj, dict):
                for key in ("session_id", "conversation_id", "chat_id"):
                    if obj.get(key):
                        return str(obj[key])
        return "default-session"

    def _best_effort_user_id(self, *objects: Any) -> str:
        for obj in objects:
            if obj is None:
                continue
            for attr in ("user_id", "sender_id", "author_id"):
                value = getattr(obj, attr, None)
                if value:
                    return str(value)
            if hasattr(obj, "get_sender_id"):
                try:
                    value = obj.get_sender_id()
                    if value:
                        return str(value)
                except Exception as exc:
                    logger.warning("Failed to read sender id: %s", exc)
            if isinstance(obj, dict):
                for key in ("user_id", "sender_id", "author_id"):
                    if obj.get(key):
                        return str(obj[key])
        return "anonymous-user"
