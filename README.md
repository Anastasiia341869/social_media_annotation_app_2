# Meaning Preservation Annotation App — v3.3

This version keeps the inter-annotator agreement by-post table and adds a compact visual overview table like the earlier summary table.

## Dashboard changes

The dashboard now shows:

1. YES / NO / MAYBE by annotator email.
2. Inter-annotator agreement overview:
   - Full agreement
   - Majority agreement
   - No majority
   - Not enough annotations yet
3. Inter-annotator agreement by post, showing how many annotators chose YES, NO and MAYBE for each post.

The old label `Tie` is now displayed as `No majority`.

## Update instructions

Upload the new `app.py` to GitHub, commit the change, then reboot the Streamlit app. You do not need to change Supabase.
