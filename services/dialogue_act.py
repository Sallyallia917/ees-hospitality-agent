"""Lightweight deterministic dialogue-act recognition for context repair.

This layer interprets conversational function only. It never authorizes a
transaction or changes booking data.
"""
import re

ACTS = {
    "new_request", "supplement", "correction", "confirmation", "rejection",
    "status_query", "history_reference", "complaint", "clarification", "unknown",
}

def classify_dialogue_act(message: str, context=None, history=None):
    text = re.sub(r"\\s+", "", str(message or "")).lower()
    context = context or {}
    history = history or []

    if not text:
        return {"act": "unknown", "confidence": 0.0, "signals": []}

    if any(x in text for x in ("你不记得", "我刚才说过", "我之前说过", "不是第一次", "之前不是")):
        return {"act": "history_reference", "confidence": 0.96, "signals": ["history_marker"]}

    if any(x in text for x in ("还是没人", "仍然没人", "一直没人", "没人处理", "没有人来", "不满意", "投诉", "太差了")):
        return {"act": "complaint", "confidence": 0.94, "signals": ["service_dissatisfaction"]}

    if any(x in text for x in ("处理到哪", "进度如何", "现在怎么样", "到哪一步", "工单状态", "处理了吗")):
        return {"act": "status_query", "confidence": 0.95, "signals": ["status_marker"]}

    if any(x in text for x in ("不是", "不对", "我说的是", "应该是", "改一下", "更正", "不是这笔", "另一笔")):
        return {"act": "correction", "confidence": 0.93, "signals": ["correction_marker"]}

    if any(x in text for x in ("另外", "还有", "再加", "同时", "也坏了", "也需要", "补充一下")):
        return {"act": "supplement", "confidence": 0.90, "signals": ["additive_marker"]}

    if context.get("pending_action") in {"confirm_transaction", "confirm_ticket"}:
        if any(x in text for x in ("确认", "是的", "没错", "对", "确定")):
            return {"act": "confirmation", "confidence": 0.96, "signals": ["pending_confirmation"]}
        if any(x in text for x in ("算了", "取消", "不需要", "先不用", "不确认")):
            return {"act": "rejection", "confidence": 0.96, "signals": ["pending_confirmation"]}

    if len(history) and any(x in text for x in ("刚才", "刚刚", "前面", "上次", "那件事", "那笔")):
        return {"act": "history_reference", "confidence": 0.84, "signals": ["history_deictic"]}

    if any(x in text for x in ("空调", "维修", "打扫", "清洁", "毛巾", "送水", "送物", "加被子", "房间太冷", "漏水", "噪音")):
        return {"act": "new_request", "confidence": 0.82, "signals": ["service_need"]}

    if any(x in text for x in ("吗", "呢", "什么", "怎么", "哪里", "几时", "多少")):
        return {"act": "clarification", "confidence": 0.72, "signals": ["question_form"]}

    return {"act": "unknown", "confidence": 0.40, "signals": []}
