"""Second Brain — closed-loop adaptive medical learning system.

Pipeline:
    Authoritative sources -> NotebookLM -> Knowledge Units + Cards/MCQs
    -> AnkiConnect -> Anki/FSRS -> performance data
    -> Claude (error diagnosis) -> Cumulative Weakness Profile
    -> Source localization -> Targeted re-study -> Adaptive questions
    -> Mastery -> Notion.

Author of the project: Dr Erfan Alinejad Ghadi — Iran Medical Council No. 219890
"""

__version__ = "0.1.0"
