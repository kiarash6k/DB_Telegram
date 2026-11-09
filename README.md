# DB_Telegram

An **unofficial** Telegram bot for Deutsche Bahn departures and connections.
Not affiliated with Deutsche Bahn.

## Commands

| Command | Example |
|---|---|
| `/departures <station>` | `/departures Aachen Hbf` |
| `/route <from> > <to>` | `/route Aachen Hbf > Köln Hbf` |

Shows delays (`+5`), platform changes (⚠️) and cancellations.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env      # add the token from @BotFather
python -m db_bot
```

## How it works

Telegram message → `db_bot/bot.py` → `db_bot/api.py` (community
[`transport.rest`](https://transport.rest) API, no key needed) →
`db_bot/formatting.py` → reply.
The API base URL can be changed via `DB_API_BASE_URL`. That service is free
but has rate limits and no uptime guarantee.

## Tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Roadmap

- Saved places (`/save home Aachen Hbf`)
- `/watch` a connection and get delay/cancellation alerts

## License

MIT
