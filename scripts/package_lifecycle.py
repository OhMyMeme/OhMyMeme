"""发布产物生命周期 probe 契约。"""

from dataclasses import dataclass, replace

PHASES = ("build", "install", "launch", "upgrade", "rollback", "uninstall")
MACOS_INSTALL = (
    "hdiutil attach {artifact} -nobrowse && "
    "ditto {mounted_app} /Applications/OhMyMeme.app"
)
MACOS_ROLLBACK = (
    "hdiutil attach {previous_artifact} -nobrowse && "
    "ditto {mounted_app} /Applications/OhMyMeme.app"
)


class LifecycleViolation(ValueError):
    """生命周期 probe 定义无效。"""


@dataclass(frozen=True)
class LifecycleProbe:
    phase: str
    runner: str
    tool: str
    input: str
    required: bool
    command: str
    observable: str
    cleanup: str

    def with_field(self, field, value):
        return replace(self, **{field: value})


def probes_for(target):
    runners = {
        "windows-x64": "windows-latest",
        "linux-appimage-x64": "ubuntu-latest",
        "linux-deb-amd64": "ubuntu-latest",
        "linux-rpm-x64": "ubuntu-latest",
        "macos-arm64": "macos-latest",
        "macos-x86_64": "macos-15-intel",
    }
    package_tools = {
        "windows-x64": "iscc",
        "linux-appimage-x64": "appimagetool",
        "linux-deb-amd64": "dpkg-deb",
        "linux-rpm-x64": "rpmbuild",
        "macos-arm64": "hdiutil",
        "macos-x86_64": "hdiutil",
    }
    runner = runners[target]
    package_tool = package_tools[target]
    commands = {
        "windows-x64": (
            "python scripts/build.py --windows",
            '"{artifact}" /VERYSILENT /SUPPRESSMSGBOXES',
            'powershell -Command "& {installed_app} --version"',
            '"{artifact}" /VERYSILENT /SUPPRESSMSGBOXES',
            '"{previous_artifact}" /VERYSILENT /SUPPRESSMSGBOXES',
            '"{uninstaller}" /VERYSILENT',
        ),
        "linux-appimage-x64": (
            "python scripts/build.py --linux --package appimage",
            "install -Dm755 {artifact} {workspace}/OhMyMeme.AppImage",
            "{workspace}/OhMyMeme.AppImage --version",
            "install -Dm755 {artifact} {workspace}/OhMyMeme.AppImage",
            "install -Dm755 {previous_artifact} {workspace}/OhMyMeme.AppImage",
            "rm -f {workspace}/OhMyMeme.AppImage",
        ),
        "linux-deb-amd64": (
            "python scripts/build.py --linux --package deb",
            "sudo dpkg -i {artifact}",
            "OhMyMeme --version",
            "sudo dpkg -i {artifact}",
            "sudo dpkg -i {previous_artifact}",
            "sudo apt-get remove --yes ohmymeme",
        ),
        "linux-rpm-x64": (
            "python scripts/build.py --linux --package rpm",
            "sudo rpm -Uvh {artifact}",
            "OhMyMeme --version",
            "sudo rpm -Uvh {artifact}",
            "sudo rpm -Uvh {previous_artifact}",
            "sudo rpm -e ohmymeme",
        ),
        "macos-arm64": (
            "python scripts/build.py --macos --arch arm64",
            MACOS_INSTALL,
            "open -W /Applications/OhMyMeme.app --args --version",
            MACOS_INSTALL,
            MACOS_ROLLBACK,
            "rm -rf /Applications/OhMyMeme.app",
        ),
        "macos-x86_64": (
            "python scripts/build.py --macos --arch x86_64",
            MACOS_INSTALL,
            "open -W /Applications/OhMyMeme.app --args --version",
            MACOS_INSTALL,
            MACOS_ROLLBACK,
            "rm -rf /Applications/OhMyMeme.app",
        ),
    }[target]
    return (
        LifecycleProbe(
            "build",
            runner,
            package_tool,
            "source tree",
            True,
            commands[0],
            "{artifact} exists",
            "remove build workspace",
        ),
        LifecycleProbe(
            "install",
            runner,
            package_tool,
            "candidate artifact",
            True,
            commands[1],
            "installed application exists",
            "uninstall candidate application",
        ),
        LifecycleProbe(
            "launch",
            runner,
            "process runner",
            "installed application",
            True,
            commands[2],
            "application process exits successfully",
            "terminate application process",
        ),
        LifecycleProbe(
            "upgrade",
            runner,
            package_tool,
            "previous and candidate artifacts",
            True,
            commands[3],
            "installed version equals {package_version}",
            "restore previous installed application",
        ),
        LifecycleProbe(
            "rollback",
            runner,
            package_tool,
            "previous artifact",
            True,
            commands[4],
            "installed version equals previous version",
            "uninstall rollback application",
        ),
        LifecycleProbe(
            "uninstall",
            runner,
            package_tool,
            "installed application",
            True,
            commands[5],
            "installed application is absent",
            "remove lifecycle workspace",
        ),
    )


def validate_probes(probes):
    if tuple(probe.phase for probe in probes) != PHASES:
        raise LifecycleViolation("lifecycle probes must define every phase in order")
    for probe in probes:
        if not probe.required:
            raise LifecycleViolation("lifecycle probe must be required")
        for field in ("runner", "tool", "input", "command", "observable", "cleanup"):
            value = getattr(probe, field)
            if not isinstance(value, str) or not value.strip():
                raise LifecycleViolation(
                    "lifecycle probe %s must be nonempty text" % field
                )
