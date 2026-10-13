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
    complexity: Literal["light", "medium", "heavy"] | None = None
    avoid: list[Literal["fighting", "violence", "horror", "timer", "player elimination"]] = Field(default_factory=list)
    wish: list[str] = Field(default_factory=list)


class DecisionInput(BaseModel):
    requirements: Requirements
    candidate: Candidate


class GameEvaluation(BaseModel):
    """PASS means met (or not requested); UNKNOWN means not enough evidence."""
    players: Literal["PASS", "FAIL", "UNKNOWN"]
    max_minutes: Literal["PASS", "FAIL", "UNKNOWN"]
    min_age: Literal["PASS", "FAIL", "UNKNOWN"]
    light_evidence: Literal["YES", "NO", "BOTH", "NONE"]
    heavy_evidence: Literal["YES", "NO", "BOTH", "NONE"]
    light_quotes: list[str] = Field(default_factory=list)
    heavy_quotes: list[str] = Field(default_factory=list)
    avoid: list[Literal["PASS", "FAIL", "UNKNOWN"]]
    explanation: str


def verified_evidence(candidate: Candidate, evidence: str, quotes: list[str]) -> str:
    """Discard invented/missing quotations before a live model's clues are used.

    A quote's presence is checked here; its relevance is still the model's job.
    Label overrides bypass the model step and use the human's evidence directly.
    """
    if evidence == "NONE":
        return "NONE"
    description = " ".join(candidate.description.split()).casefold()
    unique_quotes = {" ".join(quote.split()).casefold() for quote in quotes if quote.strip()}
    needed = 2 if evidence == "BOTH" else 1
    if len(unique_quotes) < needed or any(quote not in description for quote in unique_quotes):
        return "NONE"
    return evidence


def check_avoid(candidate: Candidate, avoided: str, model_check: str) -> str:
    """A rubric tag always proves presence; no tag leaves description checks intact."""
    categories = set(candidate.card.categories)
    mechanics = set(candidate.card.mechanics)
    tagged = {
        "fighting": "Fighting" in categories,
        "violence": bool(categories & {"Wargame", "Fighting"}),
        "horror": bool(categories & {"Horror", "Zombies"}),
        "timer": "Real-time" in categories or "Real-Time" in mechanics,
        "player elimination": "Player Elimination" in mechanics,
    }
    return "FAIL" if tagged.get(avoided, False) else model_check


def check_complexity(
    candidate: Candidate,
    requested: Literal["light", "medium", "heavy"] | None,
    light_evidence: str,
    heavy_evidence: str,
) -> Literal["PASS", "FAIL", "UNKNOWN"]:
    """Plain Python: apply the rubric to card facts and flat description clues."""
    if requested is None:
        return "PASS"
    card = candidate.card
    weight = card.complexity.weight if card.complexity is not None else None
    types = set(card.types)

    def combine(yes: bool, no: bool) -> Literal["YES", "NO", "UNKNOWN"]:
        if yes == no:  # Both conflicting clues and no clues mean can't tell.
            return "UNKNOWN"
        return "YES" if yes else "NO"

    # Weight extremes override every description/type clue.
    if weight is not None and weight <= 1.3:
        light, heavy = "YES", "NO"
    elif weight is not None and weight >= 4.0:
        light, heavy = "NO", "YES"
    else:
        light_yes = light_evidence in ("YES", "BOTH")
        light_no = light_evidence in ("NO", "BOTH")
        heavy_yes = heavy_evidence in ("YES", "BOTH")
        heavy_no = heavy_evidence in ("NO", "BOTH")
        # Without listed complexity, only description wording can decide.
        if weight is not None:
            light_yes |= bool(types & {"children's", "party"}) or ("family" in types and weight < 2.0)
            light_no |= bool(types) and types <= {"strategy", "thematic", "war", "abstract"} and weight >= 2.5
            heavy_yes |= bool(types & {"strategy", "war"}) and "family" not in types and weight >= 3.5
            heavy_no |= bool(types & {"children's", "party", "family"})
        light = combine(light_yes, light_no)
        heavy = combine(heavy_yes, heavy_no)

    if requested == "medium":
        if light == "YES" or heavy == "YES":
            status = "FAIL"
        elif weight is not None and 2.0 <= weight <= 3.5:
            status = "PASS"
        else:
            status = "UNKNOWN"
    else:
        classification = light if requested == "light" else heavy
        status = {"YES": "PASS", "NO": "FAIL", "UNKNOWN": "UNKNOWN"}[classification]

    return status


@step
def extract_requirements(request: Request) -> Requirements:

    request_only = request.request

    INSTRUCTIONS = """You are given a request for a game, and you need to extract the requirements.
	
    Only use the information available in the request, do not scrape beyond or use insider previously known information to make requirements. The extracted information is:

    complexity: Required complexity: light, medium, heavy, or null if unspecified.
    mode: Required mode: cooperative, competitive, or null if unspecified.
    avoid: Characteristics the game MUST explicitely avoid. Empty if none is mentioned.
    wish: Optional preferences that WOULD be nice to have, but are not mandatory. Empty if none is mentioned.
    players: The number of people playing, or null if unspecified.
    max_minutes: The maximum play time in minutes, or null if unspecified.
    min_age: The youngest player's age. Use null if not specified.

    Before answering, check every category below. Do not omit a requirement just because it appears in the background of the request rather than in a sentence saying "must".
    - Players: count everyone playing, including the writer. "My wife and I" means 2;
      "game night with six friends" means 7; "six of us" means 6.
      Put the number in players.
    - Time: put the maximum minutes in max_minutes. "About an hour" and "an hour tops"
      both mean "maximum 60 minutes"; two hours means 120 minutes.
    - Complexity: set complexity to "light" for easy rules, simple, beginners or casual players;
      "heavy" for deep strategy, meaty or nothing light;
      "medium" for not too simple and not too heavy.
      Set complexity to null when no mandatory complexity level is requested.
    - Cooperative or competitive: put the requested mode in mode.
      Playing together against the game means cooperative; head to head means competitive.
      Just playing together, being friends or being a couple does NOT imply cooperative.
      If no mode is requested, set mode to null.
    - Things to avoid: avoid lists PROHIBITED FEATURES, not desired features.
      Use only these canonical values, one per requested prohibition:
      "fighting": no fighting/no combat;
      "violence": nothing violent (also excludes fighting);
      "horror": nothing scary/nothing creepy;
      "timer": no timers/no racing against the clock;
      "player elimination": nobody knocked out/nobody sitting out.
      Do not infer a prohibition from someone waiting or being eliminated in another
      activity. Do not add a feature just because it appears in the request's background.
      Keep optional preferences in wish. No prohibition means avoid=[].
    - Age: record the youngest explicitly stated player age in min_age. Do not guess an age.
    - "We want" and "we need" introduce requirements, not wishes.
    - Wishes: "would be nice", "would be amazing" and "we'd love" introduce wishes.
      Keep the whole optional preference in wish, including details that explain it.
      Mentioning a previously enjoyed game does not make its features mandatory.
    Do not turn optional wishes into requirements. Do not invent requirements.
    Check the original request once more for missed player counts or time limits.

	"""

    FORMAT = """Return only a JSON object with exactly these keys:
    - "complexity": "light", "medium", "heavy", or null when unspecified.
    - "mode": "cooperative", "competitive", or null when unspecified.
    - "avoid": an array containing only "fighting", "violence", "horror", "timer",
      or "player elimination".
    - "wish": an array of strings.
    - "min_age": the youngest player's age as an integer, or null when unspecified.
    - "players": an integer or null when unspecified.
    - "max_minutes": an integer or null when unspecified.

    Put each avoid item or wish in a separate string. Use [] for empty lists.
    Use JSON null for unspecified complexity or mode, not the string "none".
    Do not include Markdown formatting.
    """

    prompt = (INSTRUCTIONS + "\n\n" + FORMAT + "\n\n" + request_only)
    return call_json(prompt, Requirements) #calls the model, return output as a Requirement object


@step
def decide(data: DecisionInput) -> GameEvaluation:

    complexity = data.requirements.complexity
    avoid = data.requirements.avoid
    min_age = data.requirements.min_age

    candidate_text = render_candidate(data.candidate)
    
    instructions = f"""You will receive extracted requirements and ONE candidate game. Evaluate this game against each requirement. Python will select the game.
    
    The request containts these fields:
    - players: required player count, None if unspecified.
    - max_minutes: maximum play time, None if unspecified.
    - complexity: required level: light, medium, heavy, or None if unspecified.
    - avoid: a list of characteristics the game MUST explicitely avoid, empty if none.
    - min_age: The youngest player's age. None means unspecified.

    The candidate game contains these fields: id, name, year, description, and a fact card. The fact card containts fields: players, play time, minimum age, complexity for each game (where the weight is the "difficulty" from 1 to 5 where 1 is low difficulty and 5 is the highest difficulty), type, category, and mechanics.

    Evaluate each requirement separately:
- PASS: this requirement is met, or it was not requested.
- FAIL: this requirement is definitely broken.
- UNKNOWN: there is not enough information to check this requirement.

    Information about type of requirements (could be present or not in the request):
    - Players: use the extracted players value as the required count; do not recount it.
      PASS exactly when game_min_players <= requested_players <= game_max_players.
      Both endpoints are inclusive. FAIL if the game's minimum is higher than the
      requested count OR its maximum is lower than the requested count.
      A game supporting more players than requested still passes if its minimum fits.
    - Time: max_minutes is the user's upper limit, not an exact duration or a
      minimum duration. Take the MAXIMUM endpoint of the game's play-time range
      and compare it with max_minutes, in the same unit (minutes).
      PASS when game_maximum_minutes <= requested_maximum_minutes, including
      equality. FAIL only when game_maximum_minutes > requested_maximum_minutes.
      A shorter game PASSES; do not reverse the comparison or describe a smaller
      duration as exceeding a larger limit. For equal range endpoints, that shared
      value is the game's maximum. If no time limit is requested, return PASS.
      If a limit is requested but neither card nor description provides play time,
      return UNKNOWN. Ensure the explanation agrees with this numeric comparison.
    - Complexity evidence: start both fields at NONE. Change them ONLY when you
      can copy an exact, applicable quotation from this game's DESCRIPTION.
      Report DESCRIPTION clues separately for light and heavy.
      Do not decide whether the requested complexity passes. Do not use the weight,
      game types, categories or mechanics for these fields; Python applies those rules.
      The requested level must not influence the evidence you report.
      For each of light and heavy, use these fixed choices:
        YES: the description contains a supporting clue, with no opposing clue.
        NO: the description contains an opposing clue, with no supporting clue.
        BOTH: separate supporting and opposing clues are both present.
        NONE: neither kind of applicable clue is present. Absence is not NO.
      Light supporting clues: the whole game's rules are easy/simple, or a comparison
      or genre label explicitly describes the game as light/lighter.
      Light opposing clues: the whole game's rules are complex or for experienced players.
      Heavy supporting clues: the whole game's rules are complex or for experienced players.
      Heavy opposing clues: the whole game's rules are easy/simple.
      NO requires actual opposing wording; it does not mean there is no YES clue.
      Descriptions of actions, themes, components or winning strategies do not
      establish how hard the rules are or who can learn them. Never paraphrase
      such content as "complex rules" or "for experienced players".
      A phrase combining easy learning with challenging mastery does not decide.
      Ignore difficulty of winning, one small part of the rules or a component,
      an optional expert variant, edition changes and marketing audience.
      An easy individual subsystem alone is not evidence that the whole game's
      rules are easy. Do not infer complexity
      from an intuitive estimate, strategic depth, or number of mechanics.
      Put exact supporting/opposing substrings in light_quotes and heavy_quotes.
      Use [] with NONE. With BOTH, include distinct supporting and opposing quotes.
      Do not quote the card, the request, this prompt, or your own paraphrase.
      Before returning, check that every quote occurs in the description AND meets
      the relevant rule above. A real but irrelevant quote still does not count.
      If no eligible quote exists, return NONE, even if the game feels difficult.
    - Age: min_age in the requirements is the youngest PLAYER'S age, not a
      requested minimum rating for the game. PASS when game_minimum_age <=
      youngest_player_age, including equality. FAIL only when the game's minimum
      age is greater than the player's age. A lower game age rating does not fail
      an older player. Use PASS if the player's age is unspecified.
	- Cooperative vs Competitive: A game whose mechanics include "Cooperative Game" is cooperative, and a game without it is competitive.

    Missing information:
        - Use the card's player range, maximum play time and minimum age. If a required field is missing, look for that information in the description. If neither gives it, mark UNKNOWN. Learning time is not play time, and separately sold expansions do not count toward the supported player count.

    Things to avoid (rubric definitions):
      Each avoid item is a PROHIBITION. Return FAIL when that feature is present,
      PASS when neither tags nor description establish it. A missing tag is not
      enough for PASS: read the description too. Empty tag lists are not hidden data.
      Do not require an explicit promise that the feature is absent, and do not
      return UNKNOWN merely because the description does not discuss it.
      Evaluate each prohibition independently, in the input order.

      Tags always establish presence and cannot be contradicted by the description:
      - fighting: category Fighting.
      - violence: category Wargame OR Fighting.
      - horror: category Horror OR Zombies.
      - timer: category Real-time OR mechanic Real-Time.
      - player elimination: mechanic Player Elimination.

      Without a matching tag, use these gameplay definitions:
      - Fighting: players' characters/creatures attack, battle, duel or vanquish
        other characters/creatures. Predation counts when a player's creature attacks
        another player's creature as a move. Armies, fleets or units battling on a
        map, raiding, pillaging, conquest and an assassination goal in a bluffing game
        count as violence, not fighting. Resource competition, treating disease,
        food chains, abstract captures, auctions called duels, penalties called attacks,
        metaphorical battles, backstory fights and a genre label alone do not count.
      - Violence: fighting, war, army battles, raids, pillaging, conquest or killing
        as the game's subject or goal. An attack that only takes cards/resources,
        a metaphor or a grim backstory alone does not establish violence.
      - Horror: content framed as frightening or disturbing: threatening hauntings,
        frightening pursuit, gore or horror creatures presented to frighten.
        Creature names alone, heroic fantasy enemies, harmless/helpful ghosts,
        generic dungeons, grim backstories, licensed titles, cartoon family/children's
        spookiness, murder mysteries or an isolated horror character do not establish
        horror. Fighting and violence do not automatically imply horror.
      - Timer: an actual clock/sand timer, timed turns, simultaneous speed play,
        or a race to grab/move first. Simultaneous action choice without speed,
        a countdown track, a racing theme and fast-paced wording do not count.
        An optional recommended timer that the rules do not require does not count.
      - Player elimination: a player stops participating and watches others continue,
        for the rest of the game OR a round. Include unavoidable elimination implied
        by the rules even if not named. Losing points/cards/pieces/characters while
        continuing, everyone losing together, or changing to another playable role
        does not count. In a two-player game, defeating the opponent and immediately
        ending play is not elimination because nobody sits out while others continue.

      A feature in an optional variant or any scenario in the box still counts;
      apply the optional recommended-timer exception above. When description wording
      conflicts, the more detailed rule wins. Judge actual gameplay, not isolated
      words or outside knowledge. Explain a FAIL with the matching tag or the actual
      described behavior, and never invent a rule or feature.

    Labeling Guidelines:
        - only use the given information and do not scrape beyond or use insider previously known information.
        - If a requirement definitely fails, mark FAIL. Otherwise, if a requirement cannot be confirmed, mark UNKNOWN.
        - Check this game against EVERY requirement. A game that meets only some requirements is not acceptable.
        - Evaluate each requirement separately. PASS means it is met, FAIL means it is
          broken, UNKNOWN means there is not enough evidence to check it.
        - For players, time and age, use PASS when that requirement is unspecified.
        - For each avoid item, PASS means the prohibited feature is absent.
        - Do not choose a game. Return checks for this one game. Python checks the requested mode and computes the final complexity status separately.

    Return one JSON object with these fields (do not wrap it in a candidate letter):
    - "players", "max_minutes", "min_age": each is "PASS", "FAIL" or "UNKNOWN".
    - "light_evidence": exactly one string: "YES", "NO", "BOTH" or "NONE".
    - "heavy_evidence": exactly one string: "YES", "NO", "BOTH" or "NONE".
    - "light_quotes", "heavy_quotes": arrays of exact DESCRIPTION substrings,
      or [] when the corresponding evidence is NONE. Keep the evidence fields
      themselves as strings, not objects.
      These two fields describe DESCRIPTION clues, not the requested level's result.
      Do not return objects, status/explanation pairs, or nested JSON for these fields.
      Python combines these strings with the card to compute the final complexity status.
    - "avoid": one status per avoid requirement, in the SAME order as the input.
    - "explanation": one plain text string, not an object or list.
    Use [] when the corresponding requirement list is empty. Do not omit checks.
    Ensure the statuses agree with the evidence in your explanation.

    REQUEST TO EVALUATE:
    - complexity: {complexity}
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
    evaluation = call_json(prompt, GameEvaluation, max_tokens=1000)
    # Only live model replies are checked here; human label overrides skip this step.
    return evaluation.model_copy(update={
        "light_evidence": verified_evidence(data.candidate, evaluation.light_evidence, evaluation.light_quotes),
        "heavy_evidence": verified_evidence(data.candidate, evaluation.heavy_evidence, evaluation.heavy_quotes),
    })



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
        complexity_check = check_complexity(
            candidate, requirements.complexity,
            evaluation.light_evidence, evaluation.heavy_evidence,
        )
        if complexity_check != "PASS":
            acceptable = False
        for avoided, model_check in zip(requirements.avoid, evaluation.avoid):
            if check_avoid(candidate, avoided, model_check) != "PASS":
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
            if requirements.complexity is not None:
                explanation += f" It meets the requested {requirements.complexity} complexity under the rubric."
            return Answer(pick=candidate.id, explanation=explanation)

    return Answer(pick=None, explanation="No candidate could be confirmed to meet every requirement.")
