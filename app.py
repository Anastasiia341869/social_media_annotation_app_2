
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
