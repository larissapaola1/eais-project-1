"""The compound variant: your system, built from declared steps.

The rules (the README has the details):
1. Every model call happens inside a step declared with @step.
2. A step takes one pydantic model and returns one pydantic model. You define these types; the declared types are
   the step's contract, and the starter code checks them on every call.
3. At most 10 model calls per request, and no data other than the request and its candidates.
4. `answer` takes a Request and returns an Answer, the same as the single-call variant. Plain Python between steps
   is fine.

The example below shows one step, and its instructions are yours to write. Replace it with your own design:
Milestone 2 needs at least 2 connected model steps. To check, run `python -m p1.contracts systems/compound.py`.
"""
from typing import Literal, Optional

from pydantic import BaseModel, Field

from p1 import Answer, Request, call_json, step #Clsses, function #function
from p1.render import render_request #function

VARIANT = "compound"


class Choice(BaseModel):
    """The step's output. You label a step in the course app by its fields that have fixed choices: here `pick`,
    which is a letter or null. Free text such as `explanation` isn't labeled. Give each of your model steps at least
    one such field, e.g. a Literal, a bool or a number."""
    pick: Optional[Literal["A", "B", "C", "D", "E"]] = Field(description="A candidate's letter, or null to decline")
    explanation: str


@step
def decide(request: Request) -> Choice:
    instructions = """
You will receive the BoardGameGeek's description of the game, the fact card with players, play time, minimum age, and the complexity for each game which is the weight of "difficulty" from 1 to 5 where 1 is low difficulty and 5 is the highest difficulty. 

For each request, label each game: 
	- ACCEPT: if it meets every requirement
	- BREAK: If it fails at least one requirement or more. 
	- CAN'T TELL: if it fails none, but at least one requirement cannot be checked from the card or description

Requirements (only if the request asks):
	- Players: The number of players must fit within the range of the game description. Count everyone playing, including the writer and that number must be inside the game's range. Example: "me and my three friends" is equivalent to 4 players.
	- Time: The game's longest listed time must fit the user's requirements. For example, if the game lasts from 30-60 minutes, this would exceed a user requirement of "max 45 minutes." The game must be up to this range and not exceed the limits. If the user specifies:  "up to x minutes", the game suggested must not exceed "x" minutes, even if it is a range. 
	- Complexity: Measure the complexity by contextual clues. For example, if there are specific things such as "easy" this clearly denotes a game of level of range 1.0-1.3. "Difficult" would denote something of a score of 4.0 or more. The medium difficulty is assigned when the game is neither light or heavy and has a weight between 2.0 and 3.5. Otherwise, If the difficulty cannot be determined this is labeled as "CAN'T TELL." The complexity decision, when there are no easy to capture words such as "easy" or "very difficult" is decided based on accumulating contextual clues. 
	Here are the hard rules: 
		* Label "LIGHT" if the weight is 1.3 or less. Or, if it is a children's or party game, or a family game with weight under 2.0.
		* label "HEAVY" if the weight is 4.0 or more. Otherwise, if the description says the rules are complex or for experienced players, or it is a strategy or war game (not also family) with weight 3.5 or more.
		* Medium: only if it is neither light nor heavy and its weight is between 2.0 and 3.5.
	- Make sure the "things to HAVE" and "things to AVOID" are all, individually, met. For example, if there is a requirement such as "avoid violence" the game fits if it does not have "violence" In short: The game BREAKS if the card has the tag or the description shows the feature as part of the game, otherwise it passes. Examples: 
		* Age requirement: make sure to meet minimum age requirement
		* Cooperative vs Competitive: A game whose mechanics include "Cooperative Game" is cooperative, and a game without it is competitive.
		* Tag: consider the tag of the game and if it matches or meets one of the "things to avoid" or "things to have"/requirement to meet. 

Labeling Guidelines
	- only use the information available in the "fact card and description." do not scrape beyond or use insider previously known information to make suggestions. Use ONLY the card and the description for evaluation.
	- if you cannot confirm a requirement, mark the game as "can't tell"
	- wishes are NOT requirements. do not consider them, or weigh them against the requirements. Ignore them. 
	- if no game is acceptable, decline
	- Check each game against each requirement one by one, then assign ACCEPT, BREAK or CAN'T TELL.
	- Pick any ONE ACCEPT game. Never pick a BREAK or CAN'T TELL game. If no game is ACCEPT, decline.

You must ONLY pick acceptable game(s). Never a "Breaks" or "Can't Tell"
"""  # your instructions for this step


    if not instructions:
        raise NotImplementedError("Write the instructions for the decide step in systems/compound.py first.")
    prompt = (instructions + "\n\n"
              "Answer with JSON only: {\"pick\": \"<letter or null>\", \"explanation\": \"<one or two sentences>\"}\n\n"
              + render_request(request))
    return call_json(prompt, Choice)


def answer(request: Request) -> Answer: #FINAL OUTPUT
    choice = decide(request) #returns Choice object
    return Answer(pick=choice.pick, explanation=choice.explanation)
