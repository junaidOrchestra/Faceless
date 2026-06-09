// Content "vibe" themes for the setup screen. When the user picks a vibe (instead
// of "match my script"), every beat is filled from this theme rather than the
// transcript. The `id` slugs MUST match the backend registry (orchestrator/app/vibes.py).

import {
  Building2,
  CloudRain,
  Mountain,
  PawPrint,
  Rocket,
  Snowflake,
  Sparkles,
  Sun,
  Sunset,
  Trees,
  Waves,
  Plane,
  type LucideIcon,
} from "lucide-react";

export type VibeId =
  | "space"
  | "forest"
  | "ocean"
  | "mountains"
  | "desert"
  | "rain"
  | "city_nights"
  | "aerial"
  | "wildlife"
  | "sky"
  | "snow"
  | "abstract";

/** The content theme chosen in setup: match the script, or fill from a vibe. */
export type ContentTheme = { mode: "script" } | { mode: "vibe"; vibe: VibeId };

export type Vibe = {
  id: VibeId;
  label: string;
  mood: string;
  icon: LucideIcon;
  // Tailwind gradient classes for the card thumbnail.
  gradient: string;
};

export const VIBES: Vibe[] = [
  {
    id: "space",
    label: "Space & Cosmos",
    mood: "Awe · motivation · meditation",
    icon: Rocket,
    gradient: "from-indigo-900 via-purple-800 to-fuchsia-700",
  },
  {
    id: "forest",
    label: "Forest & Woods",
    mood: "Calm · focus · grounding",
    icon: Trees,
    gradient: "from-emerald-900 via-green-700 to-lime-600",
  },
  {
    id: "ocean",
    label: "Ocean & Underwater",
    mood: "Relaxation · sleep",
    icon: Waves,
    gradient: "from-sky-900 via-cyan-700 to-teal-500",
  },
  {
    id: "mountains",
    label: "Mountains & Peaks",
    mood: "Epic · motivational",
    icon: Mountain,
    gradient: "from-slate-800 via-slate-600 to-blue-400",
  },
  {
    id: "desert",
    label: "Desert & Dunes",
    mood: "Minimal · meditative",
    icon: Sun,
    gradient: "from-amber-700 via-orange-500 to-yellow-400",
  },
  {
    id: "rain",
    label: "Rain & Storm",
    mood: "Cozy · study · sleep",
    icon: CloudRain,
    gradient: "from-slate-900 via-slate-700 to-sky-600",
  },
  {
    id: "city_nights",
    label: "City Nights & Urban",
    mood: "Moody · hustle · lo-fi",
    icon: Building2,
    gradient: "from-zinc-900 via-purple-900 to-rose-700",
  },
  {
    id: "aerial",
    label: "Aerial & Drone",
    mood: "Cinematic · sweeping · epic",
    icon: Plane,
    gradient: "from-cyan-800 via-sky-600 to-emerald-500",
  },
  {
    id: "wildlife",
    label: "Wildlife & Animals",
    mood: "Nature-doc calm",
    icon: PawPrint,
    gradient: "from-yellow-800 via-amber-600 to-orange-500",
  },
  {
    id: "sky",
    label: "Sky, Clouds & Sunset",
    mood: "Peaceful · uplifting",
    icon: Sunset,
    gradient: "from-orange-600 via-rose-500 to-indigo-500",
  },
  {
    id: "snow",
    label: "Snow & Winter",
    mood: "Serene · seasonal",
    icon: Snowflake,
    gradient: "from-slate-300 via-sky-300 to-blue-400",
  },
  {
    id: "abstract",
    label: "Abstract & Light",
    mood: "Neutral backdrop · focus · lo-fi",
    icon: Sparkles,
    gradient: "from-violet-700 via-fuchsia-600 to-amber-400",
  },
];

export function vibeLabel(id: VibeId): string {
  return VIBES.find((v) => v.id === id)?.label ?? id;
}
