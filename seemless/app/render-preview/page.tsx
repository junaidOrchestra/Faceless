"use client";

import * as React from "react";
import { RENDER_SCENES, RenderSceneStage, type RenderScene } from "@/components/render-scenes";

/**
 * TEMP test page — visual check for the render-loading scenes.
 *
 * Visit /render-preview to see every scene animating at once with its funny
 * status lines cycling. This page is for development/QA only and can be deleted
 * once the scenes are approved.
 */

function SceneCard({ scene }: { scene: RenderScene }) {
  const [line, setLine] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setLine((s) => (s + 1) % scene.lines.length), 2800);
    return () => clearInterval(t);
  }, [scene.lines.length]);

  return (
    <div className="panel flex flex-col gap-4 p-5">
      <div className="flex items-center justify-between">
        <h2 className="font-heading text-base font-bold text-cream">{scene.label}</h2>
        <span className="rounded-full bg-panel-raised px-2 py-0.5 font-mono text-[10px] text-faint">
          {scene.key}
        </span>
      </div>

      <RenderSceneStage scene={scene} />

      <p
        key={line}
        className="min-h-[2.75rem] animate-fade-in text-center font-heading text-base font-bold leading-tight text-cream"
      >
        {scene.lines[line]}
      </p>

      <ul className="space-y-1 border-t border-hairline pt-3 text-xs text-faint">
        {scene.lines.map((l, i) => (
          <li key={i} className={i === line ? "text-accent" : undefined}>
            • {l}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function RenderPreviewPage() {
  return (
    <main className="min-h-screen bg-canvas px-6 py-10 text-cream">
      <div className="mx-auto max-w-6xl">
        <header className="mb-8">
          <h1 className="font-heading text-2xl font-bold text-cream">
            Render scenes preview
          </h1>
          <p className="mt-1 text-sm text-faint">
            {RENDER_SCENES.length} whimsical loading scenes shown during rendering. One is
            picked at random per render. (Temporary QA page — safe to delete.)
          </p>
        </header>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {RENDER_SCENES.map((scene) => (
            <SceneCard key={scene.key} scene={scene} />
          ))}
        </div>
      </div>
    </main>
  );
}
