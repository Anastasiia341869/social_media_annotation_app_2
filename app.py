
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
    page_title="Student Meaning Preservation Annotation",
    page_icon="📝",
    layout="wide",
)

APP_TITLE = "Student Meaning Preservation Annotation"
GOLD_STANDARD_LABEL = "gold standard"
DEFAULT_GOLD_EMAIL = "ab04237@surrey.ac.uk"
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

Example:

Original: “The council rejected our application.”  
Simplified: “The council is considering our application.”

The outcome has changed. This is **NO: Core meaning changed**.
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

Example:

Original: “Fantastic. Another cancelled train.”  
Simplified: “The writer is happy that another train was cancelled.”

The sarcasm has been misunderstood. This is **NO: Non-literal meaning lost**.
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
Example:

Original: “Great 🙄”  
Simplified: “That is great.”

The eye-roll emoji showed sarcasm, so the meaning has changed. This is **NO: Social media meaning changed**.

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

Example:

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
        "The app could not read posts from Supabase. Check that the tables exist and that Streamlit secrets use the correct Supabase project.",
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


def load_student_steps(email: str) -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = safe_execute(
        client.table("step_answers")
        .select("*")
        .eq("annotator_id", email)
        .order("post_id")
        .order("step_number"),
        "The app could not read saved step answers from Supabase.",
    )
    return response.data or []


def load_gold_standard() -> list[dict[str, Any]]:
    client = get_supabase_client()
    response = safe_execute(
        client.table("gold_standard").select("*"),
        "The app could not read the gold standard table from Supabase.",
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


def clear_all_posts_annotations_and_gold() -> None:
    client = get_supabase_client()
    safe_execute(client.table("step_answers").delete().neq("id", -1), "Could not clear step answers.")
    safe_execute(client.table("annotation_progress").delete().neq("id", -1), "Could not clear annotation progress.")
    safe_execute(client.table("gold_standard").delete().neq("post_id", "__never__"), "Could not clear gold standard.")
    safe_execute(client.table("posts").delete().neq("post_id", "__never__"), "Could not clear posts.")
    st.cache_data.clear()


def clear_student_annotations() -> None:
    client = get_supabase_client()
    safe_execute(client.table("step_answers").delete().neq("id", -1), "Could not clear step answers.")
    safe_execute(client.table("annotation_progress").delete().neq("id", -1), "Could not clear annotation progress.")
    st.cache_data.clear()


# -----------------------------
# Data import
# -----------------------------

def read_uploaded_dataset(uploaded_file, preferred_sheet: str | None = None) -> pd.DataFrame:
    name = uploaded_file.name.lower()
    if name.endswith(".csv"):
        return pd.read_csv(uploaded_file)

    sheets = pd.read_excel(uploaded_file, sheet_name=None)
    if preferred_sheet and preferred_sheet in sheets:
        return sheets[preferred_sheet]
    if "Annotations" in sheets:
        return sheets["Annotations"]
    return next(iter(sheets.values()))


def guess_column(df: pd.DataFrame, candidates: list[str]) -> str:
    normalised = {str(col).strip().lower().replace(" ", "_"): col for col in df.columns}
    for candidate in candidates:
        key = candidate.strip().lower().replace(" ", "_")
        if key in normalised:
            return normalised[key]
    return df.columns[0]


def clean_post_text(original: str, simplified: str) -> tuple[str, str]:
    original = "" if pd.isna(original) else str(original)
    simplified = "" if pd.isna(simplified) else str(simplified)

    # Fix accidental tab-merged rows where the original cell contains both original and simplified text.
    if "\t" in original:
        parts = original.split("\t")
        if len(parts) >= 2 and simplified.strip() and simplified.strip() in "\t".join(parts[1:]).strip():
            original = parts[0]

    return original.strip(), simplified.strip()


def import_posts_to_supabase(df: pd.DataFrame, id_col: str | None, original_col: str, simplified_col: str, replace_existing: bool) -> int:
    if replace_existing:
        clear_all_posts_annotations_and_gold()

    client = get_supabase_client()
    records: list[dict[str, Any]] = []
    seen: set[str] = set()

    for index, row in df.iterrows():
        if id_col:
            post_id = str(row[id_col]).strip()
        else:
            post_id = str(index + 1)

        if not post_id or post_id.lower() == "nan":
            post_id = str(index + 1)

        if post_id in seen:
            post_id = f"{post_id}_{index + 1}"
        seen.add(post_id)

        original, simplified = clean_post_text(row[original_col], row[simplified_col])
        if original and simplified:
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


def normalise_text_for_match(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def import_gold_standard_to_supabase(df: pd.DataFrame, gold_email: str) -> tuple[int, int]:
    posts = load_posts()
    if not posts:
        return 0, 0

    working = df.copy()
    working.columns = [str(c).strip() for c in working.columns]

    if "annotator_email" in working.columns:
        email_series = working["annotator_email"].astype(str).str.strip().str.lower()
        target_email = gold_email.strip().lower()
        gold_label = GOLD_STANDARD_LABEL.lower()
        if email_series.eq(target_email).any():
            working = working[email_series.eq(target_email)].copy()
        elif email_series.eq(gold_label).any():
            working = working[email_series.eq(gold_label)].copy()
        # Otherwise, leave the file unchanged and treat all rows as gold-standard rows.

    if working.empty:
        return 0, len(posts)

    by_original = {}
    if "original_post" in working.columns:
        for _, row in working.iterrows():
            by_original[normalise_text_for_match(row.get("original_post"))] = row

    by_post_id = {}
    if "post_id" in working.columns:
        for _, row in working.iterrows():
            by_post_id[str(row.get("post_id")).strip()] = row

    records: list[dict[str, Any]] = []
    missing = 0

    for post in posts:
        match = by_post_id.get(str(post.get("post_id", "")).strip())
        if match is None:
            match = by_original.get(normalise_text_for_match(post.get("original_post")))

        if match is None:
            missing += 1
            continue

        rec = {
            "post_id": post["post_id"],
            "annotator_label": GOLD_STANDARD_LABEL,
            "final_label": str(match.get("final_label", "") or "").upper(),
            "terminal_reason": str(match.get("terminal_reason", "") or ""),
            "terminal_step": int(match.get("terminal_step")) if str(match.get("terminal_step", "")).strip().isdigit() else None,
            "updated_at": utc_now(),
        }
        for step in range(1, 7):
            rec[f"step_{step}_decision"] = str(match.get(f"step_{step}_decision", "") or "")
            rec[f"step_{step}_reason"] = str(match.get(f"step_{step}_reason", "") or "")
        records.append(rec)

    if records:
        client = get_supabase_client()
        for start in range(0, len(records), 500):
            safe_execute(
                client.table("gold_standard").upsert(records[start : start + 500], on_conflict="post_id"),
                "The app could not import the gold standard into Supabase.",
            )

    st.cache_data.clear()
    return len(records), missing


# -----------------------------
# Summaries and export
# -----------------------------

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


def make_by_student_summary(progress_df: pd.DataFrame) -> pd.DataFrame:
    columns = ["Student email", "YES", "NO", "MAYBE", "Total completed", "Total started"]
    if progress_df.empty:
        return pd.DataFrame(columns=columns)

    completed = progress_df[progress_df["completed"].eq(True)]
    if completed.empty:
        started = progress_df.groupby("annotator_id")["post_id"].count().reset_index(name="Total started")
        started = started.rename(columns={"annotator_id": "Student email"})
        for label in LABELS:
            started[label] = 0
        started["Total completed"] = 0
        return started[columns]

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
    out = out.rename(columns={"annotator_id": "Student email"})
    return out[columns].sort_values("Student email")


def pivot_student_steps(steps_df: pd.DataFrame) -> pd.DataFrame:
    if steps_df.empty:
        base = pd.DataFrame(columns=["annotator_email", "post_id"])
        return base

    steps_df = steps_df.copy()
    steps_df = steps_df.rename(columns={"annotator_id": "annotator_email"})
    pivot_decisions = steps_df.pivot_table(index=["annotator_email", "post_id"], columns="step_number", values="decision", aggfunc="last")
    pivot_decisions.columns = [f"student_step_{int(c)}_decision" for c in pivot_decisions.columns]
    pivot_decisions = pivot_decisions.reset_index()

    pivot_reasons = steps_df.pivot_table(index=["annotator_email", "post_id"], columns="step_number", values="reason", aggfunc="last")
    pivot_reasons.columns = [f"student_step_{int(c)}_reason" for c in pivot_reasons.columns]
    pivot_reasons = pivot_reasons.reset_index()

    return pivot_decisions.merge(pivot_reasons, how="outer", on=["annotator_email", "post_id"])


def build_student_comparison_df(email: str) -> pd.DataFrame:
    posts = pd.DataFrame(load_posts())
    progress = pd.DataFrame(load_progress(email))
    steps = pd.DataFrame(load_student_steps(email))
    gold = pd.DataFrame(load_gold_standard())

    if posts.empty:
        return pd.DataFrame()

    if progress.empty:
        progress = pd.DataFrame(columns=["annotator_id", "post_id", "completed", "final_label", "terminal_reason", "terminal_step", "comment"])
    if steps.empty:
        steps = pd.DataFrame(columns=["annotator_id", "post_id", "step_number", "decision", "reason", "comment"])
    if gold.empty:
        gold = pd.DataFrame(columns=["post_id", "annotator_label", "final_label", "terminal_reason", "terminal_step"])

    base = posts[["display_order", "post_id", "original_post", "simplified_post"]].copy()
    base = base.rename(columns={"display_order": "Post number", "post_id": "post_id"})

    student = progress[progress["annotator_id"].eq(email)].copy() if "annotator_id" in progress.columns else progress
    student = student.rename(
        columns={
            "annotator_id": "student_email",
            "final_label": "student_final_label",
            "terminal_reason": "student_reason",
            "terminal_step": "student_terminal_step",
            "comment": "student_comment",
        }
    )
    keep_student = [c for c in ["student_email", "post_id", "completed", "student_final_label", "student_reason", "student_terminal_step", "student_comment"] if c in student.columns]
    student = student[keep_student] if keep_student else pd.DataFrame(columns=["post_id"])

    out = base.merge(student, how="left", on="post_id")

    student_steps = pivot_student_steps(steps)
    if not student_steps.empty:
        out = out.merge(student_steps, how="left", left_on=["student_email", "post_id"], right_on=["annotator_email", "post_id"])
        out = out.drop(columns=["annotator_email"], errors="ignore")

    gold = gold.rename(
        columns={
            "annotator_label": "gold_standard_name",
            "final_label": "gold_standard_final_label",
            "terminal_reason": "gold_standard_reason",
            "terminal_step": "gold_standard_terminal_step",
        }
    )
    for step in range(1, 7):
        gold = gold.rename(
            columns={
                f"step_{step}_decision": f"gold_step_{step}_decision",
                f"step_{step}_reason": f"gold_step_{step}_reason",
            }
        )

    gold_cols = [c for c in gold.columns if c == "post_id" or c.startswith("gold_")]
    if gold_cols:
        out = out.merge(gold[gold_cols], how="left", on="post_id")

    out["student_email"] = out["student_email"].fillna(email)
    out["gold_standard_name"] = GOLD_STANDARD_LABEL
    out["label_match"] = out.apply(
        lambda r: "YES" if str(r.get("student_final_label", "")).upper() == str(r.get("gold_standard_final_label", "")).upper() and str(r.get("student_final_label", "")).strip() else "NO",
        axis=1,
    )

    # Order the most important columns first.
    ordered = [
        "Post number",
        "post_id",
        "original_post",
        "simplified_post",
        "student_email",
        "student_final_label",
        "gold_standard_name",
        "gold_standard_final_label",
        "label_match",
        "student_reason",
        "gold_standard_reason",
        "student_terminal_step",
        "gold_standard_terminal_step",
    ]
    for step in range(1, 7):
        ordered.append(f"student_step_{step}_decision")
        ordered.append(f"gold_step_{step}_decision")
    for step in range(1, 7):
        ordered.append(f"student_step_{step}_reason")
        ordered.append(f"gold_step_{step}_reason")
    ordered = [c for c in ordered if c in out.columns]
    extras = [c for c in out.columns if c not in ordered]
    return out[ordered + extras].sort_values("Post number")


def build_student_export(email: str) -> bytes:
    comparison = build_student_comparison_df(email)
    progress = pd.DataFrame(load_progress(email))
    summary = make_label_summary(progress)

    output = BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        comparison.to_excel(writer, sheet_name="Student vs gold standard", index=False)
        summary.to_excel(writer, sheet_name="Student summary", index=False)

        workbook = writer.book
        header = workbook.add_format({"bold": True, "bg_color": "#2F5597", "font_color": "white", "border": 1, "text_wrap": True})
        wrap = workbook.add_format({"text_wrap": True, "valign": "top"})

        for sheet_name, data in {"Student vs gold standard": comparison, "Student summary": summary}.items():
            ws = writer.sheets[sheet_name]
            for col_num, value in enumerate(data.columns):
                ws.write(0, col_num, value, header)
            ws.freeze_panes(1, 0)
            ws.autofilter(0, 0, max(len(data), 1), max(len(data.columns) - 1, 0))
            ws.set_column(0, max(len(data.columns) - 1, 0), 22, wrap)
            if sheet_name == "Student vs gold standard":
                ws.set_column(2, 3, 45, wrap)
                ws.set_column(4, 10, 24, wrap)

    return output.getvalue()


def build_admin_export() -> bytes:
    posts = pd.DataFrame(load_posts())
    progress = pd.DataFrame(load_all_progress())
    gold = pd.DataFrame(load_gold_standard())

    if posts.empty:
        posts = pd.DataFrame(columns=["post_id", "display_order", "original_post", "simplified_post"])
    if progress.empty:
        progress = pd.DataFrame(columns=["annotator_id", "post_id", "completed", "final_label", "terminal_reason"])
    if gold.empty:
        gold = pd.DataFrame(columns=["post_id", "annotator_label", "final_label", "terminal_reason"])

    by_student = make_by_student_summary(progress)
    output = BytesIO()
    progress_export = progress.rename(columns={"annotator_id": "student_email"})

    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        posts.to_excel(writer, sheet_name="Posts", index=False)
        progress_export.to_excel(writer, sheet_name="Student progress", index=False)
        gold.to_excel(writer, sheet_name="Gold standard", index=False)
        by_student.to_excel(writer, sheet_name="By student", index=False)

        workbook = writer.book
        header = workbook.add_format({"bold": True, "bg_color": "#2F5597", "font_color": "white", "border": 1, "text_wrap": True})
        wrap = workbook.add_format({"text_wrap": True, "valign": "top"})
        sheet_data = {"Posts": posts, "Student progress": progress_export, "Gold standard": gold, "By student": by_student}
        for sheet_name, data in sheet_data.items():
            ws = writer.sheets[sheet_name]
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
    if total_posts <= 0:
        st.session_state["current_post_index"] = 0
    else:
        st.session_state["current_post_index"] = max(0, min(int(index), total_posts - 1))


def render_post_navigation(idx: int, total_posts: int, email: str, post_id: str, prefix: str) -> None:
    left, right = st.columns(2)
    with left:
        st.button(
            "← Previous post",
            disabled=idx <= 0,
            use_container_width=True,
            key=f"{prefix}_previous_{email}_{post_id}_{idx}",
            on_click=set_current_post_index,
            args=(idx - 1, total_posts),
        )
    with right:
        st.button(
            "Next post →",
            disabled=idx >= total_posts - 1,
            use_container_width=True,
            key=f"{prefix}_next_{email}_{post_id}_{idx}",
            on_click=set_current_post_index,
            args=(idx + 1, total_posts),
        )


def final_label_from_steps(step_answers: list[dict[str, Any]], current_outcome: str, current_reason: str, current_step: int) -> tuple[str, str, int]:
    """Final label when Step 6 is reached.

    NO stops immediately. MAYBE continues, but if any step has a MAYBE and no later NO,
    the final post label becomes MAYBE.
    """
    if current_outcome == "NO":
        return "NO", current_reason, current_step
    if current_outcome == "MAYBE":
        return "MAYBE", current_reason, current_step

    # Step 6 selected the YES-preserving option. Check whether any earlier step was Maybe.
    maybe_answers = [a for a in step_answers if str(a.get("decision", "")).strip().lower().startswith("maybe")]
    if maybe_answers:
        first = sorted(maybe_answers, key=lambda x: int(x.get("step_number", 999)))[0]
        return "MAYBE", str(first.get("reason") or "Earlier uncertainty"), int(first.get("step_number") or current_step)

    return "YES", "Meaning preserved", current_step


# -----------------------------
# Pages
# -----------------------------

def annotator_page():
    st.title(APP_TITLE)
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

    session_email_key = "active_student_email"
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

    st.markdown(f"### Post {idx + 1} of {total_posts}")
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
        render_post_navigation(idx, total_posts, email, current_post["post_id"], prefix="completed")
    else:
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

            if outcome == "NO":
                save_progress(email, current_post["post_id"], current_step, True, "NO", reason, current_step, comment)
                st.session_state["current_post_index"] = find_next_unfinished_index(posts, get_progress_by_post(load_progress(email)), idx + 1)
            elif current_step < len(STEP_DEFINITIONS):
                # Important difference from the previous app: MAYBE continues instead of stopping.
                save_progress(email, current_post["post_id"], current_step + 1, False, comment=comment)
                st.success("Saved. Moving to the next step.")
            else:
                all_answers = load_step_answers(email, current_post["post_id"])
                final_label, final_reason, final_step = final_label_from_steps(all_answers, outcome, reason, current_step)
                save_progress(email, current_post["post_id"], current_step, True, final_label, final_reason, final_step, comment)
                st.session_state["current_post_index"] = find_next_unfinished_index(posts, get_progress_by_post(load_progress(email)), idx + 1)
            st.rerun()

        if step_answers:
            with st.expander("Undo/restart this post"):
                if st.button("Restart this post from Step 1"):
                    reset_one_annotation(email, current_post["post_id"])
                    st.rerun()

        st.divider()
        render_post_navigation(idx, total_posts, email, current_post["post_id"], prefix="bottom")

    # Show the export only after the student has completed all posts.
    # This keeps the interface simple and makes the export feel like the final step.
    if completed_count >= total_posts:
        st.divider()
        st.success("You have completed all posts.")
        st.subheader("Export your table")
        st.write("This downloads a table with only your results and the gold standard results.")
        gold_count = len(load_gold_standard())
        if gold_count == 0:
            st.warning("The gold standard has not been uploaded yet, so the comparison columns will be empty.")
        st.download_button(
            "Download my comparison with gold standard",
            data=build_student_export(email),
            file_name=f"student_gold_standard_comparison_{email.replace('@', '_at_')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
        remaining = total_posts - completed_count
        st.caption(f"The export button will appear after you finish all posts. Remaining posts: {remaining}.")


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

    tab_posts, tab_gold, tab_dashboard, tab_delete, tab_export = st.tabs(
        ["Uploaded posts", "Gold standard", "Dashboard", "Delete students", "Export"]
    )

    with tab_posts:
        st.subheader("Upload the 40 student posts")
        st.write("Upload `tweets_for_students_clean.csv` or the original XLSX file. Recommended columns: `post_id`, `text`, `simplified`.")
        uploaded_file = st.file_uploader("Upload posts CSV or XLSX", type=["csv", "xlsx"], key="posts_upload")

        if uploaded_file:
            df = read_uploaded_dataset(uploaded_file)
            st.write("Preview")
            st.dataframe(df.head(10), use_container_width=True)

            columns = list(df.columns)
            original_guess = guess_column(df, ["text", "original_post", "original", "source", "post", "tweet"])
            simplified_guess = guess_column(df, ["simplified", "simplified_post", "target", "simplification"])
            id_guess = guess_column(df, ["post_id", "id", "item_id", "row_id"])

            id_options = ["Use row number"] + columns
            default_id_index = id_options.index(id_guess) if id_guess in id_options else 0
            id_choice = st.selectbox("Post ID column", id_options, index=default_id_index)
            id_col = None if id_choice == "Use row number" else id_choice
            original_col = st.selectbox("Original post column", columns, index=columns.index(original_guess) if original_guess in columns else 0)
            simplified_col = st.selectbox("Simplified post column", columns, index=columns.index(simplified_guess) if simplified_guess in columns else min(1, len(columns) - 1))
            replace_existing = st.checkbox("Replace existing posts, gold standard and student annotations", value=False)

            if original_col == simplified_col:
                st.error("Original and simplified post columns must be different.")
            else:
                if st.button("Import posts", type="primary"):
                    count = import_posts_to_supabase(df, id_col, original_col, simplified_col, replace_existing)
                    st.success(f"Imported or updated {count} posts.")
                    st.cache_data.clear()

        posts = load_posts()
        st.subheader("Current posts in database")
        st.write(f"{len(posts)} posts available.")
        if posts:
            st.dataframe(pd.DataFrame(posts).head(50), use_container_width=True)

    with tab_gold:
        st.subheader("Upload gold standard results")
        st.write(
            "Upload the previous results workbook or `gold_standard_for_students.csv`. "
            "Rows from `ab04237@surrey.ac.uk` will be imported as `gold standard`."
        )
        gold_email = st.text_input("Email to treat as gold standard", value=DEFAULT_GOLD_EMAIL)
        gold_file = st.file_uploader("Upload gold standard CSV or XLSX", type=["csv", "xlsx"], key="gold_upload")

        if gold_file:
            df = read_uploaded_dataset(gold_file, preferred_sheet="Annotations")
            st.write("Preview")
            st.dataframe(df.head(10), use_container_width=True)
            if st.button("Import gold standard", type="primary"):
                imported, missing = import_gold_standard_to_supabase(df, gold_email)
                st.success(f"Imported {imported} gold standard rows.")
                if missing:
                    st.warning(f"{missing} uploaded posts could not be matched to the gold standard file.")
                st.cache_data.clear()

        gold = load_gold_standard()
        st.subheader("Current gold standard")
        st.write(f"{len(gold)} gold standard rows available.")
        if gold:
            st.dataframe(pd.DataFrame(gold).head(50), use_container_width=True)

    with tab_dashboard:
        posts = load_posts()
        gold = load_gold_standard()
        progress = pd.DataFrame(load_all_progress())

        col1, col2, col3 = st.columns(3)
        col1.metric("Posts", len(posts))
        col2.metric("Gold standard rows", len(gold))
        col3.metric("Student annotations", int(progress["completed"].sum()) if not progress.empty and "completed" in progress.columns else 0)

        st.subheader("YES / NO / MAYBE by student")
        by_student = make_by_student_summary(progress)
        st.dataframe(by_student, hide_index=True, use_container_width=True)

        if not by_student.empty:
            st.subheader("Individual student tables")
            for _, row in by_student.iterrows():
                email = row["Student email"]
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
        st.subheader("Delete student results")
        progress = pd.DataFrame(load_all_progress())
        if progress.empty:
            st.info("There are no student results to delete yet.")
        else:
            by_student = make_by_student_summary(progress)
            st.dataframe(by_student, hide_index=True, use_container_width=True)
            emails = sorted(progress["annotator_id"].dropna().unique().tolist())
            selected_email = st.selectbox("Select student email to delete", emails)
            st.warning(f"This will delete all saved progress and step answers for {selected_email}. It will not delete posts or the gold standard.")
            confirm = st.text_input("Type the student email to confirm deletion")
            if st.button("Delete this student", type="primary", disabled=confirm.strip().lower() != selected_email.lower()):
                delete_annotator_results(selected_email)
                st.success(f"Deleted results for {selected_email}.")
                st.rerun()

        st.divider()
        st.subheader("Delete all student annotations")
        st.write("This keeps the posts and gold standard but removes all student answers.")
        confirm_all = st.text_input("Type DELETE STUDENT RESULTS to confirm", key="delete_all_students_confirm")
        if st.button("Delete all student results", type="primary", disabled=confirm_all.strip() != "DELETE STUDENT RESULTS"):
            clear_student_annotations()
            st.success("Deleted all student annotations.")
            st.rerun()

    with tab_export:
        st.subheader("Export admin workbook")
        st.write("Download posts, student progress, gold standard and by-student summary.")
        st.download_button(
            "Download admin XLSX",
            data=build_admin_export(),
            file_name="student_annotation_admin_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )


def main():
    with st.sidebar:
        st.header("Navigation")
        page = st.radio("Choose page", ["Student annotation", "Researcher admin"])
        st.caption("Students should use the Student annotation page only.")

    if page == "Student annotation":
        annotator_page()
    else:
        admin_page()


if __name__ == "__main__":
    main()
