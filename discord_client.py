from __future__ import annotations

import random
import string
import time
from collections.abc import Iterable, Sequence
from copy import deepcopy
from datetime import datetime
from typing import Any

import httpx

try:
  from discum.utils.slash import SlashCommander
except ImportError:  # pragma: no cover - optional dependency
  SlashCommander = None  # type: ignore[assignment]

from models import DiscordMessage
from settings import DiscordSettings


class DiscordHTTPClient:
  """Thin wrapper around the Discord REST API using httpx."""

  _API_BASE = 'https://discord.com/api/v10'
  _GLOBAL_COMMANDS_TEMPLATE = '/applications/{application_id}/commands'
  _GUILD_COMMANDS_TEMPLATE = '/applications/{application_id}/guilds/{guild_id}/commands'
  _INTERACTIONS_PATH = '/interactions'

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
    self._slash_command_definitions: list[dict[str, Any]] | None = None
    self._slash_command_cache: dict[tuple[str, ...], dict[str, Any]] = {}

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

  def trigger_slash_command(self, command_path: Sequence[str] | None = None) -> None:
    path = tuple(command_path) if command_path is not None else self._settings.slash_roll_command_path
    if not path:
      raise ValueError('Slash command path cannot be empty.')
    command_data = deepcopy(self._resolve_slash_command_data(path))
    payload = {
      'type': 2,
      'application_id': self._settings.mudae_user_id,
      'guild_id': self._settings.guild_id,
      'channel_id': self._settings.channel_id,
      'data': command_data,
      'nonce': self._generate_nonce(),
      'session_id': self._generate_session_id(),
    }
    response = self._client.post(self._INTERACTIONS_PATH, json=payload)
    response.raise_for_status()

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

  def _resolve_slash_command_data(self, command_path: tuple[str, ...]) -> dict[str, Any]:
    if SlashCommander is None:
      raise RuntimeError(
        'Slash command support requires the discum package. Install discum or disable slash commands.',
      )
    cached = self._slash_command_cache.get(command_path)
    if cached is not None:
      return cached

    definitions = self._fetch_slash_command_definitions()
    commander = SlashCommander(definitions, application_id=self._settings.mudae_user_id)
    try:
      command_data = commander.get(list(command_path))
    except ValueError as exc:  # pragma: no cover - defensive branch
      joined = ' '.join(command_path)
      message = (
        f'Slash command "{joined}" was not found for application {self._settings.mudae_user_id}. '
        'Ensure the command path is correct and the bot has been invited with slash permissions.'
      )
      raise RuntimeError(message) from exc

    self._slash_command_cache[command_path] = command_data
    return command_data

  def _fetch_slash_command_definitions(self) -> list[dict[str, Any]]:
    if self._slash_command_definitions is None:
      commands_by_id: dict[str, dict[str, Any]] = {}
      endpoints = [
        self._GLOBAL_COMMANDS_TEMPLATE.format(application_id=self._settings.mudae_user_id),
        self._GUILD_COMMANDS_TEMPLATE.format(
          application_id=self._settings.mudae_user_id,
          guild_id=self._settings.guild_id,
        ),
      ]
      for endpoint in endpoints:
        response = self._client.get(endpoint)
        if response.status_code != httpx.codes.OK:
          continue
        for item in response.json():
          commands_by_id[item['id']] = item
      self._slash_command_definitions = list(commands_by_id.values())
    return self._slash_command_definitions

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

  @staticmethod
  def _generate_session_id(length: int = 32) -> str:
    alphabet = string.ascii_letters + string.digits
    return ''.join(random.choice(alphabet) for _ in range(length))

  @staticmethod
  def _generate_nonce() -> str:
    unix_millis = int(time.time()) * 1000
    return str((unix_millis - 1420070400000) * 4194304)
