// Marketing mirror of the product's content vibes
// (seemless/lib/vibes.ts + orchestrator/app/vibes.py). Kept in sync manually:
// this page is informational, the app remains the source of truth. Each vibe
// renders as an animated gradient card in the Vibes gallery.

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

export type Vibe = {
  id: string;
  label: string;
  mood: string;
  icon: LucideIcon;
  // Tailwind gradient classes for the card backdrop.
  gradient: string;
};

export const VIBES: Vibe[] = [
  {
    id: "space",
    label: "Space & Cosmos",
    mood: "Awe · motivation",
    icon: Rocket,
    gradient: "from-indigo-900 via-purple-800 to-fuchsia-700",
  },
  {
    id: "forest",
    label: "Forest & Woods",
    mood: "Calm · focus",
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
    id: "city_nights",
    label: "City Nights",
    mood: "Moody · hustle · lo-fi",
    icon: Building2,
    gradient: "from-zinc-900 via-purple-900 to-rose-700",
  },
  {
    id: "mountains",
    label: "Mountains & Peaks",
    mood: "Epic · motivational",
    icon: Mountain,
    gradient: "from-slate-800 via-slate-600 to-blue-400",
  },
  {
    id: "rain",
    label: "Rain & Storm",
    mood: "Cozy · study · sleep",
    icon: CloudRain,
    gradient: "from-slate-900 via-slate-700 to-sky-600",
  },
  {
    id: "sky",
    label: "Sky & Sunset",
    mood: "Peaceful · uplifting",
    icon: Sunset,
    gradient: "from-orange-600 via-rose-500 to-indigo-500",
  },
  {
    id: "aerial",
    label: "Aerial & Drone",
    mood: "Cinematic · sweeping",
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
    id: "desert",
    label: "Desert & Dunes",
    mood: "Minimal · meditative",
    icon: Sun,
    gradient: "from-amber-700 via-orange-500 to-yellow-400",
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
    mood: "Neutral backdrop · lo-fi",
    icon: Sparkles,
    gradient: "from-violet-700 via-fuchsia-600 to-amber-400",
  },
];
