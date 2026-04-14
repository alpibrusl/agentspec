"""Agent gym — isolated tuning and testing of agents.

Load a `.agent` spec, run it against a task fixture in a throwaway
worktree, and score the result against assertions. Used for tuning
soul/skills/tools without burning real sprints.
"""

from agentspec.gym.assertions import AssertionResult, run_assertions
from agentspec.gym.runner import BatchSummary, GymResult, discover_corpus, run_corpus, run_task
from agentspec.gym.task import Task, load_task

__all__ = [
    "AssertionResult",
    "BatchSummary",
    "GymResult",
    "Task",
    "discover_corpus",
    "load_task",
    "run_assertions",
    "run_corpus",
    "run_task",
]
