# WolfAgent —— AI 狼人杀模拟器

一个由大语言模型驱动的狼人杀对战平台。7 名 AI 玩家各自拥有独立的人格、记忆与推理链，在狼人、预言家、女巫、村民的经典角色框架下，展开日夜交替的推理博弈。你可以通过 Web 界面自由配置 AI 性格参数，选择 OpenAI 或 DeepSeek 作为推理后端，然后坐下来观看一场充满谎言、推理与反转的 AI 对决。

## 快速开始

```bash
pip install -r requirements.txt
python main.py
```

浏览器打开 `http://localhost:8000`，配置角色并开始游戏。

## 技术栈

- **后端**: FastAPI + Uvicorn
- **AI 引擎**: OpenAI / DeepSeek（支持 Mock 模式离线测试）
- **Agent 架构**: 记忆层 + 信念层 + 决策层，支持自定义人格参数（攻击性、话痨度、谨慎度）
- **前端**: 原生 HTML/CSS/JS，深色主题

---

*WolfAgent — An LLM-powered Werewolf game platform where 7 AI agents, each with its own personality, memory, and reasoning chain, battle it out across the classic roles of Werewolf, Seer, Witch, and Villager. Configure personality traits via the web UI, choose between OpenAI or DeepSeek as the reasoning backend, then sit back and watch a thrilling contest of deception, deduction, and dramatic turnarounds — all played by AI.*
