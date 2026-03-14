# -*- coding: utf-8 -*-
"""
ArcMind — Project State Machines (V2 Phase 1)
===============================================
Two state machines:
1. ProjectStateMachine — 10-state project lifecycle
2. PMAgentStateMachine — 10-state PM Agent lifecycle

Valid transitions are strictly enforced.
"""
from __future__ import annotations

import logging
from datetime import datetime

logger = logging.getLogger("arcmind.project_state_machine")


class ProjectStateMachine:
    """
    Project lifecycle: 10 states

    proposed → planning → in_progress → review → completed → archived → closed
                  ↓            ↓           ↓
               on_hold      on_hold    in_progress
                  ↓            ↓
              cancelled      failed
                              ↓
                           planning (retry)
    """

    TRANSITIONS = {
        "proposed":    ["planning", "cancelled"],
        "planning":    ["in_progress", "on_hold", "cancelled"],
        "in_progress": ["on_hold", "review", "failed"],
        "on_hold":     ["in_progress", "cancelled"],
        "review":      ["completed", "in_progress"],
        "completed":   ["archived", "closed"],
        "failed":      ["planning", "cancelled"],
        "archived":    ["closed"],
        "cancelled":   ["closed"],
        "closed":      [],
    }

    # Terminal states — no outgoing transitions at all
    # Note: cancelled→closed is allowed, so cancelled is NOT terminal
    TERMINAL = {"closed"}

    # Active states (project is "alive")
    ACTIVE = {"proposed", "planning", "in_progress", "on_hold", "review"}

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """Check if transition is valid."""
        valid = cls.TRANSITIONS.get(from_status, [])
        return to_status in valid

    @classmethod
    def transition(cls, from_status: str, to_status: str) -> str:
        """
        Execute transition. Returns new status.
        Raises ValueError if transition is invalid.
        """
        if not cls.can_transition(from_status, to_status):
            valid = cls.TRANSITIONS.get(from_status, [])
            raise ValueError(
                f"Invalid project transition: {from_status} → {to_status}. "
                f"Valid transitions from '{from_status}': {valid}"
            )
        logger.info("[ProjectSM] Transition: %s → %s", from_status, to_status)
        return to_status

    @classmethod
    def get_valid_transitions(cls, current_status: str) -> list[str]:
        """Get list of valid next states."""
        return list(cls.TRANSITIONS.get(current_status, []))

    @classmethod
    def is_active(cls, status: str) -> bool:
        """Check if project is in an active (non-terminal) state."""
        return status in cls.ACTIVE

    @classmethod
    def is_terminal(cls, status: str) -> bool:
        """Check if project is in a terminal state."""
        return status in cls.TERMINAL


class PMAgentStateMachine:
    """
    PM Agent lifecycle: 10 states

    idle → assigned → planning → executing → reporting → completed → idle
                         ↓           ↓           ↓
                       failed    waiting     executing
                                    ↓
                                 blocked
                                    ↓
                              failed/terminated
    """

    TRANSITIONS = {
        "idle":       ["assigned"],
        "assigned":   ["planning"],
        "planning":   ["executing", "failed"],
        "executing":  ["reporting", "waiting", "blocked", "failed"],
        "waiting":    ["executing", "blocked"],
        "blocked":    ["executing", "failed", "terminated"],
        "reporting":  ["completed", "executing"],
        "completed":  ["idle"],
        "failed":     ["idle", "terminated"],
        "terminated": [],
    }

    TERMINAL = {"terminated"}
    ACTIVE = {"assigned", "planning", "executing", "waiting", "blocked", "reporting"}

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """Check if transition is valid."""
        valid = cls.TRANSITIONS.get(from_status, [])
        return to_status in valid

    @classmethod
    def transition(cls, from_status: str, to_status: str) -> str:
        """
        Execute transition. Returns new status.
        Raises ValueError if transition is invalid.
        """
        if not cls.can_transition(from_status, to_status):
            valid = cls.TRANSITIONS.get(from_status, [])
            raise ValueError(
                f"Invalid PM Agent transition: {from_status} → {to_status}. "
                f"Valid transitions from '{from_status}': {valid}"
            )
        logger.info("[PMAgentSM] Transition: %s → %s", from_status, to_status)
        return to_status

    @classmethod
    def get_valid_transitions(cls, current_status: str) -> list[str]:
        """Get list of valid next states."""
        return list(cls.TRANSITIONS.get(current_status, []))

    @classmethod
    def is_active(cls, status: str) -> bool:
        """Check if PM Agent is in an active state."""
        return status in cls.ACTIVE
