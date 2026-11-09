# DB_Telegram

An **unofficial** Telegram bot for Deutsche Bahn departures and connections.
Not affiliated with Deutsche Bahn.

## Commands

| Command | Example |
|---|---|
| `/departures <station>` | `/departures Aachen Hbf` |
| `/route <from> > <to>` | `/route Aachen Hbf > Köln Hbf` |
| `/board <station>` | `/board Köln Hbf` (widget, see below) |

Shows delays (`+5`), platform changes (⚠️) and cancellations.

## Departure-board widget

`/board <station>` sends an interactive HTML widget (Telegram Bot API 10.4):
DB-style card with colour-coded line badges, delay chips (yellow → red by
severity), platform chips, ⚠️-style highlighting of platform changes,
cancelled trains, light/dark mode, and a **Refresh** button that asks the bot
for fresh data without sending a new message.

- Widgets currently work **only in private chats** with the bot, and can't be
  forwarded.
- If the widget can't be sent, the bot falls back to the plain-text board.
- Widget data is limited to 1 KB, so the board shows as many rows as fit.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env      # add the token from @BotFather
python -m db_bot
```

## How it works

Telegram message → `db_bot/bot.py` → `db_bot/api.py` →
[Transitous](https://transitous.org) (free, open MOTIS 2 transit API, no key) →
`db_bot/formatting.py` → reply.

Transitous serves German long-distance and regional rail with live delays,
platforms and cancellations. Time zone is Europe/Berlin.
Data sources: <https://transitous.org/sources/>.

> The old community DB endpoint (`v6.db.transport.rest`) no longer exists,
> because DB shut down the API behind it. That is why this bot uses Transitous.

Transitous' usage policy asks for an open-source, non-commercial project that
identifies itself with a `User-Agent`. This bot does both. The base URL can be
changed with `TRANSITOUS_BASE_URL` (or `DB_API_BASE_URL`) if you self-host MOTIS.

## Troubleshooting

- **"service isn't responding"**: check `curl -A "test (you@example.com)" "https://api.transitous.org/api/v1/geocode?text=Aachen&type=STOP"`.
  If that fails, your network blocks or can't resolve `api.transitous.org`.
- **Station not found**: use a fuller name, e.g. `Köln Hbf`.

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
