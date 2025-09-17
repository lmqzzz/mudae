from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

import httpx

from models import DiscordMessage
from settings import DiscordSettings


class DiscordHTTPClient:
  """Thin wrapper around the Discord REST API using httpx."""

  _API_BASE = 'https://discord.com/api/v10'

  def __init__(self, settings: DiscordSettings, *, timeout_seconds: float = 10.0) -> None:
    self._settings = settings
    authorization_header = self._resolve_authorization_header(settings.token)
    self._client = httpx.Client(
      base_url=self._API_BASE,
      timeout=timeout_seconds,
      headers={
        'Authorization': authorization_header,
        'Content-Type': 'application/json',
        'User-Agent': 'mudae-refactor/1.0 (+https://github.com/)',
      },
    )
    self._channel_path = f'/channels/{settings.channel_id}'

  def close(self) -> None:
    self._client.close()

  def __enter__(self) -> DiscordHTTPClient:
    return self

  def __exit__(self, exc_type, exc, exc_tb) -> None:  # type: ignore[override]
    self.close()

  def send_message(self, content: str) -> DiscordMessage:
    payload = {'content': content, 'tts': False}
    response = self._client.post(f'{self._channel_path}/messages', json=payload)
    response.raise_for_status()
    return DiscordMessage.model_validate(response.json())

  def fetch_recent_messages(self, limit: int) -> tuple[DiscordMessage, ...]:
    response = self._client.get(
      f'{self._channel_path}/messages',
      params={'limit': str(limit)},
    )
    response.raise_for_status()
    data = response.json()
    messages = tuple(DiscordMessage.model_validate(item) for item in data)
    return messages

  def poll_for_mudae_embeds(
    self,
    *,
    since: datetime | None = None,
    limit: int = 50,
  ) -> tuple[DiscordMessage, ...]:
    """Return messages from the Mudae bot that include embeds."""
    messages = self.fetch_recent_messages(limit)
    filtered: list[DiscordMessage] = []
    for message in messages:
      if message.author.id != self._settings.mudae_user_id:
        continue
      if not message.embeds:
        continue
      if since and message.timestamp <= since:
        continue
      filtered.append(message)
    return tuple(filtered)

  def iter_message_history(self, *, page_size: int = 100) -> Iterable[DiscordMessage]:
    """Simple generator for traversing channel history in chunks."""
    after_id: str | None = None
    while True:
      params: dict[str, str] = {'limit': str(page_size)}
      if after_id:
        params['after'] = after_id
      response = self._client.get(f'{self._channel_path}/messages', params=params)
      response.raise_for_status()
      batch = response.json()
      if not batch:
        break
      messages = tuple(DiscordMessage.model_validate(item) for item in batch)
      for message in messages:
        yield message
      after_id = messages[-1].id

  @staticmethod
  def _resolve_authorization_header(token: str) -> str:
    """Normalize the authorization header for both bot and user tokens."""
    trimmed = token.strip()
    if trimmed.lower().startswith('bot ') or trimmed.lower().startswith('bearer '):
      return trimmed
    # User tokens contain two dots; discord bot tokens typically do not.
    if trimmed.count('.') == 2:
      return trimmed
    return f'Bot {trimmed}'
