from __future__ import annotations

from coordbench.models import Message

ZH_TRANSLATIONS = {
    "Name a wild animal": "说出一种野生动物",
    "Name a female world leader": "说出一位女性世界领导人",
    "Name a popular dance": "说出一种流行舞蹈",
    "Name a landmark": "说出一个地标",
    "Name a typical snack": "说出一种典型零食",
    "Name a male singer": "说出一位男歌手",
    "Name a typical drink": "说出一种典型饮料",
    "Name a city": "说出一座城市",
    "Name a piece of art": "说出一件艺术作品",
    "Name a newspaper": "说出一家报纸",
    "Name a sport player (any sport)": "说出一位运动员（任何运动项目）",
    "Name a world leader": "说出一位世界领导人",
    "Name a building": "说出一座建筑",
    "Name a book": "说出一本书",
    "Name a television broadcasting organisation": "说出一家电视广播机构",
    "Name a male football player": "说出一位男性足球运动员",
    "Name a cartoon": "说出一个卡通角色",
    "Name a recognisable chocolate brand": "说出一个知名巧克力品牌",
    "Name a music band": "说出一个乐队",
    "Name a date in the year": "说出一年中的一个日期",
    "Name a mountain": "说出一座山",
    "Name a currency": "说出一种货币",
    "Name a typical celebration": "说出一种典型庆祝活动",
    "Name a female singer": "说出一位女歌手",
    "Name a beach": "说出一个海滩",
    "Name a flight company": "说出一家航空公司",
    "Name a typical dish": "说出一道典型菜肴",
    "Name a typical flower": "说出一种典型花卉",
    "Name a sport": "说出一项运动",
    "Name a tourist city": "说出一座旅游城市",
}


def translate_item(item_text_en: str) -> str:
    key = item_text_en.strip().rstrip(".:")
    return ZH_TRANSLATIONS.get(key, key)


def _target_group_context_en(target_group: str) -> str:
    mapping = {
        "british": "from the UK",
        "global": "from around the world",
        "south_african": "from South Africa",
        "chilean": "from Chile",
    }
    return mapping.get(str(target_group).strip().lower(), "from the target group")


def _target_group_context_zh(target_group: str) -> str:
    mapping = {
        "british": "来自英国",
        "global": "来自世界各地",
        "south_african": "来自南非",
        "chilean": "来自智利",
    }
    return mapping.get(str(target_group).strip().lower(), "来自目标群体")


def build_prompt_messages(
    *,
    item_text_en: str,
    item_text_zh: str,
    prompt_language: str,
    answer_language: str,
    round_index: int,
    target_group: str = "global",
) -> list[Message]:
    context_en = _target_group_context_en(target_group)
    context_zh = _target_group_context_zh(target_group)
    if prompt_language == "zh":
        system_prompt = (
            "你正在参与一个纯协调任务。"
            f"你的目标是给出最可能与另一位{context_zh}的参与者一致的答案。"
            "只输出一个简短答案，不要解释，不要加额外说明。"
        )
        if round_index == 1:
            user_prompt = (
                f"请只给出一个最可能与另一位{context_zh}的参与者一致的答案。\n"
                f"请用{answer_language}作答。\n"
                f"类别：{item_text_zh}"
            )
        else:
            user_prompt = (
                "请在不改变协调目标的前提下再尝试一次，"
                f"给出一个最可能与另一位{context_zh}的参与者一致的答案。\n"
                f"请用{answer_language}作答。\n"
                f"类别：{item_text_zh}"
            )
    else:
        system_prompt = (
            "You are taking part in a pure coordination task. "
            f"Your goal is to give the answer another participant {context_en} is most likely to give. "
            "Return exactly one short answer and no explanation."
        )
        if round_index == 1:
            user_prompt = (
                f"Give one short answer that is most likely to match another participant {context_en}.\n"
                f"Answer in {answer_language}.\n"
                f"Category: {item_text_en}"
            )
        else:
            user_prompt = (
                "Try again without changing the coordination goal. "
                f"Give one short answer that is most likely to match another participant {context_en}.\n"
                f"Answer in {answer_language}.\n"
                f"Category: {item_text_en}"
            )

    return [
        Message(role="system", content=system_prompt),
        Message(role="user", content=user_prompt),
    ]
