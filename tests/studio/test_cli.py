from qitos.cli import main


def test_studio_command_has_local_registry_entrypoint(capsys) -> None:
    assert main(["studio", "--help"]) == 0
    output = capsys.readouterr().out
    assert "--registry" in output
    assert "--no-open" in output
