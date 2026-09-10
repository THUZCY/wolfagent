import random
from engine import GameEngine, GameEvent, Phase, ROLE_ZH

class Agent:
    """AI Agent with Memory + Belief + Decision layers."""
    def __init__(self, player_number: int, role, personality: dict, llm):
        self.num = player_number
        self.role = role
        self.personality = personality
        self.llm = llm
        self.aggression = personality.get("aggression", 0.5)
        self.talkativeness = personality.get("talkativeness", 0.5)
        self.caution = personality.get("caution", 0.5)
        self.risk_preference = personality.get("risk_preference", 0.5)
        self.memory: list[dict] = []
        self.belief: dict[int, float] = {}
        self.reasoning: list[str] = []

    def observe(self, events: list[GameEvent], engine: GameEngine):
        """Update memory with new events."""
        for ev in events:
            self.memory.append({
                "day": ev.day,
                "phase": ev.phase,
                "type": ev.event_type,
                "source": ev.source,
                "target": ev.target,
                "detail": ev.detail,
            })

    def update_belief(self, engine: GameEngine):
        """Update P(Wolf) belief for each alive player."""
        alive = [p.number for p in engine.players if p.alive and p.number != self.num]
        for pid in alive:
            if pid not in self.belief:
                self.belief[pid] = 0.25  # Initial: 2/7 wolves

        self.reasoning = []
        for ev in self.memory:
            if ev["type"] == "vote_kill" and ev["target"]:
                target = ev["target"]
                target_role = engine.get_player(target).role
                # If someone voted to kill a villager, increase suspicion
                if target_role.value in ("seer", "witch", "villager") and ev["source"]:
                    if ev["source"] in self.belief:
                        self.belief[ev["source"]] = min(0.95, self.belief[ev["source"]] + 0.1)
                        self.reasoning.append("第" + str(ev["day"]) + "天" + str(ev["source"]) + "号投票杀死了好人" + str(target) + "号")
            elif ev["type"] == "werewolf_kill" and ev["target"]:
                # Player killed by wolves is likely good
                if ev["target"] in self.belief:
                    self.belief[ev["target"]] = max(0.05, self.belief[ev["target"]] - 0.2)
            elif ev["type"] == "seer_check_good" and ev["target"]:
                if ev["target"] in self.belief:
                    self.belief[ev["target"]] = 0.0
                    self.reasoning.append("第" + str(ev["day"]) + "天预言家查验" + str(ev["target"]) + "号为好人")

    def decide(self, engine: GameEngine) -> dict:
        """Make a decision based on current game state."""
        self.update_belief(engine)
        phase = engine.phase
        my_role = self.role.value
        alive = engine.get_alive()
        alive_others = [p for p in alive if p != self.num]

        # Sort suspects by belief
        suspects = sorted(self.belief.items(), key=lambda x: -x[1])
        top_suspect = suspects[0][0] if suspects else None

        # risk_preference -> action_threshold: 0.45~0.70
        action_threshold = 0.70 - self.risk_preference * 0.25

        action = {"type": "pass", "target": None, "speech": "", "reasoning": list(self.reasoning)}

        if phase == Phase.NIGHT_WEREWOLF:
            if my_role == "werewolf" and alive_others:
                # Wolves pick a non-wolf target
                non_wolves = [p for p in alive_others if engine.get_player(p).role.value != "werewolf"]
                target = random.choice(non_wolves) if non_wolves else random.choice(alive_others)
                action = {"type": "kill", "target": target, "speech": "", "reasoning": ["狼人夜间选择猎杀" + str(target) + "号"]}
        elif phase == Phase.NIGHT_SEER:
            if my_role == "seer" and alive_others:
                # Check the most suspicious player
                target = top_suspect if top_suspect else random.choice(alive_others)
                action = {"type": "check", "target": target, "speech": "", "reasoning": ["预言家查验" + str(target) + "号身份"]}
        elif phase == Phase.NIGHT_WITCH:
            if my_role == "witch":
                if engine.witch_has_save and engine.night_kill_target:
                    # 50/50 save heuristic
                    if random.random() < 0.5:
                        action = {"type": "save", "target": engine.night_kill_target, "speech": "", "reasoning": ["女巫使用解药救" + str(engine.night_kill_target) + "号"]}
                    else:
                        action = {"type": "pass", "target": None, "speech": "", "reasoning": ["女巫选择不使用解药"]}
                elif engine.witch_has_poison and top_suspect:
                    if self.belief.get(top_suspect, 0) > action_threshold:
                        action = {"type": "poison", "target": top_suspect, "speech": "", "reasoning": ["女巫使用毒药毒杀嫌疑最大的" + str(top_suspect) + "号"]}
        elif phase == Phase.DAY_SPEECH:
            # Generate speech
            prompt = self._build_speech_prompt(engine, top_suspect)
            speech = self.llm.chat(
                "你是一个狼人杀玩家，根据你的角色和游戏信息做出合理发言。保持自然，不要说自己是AI。",
                prompt
            )
            action["type"] = "speech"
            action["speech"] = speech
            action["target"] = top_suspect
        elif phase == Phase.DAY_VOTE:
            if top_suspect and self.belief.get(top_suspect, 0) > action_threshold:
                action = {"type": "vote", "target": top_suspect, "speech": "", "reasoning": self.reasoning + ["根据信念分析，投票" + str(top_suspect) + "号"]}
            elif top_suspect and self.risk_preference > 0.65:
                action = {"type": "vote", "target": top_suspect, "speech": "", "reasoning": self.reasoning + ["激进判断，投票" + str(top_suspect) + "号"]}
            elif top_suspect:
                action = {"type": "vote", "target": random.choice(alive_others), "speech": "", "reasoning": ["信念不足，谨慎随机投票"]}
            else:
                action = {"type": "vote", "target": random.choice(alive_others), "speech": "", "reasoning": ["没有明确嫌疑人，随机投票"]}

        return action

    def _build_speech_prompt(self, engine: GameEngine, top_suspect: int) -> str:
        role_name = ROLE_ZH[self.role]
        lines = ["角色：" + role_name, "序号：" + str(self.num) + "号", "第" + str(engine.day) + "天", ""]
        lines.append("你的信念（对其他玩家的狼人概率）：")
        for pid, prob in sorted(self.belief.items(), key=lambda x: -x[1]):
            bar = "=" * int(prob * 10)
            lines.append("  " + str(pid) + "号: " + bar + " " + str(int(prob * 100)) + "%")
        if top_suspect:
            lines.append("")
            lines.append("最怀疑的目标：" + str(top_suspect) + "号")
        if self.reasoning:
            lines.append("")
            lines.append("推理依据：")
            for r in self.reasoning[-5:]:
                lines.append("  - " + r)
        lines.append("")
        if self.risk_preference > 0.7:
            lines.append("人格：你非常激进，即使证据不足也敢于直接指控。")
        elif self.risk_preference > 0.55:
            lines.append("人格：你独立判断，不被多数意见左右，坚持自己的推理。")
        elif self.risk_preference > 0.35:
            lines.append("人格：你倾向于跟随多数意见，注意观察大家的态度。")
        else:
            lines.append("人格：你非常谨慎，只有把握很大时才公开怀疑别人。")
        lines.append("请以狼人杀玩家的身份进行自然发言。")
        return "\n".join(lines)
