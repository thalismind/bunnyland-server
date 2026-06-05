"""A hand-built showcase world: a quirky NYC apartment building (spec 21.4, 28.2).

Where ``examples.py`` ships one tiny demo per sim package, this is a single larger life-sim
scene — a five-storey walk-up full of eccentric tenants, each with a backstory, a furnished
apartment, and a daily routine. It exercises the life-sim package end to end (careers,
skills, money, homes, relationships, routines) plus the readable/secret-area plumbing, and
gives the web inspector a meaty, navigable map to explore.

Deterministic and offline, like the other demos: ``serve --generator apartment-demo``.
"""

from __future__ import annotations

from ..core.components import (
    DescriptionComponent,
    EditorDisplayComponent,
    IdentityComponent,
    KeyComponent,
    PortableComponent,
    ReadableComponent,
)
from ..core.ecs import replace_component, spawn_entity
from ..core.edges import ContainmentMode, Contains, ExitTo
from .generators import GenOptions, WorldGenerator
from .instantiate import InstantiatedWorld, instantiate
from .proposal import CharacterSpec, ExitSpec, ObjectSpec, RoomSpec, WorldProposal

HOUR = 60 * 60


def _add(actor, room_id, components):
    """Spawn an entity carrying ``components`` and drop it in ``room_id``."""
    entity = spawn_entity(actor.world, components)
    actor.world.get_entity(room_id).add_relationship(
        Contains(mode=ContainmentMode.ROOM_CONTENT), entity.id
    )
    return entity


def _note(actor, room_id, name, title, text, *, emoji="\U0001f4dc"):
    """A readable object whose text is the secret/info to be found."""
    return _add(actor, room_id, [
        IdentityComponent(name=name, kind="paper"),
        PortableComponent(can_pick_up=True),
        ReadableComponent(title=title, text=text),
        EditorDisplayComponent(emoji=emoji),
    ])


def _backstory(actor, entity_id, *, short, long, appearance="", emoji=""):
    """Replace the auto-generated description with a colourful one (+ optional icon)."""
    entity = actor.world.get_entity(entity_id)
    replace_component(entity, DescriptionComponent(short=short, long=long, appearance=appearance))
    if emoji:
        entity.add_component(EditorDisplayComponent(emoji=emoji))


def _routines(actor, character_id, schedule):
    """Attach a daily schedule as one routine entity per (hour, activity), linked by edge."""
    from ..mechanics.lifesim import HasRoutine, RoutineComponent

    character = actor.world.get_entity(character_id)
    for hour, activity in schedule:
        routine = spawn_entity(actor.world, [
            RoutineComponent(activity=activity, interval_seconds=24 * HOUR,
                             next_due_epoch=hour * HOUR)
        ])
        character.add_relationship(HasRoutine(), routine.id)


def _status(actor, left_id, right_id, status):
    """Add a mutual relationship-status edge between two tenants."""
    from ..mechanics.lifesim import RelationshipStatus

    actor.world.get_entity(left_id).add_relationship(
        RelationshipStatus(status=status, since_epoch=0), right_id)
    actor.world.get_entity(right_id).add_relationship(
        RelationshipStatus(status=status, since_epoch=0), left_id)


# Tenant dossiers: identity, livelihood, and a daily rhythm. Driven through one loop so the
# augmentation pass stays flat. ``home`` ties each tenant to the apartment they own.
_RESIDENTS = (
    {
        "key": "margot", "home": "apt_margot", "emoji": "\U0001f3a8", "stage": "adult",
        "career": ("painter", 12), "skills": {"painting": 6, "sculpting": 2}, "funds": 90,
        "aspiration": ("A Painted Masterpiece", ("a sold canvas", "a gallery show")),
        "known_for": ("the turpentine reek under her door",),
        "short": "Margot Beaumont, a paint-flecked bunny",
        "long": "A failed-then-feted abstract painter who arrived from Marseille with two "
                "suitcases of brushes and no plan. She paints only by north light and signs "
                "nothing, convinced fame is a kind of forgery.",
        "appearance": "ink-black ears, a smock that is itself a canvas",
        "schedule": ((9, "chase the north light with a fresh canvas"),
                     (14, "haggle with the gallery downtown"),
                     (23, "varnish the day's work by candlelight")),
    },
    {
        "key": "lew", "home": "apt_lew", "emoji": "✍️", "stage": "adult",
        "career": ("bartending poet", 9), "skills": {"poetry": 7, "mixology": 3}, "funds": 18,
        "aspiration": ("A Slim Published Volume", ("finish the manuscript",)),
        "known_for": ("reciting at the mailboxes after midnight",),
        "short": "Llewyn 'Lew' Ashgrove, a rumpled bunny poet",
        "long": "Tends bar at the Blue Burrow and writes elegies for things that never "
                "happened. Three months behind on rent and serenely unbothered by it.",
        "appearance": "a moth-eaten cardigan, ink-stained paws",
        "schedule": ((11, "nurse coffee and a hangover"),
                     (20, "read at the open mic"),
                     (2, "scribble the unfinishable poem")),
    },
    {
        "key": "dizzy", "home": "apt_dizzy", "emoji": "\U0001f3b7", "stage": "adult",
        "career": ("jazz trumpeter", 15), "skills": {"trumpet": 8, "composition": 4}, "funds": 60,
        "aspiration": ("The Perfect Solo", ("cut a record",)),
        "known_for": ("muted solos bleeding through the ceiling at 3am",),
        "short": "Dizzy Okonkwo, a nocturnal bunny trumpeter",
        "long": "Plays the late set at the Blue Burrow and sleeps through the daylight world. "
                "Swears the building's pipes hum in B-flat and writes around them.",
        "appearance": "a porkpie hat, a brass mute always in one paw",
        "schedule": ((13, "sleep off the night's gig"),
                     (22, "rehearse with the mutes in"),
                     (1, "blow the late set at the Blue Burrow")),
    },
    {
        "key": "pearl", "home": "apt_pearl", "emoji": "\U0001f33b", "stage": "elder",
        "career": ("retired botanist", 0), "skills": {"gardening": 9, "herbalism": 5}, "funds": 320,
        "aspiration": ("The Roof in Full Bloom", ("the moonflower opens",)),
        "known_for": ("leaving jars of preserves on every doorstep",),
        "short": "Pearl Nakamura, an elderly bunny gardener",
        "long": "A retired botanist who has quietly turned the tar roof into a hanging garden. "
                "She remembers every tenant who has ever lived here and most of their secrets.",
        "appearance": "a sun hat, soil under every claw",
        "schedule": ((6, "water the rooftop beds at first light"),
                     (17, "brew nettle tea for the building"),
                     (21, "press flowers between the heavy books")),
    },
    {
        "key": "sed", "home": "apt_sed", "emoji": "\U0001f527", "stage": "adult",
        "career": ("tinkerer", 10), "skills": {"engineering": 7, "lockpicking": 4}, "funds": 45,
        "aspiration": ("The Machine That Works", ("it stops humming",)),
        "known_for": ("the machines that hum behind 1B's door",),
        "short": "Sed Volkov, a wild-eyed bunny inventor",
        "long": "Builds contraptions no one ordered out of parts no one missed. Convinced the "
                "super reads everyone's mail and that the building is older than it admits.",
        "appearance": "welding goggles shoved up over both ears",
        "schedule": ((10, "solder the day's contraption"),
                     (15, "field-test the invention in the hall"),
                     (0, "patrol the stairwell for intruders")),
    },
    {
        "key": "agnes", "home": "apt_agnes", "emoji": "\U0001f50d", "stage": "elder",
        "career": ("retired detective", 0), "funds": 140,
        "skills": {"observation": 9, "deduction": 8},
        "known_for": ("knowing who came home, and when, and with whom",),
        "short": "Agnes Cole, a sharp-eyed retired bunny detective",
        "long": "Thirty years on the force, now retired to a chair by the window with a pair of "
                "binoculars and a casebook she still fills. Nothing in this building escapes her.",
        "appearance": "a grey trench coat she never takes off",
        "schedule": ((7, "watch the stoop over coffee"),
                     (12, "update the casebook"),
                     (19, "tail whatever doesn't add up")),
    },
    {
        "key": "bruno", "home": "apt_bruno", "emoji": "\U0001f9d1‍\U0001f373", "stage": "adult",
        "career": ("supper-club chef", 13), "skills": {"cooking": 8, "baking": 7}, "funds": 160,
        "business": ("Bruno's Secret Supper", 30),
        "known_for": ("the smell of onion soup that fills the second floor",),
        "short": "Bruno Malloy, a big-hearted bunny chef",
        "long": "Runs an unlicensed supper club out of 2B three nights a week and feeds half the "
                "building for free the other four. Knows every tenant's order by heart.",
        "appearance": "a flour-dusted apron, forearms like rope",
        "schedule": ((5, "proof the morning's dough"),
                     (18, "host the secret supper"),
                     (23, "scrub the pots and plan tomorrow")),
    },
    {
        "key": "coco", "home": "apt_coco", "emoji": "\U0001f4f1", "stage": "adult",
        "career": ("content creator", 8), "skills": {"dance": 6, "self-promotion": 9}, "funds": 75,
        "aspiration": ("A Million Followers", ("a video goes viral",)),
        "known_for": ("the ring-light glow leaking under 4B's door at all hours",),
        "short": "Coco Devlin, a relentlessly online bunny dancer",
        "long": "Films every waking moment for an audience that may or may not exist. Feuds with "
                "1B over the noise and has never once lost an argument on camera.",
        "appearance": "a hoodie, a phone permanently at arm's length",
        "schedule": ((8, "film the morning routine"),
                     (16, "run dance drills for the feed"),
                     (22, "go live for the night owls")),
    },
    {
        "key": "otis", "home": "basement", "emoji": "\U0001f9f0", "stage": "adult",
        "career": ("superintendent", 11), "skills": {"plumbing": 7, "snooping": 6}, "funds": 200,
        "known_for": ("having a key to every door, and an opinion on every tenant",),
        "short": "Otis Fenn, the gruff bunny superintendent",
        "long": "Keeps the boiler breathing and the building's secrets sorted. Lives in the "
                "basement, hears everything through the pipes, and trusts the cat under the floor "
                "more than any tenant.",
        "appearance": "a jangling key ring, a permanent grease smudge",
        "schedule": ((6, "stoke the groaning boiler"),
                     (13, "fix whatever broke overnight"),
                     (20, "make the evening rounds")),
    },
)


async def apartment_example(actor, seed: str, options: GenOptions) -> InstantiatedWorld:
    del options
    from ..mechanics.lifesim import (
        AspirationComponent,
        BusinessOwnerComponent,
        CareerComponent,
        HomeComponent,
        HouseholdFundsComponent,
        LifeStageComponent,
        OwnsBusiness,
        PartnerOf,
        ReputationComponent,
        SkillSetComponent,
    )

    proposal = WorldProposal(
        seed=seed,
        rooms=[
            # Outdoor approaches.
            RoomSpec(key="street", title="Mulberry Street Stoop", biome="city", light=0.8,
                     celsius=14.0),
            RoomSpec(key="alley", title="Side Alley", biome="city", light=0.3, celsius=13.0),
            RoomSpec(key="roof", title="Tar Beach Rooftop", biome="city", light=0.85,
                     celsius=15.0),
            # The vertical spine: lobby, four landings, the elevator car, and below-ground.
            RoomSpec(key="lobby", title="Lobby & Mailroom", biome="building", indoor=True,
                     light=0.6, celsius=20.0),
            RoomSpec(key="elevator", title="The Groaning Elevator", biome="building", indoor=True,
                     light=0.4, celsius=20.0),
            RoomSpec(key="land2", title="Second-Floor Landing", biome="building", indoor=True,
                     light=0.4, celsius=20.0),
            RoomSpec(key="land3", title="Third-Floor Landing", biome="building", indoor=True,
                     light=0.4, celsius=20.0),
            RoomSpec(key="land4", title="Fourth-Floor Landing", biome="building", indoor=True,
                     light=0.4, celsius=20.0),
            RoomSpec(key="land5", title="Fifth-Floor Landing", biome="building", indoor=True,
                     light=0.45, celsius=20.0),
            RoomSpec(key="basement", title="Boiler Room", biome="building", indoor=True,
                     light=0.2, celsius=26.0),
            RoomSpec(key="subbasement", title="The Warren Below", biome="building", indoor=True,
                     light=0.05, celsius=16.0),
            # Apartments.
            RoomSpec(key="apt_sed", title="Apartment 1B", biome="building", indoor=True,
                     light=0.5, celsius=21.0),
            RoomSpec(key="apt_margot", title="Apartment 2A", biome="building", indoor=True,
                     light=0.7, celsius=21.0),
            RoomSpec(key="apt_bruno", title="Apartment 2B", biome="building", indoor=True,
                     light=0.6, celsius=23.0),
            RoomSpec(key="apt_agnes", title="Apartment 3A", biome="building", indoor=True,
                     light=0.5, celsius=21.0),
            RoomSpec(key="apt_lew", title="Apartment 3B", biome="building", indoor=True,
                     light=0.45, celsius=20.0),
            RoomSpec(key="apt_dizzy", title="Apartment 4A", biome="building", indoor=True,
                     light=0.3, celsius=21.0),
            RoomSpec(key="apt_coco", title="Apartment 4B", biome="building", indoor=True,
                     light=0.8, celsius=21.0),
            RoomSpec(key="apt_pearl", title="Apartment 5A", biome="building", indoor=True,
                     light=0.7, celsius=22.0),
        ],
        exits=[
            # Street <-> lobby <-> alley.
            ExitSpec(from_key="street", direction="in", to_key="lobby"),
            ExitSpec(from_key="lobby", direction="out", to_key="street"),
            ExitSpec(from_key="street", direction="alley", to_key="alley"),
            ExitSpec(from_key="alley", direction="out", to_key="street"),
            # Stairwell: lobby up through the landings to the roof.
            ExitSpec(from_key="lobby", direction="up", to_key="land2"),
            ExitSpec(from_key="land2", direction="down", to_key="lobby"),
            ExitSpec(from_key="land2", direction="up", to_key="land3"),
            ExitSpec(from_key="land3", direction="down", to_key="land2"),
            ExitSpec(from_key="land3", direction="up", to_key="land4"),
            ExitSpec(from_key="land4", direction="down", to_key="land3"),
            ExitSpec(from_key="land4", direction="up", to_key="land5"),
            ExitSpec(from_key="land5", direction="down", to_key="land4"),
            ExitSpec(from_key="land5", direction="up", to_key="roof"),
            ExitSpec(from_key="roof", direction="down", to_key="land5"),
            # Basement off the lobby.
            ExitSpec(from_key="lobby", direction="down", to_key="basement"),
            ExitSpec(from_key="basement", direction="up", to_key="lobby"),
            # The elevator car as a hub to every floor.
            ExitSpec(from_key="lobby", direction="elevator", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="lobby", to_key="lobby"),
            ExitSpec(from_key="elevator", direction="2", to_key="land2"),
            ExitSpec(from_key="land2", direction="elevator", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="3", to_key="land3"),
            ExitSpec(from_key="land3", direction="elevator", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="4", to_key="land4"),
            ExitSpec(from_key="land4", direction="elevator", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="5", to_key="land5"),
            ExitSpec(from_key="land5", direction="elevator", to_key="elevator"),
            ExitSpec(from_key="elevator", direction="roof", to_key="roof"),
            ExitSpec(from_key="roof", direction="elevator", to_key="elevator"),
            # Apartment doors off their landings (1B opens onto the lobby).
            ExitSpec(from_key="lobby", direction="1b", to_key="apt_sed"),
            ExitSpec(from_key="apt_sed", direction="out", to_key="lobby"),
            ExitSpec(from_key="land2", direction="2a", to_key="apt_margot"),
            ExitSpec(from_key="apt_margot", direction="out", to_key="land2"),
            ExitSpec(from_key="land2", direction="2b", to_key="apt_bruno"),
            ExitSpec(from_key="apt_bruno", direction="out", to_key="land2"),
            ExitSpec(from_key="land3", direction="3a", to_key="apt_agnes"),
            ExitSpec(from_key="apt_agnes", direction="out", to_key="land3"),
            ExitSpec(from_key="land3", direction="3b", to_key="apt_lew"),
            ExitSpec(from_key="apt_lew", direction="out", to_key="land3"),
            ExitSpec(from_key="land4", direction="4a", to_key="apt_dizzy"),
            ExitSpec(from_key="apt_dizzy", direction="out", to_key="land4"),
            ExitSpec(from_key="land4", direction="4b", to_key="apt_coco"),
            ExitSpec(from_key="apt_coco", direction="out", to_key="land4"),
            ExitSpec(from_key="land5", direction="5a", to_key="apt_pearl"),
            ExitSpec(from_key="apt_pearl", direction="out", to_key="land5"),
        ],
        objects=[
            # Lobby & street: food, water, and the building's nervous system.
            ObjectSpec(key="o_cooler", room_key="lobby", name="the water cooler", kind="water",
                       hydration=25.0, portable=False),
            ObjectSpec(key="o_mailboxes", room_key="lobby", name="a wall of brass mailboxes",
                       kind="container", portable=False),
            ObjectSpec(key="o_stoop", room_key="street", name="the worn front stoop",
                       kind="item", portable=False),
            ObjectSpec(key="o_dumpster", room_key="alley", name="a battered dumpster",
                       kind="container", portable=False),
            # Roof garden: things to eat, drink, and one rare bloom.
            ObjectSpec(key="o_tomatoes", room_key="roof", name="a vine of ripe tomatoes",
                       kind="food", nutrition=4.0, satiety=18.0, portable=True),
            ObjectSpec(key="o_rainbarrel", room_key="roof", name="a brimming rain barrel",
                       kind="water", hydration=30.0, portable=False),
            ObjectSpec(key="o_moonflower", room_key="roof", name="a rare night-blooming moonflower",
                       kind="item", portable=True),
            ObjectSpec(key="o_beds", room_key="roof", name="rows of raised garden beds",
                       kind="item", portable=False),
            # Bruno's kitchen.
            ObjectSpec(key="o_croissants", room_key="apt_bruno", name="a tray of warm croissants",
                       kind="food", nutrition=5.0, satiety=22.0, portable=True),
            ObjectSpec(key="o_soup", room_key="apt_bruno", name="a pot of onion soup",
                       kind="food", nutrition=6.0, satiety=28.0, portable=False),
            ObjectSpec(key="o_recipebox", room_key="apt_bruno", name="a battered recipe box",
                       kind="container", portable=True),
            # Margot's studio.
            ObjectSpec(key="o_canvas", room_key="apt_margot", name="an unfinished masterpiece",
                       kind="item", portable=False),
            ObjectSpec(key="o_paints", room_key="apt_margot", name="a heap of squeezed paint tubes",
                       kind="item", portable=True),
            # Lew's garret.
            ObjectSpec(key="o_typewriter", room_key="apt_lew", name="a jammed typewriter",
                       kind="item", portable=False),
            ObjectSpec(key="o_coldcoffee", room_key="apt_lew", name="a mug of cold coffee",
                       kind="water", hydration=8.0, renewable=False, portable=True),
            # Dizzy's pad.
            ObjectSpec(key="o_trumpet", room_key="apt_dizzy", name="a muted brass trumpet",
                       kind="item", portable=True),
            ObjectSpec(key="o_records", room_key="apt_dizzy", name="leaning stacks of records",
                       kind="item", portable=False),
            # Agnes's perch.
            ObjectSpec(key="o_binoculars", room_key="apt_agnes", name="a worn pair of binoculars",
                       kind="item", portable=True),
            ObjectSpec(key="o_tea", room_key="apt_agnes", name="a cooling cup of tea",
                       kind="water", hydration=10.0, renewable=False, portable=True),
            # Coco's set.
            ObjectSpec(key="o_ringlight", room_key="apt_coco", name="a glaring ring light",
                       kind="item", portable=False),
            ObjectSpec(key="o_protein", room_key="apt_coco", name="a box of protein bars",
                       kind="food", nutrition=3.0, satiety=12.0, portable=True),
            # Sed's workshop.
            ObjectSpec(key="o_contraption", room_key="apt_sed", name="a humming contraption",
                       kind="item", portable=False),
            ObjectSpec(key="o_multitool", room_key="apt_sed", name="a skeleton multitool",
                       kind="item", portable=True),
            # Pearl's parlour.
            ObjectSpec(key="o_seeds", room_key="apt_pearl", name="a drawer of seed packets",
                       kind="item", portable=True),
            ObjectSpec(key="o_chamomile", room_key="apt_pearl", name="a pot of chamomile tea",
                       kind="water", hydration=20.0, portable=False),
            # Below ground.
            ObjectSpec(key="o_boiler", room_key="basement", name="the groaning boiler",
                       kind="item", portable=False),
            ObjectSpec(key="o_lostkeys", room_key="subbasement", name="a hoard of lost keys",
                       kind="item", portable=True),
        ],
        characters=[
            CharacterSpec(key="margot", name="Margot Beaumont", room_key="apt_margot",
                          controller="suspended", traits=("temperamental", "generous")),
            CharacterSpec(key="lew", name="Llewyn Ashgrove", room_key="apt_lew",
                          controller="suspended", traits=("melancholic", "charming")),
            CharacterSpec(key="dizzy", name="Dizzy Okonkwo", room_key="apt_dizzy",
                          controller="suspended", traits=("nocturnal", "easygoing")),
            CharacterSpec(key="pearl", name="Pearl Nakamura", room_key="apt_pearl",
                          controller="suspended", traits=("nurturing", "observant")),
            CharacterSpec(key="sed", name="Sed Volkov", room_key="apt_sed",
                          controller="suspended", traits=("paranoid", "ingenious")),
            CharacterSpec(key="agnes", name="Agnes Cole", room_key="apt_agnes",
                          controller="suspended", traits=("watchful", "dry")),
            CharacterSpec(key="bruno", name="Bruno Malloy", room_key="apt_bruno",
                          controller="suspended", traits=("warm", "loud")),
            CharacterSpec(key="coco", name="Coco Devlin", room_key="apt_coco",
                          controller="llm", llm_profile="performer", traits=("vain", "driven"),
                          goals=("go viral",)),
            CharacterSpec(key="otis", name="Otis Fenn", room_key="basement",
                          controller="llm", llm_profile="superintendent", traits=("gruff", "nosy"),
                          goals=("keep the building standing",)),
            # The one animal: the rat-man who lives under the basement.
            CharacterSpec(key="reginald", name="Reginald, the Rat-Man", room_key="subbasement",
                          species="rat", controller="llm", llm_profile="stray",
                          traits=("furtive", "courtly"),
                          goals=("guard the warren's secrets",)),
        ],
    )
    world = await instantiate(actor, proposal)

    async with actor._lock:
        rooms, chars = world.rooms, world.characters

        # Per-tenant: backstory, livelihood, a home, and a daily routine.
        for r in _RESIDENTS:
            cid = chars[r["key"]]
            _backstory(actor, cid, short=r["short"], long=r["long"],
                       appearance=r["appearance"], emoji=r["emoji"])
            entity = actor.world.get_entity(cid)
            title, pay = r["career"]
            if pay:
                entity.add_component(CareerComponent(title=title, hourly_pay=pay, level=2))
            else:  # retiree: title only, no shifts
                entity.add_component(CareerComponent(title=title, hourly_pay=0, active=False))
            entity.add_component(SkillSetComponent(levels=dict(r["skills"])))
            entity.add_component(HouseholdFundsComponent(balance=r["funds"]))
            entity.add_component(LifeStageComponent(stage=r["stage"]))
            if "aspiration" in r:
                name, milestones = r["aspiration"]
                entity.add_component(AspirationComponent(name=name, milestones=milestones))
            if "known_for" in r:
                entity.add_component(ReputationComponent(known_for=r["known_for"]))
            actor.world.get_entity(rooms[r["home"]]).add_component(
                HomeComponent(owner_id=str(cid)))
            _routines(actor, cid, r["schedule"])

        # Bruno's unlicensed supper club is a business he owns.
        bruno = actor.world.get_entity(chars["bruno"])
        business = spawn_entity(actor.world,
                                [BusinessOwnerComponent(name="Bruno's Secret Supper",
                                                        default_price=30)])
        bruno.add_relationship(OwnsBusiness(), business.id)

        # The rat-man: a backstory and an icon, but no career or home of his own.
        _backstory(actor, chars["reginald"],
                   short="Reginald, a courtly rat in a moth-eaten waistcoat",
                   long="Once the building's night janitor, he slipped below decades ago and "
                        "never came back up. He knows where every spare key is hidden and trades "
                        "secrets for crusts of Bruno's bread.",
                   appearance="a frayed waistcoat, whiskers gone silver",
                   emoji="\U0001f400")
        _routines(actor, chars["reginald"],
                  ((3, "scavenge the alley after the supper club"),
                   (15, "patrol the pipes and tunnels"),
                   (23, "tally the warren ledger by candle")))

        # A web of building relationships.
        _status(actor, chars["margot"], chars["lew"], "romance")
        actor.world.get_entity(chars["margot"]).add_relationship(
            PartnerOf(since_epoch=0), chars["lew"])
        actor.world.get_entity(chars["lew"]).add_relationship(
            PartnerOf(since_epoch=0), chars["margot"])
        _status(actor, chars["bruno"], chars["pearl"], "friend")
        _status(actor, chars["bruno"], chars["dizzy"], "friend")
        _status(actor, chars["sed"], chars["coco"], "rival")
        _status(actor, chars["agnes"], chars["otis"], "acquaintance")

        # Custom icons for a few standout rooms in the inspector.
        actor.world.get_entity(rooms["roof"]).add_component(EditorDisplayComponent(emoji="\U0001f33f"))
        actor.world.get_entity(rooms["subbasement"]).add_component(
            EditorDisplayComponent(emoji="\U0001f573️"))
        actor.world.get_entity(rooms["elevator"]).add_component(
            EditorDisplayComponent(emoji="\U0001f6d7"))

        # Hidden passage: a loose grate behind the boiler down into the rat-man's warren.
        actor.world.get_entity(rooms["basement"]).add_relationship(
            ExitTo(direction="down", label="a loose grate behind the boiler", hidden=True),
            rooms["subbasement"])
        actor.world.get_entity(rooms["subbasement"]).add_relationship(
            ExitTo(direction="up", label="back up through the grate", hidden=True),
            rooms["basement"])

        # The master key the super carries, and a real key down in the lost-key hoard.
        _add(actor, rooms["basement"], [
            IdentityComponent(name="the building master key", kind="key"),
            PortableComponent(can_pick_up=True),
            KeyComponent(key_name="master"),
            EditorDisplayComponent(emoji="\U0001f5dd️"),
        ])

        # Secrets and info to be found across the building.
        _note(actor, rooms["apt_agnes"], "Agnes's casebook", "Casebook of A. Cole",
              "2B runs a supper club with no permit. 4B films in the stairwell after hours. "
              "The super keeps a spare key to every apartment on the ring at his belt. And "
              "something living moves behind the boiler at night.")
        _note(actor, rooms["subbasement"], "the warren ledger", "The Warren Ledger",
              "Every spare key in the building, and where its tenant hides it: 2A behind the "
              "loose baseboard, 3B under the typewriter, 5A in the third seed drawer. Knowledge "
              "is the only rent down here.")
        _note(actor, rooms["basement"], "a note behind a loose brick", "Behind the Brick",
              "To whoever finds this: the building is older than its cornerstone claims. There "
              "is a thirteenth mailbox with no name. Do not open it.")
        _note(actor, rooms["alley"], "a coded note in the dumpster", "A Coded Note",
              "BLUE BURROW. MIDNIGHT. BRING THE MOONFLOWER. — M")
        _note(actor, rooms["roof"], "a letter behind the water tank", "An Old Letter",
              "My dear, by the time the moonflower blooms again I will be gone from this roof, "
              "but the garden is yours. Mind the rat-man; he kept my secret, and now he keeps "
              "yours.")

    return world


APARTMENT_DEMO = WorldGenerator(
    name="apartment-demo", generate=apartment_example,
    description="A quirky NYC apartment building: nine eccentric tenants with backstories, "
                "homes, and daily routines, a rat-man below, and a few hidden corners.",
    uses_seed=False)


__all__ = ["APARTMENT_DEMO", "apartment_example"]
