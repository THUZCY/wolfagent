# -*- coding: utf-8 -*-
"""Benchmark system for WolfAgent - run N games and collect statistics."""
import json
import time
import random
import asyncio
from dataclasses import dataclass, field
from typing import Optional
from engine import GameEngine, Phase, ROLE_ZH, Role
from agent import Agent
from llm import MockProvider


@dataclass
class GameResult:
    """Single game result for benchmark tracking."""
    game_id: str
    winner: str
    total_days: int
    players: list[dict] = field(default_factory=list)
    mvp: Optional[int] = None
    avg_score: float = 0.0
    agent_models: str = "mock"
    completed: bool = False
    error: Optional[str] = None
    wolf_id_accuracy: float = 0.0
    vote_accuracy: float = 0.0


class BenchmarkRunner:
    """Run N games sequentially and collect statistics."""

    def __init__(self):
        self.results: list[GameResult] = []
        self._running = False
        self._progress = {"current": 0, "total": 0}

    def run_games(self, n: int, provider: str = "mock", apikey: str = "") -> list[GameResult]:
        """Run N games sequentially with the given provider.

        Args:
            n: Number of games to run.
            provider: 'mock', 'openai', 'deepseek', 'groq', 'gemini', 'ollama'.
            apikey: API key (ignored for mock/ollama).
        """
        self.results = []
        self._running = True
        self._progress = {"current": 0, "total": n}

        for i in range(n):
            if not self._running:
                break
            self._progress["current"] = i + 1
            result = self._run_single_game(i + 1, provider, apikey)
            self.results.append(result)
            # Brief delay between games
            time.sleep(0.5)

        self._running = False
        return self.results

    def _run_single_game(self, game_num: int, provider: str, apikey: str) -> GameResult:
        """Run one complete game."""
        gid = f"bench_{game_num}_{random.randint(100, 999)}"
        personalities = [
            {"aggression": round(random.random() * 0.8 + 0.1, 1),
             "talkativeness": round(random.random() * 0.8 + 0.1, 1),
             "caution": round(random.random() * 0.8 + 0.1, 1),
             "risk_preference": round(random.random(), 1)}
            for _ in range(7)
        ]

        try:
            from llm import OpenAIProvider, DeepSeekProvider, GroqProvider, GeminiProvider, OllamaProvider
            if provider == "mock" or not apikey or not apikey.strip():
                llm = MockProvider()
            elif provider == "deepseek":
                llm = DeepSeekProvider(apikey.strip())
            elif provider == "groq":
                llm = GroqProvider(apikey.strip())
            elif provider == "gemini":
                llm = GeminiProvider(apikey.strip())
            elif provider == "ollama":
                llm = OllamaProvider()
            else:
                llm = OpenAIProvider(apikey.strip())
        except Exception:
            llm = MockProvider()

        engine = GameEngine(personalities)
        agents = [Agent(p.number, p.role, p.personality, llm) for p in engine.players]
        log = []

        max_steps = 200  # safety limit
        for _ in range(max_steps):
            if engine.game_over:
                break

            phase = engine.phase
            if phase == Phase.NIGHT_WEREWOLF:
                wolves = [a for a in agents if a.role.value == "werewolf" and engine.get_player(a.num).alive]
                if wolves:
                    for a in [wa for wa in agents if wa.role.value == "werewolf"]:
                        a.observe(engine.get_player_events(a.num), engine)
                    action = wolves[0].decide(engine)
                    if action["type"] == "kill" and action["target"]:
                        engine.set_night_kill(action["target"])
                        log.append({"type": "night", "msg": "狼人选定了猎杀目标"})
                engine.advance_phase()

            elif phase == Phase.NIGHT_SEER:
                seer = [a for a in agents if a.role.value == "seer" and engine.get_player(a.num).alive]
                if seer:
                    seer[0].observe(engine.get_player_events(seer[0].num), engine)
                    action = seer[0].decide(engine)
                    if action["type"] == "check" and action["target"]:
                        target_role = engine.get_player(action["target"]).role
                        from engine import GameEvent
                        if target_role.value == "werewolf":
                            ev = GameEvent(engine.day, "night_seer", "seer_check_wolf", seer[0].num, action["target"],
                                          f"预言家查验{action['target']}号为狼人")
                        else:
                            ev = GameEvent(engine.day, "night_seer", "seer_check_good", seer[0].num, action["target"],
                                          f"预言家查验{action['target']}号为好人")
                        engine.add_event(ev)
                engine.advance_phase()

            elif phase == Phase.NIGHT_WITCH:
                witch = [a for a in agents if a.role.value == "witch" and engine.get_player(a.num).alive]
                if witch:
                    witch[0].observe(engine.get_player_events(witch[0].num), engine)
                    action = witch[0].decide(engine)
                    if action["type"] == "save" and action["target"]:
                        engine.witch_saved_tonight = True
                    elif action["type"] == "poison" and action["target"]:
                        engine.set_night_poison(action["target"])
                engine.advance_phase()

            elif phase == Phase.DAY_ANNOUNCE:
                deaths = engine.apply_night_results()
                for d in deaths:
                    p = engine.get_player(d)
                    log.append({"type": "death", "player": d, "msg": f"{d}号死亡，身份：{ROLE_ZH[p.role]}"})
                if not deaths:
                    log.append({"type": "info", "msg": "昨晚是平安夜，没有人死亡"})
                if engine.check_game_over():
                    break
                engine.advance_phase()

            elif phase == Phase.DAY_SPEECH:
                alive_agents = [a for a in agents if engine.get_player(a.num).alive]
                speakers_today = sum(1 for l in log if l.get("type") == "speech" and l.get("day") == engine.day)
                if speakers_today < len(alive_agents):
                    speaker = alive_agents[speakers_today]
                    speaker.observe(engine.get_player_events(speaker.num), engine)
                    action = speaker.decide(engine)
                    speech = action.get("speech", "") or "..."
                    log.append({"type": "speech", "day": engine.day, "player": speaker.num, "msg": speech})
                else:
                    engine.advance_phase()

            elif phase == Phase.DAY_VOTE:
                alive_agents = [a for a in agents if engine.get_player(a.num).alive]
                for agent in alive_agents:
                    agent.observe(engine.get_player_events(agent.num), engine)
                    action = agent.decide(engine)
                    if action["type"] == "vote" and action["target"]:
                        engine.votes[agent.num] = action["target"]
                        log.append({"type": "vote", "day": engine.day, "player": agent.num, "target": action["target"],
                                    "msg": f"{agent.num}号 -> {action['target']}号"})
                eliminated = engine.apply_vote_result()
                if eliminated:
                    p = engine.get_player(eliminated)
                    log.append({"type": "death", "player": eliminated, "msg": f"{eliminated}号被投票放逐，身份：{ROLE_ZH[p.role]}"})
                else:
                    log.append({"type": "info", "msg": "平票，无人被放逐"})
                if engine.check_game_over():
                    break
                engine.advance_phase()

        # Collect player data
        players_data = []
        for p in engine.players:
            a = agents[p.number - 1]
            players_data.append({
                "number": p.number,
                "role": ROLE_ZH[p.role],
                "alive": p.alive,
                "beliefs": {str(pid): round(b.wolf_probability, 2) for pid, b in a.memory.player_beliefs.items()},
            })

        from engine import generate_recap
        recap = generate_recap(engine, log)

            # Calculate wolf ID accuracy: how often agents correctly voted/accused wolves
        wolves_set = {p.number for p in engine.players if p.role.value == "werewolf"}
        total_votes = 0
        correct_votes = 0
        total_belief_predictions = 0
        correct_belief_predictions = 0
        for a in agents:
            for pid, b in a.memory.player_beliefs.items():
                is_wolf = (pid in wolves_set)
                total_belief_predictions += 1
                if (b.wolf_probability > 0.5 and is_wolf) or (b.wolf_probability <= 0.5 and not is_wolf):
                    correct_belief_predictions += 1
        wolf_id_accuracy = correct_belief_predictions / max(total_belief_predictions, 1)
        for entry in log:
            if entry.get("type") == "vote":
                total_votes += 1
                target = entry.get("target")
                if target and ((target in wolves_set) != (engine.winner == "werewolves")):
                    correct_votes += 1
        vote_accuracy = correct_votes / max(total_votes, 1)

        return GameResult(
            game_id=gid,
            winner=engine.winner or "unknown",
            total_days=engine.day,
            players=players_data,
            mvp=recap.get("mvp"),
            avg_score=recap.get("avg_score", 0),
            agent_models=provider,
            completed=True,
            wolf_id_accuracy=round(wolf_id_accuracy, 3),
            vote_accuracy=round(vote_accuracy, 3),
        )

    def get_statistics(self) -> dict:
        """Aggregate statistics from completed games."""
        completed = [r for r in self.results if r.completed]
        if not completed:
            return {"error": "No completed games", "total_games": len(self.results)}

        n = len(completed)
        werewolf_wins = sum(1 for r in completed if r.winner == "werewolves")
        villager_wins = sum(1 for r in completed if r.winner == "villagers")

        # Win rates
        werewolf_win_rate = werewolf_wins / n if n > 0 else 0
        villager_win_rate = villager_wins / n if n > 0 else 0

        # Average game length
        avg_days = sum(r.total_days for r in completed) / n if n > 0 else 0

        # Survival rates by role
        role_survival = {}
        role_counts = {}
        for r in completed:
            for p in r.players:
                role = p["role"]
                if role not in role_survival:
                    role_survival[role] = 0
                    role_counts[role] = 0
                if p["alive"]:
                    role_survival[role] += 1
                role_counts[role] += 1

        survival_rates = {
            role: round(role_survival[role] / max(role_counts[role], 1), 2)
            for role in role_survival
        }

        # Average scores
        all_scores = [r.avg_score for r in completed]
        avg_score = sum(all_scores) / n if n > 0 else 0

        # MVP distribution
        mvp_counts = {}
        for r in completed:
            if r.mvp:
                mvp_counts[r.mvp] = mvp_counts.get(r.mvp, 0) + 1

        # Wolf identification accuracy
        avg_wolf_id = sum(r.wolf_id_accuracy for r in completed) / n if n > 0 else 0
        # Vote accuracy across all games
        avg_vote_acc = sum(r.vote_accuracy for r in completed) / n if n > 0 else 0

        return {
            "total_games": n,
            "werewolf_win_rate": round(werewolf_win_rate, 3),
            "villager_win_rate": round(villager_win_rate, 3),
            "average_game_length_days": round(avg_days, 1),
            "average_score": round(avg_score, 1),
            "wolf_identification_accuracy": round(avg_wolf_id, 3),
            "vote_accuracy": round(avg_vote_acc, 3),
            "survival_rates_by_role": survival_rates,
            "mvp_distribution": mvp_counts,
            "results": [
                {
                    "game_id": r.game_id,
                    "winner": r.winner,
                    "days": r.total_days,
                    "mvp": r.mvp,
                    "avg_score": r.avg_score,
                }
                for r in completed
            ],
        }

    def stop(self):
        self._running = False

    @property
    def progress(self) -> dict:
        return dict(self._progress)