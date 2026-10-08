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
from typing import Literal

from pydantic import BaseModel, Field

from p1 import Answer, Request, Candidate, call_json, step #Clsses, function #function
from p1.render import render_candidate

VARIANT = "compound"

class Requirements(BaseModel):
    """ Extracted requirements from a request """
    players: int | None = Field(default=None, ge=1) # if integer is provided, should be >= 1
    max_minutes: int | None = Field(default=None, ge=1)
    min_age: int | None = Field(default=None, description="Youngest player's age")
    mode: Literal["cooperative", "competitive"] | None = None
    have: list[str] = Field(default_factory=list) # ommited fields default to []
    avoid: list[str] = Field(default_factory=list)
    wish: list[str] = Field(default_factory=list)

class DecisionInput(BaseModel):
    requirements: Requirements
    candidate: Candidate


class GameEvaluation(BaseModel):
    """PASS means met (or not requested); UNKNOWN means not enough evidence."""
    players: Literal["PASS", "FAIL", "UNKNOWN"]
    max_minutes: Literal["PASS", "FAIL", "UNKNOWN"]
    min_age: Literal["PASS", "FAIL", "UNKNOWN"]
    have: list[Literal["PASS", "FAIL", "UNKNOWN"]]
    avoid: list[Literal["PASS", "FAIL", "UNKNOWN"]]
    explanation: str


@step
def extract_requirements(request: Request) -> Requirements:

    request_only = request.request

    INSTRUCTIONS = """You are given a request for a game, and you need to extract the requirements.
	
    Only use the information available in the request, do not scrape beyond or use insider previously known information to make requirements. The extracted information is:

    have: Characteristics the game MUST have. Empty if none is mentioned.
    avoid: Characteristics the game MUST explicitely avoid. Empty if none is mentioned.
    wish: Characteristics that are NOT in the previous categories (have nor avoid) AND that WOULD be nice to have, but are not mandatory. Empty if none is mentioned.
    players: The number of people playing, or null if unspecified.
    max_minutes: The maximum play time in minutes, or null if unspecified.
    min_age: The youngest player's age. Use null if not specified.

    Before answering, check every category below. Do not omit a requirement just because it appears in the background of the request rather than in a sentence saying "must".
    - Players: count everyone playing, including the writer. "My wife and I" means 2;
      "game night with six friends" means 7; "six of us" means 6.
      Put the number in players, not in have.
    - Time: put the maximum minutes in max_minutes, not in have. "About an hour" and "an hour tops"
      both mean "maximum 60 minutes"; two hours means 120 minutes.
    - Complexity: put "light complexity" for easy rules, simple, beginners or casual players;
      "heavy complexity" for deep strategy, meaty or nothing light;
      "medium complexity" for not too simple and not too heavy.
    - Cooperative or competitive: put the requested mode in mode, not in have.
      Playing together against the game means cooperative; head to head means competitive.
      Just playing together, being friends or being a couple does NOT imply cooperative.
      If no mode is requested, set mode to null.
    - Things to avoid: put fighting, violence, horror, timers or player elimination in avoid when requested. "Nobody sitting out" means avoid player elimination.
    - Age: record the youngest explicitly stated player age in min_age. Do not guess an age.
    - "We want" and "we need" introduce requirements, not wishes.
    - Wishes: "would be nice", "would be amazing" and "we'd love" introduce wishes.
      Keep the whole optional preference in wish, including details that explain it.
      Mentioning a previously enjoyed game does not make its features mandatory.
    Keep any other explicit mandatory requirements. Do not invent requirements.
    Check the original request once more for missed player counts or time limits.

	"""

    FORMAT = """Return only a JSON object with exactly these keys:
    - "have": an array of strings.
    - "avoid": an array of strings.
    - "wish": an array of strings.
    - "min_age": an integer or null when unspecified.
    - "players": an integer or null when unspecified.
    - "max_minutes": an integer or null when unspecified.
    - "mode": "cooperative", "competitive", or null when unspecified.

    Put each have, avoid or wish characteristics in a separate string.
    Use [] for empty have, avoid, and wish lists.
    Use an integer for min_age, or null when unspecified.
    Do not include Markdown formatting.

    Example structure:
    {
    "have": ["light complexity"],
    "avoid": ["fighting"],
    "wish": [],
    "min_age": 10,
    "players": 4,
    "max_minutes": 60,
    "mode": null
    }
    
    """  

    prompt = (INSTRUCTIONS + "\n\n" + FORMAT + "\n\n" + request_only)
    return call_json(prompt, Requirements) #calls the model, return output as a Requirement object


@step
def decide(data: DecisionInput) -> GameEvaluation:

    have = data.requirements.have
    avoid = data.requirements.avoid
    min_age = data.requirements.min_age
    candidate_text = render_candidate(data.candidate)
    
    instructions = f"""You will receive extracted requirements and ONE candidate game. Evaluate this game against each requirement. Python will select the game.
    
    The request containts these fields:
    - players: required player count, None if unspecified.
    - max_minutes: maximum play time, None if unspecified.
    - have: a list of characteristics the game MUST have, empty if none.
    - avoid: a list of characteristics the game MUST explicitely avoid, empty if none.
    - min_age: The youngest player's age. None means unspecified.

    The candidate game contains these fields: id, name, year, description, and a fact card. The fact card containts fields: players, play time, minimum age, complexity for each game (where the weight is the "difficulty" from 1 to 5 where 1 is low difficulty and 5 is the highest difficulty), type, category, and mechanics.

    Evaluate each requirement separately:
- PASS: this requirement is met, or it was not requested.
- FAIL: this requirement is definitely broken.
- UNKNOWN: there is not enough information to check this requirement.

    Information about type of requirements (could be present or not in the request):
	- Players: The number of players must fit within the range of the game description. Count everyone playing, including the writer and that number must be inside the game's range. Example: "me and my three friends" is equivalent to 4 players.
	- Time: The game's longest listed time must fit the user's requirements. For example, if the game lasts from 30-60 minutes, this would exceed a user requirement of "max 45 minutes." The game must be up to this range and not exceed the limits. If the user specifies:  "up to x minutes", the game suggested must not exceed "x" minutes, even if it is a range. 
    - Complexity: apply these rubric rules, not an intuitive estimate of difficulty.
        * Weight 1.3 or less means light and not heavy; weight 4.0 or more means
          heavy and not light. These extremes override all other clues.
        * Otherwise, light YES clues: easy/simple rules in the description; children's
          or party game type; family game type with weight under 2.0.
          Light NO clues: complex rules or experienced players in the description;
          only strategy/thematic/war/abstract types with weight at least 2.5.
        * Heavy YES clues: complex rules or experienced players in the description;
          strategy or war game, not also family, with weight at least 3.5.
          Heavy NO clues: easy/simple rules in the description; children's, party or
          family game type.
        * For light and heavy separately, conflicting clues or no applicable clues
          mean UNKNOWN. If complexity is not listed, only description wording can decide.
        * Medium: reject if light or heavy under the rules above. Otherwise, medium
          requires a weight between 2.0 and 3.5; outside that band or without a weight,
          medium is UNKNOWN.
        * Description comparisons such as "lighter than similar games" count.
          "Easy to learn but challenging to master" does not decide. Ignore difficulty
          of winning, optional expert variants, one small rule, edition changes and
          marketing audience. Use the card's game types for family/party classification.
	- Age requirement: If the youngest player's age is specified, the game's listed minimum age must be less than or equal to that age. If the player's age is unspecified, skip this check. For example, a game rated 12+ fails for a youngest player aged 10.
	- Cooperative vs Competitive: A game whose mechanics include "Cooperative Game" is cooperative, and a game without it is competitive.

    Missing information:
        - Use the card's player range, maximum play time and minimum age. If a required field is missing, look for that information in the description. If neither gives it, mark UNKNOWN. Learning time is not play time, and separately sold expansions do not count toward the supported player count.

    Things to avoid:
        - A matching tag always counts: Fighting for fighting; Wargame or fighting for violence; Horror or Zombies for horror; Real-time category or Real-Time
          mechanic for timers; Player Elimination mechanic for elimination.
        - The description can also show a feature without a tag. Judge actual gameplay, not an isolated word: disease-fighting is not combat, and fast-paced is not a timer.
        - Fighting means characters or creatures attacking each other. Army battles,
          raiding and killing count as violence; fighting also counts as violence.
        - Fighting, violence and horror are separate. Fighting or a Wargame tag alone
          does not imply horror. Check only the feature the user prohibited.
        - Horror means frightening content, not just a fantasy creature or harmless ghost.
          A timer includes timed turns and simultaneous speed play.
          Elimination includes sitting out a round, but not losing pieces while still playing.
        - Empty tag lists are not hidden information. If neither tags nor description
          show a prohibited feature, that avoidance requirement passes.

    Labeling Guidelines:
        - only use the given information and do not scrape beyond or use insider previously known information.
        - If a requirement definitely fails, mark FAIL. Otherwise, if a requirement cannot be confirmed, mark UNKNOWN.
        - Check this game against EVERY requirement. A game that meets only some requirements is not acceptable.
        - Evaluate each requirement separately. PASS means it is met, FAIL means it is
          broken, UNKNOWN means there is not enough evidence to check it.
        - For players, time and age, use PASS when that requirement is unspecified.
        - For each avoid item, PASS means the prohibited feature is absent.
        - Do not choose a game. Return checks for this one game. Python checks the requested mode separately.

    Return one JSON object with these fields (do not wrap it in a candidate letter):
    - "players", "max_minutes", "min_age": each is "PASS", "FAIL" or "UNKNOWN".
    - "have": one status per have requirement, in the SAME order as the input.
    - "avoid": one status per avoid requirement, in the SAME order as the input.
    - "explanation": one plain text string, not an object or list. Example: "explanation": "The game supports four players."
    Use [] when the corresponding requirement list is empty. Do not omit checks.
    Ensure the statuses agree with the evidence in your explanation.

    REQUEST TO EVALUATE:
    - have: {have}
    - avoid: {avoid}
    - min_age: {min_age}
    - players: {data.requirements.players}
    - max_minutes: {data.requirements.max_minutes}

    CANDIDATE GAME TO EVALUATE:
    {candidate_text}
    """


    if not instructions:
        raise NotImplementedError("Write the instructions for the decide step in systems/compound.py first.")
    prompt = instructions
    return call_json(prompt, GameEvaluation, max_tokens=1000)



def answer(request: Request) -> Answer:
    # 1. MODEL CALL: extract requirements.
    requirements = extract_requirements(request)

    # 2. Five model calls: evaluate one candidate at a time.
    evaluations = []
    for candidate in request.candidates:
        decision_input = DecisionInput(requirements=requirements, candidate=candidate)
        evaluations.append(decide(decision_input))

    # 3. Python selects the first candidate whose checks all pass.
    for index in range(len(request.candidates)):
        candidate = request.candidates[index]
        evaluation = evaluations[index]
        card = candidate.card

        # Missing checks must not accidentally count as a pass.
        if len(evaluation.have) != len(requirements.have):
            continue
        if len(evaluation.avoid) != len(requirements.avoid):
            continue

        # If the card provides numbers, check them directly.
        # Otherwise keep the model's check based on the description.
        players_check = evaluation.players
        if requirements.players is None:
            players_check = "PASS"
        elif card.players:
            if card.players[0] <= requirements.players <= card.players[-1]:
                players_check = "PASS"
            else:
                players_check = "FAIL"

        time_check = evaluation.max_minutes
        if requirements.max_minutes is None:
            time_check = "PASS"
        elif card.minutes:
            if max(card.minutes) <= requirements.max_minutes:
                time_check = "PASS"
            else:
                time_check = "FAIL"

        age_check = evaluation.min_age
        if requirements.min_age is None:
            age_check = "PASS"
        elif card.age is not None:
            if card.age <= requirements.min_age:
                age_check = "PASS"
            else:
                age_check = "FAIL"

        # The rubric defines mode using this exact mechanic tag.
        mode_check = "PASS"
        cooperative = "Cooperative Game" in card.mechanics
        if requirements.mode == "cooperative" and not cooperative:
            mode_check = "FAIL"
        if requirements.mode == "competitive" and cooperative:
            mode_check = "FAIL"

        acceptable = True
        if players_check != "PASS":
            acceptable = False
        if time_check != "PASS":
            acceptable = False
        if age_check != "PASS":
            acceptable = False
        if mode_check != "PASS":
            acceptable = False
        for check in evaluation.have:
            if check != "PASS":
                acceptable = False
        for check in evaluation.avoid:
            if check != "PASS":
                acceptable = False

        if acceptable:
            # Use the final checks, not a model explanation Python may have corrected.
            explanation = candidate.name + " passed every requested requirement check."
            if requirements.players is not None and card.players:
                explanation += f" Its player range is {card.players[0]} to {card.players[-1]}."
            if requirements.max_minutes is not None and card.minutes:
                explanation += f" Its maximum listed play time is {max(card.minutes)} minutes."
            if requirements.min_age is not None and card.age is not None:
                explanation += f" Its listed minimum age is {card.age}."
            if requirements.mode is not None:
                explanation += f" It is {requirements.mode} according to its mechanics."
            return Answer(pick=candidate.id, explanation=explanation)

    return Answer(pick=None, explanation="No candidate could be confirmed to meet every requirement.")
