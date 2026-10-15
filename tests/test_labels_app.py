"""`python -m p1.labels send` and `pull` against a fake course app: no model, no network."""
import http.server
import json
import threading
from pathlib import Path
from typing import Literal, Optional

import pytest
from pydantic import BaseModel, Field

from p1 import Answer, Request, call_json, labels, llm, run, step, trace
from p1.types import Complexity
from p1.app import fill, labeled_paths
from p1.io import read_jsonl
from p1.steps import stand_in

ROOT = Path(__file__).resolve().parent.parent
REAL_COMPLETE = llm._complete
REQUESTS = ROOT / "data" / "public.jsonl"


# ---- two small designs: one step per game, and two steps where the second depends on the first ----
class GameQuestion(BaseModel):
    request: str
    game: str


class Fit(BaseModel):
    fits: Literal["yes", "no", "unsure"]
    reason: str = ""


class per_game:
    VARIANT = "compound"

    @staticmethod
    @step(name="screen")
    def screen(q: GameQuestion) -> Fit:
        return call_json(f"does {q.game} fit {q.request}?", Fit)

    @staticmethod
    def answer(request: Request) -> Answer:
        fits = [per_game.screen(GameQuestion(request=request.request, game=c.id)) for c in request.candidates]
        yes = [c.id for c, f in zip(request.candidates, fits) if f.fits == "yes"]
        return Answer(pick=yes[0] if yes else None, explanation="toy")


class Needs(BaseModel):
    players: Optional[int] = Field(None, description="How many play")
    mood: Literal["light", "heavy"]
    wish: Optional[str] = None


class Check(BaseModel):
    needs: Needs
    game: str


class chained:
    VARIANT = "compound"

    @staticmethod
    @step(name="read_request")
    def read_request(request: Request) -> Needs:
        return call_json(f"read {request.request}", Needs)

    @staticmethod
    @step(name="check")
    def check(c: Check) -> Fit:
        return call_json(f"check {c.game}", Fit)

    @staticmethod
    def answer(request: Request) -> Answer:
        needs = chained.read_request(request)
        fits = [chained.check(Check(needs=needs, game=c.id)) for c in request.candidates[:2]]
        yes = [f for f in fits if f.fits == "yes"]
        return Answer(pick=request.candidates[0].id if yes else None, explanation="toy")


class per_weight:
    """One step per game that reads the game's complexity, whose weight can be a whole number such as 1.0."""
    VARIANT = "compound"

    @staticmethod
    @step(name="weigh")
    def weigh(c: Complexity) -> Fit:
        return call_json(f"is a weight of {c.weight} light?", Fit)

    @staticmethod
    def answer(request: Request) -> Answer:
        light = [c.id for c in request.candidates if c.card.complexity and per_weight.weigh(c.card.complexity).fits == "yes"]
        return Answer(pick=light[0] if light else None, explanation="toy")


# ---- a fake course app ----
def as_javascript(value):
    """A JSON value as the course app returns it: it reads and writes JSON with JavaScript, which writes 1.0 as 1."""
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, dict):
        return {k: as_javascript(v) for k, v in value.items()}
    if isinstance(value, list):
        return [as_javascript(v) for v in value]
    return value


class FakeApp:
    def __init__(self):
        self.items, self.labels, self.schemas = [], {}, {}  # labels: (step, id, input key) -> value
        self.declared = []  # each upload's declared steps
        self.stale = None  # the requests whose later-step inputs are out of date, as the app reports them

    def handler(app):
        class H(http.server.BaseHTTPRequestHandler):
            def _send(self, status, body):
                data = json.dumps(body).encode()
                self.send_response(status)
                self.send_header("content-type", "application/json")
                self.send_header("content-length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):
                assert self.headers["authorization"] == "Bearer p1_test"
                rows = [{"step": s, "id": rid, "call": 0, "input": as_javascript(json.loads(k)), "label": v, "current": True,
                         "saved_by": "Ana"}
                        for (s, rid, k), v in app.labels.items()]
                body = {"steps": {s: app.schemas[s] for s, _, _ in app.labels}, "labels": rows}
                if app.stale is not None:
                    body["stale"] = app.stale
                self._send(200, body)

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["content-length"])))
                app.schemas.update(body["steps"])
                app.items.append(body["items"])
                app.declared.append(body.get("declared"))
                self._send(200, {"sent": len(body["items"]), "added": len(body["items"]), "steps": {}})

            def log_message(self, *a):
                pass
        return H


@pytest.fixture
def fake_app(monkeypatch):
    app = FakeApp()
    server = http.server.HTTPServer(("127.0.0.1", 0), app.handler())
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("P1_ENDPOINT", f"http://127.0.0.1:{server.server_port}/api/p1")
    monkeypatch.setenv("P1_TOKEN", "p1_test")
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: pytest.fail("a model call was made while sending inputs"))
    yield app
    server.shutdown()


def system_file(tmp_path, name):
    """A system file that runs one of the toy designs above."""
    f = tmp_path / f"{name}.py"
    f.write_text(f"from tests.test_labels_app import {name} as s\nVARIANT = s.VARIANT\nanswer = s.answer\n")
    return str(f)


def test_send_reaches_every_call_of_a_step_without_the_model(fake_app, tmp_path):
    said = []
    result = labels.send(system_file(tmp_path, "per_game"), str(REQUESTS), limit=3, out=said.append)
    assert result == {"sent": 15, "added": 15, "waiting": 0}
    items = fake_app.items[0]
    assert {i["step"] for i in items} == {"screen"} and [i["call"] for i in items[:5]] == [0, 1, 2, 3, 4]
    first = [Request.model_validate(r) for r in read_jsonl(REQUESTS)][0]
    assert json.loads(items[0]["input"]) == {"request": first.request, "game": first.candidates[0].id}
    assert list(json.loads(items[0]["input"])) == ["request", "game"]  # the input type's field order
    assert fake_app.schemas["screen"] == Fit.model_json_schema()
    assert said[0] == ('We sent 15 inputs from 3 requests to the course app: 15 for your "screen" step. None of them '
                       "has a label yet. You still have to label 15, on the Labels tab of the Project 1 page.")


def test_send_waits_for_labels_on_an_earlier_step_then_sends_the_real_inputs(fake_app, tmp_path):
    system = system_file(tmp_path, "chained")
    said = []
    assert labels.send(system, str(REQUESTS), limit=2, out=said.append) == {"sent": 2, "added": 2, "waiting": 4}
    assert [i["step"] for i in fake_app.items[0]] == ["read_request", "read_request"]
    # This toy system's steps were declared when this test file was imported, before `send` loaded the system, so the
    # list of declared steps is incomplete: the upload leaves it out, and the Labels tab lists every step.
    assert fake_app.declared[0] is None
    assert said[1] == ('We didn\'t send the inputs of 4 calls to your "check" step yet, because they may depend on the '
                       'outputs of your "read_request" step, and you haven\'t labeled those yet. Label your "read_request" '
                       "step, then run this command again.")
    # The team labels read_request for both requests (free text left out, as the app stores it).
    for item in fake_app.items[0]:
        fake_app.labels[("read_request", item["request_id"], trace.input_key(json.loads(item["input"])))] = {"players": 4, "mood": "light"}
    said.clear()
    assert labels.send(system, str(REQUESTS), limit=2, out=said.append)["waiting"] == 0
    second = fake_app.items[1]
    # Each request's inputs come in the order the system calls its steps. The Labels tab lists the steps in the order
    # they first appear in the latest upload, so this order must stay (alphabetical order would put check first).
    assert list(dict.fromkeys(i["step"] for i in second)) == ["read_request", "check"]
    checks = [i for i in second if i["step"] == "check"]
    assert len(checks) == 4 and "2 of them already have a label" in said[0]
    assert said[0].startswith('We sent 6 inputs from 2 requests to the course app: 2 for your "read_request" step and 4 for '
                              'your "check" step.')
    # The check inputs carry the labeled requirements, not a stand-in.
    assert json.loads(checks[0]["input"])["needs"] == {"players": 4, "mood": "light", "wish": None}


DECLARING = """
from p1 import Answer, Request, call_json, step
from tests.test_labels_app import Check, Fit, Needs

VARIANT = "compound"


@step
def shortlist(request: Request) -> Request:  # a code step: no model call
    return request


@step
def read_request(request: Request) -> Needs:
    return call_json(f"read {request.request}", Needs)


@step
def check(c: Check) -> Fit:
    return call_json(f"check {c.game}", Fit)


def answer(request: Request) -> Answer:
    needs = read_request(shortlist(request))
    fits = [check(Check(needs=needs, game=c.id)) for c in request.candidates[:2]]
    return Answer(pick=request.candidates[0].id if any(f.fits == "yes" for f in fits) else None, explanation="toy")
"""


def test_send_names_every_step_the_system_declares(fake_app, tmp_path):
    system = tmp_path / "declaring.py"
    system.write_text(DECLARING)
    assert labels.send(str(system), str(REQUESTS), limit=1, out=lambda *_: None)["waiting"] == 2
    # Only read_request had inputs to send. The upload also names check, which waits for read_request's labels, and
    # the code step, so the Labels tab keeps listing check and drops only steps that are no longer in the code.
    assert {i["step"] for i in fake_app.items[0]} == {"read_request"}
    assert fake_app.declared == [["check", "read_request", "shortlist"]]


def test_pull_writes_whole_outputs_and_the_fields_to_compare(fake_app, tmp_path, monkeypatch):
    fake_app.schemas["read_request"] = Needs.model_json_schema()
    key = trace.input_key({"request": "x"})
    fake_app.labels[("read_request", "P001", key)] = {"players": None, "mood": "heavy"}
    said = []
    assert labels.pull(str(tmp_path / "labels"), out=said.append) == {"read_request": 1}
    row = next(read_jsonl(tmp_path / "labels" / "read_request.jsonl"))
    assert row["output"] == {"players": None, "mood": "heavy", "wish": None}
    assert row["checked"] == ["players", "mood"] and row["input"] == {"request": "x"} and row["saved_by"] == "Ana"
    Needs.model_validate(row["output"])
    assert said == [f'We saved 1 label for your "read_request" step, on 1 request, in {tmp_path / "labels" / "read_request.jsonl"}.']


def test_pulled_labels_work_for_the_swap_in_and_for_step_accuracy(fake_app, tmp_path, monkeypatch):
    monkeypatch.setenv("P1_BACKEND", "fake")
    monkeypatch.setattr(llm, "_complete", REAL_COMPLETE)  # this test makes (fake) model calls on purpose
    reqs = [Request.model_validate(r) for r in list(read_jsonl(REQUESTS))[:2]]
    # Label every screen call of both requests "yes" for game A, "no" otherwise.
    for r in reqs:
        for c in r.candidates:
            fake_app.labels[("screen", r.id, trace.input_key({"request": r.request, "game": c.id}))] = {"fits": "yes" if c.id == "A" else "no"}
    fake_app.schemas["screen"] = Fit.model_json_schema()
    labels.pull(str(tmp_path / "labels"), out=lambda s: None)
    swap = run.load_overrides(tmp_path / "labels" / "screen.jsonl")
    answers = [run.run_one(per_game, r, {"screen": swap[r.id]})[0] for r in reqs]
    assert [a["pick"] for a in answers] == ["A", "A"]
    # A normal run with a model that always says "unsure", compared by input with the labels.
    monkeypatch.setattr(llm, "fake_responder", lambda prompt, system: '{"fits": "unsure", "reason": "r"}')
    out = tmp_path / "run"
    out.mkdir()
    from p1.io import write_jsonl
    write_jsonl(out / "traces.jsonl", (run.run_one(per_game, r, {})[1] for r in reqs))
    acc = labels.accuracy(str(out), "screen", str(tmp_path / "labels" / "screen.jsonl"))
    assert acc["labeled_calls"] == 10 and acc["fields"] == {"fits": {"match": 0, "of": 10, "accuracy": 0.0}}
    # Labels for a request that wasn't in the run are left out, not counted as misses.
    with open(tmp_path / "labels" / "screen.jsonl", "a") as f:
        f.write(json.dumps({"step": "screen", "id": "L01", "call": 0, "input": {"request": "x", "game": "A"},
                            "output": {"fits": "unsure", "reason": ""}, "checked": ["fits"]}) + "\n")
    acc = labels.accuracy(str(out), "screen", str(tmp_path / "labels" / "screen.jsonl"))
    assert acc["labeled_calls"] == 10 and acc["labels_not_in_run"] == 1 and acc["fields"]["fits"]["of"] == 10
    # A label for a request in the run, whose input no call had (e.g. an earlier step's label changed after `send`), is
    # left out and named, not counted as wrong with "the step returned null".
    with open(tmp_path / "labels" / "screen.jsonl", "a") as f:
        f.write(json.dumps({"step": "screen", "id": reqs[0].id, "call": 5, "input": {"request": "old", "game": "A"},
                            "output": {"fits": "yes", "reason": ""}, "checked": ["fits"]}) + "\n")
    acc = labels.accuracy(str(out), "screen", str(tmp_path / "labels" / "screen.jsonl"))
    assert acc["labeled_calls"] == 10 and acc["labels_without_call"] == [reqs[0].id] and acc["fields"]["fits"]["of"] == 10
    assert acc["all_fields_right"] == 0 and not any(m["output"] is None for m in acc["misses"])


def test_stand_in_fits_the_output_type():
    class Inner(BaseModel):
        n: int
        on: bool

    class Out(BaseModel):
        kind: Literal["a", "b"]
        maybe: Optional[str]
        items: list[Inner]
        inner: Inner
        either: int | None
        text: str
        kept: str = "default"

    assert stand_in(Out).model_dump() == {"kind": "a", "maybe": None, "items": [], "inner": {"n": 0, "on": False},
                                          "either": None, "text": "", "kept": "default"}


def test_a_step_whose_stand_in_fails_still_records_its_input(fake_app, tmp_path):
    class Strict(BaseModel):
        n: int = Field(ge=1)

    @step(name="strict")
    def strict(r: Request) -> Strict:
        return call_json("n?", Strict)

    t = trace.Trace(request_id="P001", variant="compound", max_calls=10, labeling=True)
    token = trace.start(t)
    try:
        with pytest.raises(llm.NeedsLabel):
            strict(Request.model_validate(next(read_jsonl(REQUESTS))))
    finally:
        trace.finish(token)
    assert t.records[0]["needs_label"] and t.records[0]["stand_in"] == "failed"


def test_fill_and_labeled_paths_follow_nested_types():
    class Stated(BaseModel):
        low: Optional[int] = None
        quote: Optional[str] = None

    class Reading(BaseModel):
        feature: Literal["horror", "timer"]
        shown: bool
        quote: Optional[str] = None

    class Facts(BaseModel):
        letter: Optional[str] = None
        players: Optional[Stated] = None
        note: str
        features: list[Reading] = []

    schema = Facts.model_json_schema()
    assert labeled_paths(schema) == ["players.low", "features"]
    out = fill(schema, {"players": {"low": 2}, "features": [{"feature": "horror", "shown": True}]})
    assert out == {"letter": None, "players": {"low": 2, "quote": None}, "note": "",
                   "features": [{"feature": "horror", "shown": True, "quote": None}]}
    Facts.model_validate(out)


def test_pulled_labels_match_inputs_with_whole_number_weights(fake_app, tmp_path, monkeypatch):
    # Practice request P129 has a game whose weight is a whole number (e.g. 1.0), which the app returns as 1.
    monkeypatch.setattr(llm, "_complete", lambda *a, **k: pytest.fail("a labeled call reached the model"))
    request = next(Request.model_validate(r) for r in read_jsonl(ROOT / "data" / "practice.jsonl") if r["id"] == "P129")
    weights = [c.card.complexity.weight for c in request.candidates if c.card.complexity]
    assert any(w.is_integer() for w in weights)
    for c in request.candidates:
        if c.card.complexity:
            key = trace.input_key(c.card.complexity.model_dump(mode="json"))
            fake_app.labels[("weigh", request.id, key)] = {"fits": "yes" if c.id == "C" else "no"}
    fake_app.schemas["weigh"] = Fit.model_json_schema()
    labels.pull(str(tmp_path / "labels"), out=lambda s: None)
    swap = run.load_overrides(tmp_path / "labels" / "weigh.jsonl")
    answer, _ = run.run_one(per_weight, request, {"weigh": swap[request.id]})
    assert answer["pick"] == "C"


def test_accuracy_prints_a_count_and_names_the_labels_it_left_out(fake_app, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("P1_BACKEND", "fake")
    monkeypatch.setattr(llm, "_complete", REAL_COMPLETE)  # this test makes (fake) model calls on purpose
    monkeypatch.setattr(llm, "fake_responder", lambda prompt, system: '{"fits": "yes", "reason": "r"}')
    reqs = [Request.model_validate(r) for r in list(read_jsonl(REQUESTS))[:2]]
    out = tmp_path / "run"
    out.mkdir()
    from p1.io import write_jsonl
    write_jsonl(out / "traces.jsonl", (run.run_one(per_game, r, {})[1] for r in reqs))
    rows = [{"step": "screen", "id": r.id, "call": 0, "input": {"request": r.request, "game": "A"},
             "output": {"fits": "yes", "reason": ""}, "checked": ["fits"]} for r in reqs]
    rows.append({"step": "screen", "id": reqs[1].id, "call": 9, "input": {"request": "old", "game": "A"},
                 "output": {"fits": "no", "reason": ""}, "checked": ["fits"]})
    write_jsonl(tmp_path / "screen.jsonl", rows)
    labels.main(["accuracy", str(out), "--step", "screen", "--labels", str(tmp_path / "screen.jsonl")])
    said = capsys.readouterr().out.splitlines()
    assert said[0] == 'Your "screen" step: we compared 2 calls with your labels. In 2 of them, every labeled field is right.'
    assert said[1].startswith(f'We left out 1 label ({reqs[1].id}), because no call of your "screen" step in this run had '
                              'the input you labeled.')
    assert not any("Wrong:" in line for line in said)


def test_pull_lists_the_requests_to_send_again(fake_app, tmp_path):
    fake_app.schemas["read_request"] = Needs.model_json_schema()
    fake_app.labels[("read_request", "L04", trace.input_key({"request": "x"}))] = {"players": 2, "mood": "light"}
    fake_app.stale = [{"id": i, "steps": ["read_request"]} for i in ("L04", "L07", "L08", "P007", "P001")]
    said = []
    labels.pull(str(tmp_path / "labels"), out=said.append)
    assert said[1:] == [
        "You saved labels of an earlier step after your last `send`, for L04, L07, L08, P007 and P001. Run `send` again "
        "for those requests, and we'll build your later steps' inputs from your current labels. Then label the new "
        "inputs on the Labels tab, and run `python -m p1.labels pull` again:",
        "    python -m p1.labels send systems/compound.py --requests data/labeling.jsonl",
        "    python -m p1.labels send systems/compound.py --requests data/practice.jsonl",
        "    python -m p1.labels send systems/compound.py --requests data/public.jsonl",
    ]
    fake_app.stale = []
    said = []
    labels.pull(str(tmp_path / "labels"), out=said.append)
    assert len(said) == 1  # nothing to send again: only the saved-labels line
