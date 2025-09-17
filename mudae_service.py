from __future__ import annotations

import time
from datetime import UTC, datetime

from discord_client import DiscordHTTPClient
from models import DiscordMessage, RollPlan, RollSummary
from settings import AppSettings

MAX_US_BATCH_SIZE = 20


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
    roll_delay = self._settings.tuning.roll_delay_seconds
    roll_text_command = f'{command_prefix}wa'

    def sleep_between_actions() -> None:
      if roll_delay > 0:
        time.sleep(roll_delay)

    def perform_roll() -> None:
      nonlocal total_messages, cards_detected, last_card_title
      if plan.use_slash_commands:
        self._client.trigger_slash_command()
      else:
        self._client.send_message(roll_text_command)
      total_messages += 1

      if plan.wait_for_cards:
        card = self._await_card(timeout_seconds=15.0)
        if card:
          cards_detected += 1
          last_card_title = next(
            (embed.title for embed in card.embeds if embed.title),
            last_card_title,
          )

    for _ in range(plan.roll_count):
      perform_roll()
      sleep_between_actions()

    us_remaining = plan.us_uses
    while us_remaining > 0:
      batch_size = min(MAX_US_BATCH_SIZE, us_remaining)
      boost_command = f'{command_prefix}us {batch_size}'
      self._client.send_message(boost_command)
      total_messages += 1
      us_remaining -= batch_size
      sleep_between_actions()

      for _ in range(batch_size):
        perform_roll()
        sleep_between_actions()

    self._client.send_message('Progress finished.')
    total_messages += 1

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
