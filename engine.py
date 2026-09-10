import random
from dataclasses import dataclass, field
from enum import Enum
from collections import Counter

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



@dataclass
class PlayerScore:
    player: int
    role: str
    alive: bool
    team_win: int
    vote_accuracy: int
    key_actions: int
    survival: int
    total: int
    grade: str
    highlights: list
    summary: str


def generate_recap(engine, log):
    """Generate end-of-game recap with player scores."""
    wolves = {p.number for p in engine.players if p.role == Role.WEREWOLF}
    good_team = {p.number for p in engine.players if p.role != Role.WEREWOLF}
    winner_is_good = engine.winner == "villagers"

    vote_history = {}
    for entry in log:
        if entry.get("type") == "vote":
            p = entry["player"]
            t = entry["target"]
            d = entry.get("day", 1)
            if p not in vote_history:
                vote_history[p] = []
            vote_history[p].append((d, t))

    death_day = {}
    for entry in log:
        if entry.get("type") == "death":
            dead_player = entry["player"]
            d = entry.get("day", engine.day)
            death_day[dead_player] = d

    total_days = engine.day

    wolf_kills = {}
    seer_checks = {}
    witch_saves = {}
    witch_poisons = {}

    for ev in engine.events:
        if ev.event_type == "werewolf_kill" and ev.source:
            wolf_kills[ev.source] = wolf_kills.get(ev.source, 0) + 1
        elif ev.event_type in ("seer_check_good", "seer_check_wolf") and ev.source:
            if ev.source not in seer_checks:
                seer_checks[ev.source] = []
            is_wolf = (ev.event_type == "seer_check_wolf")
            seer_checks[ev.source].append((ev.target, is_wolf))
        elif ev.event_type == "witch_save" and ev.source:
            if ev.source not in witch_saves:
                witch_saves[ev.source] = []
            witch_saves[ev.source].append(ev.target)
        elif ev.event_type == "witch_poison" and ev.source:
            if ev.source not in witch_poisons:
                witch_poisons[ev.source] = []
            witch_poisons[ev.source].append(ev.target)

    scores = []
    for p in engine.players:
        pid = p.number
        role_name = ROLE_ZH[p.role]
        is_wolf = p.role == Role.WEREWOLF
        on_winning_team = (is_wolf and not winner_is_good) or (not is_wolf and winner_is_good)
        highlights = []

        # Team Win (0-20)
        team_win = 20 if on_winning_team else 0

        # Vote Accuracy (0-30)
        votes = vote_history.get(pid, [])
        correct_votes = 0
        for (_day, target) in votes:
            target_is_wolf = target in wolves
            if is_wolf:
                if not target_is_wolf:
                    correct_votes += 1
            else:
                if target_is_wolf:
                    correct_votes += 1
        vote_accuracy = int(30 * correct_votes / max(len(votes), 1))

        # Key Actions (0-30)
        key_actions = 0
        if is_wolf:
            kills = wolf_kills.get(pid, 0)
            key_actions = min(30, kills * 10)
            if kills > 0:
                highlights.append(u"参与猎杀 %d 次" % kills)
        elif p.role == Role.SEER:
            checks = seer_checks.get(pid, [])
            correct = sum(1 for (_, c) in checks if c)
            key_actions = min(30, correct * 15 + max(0, len(checks) - correct) * 5)
            if correct > 0:
                highlights.append(u"查验出 %d 个狼人" % correct)
            if len(checks) > 0:
                highlights.append(u"查验了 %d 名玩家" % len(checks))
        elif p.role == Role.WITCH:
            saves = witch_saves.get(pid, [])
            poisons = witch_poisons.get(pid, [])
            good_saves = sum(1 for t in saves if t in good_team)
            wolf_poisons = sum(1 for t in poisons if t in wolves)
            bad_poisons = sum(1 for t in poisons if t in good_team)
            key_actions = min(30, good_saves * 15 + wolf_poisons * 20)
            key_actions = max(0, key_actions - bad_poisons * 15)
            if good_saves > 0:
                highlights.append(u"用解药救了 %d 个好人" % good_saves)
            if wolf_poisons > 0:
                highlights.append(u"用毒药毒杀 %d 个狼人" % wolf_poisons)
            if bad_poisons > 0:
                highlights.append(u"误毒了 %d 个好人" % bad_poisons)
        else:
            # Villager
            if correct_votes > 0:
                key_actions = min(30, correct_votes * 10)
                highlights.append(u"正确投票 %d 次" % correct_votes)
            else:
                key_actions = 5

        if len(votes) >= 2:
            highlights.append(u"参与投票 %d 轮" % len(votes))

        # Survival (0-20)
        survival_day = death_day.get(pid, total_days)
        survived = p.alive
        if survived:
            survival = 20
            highlights.append(u"存活到游戏结束")
        else:
            survival = max(0, int(20 * survival_day / max(total_days, 1)))

        total = team_win + vote_accuracy + key_actions + survival
        total = max(0, min(100, total))

        if total >= 90:
            grade = "S"
        elif total >= 80:
            grade = "A"
        elif total >= 65:
            grade = "B"
        elif total >= 50:
            grade = "C"
        else:
            grade = "D"

        grade_desc = {"S": u"MVP表现", "A": u"表现优秀", "B": u"表现良好", "C": u"表现一般", "D": u"表现欠佳"}
        summary = u"%s · %s · 总分 %d/100" % (role_name, grade_desc.get(grade, ""), total)

        scores.append(PlayerScore(
            player=pid,
            role=role_name,
            alive=p.alive,
            team_win=team_win,
            vote_accuracy=vote_accuracy,
            key_actions=key_actions,
            survival=survival,
            total=total,
            grade=grade,
            highlights=highlights,
            summary=summary,
        ))

    scores.sort(key=lambda s: -s.total)

    winner_text = u"村民阵营" if winner_is_good else u"狼人阵营"
    mvp = scores[0]
    avg_score = sum(s.total for s in scores) / len(scores)

    overall = (
        u"🏆 %s获得胜利！\n" % winner_text +
        u"🌟 MVP：%d号（%s，%d分，%s级）\n" % (mvp.player, mvp.role, mvp.total, mvp.grade) +
        u"📊 全场平均分：%.1f/100\n" % avg_score +
        u"⏱️ 游戏共进行了 %d 天" % total_days
    )

    return {
        "scores": [{
            "player": s.player,
            "role": s.role,
            "alive": s.alive,
            "team_win": s.team_win,
            "vote_accuracy": s.vote_accuracy,
            "key_actions": s.key_actions,
            "survival": s.survival,
            "total": s.total,
            "grade": s.grade,
            "highlights": s.highlights,
            "summary": s.summary,
        } for s in scores],
        "overall": overall,
        "mvp": mvp.player,
        "avg_score": round(avg_score, 1),
        "total_days": total_days,
    }

