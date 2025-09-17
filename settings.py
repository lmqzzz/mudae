from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field

DEFAULT_KAKERA_TYPES: tuple[str, ...] = (
  'kakeraP',
  'kakeraO',
  'kakeraR',
  'kakeraW',
  'kakeraL',
)


class DiscordSettings(BaseModel):
  """Runtime configuration for Discord API access."""

  model_config = ConfigDict(extra='forbid')

  token: str = Field(..., description='Bot token for authenticating with Discord')
  channel_id: str = Field(..., description='Target channel ID where commands are sent')
  guild_id: str = Field(..., description='Guild (server) ID for slash-command context')
  mudae_user_id: str = Field(..., description='Discord user ID of the Mudae bot')
  command_prefix: str = Field(
    default='$',
    description='Prefix used for text commands when not relying on slash commands',
  )
  slash_roll_command: str = Field(
    default='wa',
    description='Slash command path (space-separated) used to perform rolls',
  )

  @property
  def slash_roll_command_path(self) -> tuple[str, ...]:
    return tuple(part for part in self.slash_roll_command.strip().split() if part)


class RuntimeTuning(BaseModel):
  """User-tunable runtime parameters."""

  model_config = ConfigDict(extra='forbid')

  roll_batch_size: int = Field(
    default=10,
    ge=1,
    description='Default number of rolls to trigger for batch operations',
  )
  poll_interval_seconds: float = Field(
    default=1.5,
    ge=0.1,
    description='How frequently to poll Discord for new Mudae responses',
  )
  message_history_limit: int = Field(
    default=50,
    ge=1,
    description='Number of recent messages to request when polling Discord',
  )
  roll_delay_seconds: float = Field(
    default=1.0,
    ge=0.1,
    description='Delay between roll commands to avoid hitting rate limits',
  )


class KakeraSettings(BaseModel):
  """Configuration for kakera reaction behavior."""

  model_config = ConfigDict(extra='forbid')

  preferred_types: tuple[str, ...] = Field(
    default=DEFAULT_KAKERA_TYPES,
    description='Ordered list of kakera emoji names to react to when enabled',
  )


class AppSettings(BaseModel):
  """Aggregated application configuration."""

  model_config = ConfigDict(extra='forbid')

  discord: DiscordSettings
  tuning: RuntimeTuning
  kakera: KakeraSettings


def load_settings(env_file: str | Path | None = None) -> AppSettings:
  """Load settings from an ``.env`` file into strongly typed objects."""
  env_path = Path(env_file) if env_file else Path.cwd() / '.env'
  load_dotenv(env_path, override=True)

  discord_settings = DiscordSettings(
    token=os.environ['DISCORD_TOKEN'],
    channel_id=os.environ['DISCORD_CHANNEL_ID'],
    guild_id=os.environ['DISCORD_GUILD_ID'],
    mudae_user_id=os.environ.get('MUDAE_USER_ID', '432610292342587392'),
    command_prefix=os.environ.get('DISCORD_COMMAND_PREFIX', '$'),
    slash_roll_command=os.environ.get('SLASH_ROLL_COMMAND', 'wa'),
  )

  tuning = RuntimeTuning(
    roll_batch_size=int(os.environ.get('ROLL_BATCH_SIZE', '10')),
    poll_interval_seconds=float(os.environ.get('POLL_INTERVAL_SECONDS', '1.5')),
    message_history_limit=int(os.environ.get('MESSAGE_HISTORY_LIMIT', '50')),
    roll_delay_seconds=float(os.environ.get('ROLL_DELAY_SECONDS', '1.0')),
  )

  preferred_kakera_env = os.environ.get('KAKERA_PREFERRED_TYPES', '')
  preferred_kakera = tuple(part.strip() for part in preferred_kakera_env.split(',') if part.strip())
  default_kakera_types = DEFAULT_KAKERA_TYPES
  kakera = KakeraSettings(
    preferred_types=preferred_kakera or default_kakera_types,
  )

  return AppSettings(discord=discord_settings, tuning=tuning, kakera=kakera)
