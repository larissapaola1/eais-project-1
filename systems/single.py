"""The single-call variant: one model call per request, no steps.

Write your instructions for the model in INSTRUCTIONS. Keep it to one call: the starter code refuses a second
call and the request fails.
"""

from p1 import Answer, Request, call_json #Classes
from p1.render import render_request #function

VARIANT = "single"

# Your instructions: what the model should do with the request and the five games.
INSTRUCTIONS = """
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
"""



# The answer format. Keep it, unless you also change how answer() reads the reply.
FORMAT = """Answer with JSON only, in this form:
{"pick": "<the game's letter, or null to decline>", "explanation": "<one or two sentences for the person>"}"""


def answer(request: Request) -> Answer:
    if not INSTRUCTIONS.strip():
        raise NotImplementedError("Write your instructions in INSTRUCTIONS in systems/single.py first.")
    return call_json(f"{INSTRUCTIONS}\n\n{FORMAT}\n\n{render_request(request)}", Answer)
