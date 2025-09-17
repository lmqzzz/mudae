from __future__ import annotations

import curses

from discord_client import DiscordHTTPClient
from mudae_service import MudaeService
from settings import load_settings
from ui import CursesApplication


def main() -> None:
  settings = load_settings()
  with DiscordHTTPClient(settings.discord) as client:
    service = MudaeService(client, settings)
    app = CursesApplication(service, settings)
    curses.wrapper(app.run)


if __name__ == '__main__':
  main()
