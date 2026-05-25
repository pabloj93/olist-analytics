/**
 * PlotlyChart — renders a Plotly figure spec via react-plotly.js.
 *
 * Why react-plotly.js (and not raw dangerouslySetInnerHTML):
 *   Plotly's HTML export measures the container exactly once when the
 *   embedded <script> runs. In a chat UI the bubble is still animating
 *   in (~30px wide) at that moment — Plotly bakes that width and never
 *   recovers. react-plotly.js attaches a ResizeObserver and calls
 *   Plotly.Plots.resize() whenever the wrapper resizes, so the chart
 *   self-corrects to its real width.
 *
 * The four settings below combine to fix the wrong-first-paint problem:
 *   1. layout.autosize = true       — let Plotly derive size from the DOM node
 *   2. config.responsive = true     — install a window-resize listener
 *   3. useResizeHandler prop        — attach a ResizeObserver to the wrapper
 *   4. style width:100% / height:px — fluid width, fixed height (avoids the
 *                                     "0px tall flexbox child" trap)
 */

import Plot from "react-plotly.js";


interface PlotlyChartProps {
  /**
   * Plotly figure spec from the backend: {data: [...], layout: {...}}.
   * Empty object means "no chart" — the parent should not render us at all.
   */
  spec: {
    data?: unknown[];
    layout?: Record<string, unknown>;
    config?: Record<string, unknown>;
  };
}


export function PlotlyChart({ spec }: PlotlyChartProps) {
  // Guard: empty spec from the backend (e.g. zero-row result) — render nothing.
  if (!spec || !spec.data || spec.data.length === 0) return null;

  return (
    <Plot
      // The exact arrays Plotly produced server-side.
      data={spec.data as Plotly.Data[]}
      // Spread server-side layout last so backend can override our defaults.
      layout={{
        autosize: true,
        margin: { t: 24, r: 16, b: 40, l: 48 },
        ...(spec.layout ?? {}),
      }}
      // Disable the "Made with Plotly" logo — keeps the UI clean.
      // responsive=true installs a window resize listener inside Plotly.
      config={{
        displaylogo: false,
        responsive: true,
        ...(spec.config ?? {}),
      }}
      // Fluid width + fixed height. Without an explicit height, flex children
      // collapse to 0px and the chart never renders.
      style={{ width: "100%", height: "420px" }}
      // ResizeObserver — the prop that actually fixes the wrong-initial-width bug.
      useResizeHandler
    />
  );
}
