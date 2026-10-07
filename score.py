"""Your scorer: how many of a run's requests did your system answer right?

Run it on a run folder, from this folder:

    python score.py runs/single-1

You see how many of the run's requests are right, then the id of each request that's wrong:

    6 of 10 right
    P003
    P007
    ...

Write score() below, and keep main() as it is. When we grade your scorer, we call your score() on test runs of
our own.

When an answer counts as right:
- `answers.jsonl` in the run folder has one line per request: {"id": ..., "pick": ..., "explanation": ...}, plus
  "error" if the system failed on that request.
- The answers file, `data/public_answers.jsonl` unless you give another one, has the right answer for each request:
  {"id": ..., "correct": [...]}, the letters of the acceptable games, or an empty list when the right answer is to
  decline.
- A pick is right if it's one of the listed letters. A decline ("pick": null) is right if the list is empty.
- A request with an "error" counts as wrong.
- Count every request in the run, so a run on 10 requests is scored out of 10.

To read a .jsonl file one dict per line, you can use `read_jsonl` from `p1.io`.
"""
from __future__ import annotations

import argparse
from p1.io import read_jsonl
from pathlib import Path


def score(run_dir: str, answers: str = "data/public_answers.jsonl") -> tuple[int, int, list[str]]:
    """Score the run in run_dir against the answers file. Return (right, total, wrong_ids): the number of right
    answers, the number of requests in the run, and the ids of the wrong ones, in the run's order."""

    right = 0
    total = 0
    wrong_ids = []
    output_path = Path(run_dir) / "answers.jsonl"

    for output in read_jsonl(output_path):
        total +=1
        if "error" in output:
            wrong_ids.append(output["id"])
            continue
        for answer in read_jsonl(answers):
            if output["id"] == answer["id"]:
                if (output["pick"] is None):
                    if (answer["correct"] == []):
                        right += 1
                    else:
                        wrong_ids.append(output["id"])
                    break
                if output["pick"] in answer["correct"]:
                    right += 1
                else:
                    wrong_ids.append(output["id"])
                break
        else:
            wrong_ids.append(output["id"]) #output id wasn't found in answers
        
    return (right, total, wrong_ids)
    #raise NotImplementedError("Write score() in score.py first.")


def main() -> None:
    ap = argparse.ArgumentParser(description="Score a run: how many of its requests are right.")
    ap.add_argument("run_dir", help="a run folder, e.g. runs/single-1")
    ap.add_argument("--answers", default="data/public_answers.jsonl", help="the right answers (default: %(default)s)")
    args = ap.parse_args()
    right, total, wrong = score(args.run_dir, args.answers)
    print(f"{right} of {total} right")
    for request_id in wrong:
        print(request_id)


if __name__ == "__main__":
    main()
