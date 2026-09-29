# Kezohar Torah Agent — Project Brief for Claude Code

## 1. Goal
Build a fast, local, zero-cost Jewish Torah agent for the Kezohar HaRakia app.
It answers ONLY about: halacha, minhagim, brachot, zmanim, tefillot, fasts, Shabbat, chagim, Jewish calendar.
Everything else is politely refused in Hebrew.

## 2. Non-negotiable constraints
- Zero ongoing cost. No paid APIs (OpenAI, Anthropic, Gemini, etc.), no credits, no trials, no credit card.
- All inference runs on hardware the user owns (Mac + NAS).
- The model never issues rulings on its own. Every halachic answer must cite a source returned by our search. No source → answer "אין לי מקור לכך" and show the closest sources, if any.
- No invented references, quotes, or poskim.
- Psak order: Maran (Shulchan Aruch) and Sephardi / Edot HaMizrach poskim first, then Ashkenazi (Rema, Mishnah Berurah). When they differ, show both, Sephardi first.
- Answers in Hebrew.

## 3. Speed targets (hard requirements)
- First visible content (sources): < 1 second.
- Full answer: <= 5 seconds on the Mac.
- Zmanim / calendar questions: < 1 second, answered by code, NO LLM call.
- Answers are short: up to 5 sentences + sources. "Expand" is a separate request.
- Stream by sentence, not character by character.
- Model stays loaded (no cold start). Cache repeated questions.
- Any model that fails these targets in the benchmark is rejected, even if its Hebrew is better.

## 4. Hardware (verified)
### Mac (dev machine + LLM host)
- MacBook Pro 14" M4 Pro, 48 GB unified memory, macOS 27.0.
- LM Studio with OpenAI-compatible server on port 1234, "Serve on Local Network" enabled.
- LLM base URL is configurable via `.env` → `LLM_BASE_URL=http://<MAC_LAN_IP>:1234/v1`. Never hardcode.
- Installed candidate models (use these first, do not download others without asking):
  - `qwen/qwen3.5-35b-a3b` (MoE, lmstudio-community) — run with reasoning/thinking OFF.
  - `glm-4.7-flash` (MoE, lmstudio-community)
  - `dictalm-3.0-nemotron-12b` (dicta-il)
  - `dictalm-3.0-24b-thinking` (unsloth, GGUF Q4_K_S) — baseline for Hebrew quality only.

### NAS (24/7 server)
- UGREEN DXP8800 Plus, Intel Core i5-1235U (no usable GPU for LLMs), 125 GB RAM (~111 GB available).
- SSH: `ssh nizoza369@192.168.68.83` (key auth already configured, static IP).
- Docker installed. User was added to the `docker` group. Verify `docker ps` works without sudo; if not, stop and ask the user.
- Project root on NAS: `/volume2/kezohar-agent` (NVMe, RAID 0 — fast but NOT redundant).

### Existing containers — DO NOT TOUCH
consulting-knowledge-server (app/worker/scheduler/db), jellyfin, memos, cryptofolio, metube (+mariadb), portainer, immich (server/postgres/machine_learning/redis).
Ports in use: 2283, 3000, 5230, 7280, 8000, 8081, 8096, 9090, 9444.
Do not reuse their databases (including immich_postgres with vector extensions). Create our own.

## 5. Safety rules for you (Claude Code)
- Work only inside `~/kezohar-agent` on the Mac and `/volume2/kezohar-agent` on the NAS.
- Never stop, modify, update, or restart existing containers, networks, or volumes.
- Use our own Docker network `kezohar-net` and ports in range 8700–8799 only.
- Ask before: installing system packages, using sudo, downloading anything > 1 GB, opening any port to the internet.
- Never ask for, store, or print passwords or tokens.
- Commit to git after every working step. Push to a private GitHub repo (ask the user to create it). Data on RAID 0 must be rebuildable from the repo + scripts.

## 6. Architecture
```
iPhone app (Capacitor) ──HTTP──► agent-api (NAS :8710)
                                   │
                ┌──────────────────┼───────────────────────┐
                ▼                  ▼                       ▼
        fast-path router     search service           LLM client
        (zmanim/calendar     (hybrid BM25 + dense,    (OpenAI-compatible,
         via code, cache)     Qdrant on NAS)           Mac LM Studio)
                                   │
                            Torah text store
                     (local copy of Sefaria texts)
```
- Code lives in git on the Mac; deploy to the NAS with rsync + `docker compose` over SSH.
- The LLM is a replaceable component behind one interface. Switching models = one `.env` change.
- If the Mac is offline: agent-api returns sources only ("מצב חיפוש"), clearly labeled. Zmanim/calendar keep working.
- Remote access (later phase): self-hosted WireGuard on the NAS. No paid tunnels.

### Components
- **agent-api**: small service (Python FastAPI or Node — choose one and justify briefly). Endpoints: `POST /ask` (streams: sources event first, then answer sentences), `GET /health`.
- **Fast-path router**: rule/keyword based Hebrew intent detection BEFORE any LLM call. Handles zmanim, parasha, chagim, fasts, Rosh Chodesh, omer. Default location Netivot; accept a location parameter.
- **Calendar/zmanim**: `@hebcal/core` (or an equivalent open-source library). Must be Israel mode. Cross-check a few dates against a trusted source and report.
- **Search**: Qdrant (container, internal network only) + BGE-M3 embeddings (runs on NAS CPU at query time; bulk indexing may run on the Mac). Add a BM25 keyword index. Normalize Hebrew: strip niqqud and taamim, unify final letters for matching. Measure query latency on the NAS; target < 300 ms.
- **Agent loop**: retrieval happens in code first, then ONE LLM call to write the answer from the retrieved passages. Use tool calling only when needed (e.g., open a specific seif). Minimize round trips.

## 7. Data (phase 1 scope)
Source: Sefaria (free API / public export). Store a local copy on the NAS. Record the license of every text in `data/licenses.json`. Skip texts whose license does not allow this use and report them.
Priority order:
1. Shulchan Aruch (all four parts, Hebrew).
2. Sephardi works available on Sefaria — check each: Ben Ish Chai, Kaf HaChaim, others. Report what exists.
3. Kitzur Shulchan Aruch.
4. Mishnah Berurah, Rema.
5. Siddur (Edot HaMizrach nusach if available, then Ashkenaz).
Do NOT use Yalkut Yosef, Chazon Ovadia, or any copyrighted work without a legal free source.
Chunk by seif. Every chunk keeps its exact reference (book, siman, seif) for citation.

## 8. Phases — stop and report after each phase
### Phase 0 — Audit + model benchmark (START HERE, build nothing else)
1. Verify SSH, Docker without sudo, free space on `/volume2`, LM Studio server reachable from the NAS (`curl $LLM_BASE_URL/models` from the NAS).
2. Write `bench/run.py` (or .ts) that sends each question in `bench/questions.md` to each candidate model through LM Studio and measures: time to first token, tokens/sec, total time, answer length, tool-call correctness (give each model a dummy `search_halacha` tool), memory used.
3. Load one model at a time. Reasoning/thinking OFF where supported.
4. Output a table in `bench/results.md`. Recommend one primary model. Do not grade halachic correctness yourself — mark answers for the user to review.

### Phase 1 — Data ingest (Sefaria → NAS), license report.
### Phase 2 — Search service + Qdrant + latency test.
### Phase 3 — Zmanim/calendar fast path.
### Phase 4 — Agent loop + answer policy + streaming.
### Phase 5 — API contract for the iPhone app; minimal test page.

## 9. Benchmark questions (bench/questions.md)
Behavior tags: [fast] = must bypass LLM, [src] = must cite, [both] = Sephardi + Ashkenazi, [refuse] = out of scope, [nosrc] = should admit no source.
1. מה מברכים על אורז? [src]
2. מותר לאכול דג עם חלב? [src][both]
3. מתי שקיעה היום בנתיבות? [fast]
4. מתי צום גדליה השנה? [fast]
5. שכחתי יעלה ויבוא בשחרית של ראש חודש, מה הדין? [src]
6. עד מתי אפשר לקדש לבנה? [src]
7. מותר לבשל ביום טוב בשביל מחר? [src]
8. כמה זמן מחכים בין בשר לחלב? [src][both]
9. אכלתי ושכחתי לברך ברכת המזון, עד מתי אפשר לברך? [src]
10. אומרים הלל בברכה בראש חודש? [src][both]
11. מה סדר הדלקת נרות חנוכה? [src][both]
12. מתי סוף זמן קריאת שמע מחר? [fast]
13. איזו פרשה השבוע? [fast]
14. מה מברכים על שוקולד? [src]
15. מותר לטלטל טלפון בשבת? [src]
16. שכחתי לספור ספירת העומר יום אחד, מה עושים? [src][both]
17. מה מזג האוויר מחר? [refuse]
18. תכתוב לי שיר אהבה. [refuse]
19. מה דעת הרב קוק על מיקרוגל בשבת? [nosrc]
20. מתי אומרים תפילת הדרך? [src]

## 10. Later (not now)
- User's own folder `shas full` on the NAS may contain Talmud texts — inspect format in a later phase.
- Hebrew-specific reranker if search quality needs it (measure latency first).
- Prefer MLX builds of the chosen model if they are faster than GGUF on this Mac.
