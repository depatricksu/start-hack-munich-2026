# START Hack Munich 2026

Key info collected from the event Discord on Sat 21 Nov 2026.

- **Where:** Audimax, TUM Main Campus (U2 Theresienstraße)
- **Format:** 24 h · ~250 hackers · ~65 teams · 5 challenges
- **Guidebook (single source of truth):** https://munichstart.notion.site/Guidebook-START-HackMunich-2026-4167680686328172b9dadd06d9cf0fb1 (briefs, judging criteria, slides, prizes on the *Challenges* page)
- **Hack League app:** teams, challenge ranking, full briefs

## Deadlines

| When | What |
|---|---|
| Sat 12:45 | Teams lock (unassigned people get placed) |
| Sat 13:05 | Captains rank top 3 challenges in the app (last save counts) |
| Sat 13:10 | Challenge allocation shown in the app |
| Sat 13:15 | Hacking starts → go to your challenge's Discord channel |
| Sat 16:00–17:00 | Recruiting Hour with partners |
| Sat 19:00 / 00:00 | Dinner / midnight snack |
| **Sun 12:45** | **Project submission closes** |
| Sun 15:30 | Closing ceremony |
| Sun 23:59 | Redeem OpenAI vouchers |

## Our track: 5U AI · "Build the Forwarder"

- **Room:** 1180 · **Discord:** #5u-ai · booth on site for questions
- **Task:** be an AI freight forwarder. One mailbox, a new request every ~6 minutes, in any language. The agent must:
  1. read every mail (any language),
  2. price every request,
  3. answer it,
  4. escalate the judgement calls to a human.
- The industry "changes by the hour" → expect rule/price updates during the hack.
- **Pitch:** every team pitches to 5U at the end for the top 3 prizes.
- **Prize:** fly a real plane yourself ✈️ + €300 / €200 / €100 from START Munich for the top 3.
- **Material:** 5U AI pitch slides (guidebook → Challenges) and deep-dive PDF in #5u-ai. Full brief in the Hack League app.

### Agent plan (draft)
- Loop: poll mailbox → classify + extract (origin, destination, cargo, weight/volume, dates, incoterms) → price → draft reply → send or escalate.
- Escalate when: missing data, unusual cargo (dangerous goods, oversize), low confidence, price outside normal range.
- Demo UI: live inbox on the left, agent reasoning + action on the right, human review queue.
- Models: Claude Sonnet for decisions/replies, Haiku for classification/translation (high volume).

## Other challenges (for reference)

| Partner | Room | Notes |
|---|---|---|
| **QuantCo** – "Claim to Fame" | 1200 | Live insurance-pricing game. 70 % leaderboard, 30 % approach + presentation. |
| **Feyer** – "Faster Physics" | 0602 | Speed up a JAX optical simulator. Repo: https://github.com/feyerlabs/start-hack-munich-2026 |
| **revel8** – "Agentic Social Engineer" | 0606 | Agent wins over AI twins via revel8's API. |

## Free compute

### OpenAI
$50 ChatGPT/Codex + $20 API, emailed after check-in (subject: "Your START Hack Munich vouchers"). Check spam. Links are single-use; redeem by **Sun 23:59**. Missing? DM Sivaram (START Munich) on Discord.

### AMD Radeon Cloud
48 GB VRAM, 16 cores, 55 GB RAM per GPU; ROCm, PyTorch, vLLM preinstalled. 48 free GPU-hours per person.

1. Sign in at https://radeon-global.anruicloud.com/ with **Login with Email** (not the AMD Developer Program login).
2. Fill in https://tally.so/r/2jKBye with the same email. Credits land at the next full hour (click your name → 48 credits + Hackathon pool).
3. **Add your SSH key before launching** (`ssh-keygen -t ed25519`, then Settings → New SSH key). Keys added later require destroy + relaunch.
4. Launch: Customize → Notebook · 1 GPU · vLLM latest · pool **Hackathon** · persistent `/workspace` · auto-delete 1 day.

Gotchas: running instances burn credits (no pause, destroy when done) · only `/workspace` survives · don't `pip install torch` · one instance per account · "waiting for GPU" → check Hackathon pool.
No GPU needed? **Token Factory** tab = OpenAI-compatible API (key starts `rc-`), no GPU credits used.

## Logistics
- Bring: laptop + charger, phone charger, sleeping bag/blanket, swimwear + towel (ice plunge).
- Food, drinks and caffeine provided.
- FlixBus voucher: mail s.nalliboyana@startmunich.de with your name and departure city.
- Questions: any organiser/volunteer, or #help-desk.
