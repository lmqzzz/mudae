from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class LogLevel(str, Enum):
  INFO = 'info'
  SUCCESS = 'success'
  WARNING = 'warning'
  ERROR = 'error'


class DiscordEmbed(BaseModel):
  """Subset of Discord embed fields we care about."""

  model_config = ConfigDict(extra='ignore')

  title: str | None = Field(default=None)
  description: str | None = Field(default=None)
  url: str | None = Field(default=None)


class DiscordAuthor(BaseModel):
  model_config = ConfigDict(extra='ignore')

  id: str
  username: str | None = None
  global_name: str | None = None


class DiscordEmoji(BaseModel):
  """Subset of emoji metadata used for component interactions."""

  model_config = ConfigDict(extra='ignore')

  id: str | None = None
  name: str | None = None
  animated: bool | None = None


class DiscordComponent(BaseModel):
  """Discord message component (buttons, action rows, etc.)."""

  model_config = ConfigDict(extra='ignore')

  type: int
  custom_id: str | None = None
  emoji: DiscordEmoji | None = None
  label: str | None = None
  style: int | None = None
  components: tuple['DiscordComponent', ...] = Field(default_factory=tuple)


class DiscordMessage(BaseModel):
  """Typed representation of a Discord channel message."""

  model_config = ConfigDict(extra='ignore')

  id: str
  content: str
  author: DiscordAuthor
  timestamp: datetime
  embeds: tuple[DiscordEmbed, ...] = Field(default_factory=tuple)
  components: tuple[DiscordComponent, ...] = Field(default_factory=tuple)
  flags: int | None = Field(default=None)


class KakeraReactionMode(str, Enum):
  """User-selectable strategy for kakera button reactions."""

  P_ONLY = 'p_only'
  PREFERRED = 'preferred'


class RollPlan(BaseModel):
  """Configuration for a rolling session."""

  model_config = ConfigDict(extra='forbid')

  us_uses: int = Field(default=0, ge=0, description='Number of $us boosts to perform')
  roll_count: int = Field(default=0, ge=0, description='Number of $wa rolls to send')
  use_slash_commands: bool = Field(
    default=False,
    description='Use slash command invocation for the roll action instead of text commands',
  )
  kakera_reaction_mode: KakeraReactionMode = Field(
    default=KakeraReactionMode.PREFERRED,
    description='How the service reacts to kakera buttons while rolling via slash commands',
  )


class RollSummary(BaseModel):
  """Aggregate result captured from a rolling session."""

  model_config = ConfigDict(extra='forbid')

  plan: RollPlan
  total_messages_sent: int
  cards_detected: int
  last_card_title: str | None = None
  duration_seconds: float = Field(default=0.0, ge=0.0)


class LogEntry(BaseModel):
  """Runtime log entry displayed inside the curses dashboard."""

  model_config = ConfigDict(extra='forbid')

  level: LogLevel = Field(default=LogLevel.INFO)
  message: str
  created_at: datetime
