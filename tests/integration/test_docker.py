import subprocess


def test_dockerfile_builds():
    result = subprocess.run(
        ["docker", "build", "-t", "llm-construct:test", "."],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
