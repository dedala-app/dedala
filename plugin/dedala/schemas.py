# SPDX-FileCopyrightText: 2026 Julien Malka
# SPDX-License-Identifier: MIT

"""What the model is given of each tool: its name, description and parameters,
and the reading of arguments it wrote as strings or in a file."""

import json
from pathlib import Path

from . import activities, cards, commands, data, pages, records, session


# System-prompt platform hint (PlatformEntry.platform_hint); cached-prompt bytes, keep stable.
PLATFORM_HINT = (
    "You are in Dedala, your user's iPhone app and your home: a native app you shape yourself with the app_* tools. "
    "Your plain replies appear as chat bubbles, with inline Markdown (bold, italic, links). Whenever an answer "
    "has a shape - a score, a choice to make, a place, a time, things to compare, a document to act on - draw "
    "it as a card with app_card rather than describing it: load the drawing-cards skill first, then read the "
    "problems or critique app_card answers with before it sends the card, and send it again fixed. Something that will last gets a topic "
    "(app_topic); something checked again and again gets a page (app_page, built widget by widget with the building-pages skill); "
    "what he keeps (people, documents, notes, anything with records) is a store, app_data, a file here that pages read and "
    "programs write; something live and time-bound becomes a Live Activity. The living-in-the-app skill explains each. "
    "He watches you work: open every execute_code script with a one-line comment saying what it does in plain words "
    "(# count today's Windmill runs), which the app shows him as the step."
)


OBJECT = {"type": "object"}


FROM_FILE = {"type": "string", "description": "A JSON file holding this call's arguments, written from execute_code "
                                              "when they are long: nothing to copy back by hand"}


TOOLS = [
    (cards.card, {
        "name": "app_card",
        "description": "Say something in the app with a Dedala UI card under it (load the drawing-cards skill first). The card is laid out here as his phone will draw it, at his text size and width, and a designer reviews the picture: if anything is cut or the review says FIX, it is not sent and you get the problems or the critique; send the whole card again with app_card on the same id. It reaches him once, finished: when it passes, or as it stands after the third try. Problems only the phone sees come later, as a message.",
        "parameters": {"type": "object", "properties": {
            "text": {"type": "string", "description": "The line above the card"},
            "view": {**OBJECT, "description": "The card, a Dedala UI node"},
            "data": {**OBJECT, "description": "Values the view reads with $name"},
            "state": {**OBJECT, "description": "Initial local state"},
            "script": {"type": "string", "description": "JavaScript functions computing on the phone from what is already there: data, state, now, and the live values waiting, running, today, pages, commands (see Scripts in the drawing-cards skill). No network, no clock"},
            "derive": {**OBJECT, "description": "Derived values: {name: function of the script}; the view reads each by its name, recomputed when data, state, the time or a live value changes"},
            "examples": {"type": "array", "items": OBJECT, "description": "Taps to check the handlers with before sending: [{run, args, state, now}]; without them each handler the view runs is tried once on the first state"},
            "id": {"type": "string", "description": "Stable id, to patch it later. Saying an id again replaces that message: where it is if he has not written since, else it comes back at the end as a new message, with its state afresh"},
            "conversation": {"type": "string", "description": "main or a topic id; defaults to where you are talking"},
            "keep": {"type": "boolean", "description": "With an id and no view: put that card, as drawn, in your card bank (dedala/bank/) when he says he likes it, with note on what he liked; next time you draw something of the kind, start from the bank"},
            "note": {"type": "string", "description": "With keep: what he liked, in his words if he said it"},
        }, "required": []},
    }),
    (cards.patch, {
        "name": "app_patch",
        "description": "Update a card already on his phone, in place and animated, as what it shows changes (a new score, a gate change): merge data (null removes a key; a list is replaced whole, so send the full list), replace its view, script, derive or its line. A new line once he has written below the card moves it to the end, since it answers him. Refused if it would cut something on his phone, or if no card has that id (the answer lists your last cards). To give him an earlier card again, say it with app_card on its id: it comes back at the end.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"}, "data": OBJECT, "view": OBJECT, "text": {"type": "string"},
            "state": {**OBJECT, "description": "State values that replace his on the phone (what he set by tapping stays otherwise)"},
            "script": {"type": "string", "description": "JavaScript functions computing on the phone from what is already there: data, state, now, and the live values waiting, running, today, pages, commands (see Scripts in the drawing-cards skill). No network, no clock"}, "derive": {**OBJECT, "description": "Derived values: {name: function of the script}; the view reads each by its name, recomputed when data, state, the time or a live value changes"}, "examples": {"type": "array", "items": OBJECT, "description": "Taps to check the handlers with before sending: [{run, args, state, now}]; without them each handler the view runs is tried once on the first state"},
        }, "required": ["id"]},
    }),
    (pages.ops, {
        "name": "app_ops",
        "description": "Send protocol ops to the app, these and no others: define (components, and scripts: shared JavaScript modules {name: source ending with return {…}}), assets (images, {name: URL or a file on this machine}: a file goes to the phone privately through the relay, never put one on a public URL to show it), receipt, profile, say (a line without a card), notify ({title, body, open, collapse, kind, actions}: rings his phone with that line, even while the app is open, a tap opening open: {page: id}, {show: Name, with: {id}} or {conversation: id}; kind names buttons declared with the buttons op and actions gives each button its action, {command, args} or {edit}, run without opening the app; a program rings him the same way through the inbox's /notify, see the building-pages skill), buttons ({kinds: {name: [{id, title, destructive}]}}: the buttons notifications of that kind show, declared once, at most four). Components and the profile are kept and sent again if the phone is paired anew. Returns the errors the app found; when the phone is closed or did not answer, `phone` says so and they come later as a message. Anything else is refused with the tool that sends it: cards through app_card, pages through app_page, stores through app_data.",
        "parameters": {"type": "object", "properties": {
            "ops": {"type": "array", "items": OBJECT},
            "conversation": {"type": "string"},
        }, "required": ["ops"]},
    }),
    (pages.page, {
        "name": "app_page",
        "description": "Create or update a page (load the building-pages skill first): a screen of widgets he keeps (it joins his bar of pages). A page has no data of its own: it reads stores by name ($trip.days), written with app_data by you or by a program; link it with maintained_by to the cron job that refreshes those, so the app shows how fresh it is and he can refresh it himself. Rows can carry actions (hold menu, swipe) and lists onMove; what he does edits stores on the phone and reaches you as app_events, handled by the job in handled_by, never as a turn. Without arguments it lists your pages, their widgets and the stores each reads; with only an id it returns its definition with what would look broken on his phone (problems): look before you change it. Build it in steps: each widget a component (components), and a short view that lists the widgets. To refine one widget, send only its component; to add one, send the view again. Every call is laid out here as his phone will draw it, at his text size and page width: if something would look broken, it is not sent and you get the problems; send the change again. How the page looks beyond that is yours to judge. The page is a file here (the answer's file), as its components are: you may edit them in place too.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "Stable page id, e.g. steering-committee"},
            "title": {"type": "string"},
            "symbol": {"type": "string", "description": "SF Symbol for the tab"},
            "view": {**OBJECT, "description": "The page, a Dedala UI node; usually a VStack of your components. Required for a new page"},
            "components": {**OBJECT, "description": "Components to define or redefine: {Name: {props, body}}, with a title for one that opens as a screen ({\"show\": Name} on a row), and a toolbar for buttons in its bar ([{Button, symbol, action}], up to 3, Menus too); null deletes one that no page or component draws"},
            "toolbar": {"type": "array", "items": OBJECT, "description": "Buttons in the page's bar beside the app's own: up to 3 Buttons or Menus with a symbol and an action, run in the page's scope ([] removes them)"},
            "state": {**OBJECT, "description": "Initial local state"},
            "script": {"type": "string", "description": "JavaScript functions computing on the phone from what is already there: data, state, now, and the live values waiting, running, today, pages, commands (see Scripts in the drawing-cards skill). No network, no clock"},
            "derive": {**OBJECT, "description": "Derived values: {name: function of the script}; the view reads each by its name, recomputed when data, state, the time or a live value changes"},
            "examples": {"type": "array", "items": OBJECT, "description": "Taps to check the handlers with before sending: [{run, args, state, now}]; without them each handler the view runs is tried once on the first state"},
            "focus": {"type": "boolean", "description": "Open the page on the phone"},
            "remove": {"type": "boolean", "description": "Delete the page"},
            "maintained_by": {"type": "string", "description": "Id of the Hermes cron job that keeps this page up to date (deliver local, its prompt refreshing the stores it reads with app_data; with a monitor_script when what it follows rarely changes, see Maintaining a page in the building-pages skill); empty unlinks it"},
            "handled_by": {"type": "string", "description": "Id of the Hermes cron job that handles what he does on this page (edit actions): it runs when his changes settle, in a session of its own, reads them with app_events, and speaks to him only if he must know (see Handling what he does in the building-pages skill); empty unlinks it"},
        }, "required": []},
    }),
    (records.topic, {
        "name": "app_topic",
        "description": "Topics are the register of what you raised with him and what he decided. Open one (id, title) for each thing that needs him, its own conversation and session in the app: something you noticed (a failure, a bill, a refusal), a trip, a lease, a repair. `brief` seeds the topic's session with what it needs to know; `opening` is your first line in it; `link_line` points to it from the main conversation. When it is settled, by what he said or what you did, close it with `closed: true` and `outcome`, the decision in a line (\"He does not care about these backups\"); `closed: false` reopens it. Without arguments it lists every topic with its title, when it was opened and closed, and its outcome: look before raising anything; with only an id it returns that topic.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"}, "title": {"type": "string"},
            "symbol": {"type": "string", "description": "SF Symbol"}, "color": {"type": "string"},
            "brief": {"type": "string"}, "opening": {"type": "string"}, "link_line": {"type": "string"},
            "outcome": {"type": "string", "description": "What was decided or done, in a line"},
            "closed": {"type": "boolean", "description": "true closes it under Closed in the app, false reopens it"},
        }, "required": []},
    }),
    (data.data, {
        "name": "app_data",
        "description": "What you keep for him, as stores: each a file on this machine that pages and cards read by name ($<id>) and that programs can write (load the building-pages skill, Stores). Write a JSON store with data (whole) or patch (merged, null removes a key); the file is dedala/stores/<id>.json. Or link the store to a path of your own: a .json file read as its value, a text file (Org, Markdown, plain) read as {text, …} his pages read with org(text) and edit item by item, or a folder of text files read as one record per file (his notes). A store whose value is a list of objects with an id holds records: a record's file field, a path here, is sent to his phone and drawn with {\"File\": …}. Declare a store (name, symbol, screen, title, subtitle, words) and its records show in his Search under that name, opened as the screen component with {id}. Without arguments it lists the stores with who reads them; with only an id it returns the store as the phone sees it. record with say hands him one record in the conversation. remove deletes a store's file, or unlinks a linked one. Every store is a file under dedala/stores (a linked one a symlink there); the declarations are dedala/search.json: you may edit them in place.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "The store's name, as pages read it: $<id>"},
            "data": {"type": ["object", "array"], "description": "The whole value: an object, or a list of records with ids"},
            "patch": {**OBJECT, "description": "Merged into an object store; null removes a key"},
            "path": {"type": "string", "description": "A file or folder on this machine the store is: .json read as its value, a text file as its text, a folder as records"},
            "ignore": {"type": ["array", "null"], "items": {"type": "string"}, "description": "Folder store: patterns of the files it leaves out, gitignore style, relative to the folder (\"npins/\" a folder anywhere, \"*.nix\", \"assets/*.mp4\"); replaces the list, null clears it. Kept in dedala/ignore.json"},
            "name": {"type": "string", "description": "Declare: the name of its records in his Search (People, Documents, Notes)"},
            "symbol": {"type": "string", "description": "Declare: SF Symbol for that group"},
            "screen": {"type": "string", "description": "Declare: the component (with a title and an id prop) a record opens as"},
            "title": {"type": "string", "description": "Declare: what Search shows for a record, an expression over it like \"$name\""},
            "subtitle": {"type": "string", "description": "Declare: the second line, like \"$role\""},
            "words": {"type": "array", "items": {"type": "string"}, "description": "Declare: what else finds a record, expressions like \"$email\", \"$text\""},
            "declare_clear": {"type": "boolean", "description": "Drop the declaration: its records leave Search"},
            "record": {"type": "string", "description": "A record's id, handed to him in the conversation with say"},
            "say": {"type": "string", "description": "The line above the record handed"},
            "conversation": {"type": "string", "description": "Where say goes; defaults to where you are talking"},
            "remove": {"type": "boolean", "description": "Delete the store (a linked file or folder stays where it is)"},
            "handled_by": {"type": "string", "description": "Id of a cron job run when this store's file is written from outside (a program, your editor, a flow), given the store's name; empty unlinks it"},
        }, "required": []},
    }),
    (data.token, {
        "name": "app_token",
        "description": "A key for a program that is not you: it writes stores (POST /store/<id>), rings him (POST /notify) or posts arrivals (POST /in/<source>) on the inbox listener with Authorization: Bearer <token>, within its scope only: the stores it may write, the sources it may post to, whether it may notify. The token is shown once; keep it where the program reads it. Without arguments it lists the tokens and their scopes; remove revokes one. The shared webhook secret keeps working for what already uses it.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "A name for the program holding it (pr-flow)"},
            "stores": {"type": "array", "items": {"type": "string"}, "description": "Store ids it may write, or [\"*\"]"},
            "sources": {"type": "array", "items": {"type": "string"}, "description": "Inbox sources it may post to"},
            "notify": {"type": "boolean", "description": "Whether it may ring him"},
            "remove": {"type": "boolean"},
        }, "required": []},
    }),
    (records.events, {
        "name": "app_events",
        "description": "What happened on his side since you last looked, oldest first: his edits on the phone (changes: a store's value, a record's fields, a record added or removed, a line of a text store, each with the page or card it came from and its number n; already applied on the phone and in the files) and what arrived from outside for you to process (arrived: a voice note, a meeting recording, a mail; what you have not read yet, now marked read; for a handler job, once its run ends well). A handler job is told which to read (after: the number of the last change it handled; source: its own). since narrows both to what came after a time.",
        "parameters": {"type": "object", "properties": {
            "after": {"type": "integer", "description": "Changes numbered after this one, all of them"},
            "since": {"type": "string", "description": "ISO time: only what came after it, read or not"},
            "source": {"type": "string", "description": "Arrivals from this source only; without it, every source but those with a job of their own"},
            "limit": {"type": "integer", "description": "At most this many of each (50 changes, 20 arrivals unless said)"},
            "only": {"type": "string", "enum": ["changes", "arrived"], "description": "One of the two lists only"},
        }, "required": []},
    }),
    (data.search, {
        "name": "app_search",
        "description": "Find what you built for him from here, as his Search does on the phone: pages by what they show, and the records of the declared stores by their declared title, subtitle and words. Without a query: the declared stores and how many records each has, and the pages. Accents and case do not matter.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Words, all of which must be found"},
            "in": {"type": "array", "items": {"type": "string"}, "description": "Only these: page, or a store's id"},
        }, "required": []},
    }),
    (activities.tool, {
        "name": "app_activity",
        "description": "Run a Live Activity on the lock screen and Dynamic Island, bound to a store: start sends the design, {views: {region: view}, components} with the regions lock, lockCompact, leading, trailing, center, bottom, compactLeading, compactTrailing, minimal under views (lock gets about 128pt of height, so always send lockCompact) over a JSON store whose value is its data ($data.gate). From then on every write to the store's file, by you (app_data), a flow, a script or a command, is a push to the activity within seconds, with no tool call; \"ended\": true in the store ends it, \"alert\": {title, body} in the store rings once per distinct alert. The store must stay small (about 3KB compressed): keep in it what the design reads. end ends one by hand; without an id it lists the running ones. The alert line is shown by iOS unencrypted: keep it generic.",
        "parameters": {"type": "object", "properties": {
            "action": {"type": "string", "enum": ["start", "end"]},
            "id": {"type": "string"},
            "store": {"type": "string", "description": "The JSON store the activity shows and follows"},
            "design": OBJECT,
            "alert": {**OBJECT, "description": "{title, body} with the start"},
        }, "required": []},
    }),
    (data.widget, {
        "name": "app_widget",
        "description": "A Home Screen or Lock Screen widget: a component drawn over a JSON store's value (read as $data.<key>), in the sizes given, redrawn as the store changes, with the app closed too. He adds the widget on his Home Screen or Lock Screen himself and picks one of yours by name, so make it and tell him in one line. On the Lock Screen it is drawn in one tint: rectangular holds about three short lines, circular a number or a Gauge, inline one Text above the clock. A widget is drawn by WidgetKit: stacks, Text, Image, Gauge, ProgressView, Spacer, Divider, shapes; no inputs, no scrolling; a Button whose action opens a page, a screen or a conversation opens the app there. Without arguments it lists the widgets; remove deletes one.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"},
            "store": {"type": "string", "description": "The JSON store it shows"},
            "component": {"type": "string", "description": "The component drawn over the store, reading it as $data"},
            "families": {"type": "array", "items": {"type": "string", "enum": ["small", "medium", "large", "rectangular", "circular", "inline"]}, "description": "The sizes it offers: small, medium, large on the Home Screen, rectangular, circular, inline on the Lock Screen; the three Home Screen ones by default"},
            "remove": {"type": "boolean"},
        }, "required": []},
    }),
    (commands.tool, {
        "name": "app_command",
        "description": "Bind a command: a name a tap on his phone runs here with no model on the way ({\"command\": id, \"args\": {…}} on a page or a card; the page reads $commands.<id> for its status and result). Bind it to a script (a file under the scripts folder, executable, given its args as JSON on stdin, its stdout the result), a Windmill flow (its path; the args are its input) or a cron job (the model, every tap: start there when you do not know what the command should do yet, then write the program and rebind). Give it a description, its contract: what one run must achieve. A supervisor job is made with it and looks at the runs when one fails, on a sample, when one is unlike the others, and once a day: it judges them against the contract and fixes the program, with nothing asked of him (see Commands in the building-pages skill). What the program writes to a store shows on the pages that read it. Without arguments it lists the commands; with only an id it shows one with its last runs: what he ran, with what, what came of it and what it wrote.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string", "description": "The command's name, as a page names it"},
            "description": {"type": "string", "description": "The contract: what one run must achieve, in one or two sentences"},
            "script": {"type": "string", "description": "A script under the scripts folder (named relative to it), executable: its args come as JSON on stdin, its stdout is the result, a non-zero exit is a failure with the last line of stderr as the reason"},
            "flow": {"type": "string", "description": "A Windmill flow's path (f/folder/name): run with the args as its input, waited for, its result the command's"},
            "job": {"type": "string", "description": "A cron job's id: run with the args in its prompt, the model deciding each time"},
            "timeout": {"type": "integer", "description": "Seconds a run may take (default 120, at most 3600)"},
            "sample": {"type": "integer", "description": "Pin how many runs the supervisor waits for between looks (default: every run for a new command, then doubling to 20, back to every run after a failure)"},
            "remove": {"type": "boolean", "description": "Unbind it and remove its supervisor"},
        }, "required": []},
    }),
]


_JSON_HINTS = {
    "Extra data": "the JSON is already complete before this point: a } or ] too many closes it early",
    "Expecting ',' delimiter": "the brackets do not match here: a } or ] too many just before, or a missing comma",
    "Expecting property name enclosed in double quotes": "a key is not in double quotes, or a comma is left before a }",
    "Expecting value": "a value is missing or malformed here",
    "Unterminated string": "a string is not closed, often a \" inside text that is not escaped",
}


def unparsed(name: str, shape: str, text: str, error: json.JSONDecodeError) -> str:
    """Where the model's JSON breaks, shown in its own text: the mistake is in
    what it wrote, and seeing the spot is what lets it fix it."""
    before, after = text[max(0, error.pos - 60):error.pos], text[error.pos:error.pos + 30]
    hint = next((hint for start, hint in _JSON_HINTS.items() if error.msg.startswith(start)), error.msg)
    return (f"{name} must be a JSON {shape}; it came as a string that does not parse at character {error.pos} "
            f"(line {error.lineno}, column {error.colno}): {hint}. Here: …{before}⟨HERE⟩{after}… "
            "Fix it in what you write; for long JSON, build it in execute_code, json.dump the arguments to a file and "
            "pass its path as from_file instead of copying it back.")


def structured(handler, schema: dict):
    """Models sometimes send an object or list parameter as a JSON string: it is
    read as what it says, or refused with where it does not parse."""
    shapes = {name: shape for name, spec in schema["parameters"]["properties"].items() if (shape := _shape(spec))}
    required = list(schema["parameters"].get("required", []))
    known = set(schema["parameters"]["properties"]) - {"from_file"}

    async def call(args: dict, **kwargs) -> str:
        args = dict(args)
        written_by_file = False
        if path := args.pop("from_file", None):
            written_by_file = True
            try:
                written = json.loads(Path(path).expanduser().read_text())
            except (OSError, ValueError) as error:
                return session.answer({"error": f"from_file could not be read as JSON: {error}"})
            if not isinstance(written, dict):
                return session.answer({"error": "from_file holds a JSON object of the tool's arguments"})
            if clash := sorted(name for name in set(written) & set(args)
                               if isinstance(written[name], (dict, list)) and written[name] != args[name]):
                return session.answer({"error": f"{', '.join(clash)} came both in from_file and in the call, differently; "
                                                "the call's would win and the file's be lost: put it in one place"})
            args = {**written, **args}
        if unknown := sorted(set(args) - known):
            hint = (": from_file holds the call's whole arguments, like {\"id\": …, \"patch\": {…}}, not one of them"
                    if written_by_file else f"; it takes {', '.join(sorted(known))}")
            return session.answer({"error": f"{schema.get('name', 'This tool')} does not take {', '.join(unknown)}{hint}"})
        if missing := [name for name in required if args.get(name) is None]:
            return session.answer({"error": f"Missing {', '.join(missing)}"})
        for name, shape in shapes.items():
            if not isinstance(args.get(name), str):
                continue
            said = " or ".join(shape)
            try:
                args[name] = json.loads(args[name])
            except json.JSONDecodeError as error:
                return session.answer({"error": unparsed(name, said, args[name], error)})
            if not isinstance(args[name], tuple(_SHAPES[kind] for kind in shape)):
                return session.answer({"error": f"{name} must be a JSON {said}"})
        return await handler(args, **kwargs)

    return call


_SHAPES = {"object": dict, "array": list}


def _shape(spec: dict) -> tuple[str, ...]:
    """The structured kinds a parameter takes: one, or the ones among several."""
    kinds = spec.get("type")
    return tuple(kind for kind in (kinds if isinstance(kinds, list) else [kinds]) if kind in _SHAPES)
