from __future__ import annotations

import curses
import threading
import time
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from models import LogEntry, LogLevel, RollPlan, RollSummary
from mudae_service import MudaeService
from settings import AppSettings


class AppState(BaseModel):
  """Mutable runtime state for the curses interface."""

  model_config = ConfigDict(extra='forbid', validate_assignment=True)

  plan: RollPlan
  logs: list[LogEntry] = Field(default_factory=list)
  is_busy: bool = False
  last_summary: RollSummary | None = None


class CursesApplication:
  """Interactive dashboard for coordinating Mudae commands."""

  def __init__(self, service: MudaeService, settings: AppSettings) -> None:
    self._service = service
    self._settings = settings
    self._state = AppState(
      plan=RollPlan(
        us_uses=settings.tuning.roll_batch_size // 2,
        roll_count=settings.tuning.roll_batch_size,
        wait_for_cards=True,
      )
    )
    self._state_lock = threading.Lock()
    self._runner: threading.Thread | None = None
    self._running = True

  def run(self, screen: curses._CursesWindow) -> None:  # type: ignore[name-defined]
    curses.curs_set(0)
    screen.nodelay(True)
    curses.start_color()
    curses.use_default_colors()
    self._init_colors()
    self._log("Ready to roll! Press 'r' to start a session.", LogLevel.INFO)

    while self._running:
      self._render(screen)
      key = screen.getch()
      if key == -1:
        time.sleep(0.05)
        continue
      self._handle_key(key)

  def _handle_key(self, key: int) -> None:
    if key in (ord('q'), ord('Q')):
      self._running = False
      return
    if key in (ord('r'), ord('R')):
      self._trigger_roll()
      return
    if key in (ord('+'), curses.KEY_UP):
      self._adjust_rolls(delta=1)
      return
    if key in (ord('-'), curses.KEY_DOWN):
      self._adjust_rolls(delta=-1)
      return
    if key == ord('['):
      self._adjust_us(delta=-1)
      return
    if key == ord(']'):
      self._adjust_us(delta=1)
      return
    if key in (ord('t'), ord('T')):
      self._toggle_waiting()
      return
    if key == curses.KEY_RESIZE:
      return

  def _adjust_rolls(self, *, delta: int) -> None:
    with self._state_lock:
      new_value = max(1, self._state.plan.roll_count + delta)
      self._state.plan = self._state.plan.model_copy(update={'roll_count': new_value})
    self._log(f'Roll count adjusted to {new_value}', LogLevel.INFO)

  def _adjust_us(self, *, delta: int) -> None:
    with self._state_lock:
      new_value = max(0, self._state.plan.us_uses + delta)
      self._state.plan = self._state.plan.model_copy(update={'us_uses': new_value})
    self._log(f'$us usage set to {new_value}', LogLevel.INFO)

  def _toggle_waiting(self) -> None:
    with self._state_lock:
      new_value = not self._state.plan.wait_for_cards
      self._state.plan = self._state.plan.model_copy(update={'wait_for_cards': new_value})
    state = 'enabled' if new_value else 'disabled'
    self._log(f'Card detection {state}.', LogLevel.INFO)

  def _trigger_roll(self) -> None:
    with self._state_lock:
      if self._state.is_busy:
        self._log('A session is already running.', LogLevel.WARNING)
        return
      plan = self._state.plan
      self._state.is_busy = True

    self._log(
      f'Launching session: $us {plan.us_uses} then {plan.roll_count} rolls.',
      LogLevel.SUCCESS,
    )

    self._runner = threading.Thread(target=self._run_session, args=(plan,), daemon=True)
    self._runner.start()

  def _run_session(self, plan: RollPlan) -> None:
    try:
      self._service.sync_state()
      summary = self._service.execute_roll_plan(plan)
      with self._state_lock:
        self._state.last_summary = summary
      message = f'Completed {summary.plan.roll_count} rolls, {summary.cards_detected} cards detected.'
      self._log(message, LogLevel.SUCCESS)
    except Exception as exc:  # noqa: BLE001
      self._log(f'Session failed: {exc}', LogLevel.ERROR)
    finally:
      with self._state_lock:
        self._state.is_busy = False

  def _render(self, screen: curses._CursesWindow) -> None:  # type: ignore[name-defined]
    screen.erase()
    height, width = screen.getmaxyx()

    with self._state_lock:
      state_copy = self._state.model_copy(deep=True)

    title = ' Mudae Roll Orchestrator '
    screen.attron(curses.color_pair(1))
    screen.addstr(0, max(0, (width - len(title)) // 2), title)
    screen.attroff(curses.color_pair(1))

    banner = "Press 'r' to roll • '+'/'-' adjust rolls • '['/']' adjust $us • 't' toggle card wait • 'q' quit"
    screen.attron(curses.color_pair(2))
    screen.addstr(2, max(0, (width - len(banner)) // 2), banner)
    screen.attroff(curses.color_pair(2))

    status_line = 'STATUS: RUNNING' if state_copy.is_busy else 'STATUS: IDLE'
    color = 4 if state_copy.is_busy else 3
    screen.attron(curses.color_pair(color))
    screen.addstr(4, 2, status_line)
    screen.attroff(curses.color_pair(color))

    plan = state_copy.plan
    plan_lines = [
      f'$us boosts: {plan.us_uses}',
      f'Roll count: {plan.roll_count}',
      f'Card detection: {"ON" if plan.wait_for_cards else "OFF"}',
    ]
    for idx, line in enumerate(plan_lines, start=6):
      screen.attron(curses.color_pair(5))
      screen.addstr(idx, 4, line)
      screen.attroff(curses.color_pair(5))

    summary = state_copy.last_summary
    if summary:
      screen.attron(curses.color_pair(6))
      screen.addstr(10, 2, 'Last Session Summary:')
      screen.attroff(curses.color_pair(6))
      summary_lines = [
        f'Messages sent: {summary.total_messages_sent}',
        f'Cards detected: {summary.cards_detected}',
        f'Last card: {summary.last_card_title or "—"}',
        f'Duration: {summary.duration_seconds:.1f}s',
      ]
      for idx, line in enumerate(summary_lines, start=11):
        screen.addstr(idx, 4, line)

    screen.attron(curses.color_pair(2))
    screen.addstr(height - 8, 2, 'Event log:')
    screen.attroff(curses.color_pair(2))

    visible_logs = state_copy.logs[-6:]
    for idx, entry in enumerate(visible_logs, start=height - 6):
      color = self._log_color(entry.level)
      timestamp = entry.created_at.astimezone(UTC).strftime('%H:%M:%S')
      line = f'[{timestamp}] {entry.message}'
      screen.attron(curses.color_pair(color))
      screen.addstr(idx, 4, line[: width - 8])
      screen.attroff(curses.color_pair(color))

    screen.refresh()

  @staticmethod
  def _log_color(level: LogLevel) -> int:
    return {
      LogLevel.INFO: 7,
      LogLevel.SUCCESS: 3,
      LogLevel.WARNING: 8,
      LogLevel.ERROR: 9,
    }[level]

  def _log(self, message: str, level: LogLevel) -> None:
    entry = LogEntry(level=level, message=message, created_at=datetime.now(UTC))
    with self._state_lock:
      self._state.logs.append(entry)
      if len(self._state.logs) > 200:
        self._state.logs.pop(0)

  @staticmethod
  def _init_colors() -> None:
    curses.init_pair(1, curses.COLOR_MAGENTA, -1)
    curses.init_pair(2, curses.COLOR_CYAN, -1)
    curses.init_pair(3, curses.COLOR_GREEN, -1)
    curses.init_pair(4, curses.COLOR_RED, -1)
    curses.init_pair(5, curses.COLOR_YELLOW, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)
    curses.init_pair(8, curses.COLOR_YELLOW, -1)
    curses.init_pair(9, curses.COLOR_RED, -1)
