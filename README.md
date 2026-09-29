# Student Meaning Preservation Annotation App

This is a second Streamlit + Supabase app for students.

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


## Upload data through the app

After deployment:

1. Go to Researcher admin.
2. Upload `tweets_for_students_clean.csv` in the Uploaded posts tab.
3. Upload `gold_standard_for_students.csv` in the Gold standard tab.
4. Test with a student email.

The student export will then compare student annotations against the gold standard.


## this version 

The Researcher admin page now has a clearer Export tab.

The export workbook includes:
- Summary by student
- Overall label summary
- All students vs gold standard
- Student progress
- All step answers
- Gold standard
- Posts


