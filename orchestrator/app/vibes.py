"""Content "vibe" themes for the vibe-mode clip search.

When a job's content theme is a *vibe* (rather than "match my script"), the
pipeline does not analyse the transcript for visuals. Instead it asks the LLM for
N stock-search keywords that all belong to the chosen vibe (one per beat), with
the per-vibe ``keywords`` below used as (a) example phrases that steer the LLM and
(b) a deterministic fallback/top-up when the LLM returns too few. Keep the
phrases plain, concrete, and rich on Pexels/Pixabay (1-3 words, no abstractions).

The slugs here MUST match the frontend vibe ids (see seemless/lib/vibes.ts).
"""

from __future__ import annotations

VIBES: dict[str, dict[str, object]] = {
    "space": {
        "label": "Space & Cosmos",
        "keywords": [
            "galaxy", "nebula", "starfield", "milky way", "earth from space",
            "aurora borealis", "moon surface", "rocket launch", "deep space",
            "spiral galaxy", "solar flare", "comet", "satellite orbit",
            "star cluster", "cosmic dust",
        ],
    },
    "forest": {
        "label": "Forest & Woods",
        "keywords": [
            "forest path", "tall trees", "sunlight through trees", "misty woods",
            "pine forest", "forest stream", "fallen leaves", "mossy rocks",
            "woodland canopy", "ferns", "redwood trees", "autumn forest",
            "forest floor", "morning fog forest", "birch trees",
        ],
    },
    "ocean": {
        "label": "Ocean & Underwater",
        "keywords": [
            "underwater ocean", "coral reef", "deep blue sea", "sea turtle",
            "ocean waves underwater", "sunlight underwater", "school of fish",
            "jellyfish", "diving ocean", "kelp forest", "calm sea surface",
            "tropical lagoon", "bubbles underwater", "ocean current", "reef fish",
        ],
    },
    "mountains": {
        "label": "Mountains & Peaks",
        "keywords": [
            "mountain range", "snowy peaks", "alpine sunrise", "mountain summit",
            "rocky cliffs", "mountain valley", "hiking ridge", "glacier",
            "fog over mountains", "mountain lake", "epic mountain vista",
            "climber on peak", "mountain clouds", "high altitude", "rugged peaks",
        ],
    },
    "desert": {
        "label": "Desert & Dunes",
        "keywords": [
            "sand dunes", "desert sunset", "rippled sand", "desert landscape",
            "lone dune", "wind on sand", "desert sky", "arid dunes",
            "golden desert", "footprints in sand", "desert horizon",
            "dry cracked earth", "sahara dunes", "minimal desert", "heat haze",
        ],
    },
    "rain": {
        "label": "Rain & Storm",
        "keywords": [
            "rain on window", "heavy rainfall", "storm clouds", "lightning storm",
            "rain drops", "wet street rain", "rainy night city", "thunderstorm",
            "rain puddle", "rain on leaves", "dark stormy sky", "drizzle",
            "rain ripples water", "umbrella rain", "downpour",
        ],
    },
    "city_nights": {
        "label": "City Nights & Urban",
        "keywords": [
            "city skyline night", "neon lights", "city traffic night",
            "downtown lights", "rainy city street", "urban night", "skyscrapers lit",
            "street lights night", "city timelapse night", "subway station",
            "moody alley", "bokeh city lights", "rooftop city view",
            "crosswalk night", "metro city",
        ],
    },
    "aerial": {
        "label": "Aerial & Drone",
        "keywords": [
            "aerial coastline", "drone over mountains", "aerial forest",
            "aerial city", "drone ocean waves", "aerial river", "flying over clouds",
            "aerial fields", "drone canyon", "aerial highway", "bird's eye landscape",
            "aerial island", "drone sunset", "sweeping aerial valley", "aerial desert",
        ],
    },
    "wildlife": {
        "label": "Wildlife & Animals",
        "keywords": [
            "lion savanna", "elephant herd", "birds flying", "deer in forest",
            "wolf wilderness", "eagle soaring", "whale ocean", "fox snow",
            "flock of birds", "wild horses", "safari animals", "owl close up",
            "butterfly flower", "bear river", "flamingos",
        ],
    },
    "sky": {
        "label": "Sky & Clouds & Sunset",
        "keywords": [
            "sunset sky", "golden hour clouds", "pink sky sunset", "clouds timelapse",
            "blue sky clouds", "dramatic sunset", "sky gradient dusk", "sunrise sky",
            "soft clouds", "orange horizon", "twilight sky", "cloudscape",
            "calm evening sky", "sun rays clouds", "pastel sky",
        ],
    },
    "snow": {
        "label": "Snow & Winter",
        "keywords": [
            "falling snow", "snowy forest", "winter landscape", "snow covered trees",
            "snowflakes close up", "frozen lake", "blizzard", "snowy mountains",
            "winter morning", "icicles", "snow field", "footprints in snow",
            "frost on window", "calm snowfall", "white winter scene",
        ],
    },
    "abstract": {
        "label": "Abstract & Light",
        "keywords": [
            "abstract light", "bokeh lights", "smooth gradient", "flowing ink",
            "soft light leaks", "glowing particles", "blurred neon", "liquid color",
            "light rays", "abstract loop", "calm gradient motion", "shimmer light",
            "soft focus glow", "minimal abstract", "color waves",
        ],
    },
}


def is_vibe(vibe: object) -> bool:
    return isinstance(vibe, str) and vibe in VIBES


def vibe_label(vibe: str) -> str:
    data = VIBES.get(vibe) or {}
    return str(data.get("label") or vibe)


def vibe_keywords_seed(vibe: str) -> list[str]:
    data = VIBES.get(vibe) or {}
    seed = data.get("keywords") or []
    return [str(k) for k in seed]  # type: ignore[union-attr]
