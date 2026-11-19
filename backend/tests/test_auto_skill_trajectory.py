"""Trajectory extraction and rendering for auto-skill synthesis."""

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from deerflow.skills.auto.trajectory import RunTrajectory, ToolStep, extract_run_trajectory, render_trajectory


def _run_messages(*, tool_results: list[tuple[str, str, str]] | None = None, answer: str = "最终结论") -> list:
    """Build a realistic run: user query, tool calls with results, final answer."""
    messages: list = [HumanMessage(content="查一下 A 公司的融资历史")]
    for index, (tool_call_id, name, result) in enumerate(tool_results or []):
        messages.append(AIMessage(content="", tool_calls=[{"name": name, "id": tool_call_id, "args": {"company": f"C{index}", "limit": 5}}]))
        messages.append(ToolMessage(content=result, tool_call_id=tool_call_id, name=name))
    messages.append(AIMessage(content=answer))
    return messages


class TestExtractRunTrajectory:
    def test_extracts_query_tools_and_answer(self):
        messages = _run_messages(
            tool_results=[
                ("call-1", "finance_query_financing", '{"rounds": 3}'),
                ("call-2", "enterprise_query_company", '{"status": "存续"}'),
            ]
        )
        trajectory = extract_run_trajectory({"messages": messages})

        assert trajectory is not None
        assert trajectory.query == "查一下 A 公司的融资历史"
        assert trajectory.final_answer == "最终结论"
        assert [step.tool_name for step in trajectory.tool_steps] == ["finance_query_financing", "enterprise_query_company"]
        assert trajectory.tool_steps[0].args_summary == '{"company": "C0", "limit": 5}'
        assert trajectory.tool_steps[0].result_summary == '{"rounds": 3}'
        assert trajectory.successful_tool_calls == 2

    def test_prefers_original_user_content_over_sanitized_wrapper(self):
        """The learned scenario must be the user's words, not sanitization framing."""
        messages = [
            HumanMessage(content="<untrusted_input>查一下 A 公司</untrusted_input>", additional_kwargs={"original_user_content": "查一下 A 公司"}),
            AIMessage(content="完成"),
        ]
        trajectory = extract_run_trajectory({"messages": messages})

        assert trajectory is not None
        assert trajectory.query == "查一下 A 公司"

    def test_error_results_count_as_steps_but_not_as_successful_calls(self):
        messages = [
            HumanMessage(content="查询"),
            AIMessage(content="", tool_calls=[{"name": "ok_tool", "id": "c1", "args": {}}]),
            ToolMessage(content="成功", tool_call_id="c1", name="ok_tool"),
            AIMessage(content="", tool_calls=[{"name": "bad_tool", "id": "c2", "args": {}}]),
            ToolMessage(content="boom", tool_call_id="c2", name="bad_tool", status="error"),
            AIMessage(content="已处理"),
        ]
        trajectory = extract_run_trajectory({"messages": messages})

        assert trajectory is not None
        assert len(trajectory.tool_steps) == 2
        assert trajectory.successful_tool_calls == 1
        assert trajectory.tool_steps[1].status == "error"

    def test_collects_skills_from_state_and_message_stamps(self):
        messages = [
            HumanMessage(content="写研报"),
            AIMessage(content="", additional_kwargs={"skill_usage": {"name": "deep-research", "path": "/mnt/skills/public/deep-research/SKILL.md"}}, tool_calls=[{"name": "t", "id": "c1", "args": {}}]),
            ToolMessage(content="ok", tool_call_id="c1", name="t"),
            AIMessage(content="", additional_kwargs={"skill_usages": [{"name": "ppt-generation"}, {"name": "chart-visualization"}]}),
            AIMessage(content="完成"),
        ]
        state = {"messages": messages, "skill_context": [{"name": "deep-research", "path": "p", "description": "d", "loaded_at": 1}, {"name": "data-analysis"}]}

        trajectory = extract_run_trajectory(state)

        assert trajectory is not None
        # Deduplicated across both sources, first-seen order preserved.
        assert trajectory.skill_names == ("deep-research", "data-analysis", "ppt-generation", "chart-visualization")

    def test_collects_todo_texts_from_plan_mode(self):
        messages = _run_messages(tool_results=[("c1", "t", "ok")])
        state = {"messages": messages, "todos": [{"content": "调研竞品", "status": "completed"}, {"content": "撰写报告", "status": "in_progress"}, "追加校验"]}

        trajectory = extract_run_trajectory(state)

        assert trajectory is not None
        assert trajectory.todo_texts == ("调研竞品", "撰写报告", "追加校验")

    def test_returns_none_without_messages(self):
        assert extract_run_trajectory({"messages": []}) is None
        assert extract_run_trajectory({}) is None

    def test_returns_none_without_genuine_user_query(self):
        trajectory = extract_run_trajectory({"messages": [SystemMessage(content="系统提示"), AIMessage(content="回答")]})
        assert trajectory is None

    def test_returns_none_without_visible_final_answer(self):
        """A tool-only run has no answer format to learn from."""
        messages = [
            HumanMessage(content="查询"),
            AIMessage(content="", tool_calls=[{"name": "t", "id": "c1", "args": {}}]),
            ToolMessage(content="ok", tool_call_id="c1", name="t"),
        ]
        assert extract_run_trajectory({"messages": messages}) is None

    def test_never_raises_on_malformed_state(self):
        class Exploding(dict):
            def get(self, *args, **kwargs):
                raise RuntimeError("checkpoint corrupt")

        assert extract_run_trajectory(Exploding(messages=[])) is None

    def test_bounds_query_answer_and_result_lengths(self):
        messages = [
            HumanMessage(content="问" * 5000),
            AIMessage(content="", tool_calls=[{"name": "t", "id": "c1", "args": {"k": "v" * 5000}}]),
            ToolMessage(content="果" * 9000, tool_call_id="c1", name="t"),
            AIMessage(content="答" * 20000),
        ]
        trajectory = extract_run_trajectory({"messages": messages}, max_tool_result_chars=500)

        assert trajectory is not None
        assert len(trajectory.query) < 5000
        assert len(trajectory.final_answer) < 20000
        assert len(trajectory.tool_steps[0].result_summary) <= 500 + len("\n…[truncated]")
        assert trajectory.tool_steps[0].result_summary.endswith("…[truncated]")

    def test_keeps_only_the_most_recent_tool_steps(self):
        results = [(f"c{i}", f"tool_{i}", f"result-{i}") for i in range(60)]
        trajectory = extract_run_trajectory({"messages": _run_messages(tool_results=results)})

        assert trajectory is not None
        assert len(trajectory.tool_steps) == 40
        # The tail is retained: the earliest exploratory calls are dropped.
        assert trajectory.tool_steps[-1].tool_name == "tool_59"
        assert trajectory.tool_steps[0].tool_name == "tool_20"


class TestRenderTrajectory:
    def _trajectory(self, *, steps: int = 2, query: str = "查询 A 公司融资") -> RunTrajectory:
        return RunTrajectory(
            query=query,
            skill_names=("deep-research",),
            tool_steps=tuple(ToolStep(tool_name=f"tool_{i}", args_summary='{"a": 1}', result_summary=f"result-{i}" * 40, status="success") for i in range(steps)),
            final_answer="结论：共 3 轮融资",
            todo_texts=("调研", "成稿"),
        )

    def test_renders_every_section(self):
        rendered = render_trajectory(self._trajectory(), max_chars=100000)

        assert "## 用户原始请求" in rendered
        assert "查询 A 公司融资" in rendered
        assert "## 本次命中的技能" in rendered
        assert "- deep-research" in rendered
        assert "## 执行计划" in rendered
        assert "## 取数与执行轨迹" in rendered
        assert "### 步骤 1: tool_0" in rendered
        assert "## 最终回答" in rendered
        assert "结论：共 3 轮融资" in rendered

    def test_marks_absent_skills_explicitly(self):
        trajectory = RunTrajectory(query="q", skill_names=(), tool_steps=(), final_answer="a", todo_texts=())
        assert "（无：本次未匹配到已有技能）" in render_trajectory(trajectory, max_chars=10000)

    def test_respects_total_budget_by_dropping_oldest_steps(self):
        rendered = render_trajectory(self._trajectory(steps=20), max_chars=3000)

        assert len(rendered) <= 3000 + len("\n…[truncated]")
        # The query and the final answer survive: they define the scenario.
        assert "查询 A 公司融资" in rendered
        assert "结论：共 3 轮融资" in rendered

    def test_hard_truncates_when_query_and_answer_alone_overflow(self):
        trajectory = RunTrajectory(query="问" * 2000, skill_names=(), tool_steps=(), final_answer="答" * 2000, todo_texts=())
        rendered = render_trajectory(trajectory, max_chars=500)

        assert len(rendered) <= 500 + len("\n…[truncated]")
