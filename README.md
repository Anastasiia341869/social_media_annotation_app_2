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


## v1.3 fix

Step 1 keeps Yes/No wording:
- Yes: continue to Step 2.
- No: stop this post and save final label as MAYBE: Context unclear.

For Steps 2–6:
- Yes: continue, except final Step 6 Yes saves YES.
- Maybe: continue to the next step.
- No: stop this post and save NO.


## v1.4 fix

Step 1 has only two visible options:
- Yes: continue to Step 2.
- No: stop this post and save the final label as MAYBE: Context unclear.

From Step 2 onwards:
- Yes: continue.
- Maybe: continue.
- No: stop this post.


## v1.5 update

The Researcher admin page now has a clearer Export tab.

The export workbook includes:
- Summary by student
- Overall label summary
- All students vs gold standard
- Student progress
- All step answers
- Gold standard
- Posts


## v1.6 update

The visible app name and browser tab title are now:

Social Media Annotation
