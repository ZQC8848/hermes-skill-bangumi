# hermes-skill-bangumi

A [Hermes Agent](https://github.com/NousResearch/hermes-agent) skill tap with one skill:

**`bangumi-tracker`** — track airing anime with the public [Bangumi](https://bgm.tv) API
(`https://api.bgm.tv`, no key): what airs today, the next episode of a show, and a personal
watchlist. Python standard library only; output is JSON.

## Install

```bash
hermes skills tap add ZQC8848/hermes-skill-bangumi
hermes skills install ZQC8848/hermes-skill-bangumi/bangumi-tracker
```

Then ask your agent things like "what airs today?", "add Frieren to my list", or "when is the
next episode of 药屋少女的呢喃?".

## Commands (run by the agent through its terminal tool)

```bash
python ~/.hermes/skills/bangumi-tracker/scripts/bangumi.py today [--all]
python ~/.hermes/skills/bangumi-tracker/scripts/bangumi.py search <keyword>
python ~/.hermes/skills/bangumi-tracker/scripts/bangumi.py next <subject_id>
python ~/.hermes/skills/bangumi-tracker/scripts/bangumi.py watch list|add <id>|remove <id>
```

Dates are Japan broadcast dates. Titles from the API are treated as untrusted text (cleaned,
length-capped, never followed as instructions); summaries are not returned. The watchlist
(`$HERMES_HOME/bangumi/watchlist.json`, max 50) is the only file the skill writes; the
calendar is cached for 6 hours.

Built for USC CSCI 599 (Agentic AI), Assignment 3.

## License

MIT
