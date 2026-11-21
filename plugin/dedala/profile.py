# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""The agent's name and face in the app: the JSON store `profile`, written by
the agent with app_data and by him from the app's Name and face screen.
`name`; `look`, the parts of a drawn face (the app's Avataaars, alive with the
agent's moods); `picture`, an image file on this machine, drawn instead as a
still circle and sent to the phone like a record's file. Whoever wrote last
wins; the agent is told when he changes it from the phone."""

from pathlib import Path
from typing import Optional

STORE = "profile"
NONE = "none"
FABRICS = ["262e33", "3c4f5c", "929598", "e6e6e6", "ffffff", "25557c", "5199e4", "65c9ff", "b1e2ff", "a7ffc4", "ffffb1",
           "ffafb9", "ff488e", "ff5c5c"]
HAIR_COLORS = ["2c1b18", "4a312c", "724133", "a55728", "b58143", "d6b370", "ecdcbf", "e8e1e1", "c93305", "f59797"]
LOOK = {
    "skin": ["ffdbb4", "edb98a", "d08b5b", "ae5d29", "614335"],
    "top": [NONE, "shortFlat", "shortWaved", "shortCurly", "shortRound", "theCaesar", "theCaesarAndSidePart", "sides", "shavedSides",
            "frizzle", "shaggy", "shaggyMullet", "dreads01", "dreads02", "fro", "froBand", "bob", "bun", "curly", "curvy",
            "dreads", "frida", "bigHair", "longButNotTooLong", "miaWallace", "straight01", "straight02", "straightAndStrand",
            "hat", "winterHat1", "winterHat02", "winterHat03", "winterHat04", "hijab", "turban"],
    "hairColor": HAIR_COLORS,
    "hatColor": FABRICS,
    "facialHair": [NONE, "beardLight", "beardMedium", "beardMajestic", "moustacheFancy", "moustacheMagnum"],
    "facialHairColor": HAIR_COLORS,
    "accessories": [NONE, "prescription01", "prescription02", "round", "wayfarers", "kurt", "sunglasses", "eyepatch"],
    "accessoriesColor": FABRICS,
    "clothing": ["shirtCrewNeck", "shirtScoopNeck", "shirtVNeck", "collarAndSweater", "hoodie", "blazerAndShirt", "blazerAndSweater",
                 "overall", "graphicShirt"],
    "clothesColor": FABRICS,
    "clothingGraphic": ["bat", "bear", "cumbia", "deer", "diamond", "hola", "pizza", "resist", "skull", "skullOutline"],
}
ABOUT = ("Your name and face in the app, yours to set and his to change: name; look, the parts of a drawn face that shows "
         "your moods (each part's choices in look_parts, a part left out is drawn from your name); picture, an image file "
         "on this machine drawn instead as a still circle (null gives the look back). You are told when he changes it.")


def problem(profile) -> Optional[str]:
    """Why the store cannot be the profile; None when it can."""
    if not isinstance(profile, dict):
        return "profile is an object: {name, look, picture}"
    if not isinstance(profile.get("name"), str) or not profile["name"].strip():
        return "profile needs a name"
    look = profile.get("look")
    if look is not None:
        if not isinstance(look, dict):
            return "look is an object of parts, like {\"skin\": \"edb98a\", \"top\": \"shortCurly\"}"
        for part, value in look.items():
            if part not in LOOK:
                return f"look has no part {part}: the parts are {', '.join(LOOK)}"
            if value not in LOOK[part]:
                return f"{value!r} is not a {part}: choose one of {', '.join(LOOK[part])}"
    picture = profile.get("picture")
    if picture is not None:
        if not isinstance(picture, str) or not Path(picture).expanduser().is_file():
            return "picture is the path of an image file on this machine (download one first), or null for the drawn look"
    return None


def told(before: Optional[dict], after: Optional[dict]) -> Optional[str]:
    """What the agent is told when he changed its name or face on the phone."""
    before, after = before or {}, after or {}
    said = []
    if after.get("name") and after.get("name") != before.get("name"):
        said.append(f"he named you {after['name']} in the app" + (f", instead of {before['name']}" if before.get("name") else "")
                    + ": it is your name there, on its titles and notifications")
    if after.get("picture") != before.get("picture") and after.get("picture"):
        said.append(f"he gave you a picture for a face, {after['picture']}")
    elif after.get("look") != before.get("look") or (before.get("picture") and not after.get("picture")):
        said.append("he made your face over" + (": the drawn look now" if before.get("picture") and not after.get("picture") else ""))
    if not said:
        return None
    return f"[app: {'; '.join(said)}. It is the store profile. Answer in one short line at most.]"
