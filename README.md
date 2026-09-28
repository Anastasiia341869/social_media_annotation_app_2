# Student Meaning Preservation Annotation App

This is a second Streamlit + Supabase app for students.

## Main differences from the previous app

- The app uses 40 social media posts.
- It uses the same six-step decision tree.
- If a student chooses MAYBE, the decision tree continues instead of stopping.
- NO still stops the annotation for that post.
- At the end, a student can export a table containing only:
  - the student's results;
  - the gold standard results.
- The gold-standard annotator is shown as `gold standard`, not as an email address.

## GitHub files

Upload these files to the new GitHub repository:

- app.py
- requirements.txt
- runtime.txt
- README.md

Do not upload Supabase keys or passwords to GitHub.

## Supabase setup

In the new Supabase project, run:

- supabase_clean_reset_student_app.sql

This creates the required tables:

- posts
- annotation_progress
- step_answers
- gold_standard

## Streamlit secrets

In Streamlit → Manage app → Settings → Secrets:

SUPABASE_URL = "https://your-new-project.supabase.co"
SUPABASE_KEY = "your-new-supabase-key"
ADMIN_PASSWORD = "your-admin-password"

## Upload data through the app

After deployment:

1. Go to Researcher admin.
2. Upload `tweets_for_students_clean.csv` in the Uploaded posts tab.
3. Upload `gold_standard_for_students.csv` in the Gold standard tab.
4. Test with a student email.

The student export will then compare student annotations against the gold standard.
