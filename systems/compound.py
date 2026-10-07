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
from urllib import request

from pydantic import BaseModel, Field

from p1 import Answer, Request, Candidate, call_json, step #Clsses, function #function
from p1.render import render_request #function
from p1.render import render_candidate

VARIANT = "compound"


class Choice(BaseModel):
    """The step's output. You label a step in the course app by its fields that have fixed choices: here `pick`,
    which is a letter or null. Free text such as `explanation` isn't labeled. Give each of your model steps at least
    one such field, e.g. a Literal, a bool or a number."""
    pick: Optional[Literal["A", "B", "C", "D", "E"]] = Field(description="A candidate's letter, or null to decline")
    explanation: str

class Requirements(BaseModel):
    """ Extracted requirements from a request """
    min_age: int | None = Field(default=None, description="Minimum age of players")
    have: list[str] = Field(default_factory=list) #ommited fields default to []
    avoid: list[str] = Field(default_factory=list)
    wish: list[str] = Field(default_factory=list)

class DecisionInput(BaseModel):
    requirements: Requirements
    candidates: list[Candidate]


@step
def extract_requirements(request: Request) -> Requirements:

    request_only = request.request

    INSTRUCTIONS = """You are given a request for a game, and you need to extract the requirements.
	
    Only use the information available in the request, do not scrape beyond or use insider previously known information to make requirements. The extracted information is:

    have: Characteristics the game MUST have. Empty if none is mentioned.
    avoid: Characteristics the game MUST explicitely avoid. Empty if none is mentioned.
    wish: Characteristics that are NOT in the previous categories (have nor avoid) AND that WOULD be nice to have, but are not mandatory. Empty if none is mentioned.
    min_age: The youngest player's age. Use null if not specified.

	"""

    FORMAT = """Return only a JSON object with exactly these keys:
    - "have": an array of strings.
    - "avoid": an array of strings.
    - "wish": an array of strings.
    - "min_age": an integer or null when unspecified.

    Put each have, avoid or wish characteristics in a separate string.
    Use [] for empty have, avoid, and wish lists.
    Use an integer for min_age, or null when unspecified.
    Do not include Markdown formatting.

    Example structure:
    {
    "have": ["supports 4 players"],
    "avoid": ["combat", "competitive game"],
    "wish": [],
    "min_age": 10
    }
    
    """  

    prompt = (INSTRUCTIONS + "\n\n" + FORMAT + "\n\n" + request_only)
    return call_json(prompt, Requirements) #calls the model, return output as a Requirement object


@step
def decide(data: DecisionInput) -> Choice:

    have = data.requirements.have
    avoid = data.requirements.avoid
    min_age = data.requirements.min_age
    candidates = data.candidates

    candidates_text = "\n\n".join(render_candidate(candidate) for candidate in candidates)
    
    instructions = f"""You will receive a request for a game and a list of 5 candidate games and the goal is to recommend a game that fits the user requirements.
    
    The request containts these fields:
    - have: a list of characteristics the game MUST have, empty if none.
    - avoid: a list of characteristics the game MUST explicitely avoid, empty if none.
    - min_age: The youngest player's age. None means unspecified.

    The candidate games contain these fields: id, name, year, description, and a fact card. The fact card containts fields: players, play time, minimum age, complexity for each game (where the weight is the "difficulty" from 1 to 5 where 1 is low difficulty and 5 is the highest difficulty), type, category, and mechanics.

    For each candidate game, label it as one of the following:
	- ACCEPT: if every "have" requirement is met, and every "avoid" requirement is not present in the game, and the minimum age requirement is met.
	- BREAK: If it does not meet at least one "have" requirement or it has at least one "avoid" requirement or it does not meet the minimum age requirement.
	- CAN'T TELL: If it is not ACCEPT, not BREAK, and if any "have" or any "avoid" requirement or the minimum age requirement cannot be confirmed from the candidate information.

    Information about type of requirements (could be present or not in the request):
	- Players: The number of players must fit within the range of the game description. Count everyone playing, including the writer and that number must be inside the game's range. Example: "me and my three friends" is equivalent to 4 players.
	- Time: The game's longest listed time must fit the user's requirements. For example, if the game lasts from 30-60 minutes, this would exceed a user requirement of "max 45 minutes." The game must be up to this range and not exceed the limits. If the user specifies:  "up to x minutes", the game suggested must not exceed "x" minutes, even if it is a range. 
	- Complexity: Measure the complexity by contextual clues. For example, if there are specific things such as "easy" this clearly denotes a game of level of range 1.0-1.3. "Difficult" would denote something of a score of 4.0 or more. The medium difficulty is assigned when the game is neither light or heavy and has a weight between 2.0 and 3.5. Otherwise, If the difficulty cannot be determined this is labeled as "CAN'T TELL." The complexity decision, when there are no easy to capture words such as "easy" or "very difficult" is decided based on accumulating contextual clues. Hard rules for complexity:
		* Label "LIGHT" if the weight is 1.3 or less. Or, if it is a children's or party game, or a family game with weight under 2.0.
		* label "HEAVY" if the weight is 4.0 or more. Otherwise, if the description says the rules are complex or for experienced players, or it is a strategy or war game (not also family) with weight 3.5 or more.
		* Medium: only if it is neither light nor heavy and its weight is between 2.0 and 3.5.
	- Age requirement: If the youngest player's age is specified, the game's listed minimum age must be less than or equal to that age. If the player's age is unspecified, skip this check. For example, a game rated 12+ fails for a youngest player aged 10.
	- Cooperative vs Competitive: A game whose mechanics include "Cooperative Game" is cooperative, and a game without it is competitive.

    Labeling Guidelines:
        - only use the given information and do not scrape beyond or use insider previously known information.
        - If a requirement definitely fails, mark BREAK. Otherwise, if a requirement cannot be confirmed, mark CAN'T TELL.
        - Check each game against each requirement one by one, then assign ACCEPT, BREAK or CAN'T TELL.
        - Pick any ONE ACCEPT game. Never pick a BREAK or CAN'T TELL game. If no game is ACCEPT, decline (select none).
        - You must ONLY pick acceptable game(s). Never a "Breaks" or "Can't Tell"

    Return only a JSON object with exactly these keys:
    - "pick": letter (id) of the selected game or null if none is acceptable
    - "explanation": one or two sentences

    Example structure:
    {{
        "pick": "A",
        "explanation": "Game A meets all the requirements."
    }}

    REQUEST TO EVALUATE:
    - have: {have}
    - avoid: {avoid}
    - min_age: {min_age}

    CANDIDATE GAMES TO EVALUATE:
    {candidates_text}
    """


    if not instructions:
        raise NotImplementedError("Write the instructions for the decide step in systems/compound.py first.")
    prompt = instructions
    return call_json(prompt, Choice)



def answer(request: Request) -> Answer: #FINAL OUTPUT
    # 1. MODEL CALL: extract requirements
    requirements = extract_requirements(request) # Returns a Requirements object
    # 2. MODEL CALL: pick game
    candidates = request.candidates
    decision_input = DecisionInput(requirements=requirements, candidates=candidates)
    choice = decide(decision_input) # Returns a Choice object

    return Answer(pick=choice.pick, explanation=choice.explanation)
