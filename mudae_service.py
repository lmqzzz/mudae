from __future__ import annotations

import time
from datetime import UTC, datetime

from discord_client import DiscordHTTPClient
from models import DiscordMessage, RollPlan, RollSummary
from settings import AppSettings


class MudaeService:
  """High-level orchestration for sending commands to the Mudae bot."""

  def __init__(self, client: DiscordHTTPClient, settings: AppSettings) -> None:
    self._client = client
    self._settings = settings
    self._last_seen_card: datetime | None = None

  def execute_roll_plan(self, plan: RollPlan) -> RollSummary:
    start = time.perf_counter()
    total_messages = 0
    cards_detected = 0
    last_card_title: str | None = None
    command_prefix = self._settings.discord.command_prefix

    if plan.us_uses > 0:
      command = f'{command_prefix}us {plan.us_uses}'
      self._client.send_message(command)
      total_messages += 1
      time.sleep(self._settings.tuning.roll_delay_seconds)

    for _ in range(plan.roll_count):
      roll_command = f'{command_prefix}wa'
      self._client.send_message(roll_command)
      total_messages += 1

      if plan.wait_for_cards:
        card = self._await_card(timeout_seconds=15.0)
        if card:
          cards_detected += 1
          last_card_title = next(
            (embed.title for embed in card.embeds if embed.title),
            last_card_title,
          )
      time.sleep(self._settings.tuning.roll_delay_seconds)

    duration = time.perf_counter() - start
    return RollSummary(
      plan=plan,
      total_messages_sent=total_messages,
      cards_detected=cards_detected,
      last_card_title=last_card_title,
      duration_seconds=duration,
    )

  def _await_card(self, *, timeout_seconds: float) -> DiscordMessage | None:
    deadline = time.monotonic() + timeout_seconds
    poll_interval = self._settings.tuning.poll_interval_seconds
    limit = self._settings.tuning.message_history_limit
    while time.monotonic() < deadline:
      messages = self._client.poll_for_mudae_embeds(
        since=self._last_seen_card,
        limit=limit,
      )
      if messages:
        latest = max(messages, key=lambda message: message.timestamp)
        self._last_seen_card = latest.timestamp
        return latest
      time.sleep(poll_interval)
    return None

  def sync_state(self) -> None:
    """Refresh the last seen card to avoid counting historical embeds."""
    messages = self._client.poll_for_mudae_embeds(limit=5)
    if messages:
      latest = max(messages, key=lambda message: message.timestamp)
      self._last_seen_card = latest.timestamp
    else:
      self._last_seen_card = datetime.min.replace(tzinfo=UTC)
