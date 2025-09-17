from __future__ import annotations

import curses
import threading
import time
from collections.abc import Callable
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
  focus_index: int = 0
  editing_field: str | None = None
  editing_buffer: str | None = None


class CursesApplication:
  """Interactive dashboard for coordinating Mudae commands."""

  def __init__(self, service: MudaeService, settings: AppSettings) -> None:
    self._service = service
    self._settings = settings
    self._state = AppState(
      plan=RollPlan(
        us_uses=settings.tuning.roll_batch_size // 2,
        roll_count=0,
      ),
      focus_index=1,
    )
    self._state_lock = threading.Lock()
    self._runner: threading.Thread | None = None
    self._running = True

  @staticmethod
  def _focusable_fields() -> list[tuple[str, str]]:
    return [
      ('roll_count', 'Roll remaining'),
      ('us_uses', 'Roll count'),
      ('use_slash_commands', 'Use slash commands'),
    ]

  def _current_focus(self) -> tuple[str, str]:
    fields = self._focusable_fields()
    with self._state_lock:
      index = self._state.focus_index % len(fields)
    return fields[index]

  def _is_editing(self) -> bool:
    with self._state_lock:
      return self._state.editing_field is not None

  def _move_focus(self, delta: int) -> None:
    fields = self._focusable_fields()
    with self._state_lock:
      new_index = (self._state.focus_index + delta) % len(fields)
      self._state.focus_index = new_index
      self._state.editing_field = None
      self._state.editing_buffer = None

  def _start_edit(self, *, initial_text: str | None = None) -> None:
    field, _ = self._current_focus()
    if field == 'use_slash_commands':
      return
    with self._state_lock:
      current_value = getattr(self._state.plan, field)
      buffer = initial_text if initial_text is not None else str(current_value)
      self._state.editing_field = field
      self._state.editing_buffer = buffer

  def _cancel_edit(self) -> None:
    with self._state_lock:
      self._state.editing_field = None
      self._state.editing_buffer = None

  def _update_edit_buffer(self, mutate: Callable[[str], str]) -> None:
    with self._state_lock:
      if self._state.editing_buffer is None:
        return
      new_buffer = mutate(self._state.editing_buffer)
      self._state.editing_buffer = new_buffer

  def _commit_edit(self) -> None:
    message: str | None = None
    with self._state_lock:
      field = self._state.editing_field
      buffer = self._state.editing_buffer
      if field is None:
        return
      self._state.editing_field = None
      self._state.editing_buffer = None

      if not buffer:
        return

      try:
        value = int(buffer)
      except ValueError:
        return

      plan = self._state.plan
      if field == 'us_uses':
        value = max(0, value)
        if value != plan.us_uses:
          self._state.plan = plan.model_copy(update={'us_uses': value})
          message = f'Roll count set to {value}'
      elif field == 'roll_count':
        value = max(0, value)
        if value != plan.roll_count:
          self._state.plan = plan.model_copy(update={'roll_count': value})
          message = f'Roll remaining set to {value}'

    if message:
      self._log(message, LogLevel.INFO)

  def _handle_editing_key(self, key: int) -> None:
    if key == 27:  # ESC
      self._cancel_edit()
      return
    if key in (curses.KEY_ENTER, 10, 13):
      self._commit_edit()
      return
    if key == curses.KEY_DOWN:
      self._commit_edit()
      self._move_focus(1)
      return
    if key == curses.KEY_UP:
      self._commit_edit()
      self._move_focus(-1)
      return
    if key in (curses.KEY_CTAB, 9):
      self._commit_edit()
      self._move_focus(1)
      return
    if key in (curses.KEY_BTAB, 353):
      self._commit_edit()
      self._move_focus(-1)
      return
    if key in (curses.KEY_BACKSPACE, 127, 8):
      self._update_edit_buffer(lambda value: value[:-1])
      return
    if ord('0') <= key <= ord('9'):
      self._update_edit_buffer(lambda value: value + chr(key))
      return
    curses.beep()

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
    if self._is_editing():
      self._handle_editing_key(key)
      return

    if key in (ord('q'), ord('Q')):
      self._running = False
      return
    if key in (ord('r'), ord('R')):
      self._trigger_roll()
      return
    if key in (curses.KEY_CTAB, 9, curses.KEY_DOWN):
      self._move_focus(1)
      return
    if key in (curses.KEY_BTAB, 353, curses.KEY_UP):
      self._move_focus(-1)
      return

    field, _ = self._current_focus()

    if field in {'us_uses', 'roll_count'}:
      if key in (curses.KEY_ENTER, 10, 13):
        self._start_edit()
        return
      if ord('0') <= key <= ord('9'):
        self._start_edit(initial_text=chr(key))
        return
      if key == ord('+'):
        if field == 'roll_count':
          self._adjust_rolls(delta=1)
        else:
          self._adjust_us(delta=1)
        return
      if key == ord('-'):
        if field == 'roll_count':
          self._adjust_rolls(delta=-1)
        else:
          self._adjust_us(delta=-1)
        return
    elif field == 'use_slash_commands':
      if key in (curses.KEY_ENTER, 10, 13, ord(' '), ord('t'), ord('T')):
        self._toggle_slash_commands()
        return

    if key == curses.KEY_RESIZE:
      return

  def _adjust_rolls(self, *, delta: int) -> None:
    with self._state_lock:
      new_value = max(0, self._state.plan.roll_count + delta)
      self._state.plan = self._state.plan.model_copy(update={'roll_count': new_value})
    self._log(f'Roll remaining set to {new_value}', LogLevel.INFO)

  def _adjust_us(self, *, delta: int) -> None:
    with self._state_lock:
      new_value = max(0, self._state.plan.us_uses + delta)
      self._state.plan = self._state.plan.model_copy(update={'us_uses': new_value})
    self._log(f'Roll count set to {new_value}', LogLevel.INFO)

  def _toggle_slash_commands(self) -> None:
    with self._state_lock:
      new_value = not self._state.plan.use_slash_commands
      self._state.plan = self._state.plan.model_copy(update={'use_slash_commands': new_value})
    mode = 'slash commands' if new_value else 'text commands'
    self._log(f'Rolling via {mode}.', LogLevel.INFO)

  def _trigger_roll(self) -> None:
    with self._state_lock:
      if self._state.is_busy:
        self._log('A session is already running.', LogLevel.WARNING)
        return
      plan = self._state.plan
      self._state.is_busy = True

    mode = 'slash' if plan.use_slash_commands else 'text'
    self._log(
      f"Launching session: {plan.roll_count} rolls before $us, then {plan.us_uses} boosted rolls via {mode} commands.",
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
      total_rolls = summary.plan.roll_count + summary.plan.us_uses
      message = (
        f'Completed {total_rolls} rolls '
        f'({summary.plan.roll_count} remaining + {summary.plan.us_uses} boosted), '
        f'{summary.cards_detected} cards detected.'
      )
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

    banner = 'Tab/↑/↓ move • Enter edits numbers • Space toggles slash mode • r run • q quit'
    screen.attron(curses.color_pair(2))
    screen.addstr(2, max(0, (width - len(banner)) // 2), banner)
    screen.attroff(curses.color_pair(2))

    status_line = 'STATUS: RUNNING' if state_copy.is_busy else 'STATUS: IDLE'
    color = 4 if state_copy.is_busy else 3
    screen.attron(curses.color_pair(color))
    screen.addstr(4, 2, status_line)
    screen.attroff(curses.color_pair(color))

    plan = state_copy.plan
    fields = self._focusable_fields()
    focus_index = state_copy.focus_index % len(fields)
    for offset, (field, label) in enumerate(fields):
      is_focus = offset == focus_index
      is_editing = state_copy.editing_field == field
      if is_editing:
        buffer = state_copy.editing_buffer or ''
        value_text = buffer + '_'
      elif field == 'use_slash_commands':
        value_text = 'ON' if plan.use_slash_commands else 'OFF'
      elif field == 'us_uses':
        value_text = str(plan.us_uses)
      elif field == 'roll_count':
        value_text = str(plan.roll_count)
      else:
        value_text = ''

      display = f'{label}: {value_text}'
      attr = curses.color_pair(5)
      if is_focus:
        attr |= curses.A_REVERSE
      if is_editing:
        attr |= curses.A_BOLD
      screen.attron(attr)
      screen.addstr(6 + offset, 4, display[: width - 8])
      screen.attroff(attr)

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
