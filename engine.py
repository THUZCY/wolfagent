import random
from dataclasses import dataclass, field
from enum import Enum

class Phase(Enum):
    NIGHT_WEREWOLF = 'night_werewolf'
    NIGHT_SEER = 'night_seer'
    NIGHT_WITCH = 'night_witch'
    DAY_ANNOUNCE = 'day_announce'
    DAY_SPEECH = 'day_speech'
    DAY_VOTE = 'day_vote'
    GAME_OVER = 'game_over'

class Role(Enum):
    WEREWOLF = 'werewolf'
    SEER = 'seer'
    WITCH = 'witch'
    VILLAGER = 'villager'

ROLE_ZH = {Role.WEREWOLF: '狼人', Role.SEER: '预言家', Role.WITCH: '女巫', Role.VILLAGER: '村民'}

PHASE_ORDER = [
    Phase.NIGHT_WEREWOLF, Phase.NIGHT_SEER, Phase.NIGHT_WITCH,
    Phase.DAY_ANNOUNCE, Phase.DAY_SPEECH, Phase.DAY_VOTE,
]

@dataclass
class Player:
    number: int
    role: Role
    alive: bool = True
    personality: dict = field(default_factory=dict)

@dataclass
class GameEvent:
    day: int
    phase: str
    event_type: str
    source: int | None
    target: int | None
    detail: str
    public: bool = True

class GameEngine:
    def __init__(self, personalities: list):
        self.players: list[Player] = []
        self.day = 1
        self.phase = Phase.NIGHT_WEREWOLF
        self.phase_index = 0
        self.events: list[GameEvent] = []
        self.witch_has_save = True
        self.witch_has_poison = True
        self.night_kill_target: int | None = None
        self.night_poison_target: int | None = None
        self.witch_saved_tonight = False
        self.votes: dict[int, int] = {}
        self.voted_players: set[int] = set()
        self.game_over = False
        self.winner: str | None = None
        self._setup_game(personalities)

    def _setup_game(self, personalities):
        roles = [Role.WEREWOLF, Role.WEREWOLF, Role.SEER, Role.WITCH,
                 Role.VILLAGER, Role.VILLAGER, Role.VILLAGER]
        random.shuffle(roles)
        for i in range(7):
            self.players.append(Player(number=i+1, role=roles[i], personality=personalities[i] if i < len(personalities) else {}))

    def get_alive(self):
        return [p.number for p in self.players if p.alive]

    def get_player(self, num: int):
        return self.players[num - 1]

    def add_event(self, event: GameEvent):
        self.events.append(event)

    def set_night_kill(self, target: int):
        self.night_kill_target = target

    def set_night_poison(self, target: int):
        self.night_poison_target = target

    def get_public_events(self):
        return [e for e in self.events if e.public]

    def get_player_events(self, player_num: int):
        player = self.get_player(player_num)
        visible = []
        for e in self.events:
            if e.public:
                visible.append(e)
            elif e.phase.startswith('night'):
                # Night events: only visible to same-role players or the player themselves
                if e.source == player_num or e.target == player_num:
                    visible.append(e)
                elif player.role == Role.WEREWOLF and e.phase == 'night_werewolf' and e.event_type == 'wolf_kill':
                    visible.append(e)
        return visible

    def get_state_summary(self):
        return {
            'day': self.day,
            'phase': self.phase.value,
            'alive': self.get_alive(),
            'players': [
                {
                    'number': p.number,
                    'alive': p.alive,
                    'role': ROLE_ZH[p.role] if not p.alive else '???',
                    'personality': p.personality,
                }
                for p in self.players
            ],
            'game_over': self.game_over,
            'winner': self.winner,
        }

    def check_game_over(self):
        alive_wolves = sum(1 for p in self.players if p.alive and p.role == Role.WEREWOLF)
        alive_good = sum(1 for p in self.players if p.alive and p.role != Role.WEREWOLF)
        if alive_wolves == 0:
            self.game_over = True
            self.winner = 'villagers'
            self.phase = Phase.GAME_OVER
            return True
        if alive_wolves >= alive_good:
            self.game_over = True
            self.winner = 'werewolves'
            self.phase = Phase.GAME_OVER
            return True
        return False

    def advance_phase(self):
        if self.game_over:
            return
        self.phase_index = (self.phase_index + 1) % len(PHASE_ORDER)
        self.phase = PHASE_ORDER[self.phase_index]
        if self.phase == Phase.NIGHT_WEREWOLF:
            self.day += 1
            self.night_kill_target = None
            self.night_poison_target = None
            self.witch_saved_tonight = False
            self.votes = {}
            self.voted_players = set()

    def apply_night_results(self):
        deaths = []
        if self.night_kill_target and not self.witch_saved_tonight:
            deaths.append(self.night_kill_target)
        if self.night_poison_target:
            deaths.append(self.night_poison_target)
        for num in deaths:
            p = self.get_player(num)
            p.alive = False
        return deaths

    def apply_vote_result(self):
        if not self.votes:
            return None
        from collections import Counter
        counts = Counter(self.votes.values())
        if not counts:
            return None
        max_votes = max(counts.values())
        top = [t for t, c in counts.items() if c == max_votes]
        if len(top) == 1:
            target = top[0]
            self.get_player(target).alive = False
            return target
        return None
