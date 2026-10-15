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

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, field_validator

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
    complexity_quote: str = ""
    mode_quote: str = ""
    avoid: list[Literal["fighting", "violence", "horror", "timer", "player elimination"]] = Field(default_factory=list)
    wish: list[str] = Field(default_factory=list)


class DecisionInput(BaseModel):
    requirements: Requirements
    candidate: Candidate


class GameEvaluation(BaseModel):
    """PASS means met (or not requested); UNKNOWN means not enough evidence."""
    min_players: int | None = Field(default=None, ge=1)
    max_players: int | None = Field(default=None, ge=1)
    players_quote: str = ""
    max_minutes: int | None = Field(default=None, ge=1, description="Candidate game maximum play time, not the user limit")
    play_time_quote: str = ""
    min_age: Literal["PASS", "FAIL", "UNKNOWN"]
    easy_rules: bool
    complex_rules: bool
    easy_quotes: list[str] = Field(default_factory=list)
    complex_quotes: list[str] = Field(default_factory=list)
    avoid: list[Literal["YES", "NO", "UNKNOWN"]]
    explanation: str

    @field_validator("avoid", mode="before")
    @classmethod
    def normalize_avoid_statuses(cls, value):
        # Old avoidance statuses describe whether the prohibition passes:
        # PASS means feature absent; FAIL means feature present.
        # Keep the declared contract and labeling choices as presence YES/NO/UNKNOWN.
        if isinstance(value, list):
            return [{"PASS": "NO", "FAIL": "YES"}.get(item, item)
                    if isinstance(item, str) else item for item in value]
        return value

    @field_validator("min_players", "max_players", "max_minutes", mode="before")
    @classmethod
    def zero_means_not_given(cls, value):
        # The model sometimes writes 0 for "not given"; the contract uses null for that.
        return None if value == 0 else value


def quote_exists(text: str, quote: str) -> bool:
    """Match contiguous wording, tolerating whitespace, case and ending punctuation."""
    # A quoted clause may end with a period even when the original sentence continues.
    # Keep internal punctuation and wording intact; do not join separated passages.
    wording = " ".join(quote.split()).casefold().rstrip(".,;:!?")
    return bool(wording.strip()) and wording in " ".join(text.split()).casefold()


def verified_clue(candidate: Candidate, claimed: bool, quotes: list[str]) -> bool:
    # Keep a valid short quote even if another supplied quote is malformed.
    return claimed and any(quote_exists(candidate.description, quote) for quote in quotes)


def explicit_requirement(text: str, quote: str) -> bool:
    """Live extraction must quote a mandatory clause, not an optional preference."""
    optional = r"would be nice|would be amazing|would love|we['’]d love|we love|not a must|not mandatory|not required|optional|bonus points|does(?: not|n't) have to"
    return quote_exists(text, quote) and re.search(optional, quote, re.IGNORECASE) is None


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
    return "FAIL" if tagged.get(avoided, False) else {"YES": "FAIL", "NO": "PASS", "UNKNOWN": "UNKNOWN"}[model_check]


def check_complexity(
    candidate: Candidate,
    requested: Literal["light", "medium", "heavy"] | None,
    easy_rules: bool,
    complex_rules: bool,
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
        # One description clue supplies both linked rubric implications.
        light_yes = easy_rules
        light_no = complex_rules
        heavy_yes = complex_rules
        heavy_no = easy_rules
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
      Tactical play, a preferred theme, or wanting a different game does not by
      itself specify a complexity level. Copy the full mandatory clause into
      complexity_quote, including any preference qualifiers. No requirement means "".
      Do not infer a requirement without explicit supporting wording.
    - Cooperative or competitive: put the requested mode in mode.
      Playing together against the game means cooperative; head to head means competitive.
      Just playing together, being friends or being a couple does NOT imply cooperative.
      If no mode is requested, set mode to null.
      Copy the full mandatory mode clause into mode_quote. Include qualifiers, rather
      than quoting only a mode word. A preference marked optional, nice to have,
      not a must, or not required stays in wish, and mode is null with mode_quote="".
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
    - "complexity_quote", "mode_quote": exact full clauses supporting mandatory
      requirements, or "" when the respective requirement is null.
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
    requirements = call_json(prompt, Requirements)
    updates = {}
    if requirements.complexity is not None and not explicit_requirement(request_only, requirements.complexity_quote):
        updates["complexity"] = None
    if requirements.mode is not None and not explicit_requirement(request_only, requirements.mode_quote):
        updates["mode"] = None
    return requirements.model_copy(update=updates)


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
    - Players: EXTRACT the supported minimum and maximum player counts; do not
      return a PASS/FAIL judgment. Use the card's player range when listed.
      If the card has no range, read the DESCRIPTION for a numerical range, including
      numbers written as words. Return min_players and max_players as integers.
      A single supported count means both endpoints equal that count. If no supported
      count is given, return null for both. Do not invent endpoints from "multiplayer".
      When extracting from the description, put the exact supporting substring in
      players_quote. Include only the base game; separately sold expansions do not count.
      Python compares the extracted range with the requested count inclusively.
    - Time: EXTRACT the CANDIDATE GAME'S maximum play time in minutes into
      max_minutes. This output is a number, NEVER PASS/FAIL/UNKNOWN. It is NOT the
      user's requested time limit. Use the maximum endpoint of the card's time range.
      When the card has no time, extract a stated play time from the description and
      copy its exact supporting substring into play_time_quote. If no play time is
      available, return null and play_time_quote="". Learning time is not play time.
      Python compares this game duration with the user's limit using <=, including
      equality. A shorter game fits. Do not copy the user limit as the game duration.
    - Complexity: report only TWO independent description facts:
      easy_rules: true when wording establishes easy/simple rules for the whole game,
        or explicitly describes it as light/lighter through a comparison or genre label.
      complex_rules: true when wording establishes complex rules for the whole game
        or says it is for experienced players. Explicit descriptions of the game's
        complexity count, including a complexity rating written in the description.
      Otherwise each field is false. Both may be true if both clues are present.
      Do not decide whether the requested level passes. Ignore card weight and types
      for these two facts: Python combines them with the card using the rubric.
      Difficulty of winning, strategic depth, themes, actions, components and long
      gameplay summaries do not establish rule complexity. "Challenging" alone does
      not mean complex rules. Marketing audience alone does not establish easy rules.
      A phrase combining easy learning with challenging mastery does not decide.
      Ignore one subsystem, optional expert variants and changes between editions.
      Start both facts at false. For each true fact, copy a SHORT, contiguous exact
      description substring into easy_quotes or complex_quotes. Never join separated
      text, add a paraphrase, or quote this prompt/card/request. Short quotes are enough;
      the quote need not contain an introductory sentence or the entire paragraph.
      Use [] when false. Check relevance as well as existence. Python derives the
      linked light/heavy implications from each fact, so you only report it once.
    - Age: min_age in the requirements is the youngest PLAYER'S age, not a
      requested minimum rating for the game. PASS when game_minimum_age <=
      youngest_player_age, including equality. FAIL only when the game's minimum
      age is greater than the player's age. A lower game age rating does not fail
      an older player. Use PASS if the player's age is unspecified.
	- Cooperative vs Competitive: A game whose mechanics include "Cooperative Game" is cooperative, and a game without it is competitive.

    Missing information:
        - Use the card's player range, maximum play time and minimum age. If a required field is missing, look for that information in the description. If neither gives it, mark UNKNOWN. Learning time is not play time, and separately sold expansions do not count toward the supported player count.

    Things to avoid (rubric definitions):
      For each avoid item, report whether the FEATURE IS PRESENT, not whether the
      game passes the prohibition: YES = present, NO = absent, UNKNOWN = cannot tell.
      Python converts presence YES to avoidance FAIL and presence NO to avoidance PASS.
      If neither tags nor description establish the feature, return NO. A missing tag is not
      enough for NO: read the description too. Empty tag lists are not hidden data.
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
      words or outside knowledge. Explain a YES with the matching tag or the actual
      described behavior, and never invent a rule or feature.

    Return only one JSON object with these flat fields:
    - "min_players", "max_players": integers or null, NEVER status strings.
    - "players_quote": exact description substring for a missing-card range, or "".
    - "max_minutes": the CANDIDATE GAME'S maximum duration as an integer, or null.
      Never return a status string or copy the requested maximum into this output.
    - "play_time_quote": exact description substring for missing-card time, or "".
    - "min_age": "PASS", "FAIL" or "UNKNOWN"; unspecified player age means PASS.
    - "easy_rules", "complex_rules": JSON booleans, not strings or objects.
    - "easy_quotes", "complex_quotes": arrays of exact description substrings.
    - "avoid": one "YES", "NO" or "UNKNOWN" per input prohibition, in the SAME order.
      Use presence values, NEVER PASS or FAIL: absent = NO, present = YES.
      If avoid is empty, return []. Do not invent extra items. Check only the requested
      feature: another feature's presence cannot make this one YES.
    - "explanation": one plain text string. Ensure it agrees with the evidence.
    Use only the supplied candidate. Python selects the game and computes final checks.

    REQUEST TO EVALUATE:
    - complexity: {complexity}
    - avoid: {avoid}
    - min_age: {min_age}
    - players: {data.requirements.players}
    - requested_maximum_minutes: {data.requirements.max_minutes}

    CANDIDATE GAME TO EVALUATE:
    {candidate_text}
    """


    if not instructions:
        raise NotImplementedError("Write the instructions for the decide step in systems/compound.py first.")
    prompt = instructions
    evaluation = call_json(prompt, GameEvaluation, max_tokens=1000)
    # Human label overrides skip this body and use the human's clues directly.
    updates = {
        "easy_rules": verified_clue(data.candidate, evaluation.easy_rules, evaluation.easy_quotes),
        "complex_rules": verified_clue(data.candidate, evaluation.complex_rules, evaluation.complex_quotes),
    }
    if not data.candidate.card.players and not quote_exists(data.candidate.description, evaluation.players_quote):
        updates.update(min_players=None, max_players=None)
    if not data.candidate.card.minutes and not quote_exists(data.candidate.description, evaluation.play_time_quote):
        updates["max_minutes"] = None
    return evaluation.model_copy(update=updates)




def answer(request: Request) -> Answer:
    # A reply that doesn't fit its type raises ValidationError. Every answered call counts toward the
    # limit of 10, so retries only use calls that no later step needs.
    calls_left = 10

    # 1. MODEL CALL: extract requirements, retried once if the reply doesn't fit.
    requirements = None
    for attempt in range(2):
        if calls_left - len(request.candidates) <= 0:
            break
        calls_left -= 1
        try:
            requirements = extract_requirements(request)
            break
        except ValidationError:
            pass
    if requirements is None:
        return Answer(pick=None, explanation="The request could not be read, so no game could be confirmed.")

    # 2. Five model calls: evaluate one candidate at a time. A reply that doesn't fit is retried once;
    #    a candidate still without a valid evaluation is never picked.
    evaluations = []
    for index, candidate in enumerate(request.candidates):
        decision_input = DecisionInput(requirements=requirements, candidate=candidate)
        evaluation = None
        later_candidates = len(request.candidates) - index - 1
        for attempt in range(2):
            if calls_left - later_candidates <= 0:
                break
            calls_left -= 1
            try:
                evaluation = decide(decision_input)
                break
            except ValidationError:
                pass
        evaluations.append(evaluation)

    # 3. Python selects the first candidate whose checks all pass.
    for index in range(len(request.candidates)):
        candidate = request.candidates[index]
        evaluation = evaluations[index]
        card = candidate.card
        if evaluation is None:
            continue

        # Missing checks must not accidentally count as a pass.
        if requirements.avoid and len(evaluation.avoid) != len(requirements.avoid):
            continue

        # If the card provides numbers, check them directly.
        # Otherwise keep the model's check based on the description.
        players_check = "PASS"
        if requirements.players is not None:
            player_range = card.players
            if not player_range and evaluation.min_players is not None and evaluation.max_players is not None:
                player_range = [evaluation.min_players, evaluation.max_players]
            if not player_range or player_range[0] > player_range[-1]:
                players_check = "UNKNOWN"
            elif player_range[0] <= requirements.players <= player_range[-1]:
                players_check = "PASS"
            else:
                players_check = "FAIL"

        time_check = "PASS"
        if requirements.max_minutes is not None:
            game_max_minutes = max(card.minutes) if card.minutes else evaluation.max_minutes
            if game_max_minutes is None:
                time_check = "UNKNOWN"
            elif game_max_minutes <= requirements.max_minutes:
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
            evaluation.easy_rules, evaluation.complex_rules,
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
