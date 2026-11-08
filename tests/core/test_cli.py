import sys
import textwrap

import pytest

import carhunt
from carhunt import cli


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    """Extra packages under carhunt: one good, one that fails to import, one that fails in register()."""
    root = tmp_path / "plug"
    for name, body in {
        "dummy": """
            def register(sub):
                p = sub.add_parser("dummy", help="test plugin")
                p.add_argument("word")
                p.set_defaults(func=lambda a: print("dummy says " + a.word) or 7)
        """,
        "broken": "import does_not_exist_anywhere\n",
        "halfway": """
            def register(sub):
                sub.add_parser("halfway")
                raise RuntimeError("boom")
        """,
    }.items():
        (root / name).mkdir(parents=True)
        (root / name / "__init__.py").write_text("")
        (root / name / "cli.py").write_text(textwrap.dedent(body))
    (root / "nocli").mkdir()
    (root / "nocli" / "__init__.py").write_text("")
    monkeypatch.setattr(carhunt, "__path__", [*carhunt.__path__, str(root)])
    yield
    for m in [m for m in sys.modules if m.startswith(("carhunt.dummy", "carhunt.broken", "carhunt.halfway"))]:
        del sys.modules[m]


def test_discovers_plugin_and_survives_broken_ones(plugins, capsys):
    rc = cli.main(["dummy", "hi"])
    out = capsys.readouterr()
    assert rc == 7 and "dummy says hi" in out.out
    assert "plugin broken not loaded" in out.err and "does_not_exist_anywhere" in out.err
    assert "plugin halfway failed to register" in out.err
    assert "nocli" not in out.err  # a package without cli.py is silently fine
    p = cli.build_parser(warn=lambda m: None)
    groups = p._subparsers._group_actions[0].choices
    assert {"config", "secret", "notify", "doctor", "dummy"} <= set(groups)
    assert "halfway" not in groups


def test_group_without_command_prints_help(capsys):
    assert cli.main(["notify"]) == 2
    assert "inbox" in capsys.readouterr().err


def test_config_commands(example_config, capsys):
    assert cli.main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(example_config)
    assert cli.main(["config", "validate"]) == 0
    assert cli.main(["config", "show"]) == 0
    assert "secret:telegram_bot_token" in capsys.readouterr().out
    example_config.write_text("owner: {tz: Nowhere/Land}\n")
    assert cli.main(["config", "validate"]) == 1
    assert "owner.tz" in capsys.readouterr().out
