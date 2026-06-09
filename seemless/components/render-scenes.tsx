"use client";

import * as React from "react";
import { cn } from "@/lib/utils";

/**
 * A single playful "render in progress" scene: a big animated emoji character
 * plus a few floating accents, and its own set of funny status lines.
 *
 * Rendering a video is a multi-minute, CPU-bound job, so rather than make the
 * user stare at a percent we show one of these whimsical characters (picked at
 * random per render) and cycle through its texts. New scenes can be added just
 * by appending to {@link RENDER_SCENES}.
 */
export type RenderScene = {
  /** Stable key (used for React keys and the test page). */
  key: string;
  /** Human-friendly label, shown on the test/preview page. */
  label: string;
  /** The main character emoji. */
  emoji: string;
  /** Animation utility class applied to the main character. */
  motion: string;
  /** Optional inline style for the main character (e.g. slower duration). */
  motionStyle?: React.CSSProperties;
  /** Floating accent emojis (sparkles, snow, steam, …). */
  accents: { emoji: string; className: string; style?: React.CSSProperties }[];
  /** Funny status lines cycled while this scene is shown. */
  lines: string[];
};

// A reusable corner-sparkle accent set so every scene twinkles consistently.
const sparkles = (
  ...extra: { emoji: string; className: string; style?: React.CSSProperties }[]
): RenderScene["accents"] => [
  { emoji: "✨", className: "left-5 top-6 text-lg animate-twinkle" },
  {
    emoji: "⭐",
    className: "right-6 top-9 text-base animate-twinkle",
    style: { animationDelay: "0.5s" },
  },
  ...extra,
];

export const RENDER_SCENES: RenderScene[] = [
  {
    key: "wizard",
    label: "Wizard & wand",
    emoji: "🧙",
    motion: "animate-wand-wave",
    accents: sparkles(
      { emoji: "🪄", className: "bottom-8 right-7 text-xl animate-drift-across" },
      {
        emoji: "✨",
        className: "bottom-9 left-7 text-base animate-twinkle",
        style: { animationDelay: "1.1s" },
      },
    ),
    lines: [
      "The wizard is brewing your video…",
      "Sprinkling magic on every frame…",
      "Summoning the perfect cut…",
      "Adding the final sparkle…",
    ],
  },
  {
    key: "santa",
    label: "Santa loading clips",
    emoji: "🎅",
    motion: "animate-bob",
    accents: sparkles(
      { emoji: "🎁", className: "bottom-7 left-6 text-xl animate-bob" },
      {
        emoji: "❄️",
        className: "bottom-10 right-7 text-base animate-twinkle",
        style: { animationDelay: "0.8s" },
      },
    ),
    lines: [
      "Santa is stuffing your clips into the sleigh…",
      "Checking the edit list twice…",
      "Wrapping each scene with a little bow…",
      "Ho ho hold on — almost ready…",
    ],
  },
  {
    key: "coffee",
    label: "Brewing coffee",
    emoji: "☕",
    motion: "animate-bob",
    accents: [
      { emoji: "💨", className: "left-1/2 top-7 -translate-x-1/2 text-base animate-float-up" },
      {
        emoji: "💨",
        className: "left-[58%] top-8 text-sm animate-float-up",
        style: { animationDelay: "0.7s" },
      },
      { emoji: "✨", className: "right-6 bottom-9 text-base animate-twinkle" },
    ],
    lines: [
      "Brewing a fresh pot of frames…",
      "Letting the render steep…",
      "One espresso shot of cinema, coming up…",
      "Caffeinating the pixels…",
    ],
  },
  {
    key: "witch",
    label: "Witch on a broom",
    emoji: "🧙‍♀️",
    motion: "animate-drift-across",
    accents: sparkles(
      { emoji: "🌙", className: "right-6 top-6 text-lg animate-bob" },
      {
        emoji: "🧹",
        className: "bottom-9 left-7 text-base animate-twinkle",
        style: { animationDelay: "1.2s" },
      },
    ),
    lines: [
      "The witch is sweeping scenes into place…",
      "Stirring a bubbling cauldron of clips…",
      "Casting a spell on every transition…",
      "The broom is almost parked…",
    ],
  },
  {
    key: "penguin",
    label: "Waddling penguin",
    emoji: "🐧",
    motion: "animate-bounce",
    accents: sparkles(
      { emoji: "❄️", className: "right-6 bottom-8 text-base animate-twinkle" },
      {
        emoji: "🐟",
        className: "bottom-7 left-6 text-base animate-drift-across",
        style: { animationDelay: "0.6s" },
      },
    ),
    lines: [
      "A penguin is waddling your footage over…",
      "Sliding the scenes into order…",
      "Keeping your clips perfectly chill…",
      "Just waddling the last frame in…",
    ],
  },
  {
    key: "rocket",
    label: "Rocket launch",
    emoji: "🚀",
    motion: "animate-bob",
    accents: sparkles(
      { emoji: "🌟", className: "right-7 bottom-9 text-base animate-twinkle" },
      {
        emoji: "✨",
        className: "left-1/2 bottom-6 -translate-x-1/2 text-base animate-float-up",
        style: { animationDelay: "0.4s" },
      },
    ),
    lines: [
      "Launching your video into the stratosphere…",
      "Igniting the render boosters…",
      "3… 2… 1… almost liftoff…",
      "Houston, the edit is a go…",
    ],
  },
  {
    key: "snail",
    label: "Determined snail",
    emoji: "🐌",
    motion: "animate-drift-across",
    motionStyle: { animationDuration: "6s" },
    accents: sparkles({
      emoji: "🍃",
      className: "bottom-8 left-6 text-base animate-twinkle",
      style: { animationDelay: "0.9s" },
    }),
    lines: [
      "A very determined snail is delivering each frame…",
      "Slow and steady wins the render…",
      "Leaving a shiny trail of pixels…",
      "Worth the wait, promise…",
    ],
  },
  {
    key: "robot",
    label: "Assembly robot",
    emoji: "🤖",
    motion: "animate-bob",
    accents: sparkles(
      { emoji: "⚙️", className: "right-6 top-7 text-base animate-spin" },
      {
        emoji: "🔧",
        className: "bottom-8 left-7 text-base animate-twinkle",
        style: { animationDelay: "0.7s" },
      },
    ),
    lines: [
      "Robots are assembling the pixels… beep boop…",
      "Tightening every bolt on your edit…",
      "Running cinema.exe…",
      "Calculating maximum awesomeness…",
    ],
  },
  {
    key: "bee",
    label: "Busy bee",
    emoji: "🐝",
    motion: "animate-drift-across",
    motionStyle: { animationDuration: "2.6s" },
    accents: sparkles(
      { emoji: "🌸", className: "right-6 bottom-8 text-base animate-bob" },
      {
        emoji: "🌼",
        className: "bottom-9 left-7 text-base animate-twinkle",
        style: { animationDelay: "1s" },
      },
    ),
    lines: [
      "Busy bees are pollinating every scene…",
      "Buzzing between your best frames…",
      "Making your video extra sweet…",
      "The hive is almost finished…",
    ],
  },
  {
    key: "sloth",
    label: "Careful sloth",
    emoji: "🦥",
    motion: "animate-bob",
    motionStyle: { animationDuration: "4.5s" },
    accents: sparkles({
      emoji: "🌿",
      className: "bottom-8 right-7 text-base animate-twinkle",
      style: { animationDelay: "0.6s" },
    }),
    lines: [
      "A sloth is placing each frame… very… carefully…",
      "Hanging around your timeline…",
      "Taking it slow for the perfect cut…",
      "Almost… there… (worth it)…",
    ],
  },
  {
    key: "octopus",
    label: "Multitasking octopus",
    emoji: "🐙",
    motion: "animate-bob",
    accents: sparkles(
      { emoji: "🎬", className: "right-6 top-7 text-base animate-bob" },
      {
        emoji: "💧",
        className: "bottom-8 left-7 text-base animate-float-up",
        style: { animationDelay: "0.5s" },
      },
    ),
    lines: [
      "An octopus is editing eight clips at once…",
      "All tentacles on deck…",
      "Juggling your scenes effortlessly…",
      "Inking the final frame…",
    ],
  },
  {
    key: "chef",
    label: "Cinematic chef",
    emoji: "👨‍🍳",
    motion: "animate-bob",
    accents: sparkles(
      { emoji: "🍿", className: "bottom-7 left-6 text-lg animate-bob" },
      {
        emoji: "🔥",
        className: "bottom-9 right-7 text-base animate-twinkle",
        style: { animationDelay: "0.8s" },
      },
    ),
    lines: [
      "Our chef is plating something cinematic…",
      "Seasoning each scene to taste…",
      "A pinch of drama, a dash of sparkle…",
      "Chef's kiss incoming…",
    ],
  },
];

/** Pick a random scene (used per render so each job feels a little different). */
export function pickRenderScene(): RenderScene {
  return RENDER_SCENES[Math.floor(Math.random() * RENDER_SCENES.length)];
}

/** The square animated stage for a single scene (character + floating accents). */
export function RenderSceneStage({
  scene,
  className,
}: {
  scene: RenderScene;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "relative mx-auto grid aspect-square w-full max-w-[220px] place-items-center overflow-hidden rounded-2xl border border-hairline bg-gradient-to-br from-panel-raised to-canvas",
        className,
      )}
    >
      {scene.accents.map((accent, i) => (
        <span
          key={i}
          aria-hidden
          className={cn("absolute select-none leading-none", accent.className)}
          style={accent.style}
        >
          {accent.emoji}
        </span>
      ))}
      <span
        aria-hidden
        className={cn(
          "relative select-none text-6xl leading-none drop-shadow-[0_4px_12px_rgba(244,183,64,0.35)]",
          scene.motion,
        )}
        style={scene.motionStyle}
      >
        {scene.emoji}
      </span>
    </div>
  );
}
