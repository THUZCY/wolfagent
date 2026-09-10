# -*- coding: utf-8 -*-
"""Agent Memory: lightweight structured memory for WolfAgent.

Categories:
  1. known_facts      - objective facts (role reveals, deaths, seer checks)
  2. player_beliefs   - per-player wolf probability + evidence chain
  3. important_events - chronological key events
  4. voting_history   - own and observed votes
  5. my_previous_claims - own past statements
  6. contradictions   - auto-detected inconsistencies
"""
import json
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Evidence:
    """A single piece of evidence pointing toward (or against) a player being a wolf."""
    type: str
    description: str
    weight: float = 1.0
    day: int = 0
    source: Optional[int] = None

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "description": self.description,
            "weight": self.weight,
            "day": self.day,
        }


@dataclass
class PlayerBelief:
    """One agent's belief about one other player."""
    player_id: int
    wolf_probability: float = 0.25
    confidence: float = 0.5
    evidence: list = field(default_factory=list)
    last_updated_round: int = 0

    def to_dict(self) -> dict:
        return {
            "player_id": self.player_id,
            "wolf_probability": round(self.wolf_probability, 3),
            "confidence": round(self.confidence, 3),
            "evidence": [e.to_dict() for e in self.evidence[-10:]],
            "last_updated_round": self.last_updated_round,
        }
class AgentMemory:
    """Lightweight structured memory for each Agent.

    Categories:
      1. known_facts      - objective facts (role reveals, deaths, seer checks)
      2. player_beliefs   - per-player wolf probability + evidence chain
      3. important_events - chronological key events
      4. voting_history   - own and observed votes
      5. my_previous_claims - own past statements
      6. contradictions   - auto-detected inconsistencies
    """

    def __init__(self, player_number: int):
        self.player_number = player_number
        self.known_facts: list = []
        self.player_beliefs: dict = {}
        self.important_events: list = []
        self.voting_history: list = []
        self.my_previous_claims: list = []
        self.contradictions: list = []
        self.current_round: int = 0

    # ---- Known Facts ----

    def add_fact(self, fact: str, day: int, confidence: float = 1.0):
        """Add an objective fact if not already known."""
        if not any(f["fact"] == fact for f in self.known_facts):
            self.known_facts.append({
                "fact": fact, "day": day, "confidence": confidence,
            })

    # ---- Player Beliefs ----

    def get_belief(self, player_id: int) -> PlayerBelief:
        """Get or create belief for a player."""
        if player_id not in self.player_beliefs:
            self.player_beliefs[player_id] = PlayerBelief(
                player_id=player_id, wolf_probability=0.25, confidence=0.5,
            )
        return self.player_beliefs[player_id]

    def update_belief(
        self, player_id: int, wolf_probability_delta: float,
        evidence: Optional[Evidence] = None, confidence_delta: float = 0.05,
    ):
        """Update belief: previous + new evidence + delta = updated.

        Delta is clamped to [-0.15, 0.15] to prevent single-event overreaction.
        """
        # Skip dead players
        belief = self.get_belief(player_id)
        clamped = max(-0.15, min(0.15, wolf_probability_delta))
        belief.wolf_probability = max(0.0, min(1.0, belief.wolf_probability + clamped))
        belief.confidence = max(0.1, min(1.0, belief.confidence + confidence_delta))
        if evidence:
            evidence.day = self.current_round
            belief.evidence.append(evidence)
            if len(belief.evidence) > 20:
                belief.evidence = belief.evidence[-20:]
        belief.last_updated_round = self.current_round

    def set_belief_direct(self, player_id: int, wolf_probability: float, reason: str = ""):
        """Set absolute belief (e.g., seer check result)."""
        belief = self.get_belief(player_id)
        belief.wolf_probability = max(0.0, min(1.0, wolf_probability))
        belief.confidence = 0.95 if wolf_probability in (0.0, 1.0) else 0.7
        belief.last_updated_round = self.current_round
        if reason:
            belief.evidence.append(Evidence(
                type="seer_check" if wolf_probability == 0.0 else "confirmed",
                description=reason, weight=3.0, day=self.current_round,
            ))

    # ---- Events ----

    def add_event(self, event: dict):
        """Add an event to chronological memory."""
        self.important_events.append(event)
        if len(self.important_events) > 100:
            self.important_events = self.important_events[-100:]

    # ---- Voting History ----

    def add_vote(self, day: int, voter: int, target: int, was_me: bool = False):
        self.voting_history.append({
            "day": day, "voter": voter, "target": target, "was_me": was_me,
        })

    # ---- My Claims ----

    def add_claim(self, day: int, claim_type: str, content: str, target: Optional[int] = None):
        self.my_previous_claims.append({
            "day": day, "type": claim_type, "content": content, "target": target,
        })

    # ---- Contradiction Detection ----

    def detect_contradictions(self, engine=None):
        """Auto-detect behavioral contradictions."""
        new_contradictions = []

        # Own contradictions: claimed suspicion on X but voted Y
        for claim in self.my_previous_claims:
            if claim["type"] == "accuse" and claim["target"]:
                same_day_votes = [
                    v for v in self.voting_history
                    if v["day"] == claim["day"] and v["was_me"]
                ]
                for vote in same_day_votes:
                    if vote["target"] != claim["target"]:
                        entry = {
                            "player": self.player_number,
                            "day": claim["day"],
                            "description": (
                                f"Day {claim['day']}: claimed suspicion on Player {claim['target']}, "
                                f"voted Player {vote['target']}"
                            ),
                        }
                        if not any(c["description"] == entry["description"] for c in self.contradictions):
                            new_contradictions.append(entry)

        # Other players: vote patterns
        for pid in range(1, 8):
            if pid == self.player_number:
                continue
            player_votes = [v for v in self.voting_history if v["voter"] == pid]
            for i, v1 in enumerate(player_votes):
                for v2 in player_votes[i + 1:]:
                    if v2["day"] > v1["day"]:
                        # Vote flip without new info
                        pass  # kept simple for now

        self.contradictions.extend(new_contradictions)
        return new_contradictions

    # ---- Round ----

    def advance_round(self):
        self.current_round += 1

    # ---- LLM Summary (token-efficient) ----

    def get_summary_for_llm(self) -> str:
        """Compact text summary for LLM prompt context."""
        lines = []

        if self.known_facts:
            lines.append("Known Facts:")
            for f in self.known_facts[-6:]:
                lines.append(f"  - {f['fact']}")

        if self.player_beliefs:
            sorted_b = sorted(self.player_beliefs.items(), key=lambda x: -x[1].wolf_probability)
            lines.append("Suspicion Levels:")
            for pid, b in sorted_b[:6]:
                pct = int(b.wolf_probability * 100)
                bar = "=" * (pct // 10) + " " * (10 - pct // 10)
                lines.append(f"  Player {pid}: [{bar}] {pct}% (conf: {int(b.confidence*100)}%)")

        if self.important_events:
            lines.append("Key Events:")
            for e in self.important_events[-6:]:
                lines.append(f"  Day {e.get('day','?')}: {e.get('msg', e.get('detail', ''))}")

        if self.my_previous_claims:
            lines.append("My Past Claims:")
            for c in self.my_previous_claims[-3:]:
                lines.append(f"  Day {c['day']}: {c['content'][:80]}")

        if self.contradictions:
            lines.append("Contradictions Detected:")
            for c in self.contradictions[-3:]:
                lines.append(f"  {c['description']}")

        return "\n".join(lines) if lines else "(no memory yet)"

    # ---- Export ----

    def to_dict(self) -> dict:
        return {
            "known_facts": self.known_facts[-10:],
            "player_beliefs": {str(pid): b.to_dict() for pid, b in self.player_beliefs.items()},
            "important_events": self.important_events[-20:],
            "voting_history": self.voting_history[-20:],
            "my_previous_claims": self.my_previous_claims[-10:],
            "contradictions": self.contradictions[-10:],
            "current_round": self.current_round,
        }
