from __future__ import annotations

import time
from datetime import UTC, datetime

from discord_client import DiscordHTTPClient
from models import DiscordComponent, DiscordMessage, KakeraReactionMode, RollPlan, RollSummary
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
    target_kakera = self._resolve_kakera_targets(plan.kakera_reaction_mode)
    kakera_energy_depleted = False

    def sleep_between_actions() -> None:
      if roll_delay > 0:
        time.sleep(roll_delay)

    def perform_roll() -> None:
      nonlocal total_messages, cards_detected, last_card_title, kakera_energy_depleted
      if plan.use_slash_commands:
        self._client.trigger_slash_command()
      else:
        self._client.send_message(roll_text_command)
      total_messages += 1

      card = self._await_card(timeout_seconds=15.0)
      if card:
        cards_detected += 1
        last_card_title = next(
          (embed.title for embed in card.embeds if embed.title),
          last_card_title,
        )
        if plan.use_slash_commands and target_kakera and not kakera_energy_depleted:
          kakera_energy_depleted = self._handle_kakera_reactions(card, target_kakera)

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

    self._client.send_message('Finished rolling by Mudae - https://github.com/lmqzzz/mudae')
    total_messages += 1

    duration = time.perf_counter() - start
    return RollSummary(
      plan=plan,
      total_messages_sent=total_messages,
      cards_detected=cards_detected,
      last_card_title=last_card_title,
      duration_seconds=duration,
    )

  def _resolve_kakera_targets(self, mode: KakeraReactionMode) -> tuple[str, ...]:
    if mode is KakeraReactionMode.P_ONLY:
      return ('kakeraP',)
    # Preserve user-defined order while removing duplicates.
    seen: set[str] = set()
    ordered: list[str] = []
    for name in self._settings.kakera.preferred_types:
      if name and name not in seen:
        seen.add(name)
        ordered.append(name)
    return tuple(ordered)

  def _handle_kakera_reactions(self, card: DiscordMessage, targets: tuple[str, ...]) -> bool:
    component = self._select_kakera_component(card.components, targets)
    if component is None:
      return False
    try:
      self._client.click_component(card, component)
    except Exception:  # noqa: BLE001
      return False
    return self._await_kakera_feedback(since=card.timestamp)

  def _select_kakera_component(
    self,
    components: tuple[DiscordComponent, ...],
    targets: tuple[str, ...],
  ) -> DiscordComponent | None:
    buttons = list(self._iter_button_components(components))
    if not buttons:
      return None
    for target in targets:
      for button in buttons:
        emoji = button.emoji
        if emoji and emoji.name == target:
          return button
    return None

  def _await_kakera_feedback(self, *, since: datetime, timeout_seconds: float = 6.0) -> bool:
    deadline = time.monotonic() + timeout_seconds
    poll_interval = min(0.6, self._settings.tuning.poll_interval_seconds)
    while time.monotonic() < deadline:
      messages = self._client.fetch_recent_messages(limit=5)
      for message in messages:
        if message.author.id != self._settings.discord.mudae_user_id:
          continue
        if message.timestamp <= since:
          continue
        content = message.content.lower()
        if self._is_energy_depleted_message(content):
          return True
        if self._is_successful_reaction_message(content):
          return False
      time.sleep(poll_interval)
    return False

  @staticmethod
  def _iter_button_components(components: tuple[DiscordComponent, ...]):
    for component in components:
      if component.type == 1 and component.components:
        yield from MudaeService._iter_button_components(component.components)
      elif component.type == 2:
        yield component

  @staticmethod
  def _is_energy_depleted_message(content: str) -> bool:
    lowered = content.lower()
    energy_phrases = (
      'out of energy',
      "don't have enough energy",
      'no energy left',
    )
    return any(phrase in lowered for phrase in energy_phrases)

  @staticmethod
  def _is_successful_reaction_message(content: str) -> bool:
    lowered = content.lower()
    return 'react' in lowered and 'success' in lowered

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
