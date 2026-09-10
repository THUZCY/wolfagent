# -*- coding: utf-8 -*-
import json, random
from engine import GameEngine, GameEvent, Phase, ROLE_ZH, Role
from memory import AgentMemory, PlayerBelief, Evidence

class Agent:
    """AI Agent with structured Memory + Evidence-based Belief + Explainable Decisions."""

    def __init__(self, player_number: int, role, personality: dict, llm):
        self.num = player_number
        self.role = role
        self.personality = personality
        self.llm = llm
        self.aggression = personality.get("aggression", 0.5)
        self.talkativeness = personality.get("talkativeness", 0.5)
        self.caution = personality.get("caution", 0.5)
        self.risk_preference = personality.get("risk_preference", 0.5)
        self.memory = AgentMemory(player_number)
        self.belief: dict = {}
        self.reasoning: list = []
        self._private_knowledge: dict = {}
    def observe(self, events, engine):
        """Update structured memory with visible events."""
        for ev in events:
            self.memory.add_event({
                "day": ev.day, "phase": ev.phase,
                "type": ev.event_type,
                "source": ev.source, "target": ev.target,
                "msg": ev.detail,
            })
            role_name = ROLE_ZH[engine.get_player(ev.target).role] if ev.target else "?"

            if ev.event_type == "werewolf_kill" and ev.target:
                self.memory.add_fact(
                    f"{ev.target}号在第{ev.day}天夜间被狼人猎杀", ev.day)
                self.memory.update_belief(ev.target, -0.15,
                    Evidence("werewolf_kill",
                            f"第{ev.day}天被狼人猎杀，很可能是好人", 2.0, ev.day))

            elif ev.event_type == "vote_eliminate" and ev.target:
                self.memory.add_fact(
                    f"{ev.target}号在第{ev.day}天被投票放逐，身份：{role_name}", ev.day)
                if engine.get_player(ev.target).role.value == "werewolf":
                    self.memory.add_fact(f"{ev.target}号被确认是狼人", ev.day)

            elif ev.event_type == "seer_check_good" and ev.target:
                self.memory.add_fact(f"预言家查验{ev.target}号为好人", ev.day)
                self.memory.set_belief_direct(ev.target, 0.0,
                    f"第{ev.day}天被预言家查验为好人")

            elif ev.event_type == "death" and ev.target:
                self.memory.add_fact(
                    f"{ev.target}号在第{ev.day}天死亡，身份：{role_name}", ev.day)
                if engine.get_player(ev.target).role.value == "werewolf":
                    self.memory.add_fact(f"{ev.target}号被确认是狼人", ev.day)

            elif ev.event_type == "seer_check_wolf" and ev.target:
                self.memory.add_fact(f"预言家查验{ev.target}号为狼人", ev.day)
                self.memory.set_belief_direct(ev.target, 0.95,
                    f"第{ev.day}天被预言家查验为狼人")

    # ================================================================
    #  Belief Update (incremental, evidence-based)
    # ================================================================

    def update_belief(self, engine):
        """Update P(Wolf) belief: previous_belief + new_evidence + LLM judgment."""
        alive = [p.number for p in engine.players if p.alive and p.number != self.num]
        for pid in alive:
            if pid not in self.memory.player_beliefs:
                self.memory.get_belief(pid)

        self.reasoning = []

        for ev in self.memory.important_events:
            if ev.get("type") == "vote_kill" and ev.get("target") and ev.get("source"):
                try:
                    target_role = engine.get_player(ev["target"]).role
                    if target_role.value in ("seer", "witch", "villager"):
                        if ev["source"] != self.num:
                            self.memory.update_belief(ev["source"], 0.08,
                                Evidence("vote_pattern",
                                    f"第{ev['day']}天投票放逐了好人{ev['target']}号", 1.5, ev.get("day", 0)))
                            self.reasoning.append(
                                f"第{ev['day']}天{ev['source']}号投票放逐了好人{ev['target']}号")
                except Exception:
                    pass

            elif ev.get("type") == "werewolf_kill" and ev.get("target"):
                self.memory.update_belief(ev["target"], -0.10,
                    Evidence("werewolf_kill", "被狼人猎杀，大概率是好人", 1.5, ev.get("day", 0)))

        # Auto-detect contradictions
        self.memory.detect_contradictions(engine)

        # Sync legacy belief dict for API compatibility
        self.belief = {
            pid: round(b.wolf_probability, 2)
            for pid, b in self.memory.player_beliefs.items()
        }

    # ================================================================
    #  Decision Engine
    # ================================================================

    def decide(self, engine) -> dict:
        """Make a decision based on current game state.
        Returns structured dict with analysis, decision, and public_reason."""
        self.update_belief(engine)
        phase = engine.phase
        my_role = self.role.value
        alive = engine.get_alive()
        alive_others = [p for p in alive if p != self.num]

        # Build sorted suspicion list
        suspicions = sorted(
            [{
                "player_id": pid,
                "wolf_probability": b.wolf_probability,
                "confidence": b.confidence,
                "evidence": [e.description for e in b.evidence[-3:]],
            } for pid, b in self.memory.player_beliefs.items() if pid in alive_others],
            key=lambda x: -x["wolf_probability"],
        )

        top_suspect = suspicions[0]["player_id"] if suspicions else None
        top_confidence = suspicions[0]["confidence"] if suspicions else 0.5
        action_threshold = 0.70 - self.risk_preference * 0.25

        action = {
            "type": "pass", "target": None, "speech": "",
            "confidence": 0.5, "reason": "", "evidence": [],
        }

        if phase == Phase.NIGHT_WEREWOLF:
            action = self._night_wolf(engine, alive_others)
        elif phase == Phase.NIGHT_SEER:
            action = self._night_seer(engine, alive_others, top_suspect)
        elif phase == Phase.NIGHT_WITCH:
            action = self._night_witch(engine, top_suspect, action_threshold)
        elif phase == Phase.DAY_SPEECH:
            action = self._day_speech(engine, top_suspect, top_confidence)
        elif phase == Phase.DAY_VOTE:
            action = self._day_vote(engine, alive_others, top_suspect,
                                    top_confidence, action_threshold)

        action["analysis"] = {
            "suspicions": suspicions[:5],
            "memory_round": self.memory.current_round,
        }
        return action

    # ---- Night: Werewolf ----

    def _night_wolf(self, engine, alive_others):
        if not alive_others:
            return {"type": "pass", "target": None, "speech": "", "confidence": 1.0, "reason": "", "evidence": []}
        non_wolves = [p for p in alive_others if engine.get_player(p).role.value != "werewolf"]
        target = random.choice(non_wolves) if non_wolves else random.choice(alive_others)
        return {
            "type": "kill", "target": target,
            "speech": "", "confidence": 0.8,
            "reason": f"狼人夜间猎杀{target}号", "evidence": [],
        }

    # ---- Night: Seer ----

    def _night_seer(self, engine, alive_others, top_suspect):
        if not alive_others:
            return {"type": "pass", "target": None, "speech": "", "confidence": 1.0, "reason": "", "evidence": []}
        already_checked = [e["target"] for e in self.memory.important_events
                          if e.get("type") == "seer_check"]
        candidates = [p for p in alive_others if p not in already_checked]
        if top_suspect and top_suspect in candidates:
            target = top_suspect
        elif candidates:
            target = random.choice(candidates)
        else:
            target = random.choice(alive_others)
        return {
            "type": "check", "target": target,
            "speech": "", "confidence": 0.7,
            "reason": f"预言家查验{target}号", "evidence": [],
        }

    # ---- Night: Witch ----

    def _night_witch(self, engine, top_suspect, action_threshold):
        if engine.witch_has_save and engine.night_kill_target:
            if random.random() < 0.5:
                return {
                    "type": "save", "target": engine.night_kill_target,
                    "speech": "", "confidence": 0.6,
                    "reason": f"女巫解药救{engine.night_kill_target}号", "evidence": [],
                }
            return {"type": "pass", "target": None, "speech": "", "confidence": 0.5, "reason": "", "evidence": []}
        elif engine.witch_has_poison and top_suspect:
            b = self.memory.player_beliefs.get(top_suspect)
            prob = b.wolf_probability if b else 0
            if prob > action_threshold:
                ev = [e.description for e in b.evidence[-3:]] if b else []
                return {
                    "type": "poison", "target": top_suspect,
                    "speech": "", "confidence": prob,
                    "reason": f"毒杀{top_suspect}号(狼人概率{int(prob*100)}%)",
                    "evidence": ev,
                }
        return {"type": "pass", "target": None, "speech": "", "confidence": 0.5, "reason": "", "evidence": []}

    # ---- Day Speech ----

    def _day_speech(self, engine, top_suspect, top_confidence):
        prompt = self._build_speech_prompt(engine, top_suspect)
        speech = self.llm.chat(
            "你是一个狼人杀玩家，根据你的角色和游戏信息做出合理发言。保持自然，不要说自己是AI。每轮发言控制在2-4句。",
            prompt,
        )
        # Record claim
        if top_suspect:
            if "可疑" in speech or "怀疑" in speech or "狼" in speech:
                claim_type = "accuse"
            elif "好人" in speech or "相信" in speech:
                claim_type = "defend"
            else:
                claim_type = "neutral"
            self.memory.add_claim(engine.day, claim_type, speech[:100], target=top_suspect)

        b = self.memory.player_beliefs.get(top_suspect) if top_suspect else None
        ev = [e.description for e in b.evidence[-3:]] if b else []
        return {
            "type": "speech", "speech": speech, "target": top_suspect,
            "confidence": top_confidence,
            "reason": f"最怀疑{top_suspect}号" if top_suspect else "观察中",
            "evidence": ev,
        }

    # ---- Day Vote ----

    def _day_vote(self, engine, alive_others, top_suspect, top_confidence, action_threshold):
        if top_suspect:
            b = self.memory.player_beliefs.get(top_suspect, PlayerBelief(top_suspect))
            if b.wolf_probability > action_threshold:
                return {
                    "type": "vote", "target": top_suspect,
                    "speech": "", "confidence": b.confidence,
                    "reason": f"投票{top_suspect}号(狼人概率{int(b.wolf_probability*100)}%)",
                    "evidence": [e.description for e in b.evidence[-5:]],
                }
            elif self.risk_preference > 0.65:
                return {
                    "type": "vote", "target": top_suspect,
                    "speech": "", "confidence": 0.55,
                    "reason": f"激进投票{top_suspect}号",
                    "evidence": [e.description for e in b.evidence[-3:]],
                }
            else:
                return {
                    "type": "vote", "target": top_suspect,
                    "speech": "", "confidence": b.confidence * 0.7,
                    "reason": f"谨慎投票{top_suspect}号",
                    "evidence": [e.description for e in b.evidence[-2:]],
                }
        else:
            t = random.choice(alive_others) if alive_others else None
            return {"type": "vote", "target": t, "speech": "", "confidence": 0.2, "reason": "随机投票", "evidence": []}

    # ---- Speech Prompt Builder (includes Memory summary) ----

    def _build_speech_prompt(self, engine, top_suspect):
        role_name = ROLE_ZH[self.role]
        lines = [
            f"角色：{role_name}",
            f"序号：{self.num}号",
            f"第{engine.day}天",
            "",
            "【记忆摘要】",
            self.memory.get_summary_for_llm(),
            "",
        ]

        # Role-specific private info
        if self.role.value == "werewolf":
            wolves = [p.number for p in engine.players
                      if p.role.value == "werewolf" and p.alive]
            lines.append(f"狼队友：{wolves}")
        elif self.role.value == "seer":
            checked = [e for e in self.memory.important_events
                       if e.get("type") in ("seer_check_good", "seer_check_wolf")]
            if checked:
                lines.append("查验记录：")
                for c in checked[-3:]:
                    lines.append(f"  {c.get('target','?')}号 → {c.get('msg','?')}")

        if top_suspect:
            b = self.memory.player_beliefs.get(top_suspect)
            if b:
                lines.append(f"\n最怀疑：{top_suspect}号（狼人概率{int(b.wolf_probability*100)}%）")

        # Personality guidance
        if self.risk_preference > 0.7:
            lines.append("\n人格：你非常激进，即使证据不足也敢于直接指控。")
        elif self.risk_preference > 0.55:
            lines.append("\n人格：你独立判断，不被多数意见左右。")
        elif self.risk_preference > 0.35:
            lines.append("\n人格：你倾向于跟随多数意见。")
        else:
            lines.append("\n人格：你非常谨慎，只有把握很大时才公开怀疑别人。")

        lines.append("请以狼人杀玩家身份进行自然发言（2-4句话）。")
        return "\n".join(lines)

    # ---- Round End ----

    def end_round(self, engine):
        """Called at end of each day/night round to finalize memory."""
        self.memory.advance_round()
        self.memory.detect_contradictions(engine)

    # ---- Structured Output for API ----

    def get_structured_decision(self, action: dict) -> dict:
        """Produce standardized JSON output for display."""
        return {
            "analysis": {
                "suspicions": [
                    {
                        "player_id": pid,
                        "wolf_probability": round(b.wolf_probability, 2),
                        "confidence": round(b.confidence, 2),
                        "evidence": [e.description for e in b.evidence[-3:]],
                    }
                    for pid, b in sorted(
                        self.memory.player_beliefs.items(),
                        key=lambda x: -x[1].wolf_probability,
                    )[:5]
                ],
            },
            "decision": {
                "action": action.get("type", "pass"),
                "target": action.get("target"),
                "confidence": round(action.get("confidence", 0.5), 2),
            },
            "public_reason": action.get("reason", "") or action.get("speech", "")[:100],
        }
