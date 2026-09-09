from abc import ABC, abstractmethod
import random

class LLMProvider(ABC):
    def chat(self, system_prompt: str, user_prompt: str) -> str: ...

class MockProvider(LLMProvider):
    """Smart local provider - parses game state and picks contextual templates.
    No API calls, no install, no key. Pure local reasoning simulation."""

    # ---- Template banks by role ----
    _VILLAGER_SPEECHES = {
        "accuse": [
            "{target}号，你的发言我仔细听了，{reason}。我觉得你应该解释一下。",
            "大家注意，{target}号今天的行为很反常——{reason}。我建议我们今天重点关注他。",
            "我一直觉得{target}号有问题。{reason}，这绝对不是巧合。",
        ],
        "cautious": [
            "现在局势还不太明朗，我只想说大家都别急着投票，多观察一轮。",
            "我今天没太多线索，先听听各位怎么说。目前对{target}号有一点怀疑，但还不确定。",
            "第{day}天了，信息还是不够。我倾向于再观察一轮，不想冤枉好人。",
        ],
        "defend": [
            "我觉得{target}号被踩得有点狠了，他对我的质疑回应得挺合理的。",
            "大家冷静，{target}号的发言至少是有逻辑的，我们不能只看表面。",
            "说实话，{target}号给我的感觉不太像狼。真正有问题的人可能正在带节奏。",
        ],
        "analysis": [
            "我把这几天的投票捋了一遍：{reasoning}。所以我现在最怀疑{target}号。",
            "复盘一下：第{day}天{event}，这说明什么？说明{target}号的嫌疑非常大。",
            "仔细想想，如果{target}号是好人，那他的行为就完全说不通。{reason}",
        ],
        "generic": [
            "我是{num}号村民。目前我关注的对象是{target}号，他昨天的行为确实可疑。",
            "村民报个到。线索不多，但我注意到{target}号一直在回避核心问题。",
            "虽然我只是个普通村民，但我觉得{target}号的发言里有明显的逻辑漏洞。",
        ],
    }

    _WOLF_SPEECHES = {
        "blend": [
            "我是{num}号，普通村民。说实话现在局势有点乱，我觉得{target}号的行为最反常。",
            "就是一个村民，我也没太多特殊信息。不过{target}号昨天的发言确实和之前对不上，大家可以回看一下。",
            "大家好，{num}号村民发言。我觉得{target}号在带节奏，呼吁大家冷静判断。",
        ],
        "mislead": [
            "{target}号一直在引导投票方向，这个行为本身就很可疑。真正的好人不会这么急切。",
            "我总觉得有人在第五层。{target}号虽然表面上说得有道理，但他的逻辑链条少了一环。",
            "各位想清楚，如果{target}号真是好人，他为什么要{reason}？这不符合好人逻辑。",
        ],
        "defend": [
            "我觉得{target}号挺无辜的，大家对他也太狠了。我们是不是先看看还有谁比较可疑？",
            "别这么快下结论，{target}号的解释是有道理的。我更关注另外几个没怎么发言的人。",
        ],
        "aggressive": [
            "{target}号，你哑巴了？刚才不是还很能说吗？你的逻辑我已经破了，出来解释。",
            "我就直说了，{target}号就是狼。{reason}，证据已经很充分了。",
        ],
    }

    _SEER_SPEECHES = {
        "hint": [
            "作为预言家，我可以告诉大家，我心里有数。今天先不报查验，大家自己判断。",
            "我查验过了，但没有必要现在说。请大家根据行为来分析。",
        ],
        "report": [
            "我是预言家。昨晚我查验了{target}号，他是{result}。请大家相信我！",
            "预言家在线。昨晚查验结果：{target}号是{result}。今天我们必须把票集中在狼人身上。",
        ],
        "cautious": [
            "我掌握了一些信息，但现在说出来可能对好人不一定有利。让我再观察一天。",
            "我的查验结果指向一个明确的方向，但请大家先自己分析一轮，这样更有说服力。",
        ],
    }

    _WITCH_SPEECHES = {
        "normal": [
            "我是女巫，药水还在/已用一部分。目前情况我看在眼里，请大家放心。",
            "女巫发言。我的信息不多，但今晚我会根据自己的判断行动。大家注意保护自己。",
        ],
        "suspicious": [
            "女巫在这。{target}号，你刚才的发言有一个致命问题——你说女巫应该昨晚用解药，但你怎么知道昨晚有人死了？",
            "我是女巫。我想提醒大家注意{target}号，他对药水的使用过于关注了，这不像一个普通好人的思考方式。",
        ],
    }

    _VOTE_REASONS = [
        "他的发言前后矛盾", "投票记录和口头发言不一致", "一直在回避核心问题",
        "他带节奏的方式太像狼了", "行为模式跟前面暴露的狼人一致",
        "他在关键节点改票的行为很可疑", "被指认时的反应过于激烈，炸裂式好人大部分不是好人",
    ]

    _WOLF_ACCUSE_REASONS = [
        "我觉得好人要团结，把票打在可疑的人身上",
        "狼人肯定在带节奏，大家别上当",
        "投票记录骗不了人",
    ]

    _NIGHT_EVENT_TEMPLATES = [
        "有人被杀了，说明狼人已经开始行动",
        "预言家应该已经有信息了，只是没说",
        "女巫可能已经用了解药，也可能留着",
    ]

    def chat(self, system_prompt: str, user_prompt: str) -> str:
        # Parse game state from prompt
        info = self._parse_prompt(user_prompt)
        role = info["role"]
        target = info.get("target")
        day = info.get("day", 1)

        # ---- Role-specific speech generation ----
        if role in ("villager", "村民"):
            return self._villager_speech(info)
        elif role in ("werewolf", "狼人"):
            return self._wolf_speech(info)
        elif role in ("seer", "预言家"):
            return self._seer_speech(info)
        elif role in ("witch", "女巫"):
            return self._witch_speech(info)

        # Fallback
        return self._generic_speech(info)

    def _parse_prompt(self, prompt: str) -> dict:
        info = {"role": "villager", "target": None, "day": 1, "beliefs": {}, "reasoning": [], "aggression": 0.5, "caution": 0.5, "num": 1}
        for line in prompt.split("\n"):
            s = line.strip()
            if s.startswith("角色："):
                r = s[3:].strip().split("/")[0]
                info["role"] = r
            elif s.startswith("序号："):
                try: info["num"] = int(s[3:].replace("号","").strip())
                except: pass
            elif s.startswith("第") and s.endswith("天"):
                try: info["day"] = int(s[1:-1])
                except: pass
            elif s.startswith("最怀疑的目标："):
                try: info["target"] = int(s[7:].replace("号","").strip())
                except: pass
            elif s.startswith("目标："):
                try: info["target"] = int(s[3:].replace("号","").strip())
                except: pass
            elif "激进" in s:
                info["aggression"] = 0.8
            elif "谨慎" in s:
                info["caution"] = 0.8
            elif s.endswith("%"):
                # Belief line: "  3号: === 30%"
                try:
                    parts = s.strip().split("号:")
                    if len(parts) == 2:
                        pid = int(parts[0])
                        pct = int(parts[1].strip().rstrip("%").split()[-1])
                        info["beliefs"][pid] = pct / 100.0
                except: pass
            elif s.startswith("  - ") and len(s) > 4:
                info["reasoning"].append(s[4:].strip())
        return info

    def _villager_speech(self, info):
        target = info.get("target")
        aggression = info.get("aggression", 0.5)
        caution = info.get("caution", 0.5)
        reasoning = info.get("reasoning", [])
        target_str = str(target) if target else "?"
        day = info.get("day", 1)
        num = info.get("num", "?")

        reason = random.choice(self._VOTE_REASONS)
        event = random.choice(self._NIGHT_EVENT_TEMPLATES)
        reasoning_text = "；".join(reasoning[-2:]) if reasoning else "信息还不够"

        if aggression > 0.6 and target:
            tmpl = random.choice(self._VILLAGER_SPEECHES["accuse"])
            return tmpl.format(target=target_str, reason=reason)
        elif caution > 0.6:
            tmpl = random.choice(self._VILLAGER_SPEECHES["cautious"])
            return tmpl.format(target=target_str, day=day)
        elif reasoning and target:
            tmpl = random.choice(self._VILLAGER_SPEECHES["analysis"])
            return tmpl.format(target=target_str, day=day, event=event, reasoning=reasoning_text)
        else:
            tmpl = random.choice(self._VILLAGER_SPEECHES["generic"])
            return tmpl.format(target=target_str, num=num)

    def _wolf_speech(self, info):
        target = info.get("target")
        aggression = info.get("aggression", 0.5)
        target_str = str(target) if target else "?"
        num = info.get("num", "?")
        reason = random.choice(self._WOLF_ACCUSE_REASONS)
        reasoning = info.get("reasoning", [])
        reason_detail = reasoning[-1] if reasoning else "他在关键投票中反复改口"

        scenarios = ["blend", "mislead", "defend"]
        if aggression > 0.7:
            scenarios.append("aggressive")

        scene = random.choice(scenarios)
        if scene == "blend":
            return random.choice(self._WOLF_SPEECHES["blend"]).format(num=num, target=target_str)
        elif scene == "mislead":
            return random.choice(self._WOLF_SPEECHES["mislead"]).format(target=target_str, reason=reason)
        elif scene == "defend":
            # Defend a random other player (not self, not the top suspect)
            return random.choice(self._WOLF_SPEECHES["defend"]).format(target=target_str)
        else:
            return random.choice(self._WOLF_SPEECHES["aggressive"]).format(target=target_str, reason=reason_detail)

    def _seer_speech(self, info):
        target = info.get("target")
        caution = info.get("caution", 0.5)
        target_str = str(target) if target else "?"
        day = info.get("day", 1)

        # Simulate a "check result" based on beliefs
        beliefs = info.get("beliefs", {})
        if target and target in beliefs:
            result = "狼人" if beliefs[target] > 0.5 else "好人"
        else:
            result = random.choice(["好人", "狼人"])

        if caution > 0.6 or day == 1:
            return random.choice(self._SEER_SPEECHES["hint"]).format(target=target_str)
        elif day >= 2:
            return random.choice(self._SEER_SPEECHES["report"]).format(target=target_str, result=result)
        else:
            return random.choice(self._SEER_SPEECHES["cautious"]).format(target=target_str)

    def _witch_speech(self, info):
        target = info.get("target")
        target_str = str(target) if target else "?"
        num = info.get("num", "?")

        if target:
            return random.choice(self._WITCH_SPEECHES["suspicious"]).format(target=target_str, num=num)
        else:
            return random.choice(self._WITCH_SPEECHES["normal"]).format(target=target_str, num=num)

    def _generic_speech(self, info):
        target = info.get("target")
        num = info.get("num", "?")
        target_str = str(target) if target else "?"
        return random.choice([
            f"{num}号，目前我觉得{target_str}号嫌疑较大，大家仔细回想一下他的发言。",
            f"暂时没有太多线索，但{target_str}号的行为确实值得关注。",
            f"我是{num}号，我觉得我们应该再讨论一轮，目前的证据还不够充分。",
        ])


class OpenAIProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        self.api_key = api_key; self.model = model
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI
        c = OpenAI(api_key=self.api_key)
        r = c.chat.completions.create(model=self.model, messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}], temperature=0.7, max_tokens=200)
        return r.choices[0].message.content

class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "deepseek-chat"):
        self.api_key = api_key; self.model = model
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI
        c = OpenAI(api_key=self.api_key, base_url="https://api.deepseek.com/v1")
        r = c.chat.completions.create(model=self.model, messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}], temperature=0.7, max_tokens=200)
        return r.choices[0].message.content

class GroqProvider(LLMProvider):
    """Groq Cloud - free tier, very fast (Llama 3, Mixtral)."""
    def __init__(self, api_key: str, model: str = "llama-3.2-3b-preview"):
        self.api_key = api_key; self.model = model
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI
        c = OpenAI(api_key=self.api_key, base_url="https://api.groq.com/openai/v1")
        r = c.chat.completions.create(model=self.model, messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}], temperature=0.7, max_tokens=200)
        return r.choices[0].message.content

class GeminiProvider(LLMProvider):
    """Google Gemini - free tier via OpenAI-compatible endpoint."""
    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        self.api_key = api_key; self.model = model
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI
        c = OpenAI(api_key=self.api_key, base_url="https://generativelanguage.googleapis.com/v1beta/openai/")
        r = c.chat.completions.create(model=self.model, messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}], temperature=0.7, max_tokens=200)
        return r.choices[0].message.content

class OllamaProvider(LLMProvider):
    """Ollama local - completely free, no API key, runs on your own machine.
    Supports Chinese models: qwen2.5, deepseek-r1, glm4, etc."""
    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434/v1"):
        self.model = model; self.base_url = base_url
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        from openai import OpenAI
        c = OpenAI(api_key="ollama", base_url=self.base_url)
        r = c.chat.completions.create(model=self.model, messages=[{"role":"system","content":system_prompt},{"role":"user","content":user_prompt}], temperature=0.7, max_tokens=200)
        return r.choices[0].message.content
