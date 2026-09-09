from abc import ABC, abstractmethod
import random

class LLMProvider(ABC):
    def chat(self, system_prompt: str, user_prompt: str) -> str: ...

class MockProvider(LLMProvider):
    """Mock provider for testing without API calls."""
    def chat(self, system_prompt: str, user_prompt: str) -> str:
        lines = [l.strip() for l in user_prompt.split("\n") if l.strip()]
        role = "villager"
        target = None
        for line in lines:
            if line.startswith("角色："): role = line[3:].strip().split("/")[0]
            elif line.startswith("目标："): target = line[3:].strip()
        templates = {
            "villager": ["我觉得目前局势还不太明朗，需要多观察。", "我暂时没什么特别的想法，先听听大家的意见。", "从目前的信息来看，我觉得大家应该谨慎投票。"],
            "seer": ["我需要更多信息来做判断，请大家继续发表意见。", "目前的信息还不够，我建议多讨论一轮。"],
            "witch": ["我会在关键时刻使用我的能力，请大家放心。", "目前形势还好，我会根据情况决定是否用药。"],
        }
        if target:
            tpls = [target+"号的发言有点奇怪，他在回避关键问题。", "我觉得"+target+"号很有问题，他的发言前后矛盾。", "我注意到"+target+"号的投票行为和之前不一致。" ]
            return random.choice(tpls)
        t = templates.get(role, templates["villager"])
        return random.choice(t)

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
