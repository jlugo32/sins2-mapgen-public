"""Chat mode: a REPL that edits the current MapSpec (BRIEF S3).

Only a plain-text request calls the API. Every slash command is local: preview, summary, diff, undo,
save, build, install and seed never spend a token.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from .. import ROOT, rules
from ..config import Config
from ..mod_writer import InstallError, install
from ..params import MapParams
from ..pipeline import BuildResult, build
from ..spec import MapSpec
from . import describe
from .client import SESSION, AIError, BudgetExceeded
from .repair import RepairResult, check, repair, spec_diff

HELP = """commands (all local, no API calls):
  /preview        render the current map to out/<name>_preview.png
  /summary        what is actually built, from the compiled graph
  /diff           changes since the previous spec
  /undo           step back to the previous spec
  /save           write the spec to specs/<name>.mapspec.json
  /build          build and validate the mod folder
  /install        build, then copy into the game's mods folder
  /seed N         change the seed and recompile
  /help           this list
  /quit           leave
anything else is a request and calls the model."""


@dataclass
class Chat:
    cfg: Config
    params: MapParams = field(default_factory=MapParams)
    console: Console = field(default_factory=lambda: Console(width=110))
    client: object | None = None
    out_root: Path = ROOT / "out"
    specs_dir: Path = ROOT / "specs"
    spec: MapSpec | None = None
    history: list[MapSpec] = field(default_factory=list)
    request: str | None = None
    assumptions: list[str] = field(default_factory=list)
    last_build: BuildResult | None = None
    max_rounds: int = 3
    auto_open: bool = False

    # ------------------------------------------------------------------ helpers
    def say(self, text: str = "") -> None:
        self.console.print(text)

    def plain(self, text: str = "") -> None:
        """Dynamic text (diffs, rule messages) may contain [brackets]; never read as markup."""
        self.console.print(text, markup=False)

    def need_spec(self) -> bool:
        if self.spec is None:
            self.say("[yellow]no map yet - describe one first[/]")
            return False
        return True

    def show_state(self, previous: MapSpec | None) -> None:
        """After any change: recompile, re-run the rules, show the diff and the summary."""
        m, violations = check(self.spec, self.cfg.limits, self.params)
        if previous is not None:
            self.say("[bold]changes:[/]")
            for line in spec_diff(previous, self.spec):
                self.plain(f"  {line}")
        describe.report(m, self.console, request=self.request, assumptions=self.assumptions, tables=False)
        self.render_preview()
        errs = rules.errors(violations)
        for v in violations:
            style = "red" if v.severity == "error" else "yellow"
            self.console.print(f"[{style}]{v.severity.upper()} {v.code}[/]: {escape(v.message)}")
        if errs:
            self.say("[red]this spec would not build; ask for a fix or /undo[/]")

    # ------------------------------------------------------------------ commands
    def render_preview(self, force_open: bool = False) -> None:
        """Re-render after any change. Cheap and local: no API call."""
        res = build(self.spec, self.params, self.cfg, self.out_root, preview_only=True)
        if rules.errors(res.violations) or not res.preview:
            self.say("[yellow]preview not rendered (rule violations)[/]")
            return
        self.say(f"preview: {res.preview}")
        if self.auto_open or force_open:
            from ..preview import open_file
            open_file(res.preview)

    def cmd_preview(self) -> None:
        if not self.need_spec():
            return
        self.render_preview(force_open=True)

    def cmd_summary(self) -> None:
        if not self.need_spec():
            return
        m, _ = check(self.spec, self.cfg.limits, self.params)
        describe.report(m, self.console, request=self.request, assumptions=self.assumptions)

    def cmd_diff(self) -> None:
        if not self.need_spec():
            return
        if not self.history:
            self.say("(nothing to compare: this is the first spec)")
            return
        for line in spec_diff(self.history[-1], self.spec):
            self.plain(f"  {line}")

    def cmd_undo(self) -> None:
        if not self.history:
            self.say("[yellow]nothing to undo[/]")
            return
        current, self.spec = self.spec, self.history.pop()
        self.say(f"undone; back to seed {self.spec.meta.seed}, {len(self.spec.zones)} zones")
        for line in spec_diff(current, self.spec):
            self.plain(f"  {line}")

    def cmd_save(self) -> None:
        if not self.need_spec():
            return
        path = self.specs_dir / f"{self.spec.meta.name}.mapspec.json"
        self.spec.save(path)
        self.say(f"saved: {path}")

    def cmd_build(self) -> BuildResult | None:
        if not self.need_spec():
            return None
        res = build(self.spec, self.params, self.cfg, self.out_root)
        self.last_build = res
        for v in rules.errors(res.violations):
            self.say(f"[red]ERROR {v.code}[/]: {escape(v.message)}")
        for p in res.problems:
            self.say(f"[red]INVALID[/] {escape(str(p))}")
        if res.mod_dir:
            self.say(f"[green]mod: {res.mod_dir}[/]\npreview: {res.preview}")
        else:
            self.say("[red]nothing written[/]")
        return res

    def cmd_install(self) -> None:
        res = self.last_build if (self.last_build and self.last_build.mod_dir) else self.cmd_build()
        if not res or not res.mod_dir:
            return
        try:
            self.say(f"installed: {install(res.mod_dir, self.cfg.mods_dir)}")
        except InstallError as exc:
            self.say(f"[red]install refused:[/] {exc}")

    def cmd_seed(self, arg: str) -> None:
        if not self.need_spec():
            return
        try:
            seed = int(arg)
        except ValueError:
            self.say("[yellow]usage: /seed 123[/]")
            return
        previous = self.spec
        self.history.append(previous)
        data = self.spec.to_dict()
        data["meta"]["seed"] = seed
        from ..spec import from_dict
        self.spec = from_dict(data)
        self.show_state(previous)

    # ------------------------------------------------------------------ model
    def ask_model(self, text: str) -> RepairResult:
        """The only path that spends tokens."""
        request = text if self.spec is None else f"{self.request}\n\nNow change it: {text}"
        res = repair(request, self.cfg.limits, self.params, seed=self.spec.meta.seed if self.spec else None,
                     client=self.client, max_rounds=self.max_rounds)
        for line in res.summary_lines():
            self.plain(line)
        for line in res.cost_lines():
            self.say(f"[dim]{line}[/]")
        if res.asked:
            self.say("[bold]the model needs to know:[/]")
            for q in res.questions:
                self.say(f"  ? {q}")
            return res
        if res.spec is None:
            self.say("[red]no usable spec came back[/]")
            return res
        previous = self.spec
        if previous is not None:
            self.history.append(previous)
        self.spec, self.request, self.assumptions = res.spec, request, res.assumptions
        if not res.ok:
            self.say(f"[red]still failing after {len(res.rounds)} round(s)[/]")
        self.show_state(previous)
        return res

    # ------------------------------------------------------------------ dispatch
    def handle(self, line: str) -> bool:
        """Returns False when the session should end."""
        line = line.strip()
        if not line:
            return True
        if not line.startswith("/"):
            try:
                self.ask_model(line)
            except BudgetExceeded as exc:
                self.say(f"[red]budget:[/] {escape(str(exc))}")
            except AIError as exc:
                self.say(f"[red]error:[/] {escape(str(exc))}")
            return True
        cmd, _, arg = line.partition(" ")
        match cmd:
            case "/quit" | "/exit":
                self.say(SESSION.line())
                return False
            case "/help":
                self.say(HELP)
            case "/preview":
                self.cmd_preview()
            case "/summary":
                self.cmd_summary()
            case "/diff":
                self.cmd_diff()
            case "/undo":
                self.cmd_undo()
            case "/save":
                self.cmd_save()
            case "/build":
                self.cmd_build()
            case "/install":
                self.cmd_install()
            case "/seed":
                self.cmd_seed(arg)
            case _:
                self.say(f"[yellow]unknown command {cmd}[/] - /help for the list")
        return True

    def run(self) -> int:
        self.say("sins2-mapgen chat. Describe a map, or /help.")
        while True:
            try:
                line = input("> ")
            except (EOFError, KeyboardInterrupt):
                self.say("")
                self.say(SESSION.line())
                return 0
            if not self.handle(line):
                return 0
