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
    # Exact sentence from the description that shows each avoided feature, "" when there is none.
    avoid_quotes: list[str] = Field(default_factory=list)
    # What the description says about how hard the rules are. Python applies the complexity rubric.
    rules_wording: Literal["easy", "complex", "none"] = "none"
    explanation: str


Feature = Literal["fighting", "violence", "horror", "timer", "player elimination"]


class AvoidInput(BaseModel):
    """One candidate that passed every other check, and the features the request prohibits."""
    features: list[Feature]
    candidate: Candidate


class AvoidCheck(BaseModel):
    """One entry per feature, in the same order as the input. YES means the game has the feature."""
    quotes: list[str]
    has_feature: list[Literal["YES", "NO"]]


@step
def extract_requirements(request: Request) -> Requirements: #includes players,  max_minutes, min_age, mode, have, avoid, wish

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
    - Complexity: put the level in complexity, not in have. "light" for easy rules, simple, beginners,
      never play board games or casual players; "heavy" for deep strategy, meaty or nothing light;
      "medium" for not too simple and not too heavy. If no level is requested, set complexity to null.
    - Cooperative or competitive: put the requested mode in mode, not in have.
      "Together against the game", "team up against the game" and "as one team" mean cooperative;
      "head to head" and "against each other" mean competitive.
      Just playing together, being friends or being a couple does NOT imply cooperative.
      If no mode is requested, set mode to null.
    - Things to avoid: write each one using exactly one of these words:
      "fighting" for no fighting or no combat;
      "violence" for nothing violent;
      "horror" for nothing scary or nothing creepy;
      "timer" for no timers or no racing against the clock;
      "player elimination" for nobody knocked out or nobody sitting out.
    - Age: record the youngest stated age of a child or teenager who will play in min_age ("our 8-year-old" means 8).
      Adults ("in his thirties", "early twenties") are not an age requirement: use null. Do not guess an age.
    - Tastes are not requirements. "We love civilization games" or "we usually play card games" describe
      what the players enjoy; do not put them in have. Only put something in have when the request says this
      game must have it ("we want", "we need", "it has to", "must").
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
    - "complexity": "light", "medium", "heavy", or null when unspecified.

    Put each have, avoid or wish characteristics in a separate string.
    Use [] for empty have, avoid, and wish lists.
    Use an integer for min_age, or null when unspecified.
    Never repeat players, time, age, mode or complexity inside have.
    Do not include Markdown formatting.

    Example structure:
    {
    "have": [],
    "avoid": ["fighting"],
    "wish": [],
    "min_age": 10,
    "players": 4,
    "max_minutes": 60,
    "mode": null,
    "complexity": "light"
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
    
    The request contains these fields:
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
	- Age requirement: If the youngest player's age is specified, the game's listed minimum age must be less than or equal to that age. If the player's age is unspecified, skip this check. For example, a game rated 12+ fails for a youngest player aged 10.

    Rules wording (always fill "rules_wording"; Python combines it with the card's weight and types):
        - "easy": the description says the rules or gameplay are easy, simple or quick to learn, or compares the game as
          lighter ("lighter than many similar games", "a light civilization game", "elegantly simple gameplay").
        - "complex": the description says the rules are complex or for experienced players, or compares the game as heavier.
        - "none": no such statement; wording that says both ("easy to learn, but challenging to master"); or wording about
          something other than how hard the rules are: how hard the game is to win, one part of the game, an optional
          expert variant, changes from another edition, or who it is marketed to ("family game", "casual audience").
        - Do not use the weight or game types for rules_wording. Only the description's words count.

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
        - These do NOT count: figures of speech ("disease-fighting", "fight over resources", "combat misfortune",
          "battle against each other to spread plagues"); competing, rivals, dominating or controlling areas;
          a theme word such as "military" without attacks in play; contests only called duels or battles;
          a penalty called an attack (thieves steal goods); abstract captures; a genre label alone;
          generic fantasy monsters or cartoon spookiness for horror; words about pace ("fast-paced") for timers;
          losing points, cards or pieces while still playing for elimination.
        - For each avoid item marked FAIL, copy into "avoid_quotes" the exact sentence from the description that
          shows the feature happening in play. If you cannot copy such a sentence and no tag matches, mark PASS
          and use "". The quote must be copied word for word; Python checks it against the description.

    Labeling Guidelines:
        - only use the given information and do not scrape beyond or use insider previously known information.
        - If a requirement definitely fails, mark FAIL. Otherwise, if a requirement cannot be confirmed, mark UNKNOWN.
        - Check this game against EVERY requirement. A game that meets only some requirements is not acceptable.
        - Evaluate each requirement separately. PASS means it is met, FAIL means it is
          broken, UNKNOWN means there is not enough evidence to check it.
        - For players, time and age, use PASS when that requirement is unspecified.
        - For each avoid item, PASS means the prohibited feature is absent.
        - Do not choose a game. Return checks for this one game. Python checks the requested mode and complexity separately.

    Return one JSON object with these fields (do not wrap it in a candidate letter):
    - "players", "max_minutes", "min_age": each is "PASS", "FAIL" or "UNKNOWN".
    - "have": one status per have requirement, in the SAME order as the input.
    - "avoid": one status per avoid requirement, in the SAME order as the input.
    - "avoid_quotes": one string per avoid requirement, in the SAME order as the input ("" when there is no quote).
    - "rules_wording": "easy", "complex" or "none".
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



# RUBRIC.md section 4, one definition per feature. Only the requested features go into the prompt.
FEATURE_RULES = {
    "fighting": """FIGHTING: the players' characters or creatures attack, battle or duel other characters or creatures
    as something players do.
    Counts: "fight against villains"; "swords, which are used to fight the monsters"; "vanquish the treacherous
    Darkhouse"; "the Shark wins by successfully attacking the Octopus".
    Does NOT count: armies, fleets or units attacking on a map (Risk); raiding, pillaging or conquering to score;
    an assassination that is only the goal of a bluffing game; figures of speech ("disease-fighting specialists",
    "fight over scarce access to Pearls", "battle against each other to spread their plagues", "combat the rising
    tide", "fast-paced fight to the finish"); a fight that is only backstory; attacks on something that is not a
    character or creature ("destroy your opponents' sanity"); contests only called duels or battles (an auction
    called a duel, rock-paper-scissors battles); a penalty the game calls an attack (thieves steal goods); abstract
    captures as in chess; a genre label alone ("dungeon crawler"); competing, rivals, dominating or controlling areas.""",
    "violence": """VIOLENCE: the game is about war, raiding, killing or other violence, whether or not players fight.
    Counts: everything that counts as fighting; war and battles between armies, fleets or units ("colonization and
    war", "attacking steals a city"); raiding, pillaging and conquest; killing as the goal.
    Does NOT count: a penalty the game calls an attack; figures of speech and metaphors ("disease-fighting",
    "fight over scarce access to Pearls"); a grim backstory such as a plague.""",
    "horror": """HORROR: the game is meant to frighten or disturb. It presents horror creatures (vampires, zombies,
    werewolves, Cthulhu-style monsters), threatening ghosts or hauntings, being hunted, or gore as something frightening.
    Counts: "transforms all the inhabitants into vampires"; "an alien entity picks up your scent and begins to hunt
    you"; "an adventure in a haunted house" with "murderous Skeletons".
    Does NOT count: a horror creature on its own; generic fantasy monsters and dungeons; harmless or helpful ghosts;
    undead or demons as enemies in heroic fantasy or comic games; a horror word only in a licensed title; realistic
    threats not framed as frightening (a shark menacing swimmers); cartoon spookiness in family or children's games;
    one horror character among many; giant monsters smashing a city; murder mysteries; fearsome warriors.""",
    "timer": """TIMER: play involves racing a clock or a sand timer, or everyone playing at once as fast as they can.
    Counts: "once the five-minute timer starts"; "playing at the same time"; grabbing or running at the same moment
    ("run around the table to try to be the first back"); a timed turn ("as many titles as possible in 30 seconds").
    Does NOT count: a countdown track that ends the game; choosing actions at the same time without racing; words
    about pace ("fast-paced", "turns proceed quickly"); racing as a theme (betting on racing camels); an optional
    timer the rules don't require.""",
    "player elimination": """PLAYER ELIMINATION: a player can be knocked out and has to sit and watch while the
    others keep playing, for the rest of the game or for the rest of a round.
    Counts: "the last person alive is the winner"; elimination the rules make unavoidable ("the first player to win
    all the cards is the winner", so with three or more players anyone who runs out of cards stops); sitting out
    the rest of a round.
    Does NOT count: losing points, cards, pieces or characters while still playing; skipping a single turn;
    a cooperative team losing together; a two-player game where knocking the other player out ends the game;
    a knocked-out player who keeps playing in another role.""",
}


@step
def check_avoid(data: AvoidInput) -> AvoidCheck:
    rules = "\n\n    ".join(FEATURE_RULES[feature] for feature in data.features)
    candidate_text = render_candidate(data.candidate)

    instructions = f"""You check whether ONE board game has features that the players want to avoid.
    Read only the game's description below. Do not use what you know about the game from elsewhere.

    Judge what the description shows actually happens when people play. Do not go by isolated words, creature
    names, titles or themes. A feature also counts if it appears in an optional variant or in one scenario in the box.
    When the description contradicts itself, the more detailed rule wins.

    Definitions:

    {rules}

    For each feature, in this order: {data.features}
    1. First look for one sentence in the description that shows the feature happening in play under the
       definition above. Copy it word for word into "quotes". Python checks that it is in the description.
       If there is no such sentence, write "".
    2. Then answer "YES" in "has_feature" only if you copied a sentence that clearly counts under the definition.
       Otherwise answer "NO". When the sentence matches a "Does NOT count" case, answer "NO".

    Return only a JSON object, with one entry per feature in the same order, and no Markdown:
    {{"quotes": ["..."], "has_feature": ["YES" or "NO"]}}

    GAME:
    {candidate_text}
    """
    return call_json(instructions, AvoidCheck, max_tokens=400)


def complexity_check(level, card, wording):
    """Apply the rubric's complexity rules. The model only reads the description's wording."""
    if level is None:
        return "PASS"
    weight = card.complexity.weight if card.complexity else None
    types = set(card.types)

    # Each clue is True (yes), False (no) or None (no clue). Collect them separately.
    light_yes = wording == "easy"
    light_no = wording == "complex"
    heavy_yes = wording == "complex"
    heavy_no = wording == "easy"

    # Without a weight, only the description's wording can decide.
    if weight is not None:
        if "children's" in types or "party" in types:
            light_yes = True
        if "family" in types and weight < 2.0:
            light_yes = True
        if types and types <= {"strategy", "thematic", "war", "abstract"} and weight >= 2.5:
            light_no = True
        if types & {"strategy", "war"} and "family" not in types and weight >= 3.5:
            heavy_yes = True
        if types & {"children's", "party", "family"}:
            heavy_no = True

    # The extremes win over every other clue.
    if weight is not None and weight <= 1.3:
        is_light, is_heavy = "YES", "NO"
    elif weight is not None and weight >= 4.0:
        is_light, is_heavy = "NO", "YES"
    else:
        is_light = "UNKNOWN" if light_yes == light_no else ("YES" if light_yes else "NO")
        is_heavy = "UNKNOWN" if heavy_yes == heavy_no else ("YES" if heavy_yes else "NO")

    if level == "light":
        return {"YES": "PASS", "NO": "FAIL", "UNKNOWN": "UNKNOWN"}[is_light]
    if level == "heavy":
        return {"YES": "PASS", "NO": "FAIL", "UNKNOWN": "UNKNOWN"}[is_heavy]
    # Medium: not light or heavy, and a weight between 2.0 and 3.5.
    if is_light == "YES" or is_heavy == "YES":
        return "FAIL"
    if weight is not None and 2.0 <= weight <= 3.5:
        return "PASS"
    return "UNKNOWN"


def avoid_feature(item):
    """Map an avoid requirement to one of the rubric's five features, or None."""
    text = item.lower()
    if "elimin" in text or "knock" in text or "sitting out" in text:
        return "player elimination"
    if "horror" in text or "scary" in text or "creepy" in text:
        return "horror"
    if "timer" in text or "clock" in text or "real-time" in text:
        return "timer"
    if "violen" in text:
        return "violence"
    if "fight" in text or "combat" in text:
        return "fighting"
    return None


def has_tag(feature, card):
    """A tag always counts (RUBRIC.md section 3, Things to avoid)."""
    fighting = "Fighting" in card.categories
    if feature == "fighting":
        return fighting
    if feature == "violence":
        return fighting or "Wargame" in card.categories
    if feature == "horror":
        return "Horror" in card.categories or "Zombies" in card.categories
    if feature == "timer":
        return "Real-time" in card.categories or "Real-Time" in card.mechanics
    if feature == "player elimination":
        return "Player Elimination" in card.mechanics
    return False


def normalize(text):
    return " ".join(text.lower().replace("’", "'").replace("“", '"').replace("”", '"').split())


def avoid_check(item, status, quote, candidate):
    feature = avoid_feature(item)
    if feature is None:
        return status  # Not one of the rubric's features: keep the model's check.
    if has_tag(feature, candidate.card):
        return "FAIL"
    # The description can add the feature, but only with a sentence that really is in the description.
    quote = normalize(quote)
    if status != "PASS" and quote and quote in normalize(candidate.description):
        return "FAIL"
    return "PASS"


def answer(request: Request) -> Answer:
    # 1. MODEL CALL: extract requirements.
    requirements = extract_requirements(request)

    # 2. Five model calls: evaluate one candidate at a time.
    evaluations = []
    for candidate in request.candidates:
        decision_input = DecisionInput(requirements=requirements, candidate=candidate)
        evaluations.append(decide(decision_input))

    # The rest of the 10 calls go to check_avoid, at most one per candidate that passes everything else.
    avoid_calls_left = 10 - 1 - len(request.candidates)
    features = [avoid_feature(item) for item in requirements.avoid]

    # 3. Python selects the first candidate whose checks all pass.
    for index in range(len(request.candidates)):
        candidate = request.candidates[index]
        evaluation = evaluations[index]
        card = candidate.card

        # Missing checks must not accidentally count as a pass.
        if len(evaluation.have) != len(requirements.have):
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

        complexity = complexity_check(requirements.complexity, card, evaluation.rules_wording)

        # Avoid items: a card tag always counts. Items that aren't one of the rubric's five features keep
        # decide's check. The description of the rubric features is checked by check_avoid below.
        statuses = evaluation.avoid + ["UNKNOWN"] * len(requirements.avoid)
        quotes = evaluation.avoid_quotes + [""] * len(requirements.avoid)
        avoid_checks = []
        to_check = []
        for i in range(len(requirements.avoid)):
            if features[i] is None:
                avoid_checks.append(avoid_check(requirements.avoid[i], statuses[i], quotes[i], candidate))
            elif has_tag(features[i], card):
                avoid_checks.append("FAIL")
            elif features[i] not in to_check:
                to_check.append(features[i])

        acceptable = True
        if players_check != "PASS":
            acceptable = False
        if time_check != "PASS":
            acceptable = False
        if age_check != "PASS":
            acceptable = False
        if mode_check != "PASS":
            acceptable = False
        if complexity != "PASS":
            acceptable = False
        for check in evaluation.have:
            if check != "PASS":
                acceptable = False
        for check in avoid_checks:
            if check != "PASS":
                acceptable = False

        # Only a candidate that passes everything else is worth a check_avoid call.
        if acceptable and to_check:
            if avoid_calls_left > 0:
                avoid_calls_left -= 1
                result = check_avoid(AvoidInput(features=to_check, candidate=candidate))
                result_quotes = result.quotes + [""] * len(to_check)
                description = normalize(candidate.description)
                for i in range(len(to_check)):
                    has_feature = i < len(result.has_feature) and result.has_feature[i] == "YES"
                    # A YES only counts with a sentence that really is in the description.
                    quote = normalize(result_quotes[i])
                    if has_feature and quote and quote in description:
                        acceptable = False
            else:
                # No calls left: fall back to decide's checks of the description.
                for i in range(len(requirements.avoid)):
                    if features[i] in to_check:
                        if avoid_check(requirements.avoid[i], statuses[i], quotes[i], candidate) != "PASS":
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
                explanation += f" It fits the {requirements.complexity} complexity rules."
            return Answer(pick=candidate.id, explanation=explanation)

    return Answer(pick=None, explanation="No candidate could be confirmed to meet every requirement.")
