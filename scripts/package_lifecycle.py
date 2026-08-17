"""发布产物生命周期 probe 契约。"""

from dataclasses import dataclass

PHASES = ("build", "install", "launch", "upgrade", "rollback", "uninstall")


class LifecycleViolation(ValueError):
    """生命周期 probe 定义无效。"""


@dataclass(frozen=True)
class LifecycleProbe:
    phase: str
    runner: str
    tool: str
    input: str
    required: bool


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
    return (
        LifecycleProbe("build", runner, package_tool, "source tree", True),
        LifecycleProbe("install", runner, package_tool, "candidate artifact", True),
        LifecycleProbe(
            "launch", runner, "process runner", "installed application", True
        ),
        LifecycleProbe(
            "upgrade", runner, package_tool, "previous and candidate artifacts", True
        ),
        LifecycleProbe("rollback", runner, package_tool, "previous artifact", True),
        LifecycleProbe(
            "uninstall", runner, package_tool, "installed application", True
        ),
    )


def validate_probes(probes):
    if tuple(probe.phase for probe in probes) != PHASES:
        raise LifecycleViolation("lifecycle probes must define every phase in order")
    for probe in probes:
        if not probe.required:
            raise LifecycleViolation("lifecycle probe must be required")
        if not probe.runner or not probe.tool or not probe.input:
            raise LifecycleViolation("lifecycle probe capability is missing")
