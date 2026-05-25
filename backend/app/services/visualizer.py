"""
Visualizer service — converts DataFrames into Plotly figure specs (JSON).

Why this module exists:
  Raw tables are great for analysts, but charts answer questions faster:
    - "Which artist sells the most?" -> bar chart at a glance.
    - "How do sales evolve over time?" -> line chart at a glance.
  We return a Plotly figure as JSON ({data, layout}). The React frontend
  renders it with react-plotly.js, which handles responsiveness, resize
  observers, mount/unmount — none of which work with raw HTML embedding.

Why JSON spec instead of HTML:
  Our first version returned `fig.to_html(...)` and the frontend injected
  it via dangerouslySetInnerHTML. That FAILED because Plotly measures the
  container ONCE at script-eval time, when the chat bubble is still ~30px
  wide. The chart baked that width and never recovered. The JSON-spec +
  react-plotly.js approach uses ResizeObserver to redraw on layout change.

Strategy:
  - decide_chart_type(df): heuristics to auto-pick a chart based on shape.
  - render_chart(df, chart_type): build the figure, return as JSON dict.
  - parse_chart_request(message): detect when the user asks to switch
    the chart type explicitly (e.g. "show as pie chart"). Used by the
    agent's route_intent node to skip re-running SQL.

Why heuristics + keyword parsing instead of an LLM call:
  Free, instant, and deterministic. An LLM-based intent router would be
  more flexible (e.g. handle "make it nicer") but adds latency and cost.
  Easy upgrade path later if the simple version proves insufficient.
"""

import json
from typing import Literal

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import plotly.io as pio

# Allowed chart types. "auto" means "let the heuristic pick".
ChartType = Literal["auto", "bar", "line", "pie", "scatter", "table"]


# --- Auto-detect chart type from data shape --------------------------------

def decide_chart_type(df: pd.DataFrame) -> ChartType:
    """
    Pick the best chart type based on the DataFrame shape.

    Decision tree (in order):
      1. Empty -> "table" (nothing to chart, but show consistent placeholder).
      2. Single row -> "table" (one number does not need a chart).
      3. Any date/time column -> "line" (time series).
      4. 2 columns, 1 categorical + 1 numeric, <=20 rows -> "bar".
      5. 2 numeric columns -> "scatter".
      6. Anything else -> "table".

    Why "table" as the fallback: it always renders correctly. Charts only
    when we are CONFIDENT the shape fits — otherwise we would mislead users.
    """
    if df.empty:
        return "table"

    n_rows = len(df)
    n_cols = len(df.columns)

    # Single aggregated row (e.g. COUNT(*) result) — a table reads better.
    if n_rows == 1:
        return "table"

    # Time series: any column that looks like a date / time / year / month.
    for col in df.columns:
        col_lower = col.lower()
        if any(token in col_lower for token in ("date", "time", "year", "month")):
            return "line"
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return "line"

    # 2 columns: classic "category + metric" pattern -> bar chart.
    if n_cols == 2:
        cats = df.select_dtypes(include=["object", "string"]).columns
        nums = df.select_dtypes(include=["number"]).columns
        # 1 string col + 1 numeric col + reasonable count -> bar.
        if len(cats) == 1 and len(nums) == 1:
            return "bar" if n_rows <= 20 else "table"
        # 2 numeric columns -> relationship visualization (scatter).
        if len(nums) == 2:
            return "scatter"

    # Default for complex shapes: fall back to a clean table.
    return "table"


# --- Parse user intent (chart type request) --------------------------------

# Chart-type keywords in English AND Portuguese (the analyst persona may be PT).
# Why include both: same code base serves international recruiters and the
# Portuguese-speaking sales analyst from the PRD.
_CHART_KEYWORDS: dict[str, list[str]] = {
    "bar": ["bar chart", "bar graph", "barras", "grafico de barras", "gráfico de barras"],
    "pie": ["pie chart", "pie graph", "pizza", "donut", "rosca",
            "grafico de pizza", "gráfico de pizza"],
    "line": ["line chart", "line graph", "linha", "evolucao", "evolução",
             "time series", "serie temporal", "série temporal"],
    "scatter": ["scatter", "scatter plot", "dispersao", "dispersão"],
    "table": ["table", "tabela", "raw data", "dados crus"],
}

# Question words that strongly suggest a NEW query (not a chart-change request).
# If any of these appears in the message, we treat it as a fresh question.
# Note: Portuguese "como" is ambiguous — it can mean "how" (question) OR "as/like"
# (preposition, common in "mostre como pizza"). We omit it on purpose.
_QUESTION_WORDS = {
    "what", "which", "how", "where", "when", "who", "why",
    "qual", "quais", "onde", "quando", "quem", "porque", "por que",
    "quanto", "quantos", "quantas",
}

# Entity / topic words that suggest the user is asking about NEW data
# (a fresh query), even when a chart keyword is also present.
# E.g. "Top 10 albums as bar chart" mentions "top" and "albums" — clearly a
# new question with a chart preference, not a pure re-render of prior data.
_NEW_QUERY_INDICATORS = {
    # English
    "top", "list", "show me",
    "artist", "artists", "album", "albums", "genre", "genres",
    "sales", "customer", "customers", "track", "tracks",
    "country", "countries", "year", "years", "month", "months",
    # Portuguese
    "lista",
    "artista", "artistas", "album", "álbum", "albums", "álbuns", "albuns",
    "genero", "gênero", "generos", "gêneros",
    "venda", "vendas", "cliente", "clientes",
    "faixa", "faixas", "pais", "país", "paises", "países",
    "ano", "anos", "mes", "mês", "meses",
}


def parse_chart_request(message: str) -> ChartType | None:
    """
    Detect an explicit chart-type request in the user message.

    Returns the requested chart type, or None if the message does not
    contain any chart-type keyword.
    """
    msg = message.lower()
    for chart_type, keywords in _CHART_KEYWORDS.items():
        for kw in keywords:
            if kw in msg:
                return chart_type  # type: ignore[return-value]
    return None


def is_pure_chart_request(message: str) -> bool:
    """
    Heuristic: is this message ONLY a chart-style change (not a new question)?

    Returns True when the message is short, has no question words, and does
    not mention entity nouns (top, artist, album, etc.).

    Why this matters:
      "Top 5 artists as a bar chart" -> NEW question (has "top" + "artists").
      "Show as pie"                   -> PURE chart change (just style words).
      "Mostre como pizza"             -> PURE chart change (just style words).

    The route_intent node combines this with `has_previous_data` to decide:
      pure_chart_request + previous_data -> skip SQL, just re-render chart.
    """
    msg = message.lower().strip()
    tokens = msg.split()

    # Very long messages almost always carry a new question alongside the style.
    if len(tokens) > 6:
        return False

    # Question words (what / which / how / qual ...) signal a fresh query.
    if any(w in tokens for w in _QUESTION_WORDS):
        return False

    # Entity words (top / artist / album / sales ...) signal new data is wanted.
    # We do a substring check so plurals (artists / artistas) match too.
    if any(indicator in msg for indicator in _NEW_QUERY_INDICATORS):
        return False

    return True


# --- Render charts to Plotly JSON spec --------------------------------------

def render_chart(df: pd.DataFrame, chart_type: ChartType = "auto") -> dict:
    """
    Render a DataFrame as a Plotly figure spec (JSON-serializable dict).

    Returns: {"data": [...traces...], "layout": {...}}  — same shape that
    react-plotly.js's <Plot data={...} layout={...} /> expects.

    Why a dict instead of HTML: the React frontend mounts react-plotly.js
    with useResizeHandler — Plotly recovers from wrong initial width via
    ResizeObserver. HTML embedding cannot do that.
    """
    if df.empty:
        return _empty_spec()

    if chart_type == "auto":
        chart_type = decide_chart_type(df)

    # Dispatch table — easier to read than a chain of if/elif.
    renderers = {
        "bar": _render_bar,
        "line": _render_line,
        "pie": _render_pie,
        "scatter": _render_scatter,
        "table": _render_table,
    }
    renderer = renderers.get(chart_type, _render_table)
    fig = renderer(df)
    return _fig_to_spec(fig)


# --- Internal renderers (one per chart type) -------------------------------

def _render_bar(df: pd.DataFrame) -> go.Figure:
    """
    Bar chart: first column = x (categories), first numeric = y, optional grouping.

    Handles 2 and 3+ column shapes:
      (x, y)            -> simple bar
      (x, group, y)     -> grouped bars (one color per group)
    """
    x, y, color = _pick_xy_color(df)
    if y is None:
        return _render_table(df)
    return px.bar(df, x=x, y=y, color=color)


def _render_line(df: pd.DataFrame) -> go.Figure:
    """
    Line chart: first column = x (time), first numeric = y, optional grouping.

    Why we no longer pass cols[1:] as wide-form y:
      For 3+ columns with mixed types (e.g. Month, Artist, Sales), Plotly
      Express rejects wide-form and raises ValueError. Long-form via the
      `color` parameter is robust and looks better (one line per group).
    """
    x, y, color = _pick_xy_color(df)
    if y is None:
        return _render_table(df)
    return px.line(df, x=x, y=y, color=color)


# When a grouped chart (bar/line with color) would have more than this many
# distinct groups, we refuse to draw it and fall back to a table. Beyond ~8
# colors the chart legend takes more room than the data, the lines criss-
# cross into noise, and the chart actively HURTS comprehension.
_MAX_CHART_GROUPS = 8


def _pick_xy_color(df: pd.DataFrame) -> tuple[str | None, str | None, str | None]:
    """
    Decide which column to use as x, y, and (optional) color for a chart.

    Returns (x, y, color). When y is None the caller falls back to a table —
    we use that to signal "this data should not be charted":

      - fewer than 2 columns (nothing to plot)
      - no numeric column (cannot plot quantities)
      - too many distinct groups for the color dimension (>_MAX_CHART_GROUPS)

    Why this exists: shared between bar and line so we never accidentally
    feed Plotly a wide-form DataFrame with mixed types AND so we have one
    place to enforce "do not draw a chart when it would be unreadable".
    """
    cols = list(df.columns)
    if len(cols) < 2:
        return None, None, None

    x = cols[0]
    nums = df.select_dtypes(include=["number"]).columns.tolist()

    # Pick the first numeric column that is not the x column.
    y_candidates = [c for c in nums if c != x]
    if not y_candidates:
        return x, None, None
    y = y_candidates[0]

    # Whatever is left (not x, not y) becomes the grouping color column.
    # Only used when there are 3+ columns — otherwise color stays None.
    remaining = [c for c in cols if c != x and c != y]
    color = remaining[0] if remaining else None

    # Bail out if the grouping would create too many lines/bars. The user
    # gets a clean table instead — far more readable than 50 overlapping lines.
    if color is not None and df[color].nunique() > _MAX_CHART_GROUPS:
        return None, None, None

    return x, y, color


def _render_pie(df: pd.DataFrame) -> go.Figure:
    """Pie chart: first column = labels, second column = values."""
    cols = list(df.columns)
    if len(cols) < 2:
        return _render_table(df)
    return px.pie(df, names=cols[0], values=cols[1])


def _render_scatter(df: pd.DataFrame) -> go.Figure:
    """Scatter plot: first column = x, second column = y."""
    cols = list(df.columns)
    if len(cols) < 2:
        return _render_table(df)
    return px.scatter(df, x=cols[0], y=cols[1])


def _render_table(df: pd.DataFrame) -> go.Figure:
    """Plotly table — clean default when no chart type fits the data."""
    fig = go.Figure(data=[go.Table(
        header=dict(
            values=list(df.columns),
            fill_color="paleturquoise",
            align="left",
        ),
        cells=dict(
            values=[df[c] for c in df.columns],
            fill_color="lavender",
            align="left",
        ),
    )])
    # Trim margins so the table fits neatly inside the chat UI.
    fig.update_layout(margin=dict(l=0, r=0, t=20, b=0))
    return fig


def _empty_spec() -> dict:
    """Spec rendered when the query returns no rows — empty figure, clean message."""
    return {
        "data": [],
        "layout": {
            "title": "No data to display",
            "xaxis": {"visible": False},
            "yaxis": {"visible": False},
            "annotations": [{
                "text": "No data",
                "showarrow": False,
                "font": {"size": 16, "color": "#888"},
            }],
        },
    }


def _fig_to_spec(fig: go.Figure) -> dict:
    """
    Serialize a Plotly Figure to a JSON-friendly dict.

    Why pio.to_json (instead of fig.to_dict()):
      to_dict() returns numpy arrays for trace data — FastAPI cannot JSON-
      encode those out of the box. pio.to_json applies Plotly's own encoder
      which handles numpy / pandas / datetime correctly, and we parse it
      back to a plain dict so FastAPI's serializer takes over from there.
    """
    return json.loads(pio.to_json(fig))
