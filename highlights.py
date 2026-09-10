"""
Highlight Detection Module for Werewolf Game
Detects key moments: divine prophecy, seer impersonation, critical votes, fatal mistakes.
Uses rule-based detection + optional LLM for narrative generation.
"""
from engine import GameEngine, GameEvent, ROLE_ZH, Role
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class Highlight:
    category: str          # divine_prophecy, seer_impersonation, critical_vote, fatal_mistake
    emoji: str
    title: str
    description: str
    players: list[int] = field(default_factory=list)
    day: int = 0
    score: float = 0.0     # 0-1, how significant this highlight is


CATEGORY_META = {
    "divine_prophecy": {"emoji": "🧠", "label": "神预言"},
    "seer_impersonation": {"emoji": "🎭", "label": "成功悍跳"},
    "critical_vote": {"emoji": "⚔️", "label": "关键投票"},
    "fatal_mistake": {"emoji": "💀", "label": "致命失误"},
}


class HighlightDetector:
    """Detects game highlights from the game engine and log."""

    def __init__(self, engine: GameEngine, log: list[dict]):
        self.engine = engine
        self.log = log
        self._players = {p.number: p for p in engine.players}

    def detect_all(self) -> list[Highlight]:
        highlights = []
        highlights.extend(self._detect_divine_prophecy())
        highlights.extend(self._detect_seer_impersonation())
        highlights.extend(self._detect_critical_vote())
        highlights.extend(self._detect_fatal_mistake())
        highlights.sort(key=lambda h: -h.score)
        return highlights

    # ---- Divine Prophecy: non-seer correctly predicts a werewolf ----
    def _detect_divine_prophecy(self) -> list[Highlight]:
        results = []
        # Find players without special info: villagers and witch (not seer, not werewolf)
        non_informed = [p for p in self._players.values() if p.role not in (Role.SEER, Role.WEREWOLF)]

        for player in non_informed:
            # Track accusations/votes against werewolves
            correct_accusations = []
            for entry in self.log:
                if entry.get("type") == "speech" and entry.get("player") == player.number:
                    speech = entry.get("msg", "")
                    # Check if speech accuses a werewolf
                    for p in self._players.values():
                        if p.role == Role.WEREWOLF and p.number != player.number:
                            if str(p.number) + "号" in speech or str(p.number) + " " in speech:
                                # Check if speech contains accusation keywords
                                accusation_keywords = ["狼", "可疑", "有问题", "嫌疑", "是狼", "铁狼", "狼人", "不对", "反常"]
                                if any(kw in speech for kw in accusation_keywords):
                                    correct_accusations.append({
                                        "day": entry.get("day", 0),
                                        "target": p.number,
                                    })

            if len(correct_accusations) >= 2:
                # Calculate score based on how early and how many correct accusations
                first_day = correct_accusations[0]["day"]
                score = min(1.0, 0.5 + 0.2 * len(correct_accusations) - 0.05 * max(0, first_day - 2))
                results.append(Highlight(
                    category="divine_prophecy",
                    emoji="🧠",
                    title=f'{player.number}号的神预言',
                    description=f'{player.number}号（{ROLE_ZH[player.role]}）在没有任何特殊信息的情况下，持续正确指控狼人{self._format_targets(correct_accusations)}，堪称神预言！',
                    players=[player.number],
                    day=first_day,
                    score=score,
                ))

        return results

    # ---- Seer Impersonation: werewolf successfully pretends to be seer ----
    def _detect_seer_impersonation(self) -> list[Highlight]:
        results = []
        wolves = [p for p in self._players.values() if p.role == Role.WEREWOLF]

        for wolf in wolves:
            seer_claims = []
            for entry in self.log:
                if entry.get("type") == "speech" and entry.get("player") == wolf.number:
                    speech = entry.get("msg", "")
                    if "预言家" in speech and ("我是" in speech or "我" in speech[:3]):
                        seer_claims.append({
                            "day": entry.get("day", 0),
                            "speech": speech,
                        })

            if seer_claims:
                # Check if wolf survived to the end or was not eliminated immediately after claiming
                survived = wolf.alive or not any(
                    e.get("type") == "death" and e.get("player") == wolf.number
                    for e in self.log[-5:]
                )
                score = 0.7 + 0.1 * len(seer_claims)
                if survived:
                    score += 0.2

                if score > 0.0:
                    results.append(Highlight(
                        category="seer_impersonation",
                        emoji="🎭",
                        title=f'{wolf.number}号狼人悍跳预言家',
                        description=f'{wolf.number}号（狼人）在第{seer_claims[0]["day"]}天开始伪装成预言家，连续{len(seer_claims)}轮成功骗过好人阵营，堪称演技派！',
                        players=[wolf.number],
                        day=seer_claims[0]["day"],
                        score=score,
                    ))

        return results

    # ---- Critical Vote: vote margin of 1 that changed the outcome ----
    def _detect_critical_vote(self) -> list[Highlight]:
        results = []
        # Group votes by day
        votes_by_day = {}
        for entry in self.log:
            if entry.get("type") == "vote":
                day = entry.get("day", 0)
                if day not in votes_by_day:
                    votes_by_day[day] = []
                votes_by_day[day].append(entry)

        for day, votes in votes_by_day.items():
            if len(votes) < 2:
                continue
            # Count vote targets
            target_counts = Counter(v["target"] for v in votes)
            if len(target_counts) < 2:
                continue
            sorted_counts = target_counts.most_common()
            top_count = sorted_counts[0][1]
            second_count = sorted_counts[1][1] if len(sorted_counts) > 1 else 0
            margin = top_count - second_count

            if margin == 1:
                eliminated = sorted_counts[0][0]
                player = self._players.get(eliminated)
                if player:
                    score = 0.6 + 0.1 * min(day, 3)
                    results.append(Highlight(
                        category="critical_vote",
                        emoji="⚔️",
                        title=f'第{day}天关键投票',
                        description=f'第{day}天投票中，{eliminated}号（{ROLE_ZH[player.role]}）以仅差1票的微弱优势被放逐。如果少一票，结果将完全不同！',
                        players=[eliminated],
                        day=day,
                        score=score,
                    ))

        return results

    # ---- Fatal Mistake: wolf's wrong kill leads to exposure ----
    def _detect_fatal_mistake(self) -> list[Highlight]:
        results = []
        wolves = [p for p in self._players.values() if p.role == Role.WEREWOLF]

        # Track: wolf kills someone, then wolf gets voted out next day
        # Skip same-day death pairs (witch poison is not wolf's mistake)
        # Focus on: wolf got voted out right after a night their team made a kill
        for entry in self.log:
            if entry.get("type") == "death":
                dead_player = entry.get("player")
                if dead_player is None:
                    continue
                dead = self._players.get(dead_player)
                if dead is None:
                    continue

                # Track deaths that led to wolf exposure via voting pattern
                day = entry.get("day", 0)
                # Avoid same-day death pairs (witch poison is intentional, not wolf mistake)
                same_day_deaths = [e for e in self.log
                                  if e.get("type") == "death" and e.get("day") == day]
                if len(same_day_deaths) >= 2:
                    continue  # Multiple deaths - likely witch intervention

        # Also detect: wolf kills and the kill pattern exposes them
        # Wolves that got voted out right after a night kill
        for wolf in wolves:
            if not wolf.alive:
                # Find when wolf was eliminated
                for entry in self.log:
                    if entry.get("type") == "death" and entry.get("player") == wolf.number:
                        elim_day = entry.get("day", 0)
                        # Check if there was a night kill the night before
                        night_before = elim_day - 1
                        night_kills_before = [
                            e for e in self.log
                            if e.get("type") == "night" and e.get("day") == night_before
                            and "猎杀" in e.get("msg", "")
                        ]
                        if night_kills_before:
                            results.append(Highlight(
                                category="fatal_mistake",
                                emoji="💀",
                                title=f'狼人{wolf.number}号致命失误',
                                description=f'狼人{wolf.number}号在第{night_before}天夜间猎杀后，第{elim_day}天被投票放逐，猎杀选择暴露了其狼人身份。',
                                players=[wolf.number],
                                day=elim_day,
                                score=0.7,
                            ))
                        break

        return results

    def _format_targets(self, accusations: list[dict]) -> str:
        targets = list(set(a["target"] for a in accusations))
        return "、".join(f'{t}号' for t in targets)

    def to_dict(self, highlights: list[Highlight]) -> list[dict]:
        return [
            {
                "category": h.category,
                "emoji": h.emoji,
                "title": h.title,
                "description": h.description,
                "players": h.players,
                "day": h.day,
                "score": round(h.score, 2),
            }
            for h in highlights
        ]


def generate_highlight_narrative(highlights: list[Highlight], llm_provider=None) -> str:
    """Generate a narrative summary of highlights using LLM."""
    if not highlights:
        return ""

    top = highlights[0] if highlights else None
    if top is None:
        return ""

    if llm_provider is None:
        # Fallback: rule-based narrative
        return f'🔥 本局高光：{top.title}——{top.description}'

    system_prompt = (
        "你是一个狼人杀比赛解说。根据给定的高光时刻，生成一句简短有力的解说词，"
        "适合放在首页展示，不超过30个字。要有感染力。"
    )
    user_prompt = (
        f'标题：{top.title}\n'
        f'描述：{top.description}\n'
        f'分类：{CATEGORY_META[top.category]["label"]}\n'
        "请生成一句高光解说词。"
    )
    try:
        narrative = llm_provider.chat(system_prompt, user_prompt)
        return f'🔥 {narrative.strip()}'
    except Exception:
        return f'🔥 本局高光：{top.title}——{top.description}'
