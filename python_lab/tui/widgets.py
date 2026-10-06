from rich.text import Text

from textual import events
from textual.widgets import Input, OptionList, Static
from textual.widgets.option_list import Option

from python_lab.app import PythonLabApp
from python_lab.learning import PLAN_KEYS


class NextStepBar(Static):
    def update_from(self, lab: PythonLabApp) -> None:
        done, total = cycle_progress(lab)
        bar = Text()
        bar.append("█" * done, style="#22c55e")
        bar.append("░" * (total - done), style="#3f3f3f")
        bar.append(f"  {done}/{total}  ", style="#8a8a8a")
        bar.append(lab.next_step(), style="#22c55e")
        self.update(bar)


def cycle_progress(lab: PythonLabApp) -> tuple[int, int]:
    total = 4
    current_id = lab.progress.current_mission_id
    if current_id is None:
        if any(
            item.status == "completed" for item in lab.progress.missions.values()
        ) and lab.recommended() is None:
            return total, total
        return 0, total
    progress = lab.progress.missions.get(current_id)
    if progress is None:
        return 0, total
    done = 1
    plan = progress.plan or {}
    if all(str(plan.get(key, "")).strip() for key in PLAN_KEYS):
        done += 1
    if lab.tests_are_current():
        done += 1
    if progress.explanation:
        done += 1
    return done, total


class CommandPalette(OptionList, can_focus=False):
    def update_from(self, commands: tuple[tuple[str, str, str], ...], query: str) -> None:
        text = query.strip()
        if not text.startswith("/") or " " in text:
            self.clear_options()
            self.display = False
            return
        needle = text.lower()
        options: list[Option] = []
        for command, shortcut, description in commands:
            haystack = f"{command} {shortcut}".lower()
            if needle != "/" and not haystack.startswith(needle) and needle not in haystack:
                continue
            needs_arg = "<" in command or "[" in command
            slug = command.split(" [", 1)[0].split(" <", 1)[0].lstrip("/").replace("?", "help")
            option_id = f"{'need' if needs_arg else 'run'}-{slug}"
            label = f"{command}  {description}"
            options.append(Option(label, id=option_id))
        self.clear_options()
        if not options:
            self.display = False
            return
        self.add_options(options)
        self.highlighted = 0
        self.display = True

    def selected_insert(self) -> tuple[str, bool] | None:
        if not self.display or self.highlighted is None:
            return None
        option = self.get_option_at_index(self.highlighted)
        if option.id is None:
            return None
        kind, slug = option.id.split("-", 1)
        command = f"/{slug}"
        return command, kind == "need"


class Composer(Input):
    def on_key(self, event: events.Key) -> None:
        if event.key in {"pageup", "pagedown"}:
            event.prevent_default()
            event.stop()
            self.app.scroll_content(down=event.key == "pagedown")
            return
        if event.key == "ctrl+c":
            event.prevent_default()
            event.stop()
            self.app.action_quit_lab()
            return
        if event.key == "escape":
            event.prevent_default()
            event.stop()
            self.app.action_composer_escape()
            return
        if event.key == "up":
            event.prevent_default()
            event.stop()
            self.app.action_palette_up()
            return
        if event.key == "down":
            event.prevent_default()
            event.stop()
            self.app.action_palette_down()
            return
        if event.key == "q" and not self.value:
            event.prevent_default()
            event.stop()
            self.app.action_quit_lab()
