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

## Challenges

| Partner | Room | Notes |
|---|---|---|
| **QuantCo** – "Claim to Fame" | 1200 | Score: 70 % leaderboard, 30 % approach + presentation. **Do not put the challenge or your code in a public repo.** Deep-dive PDF in #quantco. |
| **Lio** – "Keep the Line Running" | 1100 | Supplier portal: https://start-hack-portal-cxh3crbdaef2f8gt.westeurope-01.azurewebsites.net/ (data published at challenge start). Brief, judging, deep-dive PDFs in #lio. |
| **Feyer** | 0602 | Repo: https://github.com/feyerlabs/start-hack-munich-2026 |
| **revel8** – "Agentic Social Engineer" | 0606 | Challenge + scoring rubric PDFs in #revel8. Per-team Persona API key after allocation. |
| **5U AI** | 1180 | Every team pitches at the end for the top 3 prizes. Slides in #5u-ai; booth for questions. |

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
