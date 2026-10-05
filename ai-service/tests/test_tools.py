import pytest

from app import tools
from app.tools import ToolError


def calc(expression):
    return tools.run_tool("calculate", {"expression": expression})["result"]


def test_basic_arithmetic():
    assert calc("12 * 34") == 408
    assert calc("(100 + 50) / 3") == 50
    assert calc("2 ** 10") == 1024
    assert calc("-5 + 2") == -3


def test_float_rounding():
    assert calc("0.1 + 0.2") == 0.3


def test_huge_integers_become_strings():
    assert calc("10 ** 20") == str(10 ** 20)


@pytest.mark.parametrize("expression", [
    "__import__('os').getcwd()",
    "open('/etc/passwd')",
    "[1, 2, 3]",
    "abs(-1)",
    "1 if True else 2",
    "x + 1",
    "'a' * 5",
    "True + 1",
])
def test_unsafe_or_unsupported_expressions_are_rejected(expression):
    with pytest.raises(ToolError):
        calc(expression)


def test_division_by_zero_is_a_tool_error():
    with pytest.raises(ToolError):
        calc("10 / 0")


def test_power_and_length_limits():
    with pytest.raises(ToolError):
        calc("9 ** 9 ** 9")
    with pytest.raises(ToolError):
        calc("1 + " * 100 + "1")  # dài hơn 200 ký tự


def test_unknown_tool_and_bad_arguments():
    with pytest.raises(ToolError):
        tools.run_tool("delete_everything", {})
    with pytest.raises(ToolError):
        tools.run_tool("calculate", "12*34")
    with pytest.raises(ToolError):
        tools.run_tool("calculate", {})
    with pytest.raises(ToolError):
        tools.run_tool("read_document", {"document_id": "không-phải-uuid"})


def test_registry_is_read_only_and_complete():
    assert set(tools.TOOLS) == {"list_documents", "search_documents", "read_document", "calculate"}
    names = [s["name"] for s in tools.specs(list(tools.TOOLS))]
    assert sorted(names) == sorted(tools.TOOLS)
    assert tools.specs(["ghi_file"]) == []