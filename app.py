from __future__ import annotations

from datetime import datetime, timezone
from io import BytesIO
from typing import Any
import re

import pandas as pd
import streamlit as st
from supabase import create_client
from postgrest.exceptions import APIError


st.set_page_config(
    page_title="Meaning Preservation Annotation",
    page_icon="📝",
    layout="wide",
)

LABELS = ["YES", "NO", "MAYBE"]

STEP_DEFINITIONS: list[dict[str, Any]] = [
    {
        "number": 1,
        "title": "Can the original post be understood?",
        "quick": "Decide whether the original post gives enough information to understand the general topic and what is being discussed.",
        "guidance": """
The meaning may be unclear if the post depends on missing context, such as a previous comment, an unclear reference, or something outside the text.
""",
        "options": [
            {
                "label": "No: the original meaning cannot be judged confidently",
                "outcome": "MAYBE",
                "reason": "Context unclear",
            },
            {
                "label": "Yes: the original is understandable enough",
                "outcome": "CONTINUE",
                "reason": "Original understandable",
            },
        ],
    },
    {
        "number": 2,
        "title": "Is the core meaning preserved?",
        "quick": "Check whether the simplified version keeps the same main message, event, topic, outcome, claim, people involved and relationships.",
        "guidance": """
Also check that important details such as negation, time, cause or condition have not changed.

Example 1:

Original: “The council rejected our application.”  
Simplified: “The council is considering our application.”

The outcome has changed. This is **NO: Core meaning changed**.

Example 2:

Original: “They blamed me for the mistake.”  
Simplified: “I made the mistake.”

The meaning changes from an accusation to an admission. This is **NO: Core meaning changed**.
""",
        "options": [
            {
                "label": "No: the main message, event, participant or outcome has changed",
                "outcome": "NO",
                "reason": "Core meaning changed",
            },
            {
                "label": "Maybe: the core meaning may have changed, but I am not sure",
                "outcome": "MAYBE",
                "reason": "Core meaning unclear",
            },
            {
                "label": "Yes: the core meaning is preserved",
                "outcome": "CONTINUE",
                "reason": "Core meaning preserved",
            },
        ],
    },
    {
        "number": 3,
        "title": "Are emotion, polarity and intensity preserved?",
        "quick": "Check whether the simplified version keeps the same emotional meaning and strength.",
        "guidance": """
For example, anger should not become neutral, criticism should not become praise, and strong emotion should not become much weaker or stronger.

Example:

Original: “I am absolutely furious about this.”  
Simplified: “I’m okay with this.”

The emotion and intensity have changed. This is **NO: Emotion or polarity changed**.
""",
        "options": [
            {
                "label": "No: emotion, polarity or intensity clearly changes the meaning",
                "outcome": "NO",
                "reason": "Emotion or polarity changed",
            },
            {
                "label": "Maybe: there may be a small emotional change",
                "outcome": "MAYBE",
                "reason": "Emotional shift unclear",
            },
            {
                "label": "Yes: the emotional meaning is preserved",
                "outcome": "CONTINUE",
                "reason": "Emotion preserved",
            },
        ],
    },
    {
        "number": 4,
        "title": "Is non-literal or informal meaning preserved?",
        "quick": "Check whether sarcasm, irony, humour, idioms, metaphors, exaggeration, slang, abbreviations, profanity or informal language are handled correctly.",
        "guidance": """
The simplified version may explain these meanings directly, but the explanation must match the original meaning.

Example 1:

Original: “Fantastic. Another cancelled train.”  
Simplified: “The writer is happy that another train was cancelled.”

The sarcasm has been misunderstood. This is **NO: Non-literal meaning lost**.

Example 2:

Original: “Fuck my life.”  
Simplified: “I am a little upset.”

The strong frustration has been weakened too much. This is **MAYBE: Informal meaning or intensity changed** if the main message is still partly preserved, or **NO** if the intensity is central to the meaning.
""",
        "options": [
            {
                "label": "No: sarcasm, humour, slang, profanity or figurative meaning is misunderstood or omitted",
                "outcome": "NO",
                "reason": "Non-literal or informal meaning lost",
            },
            {
                "label": "Maybe: some tone or humour may be lost, but the main message may still be preserved",
                "outcome": "MAYBE",
                "reason": "Tone or humour partly lost",
            },
            {
                "label": "Yes: the intended meaning is preserved or accurately explained",
                "outcome": "CONTINUE",
                "reason": "Non-literal or informal meaning preserved",
            },
        ],
    },
    {
        "number": 5,
        "title": "Are emojis, hashtags and social media cues handled accurately?",
        "quick": "Check whether emojis, hashtags, @mentions or links affect emotion, sarcasm, emphasis, topic, identity, humour or attitude.",
        "guidance": """
Example 1:

Original: “Great 🙄”  
Simplified: “That is great.”

The eye-roll emoji showed sarcasm, so the meaning has changed. This is **NO: Social media meaning changed**.

Example 2:

Original: “I passed! 🎉”  
Simplified: “I passed! I am celebrating.”

The emoji meaning is explained clearly. This is acceptable.
""",
        "options": [
            {
                "label": "No: an emoji, hashtag or social media cue changes the meaning",
                "outcome": "NO",
                "reason": "Social media meaning changed",
            },
            {
                "label": "Maybe: the effect of the cue is unclear",
                "outcome": "MAYBE",
                "reason": "Social media cue unclear",
            },
            {
                "label": "Yes: the cue is preserved, safely removed or clearly explained",
                "outcome": "CONTINUE",
                "reason": "Social media cues preserved",
            },
        ],
    },
    {
        "number": 6,
        "title": "Has important information been removed or unsupported information added?",
        "quick": "Check whether important meaning was removed, or whether the simplified version adds new meaning not present in the original.",
        "guidance": """
A simplification may remove repetition or filler. It may also add a short explanation if the meaning is already clear. However, it should not remove important information or add unsupported meaning.

Example 1:

Original: “I did not agree to attend tomorrow.”  
Simplified: “I agreed to attend.”

Important meaning has been lost. This is **NO: Material omission or unsupported addition**.

Example 2:

Original: “She did not reply.”  
Simplified: “She ignored me because she does not care.”

The simplified version adds an unsupported motive. This is **NO: Material omission or unsupported addition**.
""",
        "options": [
            {
                "label": "Yes: important information is removed or unsupported meaning is added",
                "outcome": "NO",
                "reason": "Material omission or unsupported addition",
            },
            {
                "label": "Maybe: the effect of the change is unclear",
                "outcome": "MAYBE",
                "reason": "Information change unclear",
            },
            {
                "label": "No: only non-essential details are removed and additions are clearly supported",
                "outcome": "YES",
                "reason": "Meaning preserved",
            },
        ],
    },
]


# -----------------------------
# Supabase helpers
# -----------------------------

@st.cache_resource
def get_supabase_client():
    try:
        url = st.secrets["SUPABASE_URL"]
        key = st.secrets["SUPABASE_KEY"]
    except Exception:
        st.error(
            "Supabase secrets are missing. Add SUPABASE_URL and SUPABASE_KEY "
            "in Streamlit Community Cloud → Manage app → Settings → Secrets."
        )
        st.stop()
    return create_client(url, key)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def safe_execute(query_builder, friendly_error: str):
    try:
        return query_builder.execute()
    except APIError as exc:
        st.error(friendly_error)
        with st.expander("Technical details"):
            st.code(str(exc))
        st.stop()
    except Exception as exc:
        st.error(friendly_error)
        with st.expander("Technical details"):
            st.code(str(exc))
        st.stop()


@st.cache_data(ttl=20)
def load_posts() -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = safe_execute(
        client.table("posts").select("*").order("display_order"),
        "The app could not read the posts table in Supabase. Check that the tables exist and that Streamlit secrets use the correct Supabase project.",
    )
    return response.data or []


def load_all_progress() -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = safe_execute(
        client.table("annotation_progress").select("*"),
        "The app could not read annotation progress from Supabase.",
    )
    return response.data or []


def load_progress(email: str) -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = safe_execute(
        client.table("annotation_progress").select("*").eq("annotator_id", email),
        "The app could not read your saved progress from Supabase.",
    )
    return response.data or []


def load_step_answers(email: str, post_id: str) -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = safe_execute(
        client.table("step_answers")
        .select("*")
        .eq("annotator_id", email)
        .eq("post_id", post_id)
        .order("step_number"),
        "The app could not read saved step answers from Supabase.",
    )
    return response.data or []


def save_step_answer(email: str, post_id: str, step_number: int, decision: str, reason: str, comment: str) -> None:
    client = get_supabase_client()
    safe_execute(
        client.table("step_answers").upsert(
            {
                "annotator_id": email,
                "post_id": post_id,
                "step_number": step_number,
                "decision": decision,
                "reason": reason,
                "comment": comment,
                "updated_at": utc_now(),
            },
            on_conflict="annotator_id,post_id,step_number",
        ),
        "The app could not save this step answer. Check Supabase permissions.",
    )


def save_progress(
    email: str,
    post_id: str,
    current_step: int,
    completed: bool,
    final_label: str | None = None,
    terminal_reason: str | None = None,
    terminal_step: int | None = None,
    comment: str | None = None,
) -> None:
    client = get_supabase_client()
    safe_execute(
        client.table("annotation_progress").upsert(
            {
                "annotator_id": email,
                "post_id": post_id,
                "current_step": current_step,
                "completed": completed,
                "final_label": final_label,
                "terminal_reason": terminal_reason,
                "terminal_step": terminal_step,
                "comment": comment or "",
                "updated_at": utc_now(),
            },
            on_conflict="annotator_id,post_id",
        ),
        "The app could not save progress. Check Supabase permissions.",
    )


def reset_one_annotation(email: str, post_id: str) -> None:
    client = get_supabase_client()
    safe_execute(
        client.table("step_answers").delete().eq("annotator_id", email).eq("post_id", post_id),
        "The app could not delete step answers for this post.",
    )
    safe_execute(
        client.table("annotation_progress").delete().eq("annotator_id", email).eq("post_id", post_id),
        "The app could not delete progress for this post.",
    )
    st.cache_data.clear()


def delete_annotator_results(email: str) -> None:
    client = get_supabase_client()
    safe_execute(
        client.table("step_answers").delete().eq("annotator_id", email),
        "The app could not delete this annotator's step answers.",
    )
    safe_execute(
        client.table("annotation_progress").delete().eq("annotator_id", email),
        "The app could not delete this annotator's progress.",
    )
    st.cache_data.clear()


def clear_all_posts_and_annotations() -> None:
    client = get_supabase_client()
    safe_execute(client.table("step_answers").delete().neq("id", -1), "Could not clear step answers.")
    safe_execute(client.table("annotation_progress").delete().neq("id", -1), "Could not clear annotation progress.")
    safe_execute(client.table("posts").delete().neq("post_id", "__never__"), "Could not clear posts.")
    st.cache_data.clear()


def delete_one_post(post_id: str) -> None:
    client = get_supabase_client()
    safe_execute(
        client.table("step_answers").delete().eq("post_id", post_id),
        "The app could not delete step answers for this post.",
    )
    safe_execute(
        client.table("annotation_progress").delete().eq("post_id", post_id),
        "The app could not delete annotation progress for this post.",
    )
    safe_execute(
        client.table("posts").delete().eq("post_id", post_id),
        "The app could not delete this post.",
    )
    st.cache_data.clear()


# -----------------------------
# Data import and export
# -----------------------------


def read_uploaded_dataset(uploaded_file) -> pd.DataFrame:
    if uploaded_file.name.lower().endswith(".csv"):
        return pd.read_csv(uploaded_file)
    return pd.read_excel(uploaded_file)


def guess_column(df: pd.DataFrame, candidates: list[str]) -> str:
    normalised = {str(col).strip().lower().replace(" ", "_"): col for col in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower().replace(" ", "_")
        if key in normalised:
            return normalised[key]
    return df.columns[0]


def import_posts_to_supabase(df: pd.DataFrame, id_col: str | None, original_col: str, simplified_col: str, replace_existing: bool) -> int:
    if replace_existing:
        clear_all_posts_and_annotations()

    client = get_supabase_client()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in df.iterrows():
        if id_col:
            raw_id = row[id_col]
            post_id = str(raw_id).strip()
        else:
            post_id = str(index + 1)

        if not post_id or post_id.lower() == "nan":
            post_id = str(index + 1)

        if post_id in seen:
            post_id = f"{post_id}_{index + 1}"
        seen.add(post_id)

        original = "" if pd.isna(row[original_col]) else str(row[original_col])
        simplified = "" if pd.isna(row[simplified_col]) else str(row[simplified_col])
        if original.strip() and simplified.strip():
            records.append(
                {
                    "post_id": post_id,
                    "display_order": int(index + 1),
                    "original_post": original,
                    "simplified_post": simplified,
                    "updated_at": utc_now(),
                }
            )

    if not records:
        return 0

    for start in range(0, len(records), 500):
        safe_execute(
            client.table("posts").upsert(records[start : start + 500], on_conflict="post_id"),
            "The app could not import posts into Supabase. Check table permissions.",
        )

    load_posts.clear()
    return len(records)


def make_label_summary(progress_df: pd.DataFrame) -> pd.DataFrame:
    completed = progress_df[progress_df["completed"].eq(True)] if not progress_df.empty else pd.DataFrame()
    counts = completed["final_label"].value_counts().reindex(LABELS, fill_value=0) if not completed.empty else pd.Series([0, 0, 0], index=LABELS)
    total = int(counts.sum())
    return pd.DataFrame(
        {
            "Final label": LABELS,
            "Number": [int(counts[label]) for label in LABELS],
            "Percentage": [round((int(counts[label]) / total * 100), 1) if total else 0 for label in LABELS],
        }
    )


def make_by_annotator_summary(progress_df: pd.DataFrame) -> pd.DataFrame:
    if progress_df.empty:
        return pd.DataFrame(columns=["Annotator email", "YES", "NO", "MAYBE", "Total completed", "Total started"])

    completed = progress_df[progress_df["completed"].eq(True)]
    if completed.empty:
        started = progress_df.groupby("annotator_id")["post_id"].count().reset_index(name="Total started")
        started = started.rename(columns={"annotator_id": "Annotator email"})
        for label in LABELS:
            started[label] = 0
        started["Total completed"] = 0
        return started[["Annotator email", "YES", "NO", "MAYBE", "Total completed", "Total started"]]

    pivot = completed.pivot_table(
        index="annotator_id",
        columns="final_label",
        values="post_id",
        aggfunc="count",
        fill_value=0,
    ).reset_index()
    for label in LABELS:
        if label not in pivot.columns:
            pivot[label] = 0
    started = progress_df.groupby("annotator_id")["post_id"].count().reset_index(name="Total started")
    out = pivot.merge(started, on="annotator_id", how="left")
    out["Total completed"] = out[LABELS].sum(axis=1)
    out = out.rename(columns={"annotator_id": "Annotator email"})
    return out[["Annotator email", "YES", "NO", "MAYBE", "Total completed", "Total started"]].sort_values("Annotator email")


def make_post_agreement_summary(progress_df: pd.DataFrame, posts_df: pd.DataFrame) -> pd.DataFrame:
    """Show, for each post, how many annotators selected YES, NO or MAYBE."""
    columns = [
        "Post number",
        "Post ID",
        "YES",
        "NO",
        "MAYBE",
        "Total annotations",
        "Majority label",
        "Agreement %",
    ]

    if posts_df.empty:
        return pd.DataFrame(columns=columns)

    base = posts_df.copy()
    if "display_order" not in base.columns:
        base["display_order"] = range(1, len(base) + 1)
    base = base[["display_order", "post_id"]].rename(
        columns={"display_order": "Post number", "post_id": "Post ID"}
    )

    if progress_df.empty:
        for label in LABELS:
            base[label] = 0
        base["Total annotations"] = 0
        base["Majority label"] = "No annotations yet"
        base["Agreement %"] = 0.0
        return base[columns]

    completed = progress_df[progress_df["completed"].eq(True)].copy()
    if completed.empty:
        for label in LABELS:
            base[label] = 0
        base["Total annotations"] = 0
        base["Majority label"] = "No annotations yet"
        base["Agreement %"] = 0.0
        return base[columns]

    pivot = completed.pivot_table(
        index="post_id",
        columns="final_label",
        values="annotator_id",
        aggfunc="count",
        fill_value=0,
    ).reset_index()
    for label in LABELS:
        if label not in pivot.columns:
            pivot[label] = 0

    out = base.merge(pivot[["post_id", *LABELS]], how="left", left_on="Post ID", right_on="post_id")
    out = out.drop(columns=["post_id"], errors="ignore")
    for label in LABELS:
        out[label] = out[label].fillna(0).astype(int)

    out["Total annotations"] = out[LABELS].sum(axis=1).astype(int)

    def majority_label(row: pd.Series) -> str:
        total = int(row["Total annotations"])
        if total == 0:
            return "No annotations yet"
        counts = {label: int(row[label]) for label in LABELS}
        max_count = max(counts.values())
        winners = [label for label, count in counts.items() if count == max_count]
        if len(winners) > 1:
            return "No majority"
        return winners[0]

    def agreement_percent(row: pd.Series) -> float:
        total = int(row["Total annotations"])
        if total == 0:
            return 0.0
        return round(max(int(row[label]) for label in LABELS) / total * 100, 1)

    out["Majority label"] = out.apply(majority_label, axis=1)
    out["Agreement %"] = out.apply(agreement_percent, axis=1)
    return out[columns].sort_values("Post number")


def make_agreement_overview(agreement_by_post: pd.DataFrame) -> pd.DataFrame:
    """Create a compact visual overview of inter-annotator agreement."""
    columns = ["Agreement category", "Number of posts", "Percentage"]
    if agreement_by_post.empty:
        return pd.DataFrame(columns=columns)

    df = agreement_by_post.copy()
    total_posts = len(df)

    not_enough = df["Total annotations"].lt(2).sum()
    annotated = df["Total annotations"].ge(2)
    full = (annotated & df["Agreement %"].eq(100.0)).sum()
    no_majority = (annotated & df["Majority label"].eq("No majority")).sum()
    majority = (annotated & df["Agreement %"].lt(100.0) & ~df["Majority label"].eq("No majority")).sum()

    rows = [
        ("Full agreement", int(full)),
        ("Majority agreement", int(majority)),
        ("No majority", int(no_majority)),
        ("Not enough annotations yet", int(not_enough)),
    ]
    return pd.DataFrame(
        {
            "Agreement category": [r[0] for r in rows],
            "Number of posts": [r[1] for r in rows],
            "Percentage": [round((r[1] / total_posts * 100), 1) if total_posts else 0 for r in rows],
        }
    )


def build_export() -> bytes:
    client = get_supabase_client()
    posts = pd.DataFrame(safe_execute(client.table("posts").select("*").order("display_order"), "Could not export posts.").data or [])
    progress = pd.DataFrame(safe_execute(client.table("annotation_progress").select("*"), "Could not export progress.").data or [])
    steps = pd.DataFrame(safe_execute(client.table("step_answers").select("*"), "Could not export step answers.").data or [])

    if posts.empty:
        posts = pd.DataFrame(columns=["post_id", "display_order", "original_post", "simplified_post"])
    if progress.empty:
        progress = pd.DataFrame(columns=["annotator_id", "post_id", "current_step", "completed", "final_label", "terminal_reason", "terminal_step", "comment", "updated_at"])
    if steps.empty:
        steps = pd.DataFrame(columns=["annotator_id", "post_id", "step_number", "decision", "reason", "comment", "updated_at"])

    rows = progress.merge(posts, how="left", on="post_id", suffixes=("", "_post"))
    rows = rows.rename(columns={"annotator_id": "annotator_email"})

    if not steps.empty:
        pivot_decisions = steps.pivot_table(index=["annotator_id", "post_id"], columns="step_number", values="decision", aggfunc="last")
        pivot_decisions.columns = [f"step_{int(c)}_decision" for c in pivot_decisions.columns]
        pivot_decisions = pivot_decisions.reset_index().rename(columns={"annotator_id": "annotator_email"})

        pivot_reasons = steps.pivot_table(index=["annotator_id", "post_id"], columns="step_number", values="reason", aggfunc="last")
        pivot_reasons.columns = [f"step_{int(c)}_reason" for c in pivot_reasons.columns]
        pivot_reasons = pivot_reasons.reset_index().rename(columns={"annotator_id": "annotator_email"})

        rows = rows.merge(pivot_decisions, how="left", on=["annotator_email", "post_id"])
        rows = rows.merge(pivot_reasons, how="left", on=["annotator_email", "post_id"])

    agreement_by_post = make_post_agreement_summary(progress, posts)
    agreement_overview = make_agreement_overview(agreement_by_post)
    by_annotator = make_by_annotator_summary(progress)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        rows.to_excel(writer, sheet_name="Annotations", index=False)
        steps.rename(columns={"annotator_id": "annotator_email"}).to_excel(writer, sheet_name="Step answers", index=False)
        agreement_overview.to_excel(writer, sheet_name="Agreement overview", index=False)
        agreement_by_post.to_excel(writer, sheet_name="Agreement by post", index=False)
        by_annotator.to_excel(writer, sheet_name="By annotator", index=False)

        workbook = writer.book
        header = workbook.add_format({"bold": True, "bg_color": "#2F5597", "font_color": "white", "border": 1, "text_wrap": True})
        wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
        pct = workbook.add_format({"num_format": '0.0"%"'})

        for sheet_name in writer.sheets:
            ws = writer.sheets[sheet_name]
            if sheet_name == "Annotations":
                data = rows
            elif sheet_name == "Step answers":
                data = steps
            elif sheet_name == "Agreement overview":
                data = agreement_overview
            elif sheet_name == "Agreement by post":
                data = agreement_by_post
            else:
                data = by_annotator
            for col_num, value in enumerate(data.columns):
                ws.write(0, col_num, value, header)
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, max(len(data), 1), max(len(data.columns) - 1, 0))
            ws.set_column(0, max(len(data.columns) - 1, 0), 24, wrap)


    return output.getvalue()


# -----------------------------
# UI helpers
# -----------------------------


def normalise_email(email: str) -> str:
    return email.strip().lower()


def is_valid_email(email: str) -> bool:
    return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email.strip()))


def render_post_box(title: str, text: str):
    st.subheader(title)
    safe_text = str(text).replace("<", "&lt;").replace(">", "&gt;")
    st.markdown(
        f"""
<div style="
    border: 1px solid #B8C4D8;
    border-radius: 10px;
    padding: 18px;
    min-height: 160px;
    background: #F7F9FC;
    font-size: 1.08rem;
    white-space: pre-wrap;
">{safe_text}</div>
""",
        unsafe_allow_html=True,
    )


def post_status(post_id: str, progress_by_post: dict[str, dict[str, Any]]) -> str:
    p = progress_by_post.get(post_id)
    if not p:
        return "Not started"
    if p.get("completed"):
        return str(p.get("final_label") or "Completed")
    return f"In progress — Step {p.get('current_step', 1)}"


def get_progress_by_post(progress: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {p["post_id"]: p for p in progress}


def find_next_unfinished_index(posts: list[dict[str, Any]], progress_by_post: dict[str, dict[str, Any]], start: int = 0) -> int:
    if not posts:
        return 0
    n = len(posts)
    for offset in range(n):
        idx = (start + offset) % n
        p = progress_by_post.get(posts[idx]["post_id"])
        if not p or not p.get("completed"):
            return idx
    return min(start, n - 1)


def set_current_post_index(index: int, total_posts: int) -> None:
    """Move to a specific post index and keep it within the available range."""
    if total_posts <= 0:
        st.session_state["current_post_index"] = 0
    else:
        st.session_state["current_post_index"] = max(0, min(int(index), total_posts - 1))


def render_post_navigation(
    idx: int,
    total_posts: int,
    posts: list[dict[str, Any]],
    progress_by_post: dict[str, dict[str, Any]],
    email: str,
    prefix: str,
) -> None:
    """Render bottom navigation buttons for moving between posts."""
    current_post_id = posts[idx]["post_id"] if posts else ""
    left, right = st.columns(2)
    with left:
        st.button(
            "← Previous post",
            disabled=idx <= 0,
            use_container_width=True,
            key=f"{prefix}_previous_{email}_{current_post_id}_{idx}",
            on_click=set_current_post_index,
            args=(idx - 1, total_posts),
        )
    with right:
        st.button(
            "Next post →",
            disabled=idx >= total_posts - 1,
            use_container_width=True,
            key=f"{prefix}_next_{email}_{current_post_id}_{idx}",
            on_click=set_current_post_index,
            args=(idx + 1, total_posts),
        )


def annotator_page():
    st.title("Meaning Preservation Annotation")
    st.write("Enter your email address. Your progress is saved automatically after every decision.")

    posts = load_posts()
    if not posts:
        st.warning("No posts have been uploaded yet. Ask the researcher to add posts in the Researcher admin page.")
        return

    email_input = st.text_input("Enter your email address", placeholder="name@example.com")
    email = normalise_email(email_input)
    if not email:
        st.info("Enter your email address to begin or resume.")
        return
    if not is_valid_email(email):
        st.warning("Please enter a valid email address.")
        return

    session_email_key = "active_annotator_email"
    if st.session_state.get(session_email_key) != email:
        st.session_state[session_email_key] = email
        st.session_state.pop("current_post_index", None)

    progress = load_progress(email)
    progress_by_post = get_progress_by_post(progress)
    completed_count = sum(1 for p in progress if p.get("completed"))
    total_posts = len(posts)

    st.progress(completed_count / total_posts if total_posts else 0)
    st.caption(f"{completed_count} of {total_posts} posts completed for {email}.")


    if "current_post_index" not in st.session_state:
        st.session_state["current_post_index"] = find_next_unfinished_index(posts, progress_by_post, 0)
    st.session_state["current_post_index"] = max(0, min(int(st.session_state["current_post_index"]), total_posts - 1))

    idx = st.session_state["current_post_index"]
    current_post = posts[idx]
    current_progress = progress_by_post.get(current_post["post_id"], {})

    st.markdown(f"### Current post ID: `{current_post['post_id']}`")
    left, right = st.columns(2)
    with left:
        render_post_box("Original post", current_post["original_post"])
    with right:
        render_post_box("Simplified post", current_post["simplified_post"])

    step_answers = load_step_answers(email, current_post["post_id"])
    if step_answers:
        with st.expander("Saved step answers"):
            for answer in step_answers:
                st.write(f"**Step {answer['step_number']}:** {answer['decision']}")

    if current_progress.get("completed"):
        label = current_progress.get("final_label", "")
        reason = current_progress.get("terminal_reason", "")
        if label == "YES":
            st.success(f"Final label already saved: YES — {reason}")
        elif label == "NO":
            st.error(f"Final label already saved: NO — {reason}")
        else:
            st.warning(f"Final label already saved: MAYBE — {reason}")
        st.info("This post is already saved. You can move to the previous or next post without annotating it again.")
        with st.expander("Change this annotation"):
            st.write("This will delete your saved answers for this post only and let you annotate it again.")
            if st.button("Restart this post", type="secondary"):
                reset_one_annotation(email, current_post["post_id"])
                st.rerun()
        st.divider()
        render_post_navigation(idx, total_posts, posts, progress_by_post, email, prefix="bottom_completed")
        return

    current_step = int(current_progress.get("current_step") or 1)
    current_step = max(1, min(current_step, len(STEP_DEFINITIONS)))

    st.divider()
    step = STEP_DEFINITIONS[current_step - 1]
    st.markdown(f"## Step {step['number']}: {step['title']}")
    st.write(step["quick"])

    with st.expander("Show guidance and examples"):
        st.markdown(step["guidance"])

    option_labels = [option["label"] for option in step["options"]]

    with st.form(key=f"form_{email}_{current_post['post_id']}_{current_step}"):
        selected = st.radio("Select one decision", option_labels, index=None)
        comment = st.text_area("Optional comment", placeholder="Add a short explanation if useful.")
        submitted = st.form_submit_button("Save decision and continue", use_container_width=True)

    if submitted:
        if selected is None:
            st.warning("Please select a decision first.")
            return

        option = next(o for o in step["options"] if o["label"] == selected)
        outcome = option["outcome"]
        reason = option["reason"]

        save_step_answer(email, current_post["post_id"], current_step, selected, reason, comment)

        if outcome == "CONTINUE":
            save_progress(email, current_post["post_id"], current_step + 1, False, comment=comment)
            st.success("Saved. Moving to the next step.")
        else:
            save_progress(email, current_post["post_id"], current_step, True, outcome, reason, current_step, comment)
            st.session_state["current_post_index"] = find_next_unfinished_index(posts, get_progress_by_post(load_progress(email)), idx + 1)
        st.rerun()

    if step_answers:
        with st.expander("Undo/restart this post"):
            if st.button("Restart this post from Step 1"):
                reset_one_annotation(email, current_post["post_id"])
                st.rerun()

    st.divider()
    render_post_navigation(idx, total_posts, posts, progress_by_post, email, prefix="bottom")


def admin_page():
    st.title("Researcher Admin")

    expected_password = st.secrets.get("ADMIN_PASSWORD", "")
    password = st.text_input("Admin password", type="password")
    if not expected_password:
        st.error("ADMIN_PASSWORD is missing from Streamlit secrets.")
        return
    if password != expected_password:
        st.info("Enter the admin password to continue.")
        return

    st.success("Admin access granted.")

    tab_upload, tab_dashboard, tab_delete, tab_export = st.tabs(["Uploaded posts", "Dashboard", "Delete annotators", "Export"])

    with tab_upload:
        st.subheader("Upload or update posts")
        st.write("Upload a CSV or XLSX file. Recommended columns: post_id, original_post, simplified_post. You can also map different column names.")
        uploaded_file = st.file_uploader("Upload CSV or XLSX", type=["csv", "xlsx"])

        if uploaded_file:
            df = read_uploaded_dataset(uploaded_file)
            st.write("Preview")
            st.dataframe(df.head(10), use_container_width=True)

            columns = list(df.columns)
            original_guess = guess_column(df, ["original_post", "original", "source", "source_text", "post", "text", "tweet"])
            simplified_guess = guess_column(df, ["simplified_post", "simplified", "target", "target_text", "simplification"])
            id_guess = guess_column(df, ["post_id", "id", "item_id", "row_id"])

            id_options = ["Use row number"] + columns
            default_id_index = id_options.index(id_guess) if id_guess in id_options else 0
            id_choice = st.selectbox("Post ID column", id_options, index=default_id_index)
            id_col = None if id_choice == "Use row number" else id_choice
            original_col = st.selectbox("Original post column", columns, index=columns.index(original_guess) if original_guess in columns else 0)
            simplified_col = st.selectbox("Simplified post column", columns, index=columns.index(simplified_guess) if simplified_guess in columns else min(1, len(columns) - 1))

            replace_existing = st.checkbox("Replace existing posts and delete all existing annotations", value=False)
            if replace_existing:
                st.warning("This will remove all current posts and all saved annotations before importing the new dataset.")

            if original_col == simplified_col:
                st.error("Original and simplified post columns must be different.")
            else:
                if st.button("Import / update posts", type="primary"):
                    count = import_posts_to_supabase(df, id_col, original_col, simplified_col, replace_existing)
                    st.success(f"Imported or updated {count} posts.")
                    st.cache_data.clear()

        posts = load_posts()
        st.subheader("Current posts in database")
        st.write(f"{len(posts)} posts available.")
        if posts:
            posts_df = pd.DataFrame(posts)
            st.dataframe(posts_df.head(50), use_container_width=True)

            st.subheader("Delete old posts")
            st.write("Use this area if you want to remove old tweets/posts from the database.")
            delete_choice = st.radio(
                "What do you want to delete?",
                [
                    "Do not delete anything",
                    "Delete one selected post",
                    "Delete all posts and all annotations",
                ],
                index=0,
            )

            if delete_choice == "Delete one selected post":
                post_options = [f"{p.get('display_order', '')}: {p.get('post_id', '')}" for p in posts]
                selected_post_label = st.selectbox("Select post to delete", post_options)
                selected_post_id = selected_post_label.split(": ", 1)[1]
                st.warning("This will delete this post and any annotations already saved for it.")
                confirm_post = st.text_input("Type the post ID to confirm", key="confirm_delete_one_post")
                if st.button(
                    "Delete selected post",
                    type="primary",
                    disabled=confirm_post.strip() != selected_post_id,
                ):
                    delete_one_post(selected_post_id)
                    st.success(f"Deleted post {selected_post_id} and its annotations.")
                    st.rerun()

            elif delete_choice == "Delete all posts and all annotations":
                st.error("This will permanently delete all uploaded posts and all annotations from Supabase.")
                confirm_all = st.text_input("Type DELETE ALL POSTS to confirm", key="confirm_delete_all_posts")
                if st.button(
                    "Delete all posts and annotations",
                    type="primary",
                    disabled=confirm_all.strip() != "DELETE ALL POSTS",
                ):
                    clear_all_posts_and_annotations()
                    st.success("Deleted all posts and all annotations.")
                    st.rerun()

    with tab_dashboard:
        progress = pd.DataFrame(load_all_progress())

        st.subheader("YES / NO / MAYBE by annotator email")
        by_annotator = make_by_annotator_summary(progress)
        st.dataframe(by_annotator, hide_index=True, use_container_width=True)

        st.subheader("Inter-annotator agreement overview")
        st.write("This compact table helps you see the overall level of agreement across posts.")
        posts_df = pd.DataFrame(load_posts())
        agreement_by_post = make_post_agreement_summary(progress, posts_df)
        agreement_overview = make_agreement_overview(agreement_by_post)
        st.dataframe(agreement_overview, hide_index=True, use_container_width=True)

        st.subheader("Inter-annotator agreement by post")
        st.write("This table shows how many annotators chose YES, NO and MAYBE for each individual post.")
        st.dataframe(agreement_by_post, hide_index=True, use_container_width=True)

        if not by_annotator.empty:
            st.subheader("Individual annotator tables")
            for _, row in by_annotator.iterrows():
                email = row["Annotator email"]
                with st.expander(str(email)):
                    individual = pd.DataFrame(
                        {
                            "Final label": LABELS,
                            "Number": [int(row.get(label, 0)) for label in LABELS],
                        }
                    )
                    total = int(individual["Number"].sum())
                    individual["Percentage"] = individual["Number"].apply(lambda x: round(x / total * 100, 1) if total else 0)
                    st.dataframe(individual, hide_index=True, use_container_width=True)

    with tab_delete:
        st.subheader("Delete annotators")
        st.write("Annotators are stored by email address. Deleting an annotator removes their saved progress and step answers, but keeps the uploaded posts.")
        progress = pd.DataFrame(load_all_progress())
        if progress.empty:
            st.info("There are no annotator results to delete yet.")
        else:
            by_annotator = make_by_annotator_summary(progress)
            st.dataframe(by_annotator, hide_index=True, use_container_width=True)

            emails = sorted(progress["annotator_id"].dropna().unique().tolist())
            selected_email = st.selectbox("Select annotator email to delete", emails)
            selected_row = by_annotator[by_annotator["Annotator email"].eq(selected_email)]
            if not selected_row.empty:
                row = selected_row.iloc[0]
                st.write(
                    f"Selected annotator: **{selected_email}** | "
                    f"YES: **{int(row.get('YES', 0))}** | "
                    f"NO: **{int(row.get('NO', 0))}** | "
                    f"MAYBE: **{int(row.get('MAYBE', 0))}** | "
                    f"Started: **{int(row.get('Total started', 0))}**"
                )

            st.warning(f"This will delete all saved progress and step answers for {selected_email}. It will not delete the posts.")
            confirm = st.text_input("Type the annotator email to confirm deletion")
            if st.button("Delete this annotator", type="primary", disabled=confirm.strip().lower() != selected_email.lower()):
                delete_annotator_results(selected_email)
                st.success(f"Deleted annotator/results for {selected_email}.")
                st.rerun()

    with tab_export:
        st.subheader("Export results")
        st.write("Download all annotations, step answers, the inter-annotator agreement overview, the by-post agreement table and by-annotator summaries as an Excel workbook.")
        export_bytes = build_export()
        st.download_button(
            "Download XLSX results",
            data=export_bytes,
            file_name="meaning_preservation_annotation_results.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def main():
    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Choose page", ["Annotator", "Researcher admin"])
        st.caption("Annotators should use the Annotator page only.")

    if page == "Annotator":
        annotator_page()
    else:
        admin_page()


if __name__ == "__main__":
    main()
