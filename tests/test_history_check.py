"""The history checker on small histories written by hand. No database.

Each history here is short enough to check by eye. Together they show that
the checker uses real time, treats a call with no answer as may have happened,
reads the stored state and reports each kind of violation it names.
"""

from __future__ import annotations

import pytest

from history_check import Answer, Call, Stored, check
from workflow_model import Request

USERS = {"alex": "u-alex", "sam": "u-sam", "casey": "u-casey"}
ROW = {"reference": "R-1", "summary": "s", "details": "d", "status": "open", "priority": "normal",
       "assignee_id": None, "resolution": None, "version": 1}
START = ("R-1", "s", "d", "open", "normal", None, None, 1)


def view(version, assignee=None, status="open", resolution=None):
    return ("R-1", "s", "d", status, "normal", assignee, resolution, version)


def assign(key, version, assignee, actor="alex"):
    return Request("assign", actor, key, target="R-1", expected_version=version, assignee_id=assignee)


def read(actor="casey"):
    return Request("read", actor, "", target="R-1")


def done(view_):
    return Answer(200, view=view_, replayed=False)


def conflict(current):
    return Answer(409, code="version_conflict", current_version=current, replayed=False)


def stored(view_, events, receipts):
    return {"R-1": Stored(view_, tuple(events), tuple(receipts))}


def assigned(version, actor, assignee):
    return ("assigned", version, USERS[actor], assignee, None)


def test_two_overlapping_edits_pass_in_the_order_that_explains_them():
    # Sam's call was sent first, but both were in flight together, so the
    # checker may place Alex's first, which is the only order that fits.
    calls = [Call(1, assign("k1", 1, "u-sam", "sam"), invoked=0, returned=10, answer=conflict(2)),
             Call(2, assign("k2", 1, "u-alex"), invoked=1, returned=9, answer=done(view(2, "u-alex")))]
    result = check(USERS, [ROW], calls, stored(
        view(2, "u-alex"), [assigned(2, "alex", "u-alex")],
        [("alex", "k2", 200, view(2, "u-alex")), ("sam", "k1", 409, "version_conflict")]))
    assert result.ok and result.orders == {"R-1": [2, 1]}


def test_real_time_forbids_the_order_that_would_explain_the_answers():
    # The same answers, but Sam's call came back before Alex's was sent. Sam's
    # call must go first, the model then gives it the success, and no order fits.
    calls = [Call(1, assign("k1", 1, "u-sam", "sam"), invoked=0, returned=5, answer=conflict(2)),
             Call(2, assign("k2", 1, "u-alex"), invoked=6, returned=9, answer=done(view(2, "u-alex")))]
    result = check(USERS, [ROW], calls, stored(
        view(2, "u-alex"), [assigned(2, "alex", "u-alex")],
        [("alex", "k2", 200, view(2, "u-alex")), ("sam", "k1", 409, "version_conflict")]))
    assert result.kind == "no_order"
    assert "call 1 sam assign R-1 from version 1 answered 409 version_conflict where the model answers 200" in result.detail


def test_a_call_with_no_answer_may_have_happened():
    lost = Call(1, assign("k1", 1, "u-sam"), invoked=0)
    later = Call(2, read(), invoked=5, returned=6, answer=Answer(200, view=view(2, "u-sam")))
    result = check(USERS, [ROW], [lost, later], stored(
        view(2, "u-sam"), [assigned(2, "alex", "u-sam")], [("alex", "k1", 200, view(2, "u-sam"))]))
    assert result.ok and result.orders == {"R-1": [1, 2]}


def test_a_call_with_no_answer_may_also_not_have_happened():
    lost = Call(1, assign("k1", 1, "u-sam"), invoked=0)
    later = Call(2, read(), invoked=5, returned=6, answer=Answer(200, view=START))
    result = check(USERS, [ROW], [lost, later], stored(START, [], []))
    assert result.ok and result.orders == {"R-1": [2]}


def test_a_lost_call_whose_only_trace_is_a_saved_refusal_is_placed_to_explain_it():
    lost = Call(1, assign("k1", 5, "u-sam"), invoked=0)
    refusal = ("alex", "k1", 409, "version_conflict")
    assert check(USERS, [ROW], [lost], stored(START, [], [refusal])).orders == {"R-1": [1]}
    assert check(USERS, [ROW], [lost], stored(START, [], [])).orders == {"R-1": []}


def test_a_retry_after_a_lost_answer_is_a_replay_only_if_the_first_call_happened():
    lost = Call(1, assign("k1", 1, "u-sam"), invoked=0)
    replayed = Answer(200, view=view(2, "u-sam"), replayed=True)
    retry = Call(2, assign("k1", 1, "u-sam"), invoked=5, returned=6, answer=replayed)
    after = stored(view(2, "u-sam"), [assigned(2, "alex", "u-sam")], [("alex", "k1", 200, view(2, "u-sam"))])
    assert check(USERS, [ROW], [lost, retry], after).orders == {"R-1": [1, 2]}
    fresh = Call(2, assign("k1", 1, "u-sam"), invoked=5, returned=6, answer=done(view(2, "u-sam")))
    assert check(USERS, [ROW], [lost, fresh], after).orders == {"R-1": [2]}


def test_an_unconfirmed_answer_is_a_violation():
    calls = [Call(1, assign("k1", 1, "u-sam"), invoked=0, returned=5,
                  answer=Answer(500, code="internal_error"))]
    result = check(USERS, [ROW], calls, stored(START, [], []))
    assert result.kind == "unconfirmed_answer"


def test_two_new_changes_for_one_key_are_a_violation():
    calls = [Call(1, assign("k1", 1, "u-sam"), invoked=0, returned=5, answer=done(view(2, "u-sam"))),
             Call(2, assign("k1", 1, "u-sam"), invoked=0, returned=6, answer=done(view(2, "u-sam")))]
    result = check(USERS, [ROW], calls, stored(view(2, "u-sam"), [], []))
    assert result.kind == "duplicate_effect"


def test_a_stale_version_that_succeeds_has_no_order():
    # What a server without the version check would answer.
    first = Call(1, assign("k1", 1, "u-sam"), invoked=0, returned=5, answer=done(view(2, "u-sam")))
    stale = Call(2, assign("k2", 1, "u-alex", "sam"), invoked=6, returned=9, answer=done(view(3, "u-alex")))
    result = check(USERS, [ROW], [first, stale], stored(
        view(3, "u-alex"), [assigned(2, "alex", "u-sam"), assigned(3, "sam", "u-alex")],
        [("alex", "k1", 200, view(2, "u-sam")), ("sam", "k2", 200, view(3, "u-alex"))]))
    assert result.kind == "no_order"


def test_answers_that_fit_still_fail_when_the_stored_state_differs():
    calls = [Call(1, assign("k1", 1, "u-sam"), invoked=0, returned=5, answer=done(view(2, "u-sam")))]
    two_events = [assigned(2, "alex", "u-sam"), assigned(2, "alex", "u-sam")]
    result = check(USERS, [ROW], calls, stored(
        view(2, "u-sam"), two_events, [("alex", "k1", 200, view(2, "u-sam"))]))
    assert result.kind == "stored_state"


def test_a_receipt_for_a_key_no_call_used_is_a_violation():
    result = check(USERS, [ROW], [], {"R-1": Stored(START, (), ()),
                                       "unknown key": Stored(None, (), (("alex", "k9", 200, START),))})
    assert result.kind == "stored_state"


def test_an_untouched_exception_must_read_back_as_it_started():
    assert check(USERS, [ROW], [], stored(START, [], [])).ok
    assert check(USERS, [ROW], [], stored(view(2, "u-sam"), [], [])).kind == "stored_state"


def test_a_key_shared_by_two_exceptions_is_refused_rather_than_split():
    other = {**ROW, "reference": "R-2"}
    calls = [Call(1, assign("k1", 1, None), invoked=0, returned=5, answer=done(view(2))),
             Call(2, Request("assign", "alex", "k1", target="R-2", expected_version=1, assignee_id=None),
                  invoked=6, returned=9, answer=Answer(409, code="idempotency_conflict"))]
    with pytest.raises(ValueError, match="cannot be split by exception"):
        check(USERS, [ROW, other], calls, {})
