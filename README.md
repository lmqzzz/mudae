# Mudae Roll Orchestrator

A curses-based control panel that automates rolling against the
[Mudae](https://top.gg/bot/mudae) Discord bot. The app drives Discord's HTTP API
directly, letting you queue batches of `$wa` rolls and `$us` boosts while
monitoring for cards that drop in the channel.

## Features

- Terminal dashboard for configuring roll sessions, triggering runs, and viewing
  logs in real time
- Typed settings backed by Pydantic with `.env` configuration and sane defaults
- Resilient Discord HTTP client with optional slash-command invocation via
  `discum`
- Embed polling to count cards pulled from Mudae and report the most recent drop
- Rate-limit friendly pacing controls (polling interval and per-roll delay are
  configurable)

## Prerequisites

- Python 3.11 or newer (uses `datetime.UTC` and Pydantic v2)
- A Discord token (bot token recommended). **Never share user tokens—using them
  may violate Discord's ToS.**
- IDs for the Discord guild, target text channel, and the Mudae bot user
- Mudae invited to the guild with the permissions required for text or slash
  commands
- Terminal with curses support (macOS/Linux native, Windows via WSL or
  `pip install windows-curses`)
- Optional: [`discum`](https://github.com/Merubokkusu/Discord-S.C.U.M) if you
  want to drive slash commands instead of plain text commands

## Installation

1. Clone this repository.
2. Create and activate a virtual environment:
   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows use: .venv\Scripts\activate
   ```
3. Install dependencies:
   ```bash
   pip install --upgrade pip
   pip install httpx pydantic python-dotenv discum
   ```
   - `discum` is optional; omit it if you only plan to use text commands.

## Configuration

Create a `.env` file in the project root (use the provided variable list as a
template):

```bash
DISCORD_TOKEN=your_bot_or_user_token
DISCORD_CHANNEL_ID=123456789012345678
DISCORD_GUILD_ID=123456789012345678
MUDAE_USER_ID=432610292342587392
DISCORD_COMMAND_PREFIX=$
SLASH_ROLL_COMMAND=wa
ROLL_BATCH_SIZE=10
POLL_INTERVAL_SECONDS=1.5
MESSAGE_HISTORY_LIMIT=50
ROLL_DELAY_SECONDS=1.0
```

- **Required**: `DISCORD_TOKEN`, `DISCORD_CHANNEL_ID`, and `DISCORD_GUILD_ID`
  must be set to valid values.
- **Optional**: The other variables override defaults baked into `settings.py`.
- `MUDAE_USER_ID` defaults to the global Mudae bot ID. Only change it if you are
  working with a local clone or test bot.
- `SLASH_ROLL_COMMAND` should match the space-separated path shown in Discord
  (e.g., `mudae wa`).
- `ROLL_BATCH_SIZE` seeds the UI for quick adjustments.

Run the loader standalone to confirm the configuration parses correctly:

```bash
python -c "from settings import load_settings; print(load_settings())"
```

## Running the App

After configuration, start the dashboard:

```bash
python main.py
```

The program opens a fullscreen curses UI. It will automatically sync with recent
Mudae card messages so prior rolls are not double-counted.

## Using the Dashboard

- **Navigation**: `Tab`, `Shift+Tab`, `↑`, `↓` move focus between fields.
- **Edit numeric fields** (`Roll remaining`, `Roll count`): press `Enter` or
  type a number; confirm with `Enter`, cancel with `Esc`.
- **Increment/decrement**: `+` and `-` adjust the focused numeric field by one.
- **Toggle slash/text mode**: press `Space` (or `Enter`) while
  `Use slash commands` is focused.
- **Start a session**: press `r` (or `R`). The service will:
  1. Send the configured number of plain rolls.
  2. Batch `$us` boosts in chunks of up to 20, sending a roll after each boost.
  3. Finish with a "Progress finished." message for bookkeeping.
- **Stop/quit**: press `q` to exit the UI. Sessions run to completion once
  started.

The Event Log (bottom of the screen) captures status, warnings, and errors with
timestamps. A summary panel records the most recent session: total messages
sent, cards detected, last card title, and duration.

## Architecture Overview

- `main.py`: entry point; loads settings, wires the HTTP client, service, and
  curses UI.
- `settings.py`: strongly typed configuration loader (Pydantic). Handles `.env`
  parsing and defaults.
- `discord_client.py`: low-level HTTP client for channel messages, history
  traversal, and slash command payloads.
- `mudae_service.py`: orchestrates roll plans, batching logic, card detection,
  and summarization.
- `ui.py`: curses dashboard for interactive control, state management, and
  background session threads.
- `models.py`: shared Pydantic models for Discord payloads, roll plans,
  summaries, and log entries.

## Slash Command Support

- Enabling slash commands requires `discum` to be installed and the bot invited
  with the `applications.commands` scope.
- The service caches command definitions per session; the first slash roll may
  take longer while definitions are fetched.
- If slash command discovery fails, the UI will log an error and continue to
  allow text-based rolls.

## Safety, Rate Limiting, and Etiquette

- The app throttles roll cadence using `ROLL_DELAY_SECONDS`. Increase the delay
  if you encounter HTTP 429 responses.
- `MESSAGE_HISTORY_LIMIT` bounds how many recent messages are scanned when
  looking for new embeds; raise it if other users are very active.
- Respect server rules. Automated rolling is best done in dedicated channels
  with explicit permission.

## Troubleshooting

- **401/403 responses**: double-check the token, channel ID, and that the
  bot/user has access to the target channel.
- **No cards detected**: verify the channel contains Mudae embed messages and
  adjust `MESSAGE_HISTORY_LIMIT` if the channel is busy.
- **Slash command errors**: ensure `discum` is installed and
  `SLASH_ROLL_COMMAND` matches the command displayed in Discord.
- **Windows users**: install `windows-curses` before running the app or use WSL
  for the full curses experience.

## Development Notes

- The project uses type hints throughout—run `pyright` or `mypy` if you want
  static checking during development.
- Add unit tests for business logic (e.g., roll batching) with `pytest`; the
  repository currently ships without tests.
- Contributions should keep code formatted with standard `ruff`/`black` settings
  (not enforced, but recommended).

## Disclaimer

This project drives the Discord API directly. Use it responsibly and at your own
risk; neither the authors nor maintainers are responsible for account actions
resulting from misuse.
