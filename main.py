import json, random
from fastapi import FastAPI, Request, Form, Query
from fastapi.responses import HTMLResponse, JSONResponse
from engine import GameEngine, GameEvent, Phase, ROLE_ZH
from agent import Agent
from llm import MockProvider, OpenAIProvider, DeepSeekProvider

app = FastAPI(title="WolfAgent")
games = {}

@app.get("/", response_class=HTMLResponse)
async def index():
    with open("templates/setup.html", encoding="utf-8") as f:
        return HTMLResponse(f.read())

@app.get("/game", response_class=HTMLResponse)
async def game_page(gid: str = ""):
    with open("templates/game.html", encoding="utf-8") as f:
        html = f.read()
    if gid:
        html = html.replace("var gid = null;", "var gid = '" + gid + "';")
    return HTMLResponse(html)

@app.post("/api/game/create")
async def create_game(
    provider: str = Form(...),
    apikey: str = Form(...),
    personalities: str = Form("[]"),
):
    gid = "game_" + str(random.randint(1000, 9999))
    try:
        pers = json.loads(personalities)
    except:
        pers = [{"aggression": 0.5, "talkativeness": 0.5, "caution": 0.5} for _ in range(7)]

    if provider == "mock" or not apikey or not apikey.strip():
        llm = MockProvider()
    elif provider == "deepseek":
        llm = DeepSeekProvider(apikey.strip())
    else:
        llm = OpenAIProvider(apikey.strip())

    engine = GameEngine(pers)
    agents = []
    for p in engine.players:
        agents.append(Agent(p.number, p.role, p.personality, llm))

    games[gid] = {"engine": engine, "agents": agents, "log": [], "finished": False}
    return JSONResponse({"status": "ok", "game_id": gid})

@app.get("/api/game/{gid}/state")
async def game_state(gid: str, player_num: int = Query(0)):
    if gid not in games:
        return JSONResponse({"error": "Game not found"}, 404)
    g = games[gid]
    engine = g["engine"]
    agents = g["agents"]

    state = engine.get_state_summary()
    state["log"] = g["log"][-100:]
    state["finished"] = g["finished"]

    if player_num and 1 <= player_num <= 7:
        agent = agents[player_num - 1]
        role_text = ROLE_ZH[agent.role]
        if not engine.get_player(player_num).alive:
            role_text += " (已死亡)"
        state["agent_view"] = {
            "player": player_num,
            "role": role_text,
            "belief": {str(k): round(v, 2) for k, v in agent.belief.items()},
            "reasoning": agent.reasoning[-10:],
            "personality": agent.personality,
        }
    return JSONResponse(state)

@app.post("/api/game/{gid}/step")
async def game_step(gid: str):
    if gid not in games:
        return JSONResponse({"error": "Game not found"}, 404)
    g = games[gid]
    engine = g["engine"]
    agents = g["agents"]
    phase = engine.phase

    if engine.game_over:
        return JSONResponse({"finished": True, "winner": engine.winner, "phase": "game_over"})

    result = {"phase": phase.value, "day": engine.day, "alive": engine.get_alive(), "events": [], "finished": False}

    if phase == Phase.NIGHT_WEREWOLF:
        wolves = [a for a in agents if a.role.value == "werewolf" and engine.get_player(a.num).alive]
        if wolves:
            leader = wolves[0]
            for a in [wa for wa in agents if wa.role.value == "werewolf"]:
                a.observe(engine.get_player_events(a.num), engine)
            action = leader.decide(engine)
            if action["type"] == "kill" and action["target"]:
                engine.set_night_kill(action["target"])
                ev = GameEvent(engine.day, "night_werewolf", "werewolf_kill", leader.num, action["target"], "狼人选定了猎杀目标")
                engine.add_event(ev)
                g["log"].append({"type": "night", "msg": "狼人选定了猎杀目标"})
                result["events"].append({"type": "night_action", "detail": "狼人选定了猎杀目标"})

    elif phase == Phase.NIGHT_SEER:
        seers = [a for a in agents if a.role.value == "seer" and engine.get_player(a.num).alive]
        if seers:
            seer = seers[0]
            seer.observe(engine.get_player_events(seer.num), engine)
            action = seer.decide(engine)
            if action["type"] == "check" and action["target"]:
                target = action["target"]
                target_role = engine.get_player(target).role
                is_good = target_role.value != "werewolf"
                result_text = "好人" if is_good else "狼人"
                ev_type = "seer_check_good" if is_good else "seer_check_wolf"
                ev = GameEvent(engine.day, "night_seer", ev_type, seer.num, target,
                              "预言家查验" + str(target) + "号：" + result_text)
                engine.add_event(ev)
                g["log"].append({"type": "night", "msg": "预言家查验了" + str(target) + "号：" + result_text})
                result["events"].append({"type": "night_action", "detail": "预言家查验了" + str(target) + "号：" + result_text})

    elif phase == Phase.NIGHT_WITCH:
        witches = [a for a in agents if a.role.value == "witch" and engine.get_player(a.num).alive]
        if witches:
            witch = witches[0]
            witch.observe(engine.get_player_events(witch.num), engine)
            action = witch.decide(engine)
            if engine.witch_has_save and action["type"] == "save" and action["target"]:
                engine.witch_saved_tonight = True
                engine.witch_has_save = False
                ev = GameEvent(engine.day, "night_witch", "witch_save", witch.num, action["target"], "女巫使用了解药")
                engine.add_event(ev)
                g["log"].append({"type": "night", "msg": "女巫使用了解药，救了" + str(action["target"]) + "号"})
                result["events"].append({"type": "night_action", "detail": "女巫使用了解药"})
            elif engine.witch_has_poison and action["type"] == "poison" and action["target"]:
                engine.set_night_poison(action["target"])
                engine.witch_has_poison = False
                ev = GameEvent(engine.day, "night_witch", "witch_poison", witch.num, action["target"], "女巫使用了毒药")
                engine.add_event(ev)
                g["log"].append({"type": "night", "msg": "女巫使用了毒药，毒杀" + str(action["target"]) + "号"})
                result["events"].append({"type": "night_action", "detail": "女巫使用了毒药"})
            else:
                g["log"].append({"type": "night", "msg": "女巫没有使用药水"})

    elif phase == Phase.DAY_ANNOUNCE:
        deaths = engine.apply_night_results()
        if deaths:
            for d in deaths:
                player = engine.get_player(d)
                g["log"].append({"type": "death", "player": d,
                    "msg": str(d) + "号死亡，身份：" + ROLE_ZH[player.role]})
                result["events"].append({"type": "death", "player": d, "role": ROLE_ZH[player.role]})
                ev = GameEvent(engine.day, "day_announce", "death", None, d, str(d) + "号死亡")
                engine.add_event(ev)
        else:
            g["log"].append({"type": "info", "msg": "昨晚是平安夜，没有人死亡"})
            result["events"].append({"type": "peace"})

        if engine.check_game_over():
            g["finished"] = True
            winner_text = "村民阵营胜利！" if engine.winner == "villagers" else "狼人阵营胜利！"
            g["log"].append({"type": "gameover", "msg": winner_text})
            result["finished"] = True
            result["winner"] = engine.winner

    elif phase == Phase.DAY_SPEECH:
        alive_agents = [a for a in agents if engine.get_player(a.num).alive]
        speakers_today = sum(1 for l in g["log"]
                            if l.get("type") == "speech" and l.get("day") == engine.day)
        if speakers_today < len(alive_agents):
            speaker = alive_agents[speakers_today]
            speaker.observe(engine.get_player_events(speaker.num), engine)
            action = speaker.decide(engine)
            speech = action.get("speech", "") or "..."
            g["log"].append({
                "type": "speech", "day": engine.day, "player": speaker.num,
                "msg": speech,
            })
            result["events"].append({"type": "speech", "player": speaker.num, "speech": speech})

    elif phase == Phase.DAY_VOTE:
        alive_agents = [a for a in agents if engine.get_player(a.num).alive]
        for agent in alive_agents:
            agent.observe(engine.get_player_events(agent.num), engine)
            action = agent.decide(engine)
            if action["type"] == "vote" and action["target"]:
                engine.votes[agent.num] = action["target"]
                g["log"].append({
                    "type": "vote", "day": engine.day, "player": agent.num, "target": action["target"],
                    "msg": str(agent.num) + "号 → " + str(action["target"]) + "号",
                })
                result["events"].append({"type": "vote", "player": agent.num, "target": action["target"]})

        eliminated = engine.apply_vote_result()
        if eliminated:
            player = engine.get_player(eliminated)
            g["log"].append({"type": "death", "player": eliminated,
                "msg": str(eliminated) + "号被投票放逐，身份：" + ROLE_ZH[player.role]})
            result["events"].append({"type": "death", "player": eliminated, "role": ROLE_ZH[player.role]})
            ev = GameEvent(engine.day, "day_vote", "vote_eliminate", None, eliminated,
                          str(eliminated) + "号被投票放逐")
            engine.add_event(ev)
        else:
            g["log"].append({"type": "info", "msg": "平票，无人被放逐"})
            result["events"].append({"type": "no_elimination"})

        if engine.check_game_over():
            g["finished"] = True
            winner_text = "村民阵营胜利！" if engine.winner == "villagers" else "狼人阵营胜利！"
            g["log"].append({"type": "gameover", "msg": winner_text})
            result["finished"] = True
            result["winner"] = engine.winner

    # Advance phase
    if not g["finished"]:
        if phase == Phase.DAY_SPEECH:
            speakers_today_now = sum(1 for l in g["log"]
                                    if l.get("type") == "speech" and l.get("day") == engine.day)
            alive_count = len([a for a in agents if engine.get_player(a.num).alive])
            if speakers_today_now >= alive_count:
                engine.advance_phase()
        else:
            engine.advance_phase()

    result["next_phase"] = engine.phase.value
    result["alive"] = engine.get_alive()
    result["finished"] = g["finished"]
    return JSONResponse(result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get('PORT', 8000)))

